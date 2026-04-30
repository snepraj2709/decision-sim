# Snapshot Pipeline

The snapshot pipeline transforms a product URL into a structured ProductSnapshot with per-field confidence labels.

## Architecture

```
URL → [Scrape] → [Search] → [Extract] → [Score] → ProductSnapshot
         ↓           ↓          ↓           ↓
      Playwright  Tavily/Exa   DSPy    triangulate()
      trafilatura
```

## Stages

### Stage 1: Scrape (`scrape.py`)

**Purpose:** Fetch and extract text content from the product website.

**Dependencies:** `playwright`, `trafilatura` (in `scrape` dep group)

**Process:**
1. Normalize URL (https, lowercase host, no trailing slash)
2. Fetch homepage with Playwright (handles JS-rendered pages)
3. Discover subpage links (pricing, features, about) from homepage
4. Fetch up to 4 subpages (5 total including homepage)
5. Extract clean text using trafilatura

**Outputs:**
- `ScrapeResult` with list of `ScrapedPage` objects
- Each page has: url, kind, raw_html, clean_text, fetched_at

**Failure Modes:**
- Homepage fails → `ScrapeError`, pipeline aborts
- Subpage fails → logged, continues with remaining pages
- Timeout (60s total) → continues with pages fetched so far

### Stage 2: Search (`search.py`)

**Purpose:** Gather external evidence from search results.

**Dependencies:** `tavily-python`, `exa-py` (in `scrape` dep group)

**Process:**
1. Build 3 search queries from product domain:
   - `"{domain}" reviews`
   - `"{domain}" pricing site:reddit.com OR site:news.ycombinator.com`
   - `"{domain}" alternatives competitors`
2. Execute searches via Tavily (primary) or Exa (fallback)
3. Classify each result's source_kind (reddit, g2, capterra, twitter, press, blog, other)
4. Deduplicate by URL

**Outputs:**
- List of `SearchResult` objects with query, url, title, snippet, source_kind

**Failure Modes:**
- No API key configured → returns empty list, pipeline continues
- Rate limit/error → retry once with backoff, then continue with partial results

### Stage 3: Extract (`extract.py`)

**Purpose:** Use LLM to extract structured product fields.

**Dependencies:** `dspy`, `anthropic`, `openai` (in `llm` dep group)

**Process:**
1. Configure DSPy with Anthropic or OpenAI LM
2. Prepare scraped content (prioritize: pricing > features > homepage)
3. Format search results as citation table with indices
4. Run DSPy Predict with ProductExtraction signature
5. Parse extracted fields with source indices and reasoning

**Outputs:**
- `ExtractionResult` with fields: category, value_prop, pricing, features, audience, competitors
- Each field has: value, sources (list of indices), reasoning

**Configuration:**
- Context capped at ~30k chars
- Temperature=0 for reproducibility
- Uses Claude Sonnet 4 (Anthropic) or GPT-4o (OpenAI)

**Failure Modes:**
- No LLM API key → `RuntimeError` at module load
- LLM error → propagates up, job fails

### Stage 4: Score & Persist (`score.py`)

**Purpose:** Compute confidence labels and save to database.

**Dependencies:** Core confidence module, SQLAlchemy

**Process:**
1. For each field, compute three signals:
   - **evidence_density:** `evidence_density_from_count(n_sources, min_for_high)`
   - **inter_source_agreement:** Jaccard similarity between field value and supporting snippets (proxy for baserate agreement in Step 2)
   - **construct_stability:** Heuristic based on claim count (1 claim = 1.0, 2 = 0.7, 3+ = 0.4)
2. Call `triangulate()` to combine signals into confidence label
3. Get-or-create Product row by URL
4. Insert ProductSnapshot with all fields, confidences, and raw data

**Outputs:**
- UUID of created ProductSnapshot

**Trade-offs:**
- Inter-source agreement is a proxy; Step 4 will add real base-rate comparison
- Construct stability heuristic is simplistic; works for v1

## Dependency Groups

The pipeline dependencies are in separate groups to avoid bloating CI:

```toml
[dependency-groups]
scrape = [
    "playwright>=1.48.0",
    "trafilatura>=1.12.2",
    "tavily-python>=0.5.0",
    "exa-py>=1.0.0",
]
llm = [
    "anthropic>=0.39.0",
    "openai>=1.54.0",
    "dspy>=2.5.0",
]
```

Install with: `uv sync --group scrape --group llm`

Don't forget to install Playwright browsers: `uv run playwright install chromium`

## Configuration

Required environment variables:

```bash
# At least one LLM provider
ANTHROPIC_API_KEY=sk-ant-...
# or
OPENAI_API_KEY=sk-...

# Optional: search providers (pipeline works without, but confidence will be low)
TAVILY_API_KEY=tvly-...
# or
EXA_API_KEY=...
```

## Testing

```bash
# Unit tests (no network)
uv run pytest -v -m "not integration"

# Integration tests (hits real URLs, requires API keys)
uv run pytest -v -m integration
```

## Extensions

The following extensions were made during implementation:

1. **URL normalization** strips trailing slashes and lowercases hosts for deduplication
2. **Link discovery** uses both href patterns and anchor text for better coverage
3. **Source kind classification** includes x.com as twitter alias
4. **Context prioritization** ensures pricing page content takes precedence when context is limited
