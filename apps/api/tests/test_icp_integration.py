"""Integration tests for ICP pipeline — uses real Step 2 snapshots.

These tests are marked with @pytest.mark.integration and are skipped in
normal runs. Run with: pytest -m integration

These tests require:
  - Existing snapshots in the database (from Step 2 verification)
  - ANTHROPIC_API_KEY or OPENAI_API_KEY (for synthesis)
  - OPENAI_API_KEY (for embeddings)

Tests verify:
  - Pipeline completes for real snapshots
  - Segment count and confidence distribution is reasonable
  - Linear produces at least one Medium-or-High segment
  - example.com produces all-Low segments (hypothesis state)
"""

from __future__ import annotations

import json
import uuid
from pathlib import Path

import pytest

# Skip all tests in this module if not running integration tests
pytestmark = pytest.mark.integration

# Fixture file path for snapshot UUIDs
FIXTURES_DIR = Path(__file__).parent / "fixtures"
SNAPSHOT_UUIDS_FILE = FIXTURES_DIR / "snapshot_uuids.json"


def _get_snapshot_uuids() -> dict[str, str]:
    """Load snapshot UUIDs from fixture file.

    If the file doesn't exist, return default UUIDs from Step 2 verification.
    """
    if SNAPSHOT_UUIDS_FILE.exists():
        with open(SNAPSHOT_UUIDS_FILE) as f:
            return json.load(f)

    # Default UUIDs from Step 2 verification
    return {
        "linear": "5d0b9dd9-ed12-4a71-8078-5847ae830761",
        "example": "eedab62a-cf99-467f-95b3-4f30afa8ff69",
        "vanta": "41d56777-4dca-4321-8d0a-77f5266135f7",
    }


@pytest.fixture
def snapshot_uuids() -> dict[str, str]:
    """Get snapshot UUIDs for testing."""
    return _get_snapshot_uuids()


@pytest.fixture
def has_llm_key() -> bool:
    """Check if an LLM API key is available."""
    from app.config import get_settings

    settings = get_settings()
    return bool(settings.anthropic_api_key or settings.openai_api_key)


@pytest.fixture
def has_embedding_key() -> bool:
    """Check if an embedding API key is available (OpenAI)."""
    from app.config import get_settings

    settings = get_settings()
    return bool(settings.openai_api_key)


