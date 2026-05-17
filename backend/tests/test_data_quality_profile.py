"""End-to-end tests for the profile orchestrator: upload triggers
profiling, persisted rows match what the engine produced, and re-profiling
preserves user-set bounds."""
from __future__ import annotations

import io

import openpyxl

from app.auth import SESSION_COOKIE, sessions
from app.models import (
    DataQualityColumnProfile,
    DataQualityDataset,
    DataQualityIssue,
    DataQualitySheetProfile,
    User,
)

XLSX_MIME = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


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


def make_dq_project(client, name: str = "DQ") -> int:
    r = client.post(
        "/api/projects",
        json={"name": name, "project_type_code": "data_quality_assessment"},
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

def test_upload_auto_profiles_and_persists_rows(client, db):
    """Upload should trigger profiling so the dashboard data is ready
    by the time the POST returns."""
    login_as_user(client)
    pid = make_dq_project(client)
    payload = build_xlsx(
        {
            "people": [
                ["id", "name", "email", "score"],
                [1, "Alice", "alice@example.com", 95],
                [2, "Bob", "bob@example.com", 88],
                [3, "Carol", "carol@example.com", 72],
                [4, "Dan", "dan@example.com", 64],
            ]
        }
    )
    body = _upload(client, pid, payload)
    ds_id = body["id"]

    # The dataset row gets a profiled_at stamp
    db.expire_all()
    ds = db.query(DataQualityDataset).filter_by(id=ds_id).one()
    assert ds.profiled_at is not None

    # And the sheet/column profiles are persisted
    sheets = (
        db.query(DataQualitySheetProfile).filter_by(dataset_id=ds_id).all()
    )
    assert len(sheets) == 1
    assert sheets[0].sheet_name == "people"
    assert sheets[0].row_count == 4
    assert sheets[0].column_count == 4

    cols = {
        c.name: c
        for c in db.query(DataQualityColumnProfile)
        .filter_by(sheet_profile_id=sheets[0].id)
        .all()
    }
    assert set(cols) == {"id", "name", "email", "score"}
    assert cols["id"].semantic_type == "integer"
    assert cols["score"].semantic_type == "integer"
    assert cols["email"].pattern_label == "email"
    assert cols["email"].pattern_conformance_pct == 100.0


def test_get_profile_endpoint_returns_columns_and_top_values(client):
    login_as_user(client)
    pid = make_dq_project(client)
    payload = build_xlsx(
        {
            "small": [
                ["status"],
                ["active"],
                ["active"],
                ["active"],
                ["inactive"],
            ]
        }
    )
    ds = _upload(client, pid, payload)

    r = client.get(f"/api/projects/{pid}/dq/datasets/{ds['id']}/profile")
    assert r.status_code == 200, r.text
    sheets = r.json()
    assert len(sheets) == 1
    cols = sheets[0]["columns"]
    assert len(cols) == 1
    col = cols[0]
    assert col["name"] == "status"
    # top_values exposes parsed JSON, not the raw string
    values = {tv["value"]: tv["count"] for tv in col["top_values"]}
    assert values == {"active": 3, "inactive": 1}


def test_list_issues_endpoint_filters_by_sheet_and_severity(client):
    login_as_user(client)
    pid = make_dq_project(client)
    # A column that is 60% null -> high-severity completeness issue
    payload = build_xlsx(
        {
            "s1": [
                ["x"],
                [None],
                [None],
                [None],
                [1],
                [2],
            ],
            "s2": [
                ["y"],
                [1],
                [2],
                [3],
                [4],
                [5],
            ],
        }
    )
    ds = _upload(client, pid, payload)

    all_issues = client.get(
        f"/api/projects/{pid}/dq/datasets/{ds['id']}/issues"
    ).json()
    assert any(
        i["sheet_name"] == "s1" and i["dimension"] == "completeness"
        for i in all_issues
    )

    s1_only = client.get(
        f"/api/projects/{pid}/dq/datasets/{ds['id']}/issues?sheet=s1"
    ).json()
    assert {i["sheet_name"] for i in s1_only} == {"s1"}

    high_only = client.get(
        f"/api/projects/{pid}/dq/datasets/{ds['id']}/issues?severity=high"
    ).json()
    assert all(i["severity"] == "high" for i in high_only)


def test_setting_bounds_re_profiles_and_emits_validity_issue(client):
    login_as_user(client)
    pid = make_dq_project(client)
    payload = build_xlsx(
        {
            "s": [
                ["score"],
                [1],
                [2],
                [3],
                [100],
                [200],
            ]
        }
    )
    ds = _upload(client, pid, payload)

    # Initially: no bounds, no validity issue
    initial = client.get(
        f"/api/projects/{pid}/dq/datasets/{ds['id']}/issues?severity=high"
    ).json()
    assert not any(i["dimension"] == "validity" for i in initial)

    # Set bounds [0, 10] -> 100 and 200 violate
    r = client.patch(
        f"/api/projects/{pid}/dq/datasets/{ds['id']}/sheets/s/columns/score/bounds",
        json={"range_min": 0, "range_max": 10},
    )
    assert r.status_code == 200, r.text
    after = client.get(
        f"/api/projects/{pid}/dq/datasets/{ds['id']}/issues?severity=high"
    ).json()
    validity = [i for i in after if i["dimension"] == "validity"]
    assert len(validity) == 1
    assert "score" in validity[0]["description"]


def test_bounds_survive_recompute(client, db):
    login_as_user(client)
    pid = make_dq_project(client)
    payload = build_xlsx(
        {"s": [["score"], [1], [2], [3], [4], [5]]}
    )
    ds = _upload(client, pid, payload)

    # Set bounds
    client.patch(
        f"/api/projects/{pid}/dq/datasets/{ds['id']}/sheets/s/columns/score/bounds",
        json={"range_min": 0, "range_max": 10},
    )

    # Trigger a manual re-profile
    r = client.post(
        f"/api/projects/{pid}/dq/datasets/{ds['id']}/profile"
    )
    assert r.status_code == 200, r.text

    db.expire_all()
    col = (
        db.query(DataQualityColumnProfile)
        .join(
            DataQualitySheetProfile,
            DataQualityColumnProfile.sheet_profile_id == DataQualitySheetProfile.id,
        )
        .filter(
            DataQualitySheetProfile.dataset_id == ds["id"],
            DataQualityColumnProfile.name == "score",
        )
        .one()
    )
    assert col.range_min == 0.0
    assert col.range_max == 10.0


def test_recompute_invalidates_old_profile_rows(client, db):
    """A re-profile must replace, not append, the prior profile graph."""
    login_as_user(client)
    pid = make_dq_project(client)
    payload = build_xlsx(
        {"s": [["x"], [1], [2], [3]]}
    )
    ds = _upload(client, pid, payload)

    before = db.query(DataQualitySheetProfile).filter_by(dataset_id=ds["id"]).count()
    assert before == 1
    before_cols = db.query(DataQualityColumnProfile).count()
    before_issues = db.query(DataQualityIssue).filter_by(dataset_id=ds["id"]).count()

    r = client.post(f"/api/projects/{pid}/dq/datasets/{ds['id']}/profile")
    assert r.status_code == 200

    db.expire_all()
    after = db.query(DataQualitySheetProfile).filter_by(dataset_id=ds["id"]).count()
    assert after == 1
    # column profile total is unchanged (we don't get duplicates)
    assert db.query(DataQualityColumnProfile).count() == before_cols
    assert (
        db.query(DataQualityIssue).filter_by(dataset_id=ds["id"]).count()
        == before_issues
    )


def test_set_bounds_404_for_unknown_column(client):
    login_as_user(client)
    pid = make_dq_project(client)
    payload = build_xlsx({"s": [["x"], [1], [2]]})
    ds = _upload(client, pid, payload)

    r = client.patch(
        f"/api/projects/{pid}/dq/datasets/{ds['id']}/sheets/s/columns/nope/bounds",
        json={"range_min": 0, "range_max": 1},
    )
    assert r.status_code == 404


def test_set_bounds_rejects_min_greater_than_max(client):
    login_as_user(client)
    pid = make_dq_project(client)
    payload = build_xlsx({"s": [["x"], [1], [2]]})
    ds = _upload(client, pid, payload)

    r = client.patch(
        f"/api/projects/{pid}/dq/datasets/{ds['id']}/sheets/s/columns/x/bounds",
        json={"range_min": 10, "range_max": 0},
    )
    assert r.status_code == 400


def test_deleting_dataset_cascades_to_profile_and_issues(client, db):
    login_as_user(client)
    pid = make_dq_project(client)
    payload = build_xlsx(
        {"s": [["x"], [None], [None], [None], [1], [2]]}
    )
    ds = _upload(client, pid, payload)
    ds_id = ds["id"]
    assert (
        db.query(DataQualityIssue).filter_by(dataset_id=ds_id).count() > 0
    )

    r = client.delete(f"/api/projects/{pid}/dq/datasets/{ds_id}")
    assert r.status_code == 204

    db.expire_all()
    assert db.query(DataQualitySheetProfile).filter_by(dataset_id=ds_id).count() == 0
    assert db.query(DataQualityIssue).filter_by(dataset_id=ds_id).count() == 0
    assert db.query(DataQualityColumnProfile).count() == 0
