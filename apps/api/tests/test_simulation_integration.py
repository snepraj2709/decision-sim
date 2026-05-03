"""Integration tests for simulation pipeline — uses real Step 2/3 snapshots.

These tests are marked with @pytest.mark.integration and are skipped in
normal runs. Run with: pytest -m integration
"""

from __future__ import annotations

import json
import uuid
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import pytest
from httpx import AsyncClient

pytestmark = pytest.mark.integration

FIXTURES_DIR = Path(__file__).parent / "fixtures"
SNAPSHOT_UUIDS_FILE = FIXTURES_DIR / "snapshot_uuids.json"

VALID_SENTIMENTS = {"positive", "neutral", "negative", "mixed"}
LINEAR_OPTIONS = [
    {
        "label": "Price +20%",
        "description": "Raise all plans by 20%",
        "option_type": "pricing",
    },
    {
        "label": "Free tier",
        "description": "Add free tier for solo devs",
        "option_type": "pricing",
    },
]
EXAMPLE_COM_OPTIONS = [
    {
        "label": "SSL badge",
        "description": "Show SSL cert prominently",
        "option_type": "feature",
    },
    {
        "label": "Price cut 30%",
        "description": "Cut registration price 30%",
        "option_type": "pricing",
    },
]


def _get_snapshot_uuids() -> dict[str, str]:
    if SNAPSHOT_UUIDS_FILE.exists():
        with open(SNAPSHOT_UUIDS_FILE) as f:
            return json.load(f)

    return {
        "linear": "5d0b9dd9-ed12-4a71-8078-5847ae830761",
        "example": "eedab62a-cf99-467f-95b3-4f30afa8ff69",
        "vanta": "41d56777-4dca-4321-8d0a-77f5266135f7",
    }


@pytest.fixture
def snapshot_uuids() -> dict[str, str]:
    return _get_snapshot_uuids()


@pytest.fixture
def linear_snapshot_id(snapshot_uuids: dict[str, str]) -> uuid.UUID:
    return uuid.UUID(snapshot_uuids["linear"])


@pytest.fixture
def example_com_snapshot_id(snapshot_uuids: dict[str, str]) -> uuid.UUID:
    return uuid.UUID(snapshot_uuids["example"])


@pytest.fixture
def has_llm_key() -> bool:
    from app.config import get_settings

    settings = get_settings()
    return bool(settings.anthropic_api_key or settings.openai_api_key)


@pytest.fixture(autouse=True)
async def dispose_db_engine_between_tests() -> None:
    yield
    from app.db import engine

    await engine.dispose()


def _mock_queue() -> MagicMock:
    mock_job = MagicMock()
    mock_job.id = "simulation-job-123"
    mock_queue = MagicMock()
    mock_queue.enqueue.return_value = mock_job
    return mock_queue


async def _assert_snapshot_has_segments(snapshot_id: uuid.UUID) -> None:
    from sqlalchemy import select

    from app.db import AsyncSessionLocal
    from app.models import ProductSnapshot, Segment

    async with AsyncSessionLocal() as db:
        snapshot = await db.get(ProductSnapshot, snapshot_id)
        if snapshot is None:
            pytest.skip(f"Snapshot {snapshot_id} not found in database")

        result = await db.execute(
            select(Segment.id).where(Segment.snapshot_id == snapshot_id).limit(1)
        )
        if result.scalar_one_or_none() is None:
            pytest.skip(f"No segments found for snapshot {snapshot_id}")


async def _post_and_run_simulation(
    client: AsyncClient,
    snapshot_id: uuid.UUID,
    options: list[dict[str, str]],
) -> dict[str, Any]:
    from sqlalchemy import select
    from sqlalchemy.orm import selectinload

    from app.db import AsyncSessionLocal
    from app.models import Simulation
    from app.pipelines.simulation import run_simulation as run_simulation_pipeline

    mock_queue = _mock_queue()
    with patch("app.api.v1.simulations._get_queue", return_value=mock_queue):
        response = await client.post(
            f"/api/v1/snapshots/{snapshot_id}/simulate",
            json={"options": options},
        )

    if response.status_code == 422 and "No segments found" in response.text:
        pytest.skip(f"No segments found for snapshot {snapshot_id}")

    assert response.status_code == 202, response.text
    simulation_id = uuid.UUID(response.json()["simulation_id"])

    async with AsyncSessionLocal() as db:
        await run_simulation_pipeline(simulation_id, db)
        result = await db.execute(
            select(Simulation)
            .where(Simulation.id == simulation_id)
            .options(selectinload(Simulation.cells))
        )
        simulation = result.scalar_one()

        cells = [
            {
                "segment_id": cell.segment_id,
                "option_letter": cell.option_letter,
                "confidence": cell.confidence,
                "reaction_sentiment": cell.reaction_sentiment,
                "adoption_probability": cell.adoption_probability,
                "range_low": cell.range_low,
                "range_high": cell.range_high,
            }
            for cell in simulation.cells
        ]

        return {"id": simulation.id, "cells": cells}


