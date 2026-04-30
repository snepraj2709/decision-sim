# Decision Simulation Engine

> A flight simulator for product decisions. Paste a product URL → understand the product → generate customer segments → simulate how each segment reacts to 2–3 options you're considering → get a defensible decision artifact. With confidence scores at every step.

**This is the Step 1 scaffolding** — repo + frontend bones + backend bones + database + worker queue + CI. The actual pipelines (scrape, ICP, simulation) are scaffolded as `NotImplementedError` stubs with full type contracts. They're deliberately empty until Step 2.

---

## What's in this repo

```
decision-sim/
├── apps/
│   ├── web/        Next.js 15 + React 19 + Tailwind 3 + TypeScript
│   └── api/        FastAPI + SQLAlchemy 2 + Alembic + Pydantic v2
├── packages/
│   └── ui-tokens/  Shared CSS design tokens (single source of truth)
├── docker-compose.yml   Postgres 16 + pgvector + Redis 7
├── .github/workflows/   Lint + type-check + test on PRs
└── turbo.json           Monorepo task orchestration
```

## Build phases

| Phase | Status | What |
|---|---|---|
| **1. Scaffolding** | ✅ This commit | Monorepo, Next.js, FastAPI, Postgres+pgvector, Redis+RQ, CI, design tokens |
| **2. Snapshot pipeline** | ⏳ Next | URL → Playwright + trafilatura → Tavily/Exa → DSPy → Product Card with per-field confidence |
| **3. ICP generation** | ⏳ | Product Card → 4–5 evidence-anchored segments with confidence scores |
| **4. Cognitive model** | ⏳ | Generative reasoning trace + base-rate sanity check + confidence triangulation |
| **5. Frontend wiring** | ⏳ | Port the design's 4 screens (dashboard, composer, memo, flight log) to live data |

## Quickstart

### Prerequisites

- Node 20+ and pnpm 9+
- Python 3.12+ and [uv](https://docs.astral.sh/uv/)
- Docker (for Postgres + Redis)

### 1. Clone and install

```bash
cp .env.example .env
pnpm install                # installs web app + workspace tools
cd apps/api && uv sync && cd ../..   # installs api + workers
```

### 2. Start the data layer

```bash
docker compose up -d        # Postgres on :5432, Redis on :6379
```

### 3. Run database migrations

```bash
cd apps/api
uv run alembic upgrade head
cd ../..
```

### 4. Run the apps

In separate terminals:

```bash
# Terminal 1 — backend
cd apps/api && uv run fastapi dev app/main.py

# Terminal 2 — worker (no work yet, just connected)
cd apps/api && uv run rq worker --url redis://localhost:6379

# Terminal 3 — frontend
pnpm --filter web dev
```

You should see:

- `http://localhost:8000/docs` — FastAPI Swagger UI with health endpoint
- `http://localhost:3000` — Next.js page rendering the design tokens and primitives at all three confidence states

If those two work, Step 1 is done correctly.

## What "production-grade" means here

For Step 1 specifically:

- **Strict typing everywhere.** TypeScript strict mode in web, mypy + Pydantic v2 in api. No `any`, no untyped dicts in API contracts.
- **Migrations, not auto-create.** Alembic from day one. No `Base.metadata.create_all()` in production paths.
- **Confidence is a first-class type.** `Literal["high", "medium", "low"]` shared between Pydantic schemas and TypeScript types. Drift between them breaks CI.
- **No fake implementations.** Pipelines that aren't built yet raise `NotImplementedError` with informative messages. Frontend cannot accidentally render against fake data.
- **CI gates the contract.** Type-check and lint both apps on every PR. Tests run for the api.

## Architecture notes

### Why pgvector in Step 1

Embedding-based retrieval shows up in Step 2 (matching scraped content to ICP archetypes), Step 3 (clustering review quotes into segments), and Step 4 (analogous-case retrieval for the base-rate layer). Setting it up now means Step 2 doesn't have to ship a database migration on day one.

### Why RQ over Celery

Snapshot scraping and simulation runs are 30s–5min jobs. RQ's simplicity matches the workload; Celery's broker complexity is wasted at this scale. Revisit if we need scheduled jobs or multi-queue routing.

### Why design tokens in a shared package

The frontend (Step 5) and any future docs site / Storybook need the same source of truth for colors, fonts, and confidence states. Putting `tokens.css` in `packages/ui-tokens/` and importing it from the Next.js global stylesheet keeps drift impossible.

## License

UNLICENSED — private until further notice.
