"""IT Map Agent — Part 5 endpoint tests.

Covers the user-facing kanban endpoints:
- GET /it-map/applications/{id} (drawer payload)
- PATCH /it-map/mappings/{id} (confirm/dismiss)
- POST /it-map/mappings (user-created mapping)

Includes the project-isolation tests: a user cannot read or mutate
another user's mappings, even by guessing ids.
"""
from __future__ import annotations

import io
import json

import openpyxl

from app.auth import SESSION_COOKIE, sessions
from app.it_map import agent as it_agent
from app.models import (
    Application,
    ApplicationCapabilityMapping,
    BcmCapability,
    Project,
    ProjectType,
    User,
)

XLSX_MIME = (
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
)


# ---------------------------------------------------------------------------
# Fixture helpers
# ---------------------------------------------------------------------------


def login_as(client, db, username: str) -> tuple[User, str]:
    user = db.query(User).filter_by(username=username).one_or_none()
    if user is None:
        user = User(username=username)
        db.add(user)
        db.commit()
        db.refresh(user)
    sid = f"test-session-{username}"
    sessions[sid] = username
    client.cookies.set(SESSION_COOKIE, sid)
    return user, sid


def make_vd_project(client) -> int:
    r = client.post(
        "/api/projects",
        json={"name": "VD", "project_type_code": "value_discovery"},
    )
    assert r.status_code == 201, r.text
    return r.json()["id"]


def upload_inventory(client, pid: int) -> int:
    wb = openpyxl.Workbook()
    ws = wb.active
    assert ws is not None
    ws.title = "apps"
    ws.append(["name", "owner"])
    ws.append(["Salesforce", "Bob"])
    ws.append(["Workday", "Alice"])
    buf = io.BytesIO()
    wb.save(buf)
    r = client.post(
        f"/api/projects/{pid}/it-map/inventories",
        files={"upload": ("inv.xlsx", buf.getvalue(), XLSX_MIME)},
    )
    assert r.status_code == 201, r.text
    return r.json()["id"]


def seed_caps(db, pid: int) -> dict[str, int]:
    l1 = BcmCapability(project_id=pid, parent_id=None, level=1, name="Top", position=0)
    db.add(l1)
    db.flush()
    sales = BcmCapability(project_id=pid, parent_id=l1.id, level=2, name="Sales", position=0)
    hr = BcmCapability(project_id=pid, parent_id=l1.id, level=2, name="HR", position=1)
    fin = BcmCapability(project_id=pid, parent_id=None, level=2, name="Finance", position=2)
    l3 = BcmCapability(project_id=pid, parent_id=sales.id, level=3, name="Pricing", position=0)
    db.add_all([sales, hr, fin, l3])
    db.commit()
    return {"Top": l1.id, "Sales": sales.id, "HR": hr.id, "Finance": fin.id, "Pricing": l3.id}


def _materialize(client, db, pid: int) -> tuple[int, list[Application], dict[str, int]]:
    """Build a VD project + inventory + BCM, run propose_schema directly
    to materialise Application rows, and return ids the tests can use."""
    iid = upload_inventory(client, pid)
    caps = seed_caps(db, pid)
    it_agent._tool_propose_schema(
        db,
        iid,
        {"name_column": "name", "owner_column": "owner"},
    )
    db.commit()
    apps = (
        db.query(Application)
        .filter_by(inventory_id=iid)
        .order_by(Application.row_index)
        .all()
    )
    return iid, apps, caps


# ---------------------------------------------------------------------------
# GET /applications/{id}
# ---------------------------------------------------------------------------


def test_get_application_returns_app_with_mappings(client, db) -> None:
    login_as(client, db, "user")
    pid = make_vd_project(client)
    _iid, apps, caps = _materialize(client, db, pid)
    # Seed one suggested mapping so we can assert it round-trips.
    db.add(
        ApplicationCapabilityMapping(
            application_id=apps[0].id,
            capability_id=caps["Sales"],
            confidence=0.8,
            rationale="agent guess",
            status="suggested",
            engine_version="it-map-agent/1.0.0",
        )
    )
    db.commit()

    r = client.get(f"/api/projects/{pid}/it-map/applications/{apps[0].id}")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["inferred_name"] == "Salesforce"
    assert len(body["mappings"]) == 1
    assert body["mappings"][0]["capability_id"] == caps["Sales"]


