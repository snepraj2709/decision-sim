"""Stage 4: Score & Persist — compute confidence and write to database.

This stage:
  - For each segment, computes confidence using triangulate():
    1. evidence_density: count UNIQUE DOMAINS (not URLs)
    2. llm_baserate_agreement: use compute_quote_coherence() as proxy
    3. construct_stability: use compute_segment_stability() with centroids
  - Idempotency: DELETE existing segments for snapshot_id, then INSERT new
  - Persist Segment rows with share_pct and confidence
  - Persist Evidence rows under each segment
"""

from __future__ import annotations

import contextlib
import math
import uuid
from dataclasses import replace
from datetime import datetime

import structlog
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.core.confidence import (
    TriangulationInput,
    compute_quote_coherence,
    compute_segment_stability,
    evidence_density_from_count,
    triangulate,
)
from app.models import Evidence, ProductSnapshot, Segment
from app.pipelines.icp._filters import (
    INVALID_SEGMENT_NAMES as _INVALID_SEGMENT_NAMES,
)
from app.pipelines.icp._filters import (
    is_invalid_segment_name,
)
from app.pipelines.icp.anchor import AnchoredSegment

log = structlog.get_logger()

SegmentDraft = AnchoredSegment
MAX_SEGMENT_NAME_LENGTH = 60
INVALID_SEGMENT_NAMES = _INVALID_SEGMENT_NAMES


def _count_unique_domains(segment: AnchoredSegment) -> int:
    """Count unique domains in segment's evidence quotes.

    This is stricter than counting URLs — three quotes from reddit.com
    count as one domain, not three.
    """
    domains: set[str] = set()
    for evidence in segment.evidence_quotes:
        if evidence.domain:
            domains.add(evidence.domain.lower())
    return len(domains)


def _snapshot_is_low_confidence(snapshot: ProductSnapshot | None) -> bool:
    """Return true when core Step 2 product understanding is low confidence."""
    if snapshot is None:
        return False

    return all(
        confidence == "low"
        for confidence in (
            snapshot.category_confidence,
            snapshot.value_prop_confidence,
            snapshot.audience_confidence,
        )
    )


def is_valid_segment(draft: SegmentDraft) -> tuple[bool, str]:
    """Return (is_valid, reason) for a segment draft before persistence."""
    if is_invalid_segment_name(draft.name):
        return False, "invalid_name"

    if not draft.job_to_be_done or not draft.job_to_be_done.strip():
        return False, "empty_job_to_be_done"

    invalid_jtbd_markers = (
        "not enough information",
        "insufficient data",
        "cannot be determined",
    )
    if any(marker in draft.job_to_be_done.lower() for marker in invalid_jtbd_markers):
        return False, "insufficient_job_to_be_done"

    if not draft.drivers:
        return False, "empty_drivers"

    driver_labels = [
        driver.get("label")
        for driver in draft.drivers
        if isinstance(driver.get("label"), str)
    ]
    if not driver_labels or all(
        is_invalid_segment_name(str(label)) or str(label).strip().lower() in {"na", "none"}
        for label in driver_labels
    ):
        return False, "empty_drivers"

    return True, ""


def _cosine_similarity(a: list[float], b: list[float]) -> float:
    """Compute cosine similarity between two vectors."""
    if not a or not b or len(a) != len(b):
        return 0.0

    dot = sum(x * y for x, y in zip(a, b, strict=True))
    norm_a = math.sqrt(sum(x * x for x in a))
    norm_b = math.sqrt(sum(x * x for x in b))
    if norm_a < 1e-9 or norm_b < 1e-9:
        return 0.0
    return dot / (norm_a * norm_b)


def _merge_driver_lists(
    primary: list[dict[str, object]],
    secondary: list[dict[str, object]],
) -> list[dict[str, object]]:
    """Combine driver lists by label while preserving first occurrence."""
    merged: list[dict[str, object]] = []
    seen: set[str] = set()

    for driver in [*primary, *secondary]:
        label = driver.get("label")
        key = label.strip().lower() if isinstance(label, str) else ""
        if not key or key in seen:
            continue
        seen.add(key)
        merged.append(driver)

    return merged


def merge_near_duplicate_segments(
    drafts: list[SegmentDraft],
    centroid_embeddings: list[list[float]],
    similarity_threshold: float = 0.92,
) -> list[SegmentDraft]:
    """Merge segments whose centroids are too similar."""
    if len(drafts) < 2:
        return drafts

    embeddings = centroid_embeddings
    if len(embeddings) != len(drafts):
        embeddings = [draft.centroid_embedding for draft in drafts]

    pairs = sorted(
        zip(drafts, embeddings, strict=True),
        key=lambda pair: pair[0].share_pct,
        reverse=True,
    )
    merged: list[tuple[SegmentDraft, list[float]]] = []

    for draft, centroid in pairs:
        for existing_index, (existing, existing_centroid) in enumerate(merged):
            similarity = _cosine_similarity(centroid, existing_centroid)
            if similarity <= similarity_threshold:
                continue

            merged_segment = replace(
                existing,
                share_pct=existing.share_pct + draft.share_pct,
                drivers=_merge_driver_lists(existing.drivers, draft.drivers),
                has_synthesis_issues=(
                    existing.has_synthesis_issues or draft.has_synthesis_issues
                ),
            )
            merged[existing_index] = (merged_segment, existing_centroid)
            log.warning(
                "score.merged_near_duplicate_segments",
                kept_name=existing.name,
                merged_name=draft.name,
                similarity=round(similarity, 4),
            )
            break
        else:
            merged.append((draft, centroid))

    return [segment for segment, _centroid in merged]


