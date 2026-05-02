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
import uuid
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
from app.models import Evidence, Segment
from app.pipelines.icp.anchor import AnchoredSegment

log = structlog.get_logger()


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


def _compute_segment_confidence(
    segment: AnchoredSegment,
    other_centroids: list[list[float]],
    settings_min_sources: int,
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

    log.debug(
        "icp.score.segment",
        segment_name=segment.name,
        n_domains=n_domains,
        evidence_density=round(evidence_density, 3),
        quote_coherence=round(quote_coherence, 3),
        stability=round(stability, 3),
        confidence=confidence,
    )

    return confidence


async def score_and_persist(
    snapshot_id: uuid.UUID,
    anchored_segments: list[AnchoredSegment],
    db: AsyncSession,
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

    if not anchored_segments:
        log.info("icp.score.no_segments", snapshot_id=str(snapshot_id))
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
        )
        segment_confidences.append(confidence)

    # Begin transaction: delete old segments, insert new ones
    # CASCADE will delete evidence rows automatically

    # First, check if there are existing segments
    existing_stmt = select(Segment.id).where(Segment.snapshot_id == snapshot_id)
    existing_result = await db.execute(existing_stmt)
    existing_ids = [row[0] for row in existing_result.fetchall()]

    if existing_ids:
        log.info(
            "icp.score.replacing_segments",
            snapshot_id=str(snapshot_id),
            n_existing=len(existing_ids),
        )
        # Delete existing segments (cascade deletes evidence)
        delete_stmt = delete(Segment).where(Segment.snapshot_id == snapshot_id)
        await db.execute(delete_stmt)

    # Insert new segments
    segment_ids: list[uuid.UUID] = []

    for segment, confidence in zip(anchored_segments, segment_confidences, strict=True):
        # Create Segment row
        segment_row = Segment(
            snapshot_id=snapshot_id,
            name=segment.name,
            descriptor=segment.descriptor,
            job_to_be_done=segment.job_to_be_done,
            share_pct=segment.share_pct,
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
