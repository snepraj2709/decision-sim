"""
DevilsAdvocateAgent

In V1, devil's advocate logic lives inside simulation/score.py and runs only
for Low/Medium confidence cells. This agent makes it a first-class concern:
  - Runs on all cells (configurable via DEVIL_ADVOCATE_MODE)
  - Has its own rubric for output quality
  - Routes to Haiku or Sonnet based on cell stakes

Stakes-based model routing:
  High stakes (Sonnet): churn range_high > 40 OR reaction rubric did not pass
  Standard (Haiku): everything else
"""
from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Any

import dspy

from app.agents.base import Agent, AgentOutput
from app.agents.config import HAIKU_MODEL, SONNET_MODEL, da_should_run
from app.agents.rubrics.base import RubricDimension, RubricResult
from app.agents.rubrics.signatures import DASubstantivenessRubric
from app.models import Segment
from app.pipelines.simulation.react import ReactionResult
from app.pipelines.simulation.score import DevilsAdvocateOutput, generate_devil_advocate


@dataclass
class DAInput:
    segment: Segment
    cell: ReactionResult
    option_text: str
    reaction_rubric_passed: bool
    substantiveness_scaffold: str | None = None


@dataclass
class DAOutput:
    counter_case: str
    invalidating_experiment: str
    cell_id: str  # "{segment_id}:{option_label}" — matches back to the original cell


class DevilsAdvocateAgent(Agent[DAInput, DAOutput]):
    name = "devils_advocate"
    model = HAIKU_MODEL  # default; overridden per-cell in run()

    def __init__(self) -> None:
        self._lm_haiku = dspy.LM(model=HAIKU_MODEL)
        self._lm_sonnet = dspy.LM(model=SONNET_MODEL)
        self._da_rubric = dspy.Predict(DASubstantivenessRubric)

    def _is_high_stakes(self, input: DAInput) -> bool:
        range_high = int(min(1.0, input.cell.churn_probability + 0.10) * 100)
        return range_high > 40 or not input.reaction_rubric_passed

    async def run(self, input: DAInput) -> DAOutput:
        lm = self._lm_sonnet if self._is_high_stakes(input) else self._lm_haiku
        extra = input.substantiveness_scaffold or ""

        def _run_sync() -> DevilsAdvocateOutput:
            with dspy.context(lm=lm):
                return generate_devil_advocate(
                    segment=input.segment,
                    cell=input.cell,
                    option_text=input.option_text,
                    extra_instructions=extra or None,
                )

        result = await asyncio.to_thread(_run_sync)
        return DAOutput(
            counter_case=result.counter_case,
            invalidating_experiment=result.invalidating_experiment,
            cell_id=f"{input.cell.segment_id}:{input.cell.option_label}",
        )

    async def evaluate_rubric(
        self, input: DAInput, output: DAOutput
    ) -> RubricResult:
        range_low = int(max(0.0, input.cell.churn_probability - 0.10) * 100)
        range_high = int(min(1.0, input.cell.churn_probability + 0.10) * 100)
        reaction_summary = (
            f"churn {range_low}-{range_high}%; "
            f"concern: {input.cell.top_concern or 'not specified'}"
        )

        with dspy.context(lm=self._lm_haiku):
            result = self._da_rubric(
                segment_name=input.segment.name or "",
                decision_option=input.option_text,
                original_reaction=reaction_summary,
                counter_case=output.counter_case,
            )

        dimension = RubricDimension(
            name="da_substantiveness",
            passed=result.passed,
            score=1.0 if result.passed else (0.5 if result.substantive else 0.0),
            is_hard_gate=True,
            reason=result.reason,
        )
        return RubricResult(dimensions=[dimension])

    def build_retry_input(
        self, input: DAInput, rubric_result: RubricResult
    ) -> DAInput:
        reason = rubric_result.failure_reason
        return DAInput(
            segment=input.segment,
            cell=input.cell,
            option_text=input.option_text,
            reaction_rubric_passed=input.reaction_rubric_passed,
            substantiveness_scaffold=(
                f"Your counter-case failed the substantiveness check: {reason}. "
                f"Rewrite it to be specific to segment '{input.segment.name}' and "
                f"option '{input.option_text}'. It MUST propose a concrete, "
                f"falsifiable condition: 'If [specific observable event] occurs "
                f"within [timeframe], the reaction estimate is wrong because [reason]'."
            ),
        )


async def run_all_devil_advocates(
    reaction_outputs: list[AgentOutput[Any]],
    segments_by_id: dict[str, Segment],
    options_by_letter: dict[str, str],
) -> list[AgentOutput[DAOutput]]:
    """Run D.A. agent for cells that da_should_run() approves.

    Respects DEVIL_ADVOCATE_MODE env var. Runs approved cells in parallel.
    """
    from app.agents.reaction_analyst import ReactionOutput  # avoid circular at module level

    agent = DevilsAdvocateAgent()
    tasks = []
    for reaction_out in reaction_outputs:
        if not reaction_out.result:
            continue
        result = reaction_out.result
        if not isinstance(result, ReactionOutput):
            continue
        cell = result.cell
        if not da_should_run(reaction_out.rubric_passed):
            continue
        segment = segments_by_id.get(str(cell.segment_id))
        option_text = options_by_letter.get(cell.option_label, "")
        if segment:
            tasks.append(agent.execute(DAInput(
                segment=segment,
                cell=cell,
                option_text=option_text,
                reaction_rubric_passed=reaction_out.rubric_passed,
            )))
    if not tasks:
        return []
    return list(await asyncio.gather(*tasks))
