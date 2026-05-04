"""Add outcome_reports and calibration_rates tables; seed base rates.

Revision ID: 0003_calibration_tables
Revises: 0002_simulation_cell_columns
Create Date: 2026-05-04
"""

from collections.abc import Sequence
import uuid

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0003_calibration_tables"
down_revision: str | None = "0002_simulation_cell_columns"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None

# Mirrors BASE_RATES from score.py — these become the prior (sample_count=0).
_SEED_RATES: dict[str, dict[str, float]] = {
    "pricing": {"positive": 0.10, "neutral": 0.25, "negative": 0.55, "mixed": 0.10},
    "feature": {"positive": 0.45, "neutral": 0.30, "negative": 0.15, "mixed": 0.10},
    "copy": {"positive": 0.20, "neutral": 0.50, "negative": 0.15, "mixed": 0.15},
    "bundling": {"positive": 0.25, "neutral": 0.35, "negative": 0.25, "mixed": 0.15},
    "onboarding": {"positive": 0.35, "neutral": 0.40, "negative": 0.15, "mixed": 0.10},
}


def upgrade() -> None:
    op.create_table(
        "outcome_reports",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "simulation_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("simulations.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("option_letter", sa.String(64), nullable=False),
        sa.Column("reported_sentiment", sa.String(16), nullable=False),
        sa.Column(
            "reported_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column("notes", sa.String(500), nullable=True),
    )
    op.create_index(
        "ix_outcome_reports_simulation_id",
        "outcome_reports",
        ["simulation_id"],
    )
    op.create_unique_constraint(
        "uq_outcome_reports_simulation_option",
        "outcome_reports",
        ["simulation_id", "option_letter"],
    )

    op.create_table(
        "calibration_rates",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("option_type", sa.String(32), nullable=False),
        sa.Column("sentiment", sa.String(16), nullable=False),
        sa.Column("rate", sa.Float(), nullable=False),
        sa.Column("sample_count", sa.Integer(), server_default="0", nullable=False),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )
    op.create_unique_constraint(
        "uq_calibration_rates_type_sentiment",
        "calibration_rates",
        ["option_type", "sentiment"],
    )

    # Seed from hardcoded priors — sample_count=0 signals "prior, not observed".
    calibration_rates = sa.table(
        "calibration_rates",
        sa.column("id", postgresql.UUID(as_uuid=True)),
        sa.column("option_type", sa.String),
        sa.column("sentiment", sa.String),
        sa.column("rate", sa.Float),
        sa.column("sample_count", sa.Integer),
    )
    rows = [
        {
            "id": uuid.uuid4(),
            "option_type": option_type,
            "sentiment": sentiment,
            "rate": rate,
            "sample_count": 0,
        }
        for option_type, sentiments in _SEED_RATES.items()
        for sentiment, rate in sentiments.items()
    ]
    op.bulk_insert(calibration_rates, rows)


def downgrade() -> None:
    op.drop_table("outcome_reports")
    op.drop_table("calibration_rates")
