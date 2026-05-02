"""Stage 1: Scrape — fetch pages with Playwright, extract text with trafilatura.

This stage:
  - Normalizes the URL (scheme, trailing slash, lowercase host)
  - Fetches the homepage with Playwright (handles JS-rendered pages)
  - Discovers links to pricing, features, about, product, plans pages
  - Fetches discovered pages (cap at 5 total including homepage)
  - Extracts clean text using trafilatura
  - Returns a structured ScrapeResult

Failure modes:
  - Homepage fetch fails → raise ScrapeError, pipeline aborts
  - Subpage fetch fails → log, append to errors, continue
  - Page is JS-app shell with no content → clean_text is empty string
  - Total scrape time exceeds 60s → cancel remaining fetches, continue with what we have
"""

from __future__ import annotations

import asyncio
import re
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any, Literal
from urllib.parse import urljoin, urlparse

import structlog
import trafilatura
from playwright.async_api import TimeoutError as PlaywrightTimeoutError
from playwright.async_api import async_playwright

log = structlog.get_logger()

# Page kind classification
PageKind = Literal["homepage", "pricing", "features", "about", "product", "plans", "other"]

# Patterns for link discovery
LINK_PATTERNS: dict[PageKind, list[re.Pattern[str]]] = {
    "pricing": [
        re.compile(r"\bpricing\b", re.IGNORECASE),
        re.compile(r"\bplans?\b", re.IGNORECASE),
        re.compile(r"\bcost\b", re.IGNORECASE),
    ],
    "features": [
        re.compile(r"\bfeatures?\b", re.IGNORECASE),
        re.compile(r"\bcapabilities\b", re.IGNORECASE),
        re.compile(r"\bwhat we (do|offer)\b", re.IGNORECASE),
    ],
    "about": [
        re.compile(r"\babout\b", re.IGNORECASE),
        re.compile(r"\bcompany\b", re.IGNORECASE),
        re.compile(r"\bteam\b", re.IGNORECASE),
        re.compile(r"\bstory\b", re.IGNORECASE),
    ],
    "product": [
        re.compile(r"\bproduct\b", re.IGNORECASE),
        re.compile(r"\bsolution\b", re.IGNORECASE),
        re.compile(r"\bplatform\b", re.IGNORECASE),
    ],
    "plans": [
        re.compile(r"\bplans?\b", re.IGNORECASE),
        re.compile(r"\bsubscription\b", re.IGNORECASE),
    ],
}

# Max pages to fetch (including homepage)
MAX_PAGES = 5

# Total scrape timeout in seconds
SCRAPE_TIMEOUT = 60

# Per-page timeout in seconds
PAGE_TIMEOUT = 15000  # milliseconds for Playwright

# Some modern marketing sites keep analytics or personalization requests open
# indefinitely. Waiting for `networkidle` as the primary load condition turns
# those long-lived requests into false scrape failures.
NETWORK_IDLE_TIMEOUT = 5000
POST_LOAD_SETTLE_MS = 1000


class ScrapeError(Exception):
    """Raised when scraping fails critically (e.g., homepage unreachable)."""

    pass


@dataclass(frozen=True, slots=True)
class ScrapedPage:
    """A single scraped page."""

    url: str
    kind: PageKind
    raw_html: str
    clean_text: str
    fetched_at: datetime


@dataclass(slots=True)
class ScrapeResult:
    """Result of scraping a product's website."""

    url_canonical: str
    pages: list[ScrapedPage] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, object]:
        """Serialize for JSONB storage."""
        return {
            "url_canonical": self.url_canonical,
            "pages": [
                {
                    "url": p.url,
                    "kind": p.kind,
                    "raw_html": p.raw_html[:50000],  # Truncate for storage
                    "clean_text": p.clean_text,
                    "fetched_at": p.fetched_at.isoformat(),
                }
                for p in self.pages
            ],
            "errors": self.errors,
        }


