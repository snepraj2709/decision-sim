# Deployment

This repo is configured for a free-tier split deployment:

- Frontend: Vercel, rooted at `apps/web`
- Backend: Render Blueprint from `render.yaml`
- Backend data: Render Postgres plus Render Key Value

## Vercel

Import `snepraj2709/decision-sim` and set the project root directory to:

```text
apps/web
```

Use the default install command and the committed build command:

```text
pnpm build
```

Set these production environment variables after the Render API URL exists:

```text
NEXT_PUBLIC_API_BASE_URL=https://decision-sim-api.onrender.com
NEXT_PUBLIC_API_URL=https://decision-sim-api.onrender.com
```

Replace the hostname with the actual Render service URL if Render assigns a
different slug.

## Render

Create a new Blueprint from `snepraj2709/decision-sim`. Render will read
`render.yaml` from the repo root and create:

- `decision-sim-api` web service on the free plan
- `decision-sim-db` Postgres database on the free plan
- `decision-sim-redis` Key Value instance on the free plan

The API service runs FastAPI and the RQ worker in the same free web service.
This is intentional because Render free plans do not include free background
workers.

Set or confirm these API environment variables in Render:

```text
WEB_BASE_URL=https://your-vercel-domain.vercel.app
API_BASE_URL=https://decision-sim-api.onrender.com
CORS_ORIGINS=https://your-vercel-domain.vercel.app
```

For live non-demo simulations, also add at least one LLM key and one search key:

```text
ANTHROPIC_API_KEY=
OPENAI_API_KEY=
TAVILY_API_KEY=
EXA_API_KEY=
```

The Blueprint derives SQLAlchemy driver URLs from Render's Postgres connection
string at runtime, so you do not need to manually create `DATABASE_URL` or
`DATABASE_SYNC_URL` unless you choose not to use the Blueprint-managed database.
