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

from collections import Counter
import json
import math
import re
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


@pytest.fixture(autouse=True)
async def dispose_db_engine_between_tests() -> None:
    """Avoid asyncpg pooled connections crossing pytest event loops."""
    yield
    from app.db import engine

    await engine.dispose()


@pytest.fixture
def linear_snapshot_id(snapshot_uuids: dict[str, str]) -> uuid.UUID:
    """Linear snapshot UUID."""
    return uuid.UUID(snapshot_uuids["linear"])


@pytest.fixture
def vanta_snapshot_id(snapshot_uuids: dict[str, str]) -> uuid.UUID:
    """Vanta snapshot UUID."""
    return uuid.UUID(snapshot_uuids["vanta"])


@pytest.fixture
def example_com_snapshot_id(snapshot_uuids: dict[str, str]) -> uuid.UUID:
    """example.com snapshot UUID."""
    return uuid.UUID(snapshot_uuids["example"])


@pytest.fixture
def snapshot_ids(snapshot_uuids: dict[str, str]) -> list[uuid.UUID]:
    """All real Step 2 snapshot UUIDs."""
    return [
        uuid.UUID(snapshot_uuids["linear"]),
        uuid.UUID(snapshot_uuids["example"]),
        uuid.UUID(snapshot_uuids["vanta"]),
    ]


