# dsim-api

FastAPI backend for the Decision Simulation Engine.

## Layout

```
app/
├── main.py              FastAPI app factory + lifespan
├── config.py            Settings (env-driven, Pydantic)
├── db.py                Async SQLAlchemy engine + session
├── models.py            ORM models (single file until they outgrow it)
├── schemas.py           Pydantic request/response schemas
├── core/
│   └── confidence.py    Confidence math (triangulation, banding)
├── api/
│   ├── deps.py          FastAPI deps (db session, etc.)
│   └── v1/
│       ├── health.py    GET /health
│       └── snapshots.py POST /snapshots (Step 2 will fill this in)
├── pipelines/           Heart of the engine — Steps 2–4 implement these
│   ├── snapshot.py      URL → ProductCard (Step 2)
│   ├── icp.py           ProductCard → Segments (Step 3)
│   └── simulation.py    Segments × Options → Reactions (Step 4)
└── workers/
    └── tasks.py         RQ task definitions
```

## Run

```bash
uv sync
uv run alembic upgrade head
uv run fastapi dev app/main.py
```

Then `http://localhost:8000/docs` for the OpenAPI UI.

## Why pipelines are stubs in Step 1

The pipeline modules raise `NotImplementedError` with informative messages. This is deliberate:

1. The contracts (function signatures, types, docstrings) are locked in.
2. The frontend can't accidentally render fake data.
3. Steps 2–4 are about *implementing* these contracts, not designing them.

## Confidence: how the math works

See `app/core/confidence.py`. The triangulation logic combines three independent signals (LLM agreement with base rates, evidence anchor density, ICP construct stability) into a single `Confidence` literal. This module is unit-tested even in Step 1 because it's load-bearing.
