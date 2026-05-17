"""Tests for the Data Quality upload + sheet-detection endpoints (Part 2)."""
from __future__ import annotations

import io
from pathlib import Path

import openpyxl
import pytest

from app.auth import SESSION_COOKIE, sessions
from app.models import DataQualityDataset, Project, ProjectType, User

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


def make_value_discovery_project_directly(db, user: User) -> int:
    pt = db.query(ProjectType).filter_by(code="value_discovery").one()
    p = Project(user_id=user.id, project_type_id=pt.id, name="VD")
    db.add(p)
    db.commit()
    db.refresh(p)
    return p.id


# --- xlsx fixture builders ---

def build_xlsx(sheets: dict[str, list[list[object]]]) -> bytes:
    """Build an in-memory .xlsx from {sheet_name: rows_of_cells}."""
    wb = openpyxl.Workbook()
    # Remove the auto-created default sheet
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


def single_sheet_xlsx() -> bytes:
    return build_xlsx(
        {
            "people": [
                ["id", "name", "email"],
                [1, "Alice", "a@example.com"],
                [2, "Bob", "b@example.com"],
                [3, "Carol", "c@example.com"],
            ]
        }
    )


def multi_sheet_xlsx() -> bytes:
    return build_xlsx(
        {
            "customers": [
                ["id", "name"],
                [1, "Acme Co"],
                [2, "Beta Ltd"],
            ],
            "orders": [
                ["id", "customer_id", "amount"],
                [101, 1, 50],
                [102, 1, 75],
                [103, 2, 99],
                [104, 2, 12],
                [105, 2, 33],
            ],
            "products": [
                ["sku", "name", "price"],
                ["A-1", "Widget", 9.99],
            ],
        }
    )


# --- auth + project-type gate ---

def test_dq_endpoints_require_auth(client):
    assert client.get("/api/projects/1/dq/datasets").status_code == 401
    assert client.get("/api/projects/1/dq/datasets/1").status_code == 401
    assert (
        client.post(
            "/api/projects/1/dq/datasets",
            files={"upload": ("x.xlsx", b"x", XLSX_MIME)},
        ).status_code
        == 401
    )
    assert client.delete("/api/projects/1/dq/datasets/1").status_code == 401


def test_dq_blocked_for_non_dq_project(client, db):
    me = login_as(client, db, "user")
    pid = make_value_discovery_project_directly(db, me)
    r = client.get(f"/api/projects/{pid}/dq/datasets")
    assert r.status_code == 400
    assert "data_quality" in r.json()["detail"]


# --- upload happy paths ---

def test_upload_single_sheet_workbook(client, db, tmp_path):
    login_as_user(client)
    pid = make_dq_project(client)

    r = client.post(
        f"/api/projects/{pid}/dq/datasets",
        files={"upload": ("people.xlsx", single_sheet_xlsx(), XLSX_MIME)},
    )
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["project_id"] == pid
    assert body["original_filename"] == "people.xlsx"
    assert len(body["file_sha256"]) == 64
    assert body["engine_version"] == "1.0.0"
    # Part 3 added auto-profiling on upload, so profiled_at is stamped.
    assert body["profiled_at"] is not None
    assert body["sheets"] == [
        {"name": "people", "row_count": 4, "column_count": 3}
    ]

    # File written to disk under the project's data-quality dir
    row = db.query(DataQualityDataset).filter_by(id=body["id"]).one()
    p = Path(row.local_path)
    assert p.exists()
    assert p.parent.name == str(pid)
    assert p.parent.parent.name == "data_quality"


def test_upload_multi_sheet_workbook_reports_precise_counts(client):
    login_as_user(client)
    pid = make_dq_project(client)

    r = client.post(
        f"/api/projects/{pid}/dq/datasets",
        files={"upload": ("biz.xlsx", multi_sheet_xlsx(), XLSX_MIME)},
    )
    assert r.status_code == 201, r.text
    sheets = {s["name"]: s for s in r.json()["sheets"]}
    assert sheets["customers"]["row_count"] == 3
    assert sheets["customers"]["column_count"] == 2
    assert sheets["orders"]["row_count"] == 6
    assert sheets["orders"]["column_count"] == 3
    assert sheets["products"]["row_count"] == 2
    assert sheets["products"]["column_count"] == 3


def test_list_returns_uploaded_datasets_newest_first(client):
    login_as_user(client)
    pid = make_dq_project(client)

    r1 = client.post(
        f"/api/projects/{pid}/dq/datasets",
        files={"upload": ("a.xlsx", single_sheet_xlsx(), XLSX_MIME)},
    )
    r2 = client.post(
        f"/api/projects/{pid}/dq/datasets",
        files={"upload": ("b.xlsx", multi_sheet_xlsx(), XLSX_MIME)},
    )
    assert r1.status_code == 201 and r2.status_code == 201

    listing = client.get(f"/api/projects/{pid}/dq/datasets").json()
    assert [d["original_filename"] for d in listing] == ["b.xlsx", "a.xlsx"]