def truncate_segment_name(name: str, max_length: int = MAX_SEGMENT_NAME_LENGTH) -> str:
    """Truncate a segment name at the last word boundary before max_length."""
    if len(name) <= max_length:
        return name

    if name[max_length:max_length + 1].isspace():
        truncated = name[:max_length].rstrip()
    else:
        truncated = name[:max_length]
        last_space = truncated.rfind(" ")
        if last_space > 0:
            truncated = truncated[:last_space]

    log.warning(
        "score.segment_name_truncated",
        original_name=name,
        truncated_name=truncated,
        max_length=max_length,
    )
    return truncated


def _hypothesis_name(name: str) -> str:
    """Mark a segment name as speculative without double-prefixing."""
    if name.startswith("Hypothesis:"):
        return truncate_segment_name(name)
    return truncate_segment_name(f"Hypothesis: {name}")


def _normalized_share_percentages(segments: list[AnchoredSegment]) -> list[int]:
    """Normalize segment share percentages so persisted rows sum to 100."""
    if not segments:
        return []

    total = sum(max(segment.share_pct, 0) for segment in segments)
    if total <= 0:
        base = 100 // len(segments)
        shares = [base for _segment in segments]
        shares[0] += 100 - sum(shares)
        return shares

    exact_shares = [
        max(segment.share_pct, 0) / total * 100
        for segment in segments
    ]
    shares = [max(1, int(value)) for value in exact_shares]
    diff = 100 - sum(shares)

    if diff > 0:
        order = sorted(
            range(len(shares)),
            key=lambda index: exact_shares[index] - int(exact_shares[index]),
            reverse=True,
        )
        for index in order[:diff]:
            shares[index] += 1
    elif diff < 0:
        order = sorted(range(len(shares)), key=lambda index: shares[index], reverse=True)
        remaining = -diff
        for index in order:
            if remaining == 0:
                break
            removable = min(remaining, shares[index] - 1)
            shares[index] -= removable
            remaining -= removable

    return shares


def _prepare_segments_for_persistence(
    anchored_segments: list[AnchoredSegment],
) -> list[AnchoredSegment]:
    """Drop invalid drafts and merge near-duplicates before scoring."""
    valid_segments: list[AnchoredSegment] = []

    for segment in anchored_segments:
        is_valid, reason = is_valid_segment(segment)
        if not is_valid:
            log.warning(
                "score.segment_dropped_invalid_synthesis",
                segment_name=segment.name,
                reason=reason,
            )
            continue

        if not segment.evidence_quotes:
            log.warning(
                "score.segment_dropped_no_evidence",
                segment_name=segment.name,
            )
            continue

        valid_segments.append(segment)

    return merge_near_duplicate_segments(
        valid_segments,
        [segment.centroid_embedding for segment in valid_segments],
    )


def _compute_segment_confidence(
    segment: AnchoredSegment,
    other_centroids: list[list[float]],
    settings_min_sources: int,
    upstream_snapshot_low_confidence: bool = False,
) -> str:
    """Compute confidence for a segment using triangulation.

    Args:
        segment: The anchored segment with evidence quotes.
        other_centroids: Centroid embeddings of OTHER segments (for stability).
        settings_min_sources: Minimum sources for high confidence.

    Returns:
        Confidence label: "high", "medium", or "low".
    """
    # Signal 1: Evidence density (unique domains)
    n_domains = _count_unique_domains(segment)
    evidence_density = evidence_density_from_count(n_domains, min_for_high=settings_min_sources)

    # Signal 2: Quote coherence (proxy for baserate agreement)
    evidence_embeddings = [e.embedding for e in segment.evidence_quotes if e.embedding]
    quote_coherence = compute_quote_coherence(evidence_embeddings)

    # Signal 3: Construct stability (distinctness from other segments)
    stability = compute_segment_stability(segment.centroid_embedding, other_centroids)

    # Apply penalties for synthesis/anchor issues
    if segment.has_synthesis_issues:
        stability = min(stability, 0.5)  # Cap stability if synthesis had issues

    if segment.has_few_anchors:
        evidence_density = min(evidence_density, 0.3)  # Cap density if few anchors

    signals = TriangulationInput(
        llm_baserate_agreement=quote_coherence,
        evidence_density=evidence_density,
        construct_stability=stability,
    )

    confidence = triangulate(signals)
    if upstream_snapshot_low_confidence:
        confidence = "low"

    log.debug(
        "icp.score.segment",
        segment_name=segment.name,
        n_domains=n_domains,
        evidence_density=round(evidence_density, 3),
        quote_coherence=round(quote_coherence, 3),
        stability=round(stability, 3),
        upstream_snapshot_low_confidence=upstream_snapshot_low_confidence,
        confidence=confidence,
    )

    return confidence


