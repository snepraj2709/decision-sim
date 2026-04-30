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
