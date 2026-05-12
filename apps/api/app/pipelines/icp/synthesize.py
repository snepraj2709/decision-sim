"""Stage 2: Synthesize — turn clusters into candidate segments.

This stage:
  - Takes each cluster and runs a DSPy ChainOfThought program
  - Produces structured segment data: name, descriptor, JTBD, drivers, leaves
  - Enforces citation requirement via citations_used output field
  - Targets 4-5 final segments by taking top clusters by size
  - Merges small/noise clusters if needed
"""

from __future__ import annotations

import asyncio
import math
from dataclasses import dataclass, field

import structlog

from app.config import get_settings
from app.models import ProductSnapshot
from app.pipelines.icp._filters import is_customer_evidence, is_invalid_segment_name
from app.pipelines.icp.cluster import Cluster, ClusterResult

log = structlog.get_logger()

# Target number of segments
TARGET_MIN_SEGMENTS = 3
TARGET_MAX_SEGMENTS = 5

SPECIFIC_NAME_RETRY_INSTRUCTION = (
    "You must produce a specific segment name based on the evidence provided. "
    "Do not return 'Unknown' or 'N/A'."
)


@dataclass
class DriverWeight:
    """A value driver with its relative weight."""

    label: str
    weight: float


@dataclass
class SynthesizedSegment:
    """A synthesized segment before anchoring."""

    name: str
    descriptor: str
    job_to_be_done: str
    drivers: list[DriverWeight]
    leaves: str
    citations_used: list[int]
    cluster_index: int
    cluster_size: int
    centroid_embedding: list[float]
    member_indices: list[int] = field(default_factory=list)
    # Flag if synthesis had issues (e.g., invalid citations)
    has_synthesis_issues: bool = False


def _format_snippets_for_prompt(snippets: list[str]) -> str:
    """Format snippets as numbered quotes for the LLM."""
    lines = []
    for i, snippet in enumerate(snippets):
        # Truncate long snippets
        truncated = snippet[:500] + "..." if len(snippet) > 500 else snippet
        lines.append(f"[{i}] {truncated}")
    return "\n".join(lines)


def _format_product_context(snapshot: ProductSnapshot) -> str:
    """Format product snapshot fields for context."""
    parts = []

    if snapshot.category:
        parts.append(f"Category: {snapshot.category}")
    if snapshot.value_prop:
        parts.append(f"Value Proposition: {snapshot.value_prop}")
    if snapshot.pricing:
        parts.append(f"Pricing: {snapshot.pricing}")
    if snapshot.features:
        parts.append(f"Features: {snapshot.features}")
    if snapshot.audience:
        parts.append(f"Target Audience: {snapshot.audience}")

    return "\n".join(parts) if parts else "No product context available."


def _centroid_from_embeddings(embeddings: list[list[float]]) -> list[float]:
    """Compute a normalized centroid for a filtered cluster."""
    if not embeddings:
        return []

    dimensions = len(embeddings[0])
    centroid = [
        sum(embedding[i] for embedding in embeddings) / len(embeddings)
        for i in range(dimensions)
    ]
    norm = math.sqrt(sum(value * value for value in centroid))
    if norm > 1e-9:
        centroid = [value / norm for value in centroid]
    return centroid


def _cluster_for_synthesis(
    cluster: Cluster,
    cluster_result: ClusterResult,
    cluster_index: int,
) -> Cluster | None:
    """Return the cluster after removing snippets that are not customer voice."""
    kept_indices: list[int] = []
    kept_snippets: list[str] = []
    kept_sources = []
    kept_embeddings: list[list[float]] = []

    for idx in cluster.member_indices:
        if (
            idx >= len(cluster_result.all_snippets)
            or idx >= len(cluster_result.all_sources)
            or idx >= len(cluster_result.all_embeddings)
        ):
            continue

        snippet = cluster_result.all_snippets[idx]
        source = cluster_result.all_sources[idx]
        is_customer, reason = is_customer_evidence(snippet, source.source_kind)
        if not is_customer:
            log.debug(
                "icp.synthesize.filtered_non_customer",
                cluster_index=cluster_index,
                reason=reason,
                snippet_start=snippet[:80],
            )
            continue

        kept_indices.append(idx)
        kept_snippets.append(snippet)
        kept_sources.append(source)
        kept_embeddings.append(cluster_result.all_embeddings[idx])

    if not kept_indices:
        log.warning(
            "icp.synthesize.skip_cluster_no_customer_evidence",
            cluster_index=cluster_index,
            original_size=len(cluster.member_indices),
        )
        return None

    return Cluster(
        centroid_embedding=_centroid_from_embeddings(kept_embeddings),
        member_indices=kept_indices,
        member_snippets=kept_snippets,
        member_sources=kept_sources,
    )


