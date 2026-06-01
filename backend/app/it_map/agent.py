"""IT Map Agent — system prompt, tools, dispatch.

The agent's job is to read an uploaded application inventory (an xlsx
workbook), infer which columns hold which kind of application metadata
(name, description, business-function, technology, owner, etc.), and
then propose mappings between each application row and one or more L2
business capabilities from the project's BCM.

Precision commitments:
- Schema inference is an explicit, persisted decision via
  ``propose_schema``. Without it, ``propose_mapping`` has no applications
  to reference (the agent gets a tool-error string telling it to call
  propose_schema first).
- Every mapping carries a non-empty rationale. ``propose_mapping``
  refuses to record without one — no anonymous mappings.
- Re-runs preserve user decisions. Mappings with
  ``status='confirmed'`` or ``'dismissed'`` are never overwritten by
  the agent; the orchestrator (Part 3) clears only suggested mappings
  before each run.
- L2-only mapping targets. ``propose_mapping`` rejects capabilities at
  any other level so the agent cannot accidentally map to an L1 or L3
  node and pollute the kanban.
- Bounded tool calls per run. ``MAX_TOOL_CALLS_PER_RUN`` is the engine's
  guard against LLM loops; the orchestrator counts dispatch invocations
  and aborts past the cap.
"""
from __future__ import annotations

import json
import math
from typing import Any

import pandas as pd
from sqlalchemy.orm import Session

from app.llm.session import LlmKeys
from app.models import (
    Application,
    ApplicationCapabilityMapping,
    ApplicationInventory,
    ApplicationInventorySchema,
    BcmCapability,
)

IT_MAP_AGENT_VERSION = "1.0.0"
MAX_TOOL_CALLS_PER_RUN = 200
SAMPLE_ROWS_MAX = 50
LIST_CAPABILITIES_MAX = 500


SYSTEM_PROMPT = """\
You are an enterprise architect mapping a customer's application \
inventory to a Business Capability Model (BCM). You have read-only \
tools to inspect the inventory and the BCM, plus three write tools to \
persist your decisions.

# Working order

1. Call `describe_inventory()` once to see the filename, primary sheet, \
and row count.
2. Call `read_sample(n=10)` (or larger, up to 50) to see the columns \
and their values.
3. Call `list_capabilities()` to see the BCM's L2 nodes — these are \
your only valid mapping targets.
4. Call `propose_schema(name_column=...)` ONCE with your inference of \
which columns hold which application attribute. ``name_column`` is \
required; the rest are optional and should be omitted (not set to \
empty) when the inventory has no such field. This materialises one \
``Application`` per row of the primary sheet, with inferred fields \
filled from the columns you named.
5. For each application row, decide which L2 capability or capabilities \
it serves. Use `propose_mapping(row_index, capability_id, confidence, \
rationale)` for every (row, capability) pair you support. Confidence is \
a float in [0,1]; rationale is a short non-empty justification \
referencing the row's data and the capability's name. Many-to-many is \
expected — a CRM platform like Salesforce likely maps to Marketing, \
Sales, AND Service.
6. For any row you decide has NO clean fit, call \
`propose_unmappable(row_index, reason)`. Do not leave rows unmapped \
silently.

# Hard rules

- ALWAYS call ``propose_schema`` before any ``propose_mapping`` or \
``propose_unmappable``. Without it, applications haven't been \
materialised and the write tools will reject your call.
- NEVER invent a ``capability_id``. Use only ids returned by \
``list_capabilities``.
- NEVER omit ``rationale``. A mapping without justification is \
unreviewable; it will be rejected.
- Use ``read_row(row_index)`` to look up individual rows you need more \
detail on; ``read_sample`` only returns the first N.
- A pair (row_index, capability_id) is mapped AT MOST ONCE per run. \
Re-proposing the same pair updates the prior suggestion's confidence \
and rationale.
"""


# --- Tool specifications (Anthropic-shaped; provider translates) ---


