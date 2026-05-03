"""Stage 2 — Reaction generation.

For each (segment x option) pair, runs a DSPy ChainOfThought program
in-character as the segment to produce a structured reaction.
"""

from __future__ import annotations

import asyncio
import uuid
from dataclasses import dataclass, field

import structlog

from app.models import Segment
from app.pipelines.simulation.parse import ParsedOption

log = structlog.get_logger()


@dataclass
class ReactionResult:
    segment_id: uuid.UUID
    option_label: str
    reaction_sentiment: str  # positive | neutral | negative | mixed
    adoption_probability: float  # [0, 1]
    churn_probability: float  # [0, 1]
    top_concern: str  # ≤ 100 chars
    time_horizon: str  # immediate | 30d | 90d | 180d+
    reasoning_trace: str
    failed: bool = field(default=False)


_VALID_SENTIMENTS = frozenset({"positive", "neutral", "negative", "mixed"})
_VALID_HORIZONS = frozenset({"immediate", "30d", "90d", "180d+"})


def _format_evidence(segment: Segment) -> str:
    if not segment.evidence:
        return "No direct quotes available."
    return "\n".join(
        f'- "{e.quote}" (source: {e.source})'
        for e in segment.evidence[:2]
    )


def _format_drivers(segment: Segment) -> str:
    if not segment.drivers:
        return ""
    return ", ".join(
        str(d.get("label", ""))
        for d in segment.drivers
        if isinstance(d, dict) and d.get("label")
    )


def _call_dspy(segment: Segment, option: ParsedOption) -> ReactionResult:
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

    class SegmentReaction(dspy.Signature):  # type: ignore[misc]
        """React to a product change from the perspective of a customer segment.

        You are this customer segment. Reason from their perspective.
        Base your reaction on the evidence quotes provided, not general
        knowledge about this product category.
        top_concern must be specific to this segment's job_to_be_done,
        not a generic concern.
        """

        segment_name: str = dspy.InputField()
        segment_descriptor: str = dspy.InputField()
        job_to_be_done: str = dspy.InputField()
        value_drivers: str = dspy.InputField()
        churn_triggers: str = dspy.InputField()
        evidence_quotes: str = dspy.InputField(
            desc="Real quotes from people like this segment -- ground your reasoning here"
        )
        option_label: str = dspy.InputField()
        option_description: str = dspy.InputField()
        option_type: str = dspy.InputField()

        reaction_sentiment: str = dspy.OutputField(
            desc="One of: positive, neutral, negative, mixed"
        )
        adoption_probability: float = dspy.OutputField(
            desc="Probability this segment adopts/stays [0, 1]"
        )
        churn_probability: float = dspy.OutputField(
            desc="Probability this segment churns [0, 1]"
        )
        top_concern: str = dspy.OutputField(
            desc="Segment's #1 concern about this change, max 100 chars, specific to their JTBD"
        )
        time_horizon: str = dspy.OutputField(
            desc="When effect manifests: immediate, 30d, 90d, or 180d+"
        )
        reasoning_trace: str = dspy.OutputField(
            desc="2-3 sentences walking through this segment's reaction in their own voice"
        )

    with dspy.context(lm=lm):
        predictor = dspy.ChainOfThought(SegmentReaction)
        result = predictor(
            segment_name=segment.name or "",
            segment_descriptor=segment.descriptor or "",
            job_to_be_done=segment.job_to_be_done or "",
            value_drivers=_format_drivers(segment),
            churn_triggers=segment.leaves or "",
            evidence_quotes=_format_evidence(segment),
            option_label=option.label,
            option_description=option.description,
            option_type=option.option_type,
        )

    sentiment = str(result.reaction_sentiment or "neutral").strip().lower()
    if sentiment not in _VALID_SENTIMENTS:
        sentiment = "neutral"

    try:
        adoption = float(result.adoption_probability)
        adoption = max(0.0, min(1.0, adoption))
    except (TypeError, ValueError):
        adoption = 0.5

    try:
        churn = float(result.churn_probability)
        churn = max(0.0, min(1.0, churn))
    except (TypeError, ValueError):
        churn = 0.5

    top_concern = str(result.top_concern or "").strip()[:100]

    horizon = str(result.time_horizon or "90d").strip()
    if horizon not in _VALID_HORIZONS:
        horizon = "90d"

    reasoning = str(result.reasoning_trace or "").strip()

    return ReactionResult(
        segment_id=segment.id,
        option_label=option.label,
        reaction_sentiment=sentiment,
        adoption_probability=adoption,
        churn_probability=churn,
        top_concern=top_concern,
        time_horizon=horizon,
        reasoning_trace=reasoning,
    )


async def _react_one(segment: Segment, option: ParsedOption) -> ReactionResult:
    try:
        return await asyncio.to_thread(_call_dspy, segment, option)
    except Exception as exc:
        log.error(
            "simulation.react.failed",
            segment_id=str(segment.id),
            segment_name=segment.name,
            option_label=option.label,
            error=str(exc),
        )
        return ReactionResult(
            segment_id=segment.id,
            option_label=option.label,
            reaction_sentiment="neutral",
            adoption_probability=0.5,
            churn_probability=0.5,
            top_concern="Simulation failed - retry",
            time_horizon="90d",
            reasoning_trace="",
            failed=True,
        )


async def generate_reactions(
    segments: list[Segment],
    options: list[ParsedOption],
) -> list[ReactionResult]:
    """Generate reactions for all (segment x option) pairs in parallel."""
    tasks = [
        _react_one(segment, option)
        for segment in segments
        for option in options
    ]
    return list(await asyncio.gather(*tasks))
