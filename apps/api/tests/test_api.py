"""API surface tests.

What we check in Step 1:
  1. /health responds with the expected schema.
  2. /snapshots returns async job metadata.
  3. Schema validation rejects malformed bodies before reaching the stub.
"""

from unittest.mock import MagicMock, patch

import pytest
from httpx import AsyncClient


@pytest.mark.asyncio
async def test_health_returns_ok(client: AsyncClient) -> None:
    res = await client.get("/api/v1/health")
    assert res.status_code == 200
    body = res.json()
    assert body["status"] == "ok"
    assert "env" in body
    assert "version" in body


@pytest.mark.asyncio
async def test_snapshot_endpoint_returns_202_with_job_id(client: AsyncClient) -> None:
    """POST /snapshots should return 202 with a job_id for async processing."""
    mock_job = MagicMock()
    mock_job.id = "snapshot-job-123"
    mock_queue = MagicMock()
    mock_queue.enqueue.return_value = mock_job

    with patch("app.api.v1.snapshots._get_queue", return_value=mock_queue):
        res = await client.post(
            "/api/v1/snapshots",
            json={"url": "https://example.com"},
        )

    assert res.status_code == 202
    body = res.json()
    assert "job_id" in body
    assert "status_url" in body
    assert body["job_id"]  # non-empty
    assert "/api/v1/snapshots/jobs/" in body["status_url"]


@pytest.mark.asyncio
async def test_snapshot_endpoint_validates_url_length(client: AsyncClient) -> None:
    # Pydantic should reject a 3-char URL before we hit the stub.
    res = await client.post("/api/v1/snapshots", json={"url": "ab"})
    assert res.status_code == 422


@pytest.mark.asyncio
async def test_snapshot_endpoint_requires_url(client: AsyncClient) -> None:
    res = await client.post("/api/v1/snapshots", json={})
    assert res.status_code == 422


@pytest.mark.asyncio
async def test_openapi_schema_includes_confidence_literal(client: AsyncClient) -> None:
    """Smoke test: the OpenAPI schema must expose the Confidence enum so the
    frontend can codegen against it in Step 5."""
    res = await client.get("/openapi.json")
    assert res.status_code == 200
    schema = res.json()
    schema_str = str(schema)
    assert "high" in schema_str
    assert "medium" in schema_str
    assert "low" in schema_str