IT_MAP_TOOLS: list[dict[str, Any]] = [
    {
        "name": "describe_inventory",
        "description": (
            "Return the inventory filename, primary sheet name + row "
            "count, and a list of all sheets (other sheets are ignored "
            "by the agent). Call this first."
        ),
        "input_schema": {
            "type": "object",
            "properties": {},
            "additionalProperties": False,
        },
    },
    {
        "name": "read_sample",
        "description": (
            "Return the first N rows of the primary sheet, with all "
            "columns. Use this to identify which column holds the "
            "application name, business function, etc. Default n=10; "
            "max 50."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "n": {"type": "integer", "minimum": 1, "maximum": 50},
            },
            "additionalProperties": False,
        },
    },
    {
        "name": "read_row",
        "description": (
            "Return one specific row from the primary sheet by 0-based "
            "row index (the row index excludes the header)."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "row_index": {"type": "integer", "minimum": 0},
            },
            "required": ["row_index"],
            "additionalProperties": False,
        },
    },
    {
        "name": "list_capabilities",
        "description": (
            "Return the project's BCM capabilities at the given level "
            "(default 2). Each capability has an id, name, description, "
            "and parent_id. These ids are the only valid mapping targets."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "level": {"type": "integer", "minimum": 1, "maximum": 3},
            },
            "additionalProperties": False,
        },
    },
    {
        "name": "propose_schema",
        "description": (
            "Persist your inference of which inventory columns hold which "
            "application attribute, and materialise one Application row "
            "per data row in the primary sheet. ``name_column`` is "
            "required; all other column fields are optional. Rows whose "
            "name-column value is null/empty are still materialised but "
            "marked unmappable so they surface in the Unmapped bucket "
            "rather than vanishing."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "name_column": {"type": "string"},
                "description_column": {"type": "string"},
                "business_function_column": {"type": "string"},
                "technology_column": {"type": "string"},
                "owner_column": {"type": "string"},
                "criticality_column": {"type": "string"},
                "lifecycle_column": {"type": "string"},
            },
            "required": ["name_column"],
            "additionalProperties": False,
        },
    },
    {
        "name": "propose_mapping",
        "description": (
            "Record a proposed mapping between one application row and "
            "one L2 capability. ``rationale`` MUST be non-empty. "
            "Re-proposing the same (row_index, capability_id) updates "
            "the prior suggestion's confidence and rationale; mappings "
            "the user has already confirmed or dismissed are preserved."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "row_index": {"type": "integer", "minimum": 0},
                "capability_id": {"type": "integer"},
                "confidence": {"type": "number", "minimum": 0, "maximum": 1},
                "rationale": {"type": "string", "minLength": 1},
            },
            "required": [
                "row_index",
                "capability_id",
                "confidence",
                "rationale",
            ],
            "additionalProperties": False,
        },
    },
    {
        "name": "propose_unmappable",
        "description": (
            "Mark an application row as having no clean capability fit. "
            "``reason`` is a short justification. Surfaces the app in "
            "the Unmapped bucket on the dashboard."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "row_index": {"type": "integer", "minimum": 0},
                "reason": {"type": "string", "minLength": 1},
            },
            "required": ["row_index", "reason"],
            "additionalProperties": False,
        },
    },
]


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _resolve_inventory(db: Session, inventory_id: int) -> ApplicationInventory:
    inv = (
        db.query(ApplicationInventory).filter_by(id=inventory_id).one_or_none()
    )
    if inv is None:
        raise ValueError(f"Inventory {inventory_id} not found")
    return inv


def _load_primary_sheet(inv: ApplicationInventory) -> pd.DataFrame:
    """Read the inventory's primary sheet as a DataFrame.

    ``dtype=object`` keeps cell values untouched (no pandas type
    coercion mangling the agent's view of the data)."""
    return pd.read_excel(inv.local_path, sheet_name=inv.primary_sheet, dtype=object)


def _row_to_jsonable(row: pd.Series) -> dict[str, Any]:
    """Convert a pandas row to JSON-safe primitives, mirroring how the
    DQ agent serialises query results so the LLM sees a consistent shape."""
    out: dict[str, Any] = {}
    for col, val in row.items():
        key = str(col)
        if val is None:
            out[key] = None
        elif isinstance(val, float) and math.isnan(val):
            out[key] = None
        elif isinstance(val, pd.Timestamp):
            out[key] = val.isoformat()
        elif isinstance(val, (int, float, str, bool)):
            out[key] = val
        else:
            out[key] = str(val)
    return out


def _validate_column_exists(
    inv: ApplicationInventory, df: pd.DataFrame, column: str, role: str
) -> None:
    if column not in df.columns:
        cols = list(df.columns)
        raise ValueError(
            f"'{role}' column '{column}' not found in sheet "
            f"'{inv.primary_sheet}'. Available: {cols}"
        )


