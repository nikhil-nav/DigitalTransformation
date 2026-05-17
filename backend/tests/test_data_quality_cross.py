"""Tests for the cross-column / cross-sheet analysis engine.

Split into two groups:
- Pure-function tests against `cross.py` with constructed DataFrames.
- End-to-end tests through the HTTP API for the FK suggestion + confirm
  flow, including the precision commitment that confirmation is the *only*
  trigger for FK-violation issues.
"""
from __future__ import annotations

import io

import openpyxl
import pandas as pd

from app.auth import SESSION_COOKIE, sessions
from app.data_quality import cross
from app.models import (
    DataQualityFunctionalDependency,
    DataQualityIssue,
    DataQualityRelationship,
    User,
)

XLSX_MIME = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


# --------------------------------------------------------------------------
# helpers
# --------------------------------------------------------------------------


def _frame(**columns: list[object]) -> pd.DataFrame:
    return pd.DataFrame(columns, dtype=object)


def login_as_user(client) -> None:
    r = client.post(
        "/api/auth/login",
        json={"username": "user", "password": "password"},
    )
    assert r.status_code == 200


def login_as(client, db, username: str) -> User:
    user = db.query(User).filter_by(username=username).one_or_none()
    if user is None:
        user = User(username=username)
        db.add(user)
        db.commit()
        db.refresh(user)
    session_id = f"test-session-{username}"
    sessions[session_id] = username
    client.cookies.set(SESSION_COOKIE, session_id)
    return user


def make_dq_project(client) -> int:
    r = client.post(
        "/api/projects",
        json={"name": "DQ", "project_type_code": "data_quality_assessment"},
    )
    assert r.status_code == 201, r.text
    return r.json()["id"]


def build_xlsx(sheets: dict[str, list[list[object]]]) -> bytes:
    wb = openpyxl.Workbook()
    default = wb.active
    if default is not None:
        wb.remove(default)
    for name, rows in sheets.items():
        ws = wb.create_sheet(title=name)
        for row in rows:
            ws.append(row)
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def _upload(client, pid: int, payload: bytes, filename: str = "p.xlsx") -> dict:
    r = client.post(
        f"/api/projects/{pid}/dq/datasets",
        files={"upload": (filename, payload, XLSX_MIME)},
    )
    assert r.status_code == 201, r.text
    return r.json()


# --------------------------------------------------------------------------
# Pure-function tests: functional dependencies
# --------------------------------------------------------------------------


def test_fd_detected_when_determinant_implies_dependent():
    # zip -> city: 3 distinct zips each consistently mapped (the engine
    # requires at least FD_MIN_GROUPS=3 distinct determinant values to
    # consider the dependency).
    df = _frame(
        zip=["10001", "10001", "94101", "94101", "02101", "02101"],
        city=["NYC", "NYC", "SF", "SF", "Boston", "Boston"],
    )
    fds = cross.detect_functional_dependencies(df, "addresses")
    pairs = [(f.determinant_column, f.dependent_column) for f in fds]
    assert ("zip", "city") in pairs
    fd = next(f for f in fds if f.determinant_column == "zip")
    assert fd.confidence_pct == 100.0
    assert fd.counter_example_count == 0


def test_fd_not_emitted_below_confidence_threshold():
    # 2/3 groups consistent => 66% < 95% threshold
    df = _frame(
        a=["x", "x", "x", "y", "y", "z", "z"],
        b=[1, 1, 2, 3, 3, 4, 4],
    )
    fds = cross.detect_functional_dependencies(df, "s")
    assert not any(f.determinant_column == "a" for f in fds)


def test_fd_requires_minimum_group_count():
    # Only 2 distinct A values => below FD_MIN_GROUPS=3, skipped even if
    # the dependency is otherwise perfect.
    df = _frame(a=["x", "x", "y", "y"], b=[1, 1, 2, 2])
    fds = cross.detect_functional_dependencies(df, "s")
    assert not fds


# --------------------------------------------------------------------------
# Pure-function tests: correlations
# --------------------------------------------------------------------------


def test_correlation_flags_highly_correlated_numeric_pair():
    df = _frame(
        x=list(range(20)),
        y=[2 * i + 3 for i in range(20)],  # perfectly correlated
        unrelated=[7] * 20,  # constant -> correlation undefined / NaN
    )
    corrs = cross.detect_numeric_correlations(
        df, "s", ["x", "y", "unrelated"]
    )
    assert any(
        {c.column_a, c.column_b} == {"x", "y"} and abs(c.pearson_r) >= 0.95
        for c in corrs
    )


def test_correlation_skipped_when_n_below_threshold():
    df = _frame(x=list(range(5)), y=list(range(5)))
    assert cross.detect_numeric_correlations(df, "s", ["x", "y"]) == []


# --------------------------------------------------------------------------
# Pure-function tests: relationship suggestion
# --------------------------------------------------------------------------