async def _synthesize_with_dspy(
    cluster: Cluster,
    cluster_index: int,
    product_context: str,
    prompt_addition: str = "",
) -> SynthesizedSegment:
    """Synthesize a segment using DSPy ChainOfThought."""
    import dspy  # type: ignore[import-untyped]


    settings = get_settings()

    # Configure DSPy with available LLM
    if settings.anthropic_api_key:
        lm = dspy.LM(
            model="anthropic/claude-sonnet-4-20250514",
            api_key=settings.anthropic_api_key,
            temperature=0.0,
        )
    elif settings.openai_api_key:
        lm = dspy.LM(
            model="openai/gpt-4o",
            api_key=settings.openai_api_key,
            temperature=0.0,
        )
    else:
        raise RuntimeError("No LLM API key configured")

    # Define the signature
    class SegmentSynthesis(dspy.Signature):  # type: ignore[misc]
        """Synthesize a customer segment from evidence quotes.

        You are analyzing quotes from customers/users discussing a product.
        Based on these quotes, identify a coherent customer segment.

        CRITICAL: You MUST cite specific quote numbers [0], [1], etc. when
        making claims about drivers or churn triggers. If you cannot find
        evidence in the quotes, leave that field empty rather than fabricate.
        """

        product_context: str = dspy.InputField(desc="Product information for context")
        quotes: str = dspy.InputField(desc="Numbered customer quotes to analyze")
        n_quotes: int = dspy.InputField(desc="Total number of quotes available")
        synthesis_instructions: str = dspy.InputField(
            desc="Additional hard requirements for this synthesis run"
        )

        segment_name: str = dspy.OutputField(
            desc="Short segment name, e.g. 'College student, tier-2 city' (max 50 chars)"
        )
        descriptor: str = dspy.OutputField(
            desc="1-2 sentences describing the segment's situation and needs"
        )
        job_to_be_done: str = dspy.OutputField(
            desc="The JTBD statement in plain language, no jargon. What job is this segment hiring the product to do?"
        )
        driver_1: str = dspy.OutputField(desc="Top value driver (most important)")
        driver_1_weight: float = dspy.OutputField(desc="Weight 0-1 for driver 1")
        driver_2: str = dspy.OutputField(desc="Second value driver")
        driver_2_weight: float = dspy.OutputField(desc="Weight 0-1 for driver 2")
        driver_3: str = dspy.OutputField(desc="Third value driver")
        driver_3_weight: float = dspy.OutputField(desc="Weight 0-1 for driver 3")
        leaves_trigger: str = dspy.OutputField(
            desc="1 sentence on what triggers churn for this segment"
        )
        citations_used: str = dspy.OutputField(
            desc="Comma-separated list of quote indices you cited, e.g. '0,2,5'"
        )

    # Prepare inputs
    quotes_text = _format_snippets_for_prompt(cluster.member_snippets)

    # Run synthesis
    def _run_predict() -> dspy.Prediction:
        with dspy.context(lm=lm):
            predictor = dspy.ChainOfThought(SegmentSynthesis)
            return predictor(
                product_context=product_context,
                quotes=quotes_text,
                n_quotes=len(cluster.member_snippets),
                synthesis_instructions=prompt_addition,
            )

    result = await asyncio.to_thread(_run_predict)

    # Parse citations
    citations: list[int] = []
    has_issues = False
    try:
        if result.citations_used:
            raw_citations = result.citations_used.replace(" ", "").split(",")
            for c in raw_citations:
                if c.strip().isdigit():
                    idx = int(c.strip())
                    if 0 <= idx < len(cluster.member_snippets):
                        citations.append(idx)
                    else:
                        has_issues = True
                        log.warning(
                            "icp.synthesize.invalid_citation",
                            citation=idx,
                            max_idx=len(cluster.member_snippets) - 1,
                        )
    except Exception as e:
        log.warning("icp.synthesize.citation_parse_error", error=str(e))
        has_issues = True

    # Parse drivers
    drivers: list[DriverWeight] = []
    try:
        if result.driver_1:
            w1 = float(result.driver_1_weight) if result.driver_1_weight else 0.8
            drivers.append(DriverWeight(label=result.driver_1, weight=min(1.0, max(0.0, w1))))
        if result.driver_2:
            w2 = float(result.driver_2_weight) if result.driver_2_weight else 0.5
            drivers.append(DriverWeight(label=result.driver_2, weight=min(1.0, max(0.0, w2))))
        if result.driver_3:
            w3 = float(result.driver_3_weight) if result.driver_3_weight else 0.3
            drivers.append(DriverWeight(label=result.driver_3, weight=min(1.0, max(0.0, w3))))
    except (ValueError, TypeError) as e:
        log.warning("icp.synthesize.driver_parse_error", error=str(e))
        has_issues = True

    segment_name = str(result.segment_name).strip()[:100] if result.segment_name else "Unknown"
    descriptor = str(result.descriptor).strip()[:500] if result.descriptor else ""
    job_to_be_done = str(result.job_to_be_done).strip()[:500] if result.job_to_be_done else ""
    leaves = str(result.leaves_trigger).strip()[:300] if result.leaves_trigger else ""

    if (
        is_invalid_segment_name(segment_name)
        or not descriptor
        or not job_to_be_done
        or not drivers
        or not citations
    ):
        has_issues = True

    return SynthesizedSegment(
        name=segment_name,
        descriptor=descriptor,
        job_to_be_done=job_to_be_done,
        drivers=drivers,
        leaves=leaves,
        citations_used=citations,
        cluster_index=cluster_index,
        cluster_size=len(cluster.member_indices),
        centroid_embedding=cluster.centroid_embedding,
        member_indices=cluster.member_indices,
        has_synthesis_issues=has_issues,
    )