# ---------------------------------------------------------------------------
# Read tools
# ---------------------------------------------------------------------------


def _tool_describe_inventory(
    db: Session, inventory_id: int, _params: dict[str, Any]
) -> dict[str, Any]:
    inv = _resolve_inventory(db, inventory_id)
    schema = (
        db.query(ApplicationInventorySchema)
        .filter_by(inventory_id=inv.id)
        .one_or_none()
    )
    apps_count = (
        db.query(Application).filter_by(inventory_id=inv.id).count()
    )
    return {
        "filename": inv.original_filename,
        "primary_sheet": inv.primary_sheet,
        "sheets": inv.sheets,
        "schema_proposed": schema is not None,
        "applications_materialised": apps_count,
    }


def _tool_read_sample(
    db: Session, inventory_id: int, params: dict[str, Any]
) -> dict[str, Any]:
    inv = _resolve_inventory(db, inventory_id)
    n_raw = params.get("n", 10)
    try:
        n = int(n_raw)
    except (TypeError, ValueError) as e:
        raise ValueError("'n' must be an integer") from e
    n = max(1, min(SAMPLE_ROWS_MAX, n))
    df = _load_primary_sheet(inv)
    head = df.head(n)
    rows = [_row_to_jsonable(r) for _, r in head.iterrows()]
    return {
        "sheet": inv.primary_sheet,
        "columns": [str(c) for c in df.columns],
        "total_rows": int(len(df)),
        "rows_returned": len(rows),
        "rows": rows,
    }


def _tool_read_row(
    db: Session, inventory_id: int, params: dict[str, Any]
) -> dict[str, Any]:
    inv = _resolve_inventory(db, inventory_id)
    raw_idx = params.get("row_index")
    try:
        idx = int(raw_idx) if raw_idx is not None else -1
    except (TypeError, ValueError) as e:
        raise ValueError("'row_index' must be an integer") from e
    if idx < 0:
        raise ValueError("'row_index' must be >= 0")
    df = _load_primary_sheet(inv)
    if idx >= len(df):
        raise ValueError(
            f"row_index {idx} out of range (sheet has {len(df)} rows)"
        )
    return {
        "sheet": inv.primary_sheet,
        "row_index": idx,
        "data": _row_to_jsonable(df.iloc[idx]),
    }


def _tool_list_capabilities(
    db: Session, project_id: int, params: dict[str, Any]
) -> dict[str, Any]:
    raw_level = params.get("level", 2)
    try:
        level = int(raw_level)
    except (TypeError, ValueError) as e:
        raise ValueError("'level' must be an integer") from e
    if level < 1 or level > 3:
        raise ValueError("'level' must be 1, 2, or 3")
    caps = (
        db.query(BcmCapability)
        .filter_by(project_id=project_id, level=level)
        .order_by(BcmCapability.id.asc())
        .limit(LIST_CAPABILITIES_MAX)
        .all()
    )
    return {
        "level": level,
        "count": len(caps),
        "capabilities": [
            {
                "id": c.id,
                "name": c.name,
                "description": c.description,
                "parent_id": c.parent_id,
            }
            for c in caps
        ],
    }


# ---------------------------------------------------------------------------
# Write tools
# ---------------------------------------------------------------------------


_SCHEMA_OPTIONAL_FIELDS = (
    "description_column",
    "business_function_column",
    "technology_column",
    "owner_column",
    "criticality_column",
    "lifecycle_column",
)


