"""add sync layer (devices, case_events, hlc columns)

Revision ID: b2f1a9d3c4e5
Revises: 87d0fce1c8cf
Create Date: 2026-08-11

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "b2f1a9d3c4e5"
down_revision: Union[str, Sequence[str], None] = "87d0fce1c8cf"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

case_event_type = postgresql.ENUM(
    "scene_arrival", "transport_start", "hospital_arrival", "case_closed",
    "severity_changed", "patient_updated", "note_added", "state_updated",
    name="case_event_type", create_type=False,
)


def upgrade() -> None:
    """Upgrade schema: enum -> devices -> case_events -> existing-table additions."""
    case_event_type.create(op.get_bind(), checkfirst=True)

    op.create_table(
        "devices",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("owner_id", sa.Uuid(), nullable=False),
        sa.Column("label", sa.String(length=128), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["owner_id"], ["users.id"],
            ondelete="RESTRICT", name="fk_devices_owner_id_users",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_devices"),
    )
    op.create_index("ix_devices_owner_id", "devices", ["owner_id"], unique=False)

    op.create_table(
        "case_events",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("case_id", sa.Uuid(), nullable=False),
        sa.Column("event_type", case_event_type, nullable=False),
        sa.Column("payload", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("device_id", sa.Uuid(), nullable=True),
        sa.Column("hlc", sa.String(length=64), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["case_id"], ["emergency_cases.id"],
            ondelete="CASCADE", name="fk_case_events_case_id_emergency_cases",
        ),
        sa.ForeignKeyConstraint(
            ["device_id"], ["devices.id"],
            ondelete="RESTRICT", name="fk_case_events_device_id_devices",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_case_events"),
    )
    op.create_index(
        "ix_case_events_case_hlc", "case_events", ["case_id", "hlc"], unique=False
    )

    op.add_column("patients", sa.Column("device_id", sa.Uuid(), nullable=True))
    op.add_column("patients", sa.Column("hlc", sa.String(length=64), nullable=True))
    op.create_foreign_key(
        op.f("fk_patients_device_id_devices"), "patients", "devices",
        ["device_id"], ["id"], ondelete="RESTRICT",
    )
    op.create_index(
        "ix_patients_device_id", "patients", ["device_id"], unique=False
    )

    op.add_column("emergency_cases", sa.Column("device_id", sa.Uuid(), nullable=True))
    op.add_column("emergency_cases", sa.Column("hlc", sa.String(length=64), nullable=True))
    op.create_foreign_key(
        op.f("fk_emergency_cases_device_id_devices"), "emergency_cases", "devices",
        ["device_id"], ["id"], ondelete="RESTRICT",
    )
    op.create_index(
        "ix_cases_device_id", "emergency_cases", ["device_id"], unique=False
    )

    op.add_column("vitals", sa.Column("device_id", sa.Uuid(), nullable=True))
    op.add_column("vitals", sa.Column("hlc", sa.String(length=64), nullable=True))
    op.create_foreign_key(
        op.f("fk_vitals_device_id_devices"), "vitals", "devices",
        ["device_id"], ["id"], ondelete="RESTRICT",
    )
    op.create_index("ix_vitals_device_id", "vitals", ["device_id"], unique=False)


def downgrade() -> None:
    """Downgrade schema: reverse of upgrade."""
    op.drop_index("ix_vitals_device_id", table_name="vitals")
    op.drop_constraint(
        op.f("fk_vitals_device_id_devices"), "vitals", type_="foreignkey"
    )
    op.drop_column("vitals", "hlc")
    op.drop_column("vitals", "device_id")

    op.drop_index("ix_cases_device_id", table_name="emergency_cases")
    op.drop_constraint(
        op.f("fk_emergency_cases_device_id_devices"), "emergency_cases",
        type_="foreignkey",
    )
    op.drop_column("emergency_cases", "hlc")
    op.drop_column("emergency_cases", "device_id")

    op.drop_index("ix_patients_device_id", table_name="patients")
    op.drop_constraint(
        op.f("fk_patients_device_id_devices"), "patients", type_="foreignkey"
    )
    op.drop_column("patients", "hlc")
    op.drop_column("patients", "device_id")

    op.drop_index("ix_case_events_case_hlc", table_name="case_events")
    op.drop_table("case_events")
    op.drop_index("ix_devices_owner_id", table_name="devices")
    op.drop_table("devices")

    case_event_type.drop(op.get_bind(), checkfirst=True)
