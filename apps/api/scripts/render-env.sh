#!/usr/bin/env bash
set -euo pipefail

if [[ -n "${DATABASE_CONNECTION_STRING:-}" ]]; then
  if [[ -z "${DATABASE_URL:-}" ]]; then
    export DATABASE_URL="${DATABASE_CONNECTION_STRING/#postgresql:\/\//postgresql+asyncpg://}"
  fi

  if [[ -z "${DATABASE_SYNC_URL:-}" ]]; then
    export DATABASE_SYNC_URL="${DATABASE_CONNECTION_STRING/#postgresql:\/\//postgresql+psycopg://}"
  fi
fi

: "${DATABASE_URL:?DATABASE_URL or DATABASE_CONNECTION_STRING must be set}"
: "${DATABASE_SYNC_URL:?DATABASE_SYNC_URL or DATABASE_CONNECTION_STRING must be set}"
: "${REDIS_URL:?REDIS_URL must be set}"