class TestICPPipelineIntegration:
    """Integration tests against real Step 2 snapshots."""

    @pytest.mark.asyncio
    async def test_linear_snapshot_produces_segments(
        self, snapshot_uuids: dict[str, str], has_llm_key: bool, has_embedding_key: bool
    ) -> None:
        """Linear.app snapshot should produce multiple segments with good confidence."""
        if not has_llm_key:
            pytest.skip("No LLM API key configured")
        if not has_embedding_key:
            pytest.skip("No embedding API key (OPENAI_API_KEY) configured")

        from sqlalchemy import select

        from app.db import AsyncSessionLocal
        from app.models import ProductSnapshot, Segment
        from app.pipelines.icp import run_icp_pipeline

        snapshot_id = uuid.UUID(snapshot_uuids["linear"])

        async with AsyncSessionLocal() as db:
            # Verify snapshot exists
            stmt = select(ProductSnapshot).where(ProductSnapshot.id == snapshot_id)
            result = await db.execute(stmt)
            snapshot = result.scalar_one_or_none()

            if snapshot is None:
                pytest.skip(f"Snapshot {snapshot_id} not found in database")

            # Run ICP pipeline
            segment_ids = await run_icp_pipeline(snapshot_id, db)

            # Should produce at least 3 segments
            assert len(segment_ids) >= 3, f"Expected at least 3 segments, got {len(segment_ids)}"

            # Fetch segments and check confidences
            segment_stmt = select(Segment).where(Segment.snapshot_id == snapshot_id)
            segment_result = await db.execute(segment_stmt)
            segments = segment_result.scalars().all()

            confidence_counts = {"high": 0, "medium": 0, "low": 0}
            for segment in segments:
                confidence_counts[segment.confidence] += 1

            # Linear should have at least one Medium or High confidence segment
            assert confidence_counts["high"] + confidence_counts["medium"] >= 1, (
                f"Expected at least one Medium/High segment, got: {confidence_counts}"
            )

    @pytest.mark.asyncio
    async def test_example_com_snapshot_produces_low_confidence(
        self, snapshot_uuids: dict[str, str], has_llm_key: bool, has_embedding_key: bool
    ) -> None:
        """example.com snapshot should produce all-Low confidence segments."""
        if not has_llm_key:
            pytest.skip("No LLM API key configured")
        if not has_embedding_key:
            pytest.skip("No embedding API key (OPENAI_API_KEY) configured")

        from sqlalchemy import select

        from app.db import AsyncSessionLocal
        from app.models import ProductSnapshot, Segment
        from app.pipelines.icp import run_icp_pipeline

        snapshot_id = uuid.UUID(snapshot_uuids["example"])

        async with AsyncSessionLocal() as db:
            # Verify snapshot exists
            stmt = select(ProductSnapshot).where(ProductSnapshot.id == snapshot_id)
            result = await db.execute(stmt)
            snapshot = result.scalar_one_or_none()

            if snapshot is None:
                pytest.skip(f"Snapshot {snapshot_id} not found in database")

            # Run ICP pipeline
            segment_ids = await run_icp_pipeline(snapshot_id, db)

            # Should produce 1-3 segments (thin data)
            assert 1 <= len(segment_ids) <= 3, f"Expected 1-3 segments, got {len(segment_ids)}"

            # Fetch segments
            segment_stmt = select(Segment).where(Segment.snapshot_id == snapshot_id)
            segment_result = await db.execute(segment_stmt)
            segments = segment_result.scalars().all()

            # All should be Low confidence (hypothesis state)
            for segment in segments:
                assert segment.confidence == "low", (
                    f"Expected low confidence, got {segment.confidence} for '{segment.name}'"
                )

    @pytest.mark.asyncio
    async def test_vanta_snapshot_completes(
        self, snapshot_uuids: dict[str, str], has_llm_key: bool, has_embedding_key: bool
    ) -> None:
        """Vanta.com snapshot should complete without errors.

        Vanta's segment quality is documented in the runbook. The main
        assertion here is that the pipeline doesn't crash.
        """
        if not has_llm_key:
            pytest.skip("No LLM API key configured")
        if not has_embedding_key:
            pytest.skip("No embedding API key (OPENAI_API_KEY) configured")

        from sqlalchemy import select

        from app.db import AsyncSessionLocal
        from app.models import ProductSnapshot, Segment
        from app.pipelines.icp import run_icp_pipeline

        snapshot_id = uuid.UUID(snapshot_uuids["vanta"])

        async with AsyncSessionLocal() as db:
            # Verify snapshot exists
            stmt = select(ProductSnapshot).where(ProductSnapshot.id == snapshot_id)
            result = await db.execute(stmt)
            snapshot = result.scalar_one_or_none()

            if snapshot is None:
                pytest.skip(f"Snapshot {snapshot_id} not found in database")

            # Run ICP pipeline
            segment_ids = await run_icp_pipeline(snapshot_id, db)

            # Should produce some segments
            assert len(segment_ids) >= 1, "Expected at least 1 segment"

            # Document what we got
            segment_stmt = select(Segment).where(Segment.snapshot_id == snapshot_id)
            segment_result = await db.execute(segment_stmt)
            segments = segment_result.scalars().all()

            confidence_counts = {"high": 0, "medium": 0, "low": 0}
            for segment in segments:
                confidence_counts[segment.confidence] += 1

            # Log results for runbook documentation
            print(f"\nVanta segments: {len(segments)}")
            print(f"Confidence distribution: {confidence_counts}")
            for segment in segments:
                print(f"  - {segment.name}: {segment.confidence}")


class TestIdempotency:
    """Test that running the pipeline twice replaces segments."""

    @pytest.mark.asyncio
    async def test_pipeline_is_idempotent(
        self, snapshot_uuids: dict[str, str], has_llm_key: bool, has_embedding_key: bool
    ) -> None:
        """Running pipeline twice should replace, not duplicate, segments."""
        if not has_llm_key:
            pytest.skip("No LLM API key configured")
        if not has_embedding_key:
            pytest.skip("No embedding API key (OPENAI_API_KEY) configured")

        from sqlalchemy import select

        from app.db import AsyncSessionLocal
        from app.models import ProductSnapshot, Segment
        from app.pipelines.icp import run_icp_pipeline

        snapshot_id = uuid.UUID(snapshot_uuids["linear"])

        async with AsyncSessionLocal() as db:
            # Verify snapshot exists
            stmt = select(ProductSnapshot).where(ProductSnapshot.id == snapshot_id)
            result = await db.execute(stmt)
            snapshot = result.scalar_one_or_none()

            if snapshot is None:
                pytest.skip(f"Snapshot {snapshot_id} not found in database")

            # Run pipeline twice
            first_ids = await run_icp_pipeline(snapshot_id, db)
            second_ids = await run_icp_pipeline(snapshot_id, db)

            # IDs should be different (new rows created)
            assert set(first_ids) != set(second_ids), "Expected new segment IDs on re-run"

            # Only second batch should exist in DB
            segment_stmt = select(Segment.id).where(Segment.snapshot_id == snapshot_id)
            segment_result = await db.execute(segment_stmt)
            current_ids = {row[0] for row in segment_result.fetchall()}

            assert current_ids == set(second_ids), "Expected only second batch of segments to exist"
