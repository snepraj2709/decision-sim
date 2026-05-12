"""
Function-based rubric dimension evaluators.

These are deterministic, zero-cost checks that run before any LLM-as-judge call.
Always run these first. Only call Haiku if function-based checks are insufficient.
"""

from __future__ import annotations

import math
from datetime import UTC, datetime, timedelta
from typing import Any
from urllib.parse import urlparse

from app.agents.rubrics.base import RubricDimension
from app.pipelines.icp._filters import is_customer_evidence  # reuse existing filter


def check_source_diversity(
    search_results: list[Any], threshold: float = 0.40
) -> RubricDimension:
    """
    Unique root domains / total results must exceed threshold.
    A low ratio means all evidence comes from one or two aggregators (e.g. all G2).
    """
    if not search_results:
        return RubricDimension(
            name="source_diversity",
            passed=False,
            score=0.0,
            is_hard_gate=False,
            reason="No search results — snapshot has no external evidence",
        )
    unique_domains = {
        urlparse(r.url).netloc.replace("www.", "")
        for r in search_results
        if hasattr(r, "url") and r.url
    }
    score = len(unique_domains) / len(search_results)
    passed = score >= threshold
    return RubricDimension(
        name="source_diversity",
        passed=passed,
        score=score,
        is_hard_gate=False,   # soft gate — thin evidence doesn't block, it flags
        reason=(
            f"{len(unique_domains)} unique domains across {len(search_results)} results"
            if passed
            else f"Only {len(unique_domains)} unique domains — low source diversity"
        ),
    )


def check_recency(
    search_results: list[Any], threshold: float = 0.50, months: int = 18
) -> RubricDimension:
    """
    Fraction of results published within the last N months must exceed threshold.
    """
    if not search_results:
        return RubricDimension(
            name="recency_score",
            passed=False,
            score=0.0,
            is_hard_gate=False,
            reason="No search results to evaluate recency",
        )
    cutoff = datetime.now(tz=UTC) - timedelta(days=months * 30)
    recent = [
        r
        for r in search_results
        if hasattr(r, "published_date")
        and r.published_date
        and r.published_date > cutoff
    ]
    score = len(recent) / len(search_results)
    passed = score >= threshold
    return RubricDimension(
        name="recency_score",
        passed=passed,
        score=score,
        is_hard_gate=False,
        reason=(
            f"{len(recent)}/{len(search_results)} results within {months} months"
            if passed
            else f"Only {len(recent)}/{len(search_results)} results are recent"
        ),
    )


def check_customer_voice_ratio(
    snippets: list[str], threshold: float = 0.30
) -> RubricDimension:
    """
    Fraction of snippets that pass is_customer_evidence() must exceed threshold.
    Uses existing _filters.py logic — no new filtering code needed.
    Source kind is unknown at this call site, so we pass empty string to skip
    source-kind filtering and rely on content-based checks only.
    """
    if not snippets:
        return RubricDimension(
            name="customer_voice_ratio",
            passed=False,
            score=0.0,
            is_hard_gate=False,
            reason="No snippets to evaluate",
        )
    customer_snippets = [s for s in snippets if is_customer_evidence(s, "")[0]]
    score = len(customer_snippets) / len(snippets)
    passed = score >= threshold
    return RubricDimension(
        name="customer_voice_ratio",
        passed=passed,
        score=score,
        is_hard_gate=False,
        reason=(
            f"{len(customer_snippets)}/{len(snippets)} snippets are customer voice"
            if passed
            else f"Only {len(customer_snippets)}/{len(snippets)} snippets are genuine customer voice"
        ),
    )


def _evidence_list(s: Any) -> list[Any]:
    """Return the evidence collection from either an ORM Segment or AnchoredSegment."""
    ev = getattr(s, "evidence", None)
    if ev is not None:
        return list(ev)
    return list(getattr(s, "evidence_quotes", None) or [])


