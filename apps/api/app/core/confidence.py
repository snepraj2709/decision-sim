"""Confidence — the engine's epistemic backbone.

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

    score = (a * b * c) ** (1 / 3)

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
    return (a * b * c) ** (1 / 3)
