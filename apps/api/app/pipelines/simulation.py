"""Simulation pipeline — Layers 3 + 4.

Job: For each (segment, option) pair, produce a reaction estimate with a
confidence score. This is the most failure-prone layer of the engine and
deserves the most careful implementation.

Pipeline stages (Step 4 will implement):
    For each (segment × option) pair:

      A. Generative reasoning trace
         A DSPy program prompts the LLM in-character: "You are [segment].
         The product just changed [option]. Walk through your reaction
         step by step." Output: a chain of reasoning, not just a number.

      B. Structured extraction
         A second DSPy program parses the trace into:
           - reaction_sentiment: int in [-100, +100]
           - action_probabilities: {stay, churn, downgrade, upgrade,
                                    vocal_complaint, silent_leave}
           - top_concern: free text, ≤12 words
           - time_horizon: 'this_quarter' | 'next_renewal' | 'long_term'

      C. Base-rate sanity check
         Retrieve analogous historical cases from a knowledge base seeded
         with research (pricing changes, feature gating, copy changes).
         Compute IoU-style overlap between the LLM's predicted band and the
         historical base-rate band. A wildly out-of-band prediction gets
         flagged.

      D. Confidence triangulation
         Use core.confidence.triangulate() with three signals:
           - llm_baserate_agreement: from step C
           - evidence_density: count of evidence anchors on the segment
           - construct_stability: how distinct this segment is from its
             neighbors (cosine distance between segment embeddings)

After all cells complete, aggregate:
  - Per-option weighted churn estimate (by share_pct)
  - Revenue impact range
  - Overall confidence (worst-of-cells, not mean — one Low cell pulls the run down)

Long-running. Always enqueued to RQ, never awaited inline.

Contract: takes a Simulation ID (which has snapshot_id, options, decision_type
already stored), returns nothing. Cells are written as they complete. Frontend
polls or subscribes to status changes.
"""

from __future__ import annotations

import uuid

from sqlalchemy.ext.asyncio import AsyncSession


async def run_simulation(
    simulation_id: uuid.UUID,
    db: AsyncSession,
) -> None:
    """Run a simulation to completion. Writes cells as they're produced.

    Args:
        simulation_id: An existing Simulation row in `pending` status.
            Will be transitioned to `running` → `completed` (or `failed`).
        db: Async SQLAlchemy session.

    Returns:
        None. Results are persisted. Frontend reads them via the simulations
        read API.

    Raises:
        NotImplementedError: Always, until Step 4.
        SimulationFailedError: (Step 4) When >50% of cells fail to produce
            a reaction. The Simulation row is marked `failed` and partial
            cells are kept for debugging.
    """
    raise NotImplementedError(
        "Simulation pipeline is the Step 4 build target. "
        "ICP pipeline (Step 3) must land first."
    )
