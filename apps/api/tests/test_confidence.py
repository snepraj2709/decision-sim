"""Tests for app.core.confidence — the engine's epistemic backbone.

These tests are aggressive on purpose. The whole product's trustworthiness
rides on this module behaving sensibly at edge cases.
"""

import pytest

from app.core.confidence import (
    HIGH_THRESHOLD,
    MEDIUM_THRESHOLD,
    TriangulationInput,
    baserate_agreement_from_overlap,
    combined_score,
    evidence_density_from_count,
    triangulate,
)


# ─── evidence_density_from_count ────────────────────────────────────────────
class TestEvidenceDensity:
    def test_zero_sources_is_zero(self) -> None:
        assert evidence_density_from_count(0) == 0.0

    def test_negative_treated_as_zero(self) -> None:
        assert evidence_density_from_count(-1) == 0.0

    def test_min_threshold_is_one(self) -> None:
        assert evidence_density_from_count(3, min_for_high=3) == 1.0

    def test_above_threshold_caps_at_one(self) -> None:
        assert evidence_density_from_count(20, min_for_high=3) == 1.0

    def test_partial(self) -> None:
        assert evidence_density_from_count(2, min_for_high=4) == pytest.approx(0.5)


# ─── baserate_agreement_from_overlap ────────────────────────────────────────
class TestBaserateAgreement:
    def test_full_containment(self) -> None:
        # LLM says 8-12%, base rate says 5-15% → LLM band fully vouched for
        assert baserate_agreement_from_overlap(8, 12, 5, 15) == 1.0

    def test_disjoint_bands(self) -> None:
        # LLM says 60%, base rate says 5-15% → no overlap, suspicious
        assert baserate_agreement_from_overlap(50, 60, 5, 15) == 0.0

    def test_partial_overlap(self) -> None:
        # LLM 10-20, base 5-15 → overlap is 10-15 (width 5), LLM width 10 → 0.5
        assert baserate_agreement_from_overlap(10, 20, 5, 15) == pytest.approx(0.5)

    def test_inverted_band_raises(self) -> None:
        with pytest.raises(ValueError):
            baserate_agreement_from_overlap(20, 10, 5, 15)


# ─── triangulate ────────────────────────────────────────────────────────────
class TestTriangulate:
    def test_all_high_yields_high(self) -> None:
        assert triangulate(TriangulationInput(1.0, 1.0, 1.0)) == "high"

    def test_all_zero_yields_low(self) -> None:
        assert triangulate(TriangulationInput(0.0, 0.0, 0.0)) == "low"

    def test_one_zero_axis_drags_to_low(self) -> None:
        """The geometric mean property: one weak signal kills the score.

        This is the load-bearing behavior. A fluent LLM answer with zero
        evidence anchors must NOT round to High.
        """
        result = triangulate(TriangulationInput(1.0, 0.0, 1.0))
        assert result == "low"

    def test_one_low_axis_pulls_to_medium_or_low(self) -> None:
        """Two strong signals can't fully compensate for one weak one."""
        result = triangulate(TriangulationInput(1.0, 0.3, 1.0))
        # 0.3 ** (1/3) ≈ 0.669 → medium (above 0.45, below 0.75)
        assert result == "medium"

    def test_uniform_low_signals_yields_low(self) -> None:
        assert triangulate(TriangulationInput(0.4, 0.4, 0.4)) == "low"

    def test_uniform_mid_signals_yields_medium(self) -> None:
        assert triangulate(TriangulationInput(0.6, 0.6, 0.6)) == "medium"

    def test_uniform_high_signals_yields_high(self) -> None:
        assert triangulate(TriangulationInput(0.85, 0.85, 0.85)) == "high"

    def test_thresholds_are_consistent(self) -> None:
        """The thresholds should sort: 0 < MED < HIGH < 1."""
        assert 0.0 < MEDIUM_THRESHOLD < HIGH_THRESHOLD < 1.0

    def test_clamps_inputs_above_one(self) -> None:
        # Defensive: malformed inputs shouldn't raise — just clamp.
        result = triangulate(TriangulationInput(1.5, 1.5, 1.5))
        assert result == "high"

    def test_clamps_negative_inputs(self) -> None:
        result = triangulate(TriangulationInput(-0.5, 1.0, 1.0))
        assert result == "low"


class TestCombinedScore:
    def test_returns_float(self) -> None:
        score = combined_score(TriangulationInput(0.8, 0.8, 0.8))
        assert isinstance(score, float)
        assert 0.0 <= score <= 1.0

    def test_geometric_mean_property(self) -> None:
        # If one axis is 0, score is 0
        assert combined_score(TriangulationInput(1.0, 0.0, 1.0)) == 0.0
