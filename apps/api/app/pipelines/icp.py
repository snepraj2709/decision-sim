"""ICP pipeline — Layer 2.

Job: Turn a Product Snapshot into 4–5 evidence-anchored customer segments.

Pipeline stages (Step 3 will implement):
    1. Cluster: Pull review/social text from the snapshot's raw_search_results.
       Embed quotes, cluster by semantic similarity (HDBSCAN or Bayesian
       Gaussian Mixture). Each cluster is a candidate segment.
    2. Summarize: For each cluster, a DSPy program drafts:
         - segment name + descriptor
         - Jobs-to-be-Done statement (Christensen-style)
         - 3 ranked value drivers with weights
         - what triggers churn for this segment
    3. Anchor: For each candidate, attach 2–3 evidence quotes (the closest
       cluster members to the centroid). If fewer than 2 anchors exist for
       a segment, mark it Low confidence — the "Hypothesis not Portrait"
       state.
    4. Calibrate: Estimate share_pct from cluster sizes (with the LLM as a
       sanity check against obvious imbalances).
    5. Persist: Write Segment + Evidence rows under the snapshot.

Cold-start case: if the snapshot has thin search results (e.g., stealth
B2B product), the pipeline still produces 4–5 segments but they're flagged
Low confidence with the "Hypothesis" tag. The frontend will render the
visible-degradation state and surface the upload-customer-data CTA.

Contract: takes a ProductSnapshot ID, returns the IDs of the segments
created. Idempotent — running twice on the same snapshot replaces the
prior segment set (segments belong to snapshots, not products).
"""

from __future__ import annotations

import uuid

from sqlalchemy.ext.asyncio import AsyncSession


async def run_icp_pipeline(
    snapshot_id: uuid.UUID,
    db: AsyncSession,
) -> list[uuid.UUID]:
    """Generate 4–5 segments for a snapshot. Return their IDs.

    Args:
        snapshot_id: An existing ProductSnapshot. Pipeline reads the snapshot's
            raw search results to ground the segments in real evidence.
        db: Async SQLAlchemy session.

    Returns:
        List of newly-created Segment IDs (typically 4–5 items).

    Raises:
        NotImplementedError: Always, until Step 3.
        InsufficientEvidenceError: (Step 3) When `require_evidence_anchors=True`
            and the snapshot has fewer than 2 anchors per candidate segment.
    """
    raise NotImplementedError(
        "ICP pipeline is the Step 3 build target. "
        "Snapshot pipeline (Step 2) must land first."
    )
