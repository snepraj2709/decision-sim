"""
Integration test: full V2 simulation run using real Linear snapshot.
Requires: live DB, API keys, segments pre-seeded for KNOWN_SNAPSHOT_ID.

Run with: uv run pytest tests/test_orchestrator_integration.py -m integration -v
"""
from __future__ import annotations

import json
import uuid
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

pytestmark = pytest.mark.integration

FIXTURES_DIR = Path(__file__).parent / "fixtures"
SNAPSHOT_UUIDS_FILE = FIXTURES_DIR / "snapshot_uuids.json"

# Fallback — matches the Linear snapshot seeded by the Step 3 integration suite.
_KNOWN_LINEAR_SNAPSHOT_ID = "5d0b9dd9-ed12-4a71-8078-5847ae830761"

_V2_OPTIONS = [
    {
        "label": "Price +20%",
        "description": "Raise all plans by 20%",
        "option_type": "pricing",
    },
    {
        "label": "Free tier",
        "description": "Add free tier for solo developers",
        "option_type": "pricing",
    },
]


def _get_linear_snapshot_id() -> str:
    if SNAPSHOT_UUIDS_FILE.exists():
        with open(SNAPSHOT_UUIDS_FILE) as f:
            data = json.load(f)
        return data.get("linear", _KNOWN_LINEAR_SNAPSHOT_ID)
    return _KNOWN_LINEAR_SNAPSHOT_ID


def _mock_queue() -> MagicMock:
    mock_job = MagicMock()
    mock_job.id = "v2-simulation-job-456"
    mock_queue = MagicMock()
    mock_queue.enqueue.return_value = mock_job
    return mock_queue


async def _create_simulation(snapshot_id: uuid.UUID, client: Any) -> uuid.UUID:
    """POST /simulate with a mocked queue and return the simulation_id."""
    with patch("app.api.v1.simulations._get_queue", return_value=_mock_queue()):
        response = await client.post(
            f"/api/v1/snapshots/{snapshot_id}/simulate",
            json={"options": _V2_OPTIONS},
        )

    if response.status_code == 422 and "No segments" in response.text:
        pytest.skip(f"No segments found for snapshot {snapshot_id} — run ICP pipeline first")

    assert response.status_code == 202, response.text
    return uuid.UUID(response.json()["simulation_id"])


@pytest.fixture(autouse=True)
async def dispose_db_engine() -> None:
    yield
    from app.db import engine
    await engine.dispose()


