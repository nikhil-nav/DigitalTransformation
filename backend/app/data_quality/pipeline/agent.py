"""Data Quality chat agent: system prompt + tools + dispatch.

The streaming/persistence loop is shared with the BCM agent via
`run_agent_turn_stream(scope="data_quality", system_prompt=..., tools=...,
tool_dispatch=...)`. Only the bits that differ between modules live here.

# Precision commitments (Part 6)

- **Every tool returns data tied to a specific sheet/column/value** so the
  agent can - and must - cite its source.
- **`query_dataset` is a *whitelisted* filter, not a free-form expression.**
  We accept a list of `{column, op, value}` filters with a closed operator
  set (`==`, `!=`, `<`, `<=`, `>`, `>=`, `contains`, `is_null`, `not_null`,
  `in`). No `eval`, no `query`, no `pandas.eval`. The agent cannot smuggle
  arbitrary Python.
- **`flag_issue` writes a normal `DataQualityIssue` row** so any custom
  finding the agent records goes through the same UI/persistence pipeline
  as the deterministic engine's findings. The engine_version is set to
  `dq-agent/<version>` so audits can distinguish them.
"""
from __future__ import annotations

import json
import re
from dataclasses import asdict
from typing import Any

import pandas as pd
from sqlalchemy.orm import Session

from app.data_quality.pipeline.cross import (
    fk_violations as cross_fk_violations,
)
from app.data_quality.pipeline.inspect import inspect_workbook
from app.llm.session import LlmKeys
from app.models import (
    DataQualityColumnProfile,
    DataQualityDataset,
    DataQualityFunctionalDependency,
    DataQualityIssue,
    DataQualityRelationship,
    DataQualitySheetProfile,
)

DQ_AGENT_VERSION = "1.0.0"

SYSTEM_PROMPT = """\
You are a senior data-quality analyst embedded in an enterprise platform. \
Each conversation is scoped to a single Data Quality project and a single \
uploaded workbook (the active dataset). You have read-only tools to \
introspect the workbook's profile, its issues, and its raw cells, plus one \
write tool to record a new issue the user wants to track.

# Hard rules for every answer

1. CITE evidence. Every claim about data must reference a specific \
sheet, column, or value drawn from a tool result. Format citations as \
`[sheet.column]` or `[sheet.column = value]`. Answers without citations \
are unacceptable.
2. NEVER fabricate numbers. If you need a count, percentage, min, max, or \
distinct value, fetch it with `describe_column` or `query_dataset` first. \
Do not estimate or guess.
3. STAY scoped. The dataset is the only source of truth. Do not bring in \
external knowledge about real-world data unless the user explicitly asks.
4. PREFER concision. 3-6 short bullets is better than a wall of prose for \
most questions. Always lead with the answer; supporting evidence after.

# Tools

- `describe_dataset()` - workbook filename + per-sheet (name, row_count, \
column_count, completeness_pct, rag). Call this first for any \
"overview"/"what's wrong" question.
- `describe_column(sheet, column)` - the full persisted profile for one \
column: type, null %, distinct count, top values, numeric stats, outliers, \
pattern, RAG. Cheap; call freely.
- `list_issues(sheet?, severity?, column?)` - persisted issues. Use when \
the user asks "what issues" or "what's wrong with X".
- `query_dataset(sheet, filters?, limit=10, columns?)` - filtered rows \
from the actual workbook. `filters` is a list of {column, op, value}; \
`op` is one of `==`, `!=`, `<`, `<=`, `>`, `>=`, `contains`, `is_null`, \
`not_null`, `in`. Use this to sample concrete rows you want to cite.
- `flag_issue(sheet, column?, dimension, severity, description, sample_values?)` \
- record a custom user-discovered issue. Only call when the user asks you \
to track something the engine missed.

# Anti-patterns

- DO NOT respond from memory if you have not seen the profile yet - call \
`describe_dataset()` first.
- DO NOT claim a column is "mostly clean" without quoting the null % and \
RAG from `describe_column`.
- DO NOT suggest specific fixes (e.g. "drop those rows") without first \
quoting at least one offending value via `query_dataset` or a top-value \
from `describe_column`.
"""


# --- Tool specifications (Anthropic-shaped; provider translates) ---

