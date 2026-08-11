"""feature 4: digitized paper ECG records

Revision ID: e3f4a5b6c7d8
Revises: d4e5f6a7b8c9
Create Date: 2026-08-11

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "e3f4a5b6c7d8"
down_revision: Union[str, Sequence[str], None] = "d4e5f6a7b8c9"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Add ecg_tracings table and the ecg_added event type."""
    conn = op.get_bind()
    conn.execute(
        sa.text("ALTER TYPE case_event_type ADD VALUE IF NOT EXISTS 'ecg_added'")
    )

    op.create_table(
        "ecg_tracings",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("case_id", sa.Uuid(), nullable=False),
        sa.Column("captured_by_id", sa.Uuid(), nullable=False),
        sa.Column("captured_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("source", sa.String(length=32), nullable=False),
        sa.Column("lead_count", sa.Integer(), nullable=True),
        sa.Column("paper_speed", sa.String(length=8), nullable=False),
        sa.Column("image_original", sa.LargeBinary(), nullable=False),
        sa.Column("image_normalized", sa.LargeBinary(), nullable=True),
        sa.Column("waveform", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("quality", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("device_id", sa.Uuid(), nullable=True),
        sa.Column("hlc", sa.String(length=64), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["case_id"], ["emergency_cases.id"],
            ondelete="RESTRICT", name="fk_ecg_tracings_case_id_emergency_cases",
        ),
        sa.ForeignKeyConstraint(
            ["captured_by_id"], ["users.id"],
            ondelete="RESTRICT", name="fk_ecg_tracings_captured_by_id_users",
        ),
        sa.ForeignKeyConstraint(
            ["device_id"], ["devices.id"],
            ondelete="RESTRICT", name="fk_ecg_tracings_device_id_devices",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_ecg_tracings"),
    )
    op.create_index(
        "ix_ecg_tracings_case_id", "ecg_tracings", ["case_id"], unique=False
    )
    op.create_index(
        "ix_ecg_tracings_captured_at", "ecg_tracings", ["captured_at"], unique=False
    )


def downgrade() -> None:
    """Reverse schema: drop the table (enum value cannot be removed)."""
    op.drop_index("ix_ecg_tracings_captured_at", table_name="ecg_tracings")
    op.drop_index("ix_ecg_tracings_case_id", table_name="ecg_tracings")
    op.drop_table("ecg_tracings")
