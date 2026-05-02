"""ICP pipeline — Layer 2.

Job: Turn a Product Snapshot into 4-5 evidence-anchored customer segments.

Pipeline stages:
    1. Cluster: Pull review/social text from the snapshot's raw_search_results.
       Embed quotes, cluster by semantic similarity (HDBSCAN with fallback to
       AgglomerativeClustering). Each cluster is a candidate segment.
    2. Synthesize: For each cluster, a DSPy program drafts:
         - segment name + descriptor
         - Jobs-to-be-Done statement (Christensen-style)
         - 3 ranked value drivers with weights
         - what triggers churn for this segment
    3. Anchor: For each candidate, attach 2-3 evidence quotes (the closest
       cluster members to the centroid). If fewer than 2 anchors exist for
       a segment, mark it Low confidence — the "Hypothesis not Portrait"
       state.
    4. Score & Persist: Compute confidence via triangulate(), write Segment +
       Evidence rows under the snapshot. Idempotent — running twice replaces
       the prior segment set.

Cold-start case: if the snapshot has thin search results (e.g., stealth
B2B product), the pipeline still produces segments but they're flagged
Low confidence with the "Hypothesis" tag. The frontend will render the
visible-degradation state and surface the upload-customer-data CTA.

Contract: takes a ProductSnapshot ID, returns the IDs of the segments
created. Idempotent — running twice on the same snapshot replaces the
prior segment set (segments belong to snapshots, not products).
"""

from __future__ import annotations

import uuid

import structlog
from sqlalchemy.ext.asyncio import AsyncSession

from app.pipelines.icp.anchor import anchor_segments
from app.pipelines.icp.cluster import cluster_snippets
from app.pipelines.icp.score import score_and_persist
from app.pipelines.icp.synthesize import synthesize_segments

log = structlog.get_logger()

__all__ = ["run_icp_pipeline"]


async def run_icp_pipeline(
    snapshot_id: uuid.UUID,
    db: AsyncSession,
) -> list[uuid.UUID]:
    """Generate 4-5 segments for a snapshot. Return their IDs.

    Args:
        snapshot_id: An existing ProductSnapshot. Pipeline reads the snapshot's
            raw search results to ground the segments in real evidence.
        db: Async SQLAlchemy session.

    Returns:
        List of newly-created Segment IDs (typically 4-5 items).

    Raises:
        ValueError: If snapshot doesn't exist.
    """
    from sqlalchemy import select

    from app.models import ProductSnapshot

    log.info("icp.pipeline.start", snapshot_id=str(snapshot_id))

    # Fetch the snapshot
    stmt = select(ProductSnapshot).where(ProductSnapshot.id == snapshot_id)
    result = await db.execute(stmt)
    snapshot = result.scalar_one_or_none()

    if snapshot is None:
        raise ValueError(f"Snapshot {snapshot_id} not found")

    # Stage 1: Cluster
    log.info("icp.stage.cluster.start", snapshot_id=str(snapshot_id))
    cluster_result = await cluster_snippets(snapshot)
    log.info(
        "icp.stage.cluster.done",
        n_clusters=len(cluster_result.clusters),
        n_noise=len(cluster_result.noise_indices),
        total_snippets=cluster_result.total_snippets,
    )

    # Stage 2: Synthesize
    log.info("icp.stage.synthesize.start", n_clusters=len(cluster_result.clusters))
    synthesized = await synthesize_segments(snapshot, cluster_result)
    log.info("icp.stage.synthesize.done", n_segments=len(synthesized))

    # Stage 3: Anchor
    log.info("icp.stage.anchor.start", n_segments=len(synthesized))
    anchored = await anchor_segments(synthesized, cluster_result)
    log.info(
        "icp.stage.anchor.done",
        n_segments=len(anchored),
        total_anchors=sum(len(s.evidence_quotes) for s in anchored),
    )

    # Stage 4: Score & Persist
    log.info("icp.stage.persist.start", n_segments=len(anchored))
    segment_ids = await score_and_persist(
        snapshot_id=snapshot_id,
        anchored_segments=anchored,
        db=db,
    )
    log.info("icp.pipeline.done", snapshot_id=str(snapshot_id), n_segments=len(segment_ids))

    return segment_ids
