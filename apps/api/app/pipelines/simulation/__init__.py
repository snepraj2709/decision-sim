"""Simulation pipeline — Step 4.

Produces a SimulationCell for every (segment x option) pair.

Stages:
  1. parse   -- validate and type the option list from Simulation.options
  2. react   -- DSPy ChainOfThought: in-character reaction per (segment x option)
  3. score   — triangulate() confidence; devil's advocate for Low/Medium cells
  4. persist — write cells, handle idempotency, set Simulation.status

Contract: takes an existing Simulation ID (status='pending'), returns None.
All results are written to the database. Frontend polls via the simulations API.
"""

from __future__ import annotations

import uuid

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.config import get_settings
from app.models import Segment, Simulation
from app.pipelines.simulation.parse import parse_options
from app.pipelines.simulation.persist import persist_cells
from app.pipelines.simulation.react import generate_reactions
from app.pipelines.simulation.score import score_cells

log = structlog.get_logger()

__all__ = ["run_simulation"]


class SimulationFailedError(Exception):
    """Raised when >50% of cells fail to produce a reaction."""


async def run_simulation(
    simulation_id: uuid.UUID,
    db: AsyncSession,
) -> None:
    """Run a simulation to completion. Writes cells as they're produced.

    Args:
        simulation_id: An existing Simulation row in 'pending' status.
        db: Async SQLAlchemy session.

    Raises:
        SimulationFailedError: When >50% of cells fail to produce a reaction.
        ValueError: If the Simulation row is not found.
    """
    settings = get_settings()

    # Load simulation
    stmt = select(Simulation).where(Simulation.id == simulation_id)
    result = await db.execute(stmt)
    simulation = result.scalar_one_or_none()

    if simulation is None:
        raise ValueError(f"Simulation {simulation_id} not found")

    simulation.status = "running"
    await db.commit()

    log.info(
        "simulation.pipeline.start",
        simulation_id=str(simulation_id),
        snapshot_id=str(simulation.snapshot_id),
    )

    try:
        # Load segments with evidence
        seg_stmt = (
            select(Segment)
            .where(Segment.snapshot_id == simulation.snapshot_id)
            .options(selectinload(Segment.evidence))
            .order_by(Segment.share_pct.desc())
        )
        seg_result = await db.execute(seg_stmt)
        segments = list(seg_result.scalars().all())

        if not segments:
            log.warning(
                "simulation.pipeline.no_segments",
                simulation_id=str(simulation_id),
                snapshot_id=str(simulation.snapshot_id),
            )
            simulation.status = "failed"
            await db.commit()
            return

        log.info(
            "simulation.stage.parse.start",
            n_options=len(simulation.options or []),
        )
        parsed_options = parse_options(list(simulation.options or []))
        log.info("simulation.stage.parse.done", n_options=len(parsed_options))

        log.info(
            "simulation.stage.react.start",
            n_segments=len(segments),
            n_options=len(parsed_options),
            n_pairs=len(segments) * len(parsed_options),
        )
        reactions = await generate_reactions(segments, parsed_options)
        log.info(
            "simulation.stage.react.done",
            n_reactions=len(reactions),
            n_failed=sum(1 for r in reactions if r.failed),
        )

        failed_count = sum(1 for r in reactions if r.failed)
        total_count = len(reactions)
        if total_count > 0 and failed_count / total_count > 0.5:
            raise SimulationFailedError(
                f"{failed_count}/{total_count} cells failed — simulation aborted"
            )

        log.info("simulation.stage.score.start", n_reactions=len(reactions))
        cell_results = await score_cells(
            segments,
            reactions,
            parsed_options,
            min_sources=settings.min_sources_for_high_confidence,
        )
        log.info("simulation.stage.score.done", n_cells=len(cell_results))

        log.info("simulation.stage.persist.start", n_cells=len(cell_results))
        await persist_cells(simulation_id, cell_results, db)
        log.info("simulation.pipeline.done", simulation_id=str(simulation_id))

    except Exception:
        # Reload simulation in case session was committed between stages
        result2 = await db.execute(
            select(Simulation).where(Simulation.id == simulation_id)
        )
        sim2 = result2.scalar_one_or_none()
        if sim2 is not None:
            sim2.status = "failed"
            await db.commit()
        raise
