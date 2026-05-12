"""Unit tests for agent base primitives and retry orchestration."""

from __future__ import annotations

from collections.abc import Sequence
from types import SimpleNamespace
from typing import ClassVar

import pytest

from app.agents import config as agent_config
from app.agents.base import Agent, AgentOutput
from app.agents.rubrics.base import RubricDimension, RubricResult
from app.agents.rubrics.functional import (
    check_calibration_alignment,
    check_source_diversity,
)


def _dimension(
    name: str,
    *,
    passed: bool,
    is_hard_gate: bool = True,
    score: float = 1.0,
    reason: str | None = None,
) -> RubricDimension:
    return RubricDimension(
        name=name,
        passed=passed,
        score=score,
        is_hard_gate=is_hard_gate,
        reason=reason,
    )


def _rubric(passed: bool, *, hard: bool = True, reason: str | None = None) -> RubricResult:
    return RubricResult(
        dimensions=[
            _dimension(
                "attempt_quality",
                passed=passed,
                is_hard_gate=hard,
                score=1.0 if passed else 0.0,
                reason=reason,
            )
        ]
    )


class StubAgent(Agent[str, str]):
    """Concrete test agent with configurable rubric outcomes by attempt."""

    name: ClassVar[str] = "stub_agent"
    model: ClassVar[str] = "test-model"

    def __init__(self, rubric_results: Sequence[RubricResult], *, max_retries: int = 2) -> None:
        self.rubric_results = list(rubric_results)
        self.max_retries = max_retries
        self.run_calls = 0
        self.inputs_seen: list[str] = []
        self.retry_failures: list[str] = []

    async def run(self, input: str) -> str:
        self.run_calls += 1
        self.inputs_seen.append(input)
        return f"output-{self.run_calls}"

    async def evaluate_rubric(self, input: str, output: str) -> RubricResult:
        return self.rubric_results[self.run_calls - 1]

    def build_retry_input(self, input: str, rubric_result: RubricResult) -> str:
        self.retry_failures.append(rubric_result.failure_reason)
        return f"{input}|retry-{self.run_calls}"


class TestRubricResult:
    def test_hard_gate_failure_blocks_even_with_perfect_score(self) -> None:
        result = RubricResult(
            dimensions=[
                _dimension(
                    "hard_gate",
                    passed=False,
                    score=1.0,
                    is_hard_gate=True,
                )
            ]
        )

        assert result.passed is False

    def test_soft_gate_failure_does_not_block_when_hard_gates_pass(self) -> None:
        result = RubricResult(
            dimensions=[
                _dimension("hard_gate", passed=True, is_hard_gate=True),
                _dimension("soft_gate", passed=False, is_hard_gate=False),
            ]
        )

        assert result.passed is True

    def test_failure_reason_only_includes_failed_dimensions(self) -> None:
        result = RubricResult(
            dimensions=[
                _dimension("passed_hard", passed=True, reason="should not appear"),
                _dimension("failed_hard", passed=False, reason="hard failure"),
                _dimension(
                    "failed_soft",
                    passed=False,
                    is_hard_gate=False,
                    reason="soft warning",
                ),
            ]
        )

        assert result.failure_reason == (
            "failed_hard: hard failure; failed_soft: soft warning"
        )

    def test_soft_flags_only_returns_soft_gate_failures(self) -> None:
        result = RubricResult(
            dimensions=[
                _dimension("failed_hard", passed=False, is_hard_gate=True),
                _dimension("failed_soft", passed=False, is_hard_gate=False),
                _dimension("passed_soft", passed=True, is_hard_gate=False),
            ]
        )

        assert [dimension.name for dimension in result.soft_flags] == ["failed_soft"]


class TestAgentOutput:
    def test_needs_attention_when_rubric_failed(self) -> None:
        rubric_result = RubricResult(
            dimensions=[_dimension("hard_gate", passed=False, is_hard_gate=True)]
        )
        output = AgentOutput(
            result="value",
            rubric_passed=False,
            rubric_result=rubric_result,
            attempts=1,
            agent_name="test",
        )

        assert output.needs_orchestrator_attention is True

    def test_needs_attention_when_soft_flags_exist(self) -> None:
        rubric_result = RubricResult(
            dimensions=[
                _dimension("hard_gate", passed=True, is_hard_gate=True),
                _dimension("soft_gate", passed=False, is_hard_gate=False),
            ]
        )
        output = AgentOutput(
            result="value",
            rubric_passed=True,
            rubric_result=rubric_result,
            attempts=1,
            agent_name="test",
        )

        assert output.needs_orchestrator_attention is True

    def test_does_not_need_attention_when_rubric_passes_without_soft_flags(self) -> None:
        rubric_result = RubricResult(
            dimensions=[_dimension("hard_gate", passed=True, is_hard_gate=True)]
        )
        output = AgentOutput(
            result="value",
            rubric_passed=True,
            rubric_result=rubric_result,
            attempts=1,
            agent_name="test",
        )

        assert output.needs_orchestrator_attention is False


