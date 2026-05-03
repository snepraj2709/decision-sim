# Step 1 — Runbook & verification protocol

This file is the single source of truth for "is Step 1 done?" Run through it top to bottom. If every checkpoint passes, you can move to Step 2 confidently. If any one fails, **fix it before moving on** — Step 2 builds on top of these foundations and a shaky foundation costs days, not hours.

## What Step 1 ships

A monorepo where:

- **Frontend** (Next.js 15 + React 19 + Tailwind 3 + TS strict) renders the design tokens and two ported primitives (`ConfidenceBand`, `Cell`) at all three confidence states.
- **Backend** (FastAPI + SQLAlchemy 2 + Alembic + Pydantic v2) boots, exposes `/api/v1/health`, and wires `/api/v1/snapshots` as a documented 501.
- **Database** (Postgres 16 + pgvector) has the full schema migrated, with CHECK constraints enforcing the `Confidence` literal at the DB layer.
- **Worker** (Redis + RQ) is connected and has task entry points stubbed.
- **CI** (GitHub Actions) runs lint + typecheck on web, ruff + mypy + pytest on api, including a Postgres + Redis service.
- **Pipelines** (`snapshot.py`, `icp.py`, `simulation.py`) raise `NotImplementedError` with informative messages pointing at which Step builds them.

What it deliberately does **not** ship: any pipeline implementations, any "fake" scrape data, any UI wired to imaginary endpoints.

---

## Prerequisites

```bash
node --version    # ≥ 20
pnpm --version    # ≥ 9
python --version  # ≥ 3.12
uv --version      # any recent
docker --version  # any recent
```

If `uv` isn't installed: `curl -LsSf https://astral.sh/uv/install.sh | sh`

## Setup

```bash
cd decision-sim
cp .env.example .env

# Frontend deps
pnpm install

# Backend deps
cd apps/api
uv sync
cd ../..

# Data services
docker compose up -d
# Wait ~5 sec for postgres to be healthy:
docker compose ps        # should show postgres + redis as "healthy"

# Migrations
cd apps/api
uv run alembic upgrade head
cd ../..
```

## Run all three processes

In three terminals:

```bash
# Terminal 1 — backend
cd apps/api && uv run fastapi dev app/main.py
# Should log: api.startup env=development version=0.1.0
# OpenAPI UI at http://localhost:8000/docs

# Terminal 2 — RQ worker
cd apps/api && uv run rq worker --url redis://localhost:6379
# Should log: Worker ... started with PID ...
# (No tasks will arrive in Step 1 — just proves the connection works.)

# Terminal 3 — frontend
pnpm --filter web dev
# Visit http://localhost:3000
```

---

## ✅ Verification checklist

Run through these in order. Each checkpoint has a specific success criterion — vague "looks fine" doesn't count.

### 1. Database schema is correct

```bash
docker exec -it dsim-postgres psql -U dsim -d dsim -c "\dt"
```

Expected: 6 tables — `products`, `product_snapshots`, `segments`, `evidence`, `simulations`, `simulation_cells`, plus `alembic_version`.

```bash
docker exec -it dsim-postgres psql -U dsim -d dsim -c "\dx"
```

Expected: extensions include `vector` (pgvector) and `uuid-ossp`.

```bash
docker exec -it dsim-postgres psql -U dsim -d dsim -c "\d segments"
```

Expected: a `Check constraints:` section listing `ck_segments_confidence` enforcing `(confidence = ANY (ARRAY['high', 'medium', 'low']))`. **This is the load-bearing line — confidence is enforced at the DB layer, not just in Python.**

### 2. Backend health works

```bash
curl -s http://localhost:8000/api/v1/health | jq .
```

Expected: `{"status":"ok","env":"development","version":"0.1.0"}`

### 3. Snapshot endpoint returns an honest 501

```bash
curl -s -X POST http://localhost:8000/api/v1/snapshots \
  -H 'Content-Type: application/json' \
  -d '{"url":"https://example.com"}' | jq .
```

Expected: HTTP 501 with a `detail` message that mentions `Step 2` and `snapshot.py`. **The exact message matters** — it's how a future collaborator (including future you) finds the right file to start in.

### 4. Pydantic validation works

