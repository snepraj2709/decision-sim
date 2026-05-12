"""Unit tests for deterministic rubric evaluators."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest

from app.agents.rubrics.functional import (
    check_anchor_density,
    check_calibration_alignment,
    check_customer_voice_ratio,
    check_recency,
    check_segment_distinctness,
    check_source_diversity,
)


def _search_result(
    *,
    url: str | None = "https://example.com/review",
    published_date: datetime | None = None,
) -> SimpleNamespace:
    return SimpleNamespace(url=url, published_date=published_date)


def _segment(name: str, evidence: list[str]) -> SimpleNamespace:
    return SimpleNamespace(name=name, evidence=evidence)


class TestCheckSourceDiversity:
    def test_empty_results_fail_soft_gate_with_zero_score(self) -> None:
        result = check_source_diversity([])

        assert result.name == "source_diversity"
        assert result.passed is False
        assert result.score == 0.0
        assert result.is_hard_gate is False

    def test_passes_when_unique_domain_ratio_meets_threshold(self) -> None:
        result = check_source_diversity(
            [
                _search_result(url="https://alpha.example/a"),
                _search_result(url="https://beta.example/b"),
                _search_result(url="https://alpha.example/c"),
            ],
            threshold=0.50,
        )

        assert result.passed is True
        assert result.score == pytest.approx(2 / 3)

    def test_fails_when_unique_domain_ratio_is_below_threshold(self) -> None:
        result = check_source_diversity(
            [
                _search_result(url="https://alpha.example/a"),
                _search_result(url="https://alpha.example/b"),
                _search_result(url="https://alpha.example/c"),
            ],
            threshold=0.50,
        )

        assert result.passed is False
        assert result.score == pytest.approx(1 / 3)
        assert result.is_hard_gate is False

    def test_zero_valid_urls_gives_zero_score(self) -> None:
        result = check_source_diversity(
            [
                _search_result(url=None),
                SimpleNamespace(),
            ]
        )

        assert result.passed is False
        assert result.score == 0.0


class TestCheckRecency:
    def test_empty_results_fail_soft_gate_with_zero_score(self) -> None:
        result = check_recency([])

        assert result.name == "recency_score"
        assert result.passed is False
        assert result.score == 0.0
        assert result.is_hard_gate is False

    def test_passes_when_recent_ratio_meets_threshold(self) -> None:
        now = datetime.now(tz=UTC)

        result = check_recency(
            [
                _search_result(published_date=now - timedelta(days=10)),
                _search_result(published_date=now - timedelta(days=20)),
                _search_result(published_date=now - timedelta(days=900)),
            ],
            threshold=0.50,
            months=18,
        )

        assert result.passed is True
        assert result.score == pytest.approx(2 / 3)

    def test_fails_when_recent_ratio_is_below_threshold(self) -> None:
        old = datetime.now(tz=UTC) - timedelta(days=900)

        result = check_recency(
            [
                _search_result(published_date=old),
                _search_result(published_date=old),
            ],
            threshold=0.50,
            months=18,
        )

        assert result.passed is False
        assert result.score == 0.0
        assert result.is_hard_gate is False

    def test_missing_dates_count_against_recency(self) -> None:
        recent = datetime.now(tz=UTC) - timedelta(days=10)

        result = check_recency(
            [
                _search_result(published_date=recent),
                _search_result(published_date=None),
                SimpleNamespace(url="https://undated.example"),
            ],
            threshold=0.50,
        )

        assert result.passed is False
        assert result.score == pytest.approx(1 / 3)


class TestCheckCustomerVoiceRatio:
    def test_empty_snippets_fail_soft_gate_with_zero_score(self) -> None:
        result = check_customer_voice_ratio([])

        assert result.name == "customer_voice_ratio"
        assert result.passed is False
        assert result.score == 0.0
        assert result.is_hard_gate is False

    def test_passes_when_customer_voice_ratio_meets_threshold(self) -> None:
        result = check_customer_voice_ratio(
            [
                "I have used this product with my team for months and it saves us hours every week.",
                "Pricing plans are billed per user per month with upgrade options for teams.",
            ],
            threshold=0.50,
        )

        assert result.passed is True
        assert result.score == pytest.approx(0.5)

    def test_fails_when_customer_voice_ratio_is_below_threshold(self) -> None:
        result = check_customer_voice_ratio(
            [
                "I have used this product with my team for months and it saves us hours every week.",
                "Pricing plans are billed per user per month with upgrade options for teams.",
                "This privacy policy explains cookies, terms of service, sign up, and login behavior.",
            ],
            threshold=0.50,
        )

        assert result.passed is False
        assert result.score == pytest.approx(1 / 3)
        assert result.is_hard_gate is False

    def test_all_non_customer_snippets_give_zero_score(self) -> None:
        result = check_customer_voice_ratio(
            [
                "Pricing plans are billed per user per month with upgrade options for teams.",
                "This privacy policy explains cookies, terms of service, sign up, and login behavior.",
            ],
            threshold=0.50,
        )

        assert result.passed is False
        assert result.score == 0.0


class TestCheckAnchorDensity:
    def test_empty_segments_vacuously_pass(self) -> None:
        result = check_anchor_density([])

        assert result.name == "anchor_density"
        assert result.passed is True
        assert result.score == 1.0
        assert result.is_hard_gate is True

    def test_single_segment_with_enough_anchors_passes(self) -> None:
        result = check_anchor_density(
            [_segment("Enterprise teams", ["quote one", "quote two"])],
            min_anchors=2,
        )

        assert result.passed is True
        assert result.score == 1.0

    def test_thin_segments_fail_hard_gate(self) -> None:
        result = check_anchor_density(
            [
                _segment("Enterprise teams", ["quote one", "quote two"]),
                _segment("Startup teams", ["quote one"]),
            ],
            min_anchors=2,
        )

        assert result.passed is False
        assert result.score == pytest.approx(0.5)
        assert result.is_hard_gate is True
        assert "Startup teams" in (result.reason or "")

    def test_all_thin_segments_give_zero_score(self) -> None:
        result = check_anchor_density(
            [_segment("Startup teams", [])],
            min_anchors=2,
        )

        assert result.passed is False
        assert result.score == 0.0


class TestCheckSegmentDistinctness:
    def test_single_segment_embedding_passes_as_not_applicable(self) -> None:
        result = check_segment_distinctness([[1.0, 0.0, 0.0]])

        assert result.name == "segment_distinctness"
        assert result.passed is True
        assert result.score == 1.0
        assert result.is_hard_gate is True

    def test_distinct_embeddings_pass(self) -> None:
        result = check_segment_distinctness(
            [
                [1.0, 0.0, 0.0],
                [0.0, 1.0, 0.0],
                [0.0, 0.0, 1.0],
            ],
            max_similarity=0.92,
        )

        assert result.passed is True
        assert result.score == pytest.approx(1.0)

    def test_duplicate_embeddings_fail_with_zero_score(self) -> None:
        result = check_segment_distinctness(
            [
                [1.0, 0.0, 0.0],
                [1.0, 0.0, 0.0],
            ],
            max_similarity=0.92,
        )

        assert result.passed is False
        assert result.score == 0.0
        assert result.is_hard_gate is True


class TestCheckCalibrationAlignment:
    def test_missing_base_rate_passes_soft_gate(self) -> None:
        result = check_calibration_alignment(
            churn_range_low=10,
            churn_range_high=20,
            option_type="unknown",
            calibration_rate=None,
            calibration_n=0,
        )

        assert result.name == "calibration_alignment"
        assert result.passed is True
        assert result.score == 1.0
        assert result.is_hard_gate is False

    def test_overlapping_range_passes(self) -> None:
        result = check_calibration_alignment(
            churn_range_low=8,
            churn_range_high=12,
            option_type="price_increase",
            calibration_rate=0.10,
            calibration_n=100,
        )

        assert result.passed is True
        assert result.score == 1.0
        assert result.is_hard_gate is True

    def test_non_overlapping_range_is_soft_gate_when_n_less_than_five(self) -> None:
        result = check_calibration_alignment(
            churn_range_low=80,
            churn_range_high=90,
            option_type="price_increase",
            calibration_rate=0.10,
            calibration_n=4,
        )

        assert result.passed is False
        assert result.is_hard_gate is False
        assert 0.0 <= result.score < 1.0

    def test_non_overlapping_range_is_hard_gate_when_n_at_least_five(self) -> None:
        result = check_calibration_alignment(
            churn_range_low=80,
            churn_range_high=90,
            option_type="price_increase",
            calibration_rate=0.10,
            calibration_n=100,
        )

        assert result.passed is False
        assert result.is_hard_gate is True
        assert 0.0 <= result.score < 1.0

    def test_far_misalignment_can_score_zero(self) -> None:
        result = check_calibration_alignment(
            churn_range_low=100,
            churn_range_high=100,
            option_type="price_increase",
            calibration_rate=0.0,
            calibration_n=10,
        )

        assert result.passed is False
        assert result.score == 0.0
        assert result.is_hard_gate is True