DQ_TOOLS: list[dict[str, Any]] = [
    {
        "name": "describe_dataset",
        "description": (
            "Return the workbook filename and a per-sheet summary "
            "(name, row_count, column_count, completeness_pct, rag) for the "
            "currently scoped dataset."
        ),
        "input_schema": {
            "type": "object",
            "properties": {},
            "additionalProperties": False,
        },
    },
    {
        "name": "describe_column",
        "description": (
            "Return the full persisted profile for one column on one sheet "
            "of the dataset. Errors if sheet or column is unknown."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "sheet": {"type": "string"},
                "column": {"type": "string"},
            },
            "required": ["sheet", "column"],
            "additionalProperties": False,
        },
    },
    {
        "name": "list_issues",
        "description": (
            "List persisted issues for the dataset, optionally filtered by "
            "sheet, column, or severity. Returns up to 100 issues per call."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "sheet": {"type": "string"},
                "column": {"type": "string"},
                "severity": {
                    "type": "string",
                    "enum": ["low", "medium", "high", "critical"],
                },
            },
            "additionalProperties": False,
        },
    },
    {
        "name": "query_dataset",
        "description": (
            "Return up to `limit` rows from a sheet, optionally filtered. "
            "Filters are a list of {column, op, value} where op is one of "
            "==, !=, <, <=, >, >=, contains, is_null, not_null, in. "
            "Use `columns` to project only specific column names."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "sheet": {"type": "string"},
                "filters": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "column": {"type": "string"},
                            "op": {
                                "type": "string",
                                "enum": [
                                    "==", "!=", "<", "<=", ">", ">=",
                                    "contains", "is_null", "not_null", "in",
                                ],
                            },
                            "value": {},
                        },
                        "required": ["column", "op"],
                        "additionalProperties": False,
                    },
                },
                "limit": {"type": "integer", "minimum": 1, "maximum": 50},
                "columns": {"type": "array", "items": {"type": "string"}},
            },
            "required": ["sheet"],
            "additionalProperties": False,
        },
    },
    {
        "name": "flag_issue",
        "description": (
            "Record a new data-quality issue discovered during the chat. "
            "Writes a persisted DataQualityIssue row; visible immediately "
            "in the dashboard's issues list. Only use when the user asks "
            "you to track a finding."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "sheet": {"type": "string"},
                "column": {"type": "string"},
                "dimension": {
                    "type": "string",
                    "enum": [
                        "completeness",
                        "consistency",
                        "uniqueness",
                        "validity",
                        "accuracy",
                        "redundancy",
                    ],
                },
                "severity": {
                    "type": "string",
                    "enum": ["low", "medium", "high", "critical"],
                },
                "description": {"type": "string", "minLength": 1, "maxLength": 1000},
                "sample_values": {
                    "type": "array",
                    "items": {"type": "string"},
                    "maxItems": 20,
                },
            },
            "required": ["sheet", "dimension", "severity", "description"],
            "additionalProperties": False,
        },
    },
]


# --- Helpers ---

QUERY_LIMIT_DEFAULT = 10
QUERY_LIMIT_MAX = 50
LIST_ISSUES_MAX = 100


def _resolve_dataset(db: Session, dataset_id: int) -> DataQualityDataset:
    ds = db.query(DataQualityDataset).filter_by(id=dataset_id).one_or_none()
    if ds is None:
        raise ValueError(f"Dataset {dataset_id} not found")
    return ds


def _load_workbook_sheets(ds: DataQualityDataset) -> dict[str, pd.DataFrame]:
    from pathlib import Path
    return pd.read_excel(Path(ds.local_path), sheet_name=None, dtype=object)


def _apply_filter(
    df: pd.DataFrame, column: str, op: str, value: Any
) -> pd.DataFrame:
    if column not in df.columns:
        raise ValueError(f"Unknown column '{column}'")
    s = df[column]
    if op == "is_null":
        return df[s.isna() | (s.astype(str).str.strip() == "")]
    if op == "not_null":
        return df[s.notna() & (s.astype(str).str.strip() != "")]
    if op == "in":
        if not isinstance(value, list):
            raise ValueError("'in' op requires a list value")
        return df[s.isin(value)]
    if op == "contains":
        if not isinstance(value, str):
            raise ValueError("'contains' op requires a string value")
        return df[s.astype(str).str.contains(re.escape(value), case=False, na=False)]
    if op in {"==", "!=", "<", "<=", ">", ">="}:
        # For numeric comparisons, try numeric coercion; for equality, fall
        # back to string compare on coerce failure so the agent's filters
        # still work on string-typed id columns.
        if op in {"<", "<=", ">", ">="}:
            numeric = pd.to_numeric(s, errors="coerce")
            try:
                numeric_value = float(value)
            except (TypeError, ValueError) as e:
                raise ValueError(f"'{op}' op requires a numeric value") from e
            if op == "<":
                return df[numeric < numeric_value]
            if op == "<=":
                return df[numeric <= numeric_value]
            if op == ">":
                return df[numeric > numeric_value]
            return df[numeric >= numeric_value]
        # Equality: prefer raw-object comparison; fall back to string.
        as_str = s.astype(str)
        target_str = str(value)
        if op == "==":
            return df[(s == value) | (as_str == target_str)]
        return df[(s != value) & (as_str != target_str)]
    raise ValueError(f"Unsupported op '{op}'")


