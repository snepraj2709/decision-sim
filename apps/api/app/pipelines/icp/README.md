# ICP Pipeline

The ICP pipeline turns a completed `ProductSnapshot` into evidence-anchored customer segments. It is Layer 2 of the engine: Step 2 decides what the product is, Step 3 decides which customer groups the public evidence can support.

## Architecture

```
ProductSnapshot
  -> [Cluster]    raw search snippets -> candidate quote clusters
  -> [Synthesize] clusters + product context -> segment drafts
  -> [Anchor]     segment drafts -> 2-3 evidence quotes
  -> [Score]      triangulate() + DB writes -> Segment + Evidence rows
```

The package entry point is `run_icp_pipeline(snapshot_id, db)` in `__init__.py`. It is idempotent: every run deletes the previous segments for that snapshot and inserts the newly generated set. Evidence rows are deleted through the `Segment` cascade.

## Stage 1: Cluster (`cluster.py`)

`cluster_snippets()` extracts usable snippets from `snapshot.raw_search_results["results"]`. Each snippet is treated as a candidate voice-of-customer quote, with simple filters for obvious non-customer text such as privacy policies, cookie banners, unsubscribe copy, and terms pages.

Snippets are embedded into 1536-dimensional vectors, matching `EMBEDDING_DIM` on the ORM models. OpenAI `text-embedding-3-small` is the preferred real embedder when `OPENAI_API_KEY` is present. If OpenAI embeddings are unavailable, or if only `ANTHROPIC_API_KEY` is configured, the pipeline falls back to deterministic hash embeddings. This fallback keeps the development and Anthropic-only path runnable, but it is lower quality than semantic embeddings and should not be interpreted as production-grade clustering.

For eight or more snippets, the stage tries HDBSCAN with `min_cluster_size=2` and `min_samples=1`. If HDBSCAN produces fewer than three clusters, it falls back to `AgglomerativeClustering(n_clusters=4)`. With fewer than eight snippets, it skips clustering and emits one micro-cluster per snippet; downstream scoring will usually mark these as Low confidence because each segment has too little evidence.

## Stage 2: Synthesize (`synthesize.py`)

`synthesize_segments()` takes the largest clusters, adds product context from the snapshot fields, formats the member snippets as numbered quotes, and asks DSPy to produce:

- a short segment name
- a one-to-two sentence descriptor
- a plain-language Jobs-to-be-Done statement
- three weighted value drivers
- one churn or leave trigger
- the quote indices used as citations

Citation validation is deliberately strict. If the model cites an index outside the cluster, the segment is marked as having synthesis issues. That does not block persistence, but it caps stability during scoring so a fluent but poorly grounded segment cannot become High confidence.

## Stage 3: Anchor (`anchor.py`)

`anchor_segments()` chooses the two or three snippets closest to each cluster centroid by cosine similarity. Each selected quote becomes an `EvidenceQuote` with source URL, display source, source kind, captured date when available, domain, and embedding.

Segments with fewer than two anchors are preserved but flagged. Stage 4 converts that flag into a Low-confidence pressure. This is the "Hypothesis, not Portrait" behavior: the UI can show the segment honestly and ask for better customer data instead of fabricating supporting quotes.

## Stage 4: Score & Persist (`score.py`)

`score_and_persist()` computes the three signals required by `triangulate()`:

- `evidence_density`: unique source domains in the evidence anchors, not unique URLs.
- `llm_baserate_agreement`: proxy value from `compute_quote_coherence()`, the average pairwise quote similarity in embedding space.
- `construct_stability`: value from `compute_segment_stability()`, or `1 - max_similarity_to_neighbor`.

The geometric mean behavior in `triangulate()` is load-bearing. A segment with many anchors but poor coherence or poor distinctness still lands Low. This is intentional: an overconfident segment is more dangerous than a sparse segment that asks the user for better evidence.

## Evidence Quality Tradeoffs

The ICP pipeline treats public snippets as buyer/customer voice only when they pass fast regex filters. Press coverage and blog posts are excluded from synthesis and anchoring even when they may contain useful market context. This is deliberate: without LLM analysis at filter time, the pipeline cannot reliably tell first-party marketing, analyst summaries, and direct customer quotes apart, so it errs on the side of excluding them from customer evidence.

Review aggregate metadata, employee-review content, pricing pages, comparison pages, and navigation boilerplate are also filtered before synthesis and anchoring. If this removes too much public signal, the correct product behavior is a thinner or lower-confidence ICP, not fabricating independent evidence.

## Testing

Useful commands from `apps/api`:

```bash
uv run pytest tests/test_icp_pipeline_unit.py -q
uv run pytest tests/test_icp_api.py -q
uv run pytest -m "not integration"
uv run pytest -m integration
```

Integration tests read snapshot IDs from `tests/fixtures/snapshot_uuids.json`. Update that file when the local database is recreated and Step 2 snapshots get new IDs.