def _tool_propose_schema(
    db: Session, inventory_id: int, params: dict[str, Any]
) -> dict[str, Any]:
    inv = _resolve_inventory(db, inventory_id)
    name_column = str(params.get("name_column") or "").strip()
    if not name_column:
        raise ValueError("'name_column' is required and must be non-empty")

    df = _load_primary_sheet(inv)
    _validate_column_exists(inv, df, name_column, "name_column")

    optionals: dict[str, str | None] = {}
    for field in _SCHEMA_OPTIONAL_FIELDS:
        raw = params.get(field)
        if raw is None or str(raw).strip() == "":
            optionals[field] = None
            continue
        col = str(raw).strip()
        _validate_column_exists(inv, df, col, field)
        optionals[field] = col

    # Upsert the schema row (one per inventory).
    schema = (
        db.query(ApplicationInventorySchema)
        .filter_by(inventory_id=inv.id)
        .one_or_none()
    )
    if schema is None:
        schema = ApplicationInventorySchema(
            inventory_id=inv.id,
            name_column=name_column,
            engine_version=f"it-map-agent/{IT_MAP_AGENT_VERSION}",
            **optionals,
        )
        db.add(schema)
    else:
        schema.name_column = name_column
        for k, v in optionals.items():
            setattr(schema, k, v)
        schema.engine_version = f"it-map-agent/{IT_MAP_AGENT_VERSION}"
    db.flush()

    # Materialise Application rows (one per data row).
    # Re-running propose_schema re-derives the inferred fields, but
    # NEVER deletes Application rows — preserving any mappings the user
    # has already confirmed or dismissed (CASCADE would wipe them).
    # Existing apps get their inferred_* fields refreshed; new apps are
    # created; apps for deleted rows aren't a concern because the
    # inventory is immutable post-upload.
    created = 0
    refreshed = 0
    auto_unmappable = 0
    existing_by_idx = {
        a.row_index: a
        for a in db.query(Application).filter_by(inventory_id=inv.id).all()
    }
    for row_idx, (_, row) in enumerate(df.iterrows()):
        raw = _row_to_jsonable(row)
        name_val = raw.get(name_column)
        inferred_name = (
            str(name_val).strip() if name_val not in (None, "") else None
        )
        unmappable = None
        if not inferred_name:
            unmappable = "Row missing application name"
            auto_unmappable += 1

        app = existing_by_idx.get(row_idx)
        if app is None:
            app = Application(
                inventory_id=inv.id,
                sheet_name=inv.primary_sheet,
                row_index=row_idx,
                raw_row_json=json.dumps(raw),
            )
            db.add(app)
            created += 1
        else:
            refreshed += 1
            app.raw_row_json = json.dumps(raw)

        app.inferred_name = inferred_name
        app.inferred_description = _pick(raw, optionals.get("description_column"))
        app.inferred_business_function = _pick(
            raw, optionals.get("business_function_column")
        )
        app.inferred_technology = _pick(
            raw, optionals.get("technology_column")
        )
        app.inferred_owner = _pick(raw, optionals.get("owner_column"))
        app.inferred_criticality = _pick(
            raw, optionals.get("criticality_column")
        )
        app.inferred_lifecycle = _pick(raw, optionals.get("lifecycle_column"))
        # Only auto-set unmappable when this row genuinely has no name.
        # Don't ever CLEAR a prior unmappable reason here — the agent
        # may explicitly call propose_unmappable to revise.
        if unmappable is not None and app.unmappable_reason is None:
            app.unmappable_reason = unmappable

    db.flush()
    return {
        "name_column": name_column,
        "optional_columns": {k: v for k, v in optionals.items() if v},
        "applications_created": created,
        "applications_refreshed": refreshed,
        "applications_auto_unmappable_missing_name": auto_unmappable,
        "total_rows": int(len(df)),
    }


def _pick(raw: dict[str, Any], col: str | None) -> str | None:
    if col is None:
        return None
    v = raw.get(col)
    if v is None:
        return None
    s = str(v).strip()
    return s if s else None


