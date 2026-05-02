"""RQ task definitions — worker-side entry points.

The pipelines themselves are async; RQ tasks are sync. We bridge with
`asyncio.run` because each task gets its own process and event loop.

Run a worker:
    uv run rq worker --url redis://localhost:6379

Step 2 will register tasks here. Step 1 leaves the file with the imports
and a single placeholder so the worker has something to load.
"""

from __future__ import annotations

import asyncio
import uuid

import structlog

from app.db import AsyncSessionLocal

log = structlog.get_logger()


def task_run_snapshot(url: str) -> str:
    """Worker task — wraps the snapshot pipeline.

    Returns the snapshot ID as a string (RQ serializes return values).
    Step 2 implements the body.
    """
    log.info("task.snapshot.start", url=url)

    async def _run() -> uuid.UUID:
        from app.db import engine

        async with AsyncSessionLocal() as db:
            from app.pipelines.snapshot import run_snapshot_pipeline

            try:
                return await run_snapshot_pipeline(url, db)
            finally:
                await engine.dispose()

    snapshot_id = asyncio.run(_run())
    log.info("task.snapshot.done", url=url, snapshot_id=str(snapshot_id))
    return str(snapshot_id)


def task_run_icps(snapshot_id: str) -> list[str]:
    """Worker task — wraps the ICP pipeline. Step 3 implements."""
    log.info("task.icps.start", snapshot_id=snapshot_id)

    async def _run() -> list[uuid.UUID]:
        async with AsyncSessionLocal() as db:
            from app.pipelines.icp import run_icp_pipeline
            return await run_icp_pipeline(uuid.UUID(snapshot_id), db)

    ids = asyncio.run(_run())
    return [str(i) for i in ids]


def task_run_simulation(simulation_id: str) -> None:
    """Worker task — wraps the simulation pipeline. Step 4 implements."""
    log.info("task.simulation.start", simulation_id=simulation_id)

    async def _run() -> None:
        async with AsyncSessionLocal() as db:
            from app.pipelines.simulation import run_simulation
            await run_simulation(uuid.UUID(simulation_id), db)

    asyncio.run(_run())