```bash
curl -s -X POST http://localhost:8000/api/v1/snapshots \
  -H 'Content-Type: application/json' \
  -d '{"url":"ab"}' -w '\n%{http_code}\n'
```

Expected: HTTP 422 — the schema rejects the 3-char URL *before* hitting the stub.

### 5. OpenAPI schema exposes the Confidence enum

```bash
curl -s http://localhost:8000/openapi.json | jq '.components.schemas | keys'
```

Expected: schema list includes `ConfidentField`, `ProductSnapshotRead`, `HealthResponse`, etc. The `confidence` field on these schemas is enumerated as `"high" | "medium" | "low"` — verify by visiting `http://localhost:8000/docs` and expanding any schema.

### 6. Frontend renders the primitives correctly

Visit `http://localhost:3000`. You should see:

- **API health card** showing `{"status":"ok",...}` — proves the frontend successfully called the backend at build time.
- **ConfidenceBand row** showing 7 chips: 3 small + 3 large + 1 italicized "Hypothesis" chip. The High chip has a solid green-ink filled circle; Medium has an open amber ring; Low has a striped clay-colored lozenge.
- **Cell row** showing 3 cells: High (3–8%, bold mono), Medium (20–30%, dashed inner outline, lighter), Low (50–70%, italic, diagonal stripe pattern, faded to ~78% opacity).

**Visual gut check:** the three Cells should be *physically distinguishable from across the room*. If they look "similar but with different colors," the design hasn't survived the port — file a bug before continuing. The whole product depends on confidence being a UI state, not a label.

### 7. Tests pass

```bash
cd apps/api && uv run pytest -v
```

Expected: ~20 tests pass, no failures. Pay special attention to:

- `test_one_zero_axis_drags_to_low` — proves the geometric mean property. **If this fails, the engine will quietly produce overconfident predictions.**
- `test_snapshot_endpoint_returns_501_with_message` — proves the stub message contract.

### 8. Type-checking is strict

```bash
# Web
pnpm --filter web typecheck   # must complete with no errors

# API
cd apps/api && uv run mypy app   # must complete with no errors
```

If either complains, fix before proceeding. The whole point of Step 1's strictness is that types are a contract Steps 2–4 build against.

### 9. Linting is clean

```bash
pnpm --filter web lint
cd apps/api && uv run ruff check .
```

### 10. CI green on a fresh push

Push to a branch and open a PR. Both `web` and `api` jobs in `.github/workflows/ci.yml` must succeed. If they don't, **the local pass was a fluke** — likely a missing `.env` or unpinned dependency. Reproduce locally with the same env vars CI uses (see `ci.yml`).

---

## What "done" looks like

All ten checkpoints green. Not nine. The most common failure mode is "9/10, the last one is small, I'll fix it later" — this is exactly how scaffolding decisions sneak in as silent assumptions and bite you in week 4.

When all ten pass: **commit, tag `step-1-complete`, and move to Step 2**.

---

## Rolling forward — what Step 2 looks like

Step 2's prompt to Claude (or to yourself) starts with:

> "Implement the snapshot pipeline at `apps/api/app/pipelines/snapshot.py`. The contract is locked — read the docstring. Use Playwright + trafilatura for scraping, Tavily or Exa for search grounding, DSPy for structured extraction. Each field on the ProductSnapshot must include a confidence label produced by `app.core.confidence.triangulate()`. Replace the 501 in `apps/api/app/api/v1/snapshots.py` with the real implementation. Add at least 3 integration tests against real product URLs (Linear, Notion, a stealth-mode B2B example with thin public data — verify the last one produces a Low-confidence snapshot, not a fake-confident one)."

Notice what changed: nothing about scaffolding, nothing about types, nothing about UI. The scaffolding fights are over. Step 2 is purely about implementing one well-defined contract.

That clarity — the ability to write a precise next prompt — is what Step 1 buys you.

---

# Step 2 — Snapshot Pipeline Verification

This section documents the verification protocol for Step 2. Run through it after implementing the snapshot pipeline.

## What Step 2 ships

- **Snapshot Pipeline** — A four-stage pipeline that transforms a URL into a ProductSnapshot:
  1. **Scrape** — Playwright + trafilatura for fetching and extracting web content
  2. **Search** — Tavily/Exa for gathering external evidence
  3. **Extract** — DSPy for LLM-powered structured extraction
  4. **Score** — Confidence triangulation + database persistence