def test_get_dataset_returns_the_persisted_row(client):
    login_as_user(client)
    pid = make_dq_project(client)
    created = client.post(
        f"/api/projects/{pid}/dq/datasets",
        files={"upload": ("p.xlsx", single_sheet_xlsx(), XLSX_MIME)},
    ).json()

    r = client.get(f"/api/projects/{pid}/dq/datasets/{created['id']}")
    assert r.status_code == 200
    assert r.json()["id"] == created["id"]
    assert r.json()["original_filename"] == "p.xlsx"


# --- upload rejections ---

def test_upload_rejects_non_xlsx_extension(client):
    login_as_user(client)
    pid = make_dq_project(client)
    r = client.post(
        f"/api/projects/{pid}/dq/datasets",
        files={"upload": ("data.csv", b"a,b\n1,2\n", "text/csv")},
    )
    assert r.status_code == 400
    assert "xlsx" in r.json()["detail"].lower()


def test_upload_rejects_oversize(client, monkeypatch):
    from app.data_quality import router as dq_router

    monkeypatch.setattr(dq_router, "MAX_UPLOAD_BYTES", 1024)  # 1 KB cap
    login_as_user(client)
    pid = make_dq_project(client)
    big = b"x" * 2048  # 2 KB; valid mime but oversize
    r = client.post(
        f"/api/projects/{pid}/dq/datasets",
        files={"upload": ("big.xlsx", big, XLSX_MIME)},
    )
    assert r.status_code == 400
    assert "too large" in r.json()["detail"].lower()


def test_upload_rejects_empty_file(client):
    login_as_user(client)
    pid = make_dq_project(client)
    r = client.post(
        f"/api/projects/{pid}/dq/datasets",
        files={"upload": ("empty.xlsx", b"", XLSX_MIME)},
    )
    assert r.status_code == 400
    assert "empty" in r.json()["detail"].lower()


def test_upload_rejects_corrupt_xlsx(client):
    login_as_user(client)
    pid = make_dq_project(client)
    # Right extension and mime, but bytes are not a valid zip/xlsx
    r = client.post(
        f"/api/projects/{pid}/dq/datasets",
        files={"upload": ("fake.xlsx", b"not really an xlsx", XLSX_MIME)},
    )
    assert r.status_code == 400


def test_upload_rejects_password_protected_xlsx(client):
    """An encrypted .xlsx is stored as a CFB compound file, not a zip."""
    login_as_user(client)
    pid = make_dq_project(client)
    # CFB header signature + padding so it looks plausibly large
    encrypted = b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1" + b"\x00" * 512
    r = client.post(
        f"/api/projects/{pid}/dq/datasets",
        files={"upload": ("secret.xlsx", encrypted, XLSX_MIME)},
    )
    assert r.status_code == 400
    assert "password" in r.json()["detail"].lower()


def test_upload_rejects_duplicate_sha(client):
    login_as_user(client)
    pid = make_dq_project(client)
    payload = single_sheet_xlsx()
    r1 = client.post(
        f"/api/projects/{pid}/dq/datasets",
        files={"upload": ("a.xlsx", payload, XLSX_MIME)},
    )
    assert r1.status_code == 201
    r2 = client.post(
        f"/api/projects/{pid}/dq/datasets",
        files={"upload": ("a-copy.xlsx", payload, XLSX_MIME)},
    )
    assert r2.status_code == 409


# --- delete ---

def test_delete_removes_db_row_and_local_file(client, db):
    login_as_user(client)
    pid = make_dq_project(client)
    created = client.post(
        f"/api/projects/{pid}/dq/datasets",
        files={"upload": ("p.xlsx", single_sheet_xlsx(), XLSX_MIME)},
    ).json()
    ds_id = created["id"]
    local_path = Path(
        db.query(DataQualityDataset).filter_by(id=ds_id).one().local_path
    )
    assert local_path.exists()

    r = client.delete(f"/api/projects/{pid}/dq/datasets/{ds_id}")
    assert r.status_code == 204

    db.expire_all()
    assert db.query(DataQualityDataset).filter_by(id=ds_id).count() == 0
    assert not local_path.exists()


def test_delete_404_for_other_project(client):
    login_as_user(client)
    pid_a = make_dq_project(client, "A")
    pid_b = make_dq_project(client, "B")
    ds_id = client.post(
        f"/api/projects/{pid_a}/dq/datasets",
        files={"upload": ("a.xlsx", single_sheet_xlsx(), XLSX_MIME)},
    ).json()["id"]

    r = client.delete(f"/api/projects/{pid_b}/dq/datasets/{ds_id}")
    assert r.status_code == 404
