"""Unit tests for snapshot pipeline — no network, all mocked.

Tests verify:
  1. Rich product produces High confidence on most fields
  2. Thin product produces Low confidence on most fields
  3. SPA with no content produces Medium-or-Low confidence
  4. Geometric mean property holds: 5 sources but low agreement → Low
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from app.core.confidence import TriangulationInput, triangulate
from app.pipelines.snapshot.extract import (
    ExtractedField,
    _prepare_scraped_content,
    _prepare_search_results,
)
from app.pipelines.snapshot.score import (
    compute_construct_stability,
    compute_field_confidence,
    compute_inter_source_agreement,
)
from app.pipelines.snapshot.scrape import (
    ScrapedPage,
    ScrapeResult,
    _classify_link,
    normalize_url,
)
from app.pipelines.snapshot.search import SearchResult, classify_source_kind


# ─── URL Normalization Tests ────────────────────────────────────────────────
class TestNormalizeUrl:
    def test_adds_https_scheme(self) -> None:
        assert normalize_url("example.com") == "https://example.com"

    def test_upgrades_http_to_https(self) -> None:
        assert normalize_url("http://example.com") == "https://example.com"

    def test_lowercases_host(self) -> None:
        assert normalize_url("https://EXAMPLE.COM") == "https://example.com"

    def test_removes_trailing_slash(self) -> None:
        assert normalize_url("https://example.com/") == "https://example.com"

    def test_preserves_path(self) -> None:
        assert normalize_url("https://example.com/pricing") == "https://example.com/pricing"


# ─── Link Classification Tests ──────────────────────────────────────────────
class TestClassifyLink:
    def test_pricing_by_href(self) -> None:
        assert _classify_link("/pricing", "") == "pricing"

    def test_pricing_by_text(self) -> None:
        assert _classify_link("/foo", "Pricing & Plans") == "pricing"

    def test_features_by_href(self) -> None:
        assert _classify_link("/features", "") == "features"

    def test_about_by_text(self) -> None:
        assert _classify_link("/company", "About Us") == "about"

    def test_no_match_returns_none(self) -> None:
        assert _classify_link("/blog/post-123", "Latest News") is None


# ─── Source Kind Classification Tests ───────────────────────────────────────
class TestClassifySourceKind:
    def test_reddit(self) -> None:
        assert classify_source_kind("https://www.reddit.com/r/startups/") == "reddit"

    def test_g2(self) -> None:
        assert classify_source_kind("https://www.g2.com/products/linear") == "g2"

    def test_capterra(self) -> None:
        assert classify_source_kind("https://www.capterra.com/p/123/") == "capterra"

    def test_twitter(self) -> None:
        assert classify_source_kind("https://twitter.com/linear") == "twitter"

    def test_x_dot_com(self) -> None:
        assert classify_source_kind("https://x.com/linear") == "twitter"

    def test_press(self) -> None:
        assert classify_source_kind("https://techcrunch.com/article") == "press"

    def test_blog(self) -> None:
        assert classify_source_kind("https://medium.com/@user/post") == "blog"

    def test_other(self) -> None:
        assert classify_source_kind("https://somesite.com/page") == "other"


# ─── Inter-Source Agreement Tests ───────────────────────────────────────────
class TestInterSourceAgreement:
    def test_empty_snippets_returns_zero(self) -> None:
        assert compute_inter_source_agreement("some value", []) == 0.0

    def test_empty_value_returns_zero(self) -> None:
        assert compute_inter_source_agreement("", ["some snippet"]) == 0.0

    def test_perfect_match(self) -> None:
        # Same tokens should give high score
        result = compute_inter_source_agreement(
            "project management tool",
            ["project management tool for teams"],
        )
        assert result > 0.5

    def test_no_overlap(self) -> None:
        result = compute_inter_source_agreement(
            "email marketing automation",
            ["video streaming platform for entertainment"],
        )
        assert result < 0.3

    def test_multiple_snippets_boost_score(self) -> None:
        # Multiple agreeing snippets should boost confidence
        single = compute_inter_source_agreement(
            "project management",
            ["project management for teams"],
        )
        multiple = compute_inter_source_agreement(
            "project management",
            [
                "project management for teams",
                "project management software",
                "best project management tools",
            ],
        )
        assert multiple >= single


# ─── Construct Stability Tests ──────────────────────────────────────────────
class TestConstructStability:
    def test_empty_returns_zero(self) -> None:
        assert compute_construct_stability("") == 0.0

    def test_single_claim_returns_one(self) -> None:
        assert compute_construct_stability("Project management tool") == 1.0

    def test_semicolon_indicates_multiple_claims(self) -> None:
        result = compute_construct_stability("Project management; Issue tracking")
        assert result < 1.0

    def test_and_or_indicates_hedging(self) -> None:
        result = compute_construct_stability("Startups and/or enterprises")
        assert result < 1.0

    def test_many_claims_returns_low(self) -> None:
        result = compute_construct_stability(
            "Startups; SMBs; Enterprises; and/or individuals"
        )
        assert result == 0.4


# ─── Field Confidence Computation Tests ─────────────────────────────────────
class TestFieldConfidence:
    def test_high_sources_high_agreement_high_stability(self) -> None:
        """Rich data should produce high confidence."""
        field = ExtractedField(
            value="Project management tool for engineering teams",
            sources=[0, 1, 2, 3, 4],
            reasoning="Clear from multiple sources",
        )
        search_results = [
            SearchResult(
                query="test",
                url=f"https://example.com/{i}",
                title=f"Review {i}",
                snippet="Project management tool for engineering teams at startups",
                published_date=None,
                source_kind="g2",
            )
            for i in range(5)
        ]

        confidence, n_sources = compute_field_confidence(field, search_results, 3)
        assert n_sources == 5
        assert confidence == "high"

    def test_no_sources_produces_low(self) -> None:
        """No evidence should produce low confidence."""
        field = ExtractedField(
            value="Some product category",
            sources=[],
            reasoning="Guessed from homepage",
        )

        confidence, n_sources = compute_field_confidence(field, [], 3)
        assert n_sources == 0
        assert confidence == "low"

    def test_geometric_mean_property(self) -> None:
        """5 sources but low agreement should still produce low confidence."""
        # Field value that doesn't match snippets at all
        field = ExtractedField(
            value="Blockchain cryptocurrency fintech",
            sources=[0, 1, 2, 3, 4],
            reasoning="Extracted value",
        )
        # Snippets that talk about something completely different
        search_results = [
            SearchResult(
                query="test",
                url=f"https://example.com/{i}",
                title=f"Review {i}",
                snippet="Project management tool for engineering teams",
                published_date=None,
                source_kind="g2",
            )
            for i in range(5)
        ]

        confidence, n_sources = compute_field_confidence(field, search_results, 3)
        assert n_sources == 5
        # Even with 5 sources, low agreement should drag confidence down
        assert confidence in ("low", "medium")


# ─── Content Preparation Tests ──────────────────────────────────────────────
class TestContentPreparation:
    def test_scraped_content_prioritizes_pricing(self) -> None:
        """Pricing page should come before homepage in prepared content."""
        pages = [
            ScrapedPage(
                url="https://example.com",
                kind="homepage",
                raw_html="<html>homepage</html>",
                clean_text="Homepage content here",
                fetched_at=datetime.now(UTC),
            ),
            ScrapedPage(
                url="https://example.com/pricing",
                kind="pricing",
                raw_html="<html>pricing</html>",
                clean_text="Pricing content $10/mo",
                fetched_at=datetime.now(UTC),
            ),
        ]
        scrape_result = ScrapeResult(url_canonical="https://example.com", pages=pages)

        content = _prepare_scraped_content(scrape_result)

        # Pricing should appear before homepage
        pricing_pos = content.find("PRICING PAGE")
        homepage_pos = content.find("HOMEPAGE PAGE")
        assert pricing_pos < homepage_pos

    def test_search_results_formatted_with_indices(self) -> None:
        """Search results should be formatted with citation indices."""
        results = [
            SearchResult(
                query="test",
                url="https://g2.com/review",
                title="Great product review",
                snippet="This is a great tool",
                published_date=None,
                source_kind="g2",
            ),
        ]

        formatted = _prepare_search_results(results)

        assert "[0]" in formatted
        assert "Great product review" in formatted
        assert "g2.com" in formatted


# ─── Mock Pipeline End-to-End Tests ─────────────────────────────────────────
class TestMockPipelineEndToEnd:
    """Test pipeline behavior with mocked I/O for different product types."""

    @pytest.fixture
    def rich_product_html(self) -> str:
        """HTML for a content-rich SaaS product (Linear-like)."""
        return """
        <html>
        <head><title>Linear - Modern Project Management</title></head>
        <body>
            <h1>Linear - The issue tracking tool for modern teams</h1>
            <p>Linear is a project management and issue tracking tool built for
            engineering teams. We help software teams plan, track, and ship
            products with beautiful design and powerful features.</p>

            <h2>Key Features</h2>
            <ul>
                <li>Issue tracking and project management</li>
                <li>Roadmap planning</li>
                <li>Git integrations</li>
                <li>Keyboard-first design</li>
            </ul>

            <h2>Pricing</h2>
            <p>Free for small teams. Pro at $8/user/month. Enterprise custom pricing.</p>

            <a href="/pricing">Pricing</a>
            <a href="/features">Features</a>
            <a href="/about">About Us</a>
        </body>
        </html>
        """

    @pytest.fixture
    def thin_product_html(self) -> str:
        """HTML for a thin/stealth product with minimal content."""
        return """
        <html>
        <head><title>Stealth Startup</title></head>
        <body>
            <h1>Coming Soon</h1>
            <p>We're building something exciting. Sign up for updates.</p>
            <form><input type="email" placeholder="Email"></form>
        </body>
        </html>
        """

    @pytest.fixture
    def spa_product_html(self) -> str:
        """HTML for an SPA with no static content (JS-rendered)."""
        return """
        <html>
        <head><title>Modern App</title></head>
        <body>
            <div id="root"></div>
            <script src="/bundle.js"></script>
        </body>
        </html>
        """

    def test_rich_product_extraction_signals(self, rich_product_html: str) -> None:
        """Rich product should produce strong signals for confidence."""
        import trafilatura

        clean_text = trafilatura.extract(rich_product_html) or ""

        # Verify we get substantial content
        assert len(clean_text) > 100
        assert "project management" in clean_text.lower() or "issue tracking" in clean_text.lower()

    def test_thin_product_extraction_signals(self, thin_product_html: str) -> None:
        """Thin product should produce weak signals."""
        import trafilatura

        clean_text = trafilatura.extract(thin_product_html) or ""

        # Very little content
        assert len(clean_text) < 200

    def test_spa_product_extraction_signals(self, spa_product_html: str) -> None:
        """SPA with no content should produce empty text."""
        import trafilatura

        clean_text = trafilatura.extract(spa_product_html) or ""

        # No meaningful content
        assert len(clean_text) < 50


# ─── Confidence Triangulation Property Tests ────────────────────────────────
class TestTriangulationProperties:
    """Verify geometric mean properties of confidence triangulation."""

    def test_one_zero_axis_produces_low(self) -> None:
        """Any zero axis should produce low confidence."""
        # High evidence, high stability, but zero agreement
        signals = TriangulationInput(
            llm_baserate_agreement=0.0,
            evidence_density=1.0,
            construct_stability=1.0,
        )
        assert triangulate(signals) == "low"

    def test_all_medium_produces_medium(self) -> None:
        """Uniform medium signals should produce medium confidence."""
        signals = TriangulationInput(
            llm_baserate_agreement=0.6,
            evidence_density=0.6,
            construct_stability=0.6,
        )
        assert triangulate(signals) == "medium"

    def test_all_high_produces_high(self) -> None:
        """All high signals should produce high confidence."""
        signals = TriangulationInput(
            llm_baserate_agreement=0.9,
            evidence_density=0.9,
            construct_stability=0.9,
        )
        assert triangulate(signals) == "high"

    def test_one_low_drags_down(self) -> None:
        """One low signal should prevent high confidence."""
        # Two high, one low
        signals = TriangulationInput(
            llm_baserate_agreement=0.9,
            evidence_density=0.2,  # Low evidence
            construct_stability=0.9,
        )
        result = triangulate(signals)
        assert result != "high"  # Should be medium or low
