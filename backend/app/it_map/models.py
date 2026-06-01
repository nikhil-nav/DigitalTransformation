import json
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import (
    CheckConstraint,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    Float,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.common.db import Base


def _now() -> datetime:
    return datetime.now(timezone.utc)


# ============================================================================
# IT Map Agent — Part 1: inventory (uploaded xlsx of applications)
# ============================================================================


class ApplicationInventory(Base):
    """An uploaded application-inventory Excel for a Value Discovery project.

    The full bytes live on local disk under
    ``{DT_DATA_DIR}/it_map/{project_id}/{sha256}.xlsx``; only metadata is
    in the DB. ``primary_sheet`` is the sheet the agent will process —
    chosen at upload time as the largest sheet by row count (per the
    spec's single-sheet-inventory assumption). Other sheets are listed
    in ``sheets_json`` so the UI can surface them as ignored.

    ``engine_version`` is the inventory-builder version (currently the
    DQ inspector version since we reuse that module); bumping it
    invalidates prior metadata."""

    __tablename__ = "application_inventories"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    project_id: Mapped[int] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True
    )
    original_filename: Mapped[str] = mapped_column(String, nullable=False)
    local_path: Mapped[str] = mapped_column(Text, nullable=False)
    file_sha256: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    size_bytes: Mapped[int] = mapped_column(Integer, nullable=False)
    sheets_json: Mapped[str] = mapped_column(Text, nullable=False)
    primary_sheet: Mapped[str] = mapped_column(String, nullable=False)
    engine_version: Mapped[str] = mapped_column(String, nullable=False)
    uploaded_at: Mapped[datetime] = mapped_column(default=_now, nullable=False)

    @property
    def sheets(self) -> list[dict[str, Any]]:
        try:
            value = json.loads(self.sheets_json)
        except (TypeError, json.JSONDecodeError):
            return []
        return value if isinstance(value, list) else []

    __table_args__ = (
        # One sha256 per project, so a re-upload of the same bytes is
        # detected and reported as a 409 rather than silently duplicating.
        Index(
            "ix_app_inventory_project_sha",
            "project_id",
            "file_sha256",
            unique=True,
        ),
    )


# ============================================================================
# IT Map Agent — Part 2: agent-persisted artefacts
# ============================================================================


class ApplicationInventorySchema(Base):
    """Agent's column-role inference for one inventory.

    Created/updated by the agent's `propose_schema` tool. One row per
    inventory — subsequent `propose_schema` calls update in place because
    the agent may revise its inference. ``name_column`` is required (you
    can't materialise application rows without one); all other columns
    are optional and nullable when the agent decides the inventory has
    no such field.
    """

    __tablename__ = "application_inventory_schemas"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    inventory_id: Mapped[int] = mapped_column(
        ForeignKey("application_inventories.id", ondelete="CASCADE"),
        nullable=False,
        unique=True,
        index=True,
    )
    name_column: Mapped[str] = mapped_column(String, nullable=False)
    description_column: Mapped[str | None] = mapped_column(String, nullable=True)
    business_function_column: Mapped[str | None] = mapped_column(
        String, nullable=True
    )
    technology_column: Mapped[str | None] = mapped_column(String, nullable=True)
    owner_column: Mapped[str | None] = mapped_column(String, nullable=True)
    criticality_column: Mapped[str | None] = mapped_column(String, nullable=True)
    lifecycle_column: Mapped[str | None] = mapped_column(String, nullable=True)
    engine_version: Mapped[str] = mapped_column(String, nullable=False)
    created_at: Mapped[datetime] = mapped_column(default=_now, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        default=_now, onupdate=_now, nullable=False
    )


