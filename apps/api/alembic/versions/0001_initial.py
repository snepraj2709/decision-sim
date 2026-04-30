"""Initial schema — products, snapshots, segments, evidence, simulations.

Revision ID: 0001_initial
Revises:
Create Date: 2026-04-30
"""

from collections.abc import Sequence
from typing import Union

import sqlalchemy as sa
from alembic import op
from pgvector.sqlalchemy import Vector
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "0001_initial"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

EMBEDDING_DIM = 1536

CONFIDENCE_CHECK = "value IN ('high', 'medium', 'low')"


def upgrade() -> None:
    # ── Extensions ──────────────────────────────────────────────────────
    op.execute('CREATE EXTENSION IF NOT EXISTS "uuid-ossp"')
    op.execute('CREATE EXTENSION IF NOT EXISTS "vector"')

    # ── products ────────────────────────────────────────────────────────
    op.create_table(
        "products",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("url", sa.String(1024), nullable=False, unique=True),
        sa.Column("display_name", sa.String(256)),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_products_url", "products", ["url"], unique=True)

    # ── product_snapshots ───────────────────────────────────────────────
    op.create_table(
        "product_snapshots",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("product_id", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("products.id", ondelete="CASCADE"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("category", sa.Text),
        sa.Column("category_confidence", sa.String(8)),
        sa.Column("category_sources", sa.Integer, server_default="0", nullable=False),
        sa.Column("value_prop", sa.Text),
        sa.Column("value_prop_confidence", sa.String(8)),
        sa.Column("value_prop_sources", sa.Integer, server_default="0", nullable=False),
        sa.Column("pricing", sa.Text),
        sa.Column("pricing_confidence", sa.String(8)),
        sa.Column("pricing_sources", sa.Integer, server_default="0", nullable=False),
        sa.Column("features", sa.Text),
        sa.Column("features_confidence", sa.String(8)),
        sa.Column("features_sources", sa.Integer, server_default="0", nullable=False),
        sa.Column("audience", sa.Text),
        sa.Column("audience_confidence", sa.String(8)),
        sa.Column("audience_sources", sa.Integer, server_default="0", nullable=False),
        sa.Column("competitors", sa.Text),
        sa.Column("competitors_confidence", sa.String(8)),
        sa.Column("competitors_sources", sa.Integer, server_default="0", nullable=False),
        sa.Column("raw_scrape", postgresql.JSONB),
        sa.Column("raw_search_results", postgresql.JSONB),
    )
    op.create_index("ix_product_snapshots_product_id", "product_snapshots", ["product_id"])

    # CHECK constraints — enforce confidence values at the DB layer.
    # Mirrors the Pydantic `Confidence` Literal and the frontend type.
    for col in [
        "category_confidence", "value_prop_confidence", "pricing_confidence",
        "features_confidence", "audience_confidence", "competitors_confidence",
    ]:
        op.create_check_constraint(
            f"ck_snapshots_{col}",
            "product_snapshots",
            f"{col} IS NULL OR {col} IN ('high', 'medium', 'low')",
        )

    # ── segments ────────────────────────────────────────────────────────
    op.create_table(
        "segments",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("snapshot_id", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("product_snapshots.id", ondelete="CASCADE"), nullable=False),
        sa.Column("name", sa.String(256), nullable=False),
        sa.Column("descriptor", sa.Text),
        sa.Column("job_to_be_done", sa.Text),
        sa.Column("share_pct", sa.Integer),
        sa.Column("confidence", sa.String(8), nullable=False),
        sa.Column("drivers", postgresql.JSONB),
        sa.Column("leaves", sa.Text),
        sa.Column("embedding", Vector(EMBEDDING_DIM)),
    )
    op.create_index("ix_segments_snapshot_id", "segments", ["snapshot_id"])
    op.create_check_constraint(
        "ck_segments_confidence", "segments",
        "confidence IN ('high', 'medium', 'low')",
    )
    op.create_check_constraint(
        "ck_segments_share_pct", "segments",
        "share_pct IS NULL OR (share_pct >= 0 AND share_pct <= 100)",
    )

    # ── evidence ────────────────────────────────────────────────────────
    op.create_table(
        "evidence",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("segment_id", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("segments.id", ondelete="CASCADE")),
        sa.Column("quote", sa.Text, nullable=False),
        sa.Column("source", sa.String(512), nullable=False),
        sa.Column("source_url", sa.String(1024)),
        sa.Column("kind", sa.String(32), server_default="other", nullable=False),
        sa.Column("captured_at", sa.DateTime(timezone=True)),
        sa.Column("embedding", Vector(EMBEDDING_DIM)),
    )
    op.create_index("ix_evidence_segment_id", "evidence", ["segment_id"])

    # ── simulations ─────────────────────────────────────────────────────
    op.create_table(
        "simulations",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("snapshot_id", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("product_snapshots.id", ondelete="CASCADE"), nullable=False),
        sa.Column("decision_type", sa.String(64), nullable=False),
        sa.Column("options", postgresql.JSONB, nullable=False),
        sa.Column("status", sa.String(32), server_default="pending", nullable=False),
        sa.Column("overall_confidence", sa.String(8)),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True)),
    )
    op.create_index("ix_simulations_snapshot_id", "simulations", ["snapshot_id"])
    op.create_check_constraint(
        "ck_simulations_status", "simulations",
        "status IN ('pending', 'running', 'completed', 'failed')",
    )
    op.create_check_constraint(
        "ck_simulations_decision_type", "simulations",
        "decision_type IN ('pricing', 'copy', 'feature', 'bundle', 'onboarding')",
    )
    op.create_check_constraint(
        "ck_simulations_overall_confidence", "simulations",
        "overall_confidence IS NULL OR overall_confidence IN ('high', 'medium', 'low')",
    )

    # ── simulation_cells ────────────────────────────────────────────────
    op.create_table(
        "simulation_cells",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("simulation_id", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("simulations.id", ondelete="CASCADE"), nullable=False),
        sa.Column("segment_id", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("segments.id", ondelete="CASCADE"), nullable=False),
        sa.Column("option_letter", sa.String(2), nullable=False),
        sa.Column("range_low", sa.Integer, nullable=False),
        sa.Column("range_high", sa.Integer, nullable=False),
        sa.Column("confidence", sa.String(8), nullable=False),
        sa.Column("reasoning_trace", sa.Text),
        sa.Column("top_concern", sa.String(256)),
        sa.Column("invalidating_experiment", sa.Text),
    )
    op.create_index(
        "ix_simulation_cells_sim_seg_opt",
        "simulation_cells",
        ["simulation_id", "segment_id", "option_letter"],
        unique=True,
    )
    op.create_check_constraint(
        "ck_cells_confidence", "simulation_cells",
        "confidence IN ('high', 'medium', 'low')",
    )
    op.create_check_constraint(
        "ck_cells_range", "simulation_cells",
        "range_low >= 0 AND range_high >= range_low AND range_high <= 100",
    )


def downgrade() -> None:
    op.drop_table("simulation_cells")
    op.drop_table("simulations")
    op.drop_table("evidence")
    op.drop_table("segments")
    op.drop_table("product_snapshots")
    op.drop_table("products")
    # We leave the extensions in place — they may be used by other DBs in
    # the same cluster, and dropping them is not idempotent.
