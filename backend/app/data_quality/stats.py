"""Statistical engine for the Data Quality module.

Pure functions only - no DB, no I/O. The caller in `profile.py` loads each
sheet into a pandas DataFrame and passes it here; this module returns a
frozen `SheetProfile` describing the metrics and any detected issues. The
caller persists the result.

# Precision commitments

- **Full dataset, no sampling.** Every check looks at every value in every
  column. Performance budget is ~3s for a 10k x 20 sheet on a dev laptop.
- **Conservative type inference.** A semantic type (`integer`, `float`,
  `boolean`, `date`) is only assigned when at least
  `TYPE_INFERENCE_THRESHOLD` (99%) of non-null values parse under explicit
  predicates. Below that threshold the column is `string` and no type
  mismatches are recorded (everything in a string column is, by definition,
  string-shaped). When the type IS assigned, the residual non-conforming
  values are persisted as `type_mismatch_count` and surfaced as a high-
  severity issue.
- **Pattern detection is a curated catalogue.** Only runs on `string`
  columns; only the highest-conformance pattern is assigned, and only when
  it matches at least `PATTERN_CONFORMANCE_THRESHOLD` (95%) of non-null
  values. Non-matching values become "counter-examples" surfaced as a
  consistency issue.
- **Outliers reported through two methods.** Tukey IQR fence (1.5x IQR) and
  modified z-score on MAD (Iglewicz & Hoaglin, threshold 3.5). Both counts
  are persisted; the dashboard shows both so users can see where the methods
  disagree.
- **Deterministic.** Same DataFrame in -> identical result out. No
  randomness, no clocks except `computed_at` (which lives in the caller).
- **Reproducibility.** `STATS_ENGINE_VERSION` is persisted alongside every
  produced row. Bump it for any change that alters output.
"""
from __future__ import annotations

import math
import re
from collections import Counter
from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Any

import pandas as pd

# Bump for any change that alters numbers, type assignments, pattern labels,
# RAG rules, or issue descriptions.
STATS_ENGINE_VERSION = "1.0.0"

# Precision thresholds (see module docstring).
TYPE_INFERENCE_THRESHOLD = 0.99
PATTERN_CONFORMANCE_THRESHOLD = 0.95
MAD_MODIFIED_Z_THRESHOLD = 3.5
IQR_FENCE_MULTIPLIER = 1.5

# Cap how many counter-examples / sample values we keep in an issue. Keeps
# the dashboard scannable while still giving the user concrete evidence.
MAX_SAMPLE_VALUES = 10
TOP_VALUES_LIMIT = 10


# --------------------------------------------------------------------------
# Result dataclasses
# --------------------------------------------------------------------------


@dataclass(frozen=True)
class IssueDraft:
    """An issue as emitted by the engine, before it is persisted."""

    sheet_name: str
    column_name: str | None
    dimension: str
    severity: str
    description: str
    sample_values: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class ColumnProfile:
    name: str
    ordinal: int
    inferred_dtype: str
    semantic_type: str  # boolean | integer | float | date | string | empty
    type_mismatch_count: int

    null_count: int
    null_pct: float
    distinct_count: int
    distinct_pct: float
    top_values: list[tuple[str, int]]

    # Populated only for numeric semantic types
    numeric_min: float | None
    numeric_max: float | None
    numeric_mean: float | None
    numeric_median: float | None
    numeric_std: float | None
    numeric_p25: float | None
    numeric_p75: float | None

    # Populated only for date semantic types (ISO 8601 strings)
    date_min: str | None
    date_max: str | None

    # Populated only for string semantic types if a catalogue pattern matched
    pattern_label: str | None
    pattern_conformance_pct: float | None

    # Populated only for numeric semantic types
    outlier_iqr_count: int | None
    outlier_mad_count: int | None

    # User-supplied bounds (forwarded unchanged from prior profile if any)
    range_min: float | None
    range_max: float | None
    range_violation_count: int | None

    rag: str  # green | amber | red


@dataclass(frozen=True)
class SheetProfile:
    sheet_name: str
    row_count: int
    column_count: int
    exact_duplicate_row_count: int
    completeness_pct: float
    rag: str
    columns: list[ColumnProfile]
    issues: list[IssueDraft]


