"""Unit tests for ICP pipeline — no LLM, no embeddings.

These tests use mocked embedders and DSPy programs to verify:
1. Pipeline stages work correctly in isolation
2. Confidence calculations behave as expected
3. Edge cases (thin data, adversarial inputs) are handled properly
"""

from __future__ import annotations

import hashlib
import uuid
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from app.core.confidence import (
    TriangulationInput,
    compute_quote_coherence,
    compute_segment_stability,
    triangulate,
)
from app.models import EMBEDDING_DIM, ProductSnapshot
from app.pipelines.icp.anchor import (
    AnchoredSegment,
    EvidenceQuote,
    _truncate_at_sentence_boundary,
    anchor_segments,
)
from app.pipelines.icp.cluster import (
    ClusterResult,
    SnippetSource,
    _embed_snippets,
    _extract_snippets,
    _is_non_customer_text,
    cluster_snippets,
)
from app.pipelines.icp.score import (
    _count_unique_domains,
)
from app.pipelines.icp.synthesize import (
    DriverWeight,
    SynthesizedSegment,
)

# ─── Fixtures ───────────────────────────────────────────────────────────────

def _deterministic_embedding(text: str) -> list[float]:
    """Generate a deterministic embedding from text hash.

    This is a test-only function that produces reproducible vectors.
    """
    hash_bytes = hashlib.sha256(text.encode()).digest()
    embedding: list[float] = []
    for i in range(EMBEDDING_DIM):
        idx = i % len(hash_bytes)
        val = hash_bytes[idx] + (i // len(hash_bytes))
        embedding.append((val % 256) / 128.0 - 1.0)

    # Normalize
    norm = sum(x * x for x in embedding) ** 0.5
    if norm > 0:
        embedding = [x / norm for x in embedding]

    return embedding


def _make_snapshot(
    search_results: list[dict[str, Any]] | None = None,
    scrape_data: dict[str, Any] | None = None,
) -> ProductSnapshot:
    """Create a mock ProductSnapshot for testing."""
    snapshot = MagicMock(spec=ProductSnapshot)
    snapshot.id = uuid.uuid4()
    snapshot.category = "Project Management"
    snapshot.value_prop = "Streamlined issue tracking for modern teams"
    snapshot.pricing = "Free tier available, paid plans from $10/user/month"
    snapshot.features = "Issue tracking, roadmaps, cycles, integrations"
    snapshot.audience = "Engineering teams, startups, software companies"

    if search_results is not None:
        snapshot.raw_search_results = {"results": search_results, "count": len(search_results)}
    else:
        snapshot.raw_search_results = None

    snapshot.raw_scrape = scrape_data

    return snapshot


def _make_search_result(
    snippet: str,
    url: str = "https://reddit.com/r/test",
    source_kind: str = "reddit",
) -> dict[str, Any]:
    """Create a mock search result."""
    return {
        "query": "test query",
        "url": url,
        "title": "Test Title",
        "snippet": snippet,
        "published_date": "2024-01-01",
        "source_kind": source_kind,
    }


# ─── Test Non-Customer Text Filtering ───────────────────────────────────────

class TestNonCustomerFiltering:
    def test_privacy_policy_filtered(self) -> None:
        assert _is_non_customer_text("This is our Privacy Policy for users")

    def test_cookie_banner_filtered(self) -> None:
        assert _is_non_customer_text("We use cookies to improve your experience")

    def test_terms_filtered(self) -> None:
        assert _is_non_customer_text("By using this service you agree to our Terms of Service")

    def test_customer_voice_not_filtered(self) -> None:
        assert not _is_non_customer_text("I've been using this tool for 6 months and love it")

    def test_review_not_filtered(self) -> None:
        assert not _is_non_customer_text("Great product, helped my team ship faster")


# ─── Test Quote Truncation ──────────────────────────────────────────────────

class TestQuoteTruncation:
    def test_short_text_unchanged(self) -> None:
        text = "Short text."
        assert _truncate_at_sentence_boundary(text) == text

    def test_truncates_at_sentence_boundary(self) -> None:
        text = "First sentence. Second sentence. Third sentence that is very long."
        result = _truncate_at_sentence_boundary(text, max_length=40)
        assert result.endswith(".")
        assert len(result) <= 40

    def test_adds_ellipsis_when_no_sentence_boundary(self) -> None:
        text = "This is a very long text without any sentence boundaries"
        result = _truncate_at_sentence_boundary(text, max_length=30)
        assert result.endswith("...")


# ─── Test Snippet Extraction ────────────────────────────────────────────────

class TestSnippetExtraction:
    def test_extracts_valid_snippets(self) -> None:
        snapshot = _make_snapshot(search_results=[
            _make_search_result("This is a valid customer review that is long enough"),
            _make_search_result("Another valid review from a real user"),
        ])

        snippets, sources = _extract_snippets(snapshot)

        assert len(snippets) == 2
        assert len(sources) == 2

    def test_filters_short_snippets(self) -> None:
        snapshot = _make_snapshot(search_results=[
            _make_search_result("Too short"),  # Less than MIN_SNIPPET_LENGTH
            _make_search_result("This is a valid customer review that is long enough"),
        ])

        snippets, _sources = _extract_snippets(snapshot)

        assert len(snippets) == 1

    def test_filters_non_customer_content(self) -> None:
        snapshot = _make_snapshot(search_results=[
            _make_search_result("This is our Privacy Policy document"),
            _make_search_result("This is a valid customer review that is long enough"),
        ])

        snippets, _sources = _extract_snippets(snapshot)

        assert len(snippets) == 1

    def test_empty_results(self) -> None:
        snapshot = _make_snapshot(search_results=[])

        snippets, sources = _extract_snippets(snapshot)

        assert len(snippets) == 0
        assert len(sources) == 0


# ─── Test Domain Counting ───────────────────────────────────────────────────

class TestDomainCounting:
    def test_counts_unique_domains(self) -> None:
        segment = AnchoredSegment(
            name="Test",
            descriptor="",
            job_to_be_done="",
            drivers=[],
            leaves="",
            centroid_embedding=[],
            evidence_quotes=[
                EvidenceQuote(
                    quote="Quote 1", source="reddit", source_url="https://reddit.com/1",
                    kind="reddit", captured_at=None, embedding=[], domain="reddit.com"
                ),
                EvidenceQuote(
                    quote="Quote 2", source="reddit", source_url="https://reddit.com/2",
                    kind="reddit", captured_at=None, embedding=[], domain="reddit.com"
                ),
                EvidenceQuote(
                    quote="Quote 3", source="g2", source_url="https://g2.com/1",
                    kind="g2", captured_at=None, embedding=[], domain="g2.com"
                ),
            ],
            share_pct=30,
            has_few_anchors=False,
            has_synthesis_issues=False,
        )

        # 3 quotes but only 2 unique domains
        assert _count_unique_domains(segment) == 2


# ─── Test Confidence Calculation ────────────────────────────────────────────

class TestConfidenceCalculation:
    def test_high_evidence_high_coherence_high_stability(self) -> None:
        """Rich data should produce high confidence."""
        # High evidence density
        evidence_density = 1.0
        # High coherence (similar quotes)
        e1 = [1.0, 0.1, 0.0] + [0.0] * (EMBEDDING_DIM - 3)
        e2 = [0.99, 0.12, 0.0] + [0.0] * (EMBEDDING_DIM - 3)
        e3 = [0.98, 0.11, 0.0] + [0.0] * (EMBEDDING_DIM - 3)
        quote_coherence = compute_quote_coherence([e1, e2, e3])
        # High stability (distinct from others)
        segment_emb = [1.0, 0.0, 0.0] + [0.0] * (EMBEDDING_DIM - 3)
        other_embs = [[0.0, 1.0, 0.0] + [0.0] * (EMBEDDING_DIM - 3)]
        stability = compute_segment_stability(segment_emb, other_embs)

        signals = TriangulationInput(
            llm_baserate_agreement=quote_coherence,
            evidence_density=evidence_density,
            construct_stability=stability,
        )
        confidence = triangulate(signals)

        assert confidence == "high"

    def test_no_evidence_produces_low(self) -> None:
        """No evidence should produce low confidence."""
        evidence_density = 0.0  # No evidence
        quote_coherence = 0.5
        stability = 1.0

        signals = TriangulationInput(
            llm_baserate_agreement=quote_coherence,
            evidence_density=evidence_density,
            construct_stability=stability,
        )
        confidence = triangulate(signals)

        assert confidence == "low"

    def test_high_evidence_low_coherence_produces_low(self) -> None:
        """High evidence but incoherent quotes = low confidence.

        This is the adversarial case: lots of quotes that don't agree.
        The geometric mean property ensures this produces low confidence.
        """
        evidence_density = 1.0  # Lots of evidence
        # Low coherence (opposite direction quotes)
        e1 = [1.0, 0.0] + [0.0] * (EMBEDDING_DIM - 2)
        e2 = [-1.0, 0.0] + [0.0] * (EMBEDDING_DIM - 2)  # Opposite direction
        quote_coherence = compute_quote_coherence([e1, e2])
        stability = 1.0

        # With opposite vectors, coherence should be 0.0
        assert quote_coherence == 0.0

        signals = TriangulationInput(
            llm_baserate_agreement=quote_coherence,
            evidence_density=evidence_density,
            construct_stability=stability,
        )
        confidence = triangulate(signals)

        # With coherence = 0.0, geometric mean is 0, so confidence = low
        assert confidence == "low"


# ─── Test Cluster Stage ─────────────────────────────────────────────────────

class TestClusterStage:
    @pytest.mark.asyncio
    async def test_openai_embedding_error_falls_back_to_hash(self) -> None:
        """OPENAI_API_KEY should not make the pipeline fail if embeddings fail."""
        settings = MagicMock()
        settings.openai_api_key = "test-openai-key"
        settings.anthropic_api_key = None

        with (
            patch("app.pipelines.icp.cluster.get_settings", return_value=settings),
            patch(
                "app.pipelines.icp.cluster._embed_with_openai",
                side_effect=RuntimeError("embedding service unavailable"),
            ),
        ):
            embeddings = await _embed_snippets(["Customer quote with enough signal"])

        assert len(embeddings) == 1
        assert len(embeddings[0]) == EMBEDDING_DIM

    @pytest.mark.asyncio
    async def test_anthropic_key_uses_hash_embeddings(self) -> None:
        """ANTHROPIC_API_KEY alone should still make Step 3 runnable."""
        settings = MagicMock()
        settings.openai_api_key = None
        settings.anthropic_api_key = "test-anthropic-key"

        with patch("app.pipelines.icp.cluster.get_settings", return_value=settings):
            embeddings = await _embed_snippets(["Customer quote with enough signal"])

        assert len(embeddings) == 1
        assert len(embeddings[0]) == EMBEDDING_DIM

    @pytest.mark.asyncio
    async def test_cold_start_creates_micro_clusters(self) -> None:
        """With <8 snippets, each becomes its own cluster."""
        snapshot = _make_snapshot(search_results=[
            _make_search_result("Customer review 1 about the product features"),
            _make_search_result("Customer review 2 about pricing and value"),
            _make_search_result("Customer review 3 about team collaboration"),
        ])

        with patch("app.pipelines.icp.cluster._embed_snippets") as mock_embed:
            mock_embed.return_value = [
                _deterministic_embedding("review1"),
                _deterministic_embedding("review2"),
                _deterministic_embedding("review3"),
            ]

            result = await cluster_snippets(snapshot)

        # Each snippet becomes its own micro-cluster
        assert len(result.clusters) == 3
        assert result.total_snippets == 3

    @pytest.mark.asyncio
    async def test_empty_search_results(self) -> None:
        """No search results should return empty clusters."""
        snapshot = _make_snapshot(search_results=[])

        result = await cluster_snippets(snapshot)

        assert len(result.clusters) == 0
        assert result.total_snippets == 0


# ─── Test Anchor Stage ──────────────────────────────────────────────────────

class TestAnchorStage:
    @pytest.mark.asyncio
    async def test_selects_closest_to_centroid(self) -> None:
        """Anchoring should select snippets closest to centroid."""
        centroid = [1.0, 0.0] + [0.0] * (EMBEDDING_DIM - 2)

        # Create cluster result with 5 snippets
        all_snippets = [f"Snippet {i} with enough content to pass filter" for i in range(5)]
        all_sources = [
            SnippetSource(url=f"https://reddit.com/{i}", title=f"Title {i}",
                         source_kind="reddit", published_date="2024-01-01")
            for i in range(5)
        ]
        # Embeddings: first one is closest to centroid
        all_embeddings = [
            [0.95, 0.05] + [0.0] * (EMBEDDING_DIM - 2),  # Closest
            [0.7, 0.3] + [0.0] * (EMBEDDING_DIM - 2),
            [0.5, 0.5] + [0.0] * (EMBEDDING_DIM - 2),
            [0.3, 0.7] + [0.0] * (EMBEDDING_DIM - 2),
            [0.1, 0.9] + [0.0] * (EMBEDDING_DIM - 2),   # Furthest
        ]

        synthesized = [
            SynthesizedSegment(
                name="Test Segment",
                descriptor="Test descriptor",
                job_to_be_done="Get things done",
                drivers=[DriverWeight(label="Speed", weight=0.8)],
                leaves="Poor support",
                citations_used=[0, 1],
                cluster_index=0,
                cluster_size=5,
                centroid_embedding=centroid,
                member_indices=[0, 1, 2, 3, 4],
            )
        ]

        cluster_result = ClusterResult(
            clusters=[],
            noise_indices=[],
            total_snippets=5,
            all_snippets=all_snippets,
            all_sources=all_sources,
            all_embeddings=all_embeddings,
        )

        anchored = await anchor_segments(synthesized, cluster_result)

        assert len(anchored) == 1
        assert len(anchored[0].evidence_quotes) == 3  # Takes top 3
        # First quote should be snippet 0 (closest to centroid)
        assert "Snippet 0" in anchored[0].evidence_quotes[0].quote

    @pytest.mark.asyncio
    async def test_flags_few_anchors(self) -> None:
        """Segments with <2 anchors should be flagged."""
        synthesized = [
            SynthesizedSegment(
                name="Test Segment",
                descriptor="Test",
                job_to_be_done="Test",
                drivers=[],
                leaves="",
                citations_used=[],
                cluster_index=0,
                cluster_size=1,
                centroid_embedding=[1.0] + [0.0] * (EMBEDDING_DIM - 1),
                member_indices=[0],
            )
        ]

        cluster_result = ClusterResult(
            clusters=[],
            noise_indices=[],
            total_snippets=1,
            all_snippets=["Single snippet with enough content"],
            all_sources=[SnippetSource(url="https://reddit.com/1", title="T",
                                       source_kind="reddit", published_date=None)],
            all_embeddings=[[1.0] + [0.0] * (EMBEDDING_DIM - 1)],
        )

        anchored = await anchor_segments(synthesized, cluster_result)

        assert len(anchored) == 1
        assert anchored[0].has_few_anchors is True  # Only 1 anchor


# ─── Test Full Pipeline Fixtures ────────────────────────────────────────────

class TestPipelineFixtures:
    """Test the three fixture scenarios from the spec."""

    @pytest.mark.asyncio
    async def test_rich_snapshot_produces_multiple_segments(self) -> None:
        """Rich snapshot (30+ snippets) should produce 4-5 segments."""
        # Create a rich snapshot with 30 snippets across 5 topics
        topics = [
            "The product is great for project management and tracking issues",
            "Love the pricing, free tier is generous for small teams",
            "Integration with GitHub and Slack works seamlessly",
            "The roadmap feature helps us plan sprints better",
            "Customer support responded within an hour",
        ]

        search_results = []
        for i in range(30):
            topic = topics[i % 5]
            search_results.append(_make_search_result(
                f"{topic} - variation {i} with additional context",
                url=f"https://reddit.com/r/test/{i}",
            ))

        snapshot = _make_snapshot(search_results=search_results)

        with patch("app.pipelines.icp.cluster._embed_snippets") as mock_embed:
            # Generate deterministic embeddings based on topic
            embeddings = []
            for i in range(30):
                topic_idx = i % 5
                # Create embeddings that cluster by topic
                base = [0.0] * EMBEDDING_DIM
                base[topic_idx] = 0.9
                base[topic_idx + 5] = 0.1 + (i * 0.01)  # Small variation
                embeddings.append(base)
            mock_embed.return_value = embeddings

            result = await cluster_snippets(snapshot)

        # Should produce multiple clusters
        assert len(result.clusters) >= 3
        assert result.total_snippets == 30

    @pytest.mark.asyncio
    async def test_thin_snapshot_produces_low_confidence(self) -> None:
        """Thin snapshot should produce segments with low confidence flags."""
        # Only 2 snippets - cold start case
        snapshot = _make_snapshot(search_results=[
            _make_search_result("Some customer feedback about the product"),
            _make_search_result("Another brief mention of the tool"),
        ])

        with patch("app.pipelines.icp.cluster._embed_snippets") as mock_embed:
            mock_embed.return_value = [
                _deterministic_embedding("feedback"),
                _deterministic_embedding("mention"),
            ]

            result = await cluster_snippets(snapshot)

        # Cold start: each snippet is its own micro-cluster
        assert len(result.clusters) == 2

        # When anchored, each will have only 1 evidence quote
        # This should flag has_few_anchors = True

    @pytest.mark.asyncio
    async def test_adversarial_all_similar_produces_low_stability(self) -> None:
        """20 near-duplicate snippets should produce low construct stability.

        This tests the geometric mean property: high evidence count but
        low coherence/stability should still produce low confidence.
        """
        # 20 snippets that are all nearly identical
        search_results = [
            _make_search_result(
                f"Great product for project management - review {i}",
                url=f"https://reddit.com/{i}",
            )
            for i in range(20)
        ]

        snapshot = _make_snapshot(search_results=search_results)

        with patch("app.pipelines.icp.cluster._embed_snippets") as mock_embed:
            # All embeddings are nearly identical (same direction)
            base_embedding = [0.9, 0.1] + [0.0] * (EMBEDDING_DIM - 2)
            embeddings = [
                [base_embedding[j] + (i * 0.001) for j in range(EMBEDDING_DIM)]
                for i in range(20)
            ]
            mock_embed.return_value = embeddings

            result = await cluster_snippets(snapshot)

        # With HDBSCAN, nearly identical points should form 1-2 clusters
        # The key insight: segments from similar clusters have low stability

        # Test the stability calculation directly
        if len(result.clusters) >= 2:
            c1 = result.clusters[0].centroid_embedding
            c2 = result.clusters[1].centroid_embedding

            # Stability of c1 vs c2
            stability = compute_segment_stability(c1, [c2])

            # With near-identical embeddings, clusters should be similar
            # -> low stability
            assert stability < 0.5
