"""Stage 4 — Persist.

Writes SimulationCell rows for the current Simulation, handles idempotency
(same snapshot + same option labels → replace), and computes overall_confidence.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

import structlog
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Simulation, SimulationCell
from app.pipelines.simulation.score import CellResult

log = structlog.get_logger()


def _overall_confidence(cells: list[CellResult]) -> str:
    """Worst-of-cells: one Low pulls the whole run to Low."""
    confidences = {c.confidence for c in cells}
    if "low" in confidences:
        return "low"
    if "medium" in confidences:
        return "medium"
    return "high"


def _option_labels(options: list[dict[str, object]]) -> frozenset[str]:
    return frozenset(
        str(opt.get("label", ""))
        for opt in options
        if isinstance(opt, dict)
    )


async def _delete_sibling_simulations(
    simulation_id: uuid.UUID,
    snapshot_id: uuid.UUID,
    current_labels: frozenset[str],
    db: AsyncSession,
) -> None:
    stmt = select(Simulation).where(
        Simulation.snapshot_id == snapshot_id,
        Simulation.id != simulation_id,
    )
    result = await db.execute(stmt)
    siblings = result.scalars().all()

    for sibling in siblings:
        sibling_labels = _option_labels(list(sibling.options or []))
        if sibling_labels == current_labels:
            log.info(
                "simulation.replacing_existing",
                old_simulation_id=str(sibling.id),
                snapshot_id=str(snapshot_id),
                option_labels=sorted(current_labels),
            )
            await db.delete(sibling)


async def persist_cells(
    simulation_id: uuid.UUID,
    cell_results: list[CellResult],
    db: AsyncSession,
) -> None:
    """Write cells and finalise the Simulation row.

    Idempotency: if another Simulation for the same snapshot with the same
    option label set already exists, it is deleted first.
    """
    stmt = select(Simulation).where(Simulation.id == simulation_id)
    result = await db.execute(stmt)
    simulation = result.scalar_one_or_none()

    if simulation is None:
        raise ValueError(f"Simulation {simulation_id} not found")

    current_labels = _option_labels(list(simulation.options or []))

    await _delete_sibling_simulations(
        simulation_id, simulation.snapshot_id, current_labels, db
    )

    # Delete any existing cells for this simulation (re-run safety)
    await db.execute(
        delete(SimulationCell).where(SimulationCell.simulation_id == simulation_id)
    )

    for cell in cell_results:
        range_low = int(max(0.0, cell.churn_probability - 0.10) * 100)
        range_high = int(min(1.0, cell.churn_probability + 0.10) * 100)

        row = SimulationCell(
            simulation_id=simulation_id,
            segment_id=cell.segment_id,
            option_letter=cell.option_label,
            range_low=range_low,
            range_high=range_high,
            confidence=cell.confidence,
            reasoning_trace=cell.reasoning_trace or None,
            top_concern=cell.top_concern or None,
            invalidating_experiment=cell.smallest_experiment or None,
            reaction_sentiment=cell.reaction_sentiment,
            adoption_probability=cell.adoption_probability,
            time_horizon=cell.time_horizon,
            devil_advocate=cell.devil_advocate or None,
        )
        db.add(row)

    overall = _overall_confidence(cell_results) if cell_results else "low"

    simulation.status = "completed"
    simulation.overall_confidence = overall
    simulation.completed_at = datetime.now(tz=UTC)

    await db.commit()

    log.info(
        "simulation.persist.done",
        simulation_id=str(simulation_id),
        n_cells=len(cell_results),
        overall_confidence=overall,
    )