def test_get_application_404_for_other_users_app(client, db) -> None:
    """Project isolation: even with a guessed id, the response is 404."""
    login_as(client, db, "alice")
    pid_alice = make_vd_project(client)
    _iid, apps_alice, _ = _materialize(client, db, pid_alice)

    login_as(client, db, "bob")
    pid_bob = make_vd_project(client)
    r = client.get(
        f"/api/projects/{pid_bob}/it-map/applications/{apps_alice[0].id}"
    )
    assert r.status_code == 404


# ---------------------------------------------------------------------------
# PATCH /mappings/{id}
# ---------------------------------------------------------------------------


def test_patch_confirms_a_suggested_mapping(client, db) -> None:
    login_as(client, db, "user")
    pid = make_vd_project(client)
    _iid, apps, caps = _materialize(client, db, pid)
    mapping = ApplicationCapabilityMapping(
        application_id=apps[0].id,
        capability_id=caps["Sales"],
        confidence=0.8,
        rationale="agent",
        status="suggested",
        engine_version="it-map-agent/1.0.0",
    )
    db.add(mapping)
    db.commit()
    db.refresh(mapping)

    r = client.patch(
        f"/api/projects/{pid}/it-map/mappings/{mapping.id}",
        json={"status": "confirmed"},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["status"] == "confirmed"
    assert body["confirmed_at"] is not None
    assert body["dismissed_at"] is None


def test_patch_dismissed_then_confirm_clears_dismissed_at(client, db) -> None:
    """User can revise a prior decision — the opposite timestamp clears
    so a future audit doesn't see both states stamped together."""
    login_as(client, db, "user")
    pid = make_vd_project(client)
    _iid, apps, caps = _materialize(client, db, pid)
    mapping = ApplicationCapabilityMapping(
        application_id=apps[0].id,
        capability_id=caps["Sales"],
        confidence=0.8,
        rationale="agent",
        status="suggested",
        engine_version="it-map-agent/1.0.0",
    )
    db.add(mapping)
    db.commit()

    client.patch(
        f"/api/projects/{pid}/it-map/mappings/{mapping.id}",
        json={"status": "dismissed"},
    )
    body = client.patch(
        f"/api/projects/{pid}/it-map/mappings/{mapping.id}",
        json={"status": "confirmed"},
    ).json()
    assert body["status"] == "confirmed"
    assert body["confirmed_at"] is not None
    assert body["dismissed_at"] is None  # cleared on flip


def test_patch_404_for_other_users_mapping(client, db) -> None:
    login_as(client, db, "alice")
    pid_alice = make_vd_project(client)
    _iid, apps_alice, caps_alice = _materialize(client, db, pid_alice)
    mapping = ApplicationCapabilityMapping(
        application_id=apps_alice[0].id,
        capability_id=caps_alice["Sales"],
        confidence=0.5,
        rationale="x",
        status="suggested",
        engine_version="it-map-agent/1.0.0",
    )
    db.add(mapping)
    db.commit()
    db.refresh(mapping)

    login_as(client, db, "bob")
    pid_bob = make_vd_project(client)
    r = client.patch(
        f"/api/projects/{pid_bob}/it-map/mappings/{mapping.id}",
        json={"status": "confirmed"},
    )
    assert r.status_code == 404


# ---------------------------------------------------------------------------
# POST /mappings (user-driven)
# ---------------------------------------------------------------------------


def test_post_creates_user_mapping_with_confirmed_status(client, db) -> None:
    login_as(client, db, "user")
    pid = make_vd_project(client)
    _iid, apps, caps = _materialize(client, db, pid)

    r = client.post(
        f"/api/projects/{pid}/it-map/mappings",
        json={
            "application_id": apps[0].id,
            "capability_id": caps["Sales"],
            "rationale": "I know our CRM is for sales",
        },
    )
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["status"] == "confirmed"
    assert body["engine_version"] == "user"
    assert body["confidence"] == 1.0
    assert body["confirmed_at"] is not None


def test_post_rejects_non_l2_capability(client, db) -> None:
    login_as(client, db, "user")
    pid = make_vd_project(client)
    _iid, apps, caps = _materialize(client, db, pid)
    for cap_name in ("Top", "Pricing"):
        r = client.post(
            f"/api/projects/{pid}/it-map/mappings",
            json={
                "application_id": apps[0].id,
                "capability_id": caps[cap_name],
                "rationale": "x",
            },
        )
        assert r.status_code == 400, f"{cap_name}: {r.text}"
        assert "L2" in r.json()["detail"]


def test_post_returns_409_on_duplicate(client, db) -> None:
    login_as(client, db, "user")
    pid = make_vd_project(client)
    _iid, apps, caps = _materialize(client, db, pid)

    first = client.post(
        f"/api/projects/{pid}/it-map/mappings",
        json={
            "application_id": apps[0].id,
            "capability_id": caps["Sales"],
            "rationale": "x",
        },
    )
    assert first.status_code == 201

    dup = client.post(
        f"/api/projects/{pid}/it-map/mappings",
        json={
            "application_id": apps[0].id,
            "capability_id": caps["Sales"],
            "rationale": "y",
        },
    )
    assert dup.status_code == 409
    # The 409 surfaces the existing id so the client can PATCH instead.
    assert str(first.json()["id"]) in dup.json()["detail"]


def test_post_404_for_other_users_application(client, db) -> None:
    login_as(client, db, "alice")
    pid_alice = make_vd_project(client)
    _iid, apps_alice, _ = _materialize(client, db, pid_alice)

    login_as(client, db, "bob")
    pid_bob = make_vd_project(client)
    caps_bob = seed_caps(db, pid_bob)
    r = client.post(
        f"/api/projects/{pid_bob}/it-map/mappings",
        json={
            "application_id": apps_alice[0].id,
            "capability_id": caps_bob["Sales"],
            "rationale": "x",
        },
    )
    assert r.status_code == 404


def test_endpoints_require_value_discovery_project(client, db) -> None:
    user, _ = login_as(client, db, "user")
    pt = (
        db.query(ProjectType).filter_by(code="data_quality_assessment").one()
    )
    p = Project(user_id=user.id, project_type_id=pt.id, name="DQ")
    db.add(p)
    db.commit()
    db.refresh(p)

    r = client.get(f"/api/projects/{p.id}/it-map/applications/1")
    assert r.status_code == 400
    r = client.patch(
        f"/api/projects/{p.id}/it-map/mappings/1",
        json={"status": "confirmed"},
    )
    assert r.status_code == 400
    r = client.post(
        f"/api/projects/{p.id}/it-map/mappings",
        json={"application_id": 1, "capability_id": 1, "rationale": "x"},
    )
    assert r.status_code == 400
    # Project-scoped applications endpoint added in US 2.1.
    r = client.get(f"/api/projects/{p.id}/it-map/applications")
    assert r.status_code == 400


# ---------------------------------------------------------------------------
# US 2.1 — GET /it-map/applications (project-scoped, status-filterable)
# ---------------------------------------------------------------------------


def _seed_project_with_mixed_mappings(client, db):
    """Build a project + two inventories + apps with mappings in all
    three statuses, and return ids the tests can assert against."""
    login_as(client, db, "user")
    pid = make_vd_project(client)
    caps = seed_caps(db, pid)

    # First inventory: Salesforce (confirmed) + Stripe (dismissed).
    iid_1 = upload_inventory(client, pid)
    import app.it_map.agent as it_agent
    it_agent._tool_propose_schema(db, iid_1, {"name_column": "name"})
    db.commit()
    apps_1 = (
        db.query(Application)
        .filter_by(inventory_id=iid_1)
        .order_by(Application.row_index)
        .all()
    )
    db.add(
        ApplicationCapabilityMapping(
            application_id=apps_1[0].id,
            capability_id=caps["Sales"],
            confidence=0.9,
            rationale="confirmed by user",
            status="confirmed",
            engine_version="user",
        )
    )
    db.add(
        ApplicationCapabilityMapping(
            application_id=apps_1[1].id,
            capability_id=caps["Finance"],
            confidence=0.4,
            rationale="user dismissed",
            status="dismissed",
            engine_version="it-map-agent/1.0.0",
        )
    )

    # Second inventory: one app with a suggested mapping (so we can
    # verify the status filter excludes/includes correctly across
    # inventories).
    iid_2 = _upload_minimal(client, pid, sheet_apps=["AcmePay"])
    it_agent._tool_propose_schema(db, iid_2, {"name_column": "name"})
    db.commit()
    apps_2 = (
        db.query(Application)
        .filter_by(inventory_id=iid_2)
        .order_by(Application.row_index)
        .all()
    )
    db.add(
        ApplicationCapabilityMapping(
            application_id=apps_2[0].id,
            capability_id=caps["Sales"],
            confidence=0.7,
            rationale="agent guess",
            status="suggested",
            engine_version="it-map-agent/1.0.0",
        )
    )
    db.commit()
    return pid, iid_1, iid_2, apps_1, apps_2, caps


def _upload_minimal(client, pid: int, *, sheet_apps: list[str]) -> int:
    """Helper for a second inventory in the same project so the test can
    verify cross-inventory aggregation."""
    import io as _io
    wb = openpyxl.Workbook()
    ws = wb.active
    assert ws is not None
    ws.title = "apps"
    ws.append(["name"])
    for n in sheet_apps:
        ws.append([n])
    buf = _io.BytesIO()
    wb.save(buf)
    r = client.post(
        f"/api/projects/{pid}/it-map/inventories",
        files={"upload": (f"{sheet_apps[0]}.xlsx", buf.getvalue(), XLSX_MIME)},
    )
    assert r.status_code == 201, r.text
    return r.json()["id"]


def test_project_applications_aggregates_across_inventories(client, db) -> None:
    """No filter -> every app across every inventory of the project,
    each with all its mappings regardless of status."""
    pid, _i1, _i2, apps_1, apps_2, _caps = _seed_project_with_mixed_mappings(
        client, db
    )
    r = client.get(f"/api/projects/{pid}/it-map/applications")
    assert r.status_code == 200, r.text
    body = r.json()
    ids = {a["id"] for a in body}
    # 2 apps in inventory 1 + 1 app in inventory 2 = 3.
    assert ids == {apps_1[0].id, apps_1[1].id, apps_2[0].id}
    # Status filter omitted -> mappings are included as-is.
    counts_by_id = {a["id"]: len(a["mappings"]) for a in body}
    assert counts_by_id[apps_1[0].id] == 1
    assert counts_by_id[apps_1[1].id] == 1  # the dismissed one is still listed
    assert counts_by_id[apps_2[0].id] == 1


def test_project_applications_status_filter_confirmed_for_graph(client, db) -> None:
    """The BCM graph uses status_filter=confirmed: only apps with at
    least one confirmed mapping, with the mappings list filtered to
    confirmed only (no suggested or dismissed in the response)."""
    pid, _i1, _i2, apps_1, _apps_2, _caps = _seed_project_with_mixed_mappings(
        client, db
    )
    r = client.get(
        f"/api/projects/{pid}/it-map/applications?status_filter=confirmed"
    )
    assert r.status_code == 200, r.text
    body = r.json()
    # Only Salesforce (apps_1[0]) has a confirmed mapping; everyone else
    # has a suggested or dismissed mapping or none, so they're excluded.
    assert {a["id"] for a in body} == {apps_1[0].id}
    only = body[0]
    assert len(only["mappings"]) == 1
    assert only["mappings"][0]["status"] == "confirmed"


def test_project_applications_status_filter_validation(client, db) -> None:
    login_as(client, db, "user")
    pid = make_vd_project(client)
    r = client.get(
        f"/api/projects/{pid}/it-map/applications?status_filter=made_up"
    )
    assert r.status_code == 400
    assert "suggested" in r.json()["detail"]


def test_project_applications_isolates_users(client, db) -> None:
    """Project isolation: user B cannot read user A's apps even by
    guessing the project_id."""
    pid_alice, *_ = _seed_project_with_mixed_mappings(client, db)
    # Switch to Bob
    login_as(client, db, "bob")
    r = client.get(f"/api/projects/{pid_alice}/it-map/applications")
    assert r.status_code == 404
