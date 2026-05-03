"""Stage 3 — Confidence scoring + devil's advocate.

Computes a confidence label for every cell via triangulate(), then
generates devil's advocate challenges for Low and Medium cells.
"""

from __future__ import annotations

import asyncio
import uuid
from dataclasses import dataclass

import structlog

from app.core.confidence import (
    TriangulationInput,
    compute_segment_stability,
    evidence_density_from_count,
    triangulate,
)
from app.models import Segment
from app.pipelines.simulation.parse import ParsedOption
from app.pipelines.simulation.react import ReactionResult

log = structlog.get_logger()

# BASE_RATES are Step 4 placeholders.
# Step 6 replaces with calibrated rates from outcome tracking.
BASE_RATES: dict[str, dict[str, float]] = {
    "pricing": {
        "positive": 0.10,
        "neutral": 0.25,
        "negative": 0.55,
        "mixed": 0.10,
    },
    "feature": {
        "positive": 0.45,
        "neutral": 0.30,
        "negative": 0.15,
        "mixed": 0.10,
    },
    "copy": {
        "positive": 0.20,
        "neutral": 0.50,
        "negative": 0.15,
        "mixed": 0.15,
    },
    "bundling": {
        "positive": 0.25,
        "neutral": 0.35,
        "negative": 0.25,
        "mixed": 0.15,
    },
    "onboarding": {
        "positive": 0.35,
        "neutral": 0.40,
        "negative": 0.15,
        "mixed": 0.10,
    },
}


@dataclass
class CellResult:
    segment_id: uuid.UUID
    option_label: str
    reaction_sentiment: str
    adoption_probability: float
    churn_probability: float
    top_concern: str
    time_horizon: str
    reasoning_trace: str
    confidence: str
    devil_advocate: str
    smallest_experiment: str


def _embedding_as_list(embedding: object) -> list[float]:
    """Normalize pgvector/numpy/list embeddings before confidence math."""
    if embedding is None:
        return []
    if hasattr(embedding, "tolist"):
        value = embedding.tolist()
        if isinstance(value, list):
            return [float(x) for x in value]
    if isinstance(embedding, list):
        return [float(x) for x in embedding]
    return []


def _baserate_agreement(option_type: str, sentiment: str) -> float:
    rates = BASE_RATES.get(option_type, BASE_RATES["feature"])
    return rates.get(sentiment, 0.25)


def _churn_range(churn_probability: float) -> tuple[int, int]:
    low = int(max(0.0, churn_probability - 0.10) * 100)
    high = int(min(1.0, churn_probability + 0.10) * 100)
    return low, high


def _call_devils_advocate(
    segment_name: str,
    reaction_summary: str,
    option_description: str,
) -> tuple[str, str]:
    import dspy  # type: ignore[import-untyped]

    from app.config import get_settings

    settings = get_settings()
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

    class DevilsAdvocate(dspy.Signature):  # type: ignore[misc]
        """Generate a devil's advocate challenge for a low-confidence simulation cell."""

        segment_name: str = dspy.InputField()
        reaction_summary: str = dspy.InputField(
            desc="A brief description of the simulated reaction"
        )
        option_description: str = dspy.InputField()

        devil_advocate: str = dspy.OutputField(
            desc="What would change my mind about this reaction? Be specific."
        )
        smallest_experiment: str = dspy.OutputField(
            desc=(
                "The smallest invalidating test a PM could run in 2 weeks or less. "
                "e.g., 'Run a 50-user price survey'"
            )
        )

    with dspy.context(lm=lm):
        predictor = dspy.Predict(DevilsAdvocate)
        result = predictor(
            segment_name=segment_name,
            reaction_summary=reaction_summary,
            option_description=option_description,
        )

    devil = str(result.devil_advocate or "").strip()
    experiment = str(result.smallest_experiment or "").strip()
    return devil, experiment


