"""API surface tests.

What we check in Step 1:
  1. /health responds with the expected schema.
  2. /snapshots returns 501 with an informative message — proving the
     contract is wired but the implementation is honestly absent.
  3. Schema validation rejects malformed bodies before reaching the stub.
"""

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
async def test_snapshot_endpoint_returns_501_with_message(client: AsyncClient) -> None:
    res = await client.post(
        "/api/v1/snapshots",
        json={"url": "https://example.com"},
    )
    assert res.status_code == 501
    body = res.json()
    # The message should point future-you (or your collaborator) at the right file.
    assert "Step 2" in body["detail"]
    assert "snapshot.py" in body["detail"]


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
