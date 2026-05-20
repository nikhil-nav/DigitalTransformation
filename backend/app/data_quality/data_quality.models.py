import json
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.common.db import Base

DQ_RAG_VALUES = ("green", "amber", "red")
DQ_SEVERITY_VALUES = ("low", "medium", "high", "critical")
DQ_ISSUE_DIMENSIONS = (
    "completeness",
    "consistency",
    "uniqueness",
    "validity",
    "accuracy",
    "redundancy",
)
DQ_AI_STATUSES = ("pending", "running", "done", "failed")
DQ_RELATIONSHIP_STATUSES = ("suggested", "confirmed", "dismissed")
DQ_RELATIONSHIP_CARDINALITIES = ("one_to_one", "many_to_one", "unknown")


def _now() -> datetime:
    return datetime.now(timezone.utc)


class DataQualityDataset(Base):
    __tablename__ = "data_quality_datasets"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    project_id: Mapped[int] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True
    )
    original_filename: Mapped[str] = mapped_column(String, nullable=False)
    local_path: Mapped[str] = mapped_column(Text, nullable=False)
    file_sha256: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    size_bytes: Mapped[int] = mapped_column(Integer, nullable=False)
    sheets_json: Mapped[str] = mapped_column(Text, nullable=False)
    engine_version: Mapped[str] = mapped_column(String, nullable=False)
    uploaded_at: Mapped[datetime] = mapped_column(default=_now, nullable=False)
    profiled_at: Mapped[datetime | None] = mapped_column(nullable=True)
    annotation_status: Mapped[str] = mapped_column(
        String, nullable=False, default="pending", server_default="pending"
    )
    annotation_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    annotated_at: Mapped[datetime | None] = mapped_column(nullable=True)
    config_completed_at: Mapped[datetime | None] = mapped_column(nullable=True)

    @property
    def sheets(self) -> list[dict[str, Any]]:
        try:
            value = json.loads(self.sheets_json)
        except (TypeError, json.JSONDecodeError):
            return []
        return value if isinstance(value, list) else []