def test_suggestion_proposed_for_fk_with_perfect_subset_coverage():
    customers = _frame(id=[1, 2, 3], name=["A", "B", "C"])
    orders = _frame(id=[10, 11, 12, 13], customer_id=[1, 1, 2, 3])
    sems = {
        "customers": {"id": "integer", "name": "string"},
        "orders": {"id": "integer", "customer_id": "integer"},
    }

    suggestions = cross.suggest_relationships(
        {"customers": customers, "orders": orders}, sems
    )
    fk = next(
        s
        for s in suggestions
        if s.parent_sheet == "customers"
        and s.parent_column == "id"
        and s.child_sheet == "orders"
        and s.child_column == "customer_id"
    )
    assert fk.type_match is True
    assert fk.subset_coverage == 1.0
    assert fk.cardinality == "many_to_one"
    assert fk.confidence_pct > 50.0


def test_suggestion_skipped_when_coverage_below_threshold():
    customers = _frame(id=[1, 2, 3])
    orders = _frame(customer_id=[99, 100, 101, 102])  # 0 / 4 coverage
    sems = {"customers": {"id": "integer"}, "orders": {"customer_id": "integer"}}

    suggestions = cross.suggest_relationships(
        {"customers": customers, "orders": orders}, sems
    )
    assert not any(
        s.child_sheet == "orders" and s.child_column == "customer_id"
        for s in suggestions
    )


def test_name_similarity_camel_and_snake_overlap():
    assert cross.name_similarity("customerId", "customer_id") == 1.0
    assert 0.0 < cross.name_similarity("customer_id", "id") < 1.0
    assert cross.name_similarity("a", "b") == 0.0


def test_fk_violation_counts_distinct_missing_values():
    parent = _frame(id=[1, 2, 3])
    child = _frame(parent_id=[1, 2, 4, 5, 5])
    v = cross.fk_violations(parent, "id", child, "parent_id")
    assert v is not None
    assert v.missing_value_count == 2
    assert set(v.sample_missing_values) == {"4", "5"}


def test_fk_violation_returns_none_when_clean():
    parent = _frame(id=[1, 2, 3])
    child = _frame(parent_id=[1, 2, 2, 3])
    assert cross.fk_violations(parent, "id", child, "parent_id") is None


# --------------------------------------------------------------------------
# End-to-end via HTTP
# --------------------------------------------------------------------------


def _two_sheet_workbook() -> bytes:
    return build_xlsx(
        {
            "customers": [
                ["id", "name"],
                [1, "Acme"],
                [2, "Beta"],
                [3, "Gamma"],
            ],
            "orders": [
                ["id", "customer_id", "amount"],
                [101, 1, 50],
                [102, 2, 75],
                [103, 2, 12],
                [104, 3, 99],
            ],
        }
    )


def test_upload_emits_relationship_suggestion(client, db):
    login_as_user(client)
    pid = make_dq_project(client)
    ds = _upload(client, pid, _two_sheet_workbook())

    r = client.get(
        f"/api/projects/{pid}/dq/datasets/{ds['id']}/relationships"
    )
    assert r.status_code == 200, r.text
    suggestions = r.json()
    fk = next(
        s
        for s in suggestions
        if s["parent_sheet"] == "customers"
        and s["parent_column"] == "id"
        and s["child_sheet"] == "orders"
        and s["child_column"] == "customer_id"
    )
    assert fk["status"] == "suggested"
    assert fk["subset_coverage"] == 1.0
    assert fk["confirmed_at"] is None


def test_confirming_relationship_emits_fk_violation_when_appropriate(client, db):
    """A confirmed FK with no violations stays silent; introduce a missing
    parent value and confirmation should produce a high-severity validity
    issue tagged as FK violation."""
    login_as_user(client)
    pid = make_dq_project(client)
    # Inject an orphan customer_id=4 (not in customers.id)
    payload = build_xlsx(
        {
            "customers": [
                ["id", "name"],
                [1, "Acme"],
                [2, "Beta"],
                [3, "Gamma"],
            ],
            "orders": [
                ["id", "customer_id", "amount"],
                [101, 1, 50],
                [102, 2, 75],
                [103, 4, 12],  # orphan
            ],
        }
    )
    ds = _upload(client, pid, payload)

    # Confirm the suggested FK
    suggestions = client.get(
        f"/api/projects/{pid}/dq/datasets/{ds['id']}/relationships"
    ).json()
    # The suggested orders.customer_id -> customers.id should appear even
    # though one child value is orphaned (subset coverage is 2/3 = 0.67,
    # above the 0.5 floor).
    rel = next(
        s
        for s in suggestions
        if s["parent_sheet"] == "customers"
        and s["child_sheet"] == "orders"
        and s["child_column"] == "customer_id"
    )
    r = client.patch(
        f"/api/projects/{pid}/dq/datasets/{ds['id']}/relationships/{rel['id']}",
        json={"status": "confirmed"},
    )
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "confirmed"
    assert r.json()["confirmed_at"] is not None

    issues = client.get(
        f"/api/projects/{pid}/dq/datasets/{ds['id']}/issues"
    ).json()
    fk_issues = [i for i in issues if "FK violation" in i["description"]]
    assert len(fk_issues) == 1
    assert fk_issues[0]["severity"] == "high"
    assert fk_issues[0]["dimension"] == "validity"
    assert "4" in fk_issues[0]["sample_values"]


