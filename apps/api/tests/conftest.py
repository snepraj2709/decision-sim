"""Shared pytest fixtures and configuration."""
from __future__ import annotations

import asyncio
import pytest
from httpx import AsyncClient, ASGITransport


@pytest.fixture(scope="function", autouse=True)
def fresh_event_loop():
    """Give each test function its own clean event loop."""
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    yield loop
    loop.close()
    asyncio.set_event_loop(None)


@pytest.fixture
async def client():
    """HTTP test client wired to the FastAPI app."""
    from app.main import app
    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
    ) as c:
        yield c

@pytest.fixture(autouse=True)
async def reset_app_db_engine():
    """Dispose and recreate the app DB engine between tests.
    
    Without this, asyncpg connections created in one test's event loop
    are reused in the next test's loop, causing 'Future attached to a
    different loop' errors.
    """
    yield
    from app.db import engine
    await engine.dispose()