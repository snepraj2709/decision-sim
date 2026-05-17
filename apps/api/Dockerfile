FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    PATH="/app/.venv/bin:$PATH"

WORKDIR /app

RUN apt-get update \
    && apt-get install -y --no-install-recommends bash ca-certificates curl \
    && rm -rf /var/lib/apt/lists/*

COPY apps/api/pyproject.toml apps/api/uv.lock ./

RUN python -m pip install --no-cache-dir --upgrade pip uv \
    && uv sync --frozen --no-dev --group scrape --group llm --no-install-project \
    && uv run playwright install --with-deps chromium

COPY apps/api/ ./

RUN uv sync --frozen --no-dev --group scrape --group llm

CMD ["bash", "scripts/render-start.sh"]
