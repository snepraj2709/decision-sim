"""Snapshot pipeline — Layer 1.

Job: Turn a URL into a structured Product Card with per-field confidence.

Pipeline stages (Step 2 will implement):
    1. Scrape: Playwright fetches homepage + pricing + features pages.
       Trafilatura extracts clean text from raw HTML.
    2. Search-ground: Tavily/Exa pulls recent reviews (G2, Capterra, Reddit),
       competitor mentions, recent press. Each result is captured with URL,
       date, and snippet for traceability.
    3. Extract: A DSPy program produces structured fields (category,
       value_prop, pricing, features, audience, competitors). Each field
       includes a confidence label and the count of independent sources
       that support it.
    4. Persist: Write a ProductSnapshot row. Source documents are kept in
       `raw_scrape` and `raw_search_results` JSON columns for replay /
       debugging.

Contract: this function is async, takes a URL, returns a ProductSnapshot ID.
The actual data is read back via the snapshot read API. Long-running work
(>5 sec) should be enqueued to RQ instead of awaited inline — Step 2
decides which pattern fits.
"""

from __future__ import annotations

import uuid

from sqlalchemy.ext.asyncio import AsyncSession


async def run_snapshot_pipeline(
    url: str,
    db: AsyncSession,
) -> uuid.UUID:
    """Run the snapshot pipeline for `url`. Return the ProductSnapshot ID.

    Args:
        url: A product homepage URL. Will be normalized (scheme, trailing slash)
            inside the pipeline. Must be 4–1024 chars.
        db: Async SQLAlchemy session — pipeline reads/writes through this.

    Returns:
        The ID of the newly-created ProductSnapshot row.

    Raises:
        NotImplementedError: Always, until Step 2.
        ScrapeError: (Step 2) When Playwright fails or content is empty.
        ExtractionError: (Step 2) When DSPy program produces no usable output.
    """
    raise NotImplementedError(
        "Snapshot pipeline is the Step 2 build target. "
        "See README phases table and apps/api/README.md for context."
    )