def check_anchor_density(
    segments: list[Any], min_anchors: int = 2
) -> RubricDimension:
    """
    Every segment must have at least min_anchors unique evidence quotes.
    This is already enforced by the ICP anchor stage, but we recheck here.
    Works with both ORM Segment (evidence) and AnchoredSegment (evidence_quotes).
    """
    thin_segments = [
        s.name
        for s in segments
        if len(_evidence_list(s)) < min_anchors
    ]
    passed = len(thin_segments) == 0
    score = 1.0 if passed else (len(segments) - len(thin_segments)) / len(segments)
    return RubricDimension(
        name="anchor_density",
        passed=passed,
        score=score,
        is_hard_gate=True,  # hard gate — segments without evidence are unreliable
        reason=(
            f"All {len(segments)} segments have ≥ {min_anchors} anchors"
            if passed
            else f"Thin segments: {', '.join(thin_segments)}"
        ),
    )


def check_segment_distinctness(
    segment_embeddings: list[list[float]], max_similarity: float = 0.92
) -> RubricDimension:
    """
    Checks that no two segments are too similar (would be merged by dedup logic).
    Reuses compute_segment_stability from confidence.py.
    """
    # Import here to avoid circular imports
    from app.core.confidence import compute_segment_stability

    if len(segment_embeddings) < 2:
        return RubricDimension(
            name="segment_distinctness",
            passed=True,
            score=1.0,
            reason="Only one segment — distinctness check not applicable",
        )

    scores = []
    for i, emb in enumerate(segment_embeddings):
        others = segment_embeddings[:i] + segment_embeddings[i + 1 :]
        stability = compute_segment_stability(emb, others)
        scores.append(stability)

    min_score = min(scores)
    # stability is cosine distance from nearest neighbor — higher is more distinct
    # max_similarity is the UPPER BOUND on cosine similarity (0.92 means very similar)
    # convert: if cosine_distance < (1 - max_similarity), segments are too similar
    threshold = 1.0 - max_similarity  # e.g. 0.08 distance = 0.92 similarity
    passed = min_score >= threshold
    return RubricDimension(
        name="segment_distinctness",
        passed=passed,
        score=min_score,
        is_hard_gate=True,
        reason=(
            f"Min inter-segment distance: {min_score:.3f}"
            if passed
            else f"Segments too similar (min distance {min_score:.3f} < threshold {threshold:.3f})"
        ),
    )


def check_calibration_alignment(
    churn_range_low: int,
    churn_range_high: int,
    option_type: str,
    calibration_rate: float | None,
    calibration_n: int = 0,
    sigma_multiplier: float = 2.0,
) -> RubricDimension:
    """
    Check if the predicted churn range overlaps with [base_rate +/- 2 sigma].
    If calibration_n < 5, treat as soft gate (data too sparse to be authoritative).
    sigma here is approximated as sqrt(rate * (1-rate) / max(n, 1)).
    """
    if calibration_rate is None:
        return RubricDimension(
            name="calibration_alignment",
            passed=True,
            score=1.0,
            is_hard_gate=False,
            reason=f"No base rate available for option_type={option_type} — skipping",
        )

    n = max(calibration_n, 1)
    sigma = math.sqrt(calibration_rate * (1 - calibration_rate) / n)
    lower_bound = max(0.0, (calibration_rate - sigma_multiplier * sigma) * 100)
    upper_bound = min(100.0, (calibration_rate + sigma_multiplier * sigma) * 100)

    # Check if ranges overlap
    overlap = churn_range_low <= upper_bound and churn_range_high >= lower_bound

    is_hard = calibration_n >= 5  # only hard gate if we have enough data
    score = 1.0 if overlap else max(
        0.0, 1.0 - abs(churn_range_low - upper_bound) / 100
    )
    return RubricDimension(
        name="calibration_alignment",
        passed=overlap,
        score=score,
        is_hard_gate=is_hard,
        reason=(
            f"Range [{churn_range_low}-{churn_range_high}%] within base rate "
            f"[{lower_bound:.0f}-{upper_bound:.0f}%] (n={calibration_n})"
        )
        if overlap
        else (
            f"Range [{churn_range_low}-{churn_range_high}%] outside base rate "
            f"[{lower_bound:.0f}-{upper_bound:.0f}%] (n={calibration_n})"
        ),
    )
