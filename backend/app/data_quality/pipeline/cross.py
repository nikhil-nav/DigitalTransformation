"""Cross-column (US 1.8) and cross-sheet (US 1.9) analysis.

Pure functions. Like `stats.py`, this module accepts pandas DataFrames and
returns frozen dataclasses describing findings; the caller in `profile.py`
persists them.

# Precision commitments

- **Functional dependency detection is exact.** For each candidate
  `A -> B`, we group by A, count distinct B per group (ignoring rows where
  A is null), and compute the % of groups where B is constant. A
  dependency is *persisted* only above `FD_MIN_CONFIDENCE_PCT`; counter-
  examples (group A-values where B disagrees) are preserved so the user
  can audit the claim.
- **Numeric redundancy is reported as Pearson |r| above
  `CORRELATION_REDUNDANCY_THRESHOLD`.** We never collapse the columns or
  claim they're "the same"; the redundancy issue is informational.
- **Cross-sheet relationships are suggestions only.** Every candidate is
  emitted with `status="suggested"`. Downstream FK-violation checks fire
  only after the user explicitly confirms via the PATCH endpoint. Multiple
  signals (type_match, name_similarity, subset_coverage, cardinality) are
  surfaced separately so the user can judge the score, not just trust it.
- **Subset coverage uses the conservatively-defined denominator.** We
  count distinct *non-null* child values; null parent values can't satisfy
  a FK and are excluded. The numerator is the count of those distinct
  child values that appear at least once in the parent's non-null values.
- **Reproducibility.** `CROSS_ENGINE_VERSION` is persisted on every row.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

import pandas as pd

CROSS_ENGINE_VERSION = "1.0.0"

# Functional dependency: only persist FDs at >= 95% group consistency.
FD_MIN_CONFIDENCE_PCT = 95.0
FD_MIN_GROUPS = 3
FD_MAX_COUNTER_EXAMPLES = 10

# Redundancy: flag column pairs whose Pearson |r| exceeds this.
CORRELATION_REDUNDANCY_THRESHOLD = 0.95
CORRELATION_MIN_ROWS = 10  # need a reasonable n to trust correlation

# Cross-sheet suggestion thresholds. We only persist as `suggested` when
# subset coverage clears the floor; below this the candidate is noise.
RELATIONSHIP_MIN_SUBSET_COVERAGE = 0.5
RELATIONSHIP_MIN_CONFIDENCE_PCT = 50.0
RELATIONSHIP_MAX_SAMPLE_MISSING = 10


# --------------------------------------------------------------------------
# Result dataclasses
# --------------------------------------------------------------------------


@dataclass(frozen=True)
class FunctionalDependency:
    sheet_name: str
    determinant_column: str
    dependent_column: str
    confidence_pct: float
    counter_example_count: int
    sample_counter_examples: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class CorrelationFinding:
    sheet_name: str
    column_a: str
    column_b: str
    pearson_r: float


@dataclass(frozen=True)
class RelationshipCandidate:
    parent_sheet: str
    parent_column: str
    child_sheet: str
    child_column: str
    type_match: bool
    name_similarity: float
    subset_coverage: float
    cardinality: str  # one_to_one | many_to_one | unknown
    confidence_pct: float


@dataclass(frozen=True)
class CrossAnalysisResult:
    functional_dependencies: list[FunctionalDependency]
    correlations: list[CorrelationFinding]
    relationships: list[RelationshipCandidate]


# --------------------------------------------------------------------------
# Functional dependencies
# --------------------------------------------------------------------------


def detect_functional_dependencies(
    df: pd.DataFrame, sheet_name: str
) -> list[FunctionalDependency]:
    """For every ordered pair (A, B), report if A -> B holds with high
    confidence. Skips columns with too-few distinct A values to be
    meaningful (defaults to >= FD_MIN_GROUPS groups).
    """
    cols = list(df.columns)
    n_cols = len(cols)
    if n_cols < 2 or len(df) == 0:
        return []

    out: list[FunctionalDependency] = []
    for i in range(n_cols):
        det = str(cols[i])
        det_series = df[det]
        # Drop rows where determinant is null - they can't constrain B.
        mask = det_series.notna()
        if not bool(mask.any()):
            continue
        for j in range(n_cols):
            if i == j:
                continue
            dep = str(cols[j])
            grouped = df.loc[mask].groupby(det_series[mask], dropna=False)[dep]
            # nunique counts distinct non-null values per group
            uniq_counts = grouped.nunique(dropna=True)
            total_groups = len(uniq_counts)
            if total_groups < FD_MIN_GROUPS:
                continue
            consistent_groups = int((uniq_counts <= 1).sum())
            confidence = consistent_groups / total_groups * 100.0
            if confidence < FD_MIN_CONFIDENCE_PCT:
                continue
            counter_keys = uniq_counts[uniq_counts > 1].index.tolist()
            out.append(
                FunctionalDependency(
                    sheet_name=sheet_name,
                    determinant_column=det,
                    dependent_column=dep,
                    confidence_pct=confidence,
                    counter_example_count=len(counter_keys),
                    sample_counter_examples=[
                        str(v) for v in counter_keys[:FD_MAX_COUNTER_EXAMPLES]
                    ],
                )
            )
    return out


# --------------------------------------------------------------------------
# Numeric correlations
# --------------------------------------------------------------------------


def detect_numeric_correlations(
    df: pd.DataFrame, sheet_name: str, numeric_columns: list[str]
) -> list[CorrelationFinding]:
    """Pearson r on the listed numeric columns; emit pairs with |r| above
    the threshold. The caller passes the column list because it already
    knows which columns the stats engine inferred as numeric, so we don't
    have to redo type inference here."""
    if len(numeric_columns) < 2:
        return []
    if len(df) < CORRELATION_MIN_ROWS:
        return []

    # Coerce only the named columns, with errors='coerce' so non-numeric
    # cells become NaN and don't blow up the correlation.
    numeric_df = pd.DataFrame(
        {c: pd.to_numeric(df[c], errors="coerce") for c in numeric_columns}
    )
    corr = numeric_df.corr(method="pearson", min_periods=CORRELATION_MIN_ROWS)

    out: list[CorrelationFinding] = []
    cols = list(corr.columns)
    for i in range(len(cols)):
        for j in range(i + 1, len(cols)):
            r = corr.iloc[i, j]
            if pd.isna(r):
                continue
            if abs(float(r)) >= CORRELATION_REDUNDANCY_THRESHOLD:
                out.append(
                    CorrelationFinding(
                        sheet_name=sheet_name,
                        column_a=str(cols[i]),
                        column_b=str(cols[j]),
                        pearson_r=float(r),
                    )
                )
    return out


# --------------------------------------------------------------------------
# Cross-sheet relationships
# --------------------------------------------------------------------------


_TOKEN_SPLIT = re.compile(r"[^A-Za-z0-9]+")


def _tokenize_name(name: str) -> set[str]:
    # CamelCase split: "customerId" -> ["customer", "Id"]; lowercase tokens
    parts = _TOKEN_SPLIT.split(re.sub(r"(?<!^)(?=[A-Z])", " ", str(name)))
    return {p.lower() for p in parts if p}


def name_similarity(a: str, b: str) -> float:
    """Jaccard similarity on tokenised column names. 1.0 means identical
    token sets; 0.0 means no shared tokens."""
    ta, tb = _tokenize_name(a), _tokenize_name(b)
    if not ta or not tb:
        return 0.0
    inter = ta & tb
    union = ta | tb
    return len(inter) / len(union)


def _non_null_distinct(series: pd.Series) -> set[Any]:
    return {v for v in series.dropna().tolist()}


def _cardinality(child_series: pd.Series) -> str:
    """Classify child cardinality.

    For an FK to work the child must reference the parent many-to-one or
    one-to-one. We detect this by looking at the child column's
    duplication: if every non-null child value is unique it's at-most
    one-to-one; if some repeat it's many-to-one.
    """
    s = child_series.dropna()
    if s.empty:
        return "unknown"
    n = len(s)
    n_unique = int(s.nunique(dropna=True))
    if n_unique == n:
        return "one_to_one"
    return "many_to_one"


def suggest_relationships(
    sheets: dict[str, pd.DataFrame],
    semantic_types_by_sheet: dict[str, dict[str, str]],
) -> list[RelationshipCandidate]:
    """For every ordered cross-sheet (parent, child) pair on type-matched
    columns, compute coverage + cardinality + name similarity and produce
    a suggestion if the signals justify it.

    `semantic_types_by_sheet` is provided so we use exactly what the stats
    engine inferred (single source of truth); type re-inference here would
    risk drift.
    """
    suggestions: list[RelationshipCandidate] = []
    sheet_names = list(sheets.keys())

    for p_sheet in sheet_names:
        for c_sheet in sheet_names:
            if p_sheet == c_sheet:
                continue
            p_df = sheets[p_sheet]
            c_df = sheets[c_sheet]
            p_types = semantic_types_by_sheet.get(p_sheet, {})
            c_types = semantic_types_by_sheet.get(c_sheet, {})

            for p_col in p_df.columns:
                p_type = p_types.get(str(p_col), "string")
                p_values = _non_null_distinct(p_df[p_col])
                if not p_values:
                    continue
                for c_col in c_df.columns:
                    c_type = c_types.get(str(c_col), "string")
                    type_match = p_type == c_type and p_type not in {"empty"}
                    if not type_match:
                        continue  # required for an FK

                    child_distinct = _non_null_distinct(c_df[c_col])
                    if not child_distinct:
                        continue

                    covered = sum(1 for v in child_distinct if v in p_values)
                    subset_coverage = covered / len(child_distinct)
                    if subset_coverage < RELATIONSHIP_MIN_SUBSET_COVERAGE:
                        continue

                    card = _cardinality(c_df[c_col])
                    cardinality_score = 1.0 if card in {"one_to_one", "many_to_one"} else 0.0

                    sim = name_similarity(str(p_col), str(c_col))

                    confidence = (
                        (1.0 if type_match else 0.0)
                        + sim
                        + subset_coverage
                        + cardinality_score
                    ) / 4.0 * 100.0

                    if confidence < RELATIONSHIP_MIN_CONFIDENCE_PCT:
                        continue

                    suggestions.append(
                        RelationshipCandidate(
                            parent_sheet=p_sheet,
                            parent_column=str(p_col),
                            child_sheet=c_sheet,
                            child_column=str(c_col),
                            type_match=type_match,
                            name_similarity=sim,
                            subset_coverage=subset_coverage,
                            cardinality=card,
                            confidence_pct=confidence,
                        )
                    )
    # Stable ordering for deterministic persistence and tests.
    suggestions.sort(
        key=lambda r: (
            -r.confidence_pct,
            r.parent_sheet,
            r.parent_column,
            r.child_sheet,
            r.child_column,
        )
    )
    return suggestions


# --------------------------------------------------------------------------
# FK violations (computed when the user confirms a relationship)
# --------------------------------------------------------------------------


@dataclass(frozen=True)
class FkViolation:
    parent_sheet: str
    parent_column: str
    child_sheet: str
    child_column: str
    missing_value_count: int
    sample_missing_values: list[str]


def fk_violations(
    parent_df: pd.DataFrame,
    parent_column: str,
    child_df: pd.DataFrame,
    child_column: str,
) -> FkViolation | None:
    """For a confirmed FK, find child values absent from the parent.

    Returns None if every child value is satisfied (no violation). Otherwise
    returns the violation with sample missing values capped at
    RELATIONSHIP_MAX_SAMPLE_MISSING.
    """
    parent_values = _non_null_distinct(parent_df[parent_column])
    child_values = _non_null_distinct(child_df[child_column])
    missing = [v for v in child_values if v not in parent_values]
    if not missing:
        return None
    return FkViolation(
        parent_sheet="",  # filled in by caller (it knows the names)
        parent_column=parent_column,
        child_sheet="",
        child_column=child_column,
        missing_value_count=len(missing),
        sample_missing_values=[str(v) for v in missing[:RELATIONSHIP_MAX_SAMPLE_MISSING]],
    )


# --------------------------------------------------------------------------
# Top-level entry point
# --------------------------------------------------------------------------


def analyse_workbook(
    sheets: dict[str, pd.DataFrame],
    semantic_types_by_sheet: dict[str, dict[str, str]],
    numeric_columns_by_sheet: dict[str, list[str]],
) -> CrossAnalysisResult:
    fds: list[FunctionalDependency] = []
    correlations: list[CorrelationFinding] = []
    for sheet_name, df in sheets.items():
        fds.extend(detect_functional_dependencies(df, sheet_name))
        correlations.extend(
            detect_numeric_correlations(
                df, sheet_name, numeric_columns_by_sheet.get(sheet_name, [])
            )
        )
    relationships = suggest_relationships(sheets, semantic_types_by_sheet)
    return CrossAnalysisResult(
        functional_dependencies=fds,
        correlations=correlations,
        relationships=relationships,
    )
