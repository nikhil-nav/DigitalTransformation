import json
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import Boolean, CheckConstraint, ForeignKey, Index, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base


def _extract_citations(raw_json: str | None) -> list[dict[str, Any]]:
    """Walk the persisted assistant transcript and pull out unique web/file citations."""
    if not raw_json:
        return []
    try:
        segments = json.loads(raw_json)
    except json.JSONDecodeError:
        return []
    if not isinstance(segments, list):
        return []

    out: list[dict[str, Any]] = []
    seen_urls: set[str] = set()
    for segment in segments:
        if not isinstance(segment, dict):
            continue
        content = segment.get("content")
        if not isinstance(content, list):
            continue
        for block in content:
            if not isinstance(block, dict):
                continue
            citations = block.get("citations")
            if not isinstance(citations, list):
                continue
            for c in citations:
                if not isinstance(c, dict):
                    continue
                url = c.get("url")
                title = c.get("title") or url
                if not isinstance(url, str) or not url:
                    continue
                if url in seen_urls:
                    continue
                seen_urls.add(url)
                out.append(
                    {
                        "url": url,
                        "title": title,
                        "cited_text": c.get("cited_text"),
                    }
                )
    return out


def _now() -> datetime:
    return datetime.now(timezone.utc)


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    username: Mapped[str] = mapped_column(String, unique=True, nullable=False, index=True)
    created_at: Mapped[datetime] = mapped_column(default=_now, nullable=False)


class ProjectType(Base):
    __tablename__ = "project_types"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    code: Mapped[str] = mapped_column(String, unique=True, nullable=False, index=True)
    name: Mapped[str] = mapped_column(String, nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)


class Project(Base):
    __tablename__ = "projects"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    project_type_id: Mapped[int] = mapped_column(
        ForeignKey("project_types.id", ondelete="RESTRICT"), nullable=False
    )
    name: Mapped[str] = mapped_column(String, nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(String, default="draft", nullable=False)
    created_at: Mapped[datetime] = mapped_column(default=_now, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        default=_now, onupdate=_now, nullable=False
    )

    project_type: Mapped["ProjectType"] = relationship()
    opportunities: Mapped[list["ValueDiscoveryOpportunity"]] = relationship(
        back_populates="project",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )

    __table_args__ = (
        Index("ix_projects_user_type", "user_id", "project_type_id"),
    )


class BcmCapability(Base):
    __tablename__ = "bcm_capabilities"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    project_id: Mapped[int] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True
    )
    parent_id: Mapped[int | None] = mapped_column(
        ForeignKey("bcm_capabilities.id", ondelete="CASCADE"), nullable=True
    )
    level: Mapped[int] = mapped_column(Integer, nullable=False)
    name: Mapped[str] = mapped_column(String, nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    position: Mapped[int] = mapped_column(Integer, nullable=False)
    created_at: Mapped[datetime] = mapped_column(default=_now, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        default=_now, onupdate=_now, nullable=False
    )

    parent: Mapped["BcmCapability | None"] = relationship(
        remote_side="BcmCapability.id", back_populates="children"
    )
    children: Mapped[list["BcmCapability"]] = relationship(
        back_populates="parent",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )

    __table_args__ = (
        Index("ix_bcm_caps_project_parent", "project_id", "parent_id"),
        Index("ix_bcm_caps_project_level", "project_id", "level"),
    )


class BcmFile(Base):
    __tablename__ = "bcm_files"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    project_id: Mapped[int] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True
    )
    anthropic_file_id: Mapped[str] = mapped_column(String, nullable=False)
    original_filename: Mapped[str] = mapped_column(String, nullable=False)
    kind: Mapped[str] = mapped_column(String, nullable=False)  # 'pdf' | 'image'
    mime_type: Mapped[str] = mapped_column(String, nullable=False)
    size_bytes: Mapped[int] = mapped_column(Integer, nullable=False)
    uploaded_at: Mapped[datetime] = mapped_column(default=_now, nullable=False)


CHAT_SCOPES = ("bcm", "data_quality")


class ChatThread(Base):
    __tablename__ = "chat_threads"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    project_id: Mapped[int] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True
    )
    scope: Mapped[str] = mapped_column(
        String, nullable=False, default="bcm", server_default="bcm", index=True
    )
    title: Mapped[str] = mapped_column(String, nullable=False, default="New chat")
    created_at: Mapped[datetime] = mapped_column(default=_now, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        default=_now, onupdate=_now, nullable=False
    )

    __table_args__ = (
        CheckConstraint(
            "scope IN ('bcm','data_quality')", name="ck_chat_thread_scope"
        ),
        Index("ix_chat_threads_project_scope", "project_id", "scope"),
    )


