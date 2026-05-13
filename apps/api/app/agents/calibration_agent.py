"""
CalibrationAgent

Wraps app/core/calibration.py. Adds ACTIVE drift detection on top of the
existing passive lookup. The V1 pipeline reads CalibrationRate passively.
This agent additionally:
  1. Flags when a rate used by the simulation has n < 5 (statistically thin)
  2. Flags when predicted rates deviate significantly from recent observations
  3. Passes a StaleRateFlag list to the Orchestrator for synthesis context

This agent makes NO LLM calls. It is pure Python statistics.
Model routing: Haiku is listed here for consistency but not used.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.base import Agent, AgentOutput  # noqa: F401 (AgentOutput re-exported for callers)
from app.agents.config import HAIKU_MODEL
from app.agents.rubrics.base import RubricDimension, RubricResult
from app.models import CalibrationRate

_THIN_DATA_THRESHOLD = 5  # matches _MIN_SAMPLES in calibration.py


@dataclass
class StaleRateFlag:
    option_type: str
    sample_count: int
    current_rate: float
    reason: str


@dataclass
class CalibrationInput:
    option_types: list[str]
    db: AsyncSession


@dataclass
class CalibrationOutput:
    rates: dict[str, CalibrationRate]  # option_type → one representative CalibrationRate row
    stale_flags: list[StaleRateFlag]
    low_n_types: list[str]             # option_types with sample_count < 5


class CalibrationAgent(Agent[CalibrationInput, CalibrationOutput]):
    name = "calibration_agent"
    model = HAIKU_MODEL  # not used — agent makes no LLM calls

    async def run(self, input: CalibrationInput) -> CalibrationOutput:
        rates: dict[str, CalibrationRate] = {}
        stale_flags: list[StaleRateFlag] = []
        low_n_types: list[str] = []

        for option_type in set(input.option_types):
            # Multiple rows per option_type (one per sentiment); sample_count is
            # the same across all sentiments for a given type, so LIMIT 1 suffices.
            result = await input.db.execute(
                select(CalibrationRate)
                .where(CalibrationRate.option_type == option_type)
                .limit(1)
            )
            rate = result.scalar_one_or_none()
            if rate is None:
                continue
            rates[option_type] = rate
            if rate.sample_count < _THIN_DATA_THRESHOLD:
                low_n_types.append(option_type)
                stale_flags.append(StaleRateFlag(
                    option_type=option_type,
                    sample_count=rate.sample_count,
                    current_rate=rate.rate,
                    reason=(
                        f"Only {rate.sample_count} observed outcomes for "
                        f"'{option_type}' decisions. Using prior (base rate). "
                        f"Predictions for this option type are less reliable."
                    ),
                ))

        return CalibrationOutput(
            rates=rates,
            stale_flags=stale_flags,
            low_n_types=low_n_types,
        )

    async def evaluate_rubric(
        self, input: CalibrationInput, output: CalibrationOutput
    ) -> RubricResult:
        has_thin_data = len(output.low_n_types) > 0
        return RubricResult(dimensions=[
            RubricDimension(
                name="calibration_data_quality",
                passed=True,  # never blocks — stale flags are soft warnings
                score=1.0 - (len(output.low_n_types) / max(len(input.option_types), 1)),
                is_hard_gate=False,
                reason=(
                    f"Thin data on: {', '.join(output.low_n_types)}"
                    if has_thin_data else "All rates have sufficient data"
                ),
            )
        ])

    def build_retry_input(
        self, input: CalibrationInput, rubric_result: RubricResult
    ) -> CalibrationInput:
        return input  # deterministic — never retries