- **API Endpoints** — The 501 stub is replaced with working async endpoints:
  - `POST /snapshots` — Enqueues job, returns 202 with job_id
  - `GET /snapshots/{id}` — Returns completed snapshot
  - `GET /snapshots/jobs/{job_id}` — Returns job status

- **Tests** — Unit tests for pipeline components, integration tests for real URLs

## Prerequisites

Step 1 must be complete. Additionally:

```bash
# Sync dependencies with scrape and llm groups
cd apps/api
uv sync --group dev --group scrape --group llm

# Install Playwright browsers
uv run playwright install chromium

# Set API keys in .env
# At least one of:
ANTHROPIC_API_KEY=sk-ant-...
OPENAI_API_KEY=sk-...

# Optional (pipeline works without, but produces low confidence):
TAVILY_API_KEY=tvly-...
```

## ✅ Verification checklist

### 1. Unit tests pass

```bash
cd apps/api && uv run pytest -v -m "not integration"
```

Expected: ~70+ tests pass, no failures. Pay special attention to:

- `test_geometric_mean_property` — proves confidence triangulation works
- `test_high_sources_high_agreement_high_stability` — rich data → high confidence
- `test_no_sources_produces_low` — no evidence → low confidence

### 2. Mypy and Ruff are clean

```bash
cd apps/api && uv run mypy app && uv run ruff check .
```

Expected: No errors.

### 3. POST /snapshots returns 202

```bash
curl -s -X POST http://localhost:8000/api/v1/snapshots \
  -H 'Content-Type: application/json' \
  -d '{"url":"https://linear.app"}' | jq .
```

Expected:
```json
{
  "job_id": "some-uuid",
  "status_url": "http://localhost:8000/api/v1/snapshots/jobs/some-uuid"
}
```

### 4. Job status endpoint works

```bash
# Use the job_id from step 3
curl -s http://localhost:8000/api/v1/snapshots/jobs/{job_id} | jq .
```

Expected: `{"status": "queued"}` or `{"status": "started"}` or `{"status": "finished", "snapshot_id": "..."}`

### 5. Worker processes the job

With the RQ worker running, wait for the job to complete. On macOS, keep the
`OBJC_DISABLE_INITIALIZE_FORK_SAFETY` prefix; RQ's default worker forks and
Playwright's browser stack can otherwise abort the work-horse process.

```bash
cd apps/api
OBJC_DISABLE_INITIALIZE_FORK_SAFETY=YES uv run rq worker --url redis://localhost:6379
```

Check:

```bash
curl -s http://localhost:8000/api/v1/snapshots/jobs/{job_id} | jq .
```

Expected: `{"status": "finished", "snapshot_id": "..."}`

### 6. Snapshot contains sensible data

```bash
curl -s http://localhost:8000/api/v1/snapshots/{snapshot_id} | jq .
```

Expected:
- `category` contains something like "Project Management" or "Issue Tracking"
- `value_prop` describes what Linear does
- `features` lists actual Linear features
- Confidence values are present ("high", "medium", or "low")

### 7. Linear.app produces reasonable confidence

The Linear.app snapshot should have:
- At least 2-3 fields with "high" or "medium" confidence
- `category_sources`, `value_prop_sources` should be > 0 if search keys are configured

### 8. Thin product produces low confidence

Test with a minimal site:

```bash
curl -s -X POST http://localhost:8000/api/v1/snapshots \
  -H 'Content-Type: application/json' \
  -d '{"url":"https://example.com"}' | jq .
```

After job completes, verify:
- Most fields have "low" confidence
- Source counts are 0 or very low
- This is the correct behavior — low data → low confidence

### 9. OpenAPI schema updated

Visit http://localhost:8000/docs and verify:
- `POST /snapshots` shows `SnapshotJobResponse` as response
- `GET /snapshots/{snapshot_id}` shows `ProductSnapshotRead`
- `GET /snapshots/jobs/{job_id}` shows `SnapshotJobStatus`
- All schemas have proper types and descriptions

### 10. Three real URLs complete successfully

Test all three URLs end-to-end:

1. **Linear.app** — Content-rich SaaS, should have good extraction
2. **Vanta.com** — Security/compliance product, should work well
3. **example.com** — Thin content, should produce mostly low confidence

All three should:
- Complete within 60 seconds
- Produce a valid ProductSnapshot row
- Have confidence labels derived from actual signals (not hardcoded)

---

## What "done" looks like

All ten checkpoints green. The key property to verify:

**Confidence scales with actual evidence.** A well-documented product (Linear) should produce higher confidence than a minimal site (example.com). If both produce the same confidence, the triangulation isn't working.

When all ten pass: **commit, tag `step-2-complete`, and move to Step 3**.

---

## Troubleshooting

### Job stays "queued" forever
- Is the RQ worker running? Check `OBJC_DISABLE_INITIALIZE_FORK_SAFETY=YES uv run rq worker --url redis://localhost:6379`
- Is Redis running? Check `docker compose ps`

### ScrapeError on homepage
- Is the URL valid and reachable?
- Does the site block headless browsers? Try adding realistic headers.

### No search results
- Are `TAVILY_API_KEY` or `EXA_API_KEY` set in `.env`?
- Pipeline works without them but produces low confidence.

### LLM errors
- Is `ANTHROPIC_API_KEY` or `OPENAI_API_KEY` set?
- Check rate limits on your account.

### All fields have low confidence
- This is expected for thin products!
- For rich products, check that search is returning results and LLM extraction is working.

---

# Step 3 — ICP Pipeline Verification

This section documents the verification protocol for Step 3. Run through it after implementing the ICP generation pipeline.

## What Step 3 ships

- **ICP Pipeline** — A four-stage pipeline that transforms a `ProductSnapshot` into evidence-anchored customer segments:
  1. **Cluster** — Extract public search snippets, embed them, and form candidate quote clusters
  2. **Synthesize** — Use DSPy to convert clusters into named segment drafts with cited drivers
  3. **Anchor** — Attach the 2-3 closest source quotes as `Evidence` rows
  4. **Score** — Use `triangulate()` with source diversity, quote coherence, and segment distinctness

- **API Endpoints**:
  - `POST /snapshots/{snapshot_id}/icps` — Enqueues ICP generation, returns 202 with `job_id`
  - `GET /snapshots/{snapshot_id}/segments` — Returns generated segments with nested evidence
  - `GET /icps/jobs/{job_id}` — Returns RQ job status

- **Tests**:
  - Pure ICP pipeline unit tests, including thin and adversarial fixtures
  - API tests for the new segment endpoints
  - Integration tests that read Step 2 snapshot IDs from `tests/fixtures/snapshot_uuids.json`

## Prerequisites

```bash
cd apps/api
uv sync --group dev --group scrape --group llm
uv run alembic upgrade head
```

At least one LLM API key must be configured:

```bash
ANTHROPIC_API_KEY=sk-ant-...
# or
OPENAI_API_KEY=sk-...
```

`OPENAI_API_KEY` enables real 1536-dim embeddings. If OpenAI embeddings fail, or if only `ANTHROPIC_API_KEY` is configured, Step 3 falls back to deterministic hash embeddings so the pipeline remains runnable. Treat hash clustering as a development fallback; it is lower quality than semantic embeddings.

## ✅ Verification checklist

### 1. Unit tests pass

```bash
cd apps/api
uv run pytest -v -m "not integration"
```

Expected: all non-integration tests pass. Pay special attention to:

- `test_openai_embedding_error_falls_back_to_hash` — OpenAI key path remains runnable if embedding calls fail
- `test_anthropic_key_uses_hash_embeddings` — Anthropic-only path remains runnable
- `test_adversarial_all_similar_produces_low_stability` — near-duplicate segments cannot become overconfident
- `test_high_evidence_low_coherence_produces_low` — geometric mean still kills confidence when one signal is weak

### 2. Mypy and Ruff are clean

```bash
cd apps/api
uv run mypy app
uv run ruff check .
```

Expected: no errors.

### 3. POST /snapshots/{snapshot_id}/icps returns 202

```bash
curl -s -X POST http://localhost:8000/api/v1/snapshots/{snapshot_id}/icps | jq .
```

Expected:

