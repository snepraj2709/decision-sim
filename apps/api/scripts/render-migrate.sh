#!/usr/bin/env bash
set -euo pipefail

source scripts/render-env.sh

uv run alembic upgrade head
