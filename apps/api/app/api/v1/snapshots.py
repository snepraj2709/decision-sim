"""Snapshots endpoints — Layer 1 of the engine.

Step 1: contract-only. POST /snapshots returns 501 Not Implemented.
Step 2: implements the scrape pipeline behind this endpoint.

The contract is locked NOW so the frontend can be written against it without
drift later.
"""

from fastapi import APIRouter, HTTPException, status

from app.schemas import ProductSnapshotRead, SnapshotCreateRequest

router = APIRouter()


@router.post(
    "/snapshots",
    status_code=status.HTTP_202_ACCEPTED,
    response_model=ProductSnapshotRead,
    summary="Generate a product snapshot from a URL",
    description=(
        "Kicks off the snapshot pipeline (Step 2): scrape, search-ground, "
        "extract structured Product Card with per-field confidence. "
        "**Step 1 stub — returns 501.**"
    ),
)
async def create_snapshot(payload: SnapshotCreateRequest) -> ProductSnapshotRead:
    raise HTTPException(
        status_code=status.HTTP_501_NOT_IMPLEMENTED,
        detail=(
            "Snapshot pipeline is scaffolded but not yet implemented. "
            "See apps/api/app/pipelines/snapshot.py — Step 2 will fill this in."
        ),
    )
