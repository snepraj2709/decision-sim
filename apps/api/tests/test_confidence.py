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

# Unit tests for compute_quote_coherence and compute_segment_stability.

# These functions are load-bearing for Step 3 ICP confidence scoring.
# Tests use deterministic embeddings (no randomness) and assert exact values.

class TestComputeQuoteCoherence:
    """Unit tests for compute_quote_coherence.
    
    Quote coherence measures how semantically similar a cluster's evidence 
    quotes are to each other. Used as a proxy for llm_baserate_agreement 
    in ICP confidence scoring.
    """

    @pytest.fixture
    def embedding_all_ones(self) -> list[float]:
        """Embedding with all ones — maximum self-similarity."""
        return [1.0] * 1536

    @pytest.fixture
    def embedding_truly_orthogonal(self) -> list[float]:
        """Embedding orthogonal to all_ones: positive half cancels negative half."""
        return [1.0 if i < 768 else -1.0 for i in range(1536)]

    @pytest.fixture
    def embedding_nearly_identical(self) -> list[float]:
        """Embedding nearly identical to all_ones with tiny noise."""
        return [1.0 + (0.001 if i % 100 == 0 else 0.0) for i in range(1536)]

    def test_empty_embeddings_return_zero(self) -> None:
        """Empty embedding list returns 0.0 coherence.
        
        In ICP pipeline: no evidence quotes means no coherence signal.
        The cluster is invalid; mark Low confidence and surface "Hypothesis."
        """
        result = compute_quote_coherence([])
        assert result == 0.0

    def test_single_embedding_returns_one(self, embedding_all_ones: list[float]) -> None:
        """Single embedding is trivially coherent (1.0).
        
        In ICP pipeline: one quote cannot contradict itself, so coherence 
        is undefined but we treat it as 1.0 (no disagreement). However, 
        evidence_density will still be low due to count=1.
        """
        result = compute_quote_coherence([embedding_all_ones])
        assert result == 1.0

    def test_identical_embeddings_maximum_coherence(self, embedding_all_ones: list[float]) -> None:
        """Two identical embeddings have maximum coherence (1.0).
        
        Cosine similarity = 1.0, transformed: (1.0 + 1.0) / 2 = 1.0.
        In ICP pipeline: two quotes with identical semantic content should 
        score high coherence, indicating segment consistency.
        """
        embeddings = [embedding_all_ones, embedding_all_ones]
        result = compute_quote_coherence(embeddings)
        assert result == 1.0

    def test_orthogonal_embeddings_mid_range_coherence(self, 
                                                        embedding_all_ones: list[float],
                                                        embedding_truly_orthogonal: list[float]) -> None:
        """Two orthogonal embeddings have mid-range coherence (~0.5).
        
        Cosine similarity of orthogonal vectors = 0.0, transformed: 
        (0.0 + 1.0) / 2 = 0.5. In ICP pipeline: completely unrelated 
        quotes (not contradictory, just unrelated) should score neutral 
        coherence. Not max incoherence (which would be -1 cosine sim).
        """
        embeddings = [embedding_all_ones, embedding_truly_orthogonal]
        result = compute_quote_coherence(embeddings)
        # Orthogonal → cosine_sim ≈ 0 → (0 + 1) / 2 = 0.5
        assert result == pytest.approx(0.5, abs=0.01)

    def test_nearly_identical_embeddings_high_coherence(self, 
                                                         embedding_all_ones: list[float],
                                                         embedding_nearly_identical: list[float]) -> None:
        """Nearly identical embeddings have near-maximum coherence (>0.98).
        
        Cosine similarity ≈ 0.9999, transformed ≈ 0.99995.
        In ICP pipeline: quotes that are almost identical but not quite 
        (e.g., same idea phrased slightly differently across sources).
        """
        embeddings = [embedding_all_ones, embedding_nearly_identical]
        result = compute_quote_coherence(embeddings)
        # Should be very close to 1.0
        assert 0.98 < result <= 1.0

    def test_three_embeddings_majority_agreement(self, 
                                                   embedding_all_ones: list[float],
                                                   embedding_truly_orthogonal: list[float]) -> None:
        """Three embeddings with two agreeing, one disagreeing.
        
        In ICP pipeline: a cluster of 5 evidence quotes where 3 are about 
        "speed" and 2 are about "cost" should produce medium coherence 
        (average of: high similarity between speed quotes, low between 
        speed and cost). Tests that coherence is the average, not 
        all-or-nothing.
        """
        # Two identical, one orthogonal
        embeddings = [embedding_all_ones, embedding_all_ones, embedding_truly_orthogonal]
        result = compute_quote_coherence(embeddings)
        
        # Pairwise similarities:
        # (0,1): cosine_sim = 1.0 → (1.0 + 1.0) / 2 = 1.0
        # (0,2): cosine_sim = 0.0 → (0.0 + 1.0) / 2 = 0.5
        # (1,2): cosine_sim = 0.0 → (0.0 + 1.0) / 2 = 0.5
        # avg transformed = (1.0 + 0.5 + 0.5) / 3 ≈ 0.667
        assert 0.65 < result < 0.70

    def test_five_embeddings_incoherent_cluster(self) -> None:
        """Five embeddings with no clear consensus (incoherent cluster).
        
        In ICP pipeline: a cluster of 5 quotes that are all orthogonal 
        to each other (e.g., one about price, one about UX, one about 
        support, one about performance, one about integrations). Should 
        score low coherence, suggesting the LLM imposed a name on noise 
        rather than discovering a real segment.
        """
        # Create 5 distinct orthogonal embeddings by shifting the nonzero region
        e1 = [1.0 if 0 <= i < 307 else 0.0 for i in range(1536)]
        e2 = [1.0 if 307 <= i < 614 else 0.0 for i in range(1536)]
        e3 = [1.0 if 614 <= i < 921 else 0.0 for i in range(1536)]
        e4 = [1.0 if 921 <= i < 1228 else 0.0 for i in range(1536)]
        e5 = [1.0 if 1228 <= i < 1536 else 0.0 for i in range(1536)]
        
        embeddings = [e1, e2, e3, e4, e5]
        result = compute_quote_coherence(embeddings)
        
        # All pairwise similarities ≈ 0, so all transformed ≈ 0.5
        # Average of all ≈ 0.5
        assert result == pytest.approx(0.5, abs=0.05)


