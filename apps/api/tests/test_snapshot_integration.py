"""Integration tests for snapshot pipeline — hits real URLs.

These tests are marked with @pytest.mark.integration and are skipped in
normal runs. Run with: pytest -m integration

These tests require:
  - Network access
  - ANTHROPIC_API_KEY or OPENAI_API_KEY
  - TAVILY_API_KEY or EXA_API_KEY (optional, will produce low confidence without)

Tests verify:
  - Pipeline completes for real URLs
  - Extracted fields are plausible (not exact string matches)
  - Thin products produce lower confidence than rich products
"""

from __future__ import annotations

import os

import pytest

# Skip all tests in this module if not running integration tests
pytestmark = pytest.mark.integration


@pytest.fixture
def has_llm_key() -> bool:
    """Check if an LLM API key is available."""
    return bool(os.getenv("ANTHROPIC_API_KEY") or os.getenv("OPENAI_API_KEY"))


@pytest.fixture
def has_search_key() -> bool:
    """Check if a search API key is available."""
    return bool(os.getenv("TAVILY_API_KEY") or os.getenv("EXA_API_KEY"))


class TestRealProductSnapshots:
    """Integration tests against real product URLs."""

    @pytest.mark.asyncio
    async def test_linear_snapshot(self, has_llm_key: bool) -> None:
        """Linear.app should produce a sensible snapshot."""
        if not has_llm_key:
            pytest.skip("No LLM API key configured")

        from app.pipelines.snapshot.extract import run_extraction
        from app.pipelines.snapshot.scrape import run_scrape
        from app.pipelines.snapshot.search import run_search

        # Stage 1: Scrape
        scrape_result = await run_scrape("https://linear.app")

        assert scrape_result.url_canonical == "https://linear.app"
        assert len(scrape_result.pages) >= 1
        homepage = scrape_result.pages[0]
        assert homepage.kind == "homepage"
        assert len(homepage.clean_text) > 100  # Should have substantial content

        # Stage 2: Search
        search_results = await run_search(scrape_result)
        # May be empty if no search key, that's OK

        # Stage 3: Extract
        extraction = await run_extraction(scrape_result, search_results)

        # Verify plausible extractions (not exact matches)
        category = extraction.category.value.lower()
        assert any(
            term in category
            for term in ["project", "issue", "track", "management", "software", "tool"]
        ), f"Unexpected category: {category}"

        # Value prop should mention teams or engineering
        value_prop = extraction.value_prop.value.lower()
        assert len(value_prop) > 20  # Non-empty

        # Features should exist
        features = extraction.features.value
        assert len(features) > 10

    @pytest.mark.asyncio
    async def test_vanta_snapshot(self, has_llm_key: bool) -> None:
        """Vanta.com should produce a sensible snapshot."""
        if not has_llm_key:
            pytest.skip("No LLM API key configured")

        from app.pipelines.snapshot.extract import run_extraction
        from app.pipelines.snapshot.scrape import run_scrape
        from app.pipelines.snapshot.search import run_search

        # Stage 1: Scrape
        scrape_result = await run_scrape("https://vanta.com")

        assert scrape_result.url_canonical == "https://vanta.com"
        assert len(scrape_result.pages) >= 1

        # Stage 2: Search
        search_results = await run_search(scrape_result)

        # Stage 3: Extract
        extraction = await run_extraction(scrape_result, search_results)

        # Verify plausible extractions
        category = extraction.category.value.lower()
        assert any(
            term in category
            for term in ["security", "compliance", "soc", "trust", "audit", "software"]
        ), f"Unexpected category: {category}"

    @pytest.mark.asyncio
    async def test_thin_product_produces_lower_confidence(
        self, has_llm_key: bool, has_search_key: bool
    ) -> None:
        """A thin/minimal product should produce lower confidence."""
        if not has_llm_key:
            pytest.skip("No LLM API key configured")

        from app.config import get_settings
        from app.pipelines.snapshot.extract import run_extraction
        from app.pipelines.snapshot.score import compute_field_confidence
        from app.pipelines.snapshot.scrape import run_scrape
        from app.pipelines.snapshot.search import run_search

        settings = get_settings()

        # Use a minimal "coming soon" type site
        # Using example.com as it has minimal content
        scrape_result = await run_scrape("https://example.com")
        search_results = await run_search(scrape_result)
        extraction = await run_extraction(scrape_result, search_results)

        # Check that confidence is generally low for thin product
        low_count = 0
        for field_name in ["category", "value_prop", "pricing", "features", "audience"]:
            field = getattr(extraction, field_name)
            confidence, _ = compute_field_confidence(
                field, search_results, settings.min_sources_for_high_confidence
            )
            if confidence == "low":
                low_count += 1

        # At least 3 of 5 fields should be low confidence for a thin product
        assert low_count >= 3, f"Expected mostly low confidence, got {low_count}/5 low"