class Application(Base):
    """One application extracted from a row of the inventory's primary
    sheet.

    Materialised when the agent calls ``propose_schema`` (one
    Application per data row in the primary sheet). ``raw_row_json``
    preserves the original cell values for the detail drawer; inferred
    fields are pulled from the columns the agent named via the schema.

    Rows whose name-column value is null/empty are materialised with
    ``unmappable_reason`` set so they surface in the Unmapped bucket
    without ever being silently dropped. ``propose_unmappable`` can also
    set this on rows the agent decides have no capability fit.
    """

    __tablename__ = "applications"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    inventory_id: Mapped[int] = mapped_column(
        ForeignKey("application_inventories.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    sheet_name: Mapped[str] = mapped_column(String, nullable=False)
    row_index: Mapped[int] = mapped_column(Integer, nullable=False)
    raw_row_json: Mapped[str] = mapped_column(
        Text, nullable=False, default="{}", server_default="{}"
    )
    inferred_name: Mapped[str | None] = mapped_column(String, nullable=True)
    inferred_description: Mapped[str | None] = mapped_column(Text, nullable=True)
    inferred_business_function: Mapped[str | None] = mapped_column(
        String, nullable=True
    )
    inferred_technology: Mapped[str | None] = mapped_column(String, nullable=True)
    inferred_owner: Mapped[str | None] = mapped_column(String, nullable=True)
    inferred_criticality: Mapped[str | None] = mapped_column(
        String, nullable=True
    )
    inferred_lifecycle: Mapped[str | None] = mapped_column(String, nullable=True)
    unmappable_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(default=_now, nullable=False)

    @property
    def raw_row(self) -> dict[str, Any]:
        try:
            v = json.loads(self.raw_row_json)
        except (TypeError, json.JSONDecodeError):
            return {}
        return v if isinstance(v, dict) else {}

    mappings: Mapped[list["ApplicationCapabilityMapping"]] = relationship(
        back_populates="application",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )

    __table_args__ = (
        Index(
            "ix_application_inventory_row",
            "inventory_id",
            "row_index",
            unique=True,
        ),
    )


class ApplicationCapabilityMapping(Base):
    """A many-to-many mapping between an Application and a BcmCapability.

    Created by the agent's ``propose_mapping`` (engine_version =
    ``it-map-agent/<version>``) or by the user via the dashboard
    (engine_version = ``user``). ``status`` lifecycle:
        suggested -> confirmed     (user click "Confirm")
        suggested -> dismissed     (user click "Dismiss")

    Status drives the re-run policy: the orchestrator deletes prior
    ``status='suggested'`` rows before re-running the agent (so stale
    suggestions don't accumulate) but leaves ``confirmed`` and
    ``dismissed`` untouched.
    """

    __tablename__ = "application_capability_mappings"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    application_id: Mapped[int] = mapped_column(
        ForeignKey("applications.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    capability_id: Mapped[int] = mapped_column(
        ForeignKey("bcm_capabilities.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    confidence: Mapped[float] = mapped_column(nullable=False, default=0.0)
    rationale: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(
        String, nullable=False, default="suggested", server_default="suggested"
    )
    engine_version: Mapped[str] = mapped_column(String, nullable=False)
    created_at: Mapped[datetime] = mapped_column(default=_now, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        default=_now, onupdate=_now, nullable=False
    )
    confirmed_at: Mapped[datetime | None] = mapped_column(nullable=True)
    dismissed_at: Mapped[datetime | None] = mapped_column(nullable=True)

    application: Mapped["Application"] = relationship(back_populates="mappings")

    __table_args__ = (
        CheckConstraint(
            "confidence >= 0.0 AND confidence <= 1.0",
            name="ck_app_map_confidence",
        ),
        CheckConstraint(
            "status IN ('suggested','confirmed','dismissed')",
            name="ck_app_map_status",
        ),
        Index(
            "ix_application_capability_unique",
            "application_id",
            "capability_id",
            unique=True,
        ),
    )


class ITMapAgentRun(Base):
    """Audit row per IT Map Agent execution.

    Append-only — every ``POST /run`` creates one. ``tool_call_count``
    is the orchestrator's running total; it's the hard guard against
    LLM loops (capped by ``MAX_TOOL_CALLS_PER_RUN`` in the engine).
    Created in Part 3 alongside the run endpoint; defined here so the
    agent module can reference the type and the table is created at
    init_db time.
    """

    __tablename__ = "it_map_agent_runs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    inventory_id: Mapped[int] = mapped_column(
        ForeignKey("application_inventories.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    status: Mapped[str] = mapped_column(
        String, nullable=False, default="running", server_default="running"
    )
    tool_call_count: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0"
    )
    application_count: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0"
    )
    mapping_count: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0"
    )
    unmappable_count: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0"
    )
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    engine_version: Mapped[str] = mapped_column(String, nullable=False)
    started_at: Mapped[datetime] = mapped_column(default=_now, nullable=False)
    finished_at: Mapped[datetime | None] = mapped_column(nullable=True)

    __table_args__ = (
        CheckConstraint(
            "status IN ('running','done','failed')",
            name="ck_it_map_run_status",
        ),
    )
