"""
OrchestratorAgent

The only agent that sees the full integrated picture: all segment reactions,
all D.A. outputs, all rubric failure metadata, and calibration flags.

Produces: OrchestratorOutput which becomes the Decision Memo.

The Orchestrator does NOT replace the existing memo generation (if any exists
in V1). It produces a NEW structured output that is stored in the Simulation
record and exposed via the existing GET /api/v1/simulations/{id} endpoint.

Model: Sonnet always. This is the most complex synthesis call.
Max retries: 1 (orchestrator output is already expensive — single retry only).
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any

import dspy

from app.agents.base import Agent, AgentOutput  # noqa: F401 (AgentOutput re-exported for callers)
from app.agents.calibration_agent import CalibrationOutput
from app.agents.config import SONNET_MODEL
from app.agents.rubrics.base import RubricDimension, RubricResult


class OrchestratorSynthesis(dspy.Signature):  # type: ignore[misc]
    """
    Synthesise all agent outputs into a Decision Memo.

    You have visibility into every agent's output AND any rubric failures.
    Your output must be specific, actionable, and honest about uncertainty.

    Rules:
    1. Your recommendation must name ONE specific option, not hedge between options.
       If evidence is too thin to recommend, say so explicitly.
    2. Your strongest_counter_case must be the most falsifiable challenge across
       all D.A. outputs — pick the best one, not a composite.
    3. If any reaction rubric failed on retry, reduce your stated confidence for
       that cell and say why.
    4. If calibration flags exist, name them in your confidence_rationale.
    5. Do NOT paper over agent conflicts with vague hedging. Name the tension.
    """
    segments_summary: str = dspy.InputField(
        desc="JSON: list of {name, jtbd, drivers, churn_triggers} per segment"
    )
    reactions_summary: str = dspy.InputField(
        desc="JSON: list of {segment, option, churn_range, top_concern, rubric_passed}"
    )
    da_cases_summary: str = dspy.InputField(
        desc="JSON: list of {cell_id, counter_case, invalidating_experiment, rubric_passed}"
    )
    rubric_failure_summary: str = dspy.InputField(
        desc="JSON: list of cells where rubric failed after all retries, with failure_reason"
    )
    calibration_flags_summary: str = dspy.InputField(
        desc="JSON: list of StaleRateFlag objects — option types with thin data"
    )
    recommendation: str = dspy.OutputField(
        desc="ONE specific recommended option with a concrete, segment-grounded justification"
    )
    confidence_rationale: str = dspy.OutputField(
        desc="Why you trust or distrust this recommendation, naming specific evidence gaps"
    )
    strongest_counter_case: str = dspy.OutputField(
        desc="The single most falsifiable challenge to this recommendation, from D.A. outputs"
    )
    conflict_resolution: str = dspy.OutputField(
        desc="How you resolved any tensions between Reaction Analyst and D.A. agent outputs"
    )


@dataclass
class OrchestratorInput:
    segments: list[Any]
    reaction_outputs: list[Any]   # list[AgentOutput[ReactionOutput]]
    da_outputs: list[Any]         # list[AgentOutput[DAOutput]]
    calibration_output: CalibrationOutput | None
    simulation_id: str


@dataclass
class OrchestratorOutput:
    recommendation: str
    confidence_rationale: str
    strongest_counter_case: str
    conflict_resolution: str
    rubric_failures_count: int = 0
    stale_calibration_types: list[str] = field(default_factory=list)


class OrchestratorAgent(Agent[OrchestratorInput, OrchestratorOutput]):
    name = "orchestrator"
    model = SONNET_MODEL
    max_retries = 1  # single retry — this is the most expensive call

    def __init__(self) -> None:
        self._synthesis = dspy.ChainOfThought(OrchestratorSynthesis)
        self._lm_sonnet = dspy.LM(model=SONNET_MODEL)

    def _build_segments_summary(self, segments: list[Any]) -> str:
        return json.dumps([
            {
                "name": s.name,
                "jtbd": s.job_to_be_done,
                "drivers": s.drivers or [],
                "churn_triggers": s.leaves or "",
            }
            for s in segments
        ], indent=2)

    def _build_reactions_summary(self, reaction_outputs: list[Any]) -> str:
        rows = []
        for out in reaction_outputs:
            if not out.result:
                continue
            cell = out.result.cell  # ReactionResult
            range_low = int(max(0.0, cell.churn_probability - 0.10) * 100)
            range_high = int(min(1.0, cell.churn_probability + 0.10) * 100)
            rows.append({
                "segment": str(cell.segment_id),
                "option": cell.option_label,
                "churn_range": f"{range_low}-{range_high}%",
                "top_concern": cell.top_concern or "",
                "rubric_passed": out.rubric_passed,
                "rubric_failure": out.rubric_result.failure_reason if not out.rubric_passed else None,
            })
        return json.dumps(rows, indent=2)

    def _build_da_summary(self, da_outputs: list[Any]) -> str:
        rows = []
        for out in da_outputs:
            if not out.result:
                continue
            rows.append({
                "cell_id": out.result.cell_id,
                "counter_case": out.result.counter_case,
                "invalidating_experiment": out.result.invalidating_experiment,
                "rubric_passed": out.rubric_passed,
            })
        return json.dumps(rows, indent=2)

    def _build_rubric_failure_summary(
        self, reaction_outputs: list[Any], da_outputs: list[Any]
    ) -> str:
        failures = [
            out.failure_metadata()
            for out in reaction_outputs + da_outputs
            if not out.rubric_passed
        ]
        return json.dumps(failures, indent=2)

    async def run(self, input: OrchestratorInput) -> OrchestratorOutput:
        cal = input.calibration_output
        cal_flags = (
            [
                {"option_type": f.option_type, "n": f.sample_count, "reason": f.reason}
                for f in cal.stale_flags
            ]
            if cal is not None else []
        )

        with dspy.context(lm=self._lm_sonnet):
            result = self._synthesis(
                segments_summary=self._build_segments_summary(input.segments),
                reactions_summary=self._build_reactions_summary(input.reaction_outputs),
                da_cases_summary=self._build_da_summary(input.da_outputs),
                rubric_failure_summary=self._build_rubric_failure_summary(
                    input.reaction_outputs, input.da_outputs
                ),
                calibration_flags_summary=json.dumps(cal_flags, indent=2),
            )

        rubric_failures = sum(
            1 for out in input.reaction_outputs + input.da_outputs
            if not out.rubric_passed
        )
        return OrchestratorOutput(
            recommendation=result.recommendation,
            confidence_rationale=result.confidence_rationale,
            strongest_counter_case=result.strongest_counter_case,
            conflict_resolution=result.conflict_resolution,
            rubric_failures_count=rubric_failures,
            stale_calibration_types=cal.low_n_types if cal is not None else [],
        )

    async def evaluate_rubric(
        self, input: OrchestratorInput, output: OrchestratorOutput
    ) -> RubricResult:
        missing = [
            name for name, val in [
                ("recommendation", output.recommendation),
                ("confidence_rationale", output.confidence_rationale),
                ("strongest_counter_case", output.strongest_counter_case),
            ]
            if not val or len(val.strip()) < 20
        ]
        passed = len(missing) == 0
        return RubricResult(dimensions=[
            RubricDimension(
                name="orchestrator_completeness",
                passed=passed,
                score=1.0 if passed else 0.0,
                is_hard_gate=True,
                reason=(
                    "All required fields present" if passed
                    else f"Missing or too short: {', '.join(missing)}"
                ),
            )
        ])

    def build_retry_input(
        self, input: OrchestratorInput, rubric_result: RubricResult
    ) -> OrchestratorInput:
        # Same input — DSPy temperature variance handles the retry
        return input
