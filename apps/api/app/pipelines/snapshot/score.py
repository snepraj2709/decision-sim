"""Stage 4: Score & Persist — compute confidence and write to database.

This stage:
  - For each field, compute confidence using triangulate()
  - The three signals are:
    1. evidence_density: Based on number of unique sources
    2. llm_baserate_agreement: Proxy using inter-source agreement (Jaccard)
    3. construct_stability: Heuristic based on claim count in field value
  - Get-or-create the Product row by URL
  - Insert a new ProductSnapshot row with all fields + confidences
  - Return the new snapshot's UUID

NOTE: The llm_baserate_agreement signal is a PROXY in Step 2. We use
inter-source agreement (do multiple search snippets support the claim?)
instead of actual base-rate comparison. Step 4 will introduce the real
base-rate knowledge graph.

NOTE: The construct_stability heuristic is a placeholder. We count the
number of distinct claims (split on conjunctions). 1 claim = 1.0,
2 claims = 0.7, 3+ = 0.4. Step 4 will replace this for simulation cells.
"""

from __future__ import annotations

import re
import uuid

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.core.confidence import (
    Confidence,
    TriangulationInput,
    evidence_density_from_count,
    triangulate,
)
from app.models import Product, ProductSnapshot
from app.pipelines.snapshot.extract import ExtractedField, ExtractionResult
from app.pipelines.snapshot.scrape import ScrapeResult
from app.pipelines.snapshot.search import SearchResult

log = structlog.get_logger()


def _tokenize(text: str) -> set[str]:
    """Simple tokenization for Jaccard similarity."""
    # Lowercase, split on non-alphanumeric, remove short tokens
    tokens = re.findall(r"\b[a-z0-9]{3,}\b", text.lower())
    return set(tokens)


def compute_inter_source_agreement(
    field_value: str,
    supporting_snippets: list[str],
) -> float:
    """Compute inter-source agreement using token Jaccard similarity.

    This is a PROXY for llm_baserate_agreement in Step 2. We measure how
    much the extracted field value overlaps with the supporting search
    snippets. High overlap = the LLM is echoing what sources say = good.
    Low overlap = the LLM is making stuff up = bad.

    Args:
        field_value: The extracted field value from the LLM.
        supporting_snippets: List of search snippets that supposedly support it.

    Returns:
        Float in [0, 1]. Higher = more agreement.
    """
    if not field_value or not supporting_snippets:
        return 0.0

    field_tokens = _tokenize(field_value)
    if not field_tokens:
        return 0.0

    # Compute Jaccard with each snippet, take max
    max_jaccard = 0.0
    for snippet in supporting_snippets:
        snippet_tokens = _tokenize(snippet)
        if not snippet_tokens:
            continue

        intersection = len(field_tokens & snippet_tokens)
        union = len(field_tokens | snippet_tokens)
        if union > 0:
            jaccard = intersection / union
            max_jaccard = max(max_jaccard, jaccard)

    # Also compute average Jaccard for multiple sources
    if len(supporting_snippets) > 1:
        all_snippet_tokens: set[str] = set()
        for snippet in supporting_snippets:
            all_snippet_tokens |= _tokenize(snippet)

        if all_snippet_tokens:
            intersection = len(field_tokens & all_snippet_tokens)
            union = len(field_tokens | all_snippet_tokens)
            if union > 0:
                avg_jaccard = intersection / union
                # Weight: more snippets = trust the average more
                weight = min(0.5, len(supporting_snippets) * 0.1)
                max_jaccard = max(max_jaccard, avg_jaccard * (1 + weight))

    # Normalize to [0, 1] — Jaccard is already in that range but can be boosted
    return min(1.0, max_jaccard)


def compute_construct_stability(field_value: str) -> float:
    """Compute construct stability based on claim count.

    This is a PLACEHOLDER heuristic for Step 2. We count the number of
    distinct claims in the field value by looking for conjunction patterns.

    - 1 claim = 1.0 (clear, unambiguous)
    - 2 claims = 0.7 (some hedging)
    - 3+ claims = 0.4 (hedgy "and/or" salad)

    Args:
        field_value: The extracted field value.

    Returns:
        Float in [0, 1]. Higher = more stable/coherent.
    """
    if not field_value:
        return 0.0

    # Count claim separators: semicolons, " and ", " or ", commas in lists
    # But be smart about it — "project management and issue tracking" is one claim
    # while "startups, SMBs, and enterprises" might be multiple

    # Simple heuristic: count semicolons and "and/or" patterns
    semicolons = field_value.count(";")
    and_or = len(re.findall(r"\band/or\b|\bor\b.*\band\b|\band\b.*\bor\b", field_value, re.IGNORECASE))

    # Count explicit list items (commas followed by "and")
    list_items = len(re.findall(r",\s*(?:and|or)\s+", field_value, re.IGNORECASE))

    # Estimate claim count
    claim_count = 1 + semicolons + and_or + list_items

    if claim_count == 1:
        return 1.0
    elif claim_count == 2:
        return 0.7
    else:
        return 0.4


