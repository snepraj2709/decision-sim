"""Unit tests for DevilsAdvocateAgent."""

from __future__ import annotations

import uuid
from unittest.mock import MagicMock, patch

import pytest

from app.agents.rubrics.base import RubricDimension, RubricResult


def _make_segment(name: str = "Solo developers") -> MagicMock:
    seg = MagicMock()
    seg.id = uuid.uuid4()
    seg.name = name
    seg.job_to_be_done = "Ship features without blocking the team."
    seg.leaves = "context-switching, slow review"
    return seg


def _make_cell(
    churn_probability: float = 0.20,
    reaction_sentiment: str = "neutral",
    top_concern: str = "keyboard-first workflow",
) -> MagicMock:
    cell = MagicMock()
    cell.segment_id = uuid.uuid4()
    cell.option_label = "A"
    cell.churn_probability = churn_probability
    cell.reaction_sentiment = reaction_sentiment
    cell.top_concern = top_concern
    return cell


def _make_agent():
    from app.agents.devil_advocate import DevilsAdvocateAgent

    with (
        patch("app.agents.devil_advocate.dspy.LM"),
        patch("app.agents.devil_advocate.dspy.Predict"),
    ):
        return DevilsAdvocateAgent()


class TestDAConfig:
    def test_da_should_run_returns_false_when_mode_off(self, monkeypatch) -> None:
        monkeypatch.setenv("DEVIL_ADVOCATE_MODE", "off")
        # Reload module so env var is re-read
        import importlib
        import app.agents.config as cfg_module
        importlib.reload(cfg_module)
        from app.agents.config import da_should_run as reloaded_da_should_run
        assert reloaded_da_should_run(reaction_rubric_passed=True) is False
        assert reloaded_da_should_run(reaction_rubric_passed=False) is False

    def test_da_should_run_selective_returns_true_for_failed_reaction(
        self, monkeypatch
    ) -> None:
        monkeypatch.setenv("DEVIL_ADVOCATE_MODE", "selective")
        import importlib
        import app.agents.config as cfg_module
        importlib.reload(cfg_module)
        from app.agents.config import da_should_run as reloaded_da_should_run
        assert reloaded_da_should_run(reaction_rubric_passed=False) is True
        assert reloaded_da_should_run(reaction_rubric_passed=True) is False

    def test_da_should_run_all_returns_true_regardless_of_reaction_pass(
        self, monkeypatch
    ) -> None:
        monkeypatch.setenv("DEVIL_ADVOCATE_MODE", "all")
        import importlib
        import app.agents.config as cfg_module
        importlib.reload(cfg_module)
        from app.agents.config import da_should_run as reloaded_da_should_run
        assert reloaded_da_should_run(reaction_rubric_passed=True) is True
        assert reloaded_da_should_run(reaction_rubric_passed=False) is True


class TestDevilsAdvocateAgentHighStakes:
    def test_is_high_stakes_true_when_range_high_exceeds_40(self) -> None:
        from app.agents.devil_advocate import DAInput, DevilsAdvocateAgent

        agent = _make_agent()
        # churn_probability=0.40 → range_high = int(0.50 * 100) = 50 > 40
        cell = _make_cell(churn_probability=0.40)
        inp = DAInput(
            segment=_make_segment(),
            cell=cell,
            option_text="Increase price by 20%",
            reaction_rubric_passed=True,
        )

        assert agent._is_high_stakes(inp) is True

    def test_is_high_stakes_false_when_range_high_below_40_and_rubric_passed(self) -> None:
        from app.agents.devil_advocate import DAInput

        agent = _make_agent()
        # churn_probability=0.20 → range_high = int(0.30 * 100) = 30 ≤ 40
        cell = _make_cell(churn_probability=0.20)
        inp = DAInput(
            segment=_make_segment(),
            cell=cell,
            option_text="Increase price by 20%",
            reaction_rubric_passed=True,
        )

        assert agent._is_high_stakes(inp) is False

    def test_is_high_stakes_true_when_reaction_rubric_failed(self) -> None:
        from app.agents.devil_advocate import DAInput

        agent = _make_agent()
        cell = _make_cell(churn_probability=0.10)  # range_high = 20, not > 40
        inp = DAInput(
            segment=_make_segment(),
            cell=cell,
            option_text="Add a new feature",
            reaction_rubric_passed=False,
        )

        assert agent._is_high_stakes(inp) is True


class TestDevilsAdvocateBuildRetryInput:
    def test_build_retry_input_injects_substantiveness_scaffold(self) -> None:
        from app.agents.devil_advocate import DAInput

        agent = _make_agent()
        seg = _make_segment(name="Growth-stage PM teams")
        cell = _make_cell()
        option_text = "Bundle enterprise features"
        inp = DAInput(
            segment=seg,
            cell=cell,
            option_text=option_text,
            reaction_rubric_passed=True,
        )
        rubric = RubricResult(dimensions=[
            RubricDimension(
                name="da_substantiveness",
                passed=False,
                score=0.0,
                is_hard_gate=True,
                reason="counter-case is generic market skepticism",
            )
        ])

        retry = agent.build_retry_input(inp, rubric)

        assert retry.substantiveness_scaffold is not None
        assert seg.name in retry.substantiveness_scaffold
        assert option_text in retry.substantiveness_scaffold
        # Template requires a falsifiable condition format
        assert "falsifiable condition" in retry.substantiveness_scaffold
        assert "If [specific observable event]" in retry.substantiveness_scaffold
