"""Stage 3: Anchor — attach evidence quotes to each segment.

This stage:
  - For each segment, picks 2-3 snippets closest to the cluster centroid
  - Creates EvidenceQuote objects with quote, source, embedding
  - Truncates quotes to ~200 chars at sentence boundary
  - Maps source_kind to EvidenceKind enum
  - Tracks segments with <2 anchors for Low confidence trigger
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass
from urllib.parse import urlparse

import structlog

from app.pipelines.icp.cluster import ClusterResult, SnippetSource
from app.pipelines.icp.synthesize import SynthesizedSegment

log = structlog.get_logger()

# Target number of evidence quotes per segment
TARGET_ANCHORS_MIN = 2
TARGET_ANCHORS_MAX = 3

# Maximum quote length
MAX_QUOTE_LENGTH = 200


@dataclass
class EvidenceQuote:
    """An evidence quote for a segment."""

    quote: str
    source: str  # Host + identifier
    source_url: str
    kind: str  # Maps to EvidenceKind
    captured_at: str | None
    embedding: list[float]
    domain: str  # For unique domain counting


@dataclass
class AnchoredSegment:
    """A segment with attached evidence quotes."""

    name: str
    descriptor: str
    job_to_be_done: str
    drivers: list[dict[str, object]]  # [{label, weight}, ...]
    leaves: str
    centroid_embedding: list[float]
    evidence_quotes: list[EvidenceQuote]
    share_pct: int  # Estimated % of customer base
    has_few_anchors: bool  # Flag for Low confidence
    has_synthesis_issues: bool


def _cosine_similarity(a: list[float], b: list[float]) -> float:
    """Compute cosine similarity between two vectors."""
    if len(a) != len(b) or len(a) == 0:
        return 0.0

    dot = sum(x * y for x, y in zip(a, b, strict=True))
    norm_a = math.sqrt(sum(x * x for x in a))
    norm_b = math.sqrt(sum(x * x for x in b))

    if norm_a < 1e-9 or norm_b < 1e-9:
        return 0.0

    return dot / (norm_a * norm_b)


def _truncate_at_sentence_boundary(text: str, max_length: int = MAX_QUOTE_LENGTH) -> str:
    """Truncate text to max_length at a sentence boundary."""
    if len(text) <= max_length:
        return text

    # Find sentence boundaries
    sentence_endings = list(re.finditer(r"[.!?]\s+", text[:max_length]))

    if sentence_endings:
        # Take text up to the last complete sentence
        last_end = sentence_endings[-1].end()
        return text[:last_end].strip()

    # No sentence boundary found, truncate at word boundary
    truncated = text[:max_length]
    last_space = truncated.rfind(" ")
    if last_space > max_length // 2:
        return truncated[:last_space] + "..."

    return truncated + "..."


def _extract_domain(url: str) -> str:
    """Extract domain from URL."""
    try:
        parsed = urlparse(url)
        return parsed.netloc.lower().removeprefix("www.")
    except Exception:
        return "unknown"


def _format_source(source: SnippetSource) -> str:
    """Format source as 'domain + identifier'."""
    domain = _extract_domain(source.url)

    # Add a short identifier based on source_kind
    identifiers = {
        "reddit": "Reddit",
        "g2": "G2 Review",
        "capterra": "Capterra",
        "twitter": "X/Twitter",
        "press": "Press",
        "blog": "Blog",
        "other": "",
    }

    identifier = identifiers.get(source.source_kind, "")
    if identifier:
        return f"{domain} ({identifier})"
    return domain


def _map_source_kind(kind: str) -> str:
    """Map source_kind to EvidenceKind enum value."""
    valid_kinds = {"reddit", "g2", "twitter", "capterra", "review", "press", "other"}
    if kind in valid_kinds:
        return kind
    # Map aliases
    if kind == "blog":
        return "other"
    return "other"


def _select_best_anchors(
    segment: SynthesizedSegment,
    cluster_result: ClusterResult,
) -> list[tuple[int, float]]:
    """Select the best anchor indices by cosine similarity to centroid.

    Returns:
        List of (snippet_index, similarity) tuples, sorted by similarity desc.
    """
    centroid = segment.centroid_embedding
    member_indices = segment.member_indices

    if not member_indices or not centroid:
        return []

    # Compute similarity for each member
    similarities: list[tuple[int, float]] = []

    for idx in member_indices:
        if idx < len(cluster_result.all_embeddings):
            embedding = cluster_result.all_embeddings[idx]
            sim = _cosine_similarity(centroid, embedding)
            similarities.append((idx, sim))

    # Sort by similarity descending
    similarities.sort(key=lambda x: x[1], reverse=True)

    # Take top 3
    return similarities[:TARGET_ANCHORS_MAX]


async def anchor_segments(
    synthesized: list[SynthesizedSegment],
    cluster_result: ClusterResult,
) -> list[AnchoredSegment]:
    """Attach evidence quotes to synthesized segments.

    Args:
        synthesized: List of synthesized segments.
        cluster_result: Clustering result with snippets and embeddings.

    Returns:
        List of AnchoredSegment objects.
    """
    if not synthesized:
        return []

    total_snippets = cluster_result.total_snippets
    anchored: list[AnchoredSegment] = []

    for segment in synthesized:
        # Select best anchors
        best_anchors = _select_best_anchors(segment, cluster_result)

        # Build evidence quotes
        evidence_quotes: list[EvidenceQuote] = []
        seen_domains: set[str] = set()

        for idx, _sim in best_anchors:
            if idx >= len(cluster_result.all_snippets):
                continue

            snippet = cluster_result.all_snippets[idx]
            source = cluster_result.all_sources[idx]
            embedding = cluster_result.all_embeddings[idx]

            # Truncate quote
            truncated = _truncate_at_sentence_boundary(snippet)

            domain = _extract_domain(source.url)
            seen_domains.add(domain)

            evidence = EvidenceQuote(
                quote=truncated,
                source=_format_source(source),
                source_url=source.url,
                kind=_map_source_kind(source.source_kind),
                captured_at=source.published_date,
                embedding=embedding,
                domain=domain,
            )
            evidence_quotes.append(evidence)

        # Calculate share_pct from cluster size
        share_pct = 0
        if total_snippets > 0:
            share_pct = round(segment.cluster_size / total_snippets * 100)
            share_pct = max(1, min(100, share_pct))  # Clamp to 1-100

        # Check if we have enough anchors
        has_few_anchors = len(evidence_quotes) < TARGET_ANCHORS_MIN

        if has_few_anchors:
            log.info(
                "icp.anchor.few_anchors",
                segment_name=segment.name,
                n_anchors=len(evidence_quotes),
            )

        # Convert drivers to dict format
        drivers_dict = [
            {"label": d.label, "weight": d.weight}
            for d in segment.drivers
        ]

        anchored_segment = AnchoredSegment(
            name=segment.name,
            descriptor=segment.descriptor,
            job_to_be_done=segment.job_to_be_done,
            drivers=drivers_dict,
            leaves=segment.leaves,
            centroid_embedding=segment.centroid_embedding,
            evidence_quotes=evidence_quotes,
            share_pct=share_pct,
            has_few_anchors=has_few_anchors,
            has_synthesis_issues=segment.has_synthesis_issues,
        )
        anchored.append(anchored_segment)

    log.info(
        "icp.anchor.done",
        n_segments=len(anchored),
        total_anchors=sum(len(s.evidence_quotes) for s in anchored),
        segments_with_few_anchors=sum(1 for s in anchored if s.has_few_anchors),
    )

    return anchored