def test_dismissing_relationship_records_decision_and_no_issue(client):
    login_as_user(client)
    pid = make_dq_project(client)
    ds = _upload(client, pid, _two_sheet_workbook())
    rel = next(
        s
        for s in client.get(
            f"/api/projects/{pid}/dq/datasets/{ds['id']}/relationships"
        ).json()
        if s["child_column"] == "customer_id"
    )

    r = client.patch(
        f"/api/projects/{pid}/dq/datasets/{ds['id']}/relationships/{rel['id']}",
        json={"status": "dismissed"},
    )
    assert r.status_code == 200
    assert r.json()["status"] == "dismissed"
    assert r.json()["dismissed_at"] is not None
    assert r.json()["confirmed_at"] is None

    # No FK-violation issue should ever have been emitted from this pair
    issues = client.get(
        f"/api/projects/{pid}/dq/datasets/{ds['id']}/issues"
    ).json()
    assert not any("FK violation" in i["description"] for i in issues)


def test_dismissed_decision_survives_re_profile(client, db):
    login_as_user(client)
    pid = make_dq_project(client)
    ds = _upload(client, pid, _two_sheet_workbook())
    rel = next(
        s
        for s in client.get(
            f"/api/projects/{pid}/dq/datasets/{ds['id']}/relationships"
        ).json()
        if s["child_column"] == "customer_id"
    )
    client.patch(
        f"/api/projects/{pid}/dq/datasets/{ds['id']}/relationships/{rel['id']}",
        json={"status": "dismissed"},
    )

    # Manual re-profile
    r = client.post(f"/api/projects/{pid}/dq/datasets/{ds['id']}/profile")
    assert r.status_code == 200, r.text

    survived = next(
        s
        for s in client.get(
            f"/api/projects/{pid}/dq/datasets/{ds['id']}/relationships"
        ).json()
        if s["child_column"] == "customer_id"
    )
    assert survived["status"] == "dismissed"
    assert survived["dismissed_at"] is not None


def test_functional_dependencies_persisted_and_listed(client):
    login_as_user(client)
    pid = make_dq_project(client)
    # ZIP -> City: 3 distinct ZIPs each consistently mapped
    payload = build_xlsx(
        {
            "addr": [
                ["zip", "city"],
                ["10001", "NYC"],
                ["10001", "NYC"],
                ["10001", "NYC"],
                ["94101", "SF"],
                ["94101", "SF"],
                ["94101", "SF"],
                ["02101", "Boston"],
                ["02101", "Boston"],
                ["02101", "Boston"],
            ]
        }
    )
    ds = _upload(client, pid, payload)
    fds = client.get(
        f"/api/projects/{pid}/dq/datasets/{ds['id']}/functional-dependencies"
    ).json()
    pairs = {(f["determinant_column"], f["dependent_column"]) for f in fds}
    assert ("zip", "city") in pairs


def test_redundant_columns_emit_redundancy_issue(client):
    login_as_user(client)
    pid = make_dq_project(client)
    # Two perfectly correlated numeric columns
    rows = [["x", "y"]] + [[i, 2 * i] for i in range(20)]
    payload = build_xlsx({"s": rows})
    ds = _upload(client, pid, payload)
    issues = client.get(
        f"/api/projects/{pid}/dq/datasets/{ds['id']}/issues"
    ).json()
    redundancy = [i for i in issues if i["dimension"] == "redundancy"]
    assert len(redundancy) >= 1
    assert any(
        "Pearson" in i["description"] for i in redundancy
    )


def test_relationship_404_on_other_dataset(client):
    login_as_user(client)
    pid = make_dq_project(client)
    ds_a = _upload(client, pid, _two_sheet_workbook())
    ds_b = _upload(
        client, pid, build_xlsx({"only": [["x"], [1], [2]]}), filename="b.xlsx"
    )
    rel = next(
        s
        for s in client.get(
            f"/api/projects/{pid}/dq/datasets/{ds_a['id']}/relationships"
        ).json()
        if s["child_column"] == "customer_id"
    )
    r = client.patch(
        f"/api/projects/{pid}/dq/datasets/{ds_b['id']}/relationships/{rel['id']}",
        json={"status": "confirmed"},
    )
    assert r.status_code == 404


def test_deleting_dataset_cascades_fds_and_relationships(client, db):
    login_as_user(client)
    pid = make_dq_project(client)
    ds = _upload(client, pid, _two_sheet_workbook())
    ds_id = ds["id"]
    # Confirm there's something in those tables for this dataset first
    assert (
        db.query(DataQualityRelationship).filter_by(dataset_id=ds_id).count() > 0
    )

    r = client.delete(f"/api/projects/{pid}/dq/datasets/{ds_id}")
    assert r.status_code == 204

    db.expire_all()
    assert (
        db.query(DataQualityRelationship).filter_by(dataset_id=ds_id).count() == 0
    )
    assert (
        db.query(DataQualityFunctionalDependency)
        .filter_by(dataset_id=ds_id)
        .count()
        == 0
    )
    assert db.query(DataQualityIssue).filter_by(dataset_id=ds_id).count() == 0