def normalize_url(url: str) -> str:
    """Normalize a URL: ensure https, lowercase host, remove trailing slash."""
    # Parse the URL
    parsed = urlparse(url)

    # Ensure scheme
    if not parsed.scheme:
        url = f"https://{url}"
        parsed = urlparse(url)
    elif parsed.scheme == "http":
        url = url.replace("http://", "https://", 1)
        parsed = urlparse(url)

    # Lowercase host
    host = parsed.netloc.lower()

    # Remove trailing slash from path (unless it's just "/")
    path = parsed.path.rstrip("/") if parsed.path != "/" else ""

    # Reconstruct
    return f"https://{host}{path}"


def _classify_link(href: str, text: str) -> PageKind | None:
    """Classify a link based on href and anchor text. Returns None if no match."""
    combined = f"{href} {text}"
    for kind, patterns in LINK_PATTERNS.items():
        for pattern in patterns:
            if pattern.search(combined):
                return kind
    return None


def _extract_links(html: str, base_url: str) -> dict[PageKind, str]:
    """Extract links from HTML, classified by page kind. Returns best URL per kind."""
    from html.parser import HTMLParser

    links: dict[PageKind, list[tuple[str, str]]] = {
        "pricing": [],
        "features": [],
        "about": [],
        "product": [],
        "plans": [],
    }

    class LinkExtractor(HTMLParser):
        def __init__(self) -> None:
            super().__init__()
            self.current_href: str | None = None
            self.current_text: list[str] = []
            self.in_a = False

        def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
            if tag == "a":
                self.in_a = True
                self.current_text = []
                for name, value in attrs:
                    if name == "href" and value:
                        self.current_href = value

        def handle_data(self, data: str) -> None:
            if self.in_a:
                self.current_text.append(data)

        def handle_endtag(self, tag: str) -> None:
            if tag == "a" and self.in_a:
                self.in_a = False
                if self.current_href:
                    text = " ".join(self.current_text).strip()
                    kind = _classify_link(self.current_href, text)
                    if kind:
                        # Make absolute URL
                        abs_url = urljoin(base_url, self.current_href)
                        # Only keep same-domain links
                        base_host = urlparse(base_url).netloc.lower()
                        link_host = urlparse(abs_url).netloc.lower()
                        if link_host == base_host:
                            links[kind].append((abs_url, text))
                self.current_href = None
                self.current_text = []

    try:
        parser = LinkExtractor()
        parser.feed(html)
    except Exception as e:
        log.warning("scrape.link_extraction_failed", error=str(e))

    # Return best URL per kind (first match, prefer shorter URLs)
    result: dict[PageKind, str] = {}
    for kind, url_list in links.items():
        if url_list:
            # Sort by URL length (prefer shorter, cleaner URLs)
            sorted_urls = sorted(url_list, key=lambda x: len(x[0]))
            result[kind] = sorted_urls[0][0]

    return result


async def _navigate_to_usable_dom(page: Any, url: str, timeout_ms: int) -> None:
    """Navigate to a page and proceed once the DOM is usable."""
    try:
        await page.goto(url, wait_until="domcontentloaded", timeout=timeout_ms)
    except PlaywrightTimeoutError:
        log.warning("scrape.domcontentloaded.timeout", url=url, timeout_ms=timeout_ms)

    try:
        await page.wait_for_load_state(
            "networkidle",
            timeout=min(NETWORK_IDLE_TIMEOUT, timeout_ms),
        )
    except PlaywrightTimeoutError:
        log.debug("scrape.networkidle.timeout", url=url)