class ChatMessage(Base):
    __tablename__ = "chat_messages"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    project_id: Mapped[int] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), nullable=False
    )
    thread_id: Mapped[int | None] = mapped_column(
        ForeignKey("chat_threads.id", ondelete="CASCADE"),
        nullable=True,
        index=True,
    )
    scope: Mapped[str] = mapped_column(
        String, nullable=False, default="bcm", server_default="bcm", index=True
    )
    role: Mapped[str] = mapped_column(String, nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    raw: Mapped[str | None] = mapped_column(Text, nullable=True)
    thinking: Mapped[str | None] = mapped_column(Text, nullable=True)
    model_provider: Mapped[str | None] = mapped_column(String, nullable=True)
    model_id: Mapped[str | None] = mapped_column(String, nullable=True)
    created_at: Mapped[datetime] = mapped_column(default=_now, nullable=False)

    @property
    def citations(self) -> list[dict[str, Any]]:
        return _extract_citations(self.raw)

    __table_args__ = (
        CheckConstraint(
            "scope IN ('bcm','data_quality')", name="ck_chat_message_scope"
        ),
        Index("ix_chat_msgs_project_scope_created", "project_id", "scope", "created_at"),
        Index("ix_chat_msgs_thread_created", "thread_id", "created_at"),
    )


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


class DataQualityDataset(Base):
    """An Excel workbook uploaded to a Data Quality project.

    The full bytes live on local disk at `local_path`; only metadata sits in
    the DB. `sheets_json` is a JSON-encoded list of `{name, row_count,
    column_count}` produced at upload time by `app.data_quality.inspect`.
    `engine_version` is the inspector version that wrote those numbers, so we
    can detect stale metadata if the inspector logic changes.
    """

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
    # AI annotation pipeline state ('pending'|'running'|'done'|'failed').
    # Default 'pending' so a freshly-uploaded dataset advertises that
    # annotation hasn't started; the annotator flips it as it runs.
    annotation_status: Mapped[str] = mapped_column(
        String, nullable=False, default="pending", server_default="pending"
    )
    annotation_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    annotated_at: Mapped[datetime | None] = mapped_column(nullable=True)
    # Epic 3: similarity-config completion gate. NULL = user has not yet
    # visited the Profiling Setup & Configuration page for this dataset, so
    # the frontend should route them there before showing the dashboard.
    # Set when the user saves config or explicitly clicks "Skip similarity".
    config_completed_at: Mapped[datetime | None] = mapped_column(nullable=True)

    @property
    def sheets(self) -> list[dict[str, Any]]:
        try:
            value = json.loads(self.sheets_json)
        except (TypeError, json.JSONDecodeError):
            return []
        return value if isinstance(value, list) else []


class DataQualitySheetProfile(Base):
    """Per-sheet aggregate metrics computed by the stats engine.

    One row per (dataset, sheet). Re-profiling deletes the prior row and
    its descendant column profiles + issues so the dashboard always shows
    a single coherent run. `engine_version` records the stats.py version
    that produced these numbers; bumping that version invalidates the row.
    """

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
    """Per-column profile produced by `app.data_quality.stats.profile_column`.

    Every metric is computed on the full column (no sampling). Numeric stats
    are only populated when the column's semantic type is numeric; date stats
    only when it is date/datetime. `pattern_label` and
    `pattern_conformance_pct` are populated only for string columns where a
    catalogue regex matched >=95% of non-null values.
    """

    __tablename__ = "data_quality_column_profiles"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    sheet_profile_id: Mapped[int] = mapped_column(
        ForeignKey("data_quality_sheet_profiles.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    name: Mapped[str] = mapped_column(String, nullable=False)
    ordinal: Mapped[int] = mapped_column(Integer, nullable=False)

    # Type characterisation
    inferred_dtype: Mapped[str] = mapped_column(String, nullable=False)
    semantic_type: Mapped[str] = mapped_column(String, nullable=False)
    type_mismatch_count: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0
    )

    # Completeness / cardinality
    null_count: Mapped[int] = mapped_column(Integer, nullable=False)
    null_pct: Mapped[float] = mapped_column(nullable=False)
    distinct_count: Mapped[int] = mapped_column(Integer, nullable=False)
    distinct_pct: Mapped[float] = mapped_column(nullable=False)
    top_values_json: Mapped[str] = mapped_column(Text, nullable=False, default="[]")

    # Numeric stats (nullable for non-numeric columns)
    numeric_min: Mapped[float | None] = mapped_column(nullable=True)
    numeric_max: Mapped[float | None] = mapped_column(nullable=True)
    numeric_mean: Mapped[float | None] = mapped_column(nullable=True)
    numeric_median: Mapped[float | None] = mapped_column(nullable=True)
    numeric_std: Mapped[float | None] = mapped_column(nullable=True)
    numeric_p25: Mapped[float | None] = mapped_column(nullable=True)
    numeric_p75: Mapped[float | None] = mapped_column(nullable=True)

    # Date stats (ISO 8601 strings; nullable for non-date)
    date_min: Mapped[str | None] = mapped_column(String, nullable=True)
    date_max: Mapped[str | None] = mapped_column(String, nullable=True)

    # Pattern detection (string columns only)
    pattern_label: Mapped[str | None] = mapped_column(String, nullable=True)
    pattern_conformance_pct: Mapped[float | None] = mapped_column(nullable=True)

    # Outliers (numeric columns only)
    outlier_iqr_count: Mapped[int | None] = mapped_column(nullable=True)
    outlier_mad_count: Mapped[int | None] = mapped_column(nullable=True)

    # User-supplied bounds (Part 3 ships the storage; UI editor is Part 6)
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
    """A discrete data-quality finding. Always derived from the deterministic
    engine; AI annotation (Part 5) only adds narrative/fix, never alters
    severity, counts, or sample values."""

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
    """A candidate functional dependency A -> B within one sheet.

    Persisted as a separate table (not as a generic Issue) because FDs are
    informational - the user uses them to understand structure, not to fix
    anything. `confidence_pct` is the percentage of groups (rows sharing the
    same A value) where B is also constant. We only persist candidates with
    confidence >= FD_MIN_CONFIDENCE_PCT (see cross.py)."""

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
    """A candidate referential relationship between two sheets in the same
    workbook. Status starts `suggested` and ONLY changes via explicit user
    action (PATCH endpoint). Confirmed relationships drive FK-violation
    issue emission; dismissed relationships are kept as a paper trail so we
    don't re-suggest them on every re-profile."""

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

    # Signals from the suggestion engine (all 0.0-1.0)
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


class ValueDiscoveryOpportunity(Base):
    __tablename__ = "value_discovery_opportunities"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    project_id: Mapped[int] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True
    )
    title: Mapped[str] = mapped_column(String, nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    business_unit: Mapped[str | None] = mapped_column(String, nullable=True)
    estimated_annual_value_cents: Mapped[int | None] = mapped_column(Integer, nullable=True)
    effort: Mapped[str | None] = mapped_column(String, nullable=True)
    priority: Mapped[str | None] = mapped_column(String, nullable=True)
    status: Mapped[str] = mapped_column(String, default="identified", nullable=False)
    created_at: Mapped[datetime] = mapped_column(default=_now, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        default=_now, onupdate=_now, nullable=False
    )

    project: Mapped["Project"] = relationship(back_populates="opportunities")


# ============================================================================
# Epic 3 — Record-Level Similarity Scoring (config)
# ============================================================================


class DataQualityProfileConfig(Base):
    """User-saved configuration for cross-sheet similarity scoring.

    One row per (dataset). `normalization_json` is a JSON-encoded dict of
    rule_name -> bool capturing which US 3.2 toggles are enabled. `sheet_a`
    / `sheet_b` are the chosen sheet names; column-pair mappings live in
    `data_quality_column_mappings` (cascade delete). `threshold` is the
    pair-score floor used by the cluster engine; clusters only form when
    a pair's similarity on EVERY important column meets this threshold.

    `engine_version` is the NORMALIZE_VERSION at save time; a future bump
    invalidates the saved config and forces the user to re-confirm before
    a run is allowed."""

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
    """One column-pair mapping under a DataQualityProfileConfig.

    Maps `sheet_a.column_a` to `sheet_b.column_b` and records the chosen
    similarity algorithm, weight (0..1), important flag, optional
    field-specific parser, and provenance (`recommended_by`).

    Important flag drives CLUSTER formation only — the per-pair similarity
    score is the weighted average across all mappings regardless of
    importance. A pair joins a cluster only when its similarity on every
    important column meets the config threshold."""

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


# ============================================================================
# Epic 3 — Record-Level Similarity Scoring (runs + clusters)
# ============================================================================


class DataQualitySimilarityRun(Base):
    """One execution of the cross-sheet similarity engine.

    Each run captures the configuration snapshot it was launched against
    (sheet_a, sheet_b, threshold, engine_version) so a later re-run with a
    different config can still be diffed. Runs are append-only — the
    cluster engine creates a new row for every execution; prior runs stay
    on disk for audit and comparison."""

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
    """A connected component of A/B records under the union-find clustering.

    Pairs whose similarity on EVERY important column exceeds the run
    threshold form the edges; this row is one connected component over
    those edges. `canonical_key_json` is the important-column values from
    a representative member so the dashboard can display a memorable
    label without re-reading the workbook on every list call."""

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
    """One scored A.row ↔ B.row pair. Only pairs above the importance gate
    are persisted; below-threshold pairs are dropped to keep the table
    small. The aggregated score is the weighted average over all mappings
    (importance affects clustering, not scoring), while
    `per_column_scores_json` keeps every per-mapping score so the cluster
    detail view can explain why a pair joined."""

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
