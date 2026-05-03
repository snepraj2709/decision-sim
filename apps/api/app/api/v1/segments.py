"""Segments endpoints — Layer 2 of the engine (ICP pipeline).

POST /snapshots/{snapshot_id}/icps - Enqueue ICP generation job
GET /snapshots/{snapshot_id}/segments - Get segments for a snapshot
GET /icps/jobs/{job_id} - Check ICP job status
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
from app.models import ProductSnapshot, Segment, SimulationCell
from app.schemas import (
    DriverWeight,
    EvidenceRead,
    ICPJobResponse,
    ICPJobStatus,
    SegmentRead,
)
from app.workers.tasks import task_run_icps

router = APIRouter()
settings = get_settings()


def _get_queue() -> Queue:
    """Get the RQ queue for ICP jobs."""
    redis_conn = Redis.from_url(settings.redis_url)
    return Queue(connection=redis_conn)


def _segment_to_read(segment: Segment) -> SegmentRead:
    """Convert a Segment ORM model to the read schema."""
    # Parse drivers from JSON
    drivers: list[DriverWeight] | None = None
    if segment.drivers:
        drivers = [
            DriverWeight(label=d.get("label", ""), weight=d.get("weight", 0.0))
            for d in segment.drivers
            if isinstance(d, dict)
        ]

    # Convert evidence
    evidence = [
        EvidenceRead(
            id=e.id,
            quote=e.quote,
            source=e.source,
            source_url=e.source_url,
            kind=e.kind,
            captured_at=e.captured_at,
        )
        for e in segment.evidence
    ]

    return SegmentRead(
        id=segment.id,
        name=segment.name,
        descriptor=segment.descriptor,
        job_to_be_done=segment.job_to_be_done,
        share_pct=segment.share_pct,
        confidence=segment.confidence,
        drivers=drivers,
        leaves=segment.leaves,
        evidence=evidence,
    )


@router.post(
    "/snapshots/{snapshot_id}/icps",
    status_code=status.HTTP_202_ACCEPTED,
    response_model=ICPJobResponse,
    summary="Generate customer segments from a snapshot",
    description=(
        "Kicks off the ICP pipeline: cluster search results, synthesize "
        "segments, anchor with evidence, score confidence. "
        "Returns a job ID for polling."
    ),
)
async def create_icps(snapshot_id: uuid.UUID, db: DbSession) -> ICPJobResponse:
    """Enqueue an ICP generation job for the given snapshot."""
    # Verify snapshot exists
    stmt = select(ProductSnapshot.id).where(ProductSnapshot.id == snapshot_id)
    result = await db.execute(stmt)
    if result.scalar_one_or_none() is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Snapshot {snapshot_id} not found",
        )

    # Block ICP reruns when simulation cells already exist for this snapshot.
    # Rerunning ICP deletes and reinserts Segment rows, cascading to
    # SimulationCell rows — destroying simulation results silently.
    cells_stmt = (
        select(SimulationCell.id)
        .join(Segment, SimulationCell.segment_id == Segment.id)
        .where(Segment.snapshot_id == snapshot_id)
        .limit(1)
    )
    cells_result = await db.execute(cells_stmt)
    if cells_result.scalar_one_or_none() is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                "Cannot rerun ICP: simulation cells already exist for this snapshot. "
                "Delete the simulation before regenerating segments."
            ),
        )

    queue = _get_queue()

    # Enqueue the task
    job = queue.enqueue(
        task_run_icps,
        str(snapshot_id),
        job_timeout="5m",
    )

    return ICPJobResponse(
        job_id=job.id,
        status_url=f"{settings.api_base_url}/api/v1/icps/jobs/{job.id}",
    )


@router.get(
    "/icps/jobs/{job_id}",
    response_model=ICPJobStatus,
    summary="Get ICP job status",
    description="Check the status of an ICP generation job.",
)
async def get_icp_job_status(job_id: str) -> ICPJobStatus:
    """Get the status of an ICP generation job."""
    queue = _get_queue()

    try:
        job = Job.fetch(job_id, connection=queue.connection)
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Job {job_id} not found",
        ) from e

    # Map RQ status to our status
    if job.is_queued:
        return ICPJobStatus(status="queued")
    elif job.is_started:
        return ICPJobStatus(status="started")
    elif job.is_finished:
        # Result is a list of segment IDs as strings
        segment_ids = None
        if job.result:
            segment_ids = [uuid.UUID(s) for s in job.result]
        return ICPJobStatus(status="finished", segment_ids=segment_ids)
    elif job.is_failed:
        error = str(job.exc_info) if job.exc_info else "Unknown error"
        return ICPJobStatus(status="failed", error=error)
    else:
        return ICPJobStatus(status="queued")


@router.get(
    "/snapshots/{snapshot_id}/segments",
    response_model=list[SegmentRead],
    summary="Get segments for a snapshot",
    description="Retrieve all customer segments generated for a snapshot.",
)
async def get_segments(snapshot_id: uuid.UUID, db: DbSession) -> list[SegmentRead]:
    """Get all segments for a snapshot."""
    # First verify the snapshot exists
    snapshot_stmt = select(ProductSnapshot.id).where(ProductSnapshot.id == snapshot_id)
    snapshot_result = await db.execute(snapshot_stmt)
    if snapshot_result.scalar_one_or_none() is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Snapshot {snapshot_id} not found",
        )

    # Get segments with evidence eager-loaded
    stmt = (
        select(Segment)
        .where(Segment.snapshot_id == snapshot_id)
        .options(selectinload(Segment.evidence))
        .order_by(Segment.share_pct.desc())
    )
    result = await db.execute(stmt)
    segments = result.scalars().all()

    return [_segment_to_read(s) for s in segments]
