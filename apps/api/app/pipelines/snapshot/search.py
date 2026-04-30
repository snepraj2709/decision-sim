"""Stage 2: Search-ground — gather external evidence via Tavily/Exa.

This stage:
  - Constructs 3 search queries from the scraped product info
  - Fetches top 5 results per query using Tavily (primary) or Exa (fallback)
  - Classifies each result's source_kind for UI rendering
  - Returns a list of SearchResult objects

Failure modes:
  - No search provider configured → log warning, return empty list
  - Provider rate-limited or 5xx → retry once with backoff, then continue
"""

from __future__ import annotations

import asyncio
import re
from dataclasses import dataclass
from typing import Literal
from urllib.parse import urlparse

import structlog

from app.config import get_settings
from app.pipelines.snapshot.scrape import ScrapeResult

log = structlog.get_logger()

# Source kind classification for UI icons
SourceKind = Literal["reddit", "g2", "capterra", "twitter", "press", "blog", "other"]

# Host patterns for source classification
SOURCE_PATTERNS: list[tuple[re.Pattern[str], SourceKind]] = [
    (re.compile(r"reddit\.com", re.IGNORECASE), "reddit"),
    (re.compile(r"g2\.com", re.IGNORECASE), "g2"),
    (re.compile(r"capterra\.com", re.IGNORECASE), "capterra"),
    (re.compile(r"(twitter|x)\.com", re.IGNORECASE), "twitter"),
    (re.compile(r"(techcrunch|wired|forbes|bloomberg|wsj|nytimes)\.com", re.IGNORECASE), "press"),
    (re.compile(r"(medium\.com|substack\.com|dev\.to|hashnode)", re.IGNORECASE), "blog"),
    (re.compile(r"news\.ycombinator\.com", re.IGNORECASE), "other"),  # HN is special
]

# Number of results per query
RESULTS_PER_QUERY = 5


@dataclass(frozen=True, slots=True)
class SearchResult:
    """A single search result."""

    query: str
    url: str
    title: str
    snippet: str
    published_date: str | None
    source_kind: SourceKind

    def to_dict(self) -> dict[str, object]:
        """Serialize for JSONB storage."""
        return {
            "query": self.query,
            "url": self.url,
            "title": self.title,
            "snippet": self.snippet,
            "published_date": self.published_date,
            "source_kind": self.source_kind,
        }


def classify_source_kind(url: str) -> SourceKind:
    """Classify a URL into a source kind for UI rendering."""
    parsed = urlparse(url)
    host = parsed.netloc.lower()

    for pattern, kind in SOURCE_PATTERNS:
        if pattern.search(host):
            return kind

    return "other"


def _build_queries(scrape_result: ScrapeResult) -> list[str]:
    """Build 3 search queries from scraped product info."""
    # Extract domain
    parsed = urlparse(scrape_result.url_canonical)
    domain = parsed.netloc.replace("www.", "")

    queries = [
        f'"{domain}" reviews',
        f'"{domain}" pricing site:reddit.com OR site:news.ycombinator.com',
        f'"{domain}" alternatives competitors',
    ]

    return queries


async def _search_tavily(query: str) -> list[SearchResult]:
    """Search using Tavily API."""
    settings = get_settings()
    if not settings.tavily_api_key:
        return []

    from tavily import TavilyClient  # type: ignore[import-untyped]

    def _do_search() -> list[SearchResult]:
        client = TavilyClient(api_key=settings.tavily_api_key)
        response = client.search(
            query=query,
            search_depth="basic",
            max_results=RESULTS_PER_QUERY,
            include_raw_content=False,
        )

        results: list[SearchResult] = []
        for item in response.get("results", []):
            results.append(
                SearchResult(
                    query=query,
                    url=item.get("url", ""),
                    title=item.get("title", ""),
                    snippet=item.get("content", ""),
                    published_date=item.get("published_date"),
                    source_kind=classify_source_kind(item.get("url", "")),
                )
            )
        return results

    return await asyncio.to_thread(_do_search)


async def _search_exa(query: str) -> list[SearchResult]:
    """Search using Exa API (fallback)."""
    settings = get_settings()
    if not settings.exa_api_key:
        return []

    from exa_py import Exa

    def _do_search() -> list[SearchResult]:
        client = Exa(api_key=settings.exa_api_key)
        response = client.search_and_contents(
            query=query,
            num_results=RESULTS_PER_QUERY,
            text={"max_characters": 500},
            use_autoprompt=True,
        )

        results: list[SearchResult] = []
        for item in response.results:
            pub_date = None
            if hasattr(item, "published_date") and item.published_date:
                pub_date = str(item.published_date)

            results.append(
                SearchResult(
                    query=query,
                    url=item.url,
                    title=item.title or "",
                    snippet=item.text or "",
                    published_date=pub_date,
                    source_kind=classify_source_kind(item.url),
                )
            )
        return results

    return await asyncio.to_thread(_do_search)


async def _search_with_retry(
    query: str,
    search_fn: object,  # Callable, but mypy doesn't like the signature
    provider_name: str,
) -> list[SearchResult]:
    """Execute search with one retry on failure."""
    for attempt in range(2):
        try:
            if provider_name == "tavily":
                return await _search_tavily(query)
            else:
                return await _search_exa(query)
        except Exception as e:
            log.warning(
                "search.provider.error",
                provider=provider_name,
                query=query,
                attempt=attempt + 1,
                error=str(e),
            )
            if attempt == 0:
                # Exponential backoff before retry
                await asyncio.sleep(2)
            else:
                # Second attempt failed, return empty
                return []
    return []


async def run_search(scrape_result: ScrapeResult) -> list[SearchResult]:
    """Run the search stage for a scraped product.

    Args:
        scrape_result: Result from the scrape stage.

    Returns:
        List of SearchResult objects from external sources.
    """
    settings = get_settings()

    # Check which provider is available
    use_tavily = bool(settings.tavily_api_key)
    use_exa = bool(settings.exa_api_key)

    if not use_tavily and not use_exa:
        log.warning(
            "search.no_provider_configured",
            message="No search provider API key configured. Returning empty results.",
        )
        return []

    provider_name = "tavily" if use_tavily else "exa"
    log.info("search.using_provider", provider=provider_name)

    # Build queries
    queries = _build_queries(scrape_result)
    log.info("search.queries", queries=queries)

    # Execute searches in parallel
    all_results: list[SearchResult] = []

    tasks = [
        _search_with_retry(query, None, provider_name)
        for query in queries
    ]
    results_lists = await asyncio.gather(*tasks)

    for results in results_lists:
        all_results.extend(results)

    # Deduplicate by URL (keep first occurrence)
    seen_urls: set[str] = set()
    unique_results: list[SearchResult] = []
    for result in all_results:
        if result.url not in seen_urls:
            seen_urls.add(result.url)
            unique_results.append(result)

    log.info(
        "search.complete",
        total_results=len(unique_results),
        provider=provider_name,
    )

    return unique_results
