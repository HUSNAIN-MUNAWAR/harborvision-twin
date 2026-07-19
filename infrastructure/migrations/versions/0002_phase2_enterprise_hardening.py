"""Phase 2 enterprise hardening.

Revision ID: 0002
Revises: 0001

The initial migration intentionally creates the current metadata for clean installs.
This migration is defensive so existing Phase 1 databases can be upgraded without
recreating data, while clean installs remain idempotent.
"""

from __future__ import annotations

from collections.abc import Iterable

import sqlalchemy as sa
from alembic import op

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None


def _columns(table: str) -> set[str]:
    inspector = sa.inspect(op.get_bind())
    if table not in inspector.get_table_names():
        return set()
    return {column["name"] for column in inspector.get_columns(table)}


def _indexes(table: str) -> set[str]:
    inspector = sa.inspect(op.get_bind())
    if table not in inspector.get_table_names():
        return set()
    return {index["name"] for index in inspector.get_indexes(table) if index.get("name")}


def _add_columns(table: str, columns: Iterable[sa.Column[object]]) -> None:
    existing = _columns(table)
    missing = [column for column in columns if column.name not in existing]
    if not missing:
        return
    with op.batch_alter_table(table) as batch:
        for column in missing:
            batch.add_column(column)


def _create_index(table: str, name: str, columns: list[str]) -> None:
    if name not in _indexes(table):
        op.create_index(name, table, columns)