async def _fetch_page(url: str, timeout_ms: int = PAGE_TIMEOUT) -> tuple[str, str]:
    """Fetch a page using Playwright. Returns (html, clean_text)."""
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        try:
            context = await browser.new_context(
                user_agent=(
                    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/120.0.0.0 Safari/537.36"
                ),
                viewport={"width": 1280, "height": 720},
            )
            page = await context.new_page()

            await _navigate_to_usable_dom(page, url, timeout_ms)

            # Wait a bit for any late JS
            await page.wait_for_timeout(POST_LOAD_SETTLE_MS)

            # Get HTML
            html = await page.content()

            # Extract text using trafilatura
            clean_text = trafilatura.extract(
                html,
                include_links=False,
                include_images=False,
                include_tables=True,
                favor_recall=True,
            ) or ""

            return html, clean_text
        finally:
            await browser.close()


async def run_scrape(url: str) -> ScrapeResult:
    """Run the scrape stage for a URL.

    Args:
        url: Product homepage URL to scrape.

    Returns:
        ScrapeResult with scraped pages and any errors.

    Raises:
        ScrapeError: If homepage fetch fails.
    """
    canonical_url = normalize_url(url)
    result = ScrapeResult(url_canonical=canonical_url)

    log.info("scrape.homepage.start", url=canonical_url)

    # Start the timeout
    start_time = asyncio.get_event_loop().time()

    # Fetch homepage first — this is critical
    try:
        html, clean_text = await asyncio.wait_for(
            _fetch_page(canonical_url),
            timeout=PAGE_TIMEOUT / 1000 + 5,  # Add buffer for thread overhead
        )
        homepage = ScrapedPage(
            url=canonical_url,
            kind="homepage",
            raw_html=html,
            clean_text=clean_text,
            fetched_at=datetime.now(UTC),
        )
        result.pages.append(homepage)
        log.info("scrape.homepage.done", url=canonical_url, text_len=len(clean_text))
    except Exception as e:
        log.error("scrape.homepage.failed", url=canonical_url, error=str(e))
        raise ScrapeError(f"Failed to fetch homepage {canonical_url}: {e}") from e

    # Discover links from homepage
    discovered = _extract_links(html, canonical_url)
    log.info("scrape.links.discovered", count=len(discovered), kinds=list(discovered.keys()))

    # Fetch discovered pages (up to MAX_PAGES - 1, since we have homepage)
    # Priority: pricing > features > about > product > plans
    priority_order: list[PageKind] = ["pricing", "features", "about", "product", "plans"]

    for kind in priority_order:
        if kind not in discovered:
            continue

        # Check if we've hit the page limit
        if len(result.pages) >= MAX_PAGES:
            log.info("scrape.max_pages_reached", pages=len(result.pages))
            break

        # Check if we've exceeded total timeout
        elapsed = asyncio.get_event_loop().time() - start_time
        if elapsed >= SCRAPE_TIMEOUT:
            log.warning("scrape.timeout_reached", elapsed=elapsed)
            result.errors.append(f"Scrape timeout ({SCRAPE_TIMEOUT}s) reached")
            break

        page_url = discovered[kind]
        log.info("scrape.subpage.start", url=page_url, kind=kind)

        try:
            remaining_time = SCRAPE_TIMEOUT - elapsed
            html, clean_text = await asyncio.wait_for(
                _fetch_page(page_url),
                timeout=min(PAGE_TIMEOUT / 1000 + 5, remaining_time),
            )
            page = ScrapedPage(
                url=page_url,
                kind=kind,
                raw_html=html,
                clean_text=clean_text,
                fetched_at=datetime.now(UTC),
            )
            result.pages.append(page)
            log.info("scrape.subpage.done", url=page_url, kind=kind, text_len=len(clean_text))
        except Exception as e:
            error_msg = f"Failed to fetch {kind} page {page_url}: {e}"
            log.warning("scrape.subpage.failed", url=page_url, kind=kind, error=str(e))
            result.errors.append(error_msg)
            # Continue with other pages — don't abort for subpage failures

    log.info(
        "scrape.complete",
        url=canonical_url,
        pages=len(result.pages),
        errors=len(result.errors),
    )
    return result
