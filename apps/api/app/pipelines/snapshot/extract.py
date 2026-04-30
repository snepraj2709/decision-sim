"""Stage 3: Extract — use DSPy to produce structured product fields.

This stage:
  - Takes clean_text from scraped pages + search snippets
  - Runs a DSPy program to extract structured fields
  - Returns extracted fields with source indices and reasoning

For EACH field, the LLM returns:
  - value: The extracted field value
  - sources: List of indices into search results that support it
  - reasoning: 1-2 sentences explaining the extraction

Confidence is NOT computed here — that happens in Stage 4 using objective signals.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import dspy  # type: ignore[import-untyped]
import structlog

from app.config import get_settings
from app.pipelines.snapshot.scrape import ScrapeResult
from app.pipelines.snapshot.search import SearchResult

log = structlog.get_logger()

# Maximum context length in characters
MAX_CONTEXT_CHARS = 30000

# LM instance — configured at module load
_lm: dspy.LM | None = None


def _get_lm() -> dspy.LM:
    """Get or create the configured LM instance."""
    global _lm
    if _lm is not None:
        return _lm

    settings = get_settings()

    if settings.anthropic_api_key:
        model = "anthropic/claude-sonnet-4-20250514"
        log.info("extract.lm.configured", provider="anthropic", model=model)
    elif settings.openai_api_key:
        model = "openai/gpt-4o"
        log.info("extract.lm.configured", provider="openai", model=model)
    else:
        raise RuntimeError(
            "No LLM API key configured. Set ANTHROPIC_API_KEY or OPENAI_API_KEY."
        )

    _lm = dspy.LM(
        model=model,
        temperature=0,  # Deterministic for reproducibility
        max_tokens=4096,
    )
    return _lm


@dataclass(slots=True)
class ExtractedField:
    """A single extracted field with supporting evidence."""

    value: str
    sources: list[int] = field(default_factory=list)  # Indices into search results
    reasoning: str = ""


@dataclass(slots=True)
class ExtractionResult:
    """Result of the extraction stage."""

    category: ExtractedField
    value_prop: ExtractedField
    pricing: ExtractedField
    features: ExtractedField
    audience: ExtractedField
    competitors: ExtractedField


class ProductExtraction(dspy.Signature):  # type: ignore[misc]
    """Extract structured product information from scraped content and search results.

    You are analyzing a product website and external search results to extract
    accurate, factual information about the product.

    For each field:
    - Extract only what is explicitly stated or strongly implied
    - Cite source indices when external search results support the claim
    - Provide brief reasoning explaining your extraction
    - If information is unclear or missing, say "Unknown" or "Not specified"
    """

    scraped_content: str = dspy.InputField(
        desc="Clean text from the product website, organized by page type"
    )
    search_results: str = dspy.InputField(
        desc="External search results with index numbers for citation"
    )

    category: str = dspy.OutputField(
        desc="Product category (e.g., 'Project Management', 'CRM', 'Developer Tools')"
    )
    category_sources: str = dspy.OutputField(
        desc="Comma-separated indices of search results supporting category (e.g., '0,2,5')"
    )
    category_reasoning: str = dspy.OutputField(
        desc="1-2 sentences explaining the category extraction"
    )

    value_prop: str = dspy.OutputField(
        desc="Core value proposition - what problem does it solve and for whom"
    )
    value_prop_sources: str = dspy.OutputField(
        desc="Comma-separated indices of search results supporting value prop"
    )
    value_prop_reasoning: str = dspy.OutputField(
        desc="1-2 sentences explaining the value prop extraction"
    )

    pricing: str = dspy.OutputField(
        desc="Pricing model and tiers (e.g., 'Freemium, $10/user/mo Pro, Enterprise custom')"
    )
    pricing_sources: str = dspy.OutputField(
        desc="Comma-separated indices of search results supporting pricing"
    )
    pricing_reasoning: str = dspy.OutputField(
        desc="1-2 sentences explaining the pricing extraction"
    )

    features: str = dspy.OutputField(
        desc="Key features as a semicolon-separated list"
    )
    features_sources: str = dspy.OutputField(
        desc="Comma-separated indices of search results supporting features"
    )
    features_reasoning: str = dspy.OutputField(
        desc="1-2 sentences explaining the features extraction"
    )

    audience: str = dspy.OutputField(
        desc="Target audience (e.g., 'Engineering teams at startups and scale-ups')"
    )
    audience_sources: str = dspy.OutputField(
        desc="Comma-separated indices of search results supporting audience"
    )
    audience_reasoning: str = dspy.OutputField(
        desc="1-2 sentences explaining the audience extraction"
    )

    competitors: str = dspy.OutputField(
        desc="Main competitors as a comma-separated list"
    )
    competitors_sources: str = dspy.OutputField(
        desc="Comma-separated indices of search results supporting competitors"
    )
    competitors_reasoning: str = dspy.OutputField(
        desc="1-2 sentences explaining the competitors extraction"
    )


def _prepare_scraped_content(scrape_result: ScrapeResult) -> str:
    """Prepare scraped content for the LLM, prioritizing by page kind."""
    # Priority: pricing > features > homepage > others
    priority = {"pricing": 0, "features": 1, "homepage": 2, "about": 3, "product": 4, "plans": 5, "other": 6}

    sorted_pages = sorted(
        scrape_result.pages,
        key=lambda p: priority.get(p.kind, 99)
    )

    parts: list[str] = []
    total_chars = 0

    for page in sorted_pages:
        if not page.clean_text:
            continue

        header = f"\n=== {page.kind.upper()} PAGE ({page.url}) ===\n"
        text = page.clean_text

        # Check if adding this would exceed limit
        if total_chars + len(header) + len(text) > MAX_CONTEXT_CHARS:
            # Add truncated version
            remaining = MAX_CONTEXT_CHARS - total_chars - len(header) - 50
            if remaining > 500:
                parts.append(header)
                parts.append(text[:remaining])
                parts.append("\n[...truncated...]")
            break

        parts.append(header)
        parts.append(text)
        total_chars += len(header) + len(text)

    return "".join(parts)


def _prepare_search_results(search_results: list[SearchResult]) -> str:
    """Prepare search results as a citation table."""
    if not search_results:
        return "No external search results available."

    lines = ["EXTERNAL SEARCH RESULTS (cite by index number):", ""]

    for i, result in enumerate(search_results):
        lines.append(f"[{i}] {result.title}")
        lines.append(f"    URL: {result.url}")
        lines.append(f"    Source: {result.source_kind}")
        if result.snippet:
            # Truncate long snippets
            snippet = result.snippet[:500] + "..." if len(result.snippet) > 500 else result.snippet
            lines.append(f"    Snippet: {snippet}")
        lines.append("")

    return "\n".join(lines)


def _parse_sources(sources_str: str) -> list[int]:
    """Parse a comma-separated string of source indices."""
    if not sources_str or sources_str.lower() in ("none", "n/a", ""):
        return []

    indices: list[int] = []
    for part in sources_str.split(","):
        part = part.strip()
        if part.isdigit():
            indices.append(int(part))

    return indices


async def run_extraction(
    scrape_result: ScrapeResult,
    search_results: list[SearchResult],
) -> ExtractionResult:
    """Run the extraction stage.

    Args:
        scrape_result: Result from the scrape stage.
        search_results: Results from the search stage.

    Returns:
        ExtractionResult with structured fields and evidence.

    Raises:
        RuntimeError: If no LLM is configured.
    """
    import asyncio

    lm = _get_lm()

    # Prepare inputs
    scraped_content = _prepare_scraped_content(scrape_result)
    search_content = _prepare_search_results(search_results)

    log.info(
        "extract.context.prepared",
        scraped_chars=len(scraped_content),
        search_results=len(search_results),
    )

    # Run DSPy prediction
    def _predict() -> dspy.Prediction:
        with dspy.context(lm=lm):
            predictor = dspy.Predict(ProductExtraction)
            return predictor(
                scraped_content=scraped_content,
                search_results=search_content,
            )

    prediction = await asyncio.to_thread(_predict)

    log.info("extract.prediction.done")

    # Parse results
    result = ExtractionResult(
        category=ExtractedField(
            value=prediction.category or "Unknown",
            sources=_parse_sources(prediction.category_sources or ""),
            reasoning=prediction.category_reasoning or "",
        ),
        value_prop=ExtractedField(
            value=prediction.value_prop or "Unknown",
            sources=_parse_sources(prediction.value_prop_sources or ""),
            reasoning=prediction.value_prop_reasoning or "",
        ),
        pricing=ExtractedField(
            value=prediction.pricing or "Not specified",
            sources=_parse_sources(prediction.pricing_sources or ""),
            reasoning=prediction.pricing_reasoning or "",
        ),
        features=ExtractedField(
            value=prediction.features or "Not specified",
            sources=_parse_sources(prediction.features_sources or ""),
            reasoning=prediction.features_reasoning or "",
        ),
        audience=ExtractedField(
            value=prediction.audience or "Unknown",
            sources=_parse_sources(prediction.audience_sources or ""),
            reasoning=prediction.audience_reasoning or "",
        ),
        competitors=ExtractedField(
            value=prediction.competitors or "Unknown",
            sources=_parse_sources(prediction.competitors_sources or ""),
            reasoning=prediction.competitors_reasoning or "",
        ),
    )

    return result