def compute_field_confidence(
    field: ExtractedField,
    search_results: list[SearchResult],
    settings_min_sources: int,
) -> tuple[Confidence, int]:
    """Compute confidence for a single field.

    Args:
        field: The extracted field with sources and value.
        search_results: All search results for snippet lookup.
        settings_min_sources: Minimum sources for high confidence.

    Returns:
        Tuple of (confidence_label, source_count).
    """
    # Gather supporting snippets
    supporting_snippets: list[str] = []
    for idx in field.sources:
        if 0 <= idx < len(search_results) and search_results[idx].snippet:
            supporting_snippets.append(search_results[idx].snippet)

    n_sources = len(set(field.sources))  # Unique sources

    # Signal 1: Evidence density
    evidence_density = evidence_density_from_count(
        n_sources,
        min_for_high=settings_min_sources,
    )

    # Signal 2: Inter-source agreement (proxy for baserate agreement)
    inter_source = compute_inter_source_agreement(
        field.value,
        supporting_snippets,
    )

    # Signal 3: Construct stability
    stability = compute_construct_stability(field.value)

    # Triangulate
    signals = TriangulationInput(
        llm_baserate_agreement=inter_source,
        evidence_density=evidence_density,
        construct_stability=stability,
    )
    confidence = triangulate(signals)

    log.debug(
        "score.field.computed",
        value=field.value[:50] if field.value else "",
        n_sources=n_sources,
        evidence_density=round(evidence_density, 2),
        inter_source=round(inter_source, 2),
        stability=round(stability, 2),
        confidence=confidence,
    )

    return confidence, n_sources


async def score_and_persist(
    scrape_result: ScrapeResult,
    search_results: list[SearchResult],
    extraction: ExtractionResult,
    db: AsyncSession,
) -> uuid.UUID:
    """Score fields and persist the snapshot.

    Args:
        scrape_result: Result from scrape stage.
        search_results: Results from search stage.
        extraction: Results from extraction stage.
        db: Async database session.

    Returns:
        UUID of the created ProductSnapshot.
    """
    settings = get_settings()

    # Compute confidence for each field
    fields_data: dict[str, tuple[str, Confidence, int]] = {}

    for field_name in ["category", "value_prop", "pricing", "features", "audience", "competitors"]:
        field: ExtractedField = getattr(extraction, field_name)
        confidence, n_sources = compute_field_confidence(
            field,
            search_results,
            settings.min_sources_for_high_confidence,
        )
        fields_data[field_name] = (field.value, confidence, n_sources)

    # Get or create Product
    url = scrape_result.url_canonical
    stmt = select(Product).where(Product.url == url)
    result = await db.execute(stmt)
    product = result.scalar_one_or_none()

    if product is None:
        # Extract display name from homepage title or URL
        homepage = next((p for p in scrape_result.pages if p.kind == "homepage"), None)
        display_name = None
        if homepage and homepage.clean_text:
            # Take first line as potential title
            first_line = homepage.clean_text.split("\n")[0].strip()
            if first_line and len(first_line) < 100:
                display_name = first_line

        product = Product(url=url, display_name=display_name)
        db.add(product)
        await db.flush()  # Get the ID
        log.info("score.product.created", url=url, product_id=str(product.id))
    else:
        log.info("score.product.exists", url=url, product_id=str(product.id))

    # Prepare raw data for JSONB columns
    raw_scrape = scrape_result.to_dict()
    raw_search_results = {
        "results": [r.to_dict() for r in search_results],
        "count": len(search_results),
    }

    # Create ProductSnapshot
    snapshot = ProductSnapshot(
        product_id=product.id,
        category=fields_data["category"][0],
        category_confidence=fields_data["category"][1],
        category_sources=fields_data["category"][2],
        value_prop=fields_data["value_prop"][0],
        value_prop_confidence=fields_data["value_prop"][1],
        value_prop_sources=fields_data["value_prop"][2],
        pricing=fields_data["pricing"][0],
        pricing_confidence=fields_data["pricing"][1],
        pricing_sources=fields_data["pricing"][2],
        features=fields_data["features"][0],
        features_confidence=fields_data["features"][1],
        features_sources=fields_data["features"][2],
        audience=fields_data["audience"][0],
        audience_confidence=fields_data["audience"][1],
        audience_sources=fields_data["audience"][2],
        competitors=fields_data["competitors"][0],
        competitors_confidence=fields_data["competitors"][1],
        competitors_sources=fields_data["competitors"][2],
        raw_scrape=raw_scrape,
        raw_search_results=raw_search_results,
    )
    db.add(snapshot)
    await db.commit()

    log.info(
        "score.snapshot.created",
        snapshot_id=str(snapshot.id),
        product_id=str(product.id),
        confidences={
            "category": fields_data["category"][1],
            "value_prop": fields_data["value_prop"][1],
            "pricing": fields_data["pricing"][1],
            "features": fields_data["features"][1],
            "audience": fields_data["audience"][1],
            "competitors": fields_data["competitors"][1],
        },
    )

    return snapshot.id
