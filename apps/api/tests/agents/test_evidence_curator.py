"""Unit tests for EvidenceCuratorAgent."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.agents.evidence_curator import EvidenceCuratorAgent, EvidenceInput, EvidenceOutput
from app.agents.rubrics.base import RubricResult


def _make_search_result(
    *,
    url: str = "https://example.com/review",
    snippet: str = "I love using this tool with my team every day, it saves us hours.",
    published_date: datetime | None = None,
) -> SimpleNamespace:
    return SimpleNamespace(
        url=url,
        snippet=snippet,
        published_date=published_date or datetime.now(tz=UTC) - timedelta(days=10),
        title="Review",
        source_kind="reddit",
    )


def _make_output(
    search_results: list | None = None,
    evidence_thin: bool = False,
) -> EvidenceOutput:
    scrape = MagicMock()
    extraction = MagicMock()
    results = search_results if search_results is not None else []
    return EvidenceOutput(
        scrape_result=scrape,
        search_results=results,
        extraction=extraction,
        evidence_thin=evidence_thin,
    )


class TestEvidenceCuratorEvaluateRubric:
    @pytest.mark.asyncio
    async def test_high_diversity_results_pass_rubric(self) -> None:
        agent = EvidenceCuratorAgent()
        results = [
            _make_search_result(url="https://reddit.com/r/tools/1"),
            _make_search_result(url="https://g2.com/review/1"),
            _make_search_result(url="https://capterra.com/review/1"),
            _make_search_result(url="https://twitter.com/user/1"),
            _make_search_result(url="https://reddit.com/r/tools/2"),
        ]
        output = _make_output(search_results=results)
        rubric = await agent.evaluate_rubric(EvidenceInput(url="https://example.com"), output)

        source_dim = next(d for d in rubric.dimensions if d.name == "source_diversity")
        assert source_dim.passed is True

    @pytest.mark.asyncio
    async def test_same_domain_results_fail_source_diversity_but_rubric_still_passes(
        self,
    ) -> None:
        """All soft gates — concentrated sources flag thin evidence but don't block."""
        agent = EvidenceCuratorAgent()
        results = [
            _make_search_result(url="https://g2.com/review/1"),
            _make_search_result(url="https://g2.com/review/2"),
            _make_search_result(url="https://g2.com/review/3"),
            _make_search_result(url="https://g2.com/review/4"),
            _make_search_result(url="https://g2.com/review/5"),
        ]
        output = _make_output(search_results=results)
        rubric = await agent.evaluate_rubric(EvidenceInput(url="https://example.com"), output)

        source_dim = next(d for d in rubric.dimensions if d.name == "source_diversity")
        assert source_dim.passed is False
        assert source_dim.is_hard_gate is False
        # Soft gates don't block
        assert rubric.passed is True

    @pytest.mark.asyncio
    async def test_empty_results_all_soft_gates_fail_rubric_still_passes(self) -> None:
        agent = EvidenceCuratorAgent()
        output = _make_output(search_results=[])
        rubric = await agent.evaluate_rubric(EvidenceInput(url="https://example.com"), output)

        assert all(not d.is_hard_gate for d in rubric.dimensions)
        assert rubric.passed is True


class TestEvidenceCuratorBuildRetryInput:
    def test_build_retry_input_sets_expand_search_true(self) -> None:
        agent = EvidenceCuratorAgent()
        original = EvidenceInput(url="https://example.com", expand_search=False)
        rubric = RubricResult(dimensions=[])

        retry = agent.build_retry_input(original, rubric)

        assert retry.url == "https://example.com"
        assert retry.expand_search is True

    def test_build_retry_input_always_expands_regardless_of_failure_reason(self) -> None:
        from app.agents.rubrics.base import RubricDimension

        agent = EvidenceCuratorAgent()
        original = EvidenceInput(url="https://myproduct.io")
        rubric = RubricResult(
            dimensions=[
                RubricDimension(
                    name="source_diversity",
                    passed=False,
                    score=0.1,
                    is_hard_gate=False,
                )
            ]
        )

        retry = agent.build_retry_input(original, rubric)

        assert retry.expand_search is True


class TestEvidenceCuratorExecute:
    @pytest.mark.asyncio
    async def test_thin_evidence_sets_evidence_thin_true(self) -> None:
        """When rubric fails (all soft gates), evidence_thin must be True after execute()."""
        agent = EvidenceCuratorAgent()

        fake_output = _make_output(search_results=[], evidence_thin=False)

        with (
            patch.object(agent, "run", new=AsyncMock(return_value=fake_output)),
            patch.object(
                agent,
                "evaluate_rubric",
                new=AsyncMock(
                    side_effect=[
                        # First attempt: all soft gates fail (but rubric.passed is True
                        # since they are soft). Simulate a hard-gate fail to trigger
                        # the evidence_thin path.
                        _failing_hard_rubric(),
                        _failing_hard_rubric(),
                    ]
                ),
            ),
            patch.object(agent, "build_retry_input", return_value=EvidenceInput(url="x")),
        ):
            agent.max_retries = 2
            result = await agent.execute(EvidenceInput(url="https://example.com"))

        assert result.rubric_passed is False
        assert result.result is not None
        assert result.result.evidence_thin is True

    @pytest.mark.asyncio
    async def test_passing_rubric_does_not_set_evidence_thin(self) -> None:
        agent = EvidenceCuratorAgent()
        fake_output = _make_output(search_results=[], evidence_thin=False)

        with (
            patch.object(agent, "run", new=AsyncMock(return_value=fake_output)),
            patch.object(
                agent,
                "evaluate_rubric",
                new=AsyncMock(return_value=RubricResult(dimensions=[])),
            ),
        ):
            result = await agent.execute(EvidenceInput(url="https://example.com"))

        assert result.rubric_passed is True
        assert result.result.evidence_thin is False


def _failing_hard_rubric() -> RubricResult:
    from app.agents.rubrics.base import RubricDimension

    return RubricResult(
        dimensions=[
            RubricDimension(
                name="test_hard_gate",
                passed=False,
                score=0.0,
                is_hard_gate=True,
            )
        ]
    )
