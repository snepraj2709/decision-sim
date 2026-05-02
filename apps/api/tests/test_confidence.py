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
    compute_quote_coherence,
    compute_segment_stability,
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


# ─── compute_quote_coherence (Step 3) ──────────────────────────────────────
class TestQuoteCoherence:
    """Tests for ICP quote coherence computation."""

    def test_empty_list_returns_zero(self) -> None:
        """No evidence = no coherence."""
        assert compute_quote_coherence([]) == 0.0

    def test_single_embedding_returns_one(self) -> None:
        """Single quote is trivially coherent."""
        embedding = [1.0, 0.0, 0.0]
        assert compute_quote_coherence([embedding]) == 1.0

    def test_identical_embeddings_returns_one(self) -> None:
        """All identical quotes = maximally coherent."""
        embedding = [1.0, 0.5, 0.25]
        result = compute_quote_coherence([embedding, embedding, embedding])
        assert result == pytest.approx(1.0)

    def test_orthogonal_embeddings_returns_half(self) -> None:
        """Orthogonal vectors have cosine similarity 0, mapped to 0.5."""
        e1 = [1.0, 0.0, 0.0]
        e2 = [0.0, 1.0, 0.0]
        e3 = [0.0, 0.0, 1.0]
        result = compute_quote_coherence([e1, e2, e3])
        # Pairwise sims are all 0.0, average is 0.0
        # (0 + 1) / 2 = 0.5
        assert result == pytest.approx(0.5)

    def test_opposite_embeddings_clamps_to_zero(self) -> None:
        """Opposite vectors (-1 similarity) clamp coherence to 0."""
        e1 = [1.0, 0.0]
        e2 = [-1.0, 0.0]
        result = compute_quote_coherence([e1, e2])
        # Cosine similarity = -1, ((-1) + 1) / 2 = 0.0
        assert result == pytest.approx(0.0)

    def test_high_coherence_for_similar_vectors(self) -> None:
        """Similar vectors should have high coherence."""
        e1 = [1.0, 0.1, 0.0]
        e2 = [1.0, 0.2, 0.0]
        e3 = [1.0, 0.15, 0.0]
        result = compute_quote_coherence([e1, e2, e3])
        # These are nearly parallel, should have high similarity
        assert result > 0.9

    def test_mixed_coherence(self) -> None:
        """Mixed directions should have moderate coherence."""
        e1 = [1.0, 0.0]
        e2 = [0.707, 0.707]  # 45 degrees from e1
        result = compute_quote_coherence([e1, e2])
        # cos(45°) ≈ 0.707, mapped to (0.707 + 1) / 2 ≈ 0.85
        assert 0.8 < result < 0.9


# ─── compute_segment_stability (Step 3) ────────────────────────────────────
class TestSegmentStability:
    """Tests for ICP segment stability computation."""

    def test_empty_others_returns_one(self) -> None:
        """Only segment = maximally distinct."""
        segment = [1.0, 0.0, 0.0]
        assert compute_segment_stability(segment, []) == 1.0

    def test_empty_segment_returns_zero(self) -> None:
        """Invalid segment embedding = zero stability."""
        assert compute_segment_stability([], [[1.0, 0.0]]) == 0.0

    def test_identical_to_other_returns_zero(self) -> None:
        """Duplicate of another segment = zero stability."""
        segment = [1.0, 0.5, 0.25]
        others = [segment]  # Same embedding
        result = compute_segment_stability(segment, others)
        assert result == pytest.approx(0.0)

    def test_orthogonal_to_others_returns_one(self) -> None:
        """Completely orthogonal = maximally stable."""
        segment = [1.0, 0.0, 0.0]
        others = [[0.0, 1.0, 0.0], [0.0, 0.0, 1.0]]
        result = compute_segment_stability(segment, others)
        # Max similarity is 0.0, so stability is 1.0
        assert result == pytest.approx(1.0)

    def test_partial_overlap_returns_moderate(self) -> None:
        """Partial overlap = moderate stability."""
        segment = [1.0, 0.0]
        others = [[0.707, 0.707]]  # 45 degrees
        result = compute_segment_stability(segment, others)
        # cos(45°) ≈ 0.707, stability = 1 - 0.707 ≈ 0.293
        assert 0.2 < result < 0.4

    def test_takes_max_overlap(self) -> None:
        """Should use the MAXIMUM overlap, not average."""
        segment = [1.0, 0.0, 0.0]
        others = [
            [0.0, 1.0, 0.0],  # orthogonal, sim = 0
            [0.9, 0.436, 0.0],  # nearly parallel, sim ≈ 0.9
        ]
        result = compute_segment_stability(segment, others)
        # Max similarity is ~0.9, so stability is ~0.1
        assert result < 0.2

    def test_mismatched_dimensions_ignored(self) -> None:
        """Others with wrong dimensions are skipped."""
        segment = [1.0, 0.0, 0.0]
        others = [
            [1.0, 0.0],  # Wrong dimension, should be skipped
            [0.0, 1.0, 0.0],  # Orthogonal, sim = 0
        ]
        result = compute_segment_stability(segment, others)
        # Only orthogonal one counts, stability = 1.0
        assert result == pytest.approx(1.0)

    def test_negative_similarity_not_counted(self) -> None:
        """Negative similarity (opposite) doesn't reduce stability."""
        segment = [1.0, 0.0]
        others = [[-1.0, 0.0]]  # Opposite direction
        result = compute_segment_stability(segment, others)
        # Cosine sim = -1, but we only care about positive overlap
        # max_similarity stays at 0 (clamped), stability = 1.0
        # Actually wait - the code uses raw similarity, let me check
        # The code does: if sim > max_similarity, so -1 won't update max from 0
        assert result == pytest.approx(1.0)