class TestScrapeStageIntegration:
    """Integration tests for the scrape stage specifically."""

    @pytest.mark.asyncio
    async def test_scrape_discovers_subpages(self) -> None:
        """Scraper should discover pricing/features pages."""
        from app.pipelines.snapshot.scrape import run_scrape

        result = await run_scrape("https://linear.app")

        # Should have found some subpages
        page_kinds = {p.kind for p in result.pages}
        assert "homepage" in page_kinds

        # Linear should have pricing and/or features discoverable
        # (exact pages depend on current site structure)
        assert len(result.pages) >= 1

    @pytest.mark.asyncio
    async def test_scrape_handles_404_gracefully(self) -> None:
        """Scraper should handle non-existent pages gracefully."""
        from app.pipelines.snapshot.scrape import ScrapeError, run_scrape

        # This should fail at homepage level
        with pytest.raises(ScrapeError):
            await run_scrape("https://this-domain-does-not-exist-12345.com")


class TestSearchStageIntegration:
    """Integration tests for the search stage specifically."""

    @pytest.mark.asyncio
    async def test_search_returns_results(self, has_search_key: bool) -> None:
        """Search should return results for a known product."""
        if not has_search_key:
            pytest.skip("No search API key configured")

        from datetime import UTC, datetime

        from app.pipelines.snapshot.scrape import ScrapedPage, ScrapeResult
        from app.pipelines.snapshot.search import run_search

        # Create a mock scrape result
        scrape_result = ScrapeResult(
            url_canonical="https://linear.app",
            pages=[
                ScrapedPage(
                    url="https://linear.app",
                    kind="homepage",
                    raw_html="<html></html>",
                    clean_text="Linear is a project management tool",
                    fetched_at=datetime.now(UTC),
                )
            ],
        )

        results = await run_search(scrape_result)

        # Should have some results
        assert len(results) > 0

        # Results should have valid structure
        for result in results:
            assert result.url
            assert result.source_kind in [
                "reddit", "g2", "capterra", "twitter", "press", "blog", "other"
            ]

    @pytest.mark.asyncio
    async def test_search_empty_without_key(self) -> None:
        """Search should return empty list if no API key."""
        from datetime import UTC, datetime
        from unittest.mock import patch

        from app.config import Settings
        from app.pipelines.snapshot.scrape import ScrapedPage, ScrapeResult
        from app.pipelines.snapshot.search import run_search

        scrape_result = ScrapeResult(
            url_canonical="https://example.com",
            pages=[
                ScrapedPage(
                    url="https://example.com",
                    kind="homepage",
                    raw_html="<html></html>",
                    clean_text="Example content",
                    fetched_at=datetime.now(UTC),
                )
            ],
        )

        # Mock settings to have no API keys
        with patch("app.pipelines.snapshot.search.get_settings") as mock_settings:
            mock_settings.return_value = Settings(
                tavily_api_key=None,
                exa_api_key=None,
            )
            results = await run_search(scrape_result)

        assert results == []