class DataQualitySheetProfile(Base):
    __tablename__ = "data_quality_sheet_profiles"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    dataset_id: Mapped[int] = mapped_column(
        ForeignKey("data_quality_datasets.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    sheet_name: Mapped[str] = mapped_column(String, nullable=False)
    row_count: Mapped[int] = mapped_column(Integer, nullable=False)
    column_count: Mapped[int] = mapped_column(Integer, nullable=False)
    exact_duplicate_row_count: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0
    )
    completeness_pct: Mapped[float] = mapped_column(nullable=False)
    rag: Mapped[str] = mapped_column(String, nullable=False)
    engine_version: Mapped[str] = mapped_column(String, nullable=False)
    computed_at: Mapped[datetime] = mapped_column(default=_now, nullable=False)

    columns: Mapped[list["DataQualityColumnProfile"]] = relationship(
        back_populates="sheet_profile",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )

    __table_args__ = (
        CheckConstraint(
            "rag IN ('green','amber','red')", name="ck_dq_sheet_rag"
        ),
        Index(
            "ix_dq_sheet_profile_dataset_sheet",
            "dataset_id",
            "sheet_name",
            unique=True,
        ),
    )


class DataQualityColumnProfile(Base):
    __tablename__ = "data_quality_column_profiles"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    sheet_profile_id: Mapped[int] = mapped_column(
        ForeignKey("data_quality_sheet_profiles.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    name: Mapped[str] = mapped_column(String, nullable=False)
    ordinal: Mapped[int] = mapped_column(Integer, nullable=False)

    inferred_dtype: Mapped[str] = mapped_column(String, nullable=False)
    semantic_type: Mapped[str] = mapped_column(String, nullable=False)
    type_mismatch_count: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0
    )

    null_count: Mapped[int] = mapped_column(Integer, nullable=False)
    null_pct: Mapped[float] = mapped_column(nullable=False)
    distinct_count: Mapped[int] = mapped_column(Integer, nullable=False)
    distinct_pct: Mapped[float] = mapped_column(nullable=False)
    top_values_json: Mapped[str] = mapped_column(Text, nullable=False, default="[]")

    numeric_min: Mapped[float | None] = mapped_column(nullable=True)
    numeric_max: Mapped[float | None] = mapped_column(nullable=True)
    numeric_mean: Mapped[float | None] = mapped_column(nullable=True)
    numeric_median: Mapped[float | None] = mapped_column(nullable=True)
    numeric_std: Mapped[float | None] = mapped_column(nullable=True)
    numeric_p25: Mapped[float | None] = mapped_column(nullable=True)
    numeric_p75: Mapped[float | None] = mapped_column(nullable=True)

    date_min: Mapped[str | None] = mapped_column(String, nullable=True)
    date_max: Mapped[str | None] = mapped_column(String, nullable=True)

    pattern_label: Mapped[str | None] = mapped_column(String, nullable=True)
    pattern_conformance_pct: Mapped[float | None] = mapped_column(nullable=True)

    outlier_iqr_count: Mapped[int | None] = mapped_column(nullable=True)
    outlier_mad_count: Mapped[int | None] = mapped_column(nullable=True)

    range_min: Mapped[float | None] = mapped_column(nullable=True)
    range_max: Mapped[float | None] = mapped_column(nullable=True)
    range_violation_count: Mapped[int | None] = mapped_column(nullable=True)

    rag: Mapped[str] = mapped_column(String, nullable=False)
    computed_at: Mapped[datetime] = mapped_column(default=_now, nullable=False)

    sheet_profile: Mapped["DataQualitySheetProfile"] = relationship(
        back_populates="columns"
    )

    @property
    def top_values(self) -> list[dict[str, Any]]:
        try:
            value = json.loads(self.top_values_json)
        except (TypeError, json.JSONDecodeError):
            return []
        return value if isinstance(value, list) else []

    __table_args__ = (
        CheckConstraint(
            "rag IN ('green','amber','red')", name="ck_dq_col_rag"
        ),
        Index(
            "ix_dq_col_profile_sheet_ordinal",
            "sheet_profile_id",
            "ordinal",
        ),
    )


class DataQualityIssue(Base):
    __tablename__ = "data_quality_issues"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    dataset_id: Mapped[int] = mapped_column(
        ForeignKey("data_quality_datasets.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    sheet_name: Mapped[str] = mapped_column(String, nullable=False, index=True)
    column_name: Mapped[str | None] = mapped_column(String, nullable=True, index=True)
    dimension: Mapped[str] = mapped_column(String, nullable=False)
    severity: Mapped[str] = mapped_column(String, nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    sample_value_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    sample_values_json: Mapped[str] = mapped_column(Text, nullable=False, default="[]")
    engine_version: Mapped[str] = mapped_column(String, nullable=False)
    ai_narrative: Mapped[str | None] = mapped_column(Text, nullable=True)
    ai_fix: Mapped[str | None] = mapped_column(Text, nullable=True)
    ai_status: Mapped[str] = mapped_column(
        String, nullable=False, default="pending", server_default="pending"
    )
    ai_raw: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(default=_now, nullable=False)

    @property
    def sample_values(self) -> list[str]:
        try:
            value = json.loads(self.sample_values_json)
        except (TypeError, json.JSONDecodeError):
            return []
        if not isinstance(value, list):
            return []
        return [str(v) for v in value]

    __table_args__ = (
        CheckConstraint(
            "severity IN ('low','medium','high','critical')",
            name="ck_dq_issue_severity",
        ),
        CheckConstraint(
            "dimension IN ('completeness','consistency','uniqueness',"
            "'validity','accuracy','redundancy')",
            name="ck_dq_issue_dimension",
        ),
        CheckConstraint(
            "ai_status IN ('pending','running','done','failed')",
            name="ck_dq_issue_ai_status",
        ),
    )


class DataQualityFunctionalDependency(Base):
    __tablename__ = "data_quality_functional_dependencies"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    dataset_id: Mapped[int] = mapped_column(
        ForeignKey("data_quality_datasets.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    sheet_name: Mapped[str] = mapped_column(String, nullable=False, index=True)
    determinant_column: Mapped[str] = mapped_column(String, nullable=False)
    dependent_column: Mapped[str] = mapped_column(String, nullable=False)
    confidence_pct: Mapped[float] = mapped_column(nullable=False)
    counter_example_count: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0
    )
    sample_counter_examples_json: Mapped[str] = mapped_column(
        Text, nullable=False, default="[]"
    )
    engine_version: Mapped[str] = mapped_column(String, nullable=False)
    computed_at: Mapped[datetime] = mapped_column(default=_now, nullable=False)

    @property
    def sample_counter_examples(self) -> list[str]:
        try:
            value = json.loads(self.sample_counter_examples_json)
        except (TypeError, json.JSONDecodeError):
            return []
        return [str(v) for v in value] if isinstance(value, list) else []


class DataQualityRelationship(Base):
    __tablename__ = "data_quality_relationships"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    dataset_id: Mapped[int] = mapped_column(
        ForeignKey("data_quality_datasets.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    parent_sheet: Mapped[str] = mapped_column(String, nullable=False)
    parent_column: Mapped[str] = mapped_column(String, nullable=False)
    child_sheet: Mapped[str] = mapped_column(String, nullable=False)
    child_column: Mapped[str] = mapped_column(String, nullable=False)

    type_match: Mapped[bool] = mapped_column(Boolean, nullable=False)
    name_similarity: Mapped[float] = mapped_column(nullable=False)
    subset_coverage: Mapped[float] = mapped_column(nullable=False)
    cardinality: Mapped[str] = mapped_column(String, nullable=False)
    confidence_pct: Mapped[float] = mapped_column(nullable=False)

    status: Mapped[str] = mapped_column(
        String, nullable=False, default="suggested", server_default="suggested"
    )
    engine_version: Mapped[str] = mapped_column(String, nullable=False)
    suggested_at: Mapped[datetime] = mapped_column(default=_now, nullable=False)
    confirmed_at: Mapped[datetime | None] = mapped_column(nullable=True)
    dismissed_at: Mapped[datetime | None] = mapped_column(nullable=True)

    __table_args__ = (
        CheckConstraint(
            "status IN ('suggested','confirmed','dismissed')",
            name="ck_dq_rel_status",
        ),
        CheckConstraint(
            "cardinality IN ('one_to_one','many_to_one','unknown')",
            name="ck_dq_rel_cardinality",
        ),
        Index(
            "ix_dq_rel_unique",
            "dataset_id",
            "parent_sheet",
            "parent_column",
            "child_sheet",
            "child_column",
            unique=True,
        ),
    )


class DataQualityProfileConfig(Base):
    __tablename__ = "data_quality_profile_configs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    dataset_id: Mapped[int] = mapped_column(
        ForeignKey("data_quality_datasets.id", ondelete="CASCADE"),
        nullable=False,
        unique=True,
        index=True,
    )
    sheet_a: Mapped[str | None] = mapped_column(String, nullable=True)
    sheet_b: Mapped[str | None] = mapped_column(String, nullable=True)
    normalization_json: Mapped[str] = mapped_column(
        Text, nullable=False, default="{}", server_default="{}"
    )
    threshold: Mapped[float] = mapped_column(
        nullable=False, default=0.85, server_default="0.85"
    )
    engine_version: Mapped[str] = mapped_column(String, nullable=False)
    created_at: Mapped[datetime] = mapped_column(default=_now, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        default=_now, onupdate=_now, nullable=False
    )

    mappings: Mapped[list["DataQualityColumnMapping"]] = relationship(
        back_populates="config",
        cascade="all, delete-orphan",
        passive_deletes=True,
        order_by="DataQualityColumnMapping.id",
    )

    @property
    def normalization(self) -> dict[str, bool]:
        try:
            value = json.loads(self.normalization_json)
        except (TypeError, json.JSONDecodeError):
            return {}
        if not isinstance(value, dict):
            return {}
        return {str(k): bool(v) for k, v in value.items()}

    __table_args__ = (
        CheckConstraint(
            "threshold >= 0.0 AND threshold <= 1.0",
            name="ck_dq_config_threshold",
        ),
    )


class DataQualityColumnMapping(Base):
    __tablename__ = "data_quality_column_mappings"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    config_id: Mapped[int] = mapped_column(
        ForeignKey("data_quality_profile_configs.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    column_a: Mapped[str] = mapped_column(String, nullable=False)
    column_b: Mapped[str] = mapped_column(String, nullable=False)
    algorithm: Mapped[str] = mapped_column(String, nullable=False)
    weight: Mapped[float] = mapped_column(nullable=False, default=1.0)
    is_important: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="0"
    )
    parser: Mapped[str | None] = mapped_column(String, nullable=True)
    recommended_by: Mapped[str] = mapped_column(
        String, nullable=False, default="heuristic", server_default="heuristic"
    )
    created_at: Mapped[datetime] = mapped_column(default=_now, nullable=False)

    config: Mapped["DataQualityProfileConfig"] = relationship(
        back_populates="mappings"
    )

    __table_args__ = (
        CheckConstraint(
            "weight >= 0.0 AND weight <= 1.0",
            name="ck_dq_mapping_weight",
        ),
        CheckConstraint(
            "algorithm IN ('exact','levenshtein','jaro_winkler','jaccard_tokens',"
            "'cosine_tokens','soundex','metaphone','ngram','numeric_tolerance',"
            "'date_proximity')",
            name="ck_dq_mapping_algorithm",
        ),
        CheckConstraint(
            "parser IS NULL OR parser IN ('phone','email','date')",
            name="ck_dq_mapping_parser",
        ),
        CheckConstraint(
            "recommended_by IN ('heuristic','llm','user')",
            name="ck_dq_mapping_recommended_by",
        ),
        Index(
            "ix_dq_mapping_unique",
            "config_id",
            "column_a",
            "column_b",
            unique=True,
        ),
    )


class DataQualitySimilarityRun(Base):
    __tablename__ = "data_quality_similarity_runs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    dataset_id: Mapped[int] = mapped_column(
        ForeignKey("data_quality_datasets.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    config_id: Mapped[int] = mapped_column(
        ForeignKey("data_quality_profile_configs.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    sheet_a: Mapped[str] = mapped_column(String, nullable=False)
    sheet_b: Mapped[str] = mapped_column(String, nullable=False)
    threshold: Mapped[float] = mapped_column(nullable=False)
    status: Mapped[str] = mapped_column(
        String, nullable=False, default="running", server_default="running"
    )
    candidate_pair_count: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0"
    )
    passing_pair_count: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0"
    )
    cluster_count: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0"
    )
    blocking_column: Mapped[str | None] = mapped_column(String, nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    engine_version: Mapped[str] = mapped_column(String, nullable=False)
    started_at: Mapped[datetime] = mapped_column(default=_now, nullable=False)
    finished_at: Mapped[datetime | None] = mapped_column(nullable=True)

    clusters: Mapped[list["DataQualityRecordCluster"]] = relationship(
        cascade="all, delete-orphan", passive_deletes=True
    )
    pairs: Mapped[list["DataQualityRecordPair"]] = relationship(
        cascade="all, delete-orphan", passive_deletes=True
    )

    __table_args__ = (
        CheckConstraint(
            "status IN ('running','done','failed')",
            name="ck_dq_run_status",
        ),
    )


class DataQualityRecordCluster(Base):
    __tablename__ = "data_quality_record_clusters"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    run_id: Mapped[int] = mapped_column(
        ForeignKey("data_quality_similarity_runs.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    cluster_index: Mapped[int] = mapped_column(Integer, nullable=False)
    a_member_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    b_member_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    top_score: Mapped[float] = mapped_column(nullable=False, default=0.0)
    min_score: Mapped[float] = mapped_column(nullable=False, default=0.0)
    canonical_key_json: Mapped[str] = mapped_column(
        Text, nullable=False, default="{}", server_default="{}"
    )
    a_members_json: Mapped[str] = mapped_column(
        Text, nullable=False, default="[]", server_default="[]"
    )
    b_members_json: Mapped[str] = mapped_column(
        Text, nullable=False, default="[]", server_default="[]"
    )
    created_at: Mapped[datetime] = mapped_column(default=_now, nullable=False)

    @property
    def canonical_key(self) -> dict[str, Any]:
        try:
            v = json.loads(self.canonical_key_json)
        except (TypeError, json.JSONDecodeError):
            return {}
        return v if isinstance(v, dict) else {}

    @property
    def a_members(self) -> list[int]:
        try:
            v = json.loads(self.a_members_json)
        except (TypeError, json.JSONDecodeError):
            return []
        return [int(i) for i in v] if isinstance(v, list) else []

    @property
    def b_members(self) -> list[int]:
        try:
            v = json.loads(self.b_members_json)
        except (TypeError, json.JSONDecodeError):
            return []
        return [int(i) for i in v] if isinstance(v, list) else []

    __table_args__ = (
        Index(
            "ix_dq_cluster_run_index",
            "run_id",
            "cluster_index",
            unique=True,
        ),
    )


class DataQualityRecordPair(Base):
    __tablename__ = "data_quality_record_pairs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    run_id: Mapped[int] = mapped_column(
        ForeignKey("data_quality_similarity_runs.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    cluster_id: Mapped[int | None] = mapped_column(
        ForeignKey("data_quality_record_clusters.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    row_a_index: Mapped[int] = mapped_column(Integer, nullable=False)
    row_b_index: Mapped[int] = mapped_column(Integer, nullable=False)
    score: Mapped[float] = mapped_column(nullable=False)
    per_column_scores_json: Mapped[str] = mapped_column(
        Text, nullable=False, default="{}", server_default="{}"
    )

    @property
    def per_column_scores(self) -> dict[str, float]:
        try:
            v = json.loads(self.per_column_scores_json)
        except (TypeError, json.JSONDecodeError):
            return {}
        if not isinstance(v, dict):
            return {}
        return {str(k): float(val) for k, val in v.items()}