def _assert_cells_have_valid_probabilities(cells: list[dict[str, Any]]) -> None:
    assert all(cell["reaction_sentiment"] in VALID_SENTIMENTS for cell in cells)
    assert all(
        cell["adoption_probability"] is not None
        and 0.0 <= cell["adoption_probability"] <= 1.0
        for cell in cells
    )
    assert all(
        0.0 <= cell["range_low"] / 100 <= 1.0
        and 0.0 <= cell["range_high"] / 100 <= 1.0
        and cell["range_low"] <= cell["range_high"]
        for cell in cells
    )


@pytest.mark.asyncio
async def test_linear_simulation_produces_cells_for_all_segments(
    client: AsyncClient,
    linear_snapshot_id: uuid.UUID,
    has_llm_key: bool,
) -> None:
    if not has_llm_key:
        pytest.skip("No LLM API key configured")

    await _assert_snapshot_has_segments(linear_snapshot_id)

    simulation = await _post_and_run_simulation(
        client,
        linear_snapshot_id,
        LINEAR_OPTIONS,
    )
    cells = simulation["cells"]

    assert len(cells) == 6
    _assert_cells_have_valid_probabilities(cells)


@pytest.mark.asyncio
async def test_pricing_option_skews_toward_negative_sentiment(
    client: AsyncClient,
    linear_snapshot_id: uuid.UUID,
    has_llm_key: bool,
) -> None:
    if not has_llm_key:
        pytest.skip("No LLM API key configured")

    await _assert_snapshot_has_segments(linear_snapshot_id)

    simulation = await _post_and_run_simulation(
        client,
        linear_snapshot_id,
        LINEAR_OPTIONS,
    )
    price_cells = [
        cell
        for cell in simulation["cells"]
        if cell["option_letter"] == "Price +20%"
    ]

    assert price_cells
    assert any(
        cell["reaction_sentiment"] in {"negative", "mixed"}
        for cell in price_cells
    )


@pytest.mark.asyncio
async def test_example_com_all_low_segments_produce_low_cells(
    client: AsyncClient,
    example_com_snapshot_id: uuid.UUID,
    has_llm_key: bool,
) -> None:
    if not has_llm_key:
        pytest.skip("No LLM API key configured")

    await _assert_snapshot_has_segments(example_com_snapshot_id)

    simulation = await _post_and_run_simulation(
        client,
        example_com_snapshot_id,
        EXAMPLE_COM_OPTIONS,
    )

    assert simulation["cells"]
    assert all(cell["confidence"] == "low" for cell in simulation["cells"])


@pytest.mark.asyncio
async def test_icp_rerun_blocked_when_cells_exist(
    client: AsyncClient,
    linear_snapshot_id: uuid.UUID,
    has_llm_key: bool,
) -> None:
    if not has_llm_key:
        pytest.skip("No LLM API key configured")

    await _assert_snapshot_has_segments(linear_snapshot_id)
    await _post_and_run_simulation(client, linear_snapshot_id, LINEAR_OPTIONS)

    mock_queue = _mock_queue()
    with patch("app.api.v1.segments._get_queue", return_value=mock_queue):
        response = await client.post(f"/api/v1/snapshots/{linear_snapshot_id}/icps")

    assert response.status_code == 409
    assert "simulation cells already exist" in response.json()["detail"].lower()
    mock_queue.enqueue.assert_not_called()


@pytest.mark.asyncio
async def test_simulation_idempotent_same_options(
    client: AsyncClient,
    linear_snapshot_id: uuid.UUID,
    has_llm_key: bool,
) -> None:
    if not has_llm_key:
        pytest.skip("No LLM API key configured")

    await _assert_snapshot_has_segments(linear_snapshot_id)

    first = await _post_and_run_simulation(client, linear_snapshot_id, LINEAR_OPTIONS)
    second = await _post_and_run_simulation(client, linear_snapshot_id, LINEAR_OPTIONS)

    first_cells = sorted(
        first["cells"],
        key=lambda cell: (str(cell["segment_id"]), cell["option_letter"]),
    )
    second_cells = sorted(
        second["cells"],
        key=lambda cell: (str(cell["segment_id"]), cell["option_letter"]),
    )

    assert len(first_cells) == 6
    assert len(second_cells) == 6
    assert [cell["reaction_sentiment"] for cell in first_cells] == [
        cell["reaction_sentiment"] for cell in second_cells
    ]
    assert [cell["confidence"] for cell in first_cells] == [
        cell["confidence"] for cell in second_cells
    ]
    assert first["id"] != second["id"]
