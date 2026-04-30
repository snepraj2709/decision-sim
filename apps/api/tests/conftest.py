"""Shared pytest fixtures.

Tests in Step 1 are deliberately limited:
  - confidence math (pure, no I/O)
  - health endpoint (proves the app boots + CORS + schema)
  - 501 contract on snapshot endpoint (proves the contract is wired)

Steps 2-4 add real pipeline tests against a test database.
"""

from collections.abc import AsyncIterator

import pytest
from httpx import ASGITransport, AsyncClient

from app.main import app


@pytest.fixture
async def client() -> AsyncIterator[AsyncClient]:
    """Async HTTP client bound directly to the FastAPI app — no network."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c