def _cosine_similarity(a: list[float], b: list[float]) -> float:
    """Compute cosine similarity for integration assertions."""
    if len(a) == 0 or len(b) == 0 or len(a) != len(b):
        return 0.0
    dot = sum(x * y for x, y in zip(a, b, strict=True))
    norm_a = math.sqrt(sum(x * x for x in a))
    norm_b = math.sqrt(sum(x * x for x in b))
    if norm_a < 1e-9 or norm_b < 1e-9:
        return 0.0
    return dot / (norm_a * norm_b)


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
    async def test_no_evidence_reuse_across_segments(
        self,
        linear_snapshot_id: uuid.UUID,
        has_llm_key: bool,
        has_embedding_key: bool,
    ) -> None:
        """No two Linear segments share an identical evidence quote."""
        if not has_llm_key:
            pytest.skip("No LLM API key configured")
        if not has_embedding_key:
            pytest.skip("No embedding API key (OPENAI_API_KEY) configured")

        from sqlalchemy import select

        from app.db import AsyncSessionLocal
        from app.models import Evidence, ProductSnapshot, Segment
        from app.pipelines.icp import run_icp_pipeline

        async with AsyncSessionLocal() as db:
            snapshot = await db.get(ProductSnapshot, linear_snapshot_id)
            if snapshot is None:
                pytest.skip(f"Snapshot {linear_snapshot_id} not found in database")

            await run_icp_pipeline(linear_snapshot_id, db)
            evidence_result = await db.execute(
                select(Evidence.quote)
                .join(Segment, Evidence.segment_id == Segment.id)
                .where(Segment.snapshot_id == linear_snapshot_id)
            )
            quotes = [quote for quote in evidence_result.scalars().all()]

        quote_counts = Counter(quotes)
        reused = [quote for quote, count in quote_counts.items() if count > 1]
        assert not reused, f"Evidence reused across segments: {reused}"

    @pytest.mark.asyncio
    async def test_no_unknown_segments(
        self,
        snapshot_ids: list[uuid.UUID],
        has_llm_key: bool,
        has_embedding_key: bool,
    ) -> None:
        """No persisted segment has a name in INVALID_SEGMENT_NAMES."""
        if not has_llm_key:
            pytest.skip("No LLM API key configured")
        if not has_embedding_key:
            pytest.skip("No embedding API key (OPENAI_API_KEY) configured")

        from sqlalchemy import select

        from app.db import AsyncSessionLocal
        from app.models import ProductSnapshot, Segment
        from app.pipelines.icp import run_icp_pipeline
        from app.pipelines.icp.score import INVALID_SEGMENT_NAMES

        async with AsyncSessionLocal() as db:
            for snapshot_id in snapshot_ids:
                snapshot = await db.get(ProductSnapshot, snapshot_id)
                if snapshot is None:
                    pytest.skip(f"Snapshot {snapshot_id} not found in database")

                await run_icp_pipeline(snapshot_id, db)
                result = await db.execute(
                    select(Segment.name).where(Segment.snapshot_id == snapshot_id)
                )
                names = result.scalars().all()

                invalid = [
                    name
                    for name in names
                    if name.strip().lower() in INVALID_SEGMENT_NAMES
                ]
                assert not invalid, f"Invalid segment names persisted: {invalid}"

    @pytest.mark.asyncio
    async def test_no_glassdoor_or_employee_evidence(
        self,
        vanta_snapshot_id: uuid.UUID,
        has_llm_key: bool,
        has_embedding_key: bool,
    ) -> None:
        """Vanta evidence must not contain Glassdoor or employee review content."""
        if not has_llm_key:
            pytest.skip("No LLM API key configured")
        if not has_embedding_key:
            pytest.skip("No embedding API key (OPENAI_API_KEY) configured")

        from sqlalchemy import select

        from app.db import AsyncSessionLocal
        from app.models import Evidence, ProductSnapshot, Segment
        from app.pipelines.icp import run_icp_pipeline
        from app.pipelines.icp._filters import NON_CUSTOMER_PATTERNS

        employee_patterns = [
            pattern
            for pattern in NON_CUSTOMER_PATTERNS
            if "glassdoor" in pattern.pattern or "teamblind" in pattern.pattern
        ]

        async with AsyncSessionLocal() as db:
            snapshot = await db.get(ProductSnapshot, vanta_snapshot_id)
            if snapshot is None:
                pytest.skip(f"Snapshot {vanta_snapshot_id} not found in database")

            await run_icp_pipeline(vanta_snapshot_id, db)
            evidence_result = await db.execute(
                select(Evidence.quote)
                .join(Segment, Evidence.segment_id == Segment.id)
                .where(Segment.snapshot_id == vanta_snapshot_id)
            )
            quotes = evidence_result.scalars().all()

        for quote in quotes:
            for pattern in employee_patterns:
                assert not pattern.search(quote), (
                    f"Employee-review evidence leaked into Vanta ICPs: {quote[:100]}"
                )

    @pytest.mark.asyncio
    async def test_linear_has_no_near_duplicate_segments(
        self,
        linear_snapshot_id: uuid.UUID,
        has_llm_key: bool,
        has_embedding_key: bool,
    ) -> None:
        """Linear segments must be semantically distinct."""
        if not has_llm_key:
            pytest.skip("No LLM API key configured")
        if not has_embedding_key:
            pytest.skip("No embedding API key (OPENAI_API_KEY) configured")

        from sqlalchemy import select

        from app.db import AsyncSessionLocal
        from app.models import ProductSnapshot, Segment
        from app.pipelines.icp import run_icp_pipeline

        async with AsyncSessionLocal() as db:
            snapshot = await db.get(ProductSnapshot, linear_snapshot_id)
            if snapshot is None:
                pytest.skip(f"Snapshot {linear_snapshot_id} not found in database")

            await run_icp_pipeline(linear_snapshot_id, db)
            result = await db.execute(
                select(Segment).where(Segment.snapshot_id == linear_snapshot_id)
            )
            segments = result.scalars().all()

        embeddings = [
            (segment.name, segment.embedding)
            for segment in segments
            if segment.embedding is not None
        ]
        for i, (left_name, left_embedding) in enumerate(embeddings):
            for right_name, right_embedding in embeddings[i + 1:]:
                similarity = _cosine_similarity(left_embedding, right_embedding)
                assert similarity < 0.85, (
                    f"Linear segments are near-duplicates: {left_name!r}, "
                    f"{right_name!r}, similarity={similarity:.3f}"
                )

    @pytest.mark.asyncio
    async def test_hypothesis_segment_names_are_clean(
        self,
        example_com_snapshot_id: uuid.UUID,
        has_llm_key: bool,
        has_embedding_key: bool,
    ) -> None:
        """Hypothesis-mode segment names must not contain URL artifacts."""
        if not has_llm_key:
            pytest.skip("No LLM API key configured")
        if not has_embedding_key:
            pytest.skip("No embedding API key (OPENAI_API_KEY) configured")

        from sqlalchemy import select

        from app.db import AsyncSessionLocal
        from app.models import ProductSnapshot, Segment
        from app.pipelines.icp import run_icp_pipeline

        bad_name_pattern = re.compile(
            r"http|https|avatar|&[a-z]+;|!\[[^\]]*\]\(",
            re.IGNORECASE,
        )

        async with AsyncSessionLocal() as db:
            snapshot = await db.get(ProductSnapshot, example_com_snapshot_id)
            if snapshot is None:
                pytest.skip(f"Snapshot {example_com_snapshot_id} not found in database")

            await run_icp_pipeline(example_com_snapshot_id, db)
            result = await db.execute(
                select(Segment.name).where(Segment.snapshot_id == example_com_snapshot_id)
            )
            names = result.scalars().all()

        for name in names:
            assert not bad_name_pattern.search(name), (
                f"Hypothesis segment name contains URL artifact: {name!r}"
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
