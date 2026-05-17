"""Pure-function tests for the stats engine.

The engine itself takes a `pd.DataFrame` and returns a `SheetProfile`; no
DB or HTTP layer is involved here. We verify both reference cases
(deterministic, known expected output) and invariants that should hold for
any input (hypothesis property tests).
"""
from __future__ import annotations

import math
import warnings
from datetime import date, datetime

import pandas as pd
import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

# Hypothesis hands us extreme floats; pandas warns when squaring them
# overflows. That's expected for arbitrary-magnitude inputs, not a
# correctness signal, so we silence it at module scope.
warnings.filterwarnings(
    "ignore",
    message="overflow encountered in.*",
    category=RuntimeWarning,
)
pytestmark = pytest.mark.filterwarnings(
    "ignore::RuntimeWarning",
)

from app.data_quality.stats import (
    PATTERN_CONFORMANCE_THRESHOLD,
    TYPE_INFERENCE_THRESHOLD,
    IssueDraft,
    profile_column,
    profile_sheet,
)


def _frame(**columns: list[object]) -> pd.DataFrame:
    return pd.DataFrame(columns, dtype=object)


# --------------------------------------------------------------------------
# Reference cases
# --------------------------------------------------------------------------


def test_integer_column_is_classified_and_stats_are_exact() -> None:
    df = _frame(x=[1, 2, 3, 4, 5, 6, 7, 8, 9, 10])
    p = profile_sheet(df, sheet_name="s")
    col = p.columns[0]

    assert col.semantic_type == "integer"
    assert col.type_mismatch_count == 0
    assert col.null_count == 0
    assert col.null_pct == 0.0
    assert col.distinct_count == 10
    assert col.numeric_min == 1.0
    assert col.numeric_max == 10.0
    assert col.numeric_median == 5.5
    assert col.numeric_mean == 5.5
    assert col.numeric_p25 == 3.25
    assert col.numeric_p75 == 7.75
    # std with ddof=1 of [1..10]
    assert math.isclose(col.numeric_std or 0.0, 3.0276503540974917, rel_tol=1e-9)


def test_float_column_with_one_outlier_is_flagged_by_both_methods() -> None:
    # Tight cluster + one extreme value
    values = [1.0, 1.1, 1.05, 1.2, 0.95, 0.9, 1.15, 1.0, 1.05, 50.0]
    df = _frame(x=values)
    p = profile_sheet(df, sheet_name="s")
    col = p.columns[0]

    assert col.semantic_type in {"integer", "float"}
    assert col.outlier_iqr_count == 1
    assert col.outlier_mad_count is not None and col.outlier_mad_count >= 1


def test_string_column_with_emails_gets_pattern_label() -> None:
    df = _frame(
        email=[
            "a@example.com",
            "b@example.com",
            "c@example.com",
            "d@example.com",
            "e@example.com",
            "f@example.com",
            "g@example.com",
            "h@example.com",
            "i@example.com",
            "j@example.com",
        ]
    )
    p = profile_sheet(df, sheet_name="s")
    col = p.columns[0]

    assert col.semantic_type == "string"
    assert col.pattern_label == "email"
    assert col.pattern_conformance_pct == 100.0


def test_string_pattern_below_threshold_is_not_assigned() -> None:
    # 8/10 emails; 80% < 95% threshold
    df = _frame(
        x=[
            "a@example.com",
            "b@example.com",
            "c@example.com",
            "d@example.com",
            "e@example.com",
            "f@example.com",
            "g@example.com",
            "h@example.com",
            "notanemail",
            "alsonotanemail",
        ]
    )
    p = profile_sheet(df, sheet_name="s")
    col = p.columns[0]
    assert col.pattern_label is None


def test_string_pattern_just_above_threshold_emits_consistency_issue() -> None:
    # 19/20 emails -> 95%. Pattern is assigned but conformance < 100%.
    emails = [f"u{i}@example.com" for i in range(19)] + ["nope"]
    df = _frame(x=emails)
    p = profile_sheet(df, sheet_name="s")
    col = p.columns[0]

    assert col.pattern_label == "email"
    assert col.pattern_conformance_pct is not None
    assert col.pattern_conformance_pct < 100.0

    issues = [
        i for i in p.issues if i.column_name == "x" and i.dimension == "consistency"
    ]
    assert len(issues) == 1
    assert "nope" in issues[0].sample_values