async def _generate_devils_advocate(
    reaction: ReactionResult,
    segment_name: str,
    option_description: str,
) -> tuple[str, str]:
    summary = (
        f"{segment_name} reacted {reaction.reaction_sentiment} "
        f"(churn: {reaction.churn_probability:.0%}). "
        f"Top concern: {reaction.top_concern}"
    )
    try:
        return await asyncio.to_thread(
            _call_devils_advocate, segment_name, summary, option_description
        )
    except Exception as exc:
        log.error(
            "simulation.score.devils_advocate_failed",
            segment_id=str(reaction.segment_id),
            option_label=reaction.option_label,
            error=str(exc),
        )
        return "", ""


async def score_cells(
    segments: list[Segment],
    reactions: list[ReactionResult],
    parsed_options: list[ParsedOption],
    min_sources: int,
) -> list[CellResult]:
    """Compute confidence + devil's advocate for every reaction cell."""
    seg_by_id: dict[uuid.UUID, Segment] = {s.id: s for s in segments}
    opt_by_label: dict[str, ParsedOption] = {o.label: o for o in parsed_options}

    # Collect all embeddings for stability calculation
    all_embeddings: dict[uuid.UUID, list[float]] = {
        s.id: _embedding_as_list(s.embedding)
        for s in segments
    }

    cell_results: list[CellResult] = []
    da_tasks: list[tuple[int, ReactionResult, str, str]] = []

    for reaction in reactions:
        segment = seg_by_id.get(reaction.segment_id)
        option = opt_by_label.get(reaction.option_label)

        if segment is None or option is None:
            log.warning(
                "simulation.score.missing_segment_or_option",
                segment_id=str(reaction.segment_id),
                option_label=reaction.option_label,
            )
            continue

        # Signal 1: evidence_density — segment quality propagates to cell
        evidence_density = evidence_density_from_count(
            len(segment.evidence or []),
            min_for_high=min_sources,
        )

        # Signal 2: llm_baserate_agreement from lookup table
        if reaction.failed:
            baserate = 0.0
        else:
            baserate = _baserate_agreement(option.option_type, reaction.reaction_sentiment)

        # Signal 3: construct_stability — how distinct this segment is
        seg_embedding = all_embeddings.get(reaction.segment_id, [])
        other_embeddings = [
            emb
            for sid, emb in all_embeddings.items()
            if sid != reaction.segment_id and emb
        ]
        stability = compute_segment_stability(seg_embedding, other_embeddings)

        signals = TriangulationInput(
            llm_baserate_agreement=baserate,
            evidence_density=evidence_density,
            construct_stability=stability,
        )
        confidence = triangulate(signals)

        # Segment confidence is an upstream ceiling: hypothesis-mode segments
        # should not produce higher-confidence simulation cells.
        if segment.confidence == "low":
            confidence = "low"

        # Force Low if the DSPy call itself failed
        if reaction.failed:
            confidence = "low"

        log.debug(
            "simulation.score.cell",
            segment_id=str(reaction.segment_id),
            option_label=reaction.option_label,
            evidence_density=round(evidence_density, 3),
            baserate=round(baserate, 3),
            stability=round(stability, 3),
            confidence=confidence,
        )

        cell_results.append(
            CellResult(
                segment_id=reaction.segment_id,
                option_label=reaction.option_label,
                reaction_sentiment=reaction.reaction_sentiment,
                adoption_probability=reaction.adoption_probability,
                churn_probability=reaction.churn_probability,
                top_concern=reaction.top_concern,
                time_horizon=reaction.time_horizon,
                reasoning_trace=reaction.reasoning_trace,
                confidence=confidence,
                devil_advocate="",
                smallest_experiment="",
            )
        )

        if confidence in ("low", "medium"):
            da_tasks.append((
                len(cell_results) - 1,
                reaction,
                segment.name or "",
                option.description,
            ))

    # Generate devil's advocates in parallel for low/medium cells
    if da_tasks:
        da_results = await asyncio.gather(*[
            _generate_devils_advocate(reaction, seg_name, opt_desc)
            for _idx, reaction, seg_name, opt_desc in da_tasks
        ])
        for (idx, _reaction, _seg_name, _opt_desc), (devil, experiment) in zip(
            da_tasks, da_results, strict=True
        ):
            cell_results[idx].devil_advocate = devil
            cell_results[idx].smallest_experiment = experiment

    return cell_results
