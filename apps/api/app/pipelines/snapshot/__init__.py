"""Snapshot pipeline — Layer 1.

Job: Turn a URL into a structured Product Card with per-field confidence.

Pipeline stages:
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
(>5 sec) should be enqueued to RQ instead of awaited inline.
"""

from __future__ import annotations

import uuid

import structlog
from sqlalchemy.ext.asyncio import AsyncSession

from app.pipelines.demo_cache import get_or_create_cached_snapshot_id
from app.pipelines.snapshot.extract import run_extraction
from app.pipelines.snapshot.score import score_and_persist
from app.pipelines.snapshot.scrape import ScrapeError, run_scrape
from app.pipelines.snapshot.search import run_search

log = structlog.get_logger()

__all__ = ["ScrapeError", "run_snapshot_pipeline"]


async def run_snapshot_pipeline(
    url: str,
    db: AsyncSession,
) -> uuid.UUID:
    """Run the snapshot pipeline for `url`. Return the ProductSnapshot ID.

    Args:
        url: A product homepage URL. Will be normalized (scheme, trailing slash)
            inside the pipeline. Must be 4-1024 chars.
        db: Async SQLAlchemy session - pipeline reads/writes through this.

    Returns:
        The ID of the newly-created ProductSnapshot row.

    Raises:
        ScrapeError: When Playwright fails or content is empty.
        ExtractionError: When DSPy program produces no usable output.
    """
    log.info("snapshot.pipeline.start", url=url)

    cached_snapshot_id = await get_or_create_cached_snapshot_id(url, db)
    if cached_snapshot_id is not None:
        log.info(
            "snapshot.pipeline.cache_return",
            url=url,
            snapshot_id=str(cached_snapshot_id),
        )
        return cached_snapshot_id

    # Stage 1: Scrape
    log.info("snapshot.stage.scrape.start", url=url)
    scrape_result = await run_scrape(url)
    log.info(
        "snapshot.stage.scrape.done",
        url=scrape_result.url_canonical,
        pages=len(scrape_result.pages),
        errors=len(scrape_result.errors),
    )

    # Stage 2: Search
    log.info("snapshot.stage.search.start", url=scrape_result.url_canonical)
    search_results = await run_search(scrape_result)
    log.info("snapshot.stage.search.done", results=len(search_results))

    # Stage 3: Extract
    log.info("snapshot.stage.extract.start")
    extraction = await run_extraction(scrape_result, search_results)
    log.info("snapshot.stage.extract.done")

    # Stage 4: Score & Persist
    log.info("snapshot.stage.persist.start")
    snapshot_id = await score_and_persist(
        scrape_result=scrape_result,
        search_results=search_results,
        extraction=extraction,
        db=db,
    )
    log.info("snapshot.pipeline.done", snapshot_id=str(snapshot_id))

    return snapshot_id