def upgrade() -> None:
    _add_columns(
        "berths",
        [
            sa.Column("draft_limit_m", sa.Float(), nullable=False, server_default="14.0"),
            sa.Column("maintenance_start", sa.DateTime(timezone=True), nullable=True),
            sa.Column("maintenance_end", sa.DateTime(timezone=True), nullable=True),
        ],
    )
    _add_columns(
        "vessel_calls",
        [
            sa.Column("vessel_length_m", sa.Float(), nullable=False, server_default="300.0"),
            sa.Column("draft_m", sa.Float(), nullable=False, server_default="12.0"),
            sa.Column("operation_start", sa.DateTime(timezone=True), nullable=True),
            sa.Column("operation_completed", sa.DateTime(timezone=True), nullable=True),
            sa.Column("delay_reason", sa.String(length=200), nullable=True),
        ],
    )
    _add_columns(
        "yard_blocks",
        [
            sa.Column("is_closed", sa.Boolean(), nullable=False, server_default=sa.false()),
            sa.Column("allocation", sa.String(length=30), nullable=False, server_default="mixed"),
        ],
    )
    _create_index("yard_blocks", "ix_yard_blocks_is_closed", ["is_closed"])
    _add_columns(
        "yard_slots",
        [
            sa.Column("max_weight_kg", sa.Float(), nullable=False, server_default="36000.0"),
            sa.Column("reserved_until", sa.DateTime(timezone=True), nullable=True),
        ],
    )
    _add_columns(
        "containers",
        [
            sa.Column("retrieval_priority", sa.Integer(), nullable=False, server_default="50"),
            sa.Column("expected_retrieval_at", sa.DateTime(timezone=True), nullable=True),
        ],
    )
    _create_index("containers", "ix_containers_retrieval_priority", ["retrieval_priority"])
    _add_columns(
        "reefer_readings",
        [
            sa.Column("sensor_ok", sa.Boolean(), nullable=False, server_default=sa.true()),
            sa.Column("communication_ok", sa.Boolean(), nullable=False, server_default=sa.true()),
        ],
    )
    _add_columns(
        "incidents",
        [
            sa.Column("assigned_team", sa.String(length=120), nullable=True),
            sa.Column("due_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("dismissed_reason", sa.Text(), nullable=True),
            sa.Column("reopened_count", sa.Integer(), nullable=False, server_default="0"),
        ],
    )

    inspector = sa.inspect(op.get_bind())
    if "incident_notes" not in inspector.get_table_names():
        op.create_table(
            "incident_notes",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("organization_id", sa.Integer(), sa.ForeignKey("organizations.id"), nullable=False),
            sa.Column("incident_id", sa.Integer(), sa.ForeignKey("incidents.id"), nullable=False),
            sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=True),
            sa.Column("note", sa.Text(), nullable=False),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        )
        op.create_index("ix_incident_notes_organization_id", "incident_notes", ["organization_id"])
        op.create_index("ix_incident_notes_incident_id", "incident_notes", ["incident_id"])
        op.create_index("ix_incident_notes_created_at", "incident_notes", ["created_at"])

    _add_columns(
        "work_orders",
        [
            sa.Column("source_event_id", sa.String(length=64), nullable=True),
            sa.Column("assigned_team", sa.String(length=120), nullable=True),
            sa.Column("checklist_json", sa.Text(), nullable=False, server_default="[]"),
            sa.Column("completion_notes", sa.Text(), nullable=True),
            sa.Column("cancellation_reason", sa.Text(), nullable=True),
            sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("verified_at", sa.DateTime(timezone=True), nullable=True),
        ],
    )
    _create_index("work_orders", "ix_work_orders_source_event_id", ["source_event_id"])
    _add_columns(
        "operational_events",
        [
            sa.Column(
                "terminal_id",
                sa.Integer(),
                sa.ForeignKey("terminals.id", name="fk_operational_events_terminal_id_terminals"),
                nullable=True,
            ),
            sa.Column("ingested_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("applied_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("schema_version", sa.Integer(), nullable=False, server_default="1"),
            sa.Column("processing_status", sa.String(length=30), nullable=False, server_default="applied"),
            sa.Column("correlation_id", sa.String(length=64), nullable=True),
            sa.Column("causation_id", sa.String(length=64), nullable=True),
        ],
    )
    # Backfill deterministic provenance for Phase 1 rows.
    op.execute(
        sa.text(
            "UPDATE operational_events "
            "SET ingested_at = COALESCE(ingested_at, occurred_at), "
            "applied_at = COALESCE(applied_at, occurred_at), "
            "correlation_id = COALESCE(correlation_id, event_id)"
        )
    )
    for name, column in [
        ("ix_operational_events_terminal_id", "terminal_id"),
        ("ix_operational_events_ingested_at", "ingested_at"),
        ("ix_operational_events_processing_status", "processing_status"),
        ("ix_operational_events_correlation_id", "correlation_id"),
        ("ix_operational_events_causation_id", "causation_id"),
    ]:
        _create_index("operational_events", name, [column])

    inspector = sa.inspect(op.get_bind())
    if "simulation_runs" not in inspector.get_table_names():
        op.create_table(
            "simulation_runs",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("organization_id", sa.Integer(), sa.ForeignKey("organizations.id"), nullable=False),
            sa.Column("scenario", sa.String(length=60), nullable=False),
            sa.Column("status", sa.String(length=30), nullable=False, server_default="created"),
            sa.Column("speed_multiplier", sa.Float(), nullable=False, server_default="1.0"),
            sa.Column("random_seed", sa.Integer(), nullable=False, server_default="20260719"),
            sa.Column("simulated_time", sa.DateTime(timezone=True), nullable=False),
            sa.Column("event_count", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("error_message", sa.Text(), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        )
        op.create_index("ix_simulation_runs_organization_id", "simulation_runs", ["organization_id"])
        op.create_index("ix_simulation_runs_scenario", "simulation_runs", ["scenario"])
        op.create_index("ix_simulation_runs_status", "simulation_runs", ["status"])

    _add_columns(
        "ocr_jobs",
        [
            sa.Column("crop_path", sa.String(length=500), nullable=True),
            sa.Column("enhanced_path", sa.String(length=500), nullable=True),
            sa.Column("reviewer_id", sa.Integer(), sa.ForeignKey("users.id", name="fk_ocr_jobs_reviewer_id_users"), nullable=True),
            sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=True),
        ],
    )


def downgrade() -> None:
    # Phase 2 stores audit/evidence data that should not be silently destroyed.
    # A downgrade is intentionally conservative: only newly introduced standalone
    # tables are removed. Column removal is documented as a manual data-migration
    # operation for production deployments.
    inspector = sa.inspect(op.get_bind())
    tables = set(inspector.get_table_names())
    if "simulation_runs" in tables:
        op.drop_table("simulation_runs")
    if "incident_notes" in tables:
        op.drop_table("incident_notes")