async def _delete_existing_segments(snapshot_id: uuid.UUID, db: AsyncSession) -> int:
    """Delete existing segments for a snapshot and return the deleted count."""
    existing_stmt = select(Segment.id).where(Segment.snapshot_id == snapshot_id)
    existing_result = await db.execute(existing_stmt)
    existing_ids = [row[0] for row in existing_result.fetchall()]

    if existing_ids:
        log.info(
            "icp.score.replacing_segments",
            snapshot_id=str(snapshot_id),
            n_existing=len(existing_ids),
        )
        delete_stmt = delete(Segment).where(Segment.snapshot_id == snapshot_id)
        await db.execute(delete_stmt)

    return len(existing_ids)


async def score_and_persist(
    snapshot_id: uuid.UUID,
    anchored_segments: list[AnchoredSegment],
    db: AsyncSession,
    snapshot: ProductSnapshot | None = None,
) -> list[uuid.UUID]:
    """Score segments and persist to database.

    This is IDEMPOTENT: running twice on the same snapshot_id replaces
    the prior segment set. Evidence rows are cascaded via FK.

    Args:
        snapshot_id: The ProductSnapshot ID.
        anchored_segments: List of anchored segments to persist.
        db: Async database session.

    Returns:
        List of newly-created Segment IDs.
    """
    settings = get_settings()
    upstream_snapshot_low_confidence = _snapshot_is_low_confidence(snapshot)

    anchored_segments = _prepare_segments_for_persistence(anchored_segments)

    if not anchored_segments:
        log.info("icp.score.no_segments", snapshot_id=str(snapshot_id))
        await _delete_existing_segments(snapshot_id, db)
        await db.commit()
        return []

    # Collect all centroids for stability calculation
    all_centroids = [s.centroid_embedding for s in anchored_segments]

    # Compute confidence for each segment
    segment_confidences: list[str] = []
    for i, segment in enumerate(anchored_segments):
        # Other centroids = all except this one
        other_centroids = all_centroids[:i] + all_centroids[i + 1 :]
        confidence = _compute_segment_confidence(
            segment,
            other_centroids,
            settings.min_sources_for_high_confidence,
            upstream_snapshot_low_confidence=upstream_snapshot_low_confidence,
        )
        segment_confidences.append(confidence)

    all_low_confidence = all(confidence == "low" for confidence in segment_confidences)
    if all_low_confidence and len(anchored_segments) > 3:
        paired = sorted(
            zip(anchored_segments, segment_confidences, strict=True),
            key=lambda pair: pair[0].share_pct,
            reverse=True,
        )[:3]
        anchored_segments = [pair[0] for pair in paired]
        segment_confidences = [pair[1] for pair in paired]
        log.info(
            "icp.score.capped_hypothesis_segments",
            snapshot_id=str(snapshot_id),
            n_segments=len(anchored_segments),
        )

    normalized_shares = _normalized_share_percentages(anchored_segments)

    # Begin transaction: delete old segments, insert new ones
    # CASCADE will delete evidence rows automatically

    # First, delete existing segments (cascade deletes evidence)
    await _delete_existing_segments(snapshot_id, db)

    # Insert new segments
    segment_ids: list[uuid.UUID] = []

    for segment, confidence, share_pct in zip(
        anchored_segments,
        segment_confidences,
        normalized_shares,
        strict=True,
    ):
        segment_name = _hypothesis_name(segment.name) if all_low_confidence else segment.name
        segment_name = truncate_segment_name(segment_name)

        # Create Segment row
        segment_row = Segment(
            snapshot_id=snapshot_id,
            name=segment_name,
            descriptor=segment.descriptor,
            job_to_be_done=segment.job_to_be_done,
            share_pct=share_pct,
            confidence=confidence,
            drivers=segment.drivers,
            leaves=segment.leaves,
            embedding=segment.centroid_embedding,
        )
        db.add(segment_row)
        await db.flush()  # Get the ID

        segment_ids.append(segment_row.id)

        # Create Evidence rows
        for evidence in segment.evidence_quotes:
            # Parse captured_at if available
            captured_at: datetime | None = None
            if evidence.captured_at:
                with contextlib.suppress(ValueError):
                    captured_at = datetime.fromisoformat(
                        evidence.captured_at.replace("Z", "+00:00")
                    )

            evidence_row = Evidence(
                segment_id=segment_row.id,
                quote=evidence.quote,
                source=evidence.source,
                source_url=evidence.source_url,
                kind=evidence.kind,
                captured_at=captured_at,
                embedding=evidence.embedding,
            )
            db.add(evidence_row)

    await db.commit()

    # Log summary
    confidence_counts = {"high": 0, "medium": 0, "low": 0}
    for conf in segment_confidences:
        confidence_counts[conf] = confidence_counts.get(conf, 0) + 1

    log.info(
        "icp.score.done",
        snapshot_id=str(snapshot_id),
        n_segments=len(segment_ids),
        confidence_distribution=confidence_counts,
    )

    return segment_ids