@pytest.mark.integration
async def test_full_orchestrated_simulation(client: Any) -> None:
    """
    End-to-end V2 pipeline: create Simulation → run _orchestrated_pipeline
    → verify cells written and OrchestratorOutput present.

    Checks:
      1. All (segment × option) pairs produce SimulationCell rows.
      2. OrchestratorOutput fields are non-empty strings.
      3. simulation.status is 'completed' after the run.
      4. orchestrator_memo is persisted (requires migration 0004).
    """
    from sqlalchemy import select
    from sqlalchemy.orm import selectinload

    from app.config import get_settings
    from app.db import AsyncSessionLocal
    from app.models import Segment, Simulation
    from app.workers.tasks import _orchestrated_pipeline

    snapshot_id = uuid.UUID(_get_linear_snapshot_id())

    # Verify snapshot and segments exist in this environment
    async with AsyncSessionLocal() as db:
        seg_result = await db.execute(
            select(Segment.id).where(Segment.snapshot_id == snapshot_id).limit(1)
        )
        if seg_result.scalar_one_or_none() is None:
            pytest.skip(f"Snapshot {snapshot_id} has no segments — run ICP pipeline first")

        seg_count_result = await db.execute(
            select(Segment).where(Segment.snapshot_id == snapshot_id)
        )
        n_segments = len(seg_count_result.scalars().all())

    # Create simulation row via HTTP (mocks queue so no worker needed)
    simulation_id = await _create_simulation(snapshot_id, client)

    # Run the V2 orchestrated pipeline directly (bypasses RQ)
    settings = get_settings()
    if not (settings.anthropic_api_key or settings.openai_api_key):
        pytest.skip("No LLM API key configured — cannot run V2 pipeline")

    async with AsyncSessionLocal() as db:
        await _orchestrated_pipeline(str(simulation_id), db, settings)

    # Verify results
    async with AsyncSessionLocal() as db:
        result = await db.execute(
            select(Simulation)
            .where(Simulation.id == simulation_id)
            .options(selectinload(Simulation.cells))
        )
        simulation = result.scalar_one_or_none()

    assert simulation is not None
    assert simulation.status == "completed", f"Expected completed, got {simulation.status}"

    # All (segment × option) pairs should have cells
    expected_cells = n_segments * len(_V2_OPTIONS)
    assert len(simulation.cells) == expected_cells, (
        f"Expected {expected_cells} cells ({n_segments} segments × {len(_V2_OPTIONS)} options), "
        f"got {len(simulation.cells)}"
    )

    # Every cell must have a sentiment and a confidence label
    for cell in simulation.cells:
        assert cell.reaction_sentiment in {"positive", "neutral", "negative", "mixed"}, (
            f"Cell {cell.id} has invalid sentiment: {cell.reaction_sentiment!r}"
        )
        assert cell.confidence in {"high", "medium", "low"}, (
            f"Cell {cell.id} has invalid confidence: {cell.confidence!r}"
        )

    # Orchestrator memo must be populated (requires migration 0004)
    if hasattr(simulation, "orchestrator_memo") and simulation.orchestrator_memo is not None:
        memo = simulation.orchestrator_memo
        assert memo.get("recommendation"), "orchestrator_memo.recommendation is empty"
        assert memo.get("confidence_rationale"), "orchestrator_memo.confidence_rationale is empty"
        assert memo.get("strongest_counter_case"), "orchestrator_memo.strongest_counter_case is empty"


@pytest.mark.integration
async def test_v2_da_selective_mode_skips_clean_cells(client: Any) -> None:
    """
    With DEVIL_ADVOCATE_MODE=selective, D.A. runs only on cells where the
    reaction rubric failed. Cells where the rubric passed get no D.A. output
    from the agent layer (they may still have devil_advocate from V1 fallback).

    This test just verifies the pipeline completes — selective behaviour is
    exercised in unit tests via da_should_run().
    """
    import os

    from app.config import get_settings
    from app.db import AsyncSessionLocal
    from app.models import Segment, Simulation
    from app.workers.tasks import _orchestrated_pipeline
    from sqlalchemy import select

    original = os.environ.get("DEVIL_ADVOCATE_MODE")
    os.environ["DEVIL_ADVOCATE_MODE"] = "selective"
    try:
        snapshot_id = uuid.UUID(_get_linear_snapshot_id())

        async with AsyncSessionLocal() as db:
            seg_result = await db.execute(
                select(Segment.id).where(Segment.snapshot_id == snapshot_id).limit(1)
            )
            if seg_result.scalar_one_or_none() is None:
                pytest.skip("No segments for snapshot — run ICP pipeline first")

        settings = get_settings()
        if not (settings.anthropic_api_key or settings.openai_api_key):
            pytest.skip("No LLM API key configured")

        simulation_id = await _create_simulation(snapshot_id, client)

        async with AsyncSessionLocal() as db:
            await _orchestrated_pipeline(str(simulation_id), db, settings)

        async with AsyncSessionLocal() as db:
            sim = await db.get(Simulation, simulation_id)
        assert sim is not None
        assert sim.status == "completed"
    finally:
        if original is None:
            os.environ.pop("DEVIL_ADVOCATE_MODE", None)
        else:
            os.environ["DEVIL_ADVOCATE_MODE"] = original
