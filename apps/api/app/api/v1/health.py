"""Health check — verifies app is alive and config loaded.

Step 5 will add deeper checks (db connectivity, redis ping, search provider
health). For Step 1, returning the env + version is enough to prove the
frontend ↔ backend wiring works.
"""

from fastapi import APIRouter

from app.config import get_settings
from app.schemas import HealthResponse

router = APIRouter()


@router.get("/health", response_model=HealthResponse)
async def health() -> HealthResponse:
    settings = get_settings()
    return HealthResponse(
        status="ok",
        env=settings.env,
        version=settings.version,
    )