async def run_synthesize(
    cluster_result: ClusterResult,
    jtbd_constraint: str | None = None,
    naming_constraint: str | None = None,
) -> list[SynthesizedSegment]:
    """Agent entry point for the synthesize stage.

    Takes ClusterResult directly (no ProductSnapshot required).
    Optional constraints are appended to every synthesis prompt.

    Args:
        cluster_result: Output of run_cluster.
        jtbd_constraint: Hard requirement injected when JTBD rubric fails on retry.
        naming_constraint: Hard requirement injected when naming rubric fails on retry.
    """
    if not cluster_result.clusters:
        log.info("icp.run_synthesize.no_clusters")
        return []

    prompt_parts = [p for p in [jtbd_constraint, naming_constraint] if p]
    prompt_addition = " ".join(prompt_parts)

    segments: list[SynthesizedSegment] = []

    for i, cluster in enumerate(cluster_result.clusters):
        if len(segments) >= TARGET_MAX_SEGMENTS:
            break

        synthesis_cluster = _cluster_for_synthesis(cluster, cluster_result, i)
        if synthesis_cluster is None:
            continue

        try:
            segment = await _synthesize_with_dspy(
                synthesis_cluster, i, product_context="", prompt_addition=prompt_addition
            )
            if is_invalid_segment_name(segment.name):
                log.warning(
                    "icp.run_synthesize.invalid_name_retry",
                    cluster_index=i,
                    segment_name=segment.name,
                )
                segment = await _synthesize_with_dspy(
                    synthesis_cluster,
                    i,
                    product_context="",
                    prompt_addition=(
                        (prompt_addition + " " if prompt_addition else "")
                        + SPECIFIC_NAME_RETRY_INSTRUCTION
                    ),
                )

            if is_invalid_segment_name(segment.name):
                log.warning(
                    "icp.run_synthesize.skip_invalid_name",
                    cluster_index=i,
                    segment_name=segment.name,
                )
                continue

            segments.append(segment)
        except Exception as e:
            log.error("icp.run_synthesize.cluster_failed", cluster_index=i, error=str(e))

    log.info("icp.run_synthesize.done", n_segments=len(segments))
    return segments


async def synthesize_segments(
    snapshot: ProductSnapshot,
    cluster_result: ClusterResult,
) -> list[SynthesizedSegment]:
    """Synthesize segments from clusters.

    Args:
        snapshot: ProductSnapshot for product context.
        cluster_result: Result from clustering stage.

    Returns:
        List of SynthesizedSegment objects, sorted by cluster size.
    """
    if not cluster_result.clusters:
        log.info("icp.synthesize.no_clusters", snapshot_id=str(snapshot.id))
        return []

    product_context = _format_product_context(snapshot)

    log.info(
        "icp.synthesize.start",
        snapshot_id=str(snapshot.id),
        n_clusters=len(cluster_result.clusters),
    )

    # Synthesize each cluster
    segments: list[SynthesizedSegment] = []

    for i, cluster in enumerate(cluster_result.clusters):
        if len(segments) >= TARGET_MAX_SEGMENTS:
            break

        synthesis_cluster = _cluster_for_synthesis(cluster, cluster_result, i)
        if synthesis_cluster is None:
            continue

        try:
            segment = await _synthesize_with_dspy(synthesis_cluster, i, product_context)
            if is_invalid_segment_name(segment.name):
                log.warning(
                    "icp.synthesize.invalid_name_retry",
                    cluster_index=i,
                    segment_name=segment.name,
                )
                segment = await _synthesize_with_dspy(
                    synthesis_cluster,
                    i,
                    product_context,
                    prompt_addition=SPECIFIC_NAME_RETRY_INSTRUCTION,
                )

            if is_invalid_segment_name(segment.name):
                log.warning(
                    "icp.synthesize.skip_invalid_name",
                    cluster_index=i,
                    segment_name=segment.name,
                )
                continue

            segments.append(segment)
            log.info(
                "icp.synthesize.cluster_done",
                cluster_index=i,
                segment_name=segment.name,
                n_citations=len(segment.citations_used),
            )
        except Exception as e:
            log.error(
                "icp.synthesize.cluster_failed",
                cluster_index=i,
                error=str(e),
            )

    # If we have fewer than TARGET_MIN_SEGMENTS and there are noise points,
    # we could potentially create an "Other" segment, but per spec we ship what we have
    if len(segments) < TARGET_MIN_SEGMENTS:
        log.info(
            "icp.synthesize.few_segments",
            snapshot_id=str(snapshot.id),
            n_segments=len(segments),
        )

    log.info(
        "icp.synthesize.done",
        snapshot_id=str(snapshot.id),
        n_segments=len(segments),
    )

    return segments
