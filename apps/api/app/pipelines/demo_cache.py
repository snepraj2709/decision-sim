"""Development-only deterministic cache for known demo products.

The live pipeline burns paid scrape/search/LLM calls. Local verification often
needs a stable product that exercises the UI without re-running those services.
This module provides that path for configured demo hosts, currently Netflix.
Explicit frontend URLs for other hosts still use the normal live pipeline.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import cast
from urllib.parse import urlparse

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.models import (
    EMBEDDING_DIM,
    Evidence,
    Product,
    ProductSnapshot,
    Segment,
    Simulation,
    SimulationCell,
)

log = structlog.get_logger()

NETFLIX_HOST = "netflix.com"
NETFLIX_CANONICAL_URL = "https://www.netflix.com"


def _normalized_cache_host(url: str) -> str | None:
    """Return a normalized root host when the URL is eligible for demo cache."""
    parsed = urlparse(_normalize_url(url))
    path = parsed.path.rstrip("/")
    if path:
        return None
    return parsed.netloc.lower().removeprefix("www.")


def _normalize_url(url: str) -> str:
    parsed = urlparse(url)
    if not parsed.scheme:
        url = f"https://{url}"
        parsed = urlparse(url)
    elif parsed.scheme == "http":
        url = url.replace("http://", "https://", 1)
        parsed = urlparse(url)

    host = parsed.netloc.lower()
    path = parsed.path.rstrip("/") if parsed.path != "/" else ""
    return f"https://{host}{path}"


def _cache_enabled_for_host(host: str | None) -> bool:
    settings = get_settings()
    if settings.env == "production" or not settings.demo_cache_enabled:
        return False
    return bool(host and host in settings.demo_cache_hosts)


def _cache_urls_for_host(host: str) -> set[str]:
    return {f"https://{host}", f"https://www.{host}"}


def should_use_demo_cache(url: str) -> bool:
    """Return true when a root product URL should use the demo cache."""
    return _cache_enabled_for_host(_normalized_cache_host(url))


async def get_or_create_cached_snapshot_id(
    url: str,
    db: AsyncSession,
) -> uuid.UUID | None:
    """Return a cached snapshot ID for demo hosts, seeding Netflix if needed."""
    host = _normalized_cache_host(url)
    if not _cache_enabled_for_host(host):
        return None

    assert host is not None
    snapshot_id = await _latest_snapshot_id_for_host(host, db)
    if snapshot_id is not None:
        log.info("demo_cache.snapshot.hit", host=host, snapshot_id=str(snapshot_id))
        return snapshot_id

    if host == NETFLIX_HOST:
        return await _seed_netflix_snapshot(db)

    return None


async def get_or_create_cached_segments(
    snapshot_id: uuid.UUID,
    db: AsyncSession,
) -> list[uuid.UUID] | None:
    """Return cached segment IDs for a demo snapshot, seeding Netflix if needed."""
    host = await _host_for_snapshot(snapshot_id, db)
    if not _cache_enabled_for_host(host):
        return None

    segment_ids = await _segment_ids_for_snapshot(snapshot_id, db)
    if segment_ids:
        log.info(
            "demo_cache.segments.hit",
            host=host,
            snapshot_id=str(snapshot_id),
            n_segments=len(segment_ids),
        )
        return segment_ids

    if host == NETFLIX_HOST:
        return await _seed_netflix_segments(snapshot_id, db)

    return None


async def complete_cached_simulation_if_available(
    simulation: Simulation,
    db: AsyncSession,
) -> bool:
    """Complete a demo simulation from deterministic cells without LLM calls."""
    host = await _host_for_snapshot(simulation.snapshot_id, db)
    if not _cache_enabled_for_host(host):
        return False

    if host != NETFLIX_HOST:
        return False

    await get_or_create_cached_segments(simulation.snapshot_id, db)

    existing = await _simulation_has_cells(simulation.id, db)
    if existing:
        simulation.status = "completed"
        await db.commit()
        return True

    segment_result = await db.execute(
        select(Segment)
        .where(Segment.snapshot_id == simulation.snapshot_id)
        .order_by(Segment.share_pct.desc())
    )
    segments = cast(list[Segment], list(segment_result.scalars().all()))
    if not segments:
        return False

    cells: list[SimulationCell] = []
    options = [
        opt for opt in (simulation.options or [])
        if isinstance(opt, dict) and opt.get("label")
    ]
    for segment_index, segment in enumerate(segments):
        for option_index, option in enumerate(options):
            cells.append(_make_netflix_cell(simulation.id, segment, option, segment_index, option_index))

    if not cells:
        return False

    db.add_all(cells)
    simulation.status = "completed"
    simulation.overall_confidence = "medium"
    simulation.completed_at = datetime.now(UTC)
    await db.commit()
    log.info(
        "demo_cache.simulation.completed",
        simulation_id=str(simulation.id),
        snapshot_id=str(simulation.snapshot_id),
        n_cells=len(cells),
    )
    return True


async def _latest_snapshot_id_for_host(
    host: str,
    db: AsyncSession,
) -> uuid.UUID | None:
    stmt = (
        select(ProductSnapshot.id)
        .join(Product, ProductSnapshot.product_id == Product.id)
        .where(Product.url.in_(_cache_urls_for_host(host)))
        .order_by(ProductSnapshot.created_at.desc())
        .limit(1)
    )
    result = await db.execute(stmt)
    value = result.scalar_one_or_none()
    return value if isinstance(value, uuid.UUID) else None


async def _host_for_snapshot(
    snapshot_id: uuid.UUID,
    db: AsyncSession,
) -> str | None:
    stmt = (
        select(Product.url)
        .join(ProductSnapshot, ProductSnapshot.product_id == Product.id)
        .where(ProductSnapshot.id == snapshot_id)
        .limit(1)
    )
    result = await db.execute(stmt)
    url = result.scalar_one_or_none()
    if not isinstance(url, str):
        return None
    return _normalized_cache_host(url)


async def _segment_ids_for_snapshot(
    snapshot_id: uuid.UUID,
    db: AsyncSession,
) -> list[uuid.UUID]:
    result = await db.execute(
        select(Segment.id)
        .where(Segment.snapshot_id == snapshot_id)
        .order_by(Segment.share_pct.desc())
    )
    return [
        value
        for value in result.scalars().all()
        if isinstance(value, uuid.UUID)
    ]


async def _simulation_has_cells(
    simulation_id: uuid.UUID,
    db: AsyncSession,
) -> bool:
    result = await db.execute(
        select(SimulationCell.id)
        .where(SimulationCell.simulation_id == simulation_id)
        .limit(1)
    )
    return result.scalar_one_or_none() is not None


async def _seed_netflix_snapshot(db: AsyncSession) -> uuid.UUID:
    product = await _get_or_create_netflix_product(db)
    snapshot_id = uuid.uuid4()
    snapshot = ProductSnapshot(
        id=snapshot_id,
        product_id=product.id,
        category="Streaming entertainment service",
        category_confidence="high",
        category_sources=3,
        value_prop=(
            "Netflix gives households and individual viewers on-demand access "
            "to a large catalog of TV, film, and original programming across devices."
        ),
        value_prop_confidence="high",
        value_prop_sources=3,
        pricing="Subscription plans vary by market and tier, including ad-supported and premium options.",
        pricing_confidence="medium",
        pricing_sources=2,
        features=(
            "On-demand streaming; personalized recommendations; offline downloads; "
            "multiple profiles; kids experience; cross-device playback"
        ),
        features_confidence="high",
        features_sources=3,
        audience="Consumers and households looking for convenient entertainment at home or on mobile.",
        audience_confidence="high",
        audience_sources=3,
        competitors="Disney+, Prime Video, Hulu, Max, YouTube, Apple TV+",
        competitors_confidence="medium",
        competitors_sources=2,
        raw_scrape=_netflix_raw_scrape(),
        raw_search_results=_netflix_raw_search_results(),
    )
    db.add(snapshot)
    await db.commit()
    log.info("demo_cache.snapshot.seeded", snapshot_id=str(snapshot_id), host=NETFLIX_HOST)
    return snapshot_id


async def _get_or_create_netflix_product(db: AsyncSession) -> Product:
    result = await db.execute(
        select(Product)
        .where(Product.url.in_(_cache_urls_for_host(NETFLIX_HOST)))
        .limit(1)
    )
    product = result.scalar_one_or_none()
    if isinstance(product, Product):
        return product

    product = Product(
        id=uuid.uuid4(),
        url=NETFLIX_CANONICAL_URL,
        display_name="Netflix",
    )
    db.add(product)
    await db.flush()
    return product


async def _seed_netflix_segments(
    snapshot_id: uuid.UUID,
    db: AsyncSession,
) -> list[uuid.UUID]:
    segments = [
        _make_segment(
            snapshot_id=snapshot_id,
            name="Value-conscious household streamers",
            descriptor=(
                "Families and shared households that use Netflix as a primary evening "
                "entertainment option but stay sensitive to monthly subscription cost."
            ),
            job_to_be_done=(
                "Keep everyone entertained with enough variety to justify one recurring bill."
            ),
            share_pct=42,
            drivers=[
                {"label": "Broad catalog", "weight": 0.4},
                {"label": "Household profiles", "weight": 0.3},
                {"label": "Perceived plan value", "weight": 0.3},
            ],
            leaves="Churn risk rises when the household feels the catalog is stale for the price.",
            seed=1,
        ),
        _make_segment(
            snapshot_id=snapshot_id,
            name="Prestige original-series fans",
            descriptor=(
                "Viewers who subscribe for exclusive shows, films, documentaries, and cultural moments."
            ),
            job_to_be_done="Stay current on must-watch originals without hunting across many services.",
            share_pct=33,
            drivers=[
                {"label": "Exclusive originals", "weight": 0.45},
                {"label": "Release momentum", "weight": 0.3},
                {"label": "Recommendation quality", "weight": 0.25},
            ],
            leaves="They churn when the upcoming slate does not include enough exclusive must-watch titles.",
            seed=2,
        ),
        _make_segment(
            snapshot_id=snapshot_id,
            name="Mobile and commute viewers",
            descriptor=(
                "Individual viewers who watch in shorter sessions across phones, tablets, and travel."
            ),
            job_to_be_done="Fill downtime with reliable playback and saved episodes wherever they are.",
            share_pct=25,
            drivers=[
                {"label": "Offline downloads", "weight": 0.35},
                {"label": "Cross-device continuity", "weight": 0.35},
                {"label": "Short-session discovery", "weight": 0.3},
            ],
            leaves="They leave when downloads, playback, or recommendations feel unreliable on mobile.",
            seed=3,
        ),
    ]

    db.add_all(segments)
    for segment in segments:
        db.add_all(_make_evidence_for_segment(segment))
    await db.commit()

    ids = [segment.id for segment in segments]
    log.info("demo_cache.segments.seeded", snapshot_id=str(snapshot_id), n_segments=len(ids))
    return ids


def _make_segment(
    *,
    snapshot_id: uuid.UUID,
    name: str,
    descriptor: str,
    job_to_be_done: str,
    share_pct: int,
    drivers: list[dict[str, object]],
    leaves: str,
    seed: int,
) -> Segment:
    return Segment(
        id=uuid.uuid4(),
        snapshot_id=snapshot_id,
        name=name,
        descriptor=descriptor,
        job_to_be_done=job_to_be_done,
        share_pct=share_pct,
        confidence="medium",
        drivers=drivers,
        leaves=leaves,
        embedding=_demo_embedding(seed),
    )


def _make_evidence_for_segment(segment: Segment) -> list[Evidence]:
    source_url = "https://www.netflix.com"
    if "household" in segment.name.lower():
        quotes = [
            "The value depends on whether everyone in the house can find something to watch.",
            "Profiles and kids viewing make it easier to keep one streaming service for the family.",
        ]
    elif "original" in segment.name.lower():
        quotes = [
            "Exclusive series are what pull me back when a new season drops.",
            "I keep Netflix when the originals feel hard to replace elsewhere.",
        ]
    else:
        quotes = [
            "Offline downloads matter most when I am traveling or commuting.",
            "I expect playback to pick up smoothly between my phone, tablet, and TV.",
        ]

    return [
        Evidence(
            id=uuid.uuid4(),
            segment_id=segment.id,
            quote=quote,
            source="Netflix demo cache",
            source_url=source_url,
            kind="other",
            captured_at=datetime.now(UTC),
            embedding=_demo_embedding(idx + 10),
        )
        for idx, quote in enumerate(quotes)
    ]


def _make_netflix_cell(
    simulation_id: uuid.UUID,
    segment: Segment,
    option: dict[str, object],
    segment_index: int,
    option_index: int,
) -> SimulationCell:
    option_label = str(option.get("label", "Option"))
    option_description = str(option.get("description", option_label))
    is_pricing = str(option.get("option_type", "")).lower() == "pricing"
    churn_mid = 0.34 + (segment_index * 0.04)
    if is_pricing and any(token in option_label.lower() for token in ["free", "cut", "discount"]):
        churn_mid -= 0.12
        sentiment = "positive"
    elif is_pricing and any(token in option_label.lower() for token in ["price", "+", "raise"]):
        churn_mid += 0.10
        sentiment = "negative"
    else:
        sentiment = "mixed" if option_index % 2 else "neutral"

    churn_mid = max(0.08, min(0.78, churn_mid))
    range_low = int(max(0.0, churn_mid - 0.1) * 100)
    range_high = int(min(1.0, churn_mid + 0.1) * 100)
    confidence = "medium" if segment.confidence != "low" else "low"

    return SimulationCell(
        id=uuid.uuid4(),
        simulation_id=simulation_id,
        segment_id=segment.id,
        option_letter=option_label,
        range_low=range_low,
        range_high=range_high,
        confidence=confidence,
        reasoning_trace=(
            f"{segment.name} weighs '{option_description}' against its core job. "
            "This cached demo response is deterministic and grounded in the seeded Netflix segment."
        ),
        top_concern="Whether the plan still feels worth the monthly subscription.",
        invalidating_experiment="Run a two-week plan-choice survey with current subscribers.",
        reaction_sentiment=sentiment,
        adoption_probability=round(1.0 - churn_mid, 2),
        time_horizon="30d" if is_pricing else "90d",
        devil_advocate=(
            "This could be wrong if recent content demand or household sharing behavior "
            "has shifted since the cached fixture was created."
        ),
    )


def _demo_embedding(seed: int) -> list[float]:
    values = [0.0] * EMBEDDING_DIM
    values[seed % EMBEDDING_DIM] = 1.0
    values[(seed * 31) % EMBEDDING_DIM] = 0.5
    return values


def _netflix_raw_scrape() -> dict[str, object]:
    now = datetime.now(UTC).isoformat()
    return {
        "url_canonical": NETFLIX_CANONICAL_URL,
        "pages": [
            {
                "url": NETFLIX_CANONICAL_URL,
                "kind": "homepage",
                "raw_html": "<html><title>Netflix</title></html>",
                "clean_text": (
                    "Netflix is a streaming entertainment service with TV shows, movies, "
                    "original series, documentaries, downloads, profiles, and cross-device viewing."
                ),
                "fetched_at": now,
            }
        ],
        "errors": [],
    }


def _netflix_raw_search_results() -> dict[str, object]:
    snippets = [
        (
            "netflix value household review",
            "https://www.g2.com/products/netflix/reviews",
            "Household viewers discuss Netflix value",
            "Families say Netflix works when profiles, kids content, and enough catalog variety justify the monthly subscription.",
            "g2",
        ),
        (
            "netflix originals fans",
            "https://www.reddit.com/r/netflix/",
            "Original series drive subscriptions",
            "Viewers often come back to Netflix for exclusive series, documentaries, and new seasons they cannot watch elsewhere.",
            "reddit",
        ),
        (
            "netflix mobile downloads",
            "https://www.netflix.com/features",
            "Downloads and mobile viewing",
            "Mobile viewers value offline downloads, reliable playback, and continuing an episode across phone, tablet, and TV.",
            "other",
        ),
    ]
    return {
        "results": [
            {
                "query": query,
                "url": url,
                "title": title,
                "snippet": snippet,
                "published_date": None,
                "source_kind": source_kind,
            }
            for query, url, title, snippet, source_kind in snippets
        ],
        "count": len(snippets),
    }
