"""API tests for ICP segment endpoints.

These tests exercise the FastAPI routes without Redis, RQ workers, or a real
database. The database dependency is overridden with a small async fake that
returns SQLAlchemy-like result objects in call order.
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator, Iterator, Sequence
from contextlib import contextmanager
from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest
from httpx import AsyncClient

from app.db import get_db
from app.main import app
from app.workers.tasks import task_run_icps


class _ScalarList:
    def __init__(self, values: Sequence[object]) -> None:
        self._values = list(values)

    def all(self) -> list[object]:
        return self._values


class _ExecuteResult:
    def __init__(
        self,
        *,
        scalar: object | None = None,
        scalars: Sequence[object] = (),
    ) -> None:
        self._scalar = scalar
        self._scalars = list(scalars)

    def scalar_one_or_none(self) -> object | None:
        return self._scalar

    def scalars(self) -> _ScalarList:
        return _ScalarList(self._scalars)


class _FakeDbSession:
    def __init__(self, results: Sequence[_ExecuteResult]) -> None:
        self._results = list(results)
        self.executed: list[object] = []

    async def execute(self, statement: object) -> _ExecuteResult:
        self.executed.append(statement)
        if not self._results:
            raise AssertionError("Unexpected database execute call")
        return self._results.pop(0)


@contextmanager
def _override_db(results: Sequence[_ExecuteResult]) -> Iterator[_FakeDbSession]:
    session = _FakeDbSession(results)

    async def _get_test_db() -> AsyncIterator[_FakeDbSession]:
        yield session

    app.dependency_overrides[get_db] = _get_test_db
    try:
        yield session
    finally:
        app.dependency_overrides.pop(get_db, None)


def _job(
    *,
    queued: bool = False,
    started: bool = False,
    finished: bool = False,
    failed: bool = False,
    result: object | None = None,
    exc_info: str | None = None,
) -> MagicMock:
    mock_job = MagicMock()
    mock_job.is_queued = queued
    mock_job.is_started = started
    mock_job.is_finished = finished
    mock_job.is_failed = failed
    mock_job.result = result
    mock_job.exc_info = exc_info
    return mock_job


class TestCreateICPsEndpoint:
    """Tests for POST /api/v1/snapshots/{snapshot_id}/icps."""

    @pytest.mark.asyncio
    async def test_returns_202_with_job_id(self, client: AsyncClient) -> None:
        snapshot_id = uuid.uuid4()
        mock_job = MagicMock()
        mock_job.id = "test-job-123"
        mock_queue = MagicMock()
        mock_queue.enqueue.return_value = mock_job

        with (
            _override_db([
                _ExecuteResult(scalar=snapshot_id),  # snapshot lookup
                _ExecuteResult(scalar=None),          # simulation cells check (none exist)
            ]),
            patch("app.api.v1.segments._get_queue", return_value=mock_queue),
        ):
            response = await client.post(f"/api/v1/snapshots/{snapshot_id}/icps")

        assert response.status_code == 202
        body = response.json()
        assert body == {
            "job_id": "test-job-123",
            "status_url": "http://localhost:8000/api/v1/icps/jobs/test-job-123",
        }
        mock_queue.enqueue.assert_called_once_with(
            task_run_icps,
            str(snapshot_id),
            job_timeout="5m",
        )

    @pytest.mark.asyncio
    async def test_returns_404_for_nonexistent_snapshot(self, client: AsyncClient) -> None:
        snapshot_id = uuid.uuid4()
        mock_queue = MagicMock()

        with (
            _override_db([_ExecuteResult(scalar=None)]),
            patch("app.api.v1.segments._get_queue", return_value=mock_queue),
        ):
            response = await client.post(f"/api/v1/snapshots/{snapshot_id}/icps")

        assert response.status_code == 404
        assert "not found" in response.json()["detail"].lower()
        mock_queue.enqueue.assert_not_called()


class TestGetSegmentsEndpoint:
    """Tests for GET /api/v1/snapshots/{snapshot_id}/segments."""

    @pytest.mark.asyncio
    async def test_returns_empty_list_before_pipeline_runs(self, client: AsyncClient) -> None:
        snapshot_id = uuid.uuid4()

        with _override_db(
            [
                _ExecuteResult(scalar=snapshot_id),
                _ExecuteResult(scalars=[]),
            ]
        ):
            response = await client.get(f"/api/v1/snapshots/{snapshot_id}/segments")

        assert response.status_code == 200
        assert response.json() == []

    @pytest.mark.asyncio
    async def test_returns_segments_with_nested_evidence(self, client: AsyncClient) -> None:
        snapshot_id = uuid.uuid4()
        evidence_id = uuid.uuid4()
        segment_id = uuid.uuid4()
        captured_at = datetime(2024, 1, 1, tzinfo=UTC)

        evidence = SimpleNamespace(
            id=evidence_id,
            quote="Linear helps us keep issue tracking fast.",
            source="reddit.com (Reddit)",
            source_url="https://reddit.com/r/startups/comments/example",
            kind="reddit",
            captured_at=captured_at,
        )
        segment = SimpleNamespace(
            id=segment_id,
            name="Engineering teams",
            descriptor="Teams coordinating product work across projects.",
            job_to_be_done="Keep issue tracking and planning in one fast workflow.",
            share_pct=42,
            confidence="medium",
            drivers=[{"label": "Speed", "weight": 0.8}],
            leaves="Slow workflows or weak integrations.",
            evidence=[evidence],
        )

        with _override_db(
            [
                _ExecuteResult(scalar=snapshot_id),
                _ExecuteResult(scalars=[segment]),
            ]
        ):
            response = await client.get(f"/api/v1/snapshots/{snapshot_id}/segments")

        assert response.status_code == 200
        body = response.json()
        assert len(body) == 1
        assert body[0]["id"] == str(segment_id)
        assert body[0]["confidence"] == "medium"
        assert body[0]["drivers"] == [{"label": "Speed", "weight": 0.8}]
        assert body[0]["evidence"] == [
            {
                "id": str(evidence_id),
                "quote": "Linear helps us keep issue tracking fast.",
                "source": "reddit.com (Reddit)",
                "source_url": "https://reddit.com/r/startups/comments/example",
                "kind": "reddit",
                "captured_at": "2024-01-01T00:00:00Z",
            }
        ]

    @pytest.mark.asyncio
    async def test_returns_404_for_nonexistent_snapshot(self, client: AsyncClient) -> None:
        snapshot_id = uuid.uuid4()

        with _override_db([_ExecuteResult(scalar=None)]):
            response = await client.get(f"/api/v1/snapshots/{snapshot_id}/segments")

        assert response.status_code == 404
        assert "not found" in response.json()["detail"].lower()


class TestGetICPJobStatusEndpoint:
    """Tests for GET /api/v1/icps/jobs/{job_id}."""

    @pytest.mark.asyncio
    async def test_returns_404_for_nonexistent_job(self, client: AsyncClient) -> None:
        with (
            patch("app.api.v1.segments._get_queue", return_value=MagicMock()),
            patch("app.api.v1.segments.Job.fetch", side_effect=Exception("missing")),
        ):
            response = await client.get("/api/v1/icps/jobs/nonexistent-job-id")

        assert response.status_code == 404
        assert "not found" in response.json()["detail"].lower()

    @pytest.mark.asyncio
    async def test_returns_queued_status(self, client: AsyncClient) -> None:
        with (
            patch("app.api.v1.segments._get_queue", return_value=MagicMock()),
            patch(
                "app.api.v1.segments.Job.fetch",
                return_value=_job(queued=True),
            ),
        ):
            response = await client.get("/api/v1/icps/jobs/test-job-id")

        assert response.status_code == 200
        assert response.json() == {"status": "queued", "segment_ids": None, "error": None}

    @pytest.mark.asyncio
    async def test_returns_started_status(self, client: AsyncClient) -> None:
        with (
            patch("app.api.v1.segments._get_queue", return_value=MagicMock()),
            patch(
                "app.api.v1.segments.Job.fetch",
                return_value=_job(started=True),
            ),
        ):
            response = await client.get("/api/v1/icps/jobs/test-job-id")

        assert response.status_code == 200
        assert response.json() == {"status": "started", "segment_ids": None, "error": None}

    @pytest.mark.asyncio
    async def test_returns_finished_with_segment_ids(self, client: AsyncClient) -> None:
        segment_ids = [uuid.uuid4(), uuid.uuid4()]

        with (
            patch("app.api.v1.segments._get_queue", return_value=MagicMock()),
            patch(
                "app.api.v1.segments.Job.fetch",
                return_value=_job(finished=True, result=[str(i) for i in segment_ids]),
            ),
        ):
            response = await client.get("/api/v1/icps/jobs/test-job-id")

        assert response.status_code == 200
        assert response.json() == {
            "status": "finished",
            "segment_ids": [str(i) for i in segment_ids],
            "error": None,
        }

    @pytest.mark.asyncio
    async def test_returns_failed_with_error(self, client: AsyncClient) -> None:
        with (
            patch("app.api.v1.segments._get_queue", return_value=MagicMock()),
            patch(
                "app.api.v1.segments.Job.fetch",
                return_value=_job(failed=True, exc_info="Test error message"),
            ),
        ):
            response = await client.get("/api/v1/icps/jobs/test-job-id")

        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "failed"
        assert data["segment_ids"] is None
        assert "Test error" in data["error"]


class TestOpenAPISchema:
    """Tests for OpenAPI schema updates."""

    @pytest.mark.asyncio
    async def test_openapi_includes_icp_schemas(self, client: AsyncClient) -> None:
        response = await client.get("/openapi.json")

        assert response.status_code == 200
        schema_names = response.json()["components"]["schemas"]

        assert "ICPJobResponse" in schema_names
        assert "ICPJobStatus" in schema_names
        assert "SegmentRead" in schema_names

    @pytest.mark.asyncio
    async def test_openapi_includes_segment_endpoints(self, client: AsyncClient) -> None:
        response = await client.get("/openapi.json")

        assert response.status_code == 200
        paths = response.json()["paths"]

        assert "/api/v1/snapshots/{snapshot_id}/icps" in paths
        assert "/api/v1/snapshots/{snapshot_id}/segments" in paths
        assert "/api/v1/icps/jobs/{job_id}" in paths
