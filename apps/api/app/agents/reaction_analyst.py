"""
ReactionAnalystAgent

Wraps simulation/react.py. Runs all (segment × option) pairs in parallel,
exactly as the current pipeline does, then applies rubric evaluation per cell.

Model: Sonnet for reaction generation.
Model for rubric eval: Haiku (coherence + specificity checks).
"""
from __future__ import annotations

import asyncio
from dataclasses import dataclass, field

import dspy

from app.agents.base import Agent, AgentOutput
from app.agents.config import HAIKU_MODEL, SONNET_MODEL
from app.agents.rubrics.base import RubricDimension, RubricResult
from app.agents.rubrics.functional import check_calibration_alignment
from app.agents.rubrics.signatures import ReactionCoherenceRubric, SpecificityRubric
from app.models import Segment
from app.pipelines.simulation.react import ReactionResult, generate_reaction
from app.pipelines.simulation.score import BASE_RATES


@dataclass
class ReactionInput:
    segment: Segment
    option_letter: str
    option_text: str
    snapshot_category: str          # product category for specificity rubric
    option_type: str = "feature"    # pricing | copy | feature | bundling | onboarding
    coherence_scaffold: str | None = None
    specificity_scaffold: str | None = None
    calibration_scaffold: str | None = None


@dataclass
class ReactionOutput:
    cell: ReactionResult
    rubric_metadata: dict[str, object] = field(default_factory=dict)


class ReactionAnalystAgent(Agent[ReactionInput, ReactionOutput]):
    name = "reaction_analyst"
    model = SONNET_MODEL

    def __init__(self) -> None:
        self._lm_haiku = dspy.LM(model=HAIKU_MODEL)
        self._coherence_rubric = dspy.Predict(ReactionCoherenceRubric)
        self._specificity_rubric = dspy.Predict(SpecificityRubric)

    async def run(self, input: ReactionInput) -> ReactionOutput:
        extra_parts = [
            s
            for s in (
                input.coherence_scaffold,
                input.specificity_scaffold,
                input.calibration_scaffold,
            )
            if s
        ]
        extra = "\n".join(extra_parts) if extra_parts else None

        cell = await generate_reaction(
            segment=input.segment,
            option_letter=input.option_letter,
            option_text=input.option_text,
            option_type=input.option_type,
            extra_instructions=extra,
        )
        return ReactionOutput(cell=cell)

    async def evaluate_rubric(
        self, input: ReactionInput, output: ReactionOutput
    ) -> RubricResult:
        cell = output.cell
        dimensions: list[RubricDimension] = []

        # 1. Calibration alignment — uses hardcoded BASE_RATES as prior (soft gate
        #    because calibration_n=0; a real DB lookup would set n from CalibrationRate).
        sentiment = cell.reaction_sentiment or "neutral"
        option_rates = BASE_RATES.get(input.option_type, BASE_RATES["feature"])
        cal_rate = option_rates.get(sentiment, 0.25)
        low = int(max(0.0, cell.churn_probability - 0.10) * 100)
        high = int(min(1.0, cell.churn_probability + 0.10) * 100)
        dimensions.append(check_calibration_alignment(
            churn_range_low=low,
            churn_range_high=high,
            option_type=input.option_type,
            calibration_rate=cal_rate,
            calibration_n=0,
        ))

        # 2. Coherence + specificity via Haiku — run in parallel
        churn_triggers = input.segment.leaves or ""

        async def check_coherence() -> RubricDimension:
            with dspy.context(lm=self._lm_haiku):
                result = self._coherence_rubric(
                    segment_jtbd=input.segment.job_to_be_done or "",
                    segment_churn_triggers=churn_triggers,
                    reasoning_trace=cell.reasoning_trace or "",
                )
            return RubricDimension(
                name="reasoning_coherence",
                passed=result.passed,
                score=1.0 if result.passed else 0.0,
                is_hard_gate=True,
                reason=result.reason,
            )

        async def check_specificity() -> RubricDimension:
            with dspy.context(lm=self._lm_haiku):
                result = self._specificity_rubric(
                    top_concern=cell.top_concern or "",
                    product_name=input.snapshot_category,
                )
            return RubricDimension(
                name="specificity",
                passed=result.passed,
                score=1.0 if result.passed else 0.0,
                is_hard_gate=True,
                reason=result.reason,
            )

        coherence_dim, specificity_dim = await asyncio.gather(
            check_coherence(), check_specificity()
        )
        dimensions.extend([coherence_dim, specificity_dim])
        return RubricResult(dimensions=dimensions)

    def build_retry_input(
        self, input: ReactionInput, rubric_result: RubricResult
    ) -> ReactionInput:
        retry = ReactionInput(
            segment=input.segment,
            option_letter=input.option_letter,
            option_text=input.option_text,
            snapshot_category=input.snapshot_category,
            option_type=input.option_type,
        )
        for d in rubric_result.dimensions:
            if d.passed:
                continue
            if d.name == "reasoning_coherence":
                retry.coherence_scaffold = (
                    f"Your reasoning MUST explicitly reference this segment's "
                    f"job-to-be-done: '{input.segment.job_to_be_done}' "
                    f"AND at least one of these churn triggers: "
                    f"'{input.segment.leaves or ''}'. "
                    f"Do not reason from generic market logic."
                )
            elif d.name == "specificity":
                retry.specificity_scaffold = (
                    "Your top_concern must name a specific product feature, "
                    "workflow step, or observable customer behavior — not a "
                    "general market observation. Avoid: 'pricing concerns', "
                    "'competitive risk', 'users may churn'."
                )
            elif d.name == "calibration_alignment" and d.reason:
                retry.calibration_scaffold = (
                    f"Note: historical data shows the following for this decision type. "
                    f"{d.reason}. Your churn estimate should reflect this unless "
                    f"you have a specific segment-level reason to deviate — "
                    f"if so, state that reason explicitly."
                )
        return retry


async def run_all_reactions(
    segments: list[Segment],
    options: list[dict[str, str]],
    snapshot_category: str,
) -> list[AgentOutput[ReactionOutput]]:
    """Run ReactionAnalystAgent for all (segment × option) pairs in parallel."""
    agent = ReactionAnalystAgent()
    tasks = [
        agent.execute(ReactionInput(
            segment=seg,
            option_letter=opt["letter"],
            option_text=opt["text"],
            snapshot_category=snapshot_category,
            option_type=opt.get("option_type", "feature"),
        ))
        for seg in segments
        for opt in options
    ]
    return list(await asyncio.gather(*tasks))
