"""Add Step 4 columns to simulation_cells; widen option_letter.

Revision ID: 0002_simulation_cell_columns
Revises: 0001_initial
Create Date: 2026-05-03
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0002_simulation_cell_columns"
down_revision: str | None = "0001_initial"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None


def upgrade() -> None:
    op.alter_column(
        "simulation_cells",
        "option_letter",
        existing_type=sa.String(2),
        type_=sa.String(64),
        existing_nullable=False,
    )
    op.add_column(
        "simulation_cells",
        sa.Column("reaction_sentiment", sa.String(16), nullable=True),
    )
    op.add_column(
        "simulation_cells",
        sa.Column("adoption_probability", sa.Float(), nullable=True),
    )
    op.add_column(
        "simulation_cells",
        sa.Column("time_horizon", sa.String(16), nullable=True),
    )
    op.add_column(
        "simulation_cells",
        sa.Column("devil_advocate", sa.Text(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("simulation_cells", "devil_advocate")
    op.drop_column("simulation_cells", "time_horizon")
    op.drop_column("simulation_cells", "adoption_probability")
    op.drop_column("simulation_cells", "reaction_sentiment")
    op.alter_column(
        "simulation_cells",
        "option_letter",
        existing_type=sa.String(64),
        type_=sa.String(2),
        existing_nullable=False,
    )