def _column_profile_payload(c: DataQualityColumnProfile) -> dict[str, Any]:
    return {
        "name": c.name,
        "ordinal": c.ordinal,
        "semantic_type": c.semantic_type,
        "inferred_dtype": c.inferred_dtype,
        "rag": c.rag,
        "null_count": c.null_count,
        "null_pct": round(c.null_pct, 2),
        "distinct_count": c.distinct_count,
        "distinct_pct": round(c.distinct_pct, 2),
        "type_mismatch_count": c.type_mismatch_count,
        "top_values": c.top_values,
        "numeric": {
            "min": c.numeric_min,
            "max": c.numeric_max,
            "mean": c.numeric_mean,
            "median": c.numeric_median,
            "std": c.numeric_std,
            "p25": c.numeric_p25,
            "p75": c.numeric_p75,
            "outlier_iqr_count": c.outlier_iqr_count,
            "outlier_mad_count": c.outlier_mad_count,
        },
        "date": {"min": c.date_min, "max": c.date_max},
        "pattern": {
            "label": c.pattern_label,
            "conformance_pct": c.pattern_conformance_pct,
        },
        "range": {
            "min": c.range_min,
            "max": c.range_max,
            "violation_count": c.range_violation_count,
        },
    }


# --- Tool implementations ---

def _tool_describe_dataset(
    db: Session, dataset_id: int, _params: dict[str, Any]
) -> dict[str, Any]:
    ds = _resolve_dataset(db, dataset_id)
    sheet_profiles = (
        db.query(DataQualitySheetProfile)
        .filter_by(dataset_id=ds.id)
        .order_by(DataQualitySheetProfile.id.asc())
        .all()
    )
    return {
        "filename": ds.original_filename,
        "uploaded_at": ds.uploaded_at.isoformat() if ds.uploaded_at else None,
        "profiled_at": ds.profiled_at.isoformat() if ds.profiled_at else None,
        "annotation_status": ds.annotation_status,
        "sheets": [
            {
                "name": s.sheet_name,
                "row_count": s.row_count,
                "column_count": s.column_count,
                "completeness_pct": round(s.completeness_pct, 2),
                "exact_duplicate_row_count": s.exact_duplicate_row_count,
                "rag": s.rag,
            }
            for s in sheet_profiles
        ],
    }


def _tool_describe_column(
    db: Session, dataset_id: int, params: dict[str, Any]
) -> dict[str, Any]:
    sheet = str(params.get("sheet", ""))
    column = str(params.get("column", ""))
    profile = (
        db.query(DataQualityColumnProfile)
        .join(
            DataQualitySheetProfile,
            DataQualityColumnProfile.sheet_profile_id == DataQualitySheetProfile.id,
        )
        .filter(
            DataQualitySheetProfile.dataset_id == dataset_id,
            DataQualitySheetProfile.sheet_name == sheet,
            DataQualityColumnProfile.name == column,
        )
        .one_or_none()
    )
    if profile is None:
        raise ValueError(f"Column '{column}' on sheet '{sheet}' not found")
    return _column_profile_payload(profile)


def _tool_list_issues(
    db: Session, dataset_id: int, params: dict[str, Any]
) -> dict[str, Any]:
    q = db.query(DataQualityIssue).filter_by(dataset_id=dataset_id)
    if (sheet := params.get("sheet")) is not None:
        q = q.filter(DataQualityIssue.sheet_name == str(sheet))
    if (col := params.get("column")) is not None:
        q = q.filter(DataQualityIssue.column_name == str(col))
    if (sev := params.get("severity")) is not None:
        q = q.filter(DataQualityIssue.severity == str(sev))
    rows = (
        q.order_by(DataQualityIssue.severity.desc(), DataQualityIssue.id.asc())
        .limit(LIST_ISSUES_MAX)
        .all()
    )
    return {
        "issues": [
            {
                "id": r.id,
                "sheet": r.sheet_name,
                "column": r.column_name,
                "dimension": r.dimension,
                "severity": r.severity,
                "description": r.description,
                "sample_values": r.sample_values,
                "ai_narrative": r.ai_narrative,
                "ai_fix": r.ai_fix,
            }
            for r in rows
        ],
        "count": len(rows),
        "truncated": len(rows) == LIST_ISSUES_MAX,
    }