class TestAgentExecute:
    @pytest.mark.asyncio
    async def test_passes_on_first_attempt_returns_attempts_one(self) -> None:
        agent = StubAgent([_rubric(True)], max_retries=3)

        output = await agent.execute("initial")

        assert output.result == "output-1"
        assert output.rubric_passed is True
        assert output.attempts == 1
        assert agent.run_calls == 1
        assert agent.inputs_seen == ["initial"]

    @pytest.mark.asyncio
    async def test_retries_on_rubric_failure_and_passes_on_second_attempt(self) -> None:
        agent = StubAgent(
            [
                _rubric(False, reason="first attempt failed"),
                _rubric(True),
            ],
            max_retries=3,
        )

        output = await agent.execute("initial")

        assert output.result == "output-2"
        assert output.rubric_passed is True
        assert output.attempts == 2
        assert agent.inputs_seen == ["initial", "initial|retry-1"]
        assert agent.retry_failures == ["attempt_quality: first attempt failed"]

    @pytest.mark.asyncio
    async def test_exhausts_retries_returns_failed_rubric_with_last_output(self) -> None:
        agent = StubAgent(
            [
                _rubric(False, reason="first attempt failed"),
                _rubric(False, reason="second attempt failed"),
            ],
            max_retries=2,
        )

        output = await agent.execute("initial")

        assert output.result == "output-2"
        assert output.rubric_passed is False
        assert output.attempts == 2
        assert output.rubric_result.failure_reason == (
            "attempt_quality: second attempt failed"
        )
        assert agent.inputs_seen == ["initial", "initial|retry-1"]


@pytest.mark.parametrize(
    ("mode", "reaction_rubric_passed", "expected"),
    [
        (agent_config.DevilAdvocateMode.ALL, True, True),
        (agent_config.DevilAdvocateMode.ALL, False, True),
        (agent_config.DevilAdvocateMode.SELECTIVE, True, False),
        (agent_config.DevilAdvocateMode.SELECTIVE, False, True),
        (agent_config.DevilAdvocateMode.OFF, True, False),
        (agent_config.DevilAdvocateMode.OFF, False, False),
    ],
)
def test_da_should_run_returns_expected_value_for_each_mode(
    monkeypatch: pytest.MonkeyPatch,
    mode: str,
    reaction_rubric_passed: bool,
    expected: bool,
) -> None:
    monkeypatch.setattr(agent_config, "DEVIL_ADVOCATE_MODE", mode)

    assert agent_config.da_should_run(reaction_rubric_passed) is expected


class TestFunctionalSmokeChecks:
    def test_source_diversity_passes_above_threshold_and_fails_below(self) -> None:
        diverse_results = [
            SimpleNamespace(url="https://alpha.example/review"),
            SimpleNamespace(url="https://beta.example/review"),
            SimpleNamespace(url="https://alpha.example/other"),
        ]
        concentrated_results = [
            SimpleNamespace(url="https://alpha.example/review-1"),
            SimpleNamespace(url="https://alpha.example/review-2"),
            SimpleNamespace(url="https://alpha.example/review-3"),
        ]

        passed = check_source_diversity(diverse_results, threshold=0.50)
        failed = check_source_diversity(concentrated_results, threshold=0.50)

        assert passed.passed is True
        assert failed.passed is False

    def test_calibration_alignment_is_soft_gate_when_n_less_than_five(self) -> None:
        result = check_calibration_alignment(
            churn_range_low=80,
            churn_range_high=90,
            option_type="price_increase",
            calibration_rate=0.10,
            calibration_n=4,
        )

        assert result.passed is False
        assert result.is_hard_gate is False

    def test_calibration_alignment_is_hard_gate_when_n_at_least_five(self) -> None:
        result = check_calibration_alignment(
            churn_range_low=80,
            churn_range_high=90,
            option_type="price_increase",
            calibration_rate=0.10,
            calibration_n=100,
        )

        assert result.passed is False
        assert result.is_hard_gate is True
