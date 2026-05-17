"""Tests for the Data Quality chat agent tools + endpoints.

The streaming loop itself is exercised by the BCM stream tests in
test_llm.py; here we focus on the DQ-specific bits: the system prompt is
wired in, the right dispatch is bound, and each tool returns the right
shape (and rejects bad inputs)."""
from __future__ import annotations

import io
import json

import openpyxl

from app.auth import SESSION_COOKIE, sessions
from app.data_quality import agent as dq_agent
from app.llm.session import LlmKeys, session_keys
from app.models import (
    ChatMessage,
    ChatThread,
    DataQualityDataset,
    DataQualityIssue,
    Project,
    ProjectType,
    User,
)

XLSX_MIME = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


def login_as(client, db, username: str) -> tuple[User, str]:
    user = db.query(User).filter_by(username=username).one_or_none()
    if user is None:
        user = User(username=username)
        db.add(user)
        db.commit()
        db.refresh(user)
    session_id = f"test-session-{username}"
    sessions[session_id] = username
    client.cookies.set(SESSION_COOKIE, session_id)
    return user, session_id


def login_as_user(client) -> None:
    r = client.post(
        "/api/auth/login",
        json={"username": "user", "password": "password"},
    )
    assert r.status_code == 200


def make_dq_project(client) -> int:
    r = client.post(
        "/api/projects",
        json={"name": "DQ", "project_type_code": "data_quality_assessment"},
    )
    assert r.status_code == 201, r.text
    return r.json()["id"]


def make_value_discovery_project_directly(db, user: User) -> int:
    pt = db.query(ProjectType).filter_by(code="value_discovery").one()
    p = Project(user_id=user.id, project_type_id=pt.id, name="VD")
    db.add(p)
    db.commit()
    db.refresh(p)
    return p.id


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


def _two_sheet_xlsx() -> bytes:
    return build_xlsx(
        {
            "customers": [
                ["id", "name", "email"],
                [1, "Acme", "acme@example.com"],
                [2, "Beta", "beta@example.com"],
                [3, "Gamma", "gamma@example.com"],
            ],
            "orders": [
                ["id", "customer_id", "amount"],
                [101, 1, 50],
                [102, 2, 75],
                [103, 2, 12],
                [104, 4, 99],  # orphan
            ],
        }
    )


# ------------------------------------------------------------------
# Direct tool tests
# ------------------------------------------------------------------


def _dataset_id(client, db) -> int:
    login_as_user(client)
    pid = make_dq_project(client)
    ds = _upload(client, pid, _two_sheet_xlsx())
    return ds["id"]


def test_describe_dataset_returns_filename_and_per_sheet_summary(client, db):
    ds_id = _dataset_id(client, db)
    out = dq_agent._tool_describe_dataset(db, ds_id, {})
    assert out["filename"] == "p.xlsx"
    sheet_names = {s["name"] for s in out["sheets"]}
    assert sheet_names == {"customers", "orders"}
    for s in out["sheets"]:
        assert {"row_count", "column_count", "completeness_pct", "rag"} <= set(s)


def test_describe_column_returns_full_profile(client, db):
    ds_id = _dataset_id(client, db)
    out = dq_agent._tool_describe_column(
        db, ds_id, {"sheet": "customers", "column": "email"}
    )
    assert out["name"] == "email"
    # email pattern should be detected (3/3 conform)
    assert out["pattern"]["label"] == "email"


def test_describe_column_404_on_unknown(client, db):
    ds_id = _dataset_id(client, db)
    try:
        dq_agent._tool_describe_column(db, ds_id, {"sheet": "customers", "column": "nope"})
        raise AssertionError("expected ValueError")
    except ValueError as e:
        assert "not found" in str(e)


def test_list_issues_supports_sheet_and_severity_filters(client, db):
    """Workbook with a 33% null column emits a low completeness issue we can
    filter for. We assert filtering works without depending on exact counts."""
    login_as_user(client)
    pid = make_dq_project(client)
    payload = build_xlsx(
        {
            "s": [
                ["x"],
                [None],
                [None],
                [None],
                [1],
                [2],
            ]
        }
    )
    ds_id = _upload(client, pid, payload)["id"]
    all_issues = dq_agent._tool_list_issues(db, ds_id, {})
    assert all_issues["count"] >= 1
    only_s = dq_agent._tool_list_issues(db, ds_id, {"sheet": "s"})
    assert all(i["sheet"] == "s" for i in only_s["issues"])
    only_other = dq_agent._tool_list_issues(db, ds_id, {"sheet": "nope"})
    assert only_other["count"] == 0


def test_query_dataset_returns_rows(client, db):
    ds_id = _dataset_id(client, db)
    out = dq_agent._tool_query_dataset(db, ds_id, {"sheet": "customers"})
    assert out["sheet"] == "customers"
    assert out["row_count_total"] == 3
    assert len(out["rows"]) == 3
    assert {"id", "name", "email"} <= set(out["rows"][0])


def test_query_dataset_applies_eq_filter(client, db):
    ds_id = _dataset_id(client, db)
    out = dq_agent._tool_query_dataset(
        db,
        ds_id,
        {
            "sheet": "orders",
            "filters": [{"column": "customer_id", "op": "==", "value": 2}],
        },
    )
    assert out["row_count_total"] == 2
    for row in out["rows"]:
        assert int(row["customer_id"]) == 2


def test_query_dataset_applies_gt_filter(client, db):
    ds_id = _dataset_id(client, db)
    out = dq_agent._tool_query_dataset(
        db,
        ds_id,
        {
            "sheet": "orders",
            "filters": [{"column": "amount", "op": ">", "value": 50}],
        },
    )
    assert all(int(r["amount"]) > 50 for r in out["rows"])


