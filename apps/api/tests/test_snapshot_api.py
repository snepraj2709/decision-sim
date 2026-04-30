"""API endpoint tests for snapshots.

Tests verify:
  - POST /snapshots returns 202 with job_id
  - GET /snapshots/{id} returns 404 for non-existent snapshot
  - GET /snapshots/jobs/{id} returns job status
"""

from __future__ import annotations

import uuid

import pytest
from httpx import AsyncClient


@pytest.mark.asyncio
async def test_post_snapshots_returns_202(client: AsyncClient) -> None:
    """POST /snapshots should return 202 Accepted with job info."""
    res = await client.post(
        "/api/v1/snapshots",
        json={"url": "https://example.com"},
    )

    assert res.status_code == 202
    body = res.json()

    assert "job_id" in body
    assert "status_url" in body
    assert body["job_id"]  # Non-empty
    assert "/api/v1/snapshots/jobs/" in body["status_url"]


@pytest.mark.asyncio
async def test_get_snapshot_returns_404_for_nonexistent(client: AsyncClient) -> None:
    """GET /snapshots/{id} should return 404 for non-existent snapshot."""
    fake_id = uuid.uuid4()
    res = await client.get(f"/api/v1/snapshots/{fake_id}")

    assert res.status_code == 404
    body = res.json()
    assert "not found" in body["detail"].lower()


@pytest.mark.asyncio
async def test_get_job_status_returns_404_for_nonexistent(client: AsyncClient) -> None:
    """GET /snapshots/jobs/{id} should return 404 for non-existent job."""
    fake_job_id = "nonexistent-job-id-12345"
    res = await client.get(f"/api/v1/snapshots/jobs/{fake_job_id}")

    assert res.status_code == 404
    body = res.json()
    assert "not found" in body["detail"].lower()


@pytest.mark.asyncio
async def test_post_snapshots_validates_url(client: AsyncClient) -> None:
    """POST /snapshots should validate URL length."""
    # Too short
    res = await client.post(
        "/api/v1/snapshots",
        json={"url": "ab"},
    )
    assert res.status_code == 422

    # Missing URL
    res = await client.post(
        "/api/v1/snapshots",
        json={},
    )
    assert res.status_code == 422


@pytest.mark.asyncio
async def test_openapi_includes_new_schemas(client: AsyncClient) -> None:
    """OpenAPI schema should include the new job-related schemas."""
    res = await client.get("/openapi.json")
    assert res.status_code == 200

    schema = res.json()
    schema_names = list(schema.get("components", {}).get("schemas", {}).keys())

    # Check for new schemas
    assert "SnapshotJobResponse" in schema_names
    assert "SnapshotJobStatus" in schema_names
    # JobStatus is a Literal type, so it appears inline, not as a separate schema


@pytest.mark.asyncio
async def test_snapshot_endpoints_documented(client: AsyncClient) -> None:
    """Snapshot endpoints should be properly documented in OpenAPI."""
    res = await client.get("/openapi.json")
    assert res.status_code == 200

    schema = res.json()
    paths = schema.get("paths", {})

    # POST /snapshots
    assert "/api/v1/snapshots" in paths
    assert "post" in paths["/api/v1/snapshots"]

    # GET /snapshots/{snapshot_id}
    assert "/api/v1/snapshots/{snapshot_id}" in paths
    assert "get" in paths["/api/v1/snapshots/{snapshot_id}"]

    # GET /snapshots/jobs/{job_id}
    assert "/api/v1/snapshots/jobs/{job_id}" in paths
    assert "get" in paths["/api/v1/snapshots/jobs/{job_id}"]
