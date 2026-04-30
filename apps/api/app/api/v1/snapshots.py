"""Snapshots endpoints — Layer 1 of the engine.

POST /snapshots - Enqueue a snapshot job for a URL
GET /snapshots/{snapshot_id} - Get a completed snapshot
GET /snapshots/jobs/{job_id} - Check job status
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, HTTPException, status
from redis import Redis
from rq import Queue
from rq.job import Job
from sqlalchemy import select

from app.api.deps import DbSession
from app.config import get_settings
from app.models import ProductSnapshot
from app.schemas import (
    ConfidentField,
    ProductSnapshotRead,
    SnapshotCreateRequest,
    SnapshotJobResponse,
    SnapshotJobStatus,
)
from app.workers.tasks import task_run_snapshot

router = APIRouter()
settings = get_settings()


def _get_queue() -> Queue:
    """Get the RQ queue for snapshot jobs."""
    redis_conn = Redis.from_url(settings.redis_url)
    return Queue(connection=redis_conn)


def _snapshot_to_read(snapshot: ProductSnapshot) -> ProductSnapshotRead:
    """Convert a ProductSnapshot ORM model to the read schema."""

    def _make_field(
        value: str | None,
        confidence: str | None,
        sources: int,
    ) -> ConfidentField | None:
        if value is None:
            return None
        return ConfidentField(
            value=value,
            confidence=confidence or "low",
            sources=sources,
        )

    return ProductSnapshotRead(
        id=snapshot.id,
        product_id=snapshot.product_id,
        created_at=snapshot.created_at,
        category=_make_field(
            snapshot.category,
            snapshot.category_confidence,
            snapshot.category_sources,
        ),
        value_prop=_make_field(
            snapshot.value_prop,
            snapshot.value_prop_confidence,
            snapshot.value_prop_sources,
        ),
        pricing=_make_field(
            snapshot.pricing,
            snapshot.pricing_confidence,
            snapshot.pricing_sources,
        ),
        features=_make_field(
            snapshot.features,
            snapshot.features_confidence,
            snapshot.features_sources,
        ),
        audience=_make_field(
            snapshot.audience,
            snapshot.audience_confidence,
            snapshot.audience_sources,
        ),
        competitors=_make_field(
            snapshot.competitors,
            snapshot.competitors_confidence,
            snapshot.competitors_sources,
        ),
    )


@router.post(
    "/snapshots",
    status_code=status.HTTP_202_ACCEPTED,
    response_model=SnapshotJobResponse,
    summary="Generate a product snapshot from a URL",
    description=(
        "Kicks off the snapshot pipeline: scrape, search-ground, "
        "extract structured Product Card with per-field confidence. "
        "Returns a job ID for polling."
    ),
)
async def create_snapshot(payload: SnapshotCreateRequest) -> SnapshotJobResponse:
    """Enqueue a snapshot job for the given URL."""
    queue = _get_queue()

    # Enqueue the task
    job = queue.enqueue(
        task_run_snapshot,
        payload.url,
        job_timeout="5m",
    )

    return SnapshotJobResponse(
        job_id=job.id,
        status_url=f"{settings.api_base_url}/api/v1/snapshots/jobs/{job.id}",
    )


@router.get(
    "/snapshots/jobs/{job_id}",
    response_model=SnapshotJobStatus,
    summary="Get snapshot job status",
    description="Check the status of a snapshot generation job.",
)
async def get_job_status(job_id: str) -> SnapshotJobStatus:
    """Get the status of a snapshot job."""
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
        return SnapshotJobStatus(status="queued")
    elif job.is_started:
        return SnapshotJobStatus(status="started")
    elif job.is_finished:
        # Result is the snapshot ID as string
        snapshot_id = uuid.UUID(job.result) if job.result else None
        return SnapshotJobStatus(status="finished", snapshot_id=snapshot_id)
    elif job.is_failed:
        error = str(job.exc_info) if job.exc_info else "Unknown error"
        return SnapshotJobStatus(status="failed", error=error)
    else:
        return SnapshotJobStatus(status="queued")


@router.get(
    "/snapshots/{snapshot_id}",
    response_model=ProductSnapshotRead,
    summary="Get a product snapshot",
    description="Retrieve a completed product snapshot by ID.",
)
async def get_snapshot(snapshot_id: uuid.UUID, db: DbSession) -> ProductSnapshotRead:
    """Get a snapshot by ID."""
    stmt = select(ProductSnapshot).where(ProductSnapshot.id == snapshot_id)
    result = await db.execute(stmt)
    snapshot = result.scalar_one_or_none()

    if snapshot is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Snapshot {snapshot_id} not found",
        )

    return _snapshot_to_read(snapshot)