def test_type_mismatch_emits_high_severity_issue() -> None:
    # 99/100 are ints, 1 is a string => integer with one mismatch
    values: list[object] = [i for i in range(99)] + ["not-a-number"]
    df = _frame(x=values)
    p = profile_sheet(df, sheet_name="s")
    col = p.columns[0]

    assert col.semantic_type == "integer"
    assert col.type_mismatch_count == 1

    high_issues = [
        i
        for i in p.issues
        if i.column_name == "x" and i.severity == "high" and i.dimension == "consistency"
    ]
    assert len(high_issues) == 1
    assert "not-a-number" in high_issues[0].sample_values


def test_below_inference_threshold_falls_back_to_string() -> None:
    # 80% integers, 20% strings -> below 99% threshold for any type
    values: list[object] = [1, 2, 3, 4, 5, 6, 7, 8, "x", "y"]
    df = _frame(x=values)
    p = profile_sheet(df, sheet_name="s")
    col = p.columns[0]
    assert col.semantic_type == "string"
    assert col.type_mismatch_count == 0


def test_null_handling_uses_none_nan_and_blank_strings() -> None:
    df = _frame(
        x=[1, None, float("nan"), "  ", "", 2, 3, 4, 5, 6],
    )
    p = profile_sheet(df, sheet_name="s")
    col = p.columns[0]
    assert col.null_count == 4
    assert col.null_pct == 40.0
    # null_pct > 20 => medium severity completeness issue
    assert any(
        i.column_name == "x"
        and i.dimension == "completeness"
        and i.severity == "medium"
        for i in p.issues
    )


def test_date_column_min_max_in_iso() -> None:
    df = _frame(
        d=[
            datetime(2024, 1, 1),
            datetime(2024, 6, 1),
            datetime(2023, 12, 31),
            datetime(2024, 3, 15),
            date(2024, 5, 1),
        ]
    )
    p = profile_sheet(df, sheet_name="s")
    col = p.columns[0]
    assert col.semantic_type == "date"
    assert col.date_min == "2023-12-31"
    assert col.date_max == "2024-06-01"


def test_duplicate_rows_emit_uniqueness_issue() -> None:
    df = _frame(a=[1, 1, 2, 3, 3, 3], b=["x", "x", "y", "z", "z", "z"])
    p = profile_sheet(df, sheet_name="s")
    assert p.exact_duplicate_row_count == 5  # all rows except row 'a=2'
    sheet_issues = [
        i for i in p.issues if i.column_name is None and i.dimension == "uniqueness"
    ]
    assert len(sheet_issues) == 1


def test_duplicate_columns_emit_redundancy_issue() -> None:
    df = _frame(a=[1, 2, 3, 4], b=[1, 2, 3, 4], c=[1, 2, 3, 5])
    p = profile_sheet(df, sheet_name="s")
    red = [i for i in p.issues if i.dimension == "redundancy"]
    assert len(red) == 1
    assert set(red[0].sample_values) == {"a", "b"}


def test_constant_column_emits_low_uniqueness_issue() -> None:
    df = _frame(flag=["A"] * 20)
    p = profile_sheet(df, sheet_name="s")
    col = p.columns[0]
    assert col.distinct_count == 1
    constant_issue = [
        i
        for i in p.issues
        if i.column_name == "flag" and i.dimension == "uniqueness"
    ]
    assert len(constant_issue) == 1
    assert constant_issue[0].severity == "low"


def test_range_bounds_violations_are_counted_and_emit_validity_issue() -> None:
    values = [1, 2, 3, 4, 5, 100, 200]  # 100 and 200 over the max bound 10
    df = _frame(score=values)
    p = profile_sheet(
        df, sheet_name="s", bounds={"score": (0.0, 10.0)}
    )
    col = p.columns[0]
    assert col.range_min == 0.0
    assert col.range_max == 10.0
    assert col.range_violation_count == 2
    validity_issues = [i for i in p.issues if i.dimension == "validity"]
    assert len(validity_issues) == 1
    assert validity_issues[0].severity == "high"


