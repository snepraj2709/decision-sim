"""Add orchestrator_memo JSON column to simulations table.

Revision ID: 0004_add_orchestrator_memo_to_simulation
Revises: 0003_calibration_tables
Create Date: 2026-05-13
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0004_add_orchestrator_memo_to_simulation"
down_revision: str | None = "0003_calibration_tables"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "simulations",
        sa.Column("orchestrator_memo", postgresql.JSON(astext_type=sa.Text()), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("simulations", "orchestrator_memo")
