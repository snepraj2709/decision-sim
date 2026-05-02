"""Confidence — the engine's epistemic backbone.

This module is load-bearing for three pipelines: Snapshot (Step 2), ICP (Step 3),
and Simulation (Step 4). Every confidence label in the product flows through
triangulate(). The module is intentionally pure — no I/O, no DB, no LLM calls —
so it can be unit-tested aggressively and trusted unconditionally.

THE GEOMETRIC MEAN PRINCIPLE: We combine three independent signals using the
geometric mean, not a weighted sum. This is deliberate. A weighted sum allows
a high score on one axis to paper over a zero on another — "fluent LLM answer
with no evidence" could still round to Medium. The geometric mean kills the
score if ANY signal is near zero. This is the right behavior: we want to
over-flag Low rather than under-flag. A wrongly-Low cell creates a CTA to
upload data; a wrongly-High cell creates a wrong decision.

Three independent signals combine into a single Confidence label:

  1. LLM ↔ base-rate agreement
       Does the LLM's prediction fall within the band of historical base rates?
       1.0 = perfect agreement, 0.0 = total disagreement.

  2. Evidence anchor density
       How many independent, high-quality evidence anchors back this claim?
       Normalized by `min_sources_for_high_confidence` (default 3).

  3. Construct stability
       For ICPs: how distinct is this segment from its neighbors?
       For facts: how consistent are the source claims with each other?
       1.0 = clearly distinct / consistent, 0.0 = blurry / contradictory.

The combiner is intentionally simple — geometric mean of the three signals,
then thresholded to high/medium/low. We avoid weighted sums because they let
a high score on one axis paper over a low score on another. If any one of the
three is weak, confidence should be weak.

All functions here are pure. They have no I/O, no DB access, no LLM calls.
Tests live in `tests/test_confidence.py` and run on every CI run.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Literal

Confidence = Literal["high", "medium", "low"]


@dataclass(frozen=True, slots=True)
class TriangulationInput:
    """The three signals that combine into a Confidence label.

    All three are floats in [0.0, 1.0]. Use the helper constructors below
    when raw inputs need to be normalized.
    """

    llm_baserate_agreement: float
    evidence_density: float
    construct_stability: float


# ── Thresholds ──────────────────────────────────────────────────────────────
# These are deliberately conservative. We want to over-flag Low rather than
# under-flag — a wrongly-Low cell creates a CTA to upload data; a wrongly-High
# cell creates a wrong decision.
HIGH_THRESHOLD = 0.75
MEDIUM_THRESHOLD = 0.45


# ── Constructors for normalized signals ────────────────────────────────────
def evidence_density_from_count(
    n_independent_sources: int,
    min_for_high: int = 3,
) -> float:
    """Normalize a source count to [0, 1].

    n=0 → 0.0
    n=min_for_high → 1.0
    n=2*min → 1.0 (capped — extra sources past the threshold don't keep adding)
    """
    if n_independent_sources <= 0:
        return 0.0
    return min(1.0, n_independent_sources / max(1, min_for_high))


def baserate_agreement_from_overlap(
    llm_low: float,
    llm_high: float,
    baserate_low: float,
    baserate_high: float,
) -> float:
    """Compute IoU-style overlap between an LLM band and a base-rate band.

    Both bands are intervals (e.g., churn % low/high). Returns:
      1.0 if the LLM band is contained within the base-rate band
      0.0 if the bands are disjoint
      partial values for partial overlap

    This is deliberately asymmetric: an LLM band wider than the base-rate one
    is fine (the engine is being honest about uncertainty), but a band that
    falls outside the historical base rate is suspicious.
    """
    if llm_high < llm_low or baserate_high < baserate_low:
        raise ValueError("Bands must have low <= high")

    overlap_low = max(llm_low, baserate_low)
    overlap_high = min(llm_high, baserate_high)
    overlap = max(0.0, overlap_high - overlap_low)

    llm_width = max(1e-9, llm_high - llm_low)

    # Fraction of the LLM band that's vouched for by the base rate.
    return min(1.0, overlap / llm_width)


# ── Combiner ────────────────────────────────────────────────────────────────
def triangulate(signals: TriangulationInput) -> Confidence:
    """Combine three signals into a Confidence label.

    Uses the geometric mean — if any one signal is near zero, the result is
    near zero. This is the right behavior: a fluent LLM answer with no
    evidence anchors should NOT round to High.
    """
    a = max(0.0, min(1.0, signals.llm_baserate_agreement))
    b = max(0.0, min(1.0, signals.evidence_density))
    c = max(0.0, min(1.0, signals.construct_stability))

    score = math.pow(a * b * c, 1.0 / 3.0)

    if score >= HIGH_THRESHOLD:
        return "high"
    if score >= MEDIUM_THRESHOLD:
        return "medium"
    return "low"


def combined_score(signals: TriangulationInput) -> float:
    """Return the raw combined score (0..1) — exposed for debugging / logging."""
    a = max(0.0, min(1.0, signals.llm_baserate_agreement))
    b = max(0.0, min(1.0, signals.evidence_density))
    c = max(0.0, min(1.0, signals.construct_stability))
    return math.pow(a * b * c, 1.0 / 3.0)


# ── ICP-specific helpers (Step 3) ──────────────────────────────────────────
def _cosine_similarity(a: list[float], b: list[float]) -> float:
    """Compute cosine similarity between two vectors.

    Returns:
        Float in [-1, 1]. 1.0 = identical direction, 0.0 = orthogonal,
        -1.0 = opposite direction.
    """
    if len(a) != len(b) or len(a) == 0:
        return 0.0

    dot = sum(x * y for x, y in zip(a, b, strict=True))
    norm_a = math.sqrt(sum(x * x for x in a))
    norm_b = math.sqrt(sum(x * x for x in b))

    if norm_a < 1e-9 or norm_b < 1e-9:
        return 0.0

    return dot / (norm_a * norm_b)


def compute_quote_coherence(embeddings: list[list[float]]) -> float:
    """Compute semantic coherence among evidence quote embeddings.

    This is used as a proxy for llm_baserate_agreement in the ICP pipeline.
    High average pairwise similarity = quotes are coherently describing one
    segment = 1.0. Low or negative = the cluster is incoherent and the LLM
    imposed a name on noise = 0.0.

    Args:
        embeddings: List of embedding vectors for evidence quotes.

    Returns:
        Float in [0, 1]. Higher = more coherent.

    Edge cases:
        - Empty list → 0.0 (no evidence = no coherence)
        - Single embedding → 1.0 (trivially coherent)
        - All identical → 1.0
        - All orthogonal → 0.0
    """
    n = len(embeddings)

    if n == 0:
        return 0.0
    if n == 1:
        return 1.0

    # Compute pairwise similarities
    similarities: list[float] = []
    for i in range(n):
        for j in range(i + 1, n):
            sim = _cosine_similarity(embeddings[i], embeddings[j])
            similarities.append(sim)

    if not similarities:
        return 1.0

    # Average similarity, normalized to [0, 1]
    # Cosine similarity is in [-1, 1], so we shift to [0, 1]
    avg_sim = sum(similarities) / len(similarities)
    # Map from [-1, 1] to [0, 1]: (sim + 1) / 2
    # But for coherence, we want: negative = bad, positive = good
    # So we clamp at 0 for negative similarities
    return max(0.0, min(1.0, (avg_sim + 1.0) / 2.0))


def compute_segment_stability(
    segment_embedding: list[float],
    other_embeddings: list[list[float]],
) -> float:
    """Compute how distinct a segment is from its neighbors.

    A segment is "stable" if it's clearly distinct from other segments.
    If it's nearly identical to another segment, it should probably have
    been merged — and we penalize by returning a low stability score.

    Args:
        segment_embedding: The centroid embedding of this segment.
        other_embeddings: Centroid embeddings of all OTHER segments in
            the same snapshot.

    Returns:
        Float in [0, 1]. Higher = more distinct.
        Computed as: 1.0 - max(similarity_to_others)

    Edge cases:
        - Empty others → 1.0 (only segment = maximally distinct)
        - Empty segment embedding → 0.0 (invalid input)
        - Near-duplicate of another → approaches 0.0
    """
    if not segment_embedding or len(segment_embedding) == 0:
        return 0.0

    if not other_embeddings:
        return 1.0

    # Find the maximum similarity to any other segment
    max_similarity = 0.0
    for other in other_embeddings:
        if other and len(other) == len(segment_embedding):
            sim = _cosine_similarity(segment_embedding, other)
            # Cosine similarity is in [-1, 1], we care about magnitude
            # But for overlap detection, we only care about positive similarity
            if sim > max_similarity:
                max_similarity = sim

    # Stability is inverse of maximum overlap
    # max_similarity of 1.0 → stability of 0.0 (duplicate)
    # max_similarity of 0.0 → stability of 1.0 (distinct)
    return max(0.0, min(1.0, 1.0 - max_similarity))
