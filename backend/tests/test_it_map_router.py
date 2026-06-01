"""IT Map Agent — Part 1 tests.

Covers: upload + inspect, list, delete, project-type gating, dedup on
sha256, multi-sheet primary-sheet selection.
"""
from __future__ import annotations

import io
from pathlib import Path

import openpyxl

from app.auth import SESSION_COOKIE, sessions
from app.models import ApplicationInventory, Project, ProjectType, User

XLSX_MIME = (
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


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


def make_vd_project(client) -> int:
    """Create a Value Discovery project — IT Map lives on these."""
    r = client.post(
        "/api/projects",
        json={"name": "VD project", "project_type_code": "value_discovery"},
    )
    assert r.status_code == 201, r.text
    return r.json()["id"]


def make_dq_project_directly(db, user: User) -> int:
    """Create a Data Quality project directly (bypassing the API) so we
    can verify the IT Map endpoints reject it with 400."""
    pt = (
        db.query(ProjectType).filter_by(code="data_quality_assessment").one()
    )
    p = Project(user_id=user.id, project_type_id=pt.id, name="DQ")
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


def _single_sheet_inventory() -> bytes:
    return build_xlsx(
        {
            "applications": [
                ["app_name", "vendor", "business_function"],
                ["Salesforce", "Salesforce.com", "Sales"],
                ["SAP S/4HANA", "SAP", "Finance"],
                ["Workday", "Workday", "HR"],
            ]
        }
    )


def _multi_sheet_inventory_with_largest_second() -> bytes:
    return build_xlsx(
        {
            "metadata": [["key", "value"], ["created", "2026-05"]],
            "apps": [
                ["app_name", "owner"],
                ["A", "alice"],
                ["B", "bob"],
                ["C", "carol"],
                ["D", "dave"],
                ["E", "eve"],
            ],
            "notes": [["text"], ["just a single-line note sheet"]],
        }
    )


def _upload(
    client, pid: int, payload: bytes, filename: str = "inv.xlsx"
) -> dict:
    r = client.post(
        f"/api/projects/{pid}/it-map/inventories",
        files={"upload": (filename, payload, XLSX_MIME)},
    )
    assert r.status_code == 201, r.text
    return r.json()


# ---------------------------------------------------------------------------
# Endpoint tests
# ---------------------------------------------------------------------------


def test_list_inventories_requires_auth(client) -> None:
    r = client.get("/api/projects/1/it-map/inventories")
    assert r.status_code == 401


def test_upload_rejects_non_xlsx_extension(client) -> None:
    login_as_user(client)
    pid = make_vd_project(client)
    r = client.post(
        f"/api/projects/{pid}/it-map/inventories",
        files={"upload": ("data.csv", b"a,b\n1,2\n", "text/csv")},
    )
    assert r.status_code == 400
    assert ".csv" in r.json()["detail"]


def test_upload_rejects_empty_file(client) -> None:
    login_as_user(client)
    pid = make_vd_project(client)
    r = client.post(
        f"/api/projects/{pid}/it-map/inventories",
        files={"upload": ("inv.xlsx", b"", XLSX_MIME)},
    )
    assert r.status_code == 400
    assert "Empty" in r.json()["detail"]


def test_upload_succeeds_and_records_primary_sheet(client, db) -> None:
    login_as_user(client)
    pid = make_vd_project(client)
    body = _upload(client, pid, _single_sheet_inventory())

    assert body["project_id"] == pid
    assert body["original_filename"] == "inv.xlsx"
    assert body["primary_sheet"] == "applications"
    assert body["engine_version"] == "1.0.0"
    sheet_names = {s["name"] for s in body["sheets"]}
    assert sheet_names == {"applications"}

    # Persisted row should be queryable and have the file on disk.
    row = (
        db.query(ApplicationInventory).filter_by(id=body["id"]).one()
    )
    assert row.primary_sheet == "applications"
    assert Path(row.local_path).is_file()


def test_upload_multi_sheet_picks_largest_as_primary(client, db) -> None:
    """Per the single-sheet inventory assumption, the largest sheet
    wins. metadata=1 row, apps=5 rows, notes=1 row -> primary='apps'."""
    login_as_user(client)
    pid = make_vd_project(client)
    body = _upload(client, pid, _multi_sheet_inventory_with_largest_second())
    assert body["primary_sheet"] == "apps"
    names = {s["name"] for s in body["sheets"]}
    assert names == {"metadata", "apps", "notes"}


def test_upload_dedup_by_sha256_returns_409(client, db) -> None:
    login_as_user(client)
    pid = make_vd_project(client)
    payload = _single_sheet_inventory()
    first = _upload(client, pid, payload)

    r = client.post(
        f"/api/projects/{pid}/it-map/inventories",
        files={"upload": ("re-upload.xlsx", payload, XLSX_MIME)},
    )
    assert r.status_code == 409
    # Surface the original inventory id so the UI can deep-link to it.
    assert str(first["id"]) in r.json()["detail"]


def test_list_inventories_returns_uploaded_rows(client) -> None:
    login_as_user(client)
    pid = make_vd_project(client)
    body = _upload(client, pid, _single_sheet_inventory())

    r = client.get(f"/api/projects/{pid}/it-map/inventories")
    assert r.status_code == 200
    rows = r.json()
    assert len(rows) == 1
    assert rows[0]["id"] == body["id"]


def test_delete_inventory_removes_file_and_row(client, db) -> None:
    login_as_user(client)
    pid = make_vd_project(client)
    body = _upload(client, pid, _single_sheet_inventory())
    local_path = Path(
        db.query(ApplicationInventory).filter_by(id=body["id"]).one().local_path
    )
    assert local_path.is_file()

    r = client.delete(
        f"/api/projects/{pid}/it-map/inventories/{body['id']}"
    )
    assert r.status_code == 204
    assert not local_path.is_file()
    assert (
        db.query(ApplicationInventory).filter_by(id=body["id"]).one_or_none()
        is None
    )


def test_endpoints_reject_non_value_discovery_project(client, db) -> None:
    user, _ = login_as(client, db, "user")
    pid = make_dq_project_directly(db, user)

    # Each endpoint should 400 with a clear message rather than
    # silently allowing IT Map data to be attached to the wrong project type.
    r = client.get(f"/api/projects/{pid}/it-map/inventories")
    assert r.status_code == 400
    assert "value_discovery" in r.json()["detail"]

    r = client.post(
        f"/api/projects/{pid}/it-map/inventories",
        files={"upload": ("inv.xlsx", _single_sheet_inventory(), XLSX_MIME)},
    )
    assert r.status_code == 400


def test_endpoints_404_for_other_users_project(client, db) -> None:
    """A user cannot see or mutate another user's inventories."""
    # User A uploads.
    _ua, _ = login_as(client, db, "alice")
    pid_a = make_vd_project(client)
    inv_a = _upload(client, pid_a, _single_sheet_inventory())

    # User B logs in and tries to touch User A's inventory.
    login_as(client, db, "bob")
    r = client.get(f"/api/projects/{pid_a}/it-map/inventories")
    assert r.status_code == 404
    r = client.delete(
        f"/api/projects/{pid_a}/it-map/inventories/{inv_a['id']}"
    )
    assert r.status_code == 404
