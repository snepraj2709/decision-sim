"""FastAPI application factory.

Run locally:
    uv run fastapi dev app/main.py
"""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import structlog
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.v1 import health, segments, simulations, snapshots
from app.config import get_settings

settings = get_settings()
log = structlog.get_logger()


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    log.info("api.startup", env=settings.env, version=settings.version)
    yield
    log.info("api.shutdown")


def create_app() -> FastAPI:
    app = FastAPI(
        title="Decision Simulation Engine",
        version=settings.version,
        lifespan=lifespan,
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    app.include_router(health.router, prefix="/api/v1", tags=["health"])
    app.include_router(snapshots.router, prefix="/api/v1", tags=["snapshots"])
    app.include_router(segments.router, prefix="/api/v1", tags=["segments"])
    app.include_router(simulations.router, prefix="/api/v1", tags=["simulations"])

    return app


app = create_app()