# --------------------------------------------------------------------------
# Pattern catalogue
# --------------------------------------------------------------------------

# Compiled once at import.  Order matters: when two patterns both match
# >=95% of values we report the FIRST one in this list (more specific first).
_PATTERN_CATALOGUE: list[tuple[str, re.Pattern[str]]] = [
    (
        "email",
        re.compile(r"^[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}$"),
    ),
    ("uuid", re.compile(r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$")),
    ("url", re.compile(r"^https?://[^\s]+$")),
    ("e164_phone", re.compile(r"^\+[1-9]\d{1,14}$")),
    (
        "ipv4",
        re.compile(
            r"^(25[0-5]|2[0-4]\d|1\d{2}|[1-9]?\d)"
            r"(\.(25[0-5]|2[0-4]\d|1\d{2}|[1-9]?\d)){3}$"
        ),
    ),
    ("ipv6", re.compile(r"^([0-9a-fA-F]{1,4}:){7}[0-9a-fA-F]{1,4}$")),
    ("iso_date", re.compile(r"^\d{4}-\d{2}-\d{2}$")),
    ("us_zip", re.compile(r"^\d{5}(-\d{4})?$")),
    (
        "ca_postal",
        re.compile(r"^[ABCEGHJ-NPRSTVXY]\d[A-Z][ -]?\d[A-Z]\d$", re.IGNORECASE),
    ),
    (
        "currency_usd",
        re.compile(r"^-?\$?\d{1,3}(,\d{3})*(\.\d{1,2})?$|^-?\$?\d+(\.\d{1,2})?$"),
    ),
]


# --------------------------------------------------------------------------
# Type-inference predicates
# --------------------------------------------------------------------------

# Bool detection: only literal Python bool. Strings like "yes"/"no" are too
# ambiguous and stay as strings.
def _is_bool(v: Any) -> bool:
    return isinstance(v, bool)


def _is_integer(v: Any) -> bool:
    if isinstance(v, bool):  # bool is a subclass of int but we want to exclude
        return False
    if isinstance(v, int):
        return True
    if isinstance(v, float):
        return v.is_integer() and not math.isnan(v) and not math.isinf(v)
    if isinstance(v, str):
        s = v.strip()
        if not s:
            return False
        try:
            int(s)
            return True
        except ValueError:
            return False
    return False


def _is_float(v: Any) -> bool:
    if isinstance(v, bool):
        return False
    if isinstance(v, (int, float)):
        if isinstance(v, float) and (math.isnan(v) or math.isinf(v)):
            return False
        return True
    if isinstance(v, str):
        s = v.strip()
        if not s:
            return False
        try:
            float(s)
            return True
        except ValueError:
            return False
    return False


_DATE_FORMATS = (
    "%Y-%m-%d",
    "%Y/%m/%d",
    "%d/%m/%Y",
    "%m/%d/%Y",
    "%d-%m-%Y",
    "%Y-%m-%dT%H:%M:%S",
    "%Y-%m-%d %H:%M:%S",
)


def _is_date(v: Any) -> bool:
    if isinstance(v, (date, datetime, pd.Timestamp)):
        return True
    if isinstance(v, str):
        s = v.strip()
        if not s:
            return False
        for fmt in _DATE_FORMATS:
            try:
                datetime.strptime(s, fmt)
                return True
            except ValueError:
                continue
    return False


def _as_float(v: Any) -> float | None:
    """Coerce to float when possible; returns None for unparseable inputs."""
    if isinstance(v, bool):
        return float(v)
    if isinstance(v, (int, float)):
        f = float(v)
        if math.isnan(f) or math.isinf(f):
            return None
        return f
    if isinstance(v, str):
        s = v.strip()
        if not s:
            return None
        try:
            f = float(s)
            if math.isnan(f) or math.isinf(f):
                return None
            return f
        except ValueError:
            return None
    return None


def _as_date_iso(v: Any) -> str | None:
    if isinstance(v, datetime):
        return v.date().isoformat() if v.time() == datetime.min.time() else v.isoformat()
    if isinstance(v, pd.Timestamp):
        py = v.to_pydatetime()
        return py.date().isoformat() if py.time() == datetime.min.time() else py.isoformat()
    if isinstance(v, date):
        return v.isoformat()
    if isinstance(v, str):
        s = v.strip()
        for fmt in _DATE_FORMATS:
            try:
                parsed = datetime.strptime(s, fmt)
                if parsed.time() == datetime.min.time():
                    return parsed.date().isoformat()
                return parsed.isoformat()
            except ValueError:
                continue
    return None


# --------------------------------------------------------------------------
# Helpers
# --------------------------------------------------------------------------


def _is_null(v: Any) -> bool:
    """Treat None, NaN, and empty/whitespace strings as null."""
    if v is None:
        return True
    if isinstance(v, float) and math.isnan(v):
        return True
    if isinstance(v, str) and v.strip() == "":
        return True
    # pandas NA sentinel
    try:
        if pd.isna(v):  # type: ignore[arg-type]
            return True
    except (TypeError, ValueError):
        pass
    return False


def _value_to_display_str(v: Any) -> str:
    if isinstance(v, datetime):
        return v.isoformat()
    if isinstance(v, date):
        return v.isoformat()
    if isinstance(v, pd.Timestamp):
        return v.to_pydatetime().isoformat()
    return str(v)


def _outliers_iqr(values: list[float]) -> int:
    if len(values) < 4:
        return 0
    s = pd.Series(values)
    q1 = float(s.quantile(0.25))
    q3 = float(s.quantile(0.75))
    iqr = q3 - q1
    if iqr == 0:
        return 0
    low = q1 - IQR_FENCE_MULTIPLIER * iqr
    high = q3 + IQR_FENCE_MULTIPLIER * iqr
    return int(sum(1 for v in values if v < low or v > high))


def _outliers_mad(values: list[float]) -> int:
    """Modified z-score using MAD (Iglewicz & Hoaglin, 1993).

    A value is flagged when |0.6745 * (x - median) / MAD| > 3.5. When MAD is
    zero (more than half the values are identical), fall back to the mean
    absolute deviation to avoid division by zero; if that is also zero, no
    outlier can be defined, return 0.
    """
    if len(values) < 4:
        return 0
    s = pd.Series(values)
    med = float(s.median())
    abs_dev = (s - med).abs()
    mad = float(abs_dev.median())
    if mad == 0:
        meanad = float(abs_dev.mean())
        if meanad == 0:
            return 0
        # 1.253314 is the constant relating mean abs dev to std for normal data
        scaled = (s - med).abs() / (1.253314 * meanad)
    else:
        scaled = (s - med).abs() * 0.6745 / mad
    return int((scaled > MAD_MODIFIED_Z_THRESHOLD).sum())


def _infer_semantic_type(
    non_null_values: list[Any],
) -> tuple[str, int, list[Any]]:
    """Return (semantic_type, type_mismatch_count, mismatched_samples)."""
    n = len(non_null_values)
    if n == 0:
        return ("empty", 0, [])

    candidates = (
        ("boolean", _is_bool),
        ("integer", _is_integer),
        ("float", _is_float),
        ("date", _is_date),
    )
    for name, predicate in candidates:
        non_matching = [v for v in non_null_values if not predicate(v)]
        conformance = (n - len(non_matching)) / n
        if conformance >= TYPE_INFERENCE_THRESHOLD:
            return (name, len(non_matching), non_matching[:MAX_SAMPLE_VALUES])

    return ("string", 0, [])


def _detect_pattern(
    string_values: list[str],
) -> tuple[str | None, float | None, list[str]]:
    """Pick the highest-conformance pattern in the catalogue that beats the
    threshold. Returns (label, conformance_pct, counter_examples)."""
    n = len(string_values)
    if n == 0:
        return (None, None, [])

    best: tuple[str, float] | None = None
    best_counter: list[str] = []
    for label, regex in _PATTERN_CATALOGUE:
        matches = [bool(regex.match(v)) for v in string_values]
        conformance = sum(matches) / n
        if conformance >= PATTERN_CONFORMANCE_THRESHOLD:
            if best is None or conformance > best[1]:
                best = (label, conformance)
                best_counter = [
                    v
                    for v, m in zip(string_values, matches, strict=True)
                    if not m
                ][:MAX_SAMPLE_VALUES]
    if best is None:
        return (None, None, [])
    return (best[0], best[1] * 100.0, best_counter)


def _compute_column_rag(
    *,
    null_pct: float,
    distinct_count: int,
    type_mismatch_count: int,
    pattern_conformance_pct: float | None,
    range_violation_count: int | None,
) -> str:
    # Hard problems first.
    if type_mismatch_count > 0:
        return "red"
    if (range_violation_count or 0) > 0:
        return "red"
    if null_pct > 50.0:
        return "red"
    # Moderate problems.
    if null_pct > 20.0:
        return "amber"
    if pattern_conformance_pct is not None and pattern_conformance_pct < 100.0:
        return "amber"
    if distinct_count == 0:
        return "amber"  # empty column
    if null_pct >= 5.0:
        return "amber"
    return "green"


def _compute_sheet_rag(
    column_rags: list[str], exact_duplicate_row_count: int
) -> str:
    if exact_duplicate_row_count > 0 or "red" in column_rags:
        return "red"
    if "amber" in column_rags:
        return "amber"
    return "green"


# --------------------------------------------------------------------------
# Per-column profiling
# --------------------------------------------------------------------------


def profile_column(
    series: pd.Series,
    *,
    ordinal: int,
    sheet_name: str,
    range_min: float | None = None,
    range_max: float | None = None,
) -> tuple[ColumnProfile, list[IssueDraft]]:
    """Profile one column and emit issues for any precision-grade findings."""
    name = str(series.name)
    raw_values: list[Any] = list(series.values)
    total = len(raw_values)

    non_nulls = [v for v in raw_values if not _is_null(v)]
    null_count = total - len(non_nulls)
    null_pct = (null_count / total * 100.0) if total > 0 else 0.0

    distinct_count = len({_value_to_display_str(v) for v in non_nulls})
    distinct_pct = (distinct_count / total * 100.0) if total > 0 else 0.0

    semantic_type, type_mismatch_count, mismatched_samples = _infer_semantic_type(
        non_nulls
    )
    inferred_dtype = str(series.dtype)

    # Top values (string representation, for display)
    counter = Counter(_value_to_display_str(v) for v in non_nulls)
    top_values = counter.most_common(TOP_VALUES_LIMIT)

    # Numeric stats only when type is numeric
    numeric_min = numeric_max = numeric_mean = None
    numeric_median = numeric_std = numeric_p25 = numeric_p75 = None
    outlier_iqr_count: int | None = None
    outlier_mad_count: int | None = None
    range_violation_count: int | None = None

    if semantic_type in {"integer", "float"}:
        nums = [_as_float(v) for v in non_nulls]
        nums = [n for n in nums if n is not None]
        if nums:
            s = pd.Series(nums)
            numeric_min = float(s.min())
            numeric_max = float(s.max())
            numeric_mean = float(s.mean())
            numeric_median = float(s.median())
            numeric_std = float(s.std(ddof=1)) if len(nums) > 1 else 0.0
            numeric_p25 = float(s.quantile(0.25))
            numeric_p75 = float(s.quantile(0.75))
            outlier_iqr_count = _outliers_iqr(nums)
            outlier_mad_count = _outliers_mad(nums)

            if range_min is not None or range_max is not None:
                lo = range_min if range_min is not None else float("-inf")
                hi = range_max if range_max is not None else float("inf")
                range_violation_count = int(sum(1 for v in nums if v < lo or v > hi))

    # Date stats only when type is date
    date_min: str | None = None
    date_max: str | None = None
    if semantic_type == "date":
        iso = [_as_date_iso(v) for v in non_nulls]
        iso = [d for d in iso if d is not None]
        if iso:
            date_min = min(iso)
            date_max = max(iso)

    # Pattern detection only when type is string
    pattern_label: str | None = None
    pattern_conformance_pct: float | None = None
    pattern_counter_examples: list[str] = []
    if semantic_type == "string":
        string_values = [_value_to_display_str(v) for v in non_nulls]
        pattern_label, pattern_conformance_pct, pattern_counter_examples = (
            _detect_pattern(string_values)
        )

    rag = _compute_column_rag(
        null_pct=null_pct,
        distinct_count=distinct_count,
        type_mismatch_count=type_mismatch_count,
        pattern_conformance_pct=pattern_conformance_pct,
        range_violation_count=range_violation_count,
    )

    profile = ColumnProfile(
        name=name,
        ordinal=ordinal,
        inferred_dtype=inferred_dtype,
        semantic_type=semantic_type,
        type_mismatch_count=type_mismatch_count,
        null_count=null_count,
        null_pct=null_pct,
        distinct_count=distinct_count,
        distinct_pct=distinct_pct,
        top_values=top_values,
        numeric_min=numeric_min,
        numeric_max=numeric_max,
        numeric_mean=numeric_mean,
        numeric_median=numeric_median,
        numeric_std=numeric_std,
        numeric_p25=numeric_p25,
        numeric_p75=numeric_p75,
        date_min=date_min,
        date_max=date_max,
        pattern_label=pattern_label,
        pattern_conformance_pct=pattern_conformance_pct,
        outlier_iqr_count=outlier_iqr_count,
        outlier_mad_count=outlier_mad_count,
        range_min=range_min,
        range_max=range_max,
        range_violation_count=range_violation_count,
        rag=rag,
    )

    issues: list[IssueDraft] = []
    if null_pct > 50.0:
        issues.append(
            IssueDraft(
                sheet_name=sheet_name,
                column_name=name,
                dimension="completeness",
                severity="high",
                description=(
                    f"Column '{name}' is {null_pct:.1f}% null "
                    f"({null_count} of {total} rows)."
                ),
            )
        )
    elif null_pct > 20.0:
        issues.append(
            IssueDraft(
                sheet_name=sheet_name,
                column_name=name,
                dimension="completeness",
                severity="medium",
                description=(
                    f"Column '{name}' is {null_pct:.1f}% null "
                    f"({null_count} of {total} rows)."
                ),
            )
        )
    elif null_pct >= 5.0:
        issues.append(
            IssueDraft(
                sheet_name=sheet_name,
                column_name=name,
                dimension="completeness",
                severity="low",
                description=(
                    f"Column '{name}' is {null_pct:.1f}% null "
                    f"({null_count} of {total} rows)."
                ),
            )
        )

    if type_mismatch_count > 0:
        issues.append(
            IssueDraft(
                sheet_name=sheet_name,
                column_name=name,
                dimension="consistency",
                severity="high",
                description=(
                    f"Column '{name}' was inferred as '{semantic_type}' but "
                    f"{type_mismatch_count} of {len(non_nulls)} non-null "
                    f"values do not conform."
                ),
                sample_values=[_value_to_display_str(v) for v in mismatched_samples],
            )
        )

    if (
        pattern_label is not None
        and pattern_conformance_pct is not None
        and pattern_conformance_pct < 100.0
    ):
        issues.append(
            IssueDraft(
                sheet_name=sheet_name,
                column_name=name,
                dimension="consistency",
                severity="medium",
                description=(
                    f"Column '{name}' looks like '{pattern_label}' "
                    f"({pattern_conformance_pct:.1f}% conformance); "
                    f"some values don't match the pattern."
                ),
                sample_values=pattern_counter_examples,
            )
        )

    if range_violation_count is not None and range_violation_count > 0:
        issues.append(
            IssueDraft(
                sheet_name=sheet_name,
                column_name=name,
                dimension="validity",
                severity="high",
                description=(
                    f"Column '{name}' has {range_violation_count} value(s) "
                    f"outside the configured bounds "
                    f"[{range_min}, {range_max}]."
                ),
            )
        )

    if outlier_iqr_count is not None and outlier_iqr_count > 0:
        issues.append(
            IssueDraft(
                sheet_name=sheet_name,
                column_name=name,
                dimension="accuracy",
                severity="low",
                description=(
                    f"Column '{name}' has {outlier_iqr_count} Tukey-IQR "
                    f"outlier(s)"
                    + (
                        f" and {outlier_mad_count} MAD outlier(s)"
                        if outlier_mad_count is not None
                        else ""
                    )
                    + "; investigate whether they are valid extremes."
                ),
            )
        )

    if distinct_count == 1 and null_count < total:
        issues.append(
            IssueDraft(
                sheet_name=sheet_name,
                column_name=name,
                dimension="uniqueness",
                severity="low",
                description=(
                    f"Column '{name}' has only one distinct value across "
                    f"{total - null_count} non-null rows; consider dropping."
                ),
            )
        )

    return profile, issues


# --------------------------------------------------------------------------
# Sheet-level helpers
# --------------------------------------------------------------------------


def _detect_duplicate_columns(df: pd.DataFrame) -> list[tuple[str, str]]:
    """Return pairs of column names whose values are exactly equal row-wise."""
    cols = list(df.columns)
    pairs: list[tuple[str, str]] = []
    for i in range(len(cols)):
        for j in range(i + 1, len(cols)):
            a = df[cols[i]].astype(object)
            b = df[cols[j]].astype(object)
            # Treat NaN-vs-NaN as equal for this comparison.
            a_eq_b = (a.isna() & b.isna()) | (a == b)
            if bool(a_eq_b.all()):
                pairs.append((str(cols[i]), str(cols[j])))
    return pairs


def _exact_duplicate_row_count(df: pd.DataFrame) -> int:
    if len(df) == 0:
        return 0
    return int(df.duplicated(keep=False).sum())


# --------------------------------------------------------------------------
# Public entry point
# --------------------------------------------------------------------------


def profile_sheet(
    df: pd.DataFrame,
    *,
    sheet_name: str,
    bounds: dict[str, tuple[float | None, float | None]] | None = None,
) -> SheetProfile:
    """Profile every column in `df` and return a complete SheetProfile.

    Args:
        df: a DataFrame loaded with `dtype=object` so raw values reach the
            type-inference predicates.
        sheet_name: the workbook sheet name, used for issue attribution.
        bounds: optional {column_name: (min, max)} for range checks. Either
            bound may be None.
    """
    bounds = bounds or {}
    columns: list[ColumnProfile] = []
    issues: list[IssueDraft] = []

    for i, col_name in enumerate(df.columns):
        col_bounds = bounds.get(str(col_name), (None, None))
        cp, col_issues = profile_column(
            df[col_name],
            ordinal=i,
            sheet_name=sheet_name,
            range_min=col_bounds[0],
            range_max=col_bounds[1],
        )
        columns.append(cp)
        issues.extend(col_issues)

    exact_dup_rows = _exact_duplicate_row_count(df)
    if exact_dup_rows > 0:
        issues.append(
            IssueDraft(
                sheet_name=sheet_name,
                column_name=None,
                dimension="uniqueness",
                severity="medium",
                description=(
                    f"Sheet '{sheet_name}' contains {exact_dup_rows} row(s) "
                    f"that appear more than once."
                ),
            )
        )

    dup_col_pairs = _detect_duplicate_columns(df)
    for a, b in dup_col_pairs:
        issues.append(
            IssueDraft(
                sheet_name=sheet_name,
                column_name=None,
                dimension="redundancy",
                severity="medium",
                description=(
                    f"Sheet '{sheet_name}' has identical columns '{a}' and "
                    f"'{b}'; consider dropping one."
                ),
                sample_values=[a, b],
            )
        )

    total_cells = len(df) * len(df.columns) if len(df.columns) else 0
    null_cells = sum(c.null_count for c in columns)
    completeness_pct = (
        100.0 - (null_cells / total_cells * 100.0) if total_cells > 0 else 100.0
    )

    sheet_rag = _compute_sheet_rag(
        [c.rag for c in columns], exact_dup_rows
    )

    return SheetProfile(
        sheet_name=sheet_name,
        row_count=int(len(df)),
        column_count=int(len(df.columns)),
        exact_duplicate_row_count=exact_dup_rows,
        completeness_pct=completeness_pct,
        rag=sheet_rag,
        columns=columns,
        issues=issues,
    )
