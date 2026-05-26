"""initial_schema

Revision ID: 0001
Revises:
Create Date: 2026-05-21 00:00:00.000000

"""
from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = "0001"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()

    # ------------------------------------------------------------------
    # users
    # ------------------------------------------------------------------
    if not bind.dialect.has_table(bind, "users"):
        op.create_table(
            "users",
            sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
            sa.Column("username", sa.String(), nullable=False),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint("username"),
        )
        op.create_index("ix_users_username", "users", ["username"], unique=True)

    # ------------------------------------------------------------------
    # project_types
    # ------------------------------------------------------------------
    if not bind.dialect.has_table(bind, "project_types"):
        op.create_table(
            "project_types",
            sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
            sa.Column("code", sa.String(), nullable=False),
            sa.Column("name", sa.String(), nullable=False),
            sa.Column("is_active", sa.Boolean(), nullable=False, server_default="false"),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint("code"),
        )
        op.create_index("ix_project_types_code", "project_types", ["code"], unique=True)

    # ------------------------------------------------------------------
    # projects
    # ------------------------------------------------------------------
    if not bind.dialect.has_table(bind, "projects"):
        op.create_table(
            "projects",
            sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
            sa.Column("user_id", sa.Integer(), nullable=False),
            sa.Column("project_type_id", sa.Integer(), nullable=False),
            sa.Column("name", sa.String(), nullable=False),
            sa.Column("description", sa.Text(), nullable=True),
            sa.Column("status", sa.String(), nullable=False, server_default="draft"),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
            sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
            sa.ForeignKeyConstraint(
                ["project_type_id"], ["project_types.id"], ondelete="RESTRICT"
            ),
            sa.PrimaryKeyConstraint("id"),
        )
        op.create_index("ix_projects_user_id", "projects", ["user_id"], unique=False)
        op.create_index(
            "ix_projects_user_type",
            "projects",
            ["user_id", "project_type_id"],
            unique=False,
        )

    # ------------------------------------------------------------------
    # value_discovery_opportunities
    # ------------------------------------------------------------------
    if not bind.dialect.has_table(bind, "value_discovery_opportunities"):
        op.create_table(
            "value_discovery_opportunities",
            sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
            sa.Column("project_id", sa.Integer(), nullable=False),
            sa.Column("title", sa.String(), nullable=False),
            sa.Column("description", sa.Text(), nullable=True),
            sa.Column("business_unit", sa.String(), nullable=True),
            sa.Column("estimated_annual_value_cents", sa.Integer(), nullable=True),
            sa.Column("effort", sa.String(), nullable=True),
            sa.Column("priority", sa.String(), nullable=True),
            sa.Column(
                "status", sa.String(), nullable=False, server_default="identified"
            ),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
            sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
            sa.PrimaryKeyConstraint("id"),
        )
        op.create_index(
            "ix_value_discovery_opportunities_project_id",
            "value_discovery_opportunities",
            ["project_id"],
            unique=False,
        )

    # ------------------------------------------------------------------
    # bcm_capabilities
    # ------------------------------------------------------------------
    if not bind.dialect.has_table(bind, "bcm_capabilities"):
        op.create_table(
            "bcm_capabilities",
            sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
            sa.Column("project_id", sa.Integer(), nullable=False),
            sa.Column("parent_id", sa.Integer(), nullable=True),
            sa.Column("level", sa.Integer(), nullable=False),
            sa.Column("name", sa.String(), nullable=False),
            sa.Column("description", sa.Text(), nullable=True),
            sa.Column("position", sa.Integer(), nullable=False),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
            sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
            sa.ForeignKeyConstraint(
                ["parent_id"], ["bcm_capabilities.id"], ondelete="CASCADE"
            ),
            sa.PrimaryKeyConstraint("id"),
        )
        op.create_index(
            "ix_bcm_capabilities_project_id",
            "bcm_capabilities",
            ["project_id"],
            unique=False,
        )
        op.create_index(
            "ix_bcm_caps_project_parent",
            "bcm_capabilities",
            ["project_id", "parent_id"],
            unique=False,
        )
        op.create_index(
            "ix_bcm_caps_project_level",
            "bcm_capabilities",
            ["project_id", "level"],
            unique=False,
        )

    # ------------------------------------------------------------------
    # bcm_files
    # ------------------------------------------------------------------
    if not bind.dialect.has_table(bind, "bcm_files"):
        op.create_table(
            "bcm_files",
            sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
            sa.Column("project_id", sa.Integer(), nullable=False),
            sa.Column("anthropic_file_id", sa.String(), nullable=False),
            sa.Column("original_filename", sa.String(), nullable=False),
            sa.Column("kind", sa.String(), nullable=False),
            sa.Column("mime_type", sa.String(), nullable=False),
            sa.Column("size_bytes", sa.Integer(), nullable=False),
            sa.Column("uploaded_at", sa.DateTime(timezone=True), nullable=False),
            sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
            sa.PrimaryKeyConstraint("id"),
        )
        op.create_index(
            "ix_bcm_files_project_id", "bcm_files", ["project_id"], unique=False
        )

    # ------------------------------------------------------------------
    # chat_threads
    # ------------------------------------------------------------------
    if not bind.dialect.has_table(bind, "chat_threads"):
        op.create_table(
            "chat_threads",
            sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
            sa.Column("project_id", sa.Integer(), nullable=False),
            sa.Column(
                "scope", sa.String(), nullable=False, server_default="bcm"
            ),
            sa.Column(
                "title", sa.String(), nullable=False, server_default="New chat"
            ),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
            sa.CheckConstraint(
                "scope IN ('bcm','data_quality')", name="ck_chat_thread_scope"
            ),
            sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
            sa.PrimaryKeyConstraint("id"),
        )
        op.create_index(
            "ix_chat_threads_project_id", "chat_threads", ["project_id"], unique=False
        )
        op.create_index(
            "ix_chat_threads_project_scope",
            "chat_threads",
            ["project_id", "scope"],
            unique=False,
        )

    # ------------------------------------------------------------------
    # chat_messages
    # ------------------------------------------------------------------
    if not bind.dialect.has_table(bind, "chat_messages"):
        op.create_table(
            "chat_messages",
            sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
            sa.Column("project_id", sa.Integer(), nullable=False),
            sa.Column("thread_id", sa.Integer(), nullable=True),
            sa.Column(
                "scope", sa.String(), nullable=False, server_default="bcm"
            ),
            sa.Column("role", sa.String(), nullable=False),
            sa.Column("content", sa.Text(), nullable=False),
            sa.Column("raw", sa.Text(), nullable=True),
            sa.Column("thinking", sa.Text(), nullable=True),
            sa.Column("model_provider", sa.String(), nullable=True),
            sa.Column("model_id", sa.String(), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.CheckConstraint(
                "scope IN ('bcm','data_quality')", name="ck_chat_message_scope"
            ),
            sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
            sa.ForeignKeyConstraint(
                ["thread_id"], ["chat_threads.id"], ondelete="CASCADE"
            ),
            sa.PrimaryKeyConstraint("id"),
        )
        op.create_index(
            "ix_chat_messages_thread_id", "chat_messages", ["thread_id"], unique=False
        )
        op.create_index(
            "ix_chat_messages_scope", "chat_messages", ["scope"], unique=False
        )
        op.create_index(
            "ix_chat_msgs_project_scope_created",
            "chat_messages",
            ["project_id", "scope", "created_at"],
            unique=False,
        )
        op.create_index(
            "ix_chat_msgs_thread_created",
            "chat_messages",
            ["thread_id", "created_at"],
            unique=False,
        )

    # ------------------------------------------------------------------
    # data_quality_datasets
    # ------------------------------------------------------------------
    if not bind.dialect.has_table(bind, "data_quality_datasets"):
        op.create_table(
            "data_quality_datasets",
            sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
            sa.Column("project_id", sa.Integer(), nullable=False),
            sa.Column("original_filename", sa.String(), nullable=False),
            sa.Column("local_path", sa.Text(), nullable=False),
            sa.Column("file_sha256", sa.String(64), nullable=False),
            sa.Column("size_bytes", sa.Integer(), nullable=False),
            sa.Column("sheets_json", sa.Text(), nullable=False),
            sa.Column("engine_version", sa.String(), nullable=False),
            sa.Column("uploaded_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("profiled_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column(
                "annotation_status",
                sa.String(),
                nullable=False,
                server_default="pending",
            ),
            sa.Column("annotation_error", sa.Text(), nullable=True),
            sa.Column("annotated_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column(
                "config_completed_at", sa.DateTime(timezone=True), nullable=True
            ),
            sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
            sa.PrimaryKeyConstraint("id"),
        )
        op.create_index(
            "ix_data_quality_datasets_project_id",
            "data_quality_datasets",
            ["project_id"],
            unique=False,
        )
        op.create_index(
            "ix_data_quality_datasets_file_sha256",
            "data_quality_datasets",
            ["file_sha256"],
            unique=False,
        )

    # ------------------------------------------------------------------
    # data_quality_sheet_profiles
    # ------------------------------------------------------------------
    if not bind.dialect.has_table(bind, "data_quality_sheet_profiles"):
        op.create_table(
            "data_quality_sheet_profiles",
            sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
            sa.Column("dataset_id", sa.Integer(), nullable=False),
            sa.Column("sheet_name", sa.String(), nullable=False),
            sa.Column("row_count", sa.Integer(), nullable=False),
            sa.Column("column_count", sa.Integer(), nullable=False),
            sa.Column(
                "exact_duplicate_row_count",
                sa.Integer(),
                nullable=False,
                server_default="0",
            ),
            sa.Column("completeness_pct", sa.Float(), nullable=False),
            sa.Column("rag", sa.String(), nullable=False),
            sa.Column("engine_version", sa.String(), nullable=False),
            sa.Column("computed_at", sa.DateTime(timezone=True), nullable=False),
            sa.CheckConstraint(
                "rag IN ('green','amber','red')", name="ck_dq_sheet_rag"
            ),
            sa.ForeignKeyConstraint(
                ["dataset_id"], ["data_quality_datasets.id"], ondelete="CASCADE"
            ),
            sa.PrimaryKeyConstraint("id"),
        )
        op.create_index(
            "ix_data_quality_sheet_profiles_dataset_id",
            "data_quality_sheet_profiles",
            ["dataset_id"],
            unique=False,
        )
        op.create_index(
            "ix_dq_sheet_profile_dataset_sheet",
            "data_quality_sheet_profiles",
            ["dataset_id", "sheet_name"],
            unique=True,
        )

    # ------------------------------------------------------------------
    # data_quality_column_profiles
    # ------------------------------------------------------------------
    if not bind.dialect.has_table(bind, "data_quality_column_profiles"):
        op.create_table(
            "data_quality_column_profiles",
            sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
            sa.Column("sheet_profile_id", sa.Integer(), nullable=False),
            sa.Column("name", sa.String(), nullable=False),
            sa.Column("ordinal", sa.Integer(), nullable=False),
            sa.Column("inferred_dtype", sa.String(), nullable=False),
            sa.Column("semantic_type", sa.String(), nullable=False),
            sa.Column(
                "type_mismatch_count", sa.Integer(), nullable=False, server_default="0"
            ),
            sa.Column("null_count", sa.Integer(), nullable=False),
            sa.Column("null_pct", sa.Float(), nullable=False),
            sa.Column("distinct_count", sa.Integer(), nullable=False),
            sa.Column("distinct_pct", sa.Float(), nullable=False),
            sa.Column(
                "top_values_json", sa.Text(), nullable=False, server_default="[]"
            ),
            sa.Column("numeric_min", sa.Float(), nullable=True),
            sa.Column("numeric_max", sa.Float(), nullable=True),
            sa.Column("numeric_mean", sa.Float(), nullable=True),
            sa.Column("numeric_median", sa.Float(), nullable=True),
            sa.Column("numeric_std", sa.Float(), nullable=True),
            sa.Column("numeric_p25", sa.Float(), nullable=True),
            sa.Column("numeric_p75", sa.Float(), nullable=True),
            sa.Column("date_min", sa.String(), nullable=True),
            sa.Column("date_max", sa.String(), nullable=True),
            sa.Column("pattern_label", sa.String(), nullable=True),
            sa.Column("pattern_conformance_pct", sa.Float(), nullable=True),
            sa.Column("outlier_iqr_count", sa.Integer(), nullable=True),
            sa.Column("outlier_mad_count", sa.Integer(), nullable=True),
            sa.Column("range_min", sa.Float(), nullable=True),
            sa.Column("range_max", sa.Float(), nullable=True),
            sa.Column("range_violation_count", sa.Integer(), nullable=True),
            sa.Column("rag", sa.String(), nullable=False),
            sa.Column("computed_at", sa.DateTime(timezone=True), nullable=False),
            sa.CheckConstraint(
                "rag IN ('green','amber','red')", name="ck_dq_col_rag"
            ),
            sa.ForeignKeyConstraint(
                ["sheet_profile_id"],
                ["data_quality_sheet_profiles.id"],
                ondelete="CASCADE",
            ),
            sa.PrimaryKeyConstraint("id"),
        )
        op.create_index(
            "ix_data_quality_column_profiles_sheet_profile_id",
            "data_quality_column_profiles",
            ["sheet_profile_id"],
            unique=False,
        )
        op.create_index(
            "ix_dq_col_profile_sheet_ordinal",
            "data_quality_column_profiles",
            ["sheet_profile_id", "ordinal"],
            unique=False,
        )

    # ------------------------------------------------------------------
    # data_quality_issues
    # ------------------------------------------------------------------
    if not bind.dialect.has_table(bind, "data_quality_issues"):
        op.create_table(
            "data_quality_issues",
            sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
            sa.Column("dataset_id", sa.Integer(), nullable=False),
            sa.Column("sheet_name", sa.String(), nullable=False),
            sa.Column("column_name", sa.String(), nullable=True),
            sa.Column("dimension", sa.String(), nullable=False),
            sa.Column("severity", sa.String(), nullable=False),
            sa.Column("description", sa.Text(), nullable=False),
            sa.Column(
                "sample_value_count", sa.Integer(), nullable=False, server_default="0"
            ),
            sa.Column(
                "sample_values_json", sa.Text(), nullable=False, server_default="[]"
            ),
            sa.Column("engine_version", sa.String(), nullable=False),
            sa.Column("ai_narrative", sa.Text(), nullable=True),
            sa.Column("ai_fix", sa.Text(), nullable=True),
            sa.Column(
                "ai_status", sa.String(), nullable=False, server_default="pending"
            ),
            sa.Column("ai_raw", sa.Text(), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.CheckConstraint(
                "severity IN ('low','medium','high','critical')",
                name="ck_dq_issue_severity",
            ),
            sa.CheckConstraint(
                "dimension IN ('completeness','consistency','uniqueness','validity','accuracy','redundancy')",
                name="ck_dq_issue_dimension",
            ),
            sa.CheckConstraint(
                "ai_status IN ('pending','running','done','failed')",
                name="ck_dq_issue_ai_status",
            ),
            sa.ForeignKeyConstraint(
                ["dataset_id"], ["data_quality_datasets.id"], ondelete="CASCADE"
            ),
            sa.PrimaryKeyConstraint("id"),
        )
        op.create_index(
            "ix_data_quality_issues_dataset_id",
            "data_quality_issues",
            ["dataset_id"],
            unique=False,
        )
        op.create_index(
            "ix_data_quality_issues_sheet_name",
            "data_quality_issues",
            ["sheet_name"],
            unique=False,
        )
        op.create_index(
            "ix_data_quality_issues_column_name",
            "data_quality_issues",
            ["column_name"],
            unique=False,
        )

    # ------------------------------------------------------------------
    # data_quality_functional_dependencies
    # ------------------------------------------------------------------
    if not bind.dialect.has_table(bind, "data_quality_functional_dependencies"):
        op.create_table(
            "data_quality_functional_dependencies",
            sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
            sa.Column("dataset_id", sa.Integer(), nullable=False),
            sa.Column("sheet_name", sa.String(), nullable=False),
            sa.Column("determinant_column", sa.String(), nullable=False),
            sa.Column("dependent_column", sa.String(), nullable=False),
            sa.Column("confidence_pct", sa.Float(), nullable=False),
            sa.Column(
                "counter_example_count",
                sa.Integer(),
                nullable=False,
                server_default="0",
            ),
            sa.Column(
                "sample_counter_examples_json",
                sa.Text(),
                nullable=False,
                server_default="[]",
            ),
            sa.Column("engine_version", sa.String(), nullable=False),
            sa.Column("computed_at", sa.DateTime(timezone=True), nullable=False),
            sa.ForeignKeyConstraint(
                ["dataset_id"], ["data_quality_datasets.id"], ondelete="CASCADE"
            ),
            sa.PrimaryKeyConstraint("id"),
        )
        op.create_index(
            "ix_data_quality_functional_dependencies_dataset_id",
            "data_quality_functional_dependencies",
            ["dataset_id"],
            unique=False,
        )
        op.create_index(
            "ix_data_quality_functional_dependencies_sheet_name",
            "data_quality_functional_dependencies",
            ["sheet_name"],
            unique=False,
        )

    # ------------------------------------------------------------------
    # data_quality_relationships
    # ------------------------------------------------------------------
    if not bind.dialect.has_table(bind, "data_quality_relationships"):
        op.create_table(
            "data_quality_relationships",
            sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
            sa.Column("dataset_id", sa.Integer(), nullable=False),
            sa.Column("parent_sheet", sa.String(), nullable=False),
            sa.Column("parent_column", sa.String(), nullable=False),
            sa.Column("child_sheet", sa.String(), nullable=False),
            sa.Column("child_column", sa.String(), nullable=False),
            sa.Column("type_match", sa.Boolean(), nullable=False),
            sa.Column("name_similarity", sa.Float(), nullable=False),
            sa.Column("subset_coverage", sa.Float(), nullable=False),
            sa.Column("cardinality", sa.String(), nullable=False),
            sa.Column("confidence_pct", sa.Float(), nullable=False),
            sa.Column(
                "status", sa.String(), nullable=False, server_default="suggested"
            ),
            sa.Column("engine_version", sa.String(), nullable=False),
            sa.Column("suggested_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("confirmed_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("dismissed_at", sa.DateTime(timezone=True), nullable=True),
            sa.CheckConstraint(
                "status IN ('suggested','confirmed','dismissed')",
                name="ck_dq_rel_status",
            ),
            sa.CheckConstraint(
                "cardinality IN ('one_to_one','many_to_one','unknown')",
                name="ck_dq_rel_cardinality",
            ),
            sa.ForeignKeyConstraint(
                ["dataset_id"], ["data_quality_datasets.id"], ondelete="CASCADE"
            ),
            sa.PrimaryKeyConstraint("id"),
        )
        op.create_index(
            "ix_data_quality_relationships_dataset_id",
            "data_quality_relationships",
            ["dataset_id"],
            unique=False,
        )
        op.create_index(
            "ix_dq_rel_unique",
            "data_quality_relationships",
            ["dataset_id", "parent_sheet", "parent_column", "child_sheet", "child_column"],
            unique=True,
        )

    # ------------------------------------------------------------------
    # data_quality_profile_configs
    # ------------------------------------------------------------------
    if not bind.dialect.has_table(bind, "data_quality_profile_configs"):
        op.create_table(
            "data_quality_profile_configs",
            sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
            sa.Column("dataset_id", sa.Integer(), nullable=False),
            sa.Column("sheet_a", sa.String(), nullable=True),
            sa.Column("sheet_b", sa.String(), nullable=True),
            sa.Column(
                "normalization_json", sa.Text(), nullable=False, server_default="{}"
            ),
            sa.Column(
                "threshold", sa.Float(), nullable=False, server_default="0.85"
            ),
            sa.Column("engine_version", sa.String(), nullable=False),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
            sa.CheckConstraint(
                "threshold >= 0.0 AND threshold <= 1.0",
                name="ck_dq_config_threshold",
            ),
            sa.ForeignKeyConstraint(
                ["dataset_id"], ["data_quality_datasets.id"], ondelete="CASCADE"
            ),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint("dataset_id"),
        )
        op.create_index(
            "ix_data_quality_profile_configs_dataset_id",
            "data_quality_profile_configs",
            ["dataset_id"],
            unique=True,
        )

    # ------------------------------------------------------------------
    # data_quality_column_mappings
    # ------------------------------------------------------------------
    if not bind.dialect.has_table(bind, "data_quality_column_mappings"):
        op.create_table(
            "data_quality_column_mappings",
            sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
            sa.Column("config_id", sa.Integer(), nullable=False),
            sa.Column("column_a", sa.String(), nullable=False),
            sa.Column("column_b", sa.String(), nullable=False),
            sa.Column("algorithm", sa.String(), nullable=False),
            sa.Column("weight", sa.Float(), nullable=False, server_default="1.0"),
            sa.Column(
                "is_important", sa.Boolean(), nullable=False, server_default="0"
            ),
            sa.Column("parser", sa.String(), nullable=True),
            sa.Column(
                "recommended_by",
                sa.String(),
                nullable=False,
                server_default="heuristic",
            ),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.CheckConstraint(
                "weight >= 0.0 AND weight <= 1.0", name="ck_dq_mapping_weight"
            ),
            sa.CheckConstraint(
                "algorithm IN ('exact','levenshtein','jaro_winkler','jaccard_tokens',"
                "'cosine_tokens','soundex','metaphone','ngram','numeric_tolerance','date_proximity')",
                name="ck_dq_mapping_algorithm",
            ),
            sa.CheckConstraint(
                "parser IS NULL OR parser IN ('phone','email','date')",
                name="ck_dq_mapping_parser",
            ),
            sa.CheckConstraint(
                "recommended_by IN ('heuristic','llm','user')",
                name="ck_dq_mapping_recommended_by",
            ),
            sa.ForeignKeyConstraint(
                ["config_id"],
                ["data_quality_profile_configs.id"],
                ondelete="CASCADE",
            ),
            sa.PrimaryKeyConstraint("id"),
        )
        op.create_index(
            "ix_data_quality_column_mappings_config_id",
            "data_quality_column_mappings",
            ["config_id"],
            unique=False,
        )
        op.create_index(
            "ix_dq_mapping_unique",
            "data_quality_column_mappings",
            ["config_id", "column_a", "column_b"],
            unique=True,
        )

    # ------------------------------------------------------------------
    # data_quality_similarity_runs
    # ------------------------------------------------------------------
    if not bind.dialect.has_table(bind, "data_quality_similarity_runs"):
        op.create_table(
            "data_quality_similarity_runs",
            sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
            sa.Column("dataset_id", sa.Integer(), nullable=False),
            sa.Column("config_id", sa.Integer(), nullable=False),
            sa.Column("sheet_a", sa.String(), nullable=False),
            sa.Column("sheet_b", sa.String(), nullable=False),
            sa.Column("threshold", sa.Float(), nullable=False),
            sa.Column(
                "status", sa.String(), nullable=False, server_default="running"
            ),
            sa.Column(
                "candidate_pair_count",
                sa.Integer(),
                nullable=False,
                server_default="0",
            ),
            sa.Column(
                "passing_pair_count",
                sa.Integer(),
                nullable=False,
                server_default="0",
            ),
            sa.Column(
                "cluster_count", sa.Integer(), nullable=False, server_default="0"
            ),
            sa.Column("blocking_column", sa.String(), nullable=True),
            sa.Column("error", sa.Text(), nullable=True),
            sa.Column("engine_version", sa.String(), nullable=False),
            sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
            sa.CheckConstraint(
                "status IN ('running','done','failed')", name="ck_dq_run_status"
            ),
            sa.ForeignKeyConstraint(
                ["dataset_id"], ["data_quality_datasets.id"], ondelete="CASCADE"
            ),
            sa.ForeignKeyConstraint(
                ["config_id"],
                ["data_quality_profile_configs.id"],
                ondelete="CASCADE",
            ),
            sa.PrimaryKeyConstraint("id"),
        )
        op.create_index(
            "ix_data_quality_similarity_runs_dataset_id",
            "data_quality_similarity_runs",
            ["dataset_id"],
            unique=False,
        )
        op.create_index(
            "ix_data_quality_similarity_runs_config_id",
            "data_quality_similarity_runs",
            ["config_id"],
            unique=False,
        )

    # ------------------------------------------------------------------
    # data_quality_record_clusters
    # ------------------------------------------------------------------
    if not bind.dialect.has_table(bind, "data_quality_record_clusters"):
        op.create_table(
            "data_quality_record_clusters",
            sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
            sa.Column("run_id", sa.Integer(), nullable=False),
            sa.Column("cluster_index", sa.Integer(), nullable=False),
            sa.Column(
                "a_member_count", sa.Integer(), nullable=False, server_default="0"
            ),
            sa.Column(
                "b_member_count", sa.Integer(), nullable=False, server_default="0"
            ),
            sa.Column(
                "top_score", sa.Float(), nullable=False, server_default="0.0"
            ),
            sa.Column(
                "min_score", sa.Float(), nullable=False, server_default="0.0"
            ),
            sa.Column(
                "canonical_key_json", sa.Text(), nullable=False, server_default="{}"
            ),
            sa.Column(
                "a_members_json", sa.Text(), nullable=False, server_default="[]"
            ),
            sa.Column(
                "b_members_json", sa.Text(), nullable=False, server_default="[]"
            ),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.ForeignKeyConstraint(
                ["run_id"],
                ["data_quality_similarity_runs.id"],
                ondelete="CASCADE",
            ),
            sa.PrimaryKeyConstraint("id"),
        )
        op.create_index(
            "ix_data_quality_record_clusters_run_id",
            "data_quality_record_clusters",
            ["run_id"],
            unique=False,
        )
        op.create_index(
            "ix_dq_cluster_run_index",
            "data_quality_record_clusters",
            ["run_id", "cluster_index"],
            unique=True,
        )

    # ------------------------------------------------------------------
    # data_quality_record_pairs
    # ------------------------------------------------------------------
    if not bind.dialect.has_table(bind, "data_quality_record_pairs"):
        op.create_table(
            "data_quality_record_pairs",
            sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
            sa.Column("run_id", sa.Integer(), nullable=False),
            sa.Column("cluster_id", sa.Integer(), nullable=True),
            sa.Column("row_a_index", sa.Integer(), nullable=False),
            sa.Column("row_b_index", sa.Integer(), nullable=False),
            sa.Column("score", sa.Float(), nullable=False),
            sa.Column(
                "per_column_scores_json",
                sa.Text(),
                nullable=False,
                server_default="{}",
            ),
            sa.ForeignKeyConstraint(
                ["run_id"],
                ["data_quality_similarity_runs.id"],
                ondelete="CASCADE",
            ),
            sa.ForeignKeyConstraint(
                ["cluster_id"],
                ["data_quality_record_clusters.id"],
                ondelete="SET NULL",
            ),
            sa.PrimaryKeyConstraint("id"),
        )
        op.create_index(
            "ix_data_quality_record_pairs_run_id",
            "data_quality_record_pairs",
            ["run_id"],
            unique=False,
        )
        op.create_index(
            "ix_data_quality_record_pairs_cluster_id",
            "data_quality_record_pairs",
            ["cluster_id"],
            unique=False,
        )


def downgrade() -> None:
    bind = op.get_bind()

    # Drop in reverse dependency order: children before parents.

    if bind.dialect.has_table(bind, "data_quality_record_pairs"):
        op.drop_table("data_quality_record_pairs")

    if bind.dialect.has_table(bind, "data_quality_record_clusters"):
        op.drop_table("data_quality_record_clusters")

    if bind.dialect.has_table(bind, "data_quality_similarity_runs"):
        op.drop_table("data_quality_similarity_runs")

    if bind.dialect.has_table(bind, "data_quality_column_mappings"):
        op.drop_table("data_quality_column_mappings")

    if bind.dialect.has_table(bind, "data_quality_profile_configs"):
        op.drop_table("data_quality_profile_configs")

    if bind.dialect.has_table(bind, "data_quality_relationships"):
        op.drop_table("data_quality_relationships")

    if bind.dialect.has_table(bind, "data_quality_functional_dependencies"):
        op.drop_table("data_quality_functional_dependencies")

    if bind.dialect.has_table(bind, "data_quality_issues"):
        op.drop_table("data_quality_issues")

    if bind.dialect.has_table(bind, "data_quality_column_profiles"):
        op.drop_table("data_quality_column_profiles")

    if bind.dialect.has_table(bind, "data_quality_sheet_profiles"):
        op.drop_table("data_quality_sheet_profiles")

    if bind.dialect.has_table(bind, "data_quality_datasets"):
        op.drop_table("data_quality_datasets")

    if bind.dialect.has_table(bind, "chat_messages"):
        op.drop_table("chat_messages")

    if bind.dialect.has_table(bind, "chat_threads"):
        op.drop_table("chat_threads")

    if bind.dialect.has_table(bind, "bcm_files"):
        op.drop_table("bcm_files")

    if bind.dialect.has_table(bind, "bcm_capabilities"):
        op.drop_table("bcm_capabilities")

    if bind.dialect.has_table(bind, "value_discovery_opportunities"):
        op.drop_table("value_discovery_opportunities")

    if bind.dialect.has_table(bind, "projects"):
        op.drop_table("projects")

    if bind.dialect.has_table(bind, "project_types"):
        op.drop_table("project_types")

    if bind.dialect.has_table(bind, "users"):
        op.drop_table("users")