def test_empty_sheet_does_not_crash() -> None:
    df = pd.DataFrame({"a": [], "b": []}, dtype=object)
    p = profile_sheet(df, sheet_name="s")
    assert p.row_count == 0
    assert p.column_count == 2
    assert p.exact_duplicate_row_count == 0
    assert p.completeness_pct == 100.0


def test_completeness_pct_aggregates_correctly() -> None:
    # 2 cols x 4 rows = 8 cells. 2 nulls in col a, 1 in col b => 3 nulls.
    # completeness = (8 - 3) / 8 = 0.625
    df = _frame(a=[1, None, 2, None], b=[1, 2, None, 4])
    p = profile_sheet(df, sheet_name="s")
    assert math.isclose(p.completeness_pct, 62.5, abs_tol=1e-9)


# --------------------------------------------------------------------------
# RAG rule reference cases (verifies the rule table in stats.py)
# --------------------------------------------------------------------------


def test_rag_is_red_when_type_mismatch_exists() -> None:
    values: list[object] = [i for i in range(99)] + ["x"]
    df = _frame(c=values)
    p = profile_sheet(df, sheet_name="s")
    assert p.columns[0].rag == "red"
    assert p.rag == "red"


def test_rag_is_red_when_null_pct_over_50() -> None:
    df = _frame(c=[None] * 6 + [1, 2, 3, 4])
    p = profile_sheet(df, sheet_name="s")
    assert p.columns[0].null_pct == 60.0
    assert p.columns[0].rag == "red"


def test_rag_is_green_for_clean_integer_column() -> None:
    df = _frame(c=list(range(100)))
    p = profile_sheet(df, sheet_name="s")
    assert p.columns[0].rag == "green"
    # No duplicate rows here -> sheet is green
    assert p.rag == "green"


def test_rag_amber_for_partial_pattern_conformance() -> None:
    # 19 emails + 1 non-email = 95% conformance, pattern assigned but <100%
    df = _frame(c=[f"u{i}@e.com" for i in range(19)] + ["x"])
    p = profile_sheet(df, sheet_name="s")
    assert p.columns[0].pattern_label == "email"
    assert p.columns[0].rag == "amber"


# --------------------------------------------------------------------------
# Hypothesis invariants
# --------------------------------------------------------------------------


@settings(max_examples=50, deadline=None)
@given(
    st.lists(
        st.one_of(
            st.integers(min_value=-10_000, max_value=10_000),
            st.floats(allow_nan=False, allow_infinity=False, width=32),
            st.text(min_size=0, max_size=20),
            st.none(),
        ),
        min_size=0,
        max_size=200,
    )
)
def test_invariant_null_plus_nonnull_equals_total(values: list[object]) -> None:
    df = pd.DataFrame({"c": values}, dtype=object)
    p = profile_sheet(df, sheet_name="s")
    col = p.columns[0]
    total = len(values)
    assert col.null_count + (total - col.null_count) == total
    if total > 0:
        assert 0.0 <= col.null_pct <= 100.0
        assert 0.0 <= col.distinct_pct <= 100.0


@settings(max_examples=30, deadline=None)
@given(st.lists(st.integers(min_value=-1000, max_value=1000), min_size=1, max_size=50))
def test_invariant_distinct_count_le_total(values: list[int]) -> None:
    df = pd.DataFrame({"c": values}, dtype=object)
    p = profile_sheet(df, sheet_name="s")
    col = p.columns[0]
    assert col.distinct_count <= len(values)


@settings(max_examples=30, deadline=None)
@given(st.lists(st.floats(allow_nan=False, allow_infinity=False), min_size=4, max_size=200))
def test_invariant_outlier_counts_within_bounds(values: list[float]) -> None:
    df = pd.DataFrame({"c": values}, dtype=object)
    p = profile_sheet(df, sheet_name="s")
    col = p.columns[0]
    # Outliers are only computed for numeric semantic types
    if col.outlier_iqr_count is not None:
        assert 0 <= col.outlier_iqr_count <= len(values)
    if col.outlier_mad_count is not None:
        assert 0 <= col.outlier_mad_count <= len(values)


def test_threshold_constants_are_documented_at_99_and_95() -> None:
    """Sanity check: precision commitments in the docstring must match code."""
    assert TYPE_INFERENCE_THRESHOLD == 0.99
    assert PATTERN_CONFORMANCE_THRESHOLD == 0.95
