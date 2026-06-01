"""it_map_and_dq_golden_records

Revision ID: 0002
Revises: 0001
Create Date: 2026-06-01 00:00:00.000000

"""
from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = "0002"
down_revision: Union[str, None] = "0001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()

    # ------------------------------------------------------------------
    # data_quality_record_clusters — add fingerprint column
    # ------------------------------------------------------------------
    if bind.dialect.has_table(bind, "data_quality_record_clusters"):
        existing_cols = {
            col["name"]
            for col in bind.dialect.get_columns(bind, "data_quality_record_clusters")
        }
        if "fingerprint" not in existing_cols:
            op.add_column(
                "data_quality_record_clusters",
                sa.Column(
                    "fingerprint",
                    sa.String(64),
                    nullable=False,
                    server_default="",
                ),
            )
            op.create_index(
                "ix_dq_cluster_run_fingerprint",
                "data_quality_record_clusters",
                ["run_id", "fingerprint"],
                unique=False,
            )

    # ------------------------------------------------------------------
    # data_quality_cluster_golden_values
    # ------------------------------------------------------------------
    if not bind.dialect.has_table(bind, "data_quality_cluster_golden_values"):
        op.create_table(
            "data_quality_cluster_golden_values",
            sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
            sa.Column("dataset_id", sa.Integer(), nullable=False),
            sa.Column("cluster_fingerprint", sa.String(64), nullable=False),
            sa.Column("column_name", sa.String(), nullable=False),
            sa.Column("chosen_value", sa.Text(), nullable=True),
            sa.Column(
                "value_kind", sa.String(), nullable=False, server_default="scalar"
            ),
            sa.Column("chosen_at", sa.DateTime(timezone=True), nullable=False),
            sa.CheckConstraint(
                "value_kind IN ('scalar','array')",
                name="ck_dq_golden_value_kind",
            ),
            sa.ForeignKeyConstraint(
                ["dataset_id"], ["data_quality_datasets.id"], ondelete="CASCADE"
            ),
            sa.PrimaryKeyConstraint("id"),
        )
        op.create_index(
            "ix_data_quality_cluster_golden_values_dataset_id",
            "data_quality_cluster_golden_values",
            ["dataset_id"],
            unique=False,
        )
        op.create_index(
            "ix_dq_golden_unique",
            "data_quality_cluster_golden_values",
            ["dataset_id", "cluster_fingerprint", "column_name"],
            unique=True,
        )

    # ------------------------------------------------------------------
    # application_inventories
    # ------------------------------------------------------------------
    if not bind.dialect.has_table(bind, "application_inventories"):
        op.create_table(
            "application_inventories",
            sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
            sa.Column("project_id", sa.Integer(), nullable=False),
            sa.Column("original_filename", sa.String(), nullable=False),
            sa.Column("local_path", sa.Text(), nullable=False),
            sa.Column("file_sha256", sa.String(64), nullable=False),
            sa.Column("size_bytes", sa.Integer(), nullable=False),
            sa.Column("sheets_json", sa.Text(), nullable=False),
            sa.Column("primary_sheet", sa.String(), nullable=False),
            sa.Column("engine_version", sa.String(), nullable=False),
            sa.Column("uploaded_at", sa.DateTime(timezone=True), nullable=False),
            sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
            sa.PrimaryKeyConstraint("id"),
        )
        op.create_index(
            "ix_application_inventories_project_id",
            "application_inventories",
            ["project_id"],
            unique=False,
        )
        op.create_index(
            "ix_application_inventories_file_sha256",
            "application_inventories",
            ["file_sha256"],
            unique=False,
        )
        op.create_index(
            "ix_app_inventory_project_sha",
            "application_inventories",
            ["project_id", "file_sha256"],
            unique=True,
        )

    # ------------------------------------------------------------------
    # application_inventory_schemas
    # ------------------------------------------------------------------
    if not bind.dialect.has_table(bind, "application_inventory_schemas"):
        op.create_table(
            "application_inventory_schemas",
            sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
            sa.Column("inventory_id", sa.Integer(), nullable=False),
            sa.Column("name_column", sa.String(), nullable=False),
            sa.Column("description_column", sa.String(), nullable=True),
            sa.Column("business_function_column", sa.String(), nullable=True),
            sa.Column("technology_column", sa.String(), nullable=True),
            sa.Column("owner_column", sa.String(), nullable=True),
            sa.Column("criticality_column", sa.String(), nullable=True),
            sa.Column("lifecycle_column", sa.String(), nullable=True),
            sa.Column("engine_version", sa.String(), nullable=False),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
            sa.ForeignKeyConstraint(
                ["inventory_id"], ["application_inventories.id"], ondelete="CASCADE"
            ),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint("inventory_id"),
        )
        op.create_index(
            "ix_application_inventory_schemas_inventory_id",
            "application_inventory_schemas",
            ["inventory_id"],
            unique=True,
        )

    # ------------------------------------------------------------------
    # applications
    # ------------------------------------------------------------------
    if not bind.dialect.has_table(bind, "applications"):
        op.create_table(
            "applications",
            sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
            sa.Column("inventory_id", sa.Integer(), nullable=False),
            sa.Column("sheet_name", sa.String(), nullable=False),
            sa.Column("row_index", sa.Integer(), nullable=False),
            sa.Column(
                "raw_row_json", sa.Text(), nullable=False, server_default="{}"
            ),
            sa.Column("inferred_name", sa.String(), nullable=True),
            sa.Column("inferred_description", sa.Text(), nullable=True),
            sa.Column("inferred_business_function", sa.String(), nullable=True),
            sa.Column("inferred_technology", sa.String(), nullable=True),
            sa.Column("inferred_owner", sa.String(), nullable=True),
            sa.Column("inferred_criticality", sa.String(), nullable=True),
            sa.Column("inferred_lifecycle", sa.String(), nullable=True),
            sa.Column("unmappable_reason", sa.Text(), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.ForeignKeyConstraint(
                ["inventory_id"], ["application_inventories.id"], ondelete="CASCADE"
            ),
            sa.PrimaryKeyConstraint("id"),
        )
        op.create_index(
            "ix_applications_inventory_id",
            "applications",
            ["inventory_id"],
            unique=False,
        )
        op.create_index(
            "ix_application_inventory_row",
            "applications",
            ["inventory_id", "row_index"],
            unique=True,
        )

    # ------------------------------------------------------------------
    # application_capability_mappings
    # ------------------------------------------------------------------
    if not bind.dialect.has_table(bind, "application_capability_mappings"):
        op.create_table(
            "application_capability_mappings",
            sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
            sa.Column("application_id", sa.Integer(), nullable=False),
            sa.Column("capability_id", sa.Integer(), nullable=False),
            sa.Column("confidence", sa.Float(), nullable=False, server_default="0.0"),
            sa.Column("rationale", sa.Text(), nullable=False),
            sa.Column(
                "status", sa.String(), nullable=False, server_default="suggested"
            ),
            sa.Column("engine_version", sa.String(), nullable=False),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("confirmed_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("dismissed_at", sa.DateTime(timezone=True), nullable=True),
            sa.CheckConstraint(
                "confidence >= 0.0 AND confidence <= 1.0",
                name="ck_app_map_confidence",
            ),
            sa.CheckConstraint(
                "status IN ('suggested','confirmed','dismissed')",
                name="ck_app_map_status",
            ),
            sa.ForeignKeyConstraint(
                ["application_id"], ["applications.id"], ondelete="CASCADE"
            ),
            sa.ForeignKeyConstraint(
                ["capability_id"], ["bcm_capabilities.id"], ondelete="CASCADE"
            ),
            sa.PrimaryKeyConstraint("id"),
        )
        op.create_index(
            "ix_application_capability_mappings_application_id",
            "application_capability_mappings",
            ["application_id"],
            unique=False,
        )
        op.create_index(
            "ix_application_capability_mappings_capability_id",
            "application_capability_mappings",
            ["capability_id"],
            unique=False,
        )
        op.create_index(
            "ix_application_capability_unique",
            "application_capability_mappings",
            ["application_id", "capability_id"],
            unique=True,
        )

    # ------------------------------------------------------------------
    # it_map_agent_runs
    # ------------------------------------------------------------------
    if not bind.dialect.has_table(bind, "it_map_agent_runs"):
        op.create_table(
            "it_map_agent_runs",
            sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
            sa.Column("inventory_id", sa.Integer(), nullable=False),
            sa.Column(
                "status", sa.String(), nullable=False, server_default="running"
            ),
            sa.Column(
                "tool_call_count", sa.Integer(), nullable=False, server_default="0"
            ),
            sa.Column(
                "application_count", sa.Integer(), nullable=False, server_default="0"
            ),
            sa.Column(
                "mapping_count", sa.Integer(), nullable=False, server_default="0"
            ),
            sa.Column(
                "unmappable_count", sa.Integer(), nullable=False, server_default="0"
            ),
            sa.Column("error", sa.Text(), nullable=True),
            sa.Column("engine_version", sa.String(), nullable=False),
            sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
            sa.CheckConstraint(
                "status IN ('running','done','failed')",
                name="ck_it_map_run_status",
            ),
            sa.ForeignKeyConstraint(
                ["inventory_id"], ["application_inventories.id"], ondelete="CASCADE"
            ),
            sa.PrimaryKeyConstraint("id"),
        )
        op.create_index(
            "ix_it_map_agent_runs_inventory_id",
            "it_map_agent_runs",
            ["inventory_id"],
            unique=False,
        )


def downgrade() -> None:
    bind = op.get_bind()

    # Drop in reverse dependency order: children before parents.

    if bind.dialect.has_table(bind, "it_map_agent_runs"):
        op.drop_table("it_map_agent_runs")

    if bind.dialect.has_table(bind, "application_capability_mappings"):
        op.drop_table("application_capability_mappings")

    if bind.dialect.has_table(bind, "applications"):
        op.drop_table("applications")

    if bind.dialect.has_table(bind, "application_inventory_schemas"):
        op.drop_table("application_inventory_schemas")

    if bind.dialect.has_table(bind, "application_inventories"):
        op.drop_table("application_inventories")

    if bind.dialect.has_table(bind, "data_quality_cluster_golden_values"):
        op.drop_table("data_quality_cluster_golden_values")

    # Remove fingerprint column and its index from data_quality_record_clusters
    if bind.dialect.has_table(bind, "data_quality_record_clusters"):
        existing_indexes = {
            idx["name"]
            for idx in bind.dialect.get_indexes(bind, "data_quality_record_clusters")
        }
        if "ix_dq_cluster_run_fingerprint" in existing_indexes:
            op.drop_index(
                "ix_dq_cluster_run_fingerprint",
                table_name="data_quality_record_clusters",
            )
        existing_cols = {
            col["name"]
            for col in bind.dialect.get_columns(bind, "data_quality_record_clusters")
        }
        if "fingerprint" in existing_cols:
            op.drop_column("data_quality_record_clusters", "fingerprint")