def _tool_query_dataset(
    db: Session, dataset_id: int, params: dict[str, Any]
) -> dict[str, Any]:
    ds = _resolve_dataset(db, dataset_id)
    sheet = str(params.get("sheet", ""))
    sheets = _load_workbook_sheets(ds)
    if sheet not in sheets:
        raise ValueError(
            f"Unknown sheet '{sheet}'. Available: {sorted(sheets.keys())}"
        )
    df = sheets[sheet]

    raw_filters = params.get("filters") or []
    if not isinstance(raw_filters, list):
        raise ValueError("'filters' must be a list")
    for f in raw_filters:
        if not isinstance(f, dict):
            raise ValueError("Each filter must be an object")
        df = _apply_filter(df, str(f["column"]), str(f["op"]), f.get("value"))

    columns = params.get("columns")
    if columns is not None:
        if not isinstance(columns, list):
            raise ValueError("'columns' must be a list of column names")
        missing = [c for c in columns if c not in df.columns]
        if missing:
            raise ValueError(f"Unknown column(s) in 'columns': {missing}")
        df = df[columns]

    raw_limit = params.get("limit", QUERY_LIMIT_DEFAULT)
    try:
        limit = int(raw_limit)
    except (TypeError, ValueError) as e:
        raise ValueError("'limit' must be an integer") from e
    limit = max(1, min(QUERY_LIMIT_MAX, limit))

    total_matches = int(len(df))
    sliced = df.head(limit)
    # Convert to JSON-safe rows; pandas timestamps -> ISO, NaN -> None
    rows: list[dict[str, Any]] = []
    for _, row in sliced.iterrows():
        out: dict[str, Any] = {}
        for col, val in row.items():
            if pd.isna(val):
                out[str(col)] = None
            elif isinstance(val, pd.Timestamp):
                out[str(col)] = val.isoformat()
            else:
                out[str(col)] = val if isinstance(val, (int, float, str, bool)) else str(val)
        rows.append(out)
    return {
        "sheet": sheet,
        "row_count_total": total_matches,
        "rows_returned": len(rows),
        "limit_applied": limit,
        "rows": rows,
    }


def _tool_flag_issue(
    db: Session, dataset_id: int, params: dict[str, Any]
) -> dict[str, Any]:
    description = str(params.get("description", "")).strip()
    if not description:
        raise ValueError("'description' is required and must be non-empty")
    sheet = str(params.get("sheet", "")).strip()
    if not sheet:
        raise ValueError("'sheet' is required")
    dimension = str(params.get("dimension", "")).strip()
    if dimension not in {
        "completeness",
        "consistency",
        "uniqueness",
        "validity",
        "accuracy",
        "redundancy",
    }:
        raise ValueError(f"Unsupported dimension '{dimension}'")
    severity = str(params.get("severity", "")).strip()
    if severity not in {"low", "medium", "high", "critical"}:
        raise ValueError(f"Unsupported severity '{severity}'")
    column = params.get("column")
    column = str(column) if column is not None else None
    raw_samples = params.get("sample_values") or []
    if not isinstance(raw_samples, list):
        raise ValueError("'sample_values' must be a list")
    samples = [str(v) for v in raw_samples][:20]

    row = DataQualityIssue(
        dataset_id=dataset_id,
        sheet_name=sheet,
        column_name=column,
        dimension=dimension,
        severity=severity,
        description=description,
        sample_value_count=len(samples),
        sample_values_json=json.dumps(samples),
        engine_version=f"dq-agent/{DQ_AGENT_VERSION}",
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return {
        "id": row.id,
        "sheet": row.sheet_name,
        "column": row.column_name,
        "dimension": row.dimension,
        "severity": row.severity,
        "description": row.description,
    }


# --- Dispatch ---

def make_dq_tool_dispatch(dataset_id: int):
    """Bind a dispatch function to one dataset; the streaming loop calls it
    with `(name, params, *, db, project_id, keys)` for each tool use."""

    def _dispatch(
        name: str,
        params: dict[str, Any],
        *,
        db: Session,
        project_id: int,
        keys: LlmKeys,
    ) -> tuple[str, bool]:
        try:
            if name == "describe_dataset":
                return json.dumps(_tool_describe_dataset(db, dataset_id, params)), False
            if name == "describe_column":
                return json.dumps(_tool_describe_column(db, dataset_id, params)), False
            if name == "list_issues":
                return json.dumps(_tool_list_issues(db, dataset_id, params)), False
            if name == "query_dataset":
                return json.dumps(_tool_query_dataset(db, dataset_id, params)), False
            if name == "flag_issue":
                return json.dumps(_tool_flag_issue(db, dataset_id, params)), False
            return f"Unknown tool: {name}", True
        except ValueError as e:
            # Validation errors: return as tool error so the model can retry
            return f"Tool {name} rejected input: {e}", True
        except Exception as e:  # noqa: BLE001 - surface to the model
            return f"Tool {name} failed: {e}", True

    return _dispatch
