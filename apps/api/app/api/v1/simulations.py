"""Simulation endpoints — Step 4.

POST /snapshots/{snapshot_id}/simulate  — enqueue a simulation run
GET  /snapshots/{snapshot_id}/simulations — list simulations for a snapshot
GET  /simulations/{simulation_id}         — get simulation + cells
GET  /simulations/jobs/{job_id}           — job status
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, HTTPException, status
from redis import Redis
from rq import Queue
from rq.job import Job
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from app.api.deps import DbSession
from app.config import get_settings
from app.models import ProductSnapshot, Segment, Simulation, SimulationCell
from app.schemas import (
    DecisionOption,
    SimulateRequest,
    SimulationCellRead,
    SimulationJobResponse,
    SimulationJobStatus,
    SimulationRead,
)
from app.workers.tasks import task_run_simulation

router = APIRouter()
settings = get_settings()

_OPTION_TYPE_TO_DECISION_TYPE = {
    "pricing": "pricing",
    "copy": "copy",
    "feature": "feature",
    "bundling": "bundle",
    "onboarding": "onboarding",
}


def _get_queue() -> Queue:
    return Queue(connection=Redis.from_url(settings.redis_url))


def _derive_decision_type(options: list[DecisionOption]) -> str:
    return _OPTION_TYPE_TO_DECISION_TYPE.get(options[0].option_type, "feature")


def _cell_to_read(cell: SimulationCell) -> SimulationCellRead:
    return SimulationCellRead(
        id=cell.id,
        segment_id=cell.segment_id,
        option_letter=cell.option_letter,
        range_low=cell.range_low,
        range_high=cell.range_high,
        confidence=cell.confidence,
        reasoning_trace=cell.reasoning_trace,
        top_concern=cell.top_concern,
        invalidating_experiment=cell.invalidating_experiment,
        reaction_sentiment=cell.reaction_sentiment,
        adoption_probability=cell.adoption_probability,
        time_horizon=cell.time_horizon,
        devil_advocate=cell.devil_advocate,
    )


def _sim_to_read(sim: Simulation) -> SimulationRead:
    from app.schemas import OptionInput

    options = [
        OptionInput(
            letter=str(opt.get("label", "")),
            title=str(opt.get("description", ""))[:128],
            sub=None,
        )
        for opt in (sim.options or [])
        if isinstance(opt, dict)
    ]
    cells = [_cell_to_read(c) for c in (sim.cells or [])]

    return SimulationRead(
        id=sim.id,
        snapshot_id=sim.snapshot_id,
        decision_type=sim.decision_type,
        options=options,
        status=sim.status,
        overall_confidence=sim.overall_confidence,
        created_at=sim.created_at,
        completed_at=sim.completed_at,
        cells=cells,
    )


@router.post(
    "/snapshots/{snapshot_id}/simulate",
    status_code=status.HTTP_202_ACCEPTED,
    response_model=SimulationJobResponse,
    summary="Enqueue a simulation run",
    description=(
        "Creates a Simulation row and enqueues the simulation pipeline. "
        "Returns a job ID for polling. Re-running with the same option labels "
        "will replace the previous simulation for this snapshot."
    ),
)
async def create_simulation(
    snapshot_id: uuid.UUID,
    body: SimulateRequest,
    db: DbSession,
) -> SimulationJobResponse:
    # Verify snapshot exists
    snap_stmt = select(ProductSnapshot.id).where(ProductSnapshot.id == snapshot_id)
    snap_result = await db.execute(snap_stmt)
    if snap_result.scalar_one_or_none() is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Snapshot {snapshot_id} not found",
        )

    # Verify segments exist
    seg_stmt = select(Segment.id).where(Segment.snapshot_id == snapshot_id).limit(1)
    seg_result = await db.execute(seg_stmt)
    if seg_result.scalar_one_or_none() is None:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=(
                "No segments found for this snapshot. "
                "Run POST /snapshots/{snapshot_id}/icps first."
            ),
        )

    options_json = [
        {"label": opt.label, "description": opt.description, "option_type": opt.option_type}
        for opt in body.options
    ]
    decision_type = _derive_decision_type(body.options)

    simulation = Simulation(
        snapshot_id=snapshot_id,
        decision_type=decision_type,
        options=options_json,
        status="pending",
    )
    db.add(simulation)
    await db.flush()
    simulation_id = simulation.id
    await db.commit()

    queue = _get_queue()
    job = queue.enqueue(
        task_run_simulation,
        str(simulation_id),
        job_timeout="10m",
    )

    return SimulationJobResponse(
        simulation_id=simulation_id,
        job_id=job.id,
        status_url=f"{settings.api_base_url}/api/v1/simulations/jobs/{job.id}",
    )


@router.get(
    "/simulations/jobs/{job_id}",
    response_model=SimulationJobStatus,
    summary="Get simulation job status",
)
async def get_simulation_job(job_id: str) -> SimulationJobStatus:
    queue = _get_queue()
    try:
        job = Job.fetch(job_id, connection=queue.connection)
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Job {job_id} not found",
        ) from exc

    if job.is_queued:
        return SimulationJobStatus(status="queued")
    if job.is_started:
        return SimulationJobStatus(status="started")
    if job.is_finished:
        return SimulationJobStatus(status="finished")
    if job.is_failed:
        error = str(job.exc_info) if job.exc_info else "Unknown error"
        return SimulationJobStatus(status="failed", error=error)
    return SimulationJobStatus(status="queued")


@router.get(
    "/snapshots/{snapshot_id}/simulations",
    response_model=list[SimulationRead],
    summary="List simulations for a snapshot",
)
async def list_simulations(
    snapshot_id: uuid.UUID,
    db: DbSession,
) -> list[SimulationRead]:
    snap_stmt = select(ProductSnapshot.id).where(ProductSnapshot.id == snapshot_id)
    if (await db.execute(snap_stmt)).scalar_one_or_none() is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Snapshot {snapshot_id} not found",
        )

    stmt = (
        select(Simulation)
        .where(Simulation.snapshot_id == snapshot_id)
        .options(selectinload(Simulation.cells))
        .order_by(Simulation.created_at.desc())
    )
    result = await db.execute(stmt)
    sims = result.scalars().all()
    return [_sim_to_read(s) for s in sims]


@router.get(
    "/simulations/{simulation_id}",
    response_model=SimulationRead,
    summary="Get a simulation with all cells",
)
async def get_simulation(
    simulation_id: uuid.UUID,
    db: DbSession,
) -> SimulationRead:
    stmt = (
        select(Simulation)
        .where(Simulation.id == simulation_id)
        .options(selectinload(Simulation.cells))
    )
    result = await db.execute(stmt)
    sim = result.scalar_one_or_none()

    if sim is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Simulation {simulation_id} not found",
        )

    return _sim_to_read(sim)