class TestComputeSegmentStability:
    """Unit tests for compute_segment_stability.
    
    Segment stability measures how distinct a segment is from its neighbors.
    High stability = the segment is well-defined and not a duplicate.
    Low stability = the segment should probably have been merged with a neighbor.
    """

    @pytest.fixture
    def embedding_all_ones(self) -> list[float]:
        """Base embedding for testing."""
        return [1.0] * 1536

    @pytest.fixture
    def embedding_orthogonal(self) -> list[float]:
        """Embedding orthogonal to all_ones: positive half cancels negative half."""
        return [1.0 if i < 768 else -1.0 for i in range(1536)]

    def test_empty_segment_embedding_returns_zero(self, embedding_orthogonal: list[float]) -> None:
        """Empty segment embedding returns 0.0 stability.
        
        In ICP pipeline: a segment with no centroid cannot be compared to 
        neighbors. This is an invalid segment; treat as unstable.
        """
        result = compute_segment_stability([], [embedding_orthogonal])
        assert result == 0.0

    def test_no_other_segments_returns_one(self, embedding_all_ones: list[float]) -> None:
        """No other segments → stability = 1.0 (vacuously distinct).
        
        In ICP pipeline: if this is the only segment in the snapshot, 
        it's trivially distinct from all others (none exist).
        """
        result = compute_segment_stability(embedding_all_ones, [])
        assert result == 1.0

    def test_identical_to_another_returns_zero(self, embedding_all_ones: list[float]) -> None:
        """Segment identical to another → stability = 0.0 (duplicate).
        
        Cosine similarity = 1.0, stability = 1.0 - 1.0 = 0.0.
        In ICP pipeline: if another segment has an identical centroid, 
        they should have been merged. This segment is a duplicate and 
        should score Low confidence.
        """
        result = compute_segment_stability(embedding_all_ones, [embedding_all_ones])
        assert result == 0.0

    def test_orthogonal_to_all_others_returns_one(self, 
                                                    embedding_all_ones: list[float],
                                                    embedding_orthogonal: list[float]) -> None:
        """Segment orthogonal to all others → stability ≈ 1.0.
        
        Cosine similarity = 0.0, stability = 1.0 - 0.0 ≈ 1.0.
        In ICP pipeline: if this segment's centroid is orthogonal to all 
        neighbors (completely different semantic space), it's maximally 
        distinct and well-defined.
        """
        result = compute_segment_stability(embedding_all_ones, [embedding_orthogonal])
        assert result == pytest.approx(1.0, abs=0.01)

    def test_one_similar_neighbor_among_many_distant(self) -> None:
        """One very similar neighbor and many distant ones.
        
        In ICP pipeline: stability is determined by the MOST similar 
        neighbor, not the average. Even if all other segments are distant, 
        one very similar neighbor makes this segment unstable — it should 
        have been merged.
        """
        segment = [1.0] * 1536
        
        # Similar: 95% overlap (first 1460 dimensions same)
        similar = [1.0 if i < 1460 else 0.0 for i in range(1536)]
        
        # Distant: orthogonal
        distant_a = [0.0 if i < 768 else 1.0 for i in range(1536)]
        distant_b = [1.0 if i % 3 == 0 else 0.0 for i in range(1536)]
        distant_c = [1.0 if i % 5 == 0 else 0.0 for i in range(1536)]
        
        others = [similar, distant_a, distant_b, distant_c]
        result = compute_segment_stability(segment, others)
        
        # Max similarity is to 'similar' (cosine_sim ≈ 0.93)
        # Stability = 1.0 - 0.93 ≈ 0.07 (very unstable)
        assert 0.0 < result < 0.2

    def test_all_distant_neighbors_high_stability(self) -> None:
        """All neighbors are distant → stability ≈ 1.0.
        
        In ICP pipeline: if this segment is semantically distinct from 
        all others (no close neighbors), it's a well-defined, stable segment.
        """
        segment = [1.0 if i < 768 else -1.0 for i in range(1536)]
        
        # Create 4 distinct orthogonal embeddings
        other_a = [0.0 if i < 768 else 1.0 for i in range(1536)]
        other_b = [1.0 if i % 3 == 0 else 0.0 for i in range(1536)]
        other_c = [1.0 if i % 5 == 0 else 0.0 for i in range(1536)]
        other_d = [1.0 if i % 7 == 0 else 0.0 for i in range(1536)]
        
        others = [other_a, other_b, other_c, other_d]
        result = compute_segment_stability(segment, others)
        
        # All neighbors are near-orthogonal, so max similarity ≈ 0
        # Stability = 1.0 - 0 ≈ 1.0
        assert result > 0.90

    def test_multiple_similar_neighbors_lowest_max_wins(self) -> None:
        """Multiple similar neighbors — stability penalized by the most similar.
        
        In ICP pipeline: if two neighbors are similar to this segment, 
        the stability is determined by the ONE that's most similar 
        (worst case). Stability = 1.0 - max(similarities).
        """
        segment = [1.0] * 1536
        
        # Two similar neighbors
        similar_a = [1.0 if i < 1000 else 0.0 for i in range(1536)]  # ~82% overlap
        similar_b = [1.0 if i < 900 else 0.0 for i in range(1536)]   # ~58% overlap
        
        # One distant
        distant = [0.0 if i < 768 else 1.0 for i in range(1536)]
        
        others = [similar_a, similar_b, distant]
        result = compute_segment_stability(segment, others)
        
        # Max similarity is to similar_a (cosine_sim ≈ 0.82)
        # Stability = 1.0 - 0.82 = 0.18 (unstable due to similar_a)
        assert 0.1 < result < 0.3
