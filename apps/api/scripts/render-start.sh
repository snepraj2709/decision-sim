#!/usr/bin/env bash
set -euo pipefail

source scripts/render-env.sh

uv run alembic upgrade head

uv run rq worker --url "$REDIS_URL" &
worker_pid=$!

uv run uvicorn app.main:app --host 0.0.0.0 --port "${PORT:-8000}" &
api_pid=$!

shutdown() {
  kill "$api_pid" "$worker_pid" 2>/dev/null || true
  wait "$api_pid" "$worker_pid" 2>/dev/null || true
}

trap shutdown SIGINT SIGTERM

wait -n "$api_pid" "$worker_pid"
status=$?
shutdown
exit "$status"