def _tool_propose_mapping(
    db: Session,
    inventory_id: int,
    project_id: int,
    params: dict[str, Any],
) -> dict[str, Any]:
    rationale = str(params.get("rationale") or "").strip()
    if not rationale:
        raise ValueError("'rationale' is required and must be non-empty")
    raw_idx = params.get("row_index")
    try:
        row_idx = int(raw_idx) if raw_idx is not None else -1
    except (TypeError, ValueError) as e:
        raise ValueError("'row_index' must be an integer") from e
    if row_idx < 0:
        raise ValueError("'row_index' must be >= 0")
    raw_cap = params.get("capability_id")
    try:
        cap_id = int(raw_cap) if raw_cap is not None else -1
    except (TypeError, ValueError) as e:
        raise ValueError("'capability_id' must be an integer") from e
    raw_conf = params.get("confidence")
    try:
        confidence = float(raw_conf) if raw_conf is not None else -1.0
    except (TypeError, ValueError) as e:
        raise ValueError("'confidence' must be a number") from e
    if not (0.0 <= confidence <= 1.0):
        raise ValueError("'confidence' must be between 0 and 1 inclusive")

    app = (
        db.query(Application)
        .filter_by(inventory_id=inventory_id, row_index=row_idx)
        .one_or_none()
    )
    if app is None:
        raise ValueError(
            f"No application for row_index={row_idx}. "
            "Call propose_schema first to materialise applications."
        )

    cap = (
        db.query(BcmCapability)
        .filter_by(id=cap_id, project_id=project_id)
        .one_or_none()
    )
    if cap is None:
        raise ValueError(
            f"capability_id {cap_id} not found in this project's BCM"
        )
    if cap.level != 2:
        raise ValueError(
            f"capability_id {cap_id} is at level {cap.level}; only L2 "
            f"capabilities are valid mapping targets"
        )

    existing = (
        db.query(ApplicationCapabilityMapping)
        .filter_by(application_id=app.id, capability_id=cap.id)
        .one_or_none()
    )
    if existing is not None:
        # Preserve user decisions across re-runs: confirmed and dismissed
        # mappings are NEVER touched by the agent.
        if existing.status in ("confirmed", "dismissed"):
            return {
                "id": existing.id,
                "status": existing.status,
                "outcome": "preserved-user-decision",
            }
        # Suggested: update in place (latest agent suggestion wins).
        existing.confidence = confidence
        existing.rationale = rationale
        existing.engine_version = f"it-map-agent/{IT_MAP_AGENT_VERSION}"
        db.flush()
        return {
            "id": existing.id,
            "status": existing.status,
            "outcome": "updated-suggestion",
        }

    row = ApplicationCapabilityMapping(
        application_id=app.id,
        capability_id=cap.id,
        confidence=confidence,
        rationale=rationale,
        status="suggested",
        engine_version=f"it-map-agent/{IT_MAP_AGENT_VERSION}",
    )
    db.add(row)
    db.flush()
    return {
        "id": row.id,
        "status": row.status,
        "outcome": "created",
    }


def _tool_propose_unmappable(
    db: Session, inventory_id: int, params: dict[str, Any]
) -> dict[str, Any]:
    reason = str(params.get("reason") or "").strip()
    if not reason:
        raise ValueError("'reason' is required and must be non-empty")
    raw_idx = params.get("row_index")
    try:
        row_idx = int(raw_idx) if raw_idx is not None else -1
    except (TypeError, ValueError) as e:
        raise ValueError("'row_index' must be an integer") from e
    if row_idx < 0:
        raise ValueError("'row_index' must be >= 0")
    app = (
        db.query(Application)
        .filter_by(inventory_id=inventory_id, row_index=row_idx)
        .one_or_none()
    )
    if app is None:
        raise ValueError(
            f"No application for row_index={row_idx}. "
            "Call propose_schema first to materialise applications."
        )
    app.unmappable_reason = reason
    db.flush()
    return {"application_id": app.id, "unmappable_reason": reason}


# ---------------------------------------------------------------------------
# Dispatch
# ---------------------------------------------------------------------------


def make_it_map_tool_dispatch(inventory_id: int):
    """Bind a dispatch function to one inventory.

    The orchestrator (Part 3) calls it with ``(name, params, *, db,
    project_id, keys)`` per tool use. Validation failures return
    ``(error_message, True)`` so the LLM gets a chance to retry; only
    truly unexpected exceptions propagate."""

    def _dispatch(
        name: str,
        params: dict[str, Any],
        *,
        db: Session,
        project_id: int,
        keys: LlmKeys,
    ) -> tuple[str, bool]:
        try:
            if name == "describe_inventory":
                return json.dumps(_tool_describe_inventory(db, inventory_id, params)), False
            if name == "read_sample":
                return json.dumps(_tool_read_sample(db, inventory_id, params)), False
            if name == "read_row":
                return json.dumps(_tool_read_row(db, inventory_id, params)), False
            if name == "list_capabilities":
                return json.dumps(_tool_list_capabilities(db, project_id, params)), False
            if name == "propose_schema":
                return json.dumps(_tool_propose_schema(db, inventory_id, params)), False
            if name == "propose_mapping":
                return json.dumps(
                    _tool_propose_mapping(db, inventory_id, project_id, params)
                ), False
            if name == "propose_unmappable":
                return json.dumps(_tool_propose_unmappable(db, inventory_id, params)), False
            return f"Unknown tool: {name}", True
        except ValueError as e:
            # Validation errors come back as tool errors so the model
            # can correct itself, exactly like the DQ agent.
            return f"Tool {name} rejected input: {e}", True
        except Exception as e:  # noqa: BLE001 - surface to the model
            return f"Tool {name} failed: {e}", True

    return _dispatch