def test_query_dataset_supports_is_null(client, db):
    """is_null finds the rows where the cell is None / NaN / blank."""
    login_as_user(client)
    pid = make_dq_project(client)
    payload = build_xlsx(
        {
            "s": [
                ["x"],
                [None],
                ["a"],
                [None],
                ["b"],
            ]
        }
    )
    ds_id = _upload(client, pid, payload)["id"]
    out = dq_agent._tool_query_dataset(
        db,
        ds_id,
        {"sheet": "s", "filters": [{"column": "x", "op": "is_null"}]},
    )
    assert out["row_count_total"] == 2


def test_query_dataset_rejects_unknown_op(client, db):
    ds_id = _dataset_id(client, db)
    try:
        dq_agent._tool_query_dataset(
            db,
            ds_id,
            {
                "sheet": "orders",
                "filters": [
                    {"column": "amount", "op": "regex", "value": "^1"}
                ],
            },
        )
        raise AssertionError("expected ValueError")
    except ValueError as e:
        assert "Unsupported op" in str(e)


def test_query_dataset_rejects_unknown_column(client, db):
    ds_id = _dataset_id(client, db)
    try:
        dq_agent._tool_query_dataset(
            db,
            ds_id,
            {
                "sheet": "orders",
                "filters": [{"column": "nope", "op": "==", "value": 1}],
            },
        )
        raise AssertionError("expected ValueError")
    except ValueError as e:
        assert "Unknown column" in str(e)


def test_query_dataset_respects_limit(client, db):
    ds_id = _dataset_id(client, db)
    out = dq_agent._tool_query_dataset(
        db, ds_id, {"sheet": "orders", "limit": 2}
    )
    assert out["row_count_total"] == 4
    assert out["rows_returned"] == 2
    assert out["limit_applied"] == 2


def test_query_dataset_clamps_oversized_limit(client, db):
    ds_id = _dataset_id(client, db)
    out = dq_agent._tool_query_dataset(
        db, ds_id, {"sheet": "orders", "limit": 1000}
    )
    # max 50 per call
    assert out["limit_applied"] == 50


def test_flag_issue_creates_persisted_row_marked_agent(client, db):
    ds_id = _dataset_id(client, db)
    out = dq_agent._tool_flag_issue(
        db,
        ds_id,
        {
            "sheet": "orders",
            "column": "amount",
            "dimension": "validity",
            "severity": "medium",
            "description": "User flagged: refunds may be miscoded.",
            "sample_values": ["50", "75"],
        },
    )
    db.expire_all()
    row = db.query(DataQualityIssue).filter_by(id=out["id"]).one()
    assert row.engine_version.startswith("dq-agent/")
    assert row.dimension == "validity"
    assert row.severity == "medium"
    assert row.sample_values == ["50", "75"]


def test_flag_issue_rejects_bad_dimension(client, db):
    ds_id = _dataset_id(client, db)
    try:
        dq_agent._tool_flag_issue(
            db,
            ds_id,
            {
                "sheet": "orders",
                "dimension": "made_up",
                "severity": "high",
                "description": "x",
            },
        )
        raise AssertionError("expected ValueError")
    except ValueError as e:
        assert "Unsupported dimension" in str(e)


def test_dispatch_returns_tool_error_string_on_validation_failure(client, db):
    ds_id = _dataset_id(client, db)
    dispatch = dq_agent.make_dq_tool_dispatch(ds_id)
    text, is_error = dispatch(
        "describe_column",
        {"sheet": "customers", "column": "nope"},
        db=db,
        project_id=0,
        keys=LlmKeys(provider="anthropic", llm_api_key="sk-x"),
    )
    assert is_error is True
    assert "rejected input" in text


# ------------------------------------------------------------------
# HTTP endpoints
# ------------------------------------------------------------------


def test_chat_endpoints_require_auth(client):
    assert (
        client.get("/api/projects/1/dq/datasets/1/chat").status_code == 401
    )
    assert (
        client.post(
            "/api/projects/1/dq/datasets/1/chat/stream",
            json={"content": "hi"},
        ).status_code
        == 401
    )


def test_chat_blocked_for_non_dq_project(client, db):
    user, _ = login_as(client, db, "user")
    pid = make_value_discovery_project_directly(db, user)
    r = client.get(f"/api/projects/{pid}/dq/datasets/1/chat")
    # First gate: project type check (404 from underlying gate since the dataset
    # cannot exist for a non-DQ project, but the type gate runs first and returns 400)
    assert r.status_code == 400


def test_chat_stream_400_when_llm_key_missing(client, db):
    login_as_user(client)
    pid = make_dq_project(client)
    ds = _upload(client, pid, _two_sheet_xlsx())
    r = client.post(
        f"/api/projects/{pid}/dq/datasets/{ds['id']}/chat/stream",
        json={"content": "hi"},
    )
    assert r.status_code == 400
    assert "LLM API key" in r.json()["detail"]


def test_chat_list_returns_empty_array_before_any_message(client, db):
    login_as_user(client)
    pid = make_dq_project(client)
    ds = _upload(client, pid, _two_sheet_xlsx())
    r = client.get(f"/api/projects/{pid}/dq/datasets/{ds['id']}/chat")
    assert r.status_code == 200
    assert r.json() == []
    # And calling it created a DQ thread on the project
    threads = (
        db.query(ChatThread).filter_by(project_id=pid, scope="data_quality").all()
    )
    assert len(threads) == 1
    assert threads[0].title == "Data Quality chat"
