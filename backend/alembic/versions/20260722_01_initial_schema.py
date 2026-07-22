"""initial schema

Revision ID: 20260722_01
Revises:
Create Date: 2026-07-22 12:45:00
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "20260722_01"
down_revision: str | Sequence[str] | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "brew_sessions",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("brewzilla_id", sa.String(), nullable=False),
        sa.Column("name", sa.String(), nullable=True),
        sa.Column("profile_id", sa.String(), nullable=True),
        sa.Column("profile_json", sa.Text(), nullable=True),
        sa.Column("start_date", sa.DateTime(), nullable=True),
        sa.Column("end_date", sa.DateTime(), nullable=True),
        sa.Column("active", sa.Boolean(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_brew_sessions_brewzilla_id"), "brew_sessions", ["brewzilla_id"])

    op.create_table(
        "brewzillas",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("name", sa.String(), nullable=True),
        sa.Column("temperature", sa.Float(), nullable=True),
        sa.Column("target_temperature", sa.Float(), nullable=True),
        sa.Column("heating_enabled", sa.Boolean(), nullable=True),
        sa.Column("heating_utilisation", sa.Float(), nullable=True),
        sa.Column("pump_enabled", sa.Boolean(), nullable=True),
        sa.Column("pump_utilisation", sa.Float(), nullable=True),
        sa.Column("rssi", sa.Float(), nullable=True),
        sa.Column("active_session_id", sa.String(), nullable=True),
        sa.Column("updated_at", sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )

    op.create_table(
        "hydrometer_sessions",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("hydrometer_id", sa.String(), nullable=False),
        sa.Column("name", sa.String(), nullable=True),
        sa.Column("yeast_id", sa.String(), nullable=True),
        sa.Column("start_date", sa.DateTime(), nullable=True),
        sa.Column("end_date", sa.DateTime(), nullable=True),
        sa.Column("original_gravity", sa.Float(), nullable=True),
        sa.Column("final_gravity", sa.Float(), nullable=True),
        sa.Column("active", sa.Boolean(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_hydrometer_sessions_hydrometer_id"),
        "hydrometer_sessions",
        ["hydrometer_id"],
    )
    op.create_index(op.f("ix_hydrometer_sessions_yeast_id"), "hydrometer_sessions", ["yeast_id"])

    op.create_table(
        "hydrometers",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("name", sa.String(), nullable=True),
        sa.Column("gravity", sa.Float(), nullable=True),
        sa.Column("temperature", sa.Float(), nullable=True),
        sa.Column("battery", sa.Float(), nullable=True),
        sa.Column("rssi", sa.Float(), nullable=True),
        sa.Column("active_session_id", sa.String(), nullable=True),
        sa.Column("updated_at", sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )

    op.create_table(
        "system_jobs",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("kind", sa.String(), nullable=False),
        sa.Column("status", sa.String(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("started_at", sa.DateTime(), nullable=True),
        sa.Column("finished_at", sa.DateTime(), nullable=True),
        sa.Column("result_json", sa.Text(), nullable=True),
        sa.Column("error", sa.Text(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_system_jobs_created_at"), "system_jobs", ["created_at"])
    op.create_index(op.f("ix_system_jobs_kind"), "system_jobs", ["kind"])
    op.create_index(op.f("ix_system_jobs_status"), "system_jobs", ["status"])

    op.create_table(
        "yeasts",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("name", sa.String(), nullable=True),
        sa.Column("product_id", sa.String(), nullable=True),
        sa.Column("laboratory", sa.String(), nullable=True),
        sa.Column("type", sa.String(), nullable=True),
        sa.Column("form", sa.String(), nullable=True),
        sa.Column("min_temperature", sa.Float(), nullable=True),
        sa.Column("max_temperature", sa.Float(), nullable=True),
        sa.Column("flocculation", sa.String(), nullable=True),
        sa.Column("attenuation", sa.Float(), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("is_global", sa.Boolean(), nullable=False),
        sa.Column("archived", sa.Boolean(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_yeasts_laboratory"), "yeasts", ["laboratory"])
    op.create_index(op.f("ix_yeasts_name"), "yeasts", ["name"])
    op.create_index(op.f("ix_yeasts_type"), "yeasts", ["type"])

    op.create_table(
        "brew_telemetry",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("session_id", sa.String(), nullable=False),
        sa.Column("timestamp", sa.DateTime(), nullable=False),
        sa.Column("temperature", sa.Float(), nullable=True),
        sa.Column("target_temperature", sa.Float(), nullable=True),
        sa.Column("min_target_temperature", sa.Float(), nullable=True),
        sa.Column("max_target_temperature", sa.Float(), nullable=True),
        sa.Column("control_device_temperature", sa.Float(), nullable=True),
        sa.Column("heating_run_time", sa.Float(), nullable=True),
        sa.Column("heating_starts", sa.Integer(), nullable=True),
        sa.Column("auxillary_run_time", sa.Float(), nullable=True),
        sa.Column("auxillary_starts", sa.Integer(), nullable=True),
        sa.Column("profile_step_id", sa.String(), nullable=True),
        sa.Column("profile_step_progress", sa.Float(), nullable=True),
        sa.Column("profile_session_time", sa.Float(), nullable=True),
        sa.Column("rssi", sa.Float(), nullable=True),
        sa.ForeignKeyConstraint(["session_id"], ["brew_sessions.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("session_id", "timestamp", name="uq_brew_session_ts"),
    )
    op.create_index(op.f("ix_brew_telemetry_session_id"), "brew_telemetry", ["session_id"])

    op.create_table(
        "hydrometer_telemetry",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("session_id", sa.String(), nullable=False),
        sa.Column("timestamp", sa.DateTime(), nullable=False),
        sa.Column("gravity", sa.Float(), nullable=True),
        sa.Column("gravity_velocity", sa.Float(), nullable=True),
        sa.Column("temperature", sa.Float(), nullable=True),
        sa.Column("battery", sa.Float(), nullable=True),
        sa.Column("rssi", sa.Float(), nullable=True),
        sa.ForeignKeyConstraint(["session_id"], ["hydrometer_sessions.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("session_id", "timestamp", name="uq_hydro_session_ts"),
    )
    op.create_index(
        op.f("ix_hydrometer_telemetry_session_id"),
        "hydrometer_telemetry",
        ["session_id"],
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_hydrometer_telemetry_session_id"), table_name="hydrometer_telemetry")
    op.drop_table("hydrometer_telemetry")
    op.drop_index(op.f("ix_brew_telemetry_session_id"), table_name="brew_telemetry")
    op.drop_table("brew_telemetry")
    op.drop_index(op.f("ix_yeasts_type"), table_name="yeasts")
    op.drop_index(op.f("ix_yeasts_name"), table_name="yeasts")
    op.drop_index(op.f("ix_yeasts_laboratory"), table_name="yeasts")
    op.drop_table("yeasts")
    op.drop_index(op.f("ix_system_jobs_status"), table_name="system_jobs")
    op.drop_index(op.f("ix_system_jobs_kind"), table_name="system_jobs")
    op.drop_index(op.f("ix_system_jobs_created_at"), table_name="system_jobs")
    op.drop_table("system_jobs")
    op.drop_table("hydrometers")
    op.drop_index(op.f("ix_hydrometer_sessions_yeast_id"), table_name="hydrometer_sessions")
    op.drop_index(op.f("ix_hydrometer_sessions_hydrometer_id"), table_name="hydrometer_sessions")
    op.drop_table("hydrometer_sessions")
    op.drop_table("brewzillas")
    op.drop_index(op.f("ix_brew_sessions_brewzilla_id"), table_name="brew_sessions")
    op.drop_table("brew_sessions")
