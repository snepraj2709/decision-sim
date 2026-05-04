"""Integration tests for the calibration loop.

Marked @pytest.mark.integration — requires a live DB + Step 2/3/4 data.
Run with: pytest -m integration
"""

from __future__ import annotations

import json
import uuid
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from httpx import AsyncClient

pytestmark = pytest.mark.integration

FIXTURES_DIR = Path(__file__).parent / "fixtures"
SNAPSHOT_UUIDS_FILE = FIXTURES_DIR / "snapshot_uuids.json"

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


def _get_snapshot_uuids() -> dict[str, str]:
    if SNAPSHOT_UUIDS_FILE.exists():
        with open(SNAPSHOT_UUIDS_FILE) as f:
            return json.load(f)
    return {
        "linear": "5d0b9dd9-ed12-4a71-8078-5847ae830761",
        "example": "eedab62a-cf99-467f-95b3-4f30afa8ff69",
    }


@pytest.fixture
def linear_snapshot_id() -> uuid.UUID:
    return uuid.UUID(_get_snapshot_uuids()["linear"])


@pytest.fixture(autouse=True)
async def dispose_db_engine_between_tests() -> None:
    yield
    from app.db import engine
    await engine.dispose()


def _mock_queue() -> MagicMock:
    mock_job = MagicMock()
    mock_job.id = "calib-job-123"
    mock_queue = MagicMock()
    mock_queue.enqueue.return_value = mock_job
    return mock_queue


async def _create_simulation(
    client: AsyncClient,
    snapshot_id: uuid.UUID,
    options: list[dict[str, str]],
) -> uuid.UUID:
    """Create and run a simulation, return its ID."""
    from sqlalchemy import select
    from sqlalchemy.orm import selectinload

    from app.db import AsyncSessionLocal
    from app.models import Segment, Simulation
    from app.pipelines.simulation import run_simulation as run_simulation_pipeline

    async with AsyncSessionLocal() as db:
        result = await db.execute(
            select(Segment.id).where(Segment.snapshot_id == snapshot_id).limit(1)
        )
        if result.scalar_one_or_none() is None:
            pytest.skip(f"No segments found for snapshot {snapshot_id}")

    mock_queue = _mock_queue()
    with patch("app.api.v1.simulations._get_queue", return_value=mock_queue):
        response = await client.post(
            f"/api/v1/snapshots/{snapshot_id}/simulate",
            json={"options": options},
        )

    if response.status_code == 422 and "No segments" in response.text:
        pytest.skip(f"No segments for snapshot {snapshot_id}")

    assert response.status_code == 202, response.text
    simulation_id = uuid.UUID(response.json()["simulation_id"])

    async with AsyncSessionLocal() as db:
        await run_simulation_pipeline(simulation_id, db)

    return simulation_id


@pytest.mark.asyncio
async def test_outcome_report_persists_and_recomputes(
    client: AsyncClient,
    linear_snapshot_id: uuid.UUID,
) -> None:
    """Submit an outcome → OutcomeReport row exists, CalibrationRate updated."""
    from sqlalchemy import select

    from app.db import AsyncSessionLocal
    from app.models import CalibrationRate, OutcomeReport

    has_llm_key = False
    try:
        from app.config import get_settings
        s = get_settings()
        has_llm_key = bool(s.anthropic_api_key or s.openai_api_key)
    except Exception:
        pass

    if not has_llm_key:
        pytest.skip("No LLM API key configured")

    simulation_id = await _create_simulation(client, linear_snapshot_id, LINEAR_OPTIONS)

    response = await client.post(
        f"/api/v1/simulations/{simulation_id}/outcome",
        json={
            "option_letter": "Price +20%",
            "reported_sentiment": "negative",
            "notes": "Customers pushed back hard on pricing.",
        },
    )
    assert response.status_code == 201, response.text
    data = response.json()
    assert data["reported_sentiment"] == "negative"
    assert data["simulation_id"] == str(simulation_id)

    async with AsyncSessionLocal() as db:
        report = (
            await db.execute(
                select(OutcomeReport).where(
                    OutcomeReport.simulation_id == simulation_id
                )
            )
        ).scalar_one_or_none()
        assert report is not None
        assert report.reported_sentiment == "negative"

        rate = (
            await db.execute(
                select(CalibrationRate).where(
                    CalibrationRate.option_type == "pricing",
                    CalibrationRate.sentiment == "negative",
                )
            )
        ).scalar_one_or_none()
        assert rate is not None
        assert rate.sample_count >= 1


@pytest.mark.asyncio
async def test_rates_endpoint_returns_all_option_types(client: AsyncClient) -> None:
    """GET /calibration/rates returns 5 option_types with 4 sentiments each.

    Seeded rows have sample_count=0 and rates matching BASE_RATES.
    """
    from app.pipelines.simulation.score import BASE_RATES

    response = await client.get("/api/v1/calibration/rates")
    assert response.status_code == 200, response.text
    data = response.json()["rates"]

    expected_types = {"pricing", "feature", "copy", "bundling", "onboarding"}
    expected_sentiments = {"positive", "neutral", "negative", "mixed"}

    assert set(data.keys()) == expected_types

    for option_type in expected_types:
        assert set(data[option_type].keys()) == expected_sentiments
        for sentiment in expected_sentiments:
            cell = data[option_type][sentiment]
            assert "rate" in cell
            assert "sample_count" in cell
            # Seeded rows start at sample_count=0 and match BASE_RATES.
            if cell["sample_count"] == 0:
                expected_rate = BASE_RATES[option_type][sentiment]
                assert abs(cell["rate"] - expected_rate) < 1e-6, (
                    f"{option_type}/{sentiment}: expected {expected_rate}, got {cell['rate']}"
                )


@pytest.mark.asyncio
async def test_duplicate_outcome_returns_409(
    client: AsyncClient,
    linear_snapshot_id: uuid.UUID,
) -> None:
    """POSTing two outcomes for same simulation + option_letter returns 409."""
    has_llm_key = False
    try:
        from app.config import get_settings
        s = get_settings()
        has_llm_key = bool(s.anthropic_api_key or s.openai_api_key)
    except Exception:
        pass

    if not has_llm_key:
        pytest.skip("No LLM API key configured")

    simulation_id = await _create_simulation(client, linear_snapshot_id, LINEAR_OPTIONS)

    payload = {
        "option_letter": "Price +20%",
        "reported_sentiment": "negative",
    }
    first = await client.post(f"/api/v1/simulations/{simulation_id}/outcome", json=payload)
    assert first.status_code == 201, first.text

    second = await client.post(f"/api/v1/simulations/{simulation_id}/outcome", json=payload)
    assert second.status_code == 409, second.text
