"""Unit tests for SegmentArchitectAgent."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.agents.rubrics.base import RubricDimension, RubricResult
from app.agents.segment_architect import SegmentArchitectAgent, SegmentInput, SegmentOutput


def _anchored_segment(
    name: str,
    n_evidence: int = 2,
    embedding: list[float] | None = None,
) -> MagicMock:
    seg = MagicMock()
    seg.name = name
    seg.job_to_be_done = "Ship features without blocking the rest of the team."
    seg.centroid_embedding = embedding or [0.1, 0.2, 0.3]
    # evidence_quotes used by check_anchor_density
    seg.evidence_quotes = [MagicMock() for _ in range(n_evidence)]
    # no .evidence attr so check_anchor_density falls through to evidence_quotes
    del seg.evidence
    return seg


def _output(
    segments: list | None = None,
    embeddings: list | None = None,
) -> SegmentOutput:
    segs = segments if segments is not None else []
    embs = embeddings if embeddings is not None else [s.centroid_embedding for s in segs]
    return SegmentOutput(segments=segs, segment_embeddings=embs)


def _make_agent() -> SegmentArchitectAgent:
    """Create agent with patched dspy.LM so no API key is needed at init."""
    with patch("app.agents.segment_architect.dspy.LM"), patch(
        "app.agents.segment_architect.dspy.Predict"
    ):
        return SegmentArchitectAgent()


class TestSegmentArchitectEvaluateRubric:
    @pytest.mark.asyncio
    async def test_segments_missing_anchors_fail_anchor_density_hard_gate(self) -> None:
        agent = _make_agent()
        seg_thin = _anchored_segment("Solo devs", n_evidence=1)
        output = _output(segments=[seg_thin])

        result_mock = MagicMock(passed=True, reason="ok")
        with (
            patch.object(agent, "_jtbd_rubric", return_value=result_mock),
            patch.object(agent, "_naming_rubric", return_value=result_mock),
            patch("app.agents.segment_architect.dspy.context"),
        ):
            rubric = await agent.evaluate_rubric(
                SegmentInput(snapshot_id="abc", search_results=[]),
                output,
            )

        anchor_dim = next(d for d in rubric.dimensions if d.name == "anchor_density")
        assert anchor_dim.passed is False
        assert anchor_dim.is_hard_gate is True
        assert rubric.passed is False

    @pytest.mark.asyncio
    async def test_segments_with_enough_anchors_pass_anchor_density(self) -> None:
        agent = _make_agent()
        segs = [
            _anchored_segment("Enterprise buyers", n_evidence=2),
            _anchored_segment("Solo devs", n_evidence=3),
        ]
        # Use orthogonal embeddings so distinctness passes too
        output = _output(
            segments=segs,
            embeddings=[[1.0, 0.0, 0.0], [0.0, 1.0, 0.0]],
        )

        result_mock = MagicMock(passed=True, reason="ok")
        with (
            patch.object(agent, "_jtbd_rubric", return_value=result_mock),
            patch.object(agent, "_naming_rubric", return_value=result_mock),
            patch("app.agents.segment_architect.dspy.context"),
        ):
            rubric = await agent.evaluate_rubric(
                SegmentInput(snapshot_id="abc", search_results=[]),
                output,
            )

        anchor_dim = next(d for d in rubric.dimensions if d.name == "anchor_density")
        assert anchor_dim.passed is True


class TestSegmentArchitectBuildRetryInput:
    def test_distinctness_failure_sets_finer_clustering_flag(self) -> None:
        agent = _make_agent()

        rubric = RubricResult(
            dimensions=[
                RubricDimension(
                    name="segment_distinctness",
                    passed=False,
                    score=0.02,
                    is_hard_gate=True,
                )
            ]
        )
        original = SegmentInput(snapshot_id="snap1", search_results=[])

        retry = agent.build_retry_input(original, rubric)

        assert retry.retry_with_finer_clustering is True
        assert retry.jtbd_constraint is None
        assert retry.naming_constraint is None

    def test_jtbd_failure_sets_jtbd_constraint(self) -> None:
        agent = _make_agent()

        rubric = RubricResult(
            dimensions=[
                RubricDimension(
                    name="jtbd_completeness:Solo devs",
                    passed=False,
                    score=0.0,
                    is_hard_gate=False,
                )
            ]
        )
        original = SegmentInput(snapshot_id="snap1", search_results=[])

        retry = agent.build_retry_input(original, rubric)

        assert retry.jtbd_constraint is not None
        assert "functional outcome" in retry.jtbd_constraint
        assert retry.naming_constraint is None

    def test_naming_failure_sets_naming_constraint(self) -> None:
        agent = _make_agent()

        rubric = RubricResult(
            dimensions=[
                RubricDimension(
                    name="naming_precision:Business users",
                    passed=False,
                    score=0.0,
                    is_hard_gate=False,
                )
            ]
        )
        original = SegmentInput(snapshot_id="snap1", search_results=[])

        retry = agent.build_retry_input(original, rubric)

        assert retry.naming_constraint is not None
        assert "persona" in retry.naming_constraint
        assert retry.jtbd_constraint is None

    def test_multiple_failures_set_all_relevant_constraints(self) -> None:
        agent = _make_agent()

        rubric = RubricResult(
            dimensions=[
                RubricDimension(
                    name="jtbd_completeness:Users",
                    passed=False,
                    score=0.0,
                    is_hard_gate=False,
                ),
                RubricDimension(
                    name="naming_precision:Users",
                    passed=False,
                    score=0.0,
                    is_hard_gate=False,
                ),
            ]
        )
        original = SegmentInput(snapshot_id="snap1", search_results=[])

        retry = agent.build_retry_input(original, rubric)

        assert retry.jtbd_constraint is not None
        assert retry.naming_constraint is not None
        assert retry.retry_with_finer_clustering is False


@pytest.mark.integration
class TestSegmentArchitectLLMRubrics:
    """These tests require ANTHROPIC_API_KEY and call Haiku — mark integration."""

    @pytest.mark.asyncio
    async def test_jtbd_completeness_rubric_passes_for_specific_outcome(self) -> None:
        agent = SegmentArchitectAgent()
        seg = _anchored_segment("Solo devs")
        seg.job_to_be_done = "Ship features without blocking the rest of the team."

        output = _output(segments=[seg], embeddings=[[1.0, 0.0]])

        rubric = await agent.evaluate_rubric(
            SegmentInput(snapshot_id="snap1", search_results=[]),
            output,
        )

        jtbd_dim = next(
            (d for d in rubric.dimensions if "jtbd_completeness" in d.name), None
        )
        assert jtbd_dim is not None
        assert jtbd_dim.passed is True

    @pytest.mark.asyncio
    async def test_naming_rubric_fails_for_generic_name(self) -> None:
        agent = SegmentArchitectAgent()
        seg = _anchored_segment("Business users")
        seg.job_to_be_done = "Manage their work."

        output = _output(segments=[seg], embeddings=[[1.0, 0.0]])

        rubric = await agent.evaluate_rubric(
            SegmentInput(snapshot_id="snap1", search_results=[]),
            output,
        )

        naming_dim = next(
            (d for d in rubric.dimensions if "naming_precision" in d.name), None
        )
        assert naming_dim is not None
        assert naming_dim.passed is False
