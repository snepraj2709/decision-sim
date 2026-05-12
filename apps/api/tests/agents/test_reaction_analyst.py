"""Unit tests for ReactionAnalystAgent."""

from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.agents.reaction_analyst import ReactionAnalystAgent, ReactionInput, ReactionOutput
from app.agents.rubrics.base import RubricDimension, RubricResult


def _make_segment(
    name: str = "Solo developers",
    jtbd: str = "Ship features without blocking the team.",
    leaves: str = "context-switching, slow code review, noisy notifications",
) -> MagicMock:
    seg = MagicMock()
    seg.id = uuid.uuid4()
    seg.name = name
    seg.job_to_be_done = jtbd
    seg.leaves = leaves
    return seg


def _make_reaction_result(
    segment_id: uuid.UUID | None = None,
    option_label: str = "A",
    churn_probability: float = 0.20,
    reaction_sentiment: str = "neutral",
    top_concern: str = "keyboard-first workflow disruption",
    reasoning_trace: str = "This segment's JTBD is disrupted by the change.",
) -> MagicMock:
    cell = MagicMock()
    cell.segment_id = segment_id or uuid.uuid4()
    cell.option_label = option_label
    cell.churn_probability = churn_probability
    cell.reaction_sentiment = reaction_sentiment
    cell.top_concern = top_concern
    cell.reasoning_trace = reasoning_trace
    return cell


def _make_input(segment: MagicMock | None = None) -> ReactionInput:
    return ReactionInput(
        segment=segment or _make_segment(),
        option_letter="A",
        option_text="Increase price by 20%",
        snapshot_category="project management tool",
        option_type="pricing",
    )


def _make_agent() -> ReactionAnalystAgent:
    with (
        patch("app.agents.reaction_analyst.dspy.LM"),
        patch("app.agents.reaction_analyst.dspy.Predict"),
    ):
        return ReactionAnalystAgent()


class TestReactionAnalystBuildRetryInput:
    def test_coherence_failure_sets_coherence_scaffold_only(self) -> None:
        agent = _make_agent()
        seg = _make_segment()
        original = _make_input(segment=seg)
        rubric = RubricResult(dimensions=[
            RubricDimension(name="reasoning_coherence", passed=False, score=0.0,
                            is_hard_gate=True, reason="JTBD not referenced"),
        ])

        retry = agent.build_retry_input(original, rubric)

        assert retry.coherence_scaffold is not None
        assert seg.job_to_be_done in retry.coherence_scaffold
        assert retry.specificity_scaffold is None
        assert retry.calibration_scaffold is None

    def test_specificity_failure_sets_specificity_scaffold_only(self) -> None:
        agent = _make_agent()
        original = _make_input()
        rubric = RubricResult(dimensions=[
            RubricDimension(name="specificity", passed=False, score=0.0,
                            is_hard_gate=True, reason="Generic observation"),
        ])

        retry = agent.build_retry_input(original, rubric)

        assert retry.specificity_scaffold is not None
        assert "top_concern" in retry.specificity_scaffold
        assert retry.coherence_scaffold is None
        assert retry.calibration_scaffold is None

    def test_calibration_failure_with_reason_sets_calibration_scaffold(self) -> None:
        agent = _make_agent()
        original = _make_input()
        reason = "Range [5-25%] outside base rate [30-70%] (n=8)"
        rubric = RubricResult(dimensions=[
            RubricDimension(
                name="calibration_alignment", passed=False, score=0.3,
                is_hard_gate=True, reason=reason,
            ),
        ])

        retry = agent.build_retry_input(original, rubric)

        assert retry.calibration_scaffold is not None
        assert reason in retry.calibration_scaffold
        assert retry.coherence_scaffold is None
        assert retry.specificity_scaffold is None

    @pytest.mark.asyncio
    async def test_run_all_reactions_produces_n_segments_times_n_options(self) -> None:
        segments = [_make_segment(name=f"Segment {i}") for i in range(3)]
        options = [
            {"letter": "A", "text": "Option A", "option_type": "pricing"},
            {"letter": "B", "text": "Option B", "option_type": "pricing"},
        ]

        fake_cell = _make_reaction_result()
        fake_output = ReactionOutput(cell=fake_cell)
        from app.agents.base import AgentOutput
        from app.agents.rubrics.base import RubricResult as RR

        fake_agent_output = AgentOutput(
            result=fake_output,
            rubric_passed=True,
            rubric_result=RR(),
            attempts=1,
            agent_name="reaction_analyst",
        )

        with patch(
            "app.agents.reaction_analyst.ReactionAnalystAgent.execute",
            new=AsyncMock(return_value=fake_agent_output),
        ):
            from app.agents.reaction_analyst import run_all_reactions
            results = await run_all_reactions(segments, options, "project management")

        assert len(results) == len(segments) * len(options)
