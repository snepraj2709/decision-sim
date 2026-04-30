"""ORM models — the data shape of the engine.

All models live here in Step 1. Once any one model has more than ~150 lines,
or once relationships span 3+ tables non-trivially, split into a `models/`
package. Premature splitting hurts readability more than file length does.

Tables:
  - products       — a tracked product (URL = primary identity)
  - product_snapshots — versioned engine output: "what we think this product is"
  - segments       — generated customer segments per snapshot
  - evidence       — anchors (quotes / sources) supporting a segment or fact
  - simulations    — a comparison run (Options × Segments → Reactions)
  - simulation_cells — per-(segment, option) reaction with confidence

Embeddings live alongside the row that owns them (segment.embedding,
evidence.embedding) using pgvector. We store 1536-dim vectors by default
(OpenAI text-embedding-3-small / ada-002 sized) — change in migration if
we settle on a different embedder.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Literal

from pgvector.sqlalchemy import Vector
from sqlalchemy import (
    JSON,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
    func,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base

# Confidence type — mirrors the frontend's `Confidence` TypeScript type.
# Kept as a plain string column with a CHECK constraint added in migration.
ConfidenceLiteral = Literal["high", "medium", "low"]

EMBEDDING_DIM = 1536


# ─── Product ────────────────────────────────────────────────────────────────
class Product(Base):
    __tablename__ = "products"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    url: Mapped[str] = mapped_column(String(1024), unique=True, nullable=False)
    display_name: Mapped[str | None] = mapped_column(String(256))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    snapshots: Mapped[list[ProductSnapshot]] = relationship(
        back_populates="product",
        cascade="all, delete-orphan",
        order_by="ProductSnapshot.created_at.desc()",
    )


# ─── ProductSnapshot ────────────────────────────────────────────────────────
class ProductSnapshot(Base):
    """Versioned engine output: what the engine thinks the product is.

    Every run of the snapshot pipeline (Step 2) creates a new row. The latest
    one is the "current" snapshot; older ones are kept for audit + diffing.
    """

    __tablename__ = "product_snapshots"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    product_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("products.id", ondelete="CASCADE"), nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    # Structured fields — each with a confidence and a count of independent sources
    category: Mapped[str | None] = mapped_column(Text)
    category_confidence: Mapped[str | None] = mapped_column(String(8))
    category_sources: Mapped[int] = mapped_column(Integer, default=0)

    value_prop: Mapped[str | None] = mapped_column(Text)
    value_prop_confidence: Mapped[str | None] = mapped_column(String(8))
    value_prop_sources: Mapped[int] = mapped_column(Integer, default=0)

    pricing: Mapped[str | None] = mapped_column(Text)
    pricing_confidence: Mapped[str | None] = mapped_column(String(8))
    pricing_sources: Mapped[int] = mapped_column(Integer, default=0)

    features: Mapped[str | None] = mapped_column(Text)
    features_confidence: Mapped[str | None] = mapped_column(String(8))
    features_sources: Mapped[int] = mapped_column(Integer, default=0)

    audience: Mapped[str | None] = mapped_column(Text)
    audience_confidence: Mapped[str | None] = mapped_column(String(8))
    audience_sources: Mapped[int] = mapped_column(Integer, default=0)

    competitors: Mapped[str | None] = mapped_column(Text)
    competitors_confidence: Mapped[str | None] = mapped_column(String(8))
    competitors_sources: Mapped[int] = mapped_column(Integer, default=0)

    # Raw scrape + search artifacts kept for debugging / re-running
    raw_scrape: Mapped[dict | None] = mapped_column(JSON)
    raw_search_results: Mapped[dict | None] = mapped_column(JSON)

    product: Mapped[Product] = relationship(back_populates="snapshots")
    segments: Mapped[list[Segment]] = relationship(
        back_populates="snapshot", cascade="all, delete-orphan"
    )


# ─── Segment ────────────────────────────────────────────────────────────────
class Segment(Base):
    """A generated customer segment for a given snapshot.

    Each snapshot typically yields 4–5 segments. Segments belong to a snapshot,
    not directly to a product, because changing the product card invalidates
    the segments — they need to be regenerated.
    """

    __tablename__ = "segments"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    snapshot_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("product_snapshots.id", ondelete="CASCADE"),
        nullable=False,
    )
    name: Mapped[str] = mapped_column(String(256), nullable=False)
    descriptor: Mapped[str | None] = mapped_column(Text)
    job_to_be_done: Mapped[str | None] = mapped_column(Text)
    share_pct: Mapped[int | None] = mapped_column(Integer)  # 0..100, est. % of base
    confidence: Mapped[str] = mapped_column(String(8), nullable=False)
    drivers: Mapped[list[dict] | None] = mapped_column(JSON)  # [{label, weight}, ...]
    leaves: Mapped[str | None] = mapped_column(Text)  # what triggers churn

    embedding: Mapped[list[float] | None] = mapped_column(Vector(EMBEDDING_DIM))

    snapshot: Mapped[ProductSnapshot] = relationship(back_populates="segments")
    evidence: Mapped[list[Evidence]] = relationship(
        back_populates="segment", cascade="all, delete-orphan"
    )


# ─── Evidence ───────────────────────────────────────────────────────────────
class Evidence(Base):
    """An anchor — a real quote / source that grounds a segment or fact.

    `kind` is one of: 'reddit', 'g2', 'twitter', 'capterra', 'review', 'press', 'other'.
    Kept loosely typed — the frontend renders a different icon per kind, but the
    set may grow.
    """

    __tablename__ = "evidence"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    segment_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("segments.id", ondelete="CASCADE")
    )
    quote: Mapped[str] = mapped_column(Text, nullable=False)
    source: Mapped[str] = mapped_column(String(512), nullable=False)
    source_url: Mapped[str | None] = mapped_column(String(1024))
    kind: Mapped[str] = mapped_column(String(32), default="other", nullable=False)
    captured_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    embedding: Mapped[list[float] | None] = mapped_column(Vector(EMBEDDING_DIM))

    segment: Mapped[Segment | None] = relationship(back_populates="evidence")


# ─── Simulation ─────────────────────────────────────────────────────────────
class Simulation(Base):
    """A comparison run. Holds the options Maya defined + per-cell reactions."""

    __tablename__ = "simulations"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    snapshot_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("product_snapshots.id", ondelete="CASCADE"),
        nullable=False,
    )
    decision_type: Mapped[str] = mapped_column(String(64), nullable=False)
    # decision_type ∈ {'pricing', 'copy', 'feature', 'bundle', 'onboarding'}
    options: Mapped[list[dict]] = mapped_column(JSON, nullable=False)
    # [{letter: 'A', title: '...', sub: '...'}, ...]
    status: Mapped[str] = mapped_column(String(32), default="pending", nullable=False)
    # status ∈ {'pending', 'running', 'completed', 'failed'}
    overall_confidence: Mapped[str | None] = mapped_column(String(8))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    cells: Mapped[list[SimulationCell]] = relationship(
        back_populates="simulation", cascade="all, delete-orphan"
    )


class SimulationCell(Base):
    """One cell in the dashboard grid: (segment, option) → reaction."""

    __tablename__ = "simulation_cells"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    simulation_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("simulations.id", ondelete="CASCADE"), nullable=False
    )
    segment_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("segments.id", ondelete="CASCADE"), nullable=False
    )
    option_letter: Mapped[str] = mapped_column(String(2), nullable=False)  # 'A', 'B', 'C'
    range_low: Mapped[int] = mapped_column(Integer, nullable=False)   # churn % low end
    range_high: Mapped[int] = mapped_column(Integer, nullable=False)  # churn % high end
    confidence: Mapped[str] = mapped_column(String(8), nullable=False)
    reasoning_trace: Mapped[str | None] = mapped_column(Text)
    top_concern: Mapped[str | None] = mapped_column(String(256))
    invalidating_experiment: Mapped[str | None] = mapped_column(Text)

    simulation: Mapped[Simulation] = relationship(back_populates="cells")