```json
{
  "job_id": "some-uuid",
  "status_url": "http://localhost:8000/api/v1/icps/jobs/some-uuid"
}
```

### 4. Job status endpoint works

```bash
curl -s http://localhost:8000/api/v1/icps/jobs/{job_id} | jq .
```

Expected: `{"status": "queued"}`, `{"status": "started"}`, or `{"status": "finished", "segment_ids": ["..."]}`.

### 5. Segments endpoint returns anchored evidence

```bash
curl -s http://localhost:8000/api/v1/snapshots/{snapshot_id}/segments | jq .
```

Expected:

- 1-5 segment objects
- each segment has `name`, `job_to_be_done`, `share_pct`, `confidence`, and `evidence`
- evidence quotes are real snippets from source URLs, not generated text

### 6. Linear snapshot produces usable segments

Use the Linear snapshot ID from `apps/api/tests/fixtures/snapshot_uuids.json`.

Expected:

- at least 3 segments
- at least one Medium-or-High confidence segment
- at least one Medium-or-High segment has 2+ evidence anchors from distinct domains

### 7. example.com remains Low confidence

Use the example.com snapshot ID from `apps/api/tests/fixtures/snapshot_uuids.json`.

Expected:

- 1-3 segments when thin public signal exists
- all segments are Low confidence
- the UI should render these as Hypothesis-style segments

### 8. Vanta completes and quality is documented

Use the Vanta snapshot ID from `apps/api/tests/fixtures/snapshot_uuids.json`.

Expected:

- pipeline completes without crashing
- segment count and confidence distribution are documented below
- if the segments are low quality, preserve that as a finding instead of tuning confidence upward

### 9. Integration tests pass when live prerequisites exist

```bash
cd apps/api
uv run pytest -v -m integration
```

## Known limitations (accepted tradeoffs):
- Filter may be aggressive on products with high SEO/comparison content
  (e.g., Linear: 3/15 snippets survive). This is honest — thin signal
  after filtering is correct behavior, not a bug.
- LLM may produce identical names for distinct clusters when the 
  underlying evidence themes are similar. Segments are distinct by 
  evidence and embedding; name collision is cosmetic. Step 5 UI 
  should display descriptor alongside name.

If the database was recreated, regenerate Step 2 snapshots and update `tests/fixtures/snapshot_uuids.json`.

### Step 4 cascade deletion risk

ICP reruns delete and reinsert all `Segment` rows through the idempotency transaction in `score.py`. `SimulationCell` rows reference `segments.id` with `ondelete="CASCADE"`, so if Step 4 creates simulation cells and ICP is rerun afterward, all simulation cells for that snapshot will be deleted.

Step 4 must choose one policy before simulations ship: prevent ICP reruns after simulation cells exist and return 409 for that `snapshot_id`, or delete and regenerate simulation cells as part of the ICP rerun workflow.

## Verification results

Record local Step 3 verification here:

- Non-integration tests: `uv run pytest -m "not integration" -q` passed — 131 passed, 11 deselected, 11 DSPy deprecation warnings.
- `uv run mypy app`: passed — no issues in 28 source files.
- `uv run ruff check .`: passed.
- Integration check: `uv run pytest -m integration -q` did not complete cleanly in this local environment. ICP integration could not connect to Postgres at `localhost:5432`; snapshot live integration reached OpenAI but failed with insufficient quota. Re-run after local services and API billing are available.
- Linear: not live-verified in this run because integration was blocked by local Postgres/API quota.
- example.com: not live-verified in this run because integration was blocked by local Postgres/API quota.
- Vanta: not live-verified in this run because integration was blocked by local Postgres/API quota.

## Step 4 verification (simulation pipeline)

37 tests pass (32 unit + 5 integration).
mypy strict: clean. ruff: clean.

Live DB check (Linear, 2 pricing options):
  - 6 cells produced (3 segments × 2 options) ✓
  - Price +20%: mixed/negative sentiment ✓
  - devil_advocate populated on all cells ✓
  - example.com: 6 cells, all Low confidence ✓

Known schema deviation from Step 4 spec:
  - Column is option_letter not option_label (Claude Code used model field name)
  - churn_probability stored as range_low/range_high not float
  Update Step 5 frontend to read these actual column names.