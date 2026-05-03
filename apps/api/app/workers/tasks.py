"""RQ task definitions — worker-side entry points.

The pipelines themselves are async; RQ tasks are sync. We bridge with
`asyncio.run`, and each task must create and dispose its own async engine
inside that event loop. asyncpg pools keep loop references, so sharing the
FastAPI process engine/sessionmaker across RQ jobs can poison later jobs.

Run a worker:
    uv run rq worker --url redis://localhost:6379

Step 2 will register tasks here. Step 1 leaves the file with the imports
and a single placeholder so the worker has something to load.
"""

from __future__ import annotations

import asyncio
import uuid

import structlog

log = structlog.get_logger()


def task_run_snapshot(url: str) -> str:
    """Worker task — wraps the snapshot pipeline.

    Returns the snapshot ID as a string (RQ serializes return values).
    Step 2 implements the body.
    """
    log.info("task.snapshot.start", url=url)

    async def _run() -> str:
        from sqlalchemy.ext.asyncio import (
            AsyncSession,
            async_sessionmaker,
            create_async_engine,
        )

        from app.config import get_settings

        settings = get_settings()
        engine = create_async_engine(
            settings.database_url,
            pool_pre_ping=True,
            pool_size=1,
            max_overflow=0,
        )

        try:
            async with async_sessionmaker(
                engine,
                class_=AsyncSession,
                expire_on_commit=False,
            )() as db:
                from app.pipelines.snapshot import run_snapshot_pipeline

                snapshot_id = await run_snapshot_pipeline(url, db)
                return str(snapshot_id)
        finally:
            await engine.dispose()

    snapshot_id = asyncio.run(_run())
    log.info("task.snapshot.done", url=url, snapshot_id=snapshot_id)
    return snapshot_id


def task_run_icps(snapshot_id: str) -> list[str]:
    """Worker task — wraps the ICP pipeline. Step 3 implements."""
    log.info("task.icps.start", snapshot_id=snapshot_id)

    async def _run() -> list[str]:
        from sqlalchemy.ext.asyncio import (
            AsyncSession,
            async_sessionmaker,
            create_async_engine,
        )

        from app.config import get_settings

        settings = get_settings()
        engine = create_async_engine(
            settings.database_url,
            pool_pre_ping=True,
            pool_size=1,
            max_overflow=0,
        )

        try:
            async with async_sessionmaker(
                engine,
                class_=AsyncSession,
                expire_on_commit=False,
            )() as db:
                from app.pipelines.icp import run_icp_pipeline

                ids = await run_icp_pipeline(uuid.UUID(snapshot_id), db)
                return [str(i) for i in ids]
        finally:
            await engine.dispose()

    return asyncio.run(_run())


def task_run_simulation(simulation_id: str) -> None:
    """Worker task — wraps the simulation pipeline. Step 4 implements."""
    log.info("task.simulation.start", simulation_id=simulation_id)

    async def _run() -> None:
        from sqlalchemy.ext.asyncio import (
            AsyncSession,
            async_sessionmaker,
            create_async_engine,
        )

        from app.config import get_settings

        settings = get_settings()
        engine = create_async_engine(
            settings.database_url,
            pool_pre_ping=True,
            pool_size=1,
            max_overflow=0,
        )

        try:
            async with async_sessionmaker(
                engine,
                class_=AsyncSession,
                expire_on_commit=False,
            )() as db:
                from app.pipelines.simulation import run_simulation

                await run_simulation(uuid.UUID(simulation_id), db)
        finally:
            await engine.dispose()

    asyncio.run(_run())
