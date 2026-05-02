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
from urllib.parse import urlparse

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

STOP_WORDS = {
    "and",
    "are",
    "but",
    "for",
    "from",
    "into",
    "not",
    "the",
    "that",
    "this",
    "with",
    "you",
    "your",
}

UNKNOWN_VALUES = {
    "",
    "n/a",
    "none",
    "not applicable",
    "not specified",
    "unknown",
}

FIRST_PARTY_MIN_TOTAL_CHARS = 1000
FIRST_PARTY_MIN_PAGE_CHARS = 300
FIRST_PARTY_SUPPORT_THRESHOLD = 0.35
FIRST_PARTY_ALIGNMENT_THRESHOLD = 0.30
TRUSTED_EXTERNAL_SOURCE_KINDS = {"reddit", "g2", "capterra", "twitter", "press", "blog"}
COMMON_DOMAIN_TOKENS = {
    "app",
    "com",
    "co",
    "io",
    "net",
    "org",
    "www",
}


def _tokenize(text: str) -> set[str]:
    """Simple tokenization for Jaccard similarity."""
    return set(_token_sequence(text))


def _token_sequence(text: str) -> list[str]:
    """Return normalized tokens while preserving order."""
    # Lowercase, split on non-alphanumeric, remove short tokens
    tokens = re.findall(r"\b[a-z0-9]{3,}\b", text.lower())
    return [token for token in tokens if token not in STOP_WORDS]


def _has_contiguous_sequence(needle: list[str], haystack: list[str]) -> bool:
    """Return true when all needle tokens appear consecutively in haystack."""
    if not needle or len(needle) > len(haystack):
        return False

    needle_len = len(needle)
    return any(haystack[idx : idx + needle_len] == needle for idx in range(len(haystack) - needle_len + 1))


def _is_unknownish(value: str) -> bool:
    """Return true for placeholder values that should not earn confidence."""
    normalized = value.strip().lower().rstrip(".")
    return normalized in UNKNOWN_VALUES


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

    field_sequence = _token_sequence(field_value)
    field_tokens = set(field_sequence)
    if not field_tokens:
        return 0.0

    # Compute agreement with each snippet, taking the best source. Plain
    # Jaccard unfairly penalizes concise facts against long evidence pages, so
    # include directional coverage: how much of the field appears in the source.
    max_jaccard = 0.0
    for snippet in supporting_snippets:
        snippet_tokens = _tokenize(snippet)
        if not snippet_tokens:
            continue

        intersection = len(field_tokens & snippet_tokens)
        union = len(field_tokens | snippet_tokens)
        if union > 0:
            jaccard = intersection / union
            coverage = intersection / len(field_tokens)
            snippet_sequence = _token_sequence(snippet)
            # Very short labels are prone to false support from scattered terms
            # in long pages. Require phrase-level support before using the
            # directional coverage shortcut.
            if len(field_tokens) <= 2 and not _has_contiguous_sequence(field_sequence, snippet_sequence):
                coverage = jaccard
            max_jaccard = max(max_jaccard, jaccard, coverage)

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
    scrape_result: ScrapeResult | None = None,
) -> tuple[Confidence, int]:
    """Compute confidence for a single field.

    Args:
        field: The extracted field with sources and value.
        search_results: All search results for snippet lookup.
        settings_min_sources: Minimum sources for high confidence.

    Returns:
        Tuple of (confidence_label, source_count).
    """
    # Gather supporting snippets from valid LLM-cited external search results.
    supporting_snippets: list[str] = []
    valid_external_source_ids: set[int] = set()
    first_party_snippets = _first_party_supporting_snippets(field.value, scrape_result)
    for idx in field.sources:
        if (
            0 <= idx < len(search_results)
            and search_results[idx].snippet
            and _is_relevant_external_source(
                result=search_results[idx],
                scrape_result=scrape_result,
                field_value=field.value,
                first_party_supports_field=bool(first_party_snippets),
            )
        ):
            valid_external_source_ids.add(idx)
            supporting_snippets.append(search_results[idx].snippet)

    first_party_source_count = 0
    if first_party_snippets and valid_external_source_ids:
        supporting_snippets.extend(first_party_snippets)
        first_party_source_count = 1

    n_sources = len(valid_external_source_ids) + first_party_source_count

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
        external_sources=len(valid_external_source_ids),
        first_party_sources=first_party_source_count,
        n_sources=n_sources,
        evidence_density=round(evidence_density, 2),
        inter_source=round(inter_source, 2),
        stability=round(stability, 2),
        confidence=confidence,
    )

    return confidence, n_sources


def _first_party_supporting_snippets(
    field_value: str,
    scrape_result: ScrapeResult | None,
) -> list[str]:
    """Return scraped page text that corroborates a field.

    First-party website evidence is useful for rich product pages, but it
    should not rescue guesses on thin pages or replace external evidence.
    """
    if not scrape_result or _is_unknownish(field_value):
        return []

    text_pages = [
        page.clean_text
        for page in scrape_result.pages
        if len(page.clean_text.strip()) >= FIRST_PARTY_MIN_PAGE_CHARS
    ]
    if sum(len(text) for text in text_pages) < FIRST_PARTY_MIN_TOTAL_CHARS:
        return []

    supporting_pages = [
        text
        for text in text_pages
        if compute_inter_source_agreement(field_value, [text]) >= FIRST_PARTY_SUPPORT_THRESHOLD
    ]
    return supporting_pages[:2]


def _is_relevant_external_source(
    *,
    result: SearchResult,
    scrape_result: ScrapeResult | None,
    field_value: str,
    first_party_supports_field: bool,
) -> bool:
    """Return whether a cited search result is about this product.

    Search providers often return SEO/domain-name noise for sparse sites. A
    result must first identify the product. After that, trusted review/social/
    press sources can stand on their own; generic "other" sources need either
    topical alignment with the product site or first-party support for the same
    field value.
    """
    if scrape_result is None:
        return True

    if _is_same_site(result.url, scrape_result):
        return True

    if not _mentions_product_identity(result, scrape_result):
        return False

    if result.source_kind in TRUSTED_EXTERNAL_SOURCE_KINDS:
        return True

    if first_party_supports_field and compute_inter_source_agreement(
        field_value,
        [_search_result_text(result)],
    ) >= FIRST_PARTY_SUPPORT_THRESHOLD:
        return True

    return _first_party_alignment(result, scrape_result) >= FIRST_PARTY_ALIGNMENT_THRESHOLD


def _is_same_site(url: str, scrape_result: ScrapeResult) -> bool:
    """Return true if a search result URL is on the product's own domain."""
    return _normalized_host(url) == _normalized_host(scrape_result.url_canonical)


def _mentions_product_identity(result: SearchResult, scrape_result: ScrapeResult) -> bool:
    """Return true if title/snippet/url mention the product host or name token."""
    text = _search_result_text(result).lower()
    host = _normalized_host(scrape_result.url_canonical)
    if host and host in text:
        return True

    return any(re.search(rf"\b{re.escape(term)}\b", text) for term in _identity_terms(host))


def _first_party_alignment(result: SearchResult, scrape_result: ScrapeResult) -> float:
    """Estimate whether a search result talks about the same thing as the site."""
    official_tokens = _tokenize(_first_party_text(scrape_result))
    result_tokens = _tokenize(f"{result.title} {result.snippet}")
    if not official_tokens or not result_tokens:
        return 0.0

    overlap = len(official_tokens & result_tokens)
    return overlap / max(1, min(len(result_tokens), 50))


def _search_result_text(result: SearchResult) -> str:
    """Return all searchable text for a search result."""
    return f"{result.url} {result.title} {result.snippet}"


def _first_party_text(scrape_result: ScrapeResult) -> str:
    """Return concatenated first-party clean text."""
    return "\n".join(page.clean_text for page in scrape_result.pages)


def _normalized_host(url: str) -> str:
    """Return a lowercase host without a leading www."""
    return urlparse(url).netloc.lower().removeprefix("www.")


def _identity_terms(host: str) -> set[str]:
    """Return distinctive product-name-ish tokens from a host."""
    raw_tokens = re.split(r"[^a-z0-9]+", host.lower())
    return {
        token
        for token in raw_tokens
        if len(token) >= 4 and token not in COMMON_DOMAIN_TOKENS
    }


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
            scrape_result,
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
