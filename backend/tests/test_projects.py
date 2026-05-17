from app.auth import SESSION_COOKIE, sessions
from app.models import User, ValueDiscoveryOpportunity


def login_as_user(client):
    """Log in via the real endpoint as the hardcoded MVP user."""
    r = client.post(
        "/api/auth/login",
        json={"username": "user", "password": "password"},
    )
    assert r.status_code == 200


def login_as(client, db, username: str):
    """Test-only: inject a session for an arbitrary username, creating the User row."""
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


# --- Auth gate ---

def test_list_projects_requires_auth(client):
    assert client.get("/api/projects").status_code == 401


def test_create_project_requires_auth(client):
    r = client.post(
        "/api/projects",
        json={"name": "X", "project_type_code": "value_discovery"},
    )
    assert r.status_code == 401


def test_get_project_requires_auth(client):
    assert client.get("/api/projects/1").status_code == 401


def test_update_project_requires_auth(client):
    assert (
        client.patch("/api/projects/1", json={"name": "Y"}).status_code == 401
    )


def test_delete_project_requires_auth(client):
    assert client.delete("/api/projects/1").status_code == 401


def test_list_project_types_requires_auth(client):
    assert client.get("/api/project-types").status_code == 401


def test_opportunities_require_auth(client):
    assert client.get("/api/projects/1/opportunities").status_code == 401
    assert (
        client.post("/api/projects/1/opportunities", json={"title": "T"}).status_code
        == 401
    )


# --- Project types ---

def test_list_project_types(client):
    login_as_user(client)
    r = client.get("/api/project-types")
    assert r.status_code == 200
    types = r.json()
    codes = [t["code"] for t in types]
    assert codes == [
        "value_discovery",
        "business_process_discovery",
        "ai_assessment",
        "data_quality_assessment",
    ]
    active_codes = sorted(t["code"] for t in types if t["is_active"])
    assert active_codes == ["data_quality_assessment", "value_discovery"]


# --- Project happy path ---

def test_create_and_list_project(client):
    login_as_user(client)

    r = client.post(
        "/api/projects",
        json={"name": "Q3 Discovery", "project_type_code": "value_discovery"},
    )
    assert r.status_code == 201
    project = r.json()
    assert project["name"] == "Q3 Discovery"
    assert project["status"] == "draft"
    assert project["project_type"]["code"] == "value_discovery"

    listed = client.get("/api/projects")
    assert listed.status_code == 200
    items = listed.json()
    assert len(items) == 1
    assert items[0]["id"] == project["id"]


def test_get_project(client):
    login_as_user(client)
    pid = client.post(
        "/api/projects",
        json={"name": "P", "project_type_code": "value_discovery"},
    ).json()["id"]
    r = client.get(f"/api/projects/{pid}")
    assert r.status_code == 200
    assert r.json()["id"] == pid


def test_update_project(client):
    login_as_user(client)
    pid = client.post(
        "/api/projects",
        json={"name": "Old", "project_type_code": "value_discovery"},
    ).json()["id"]

    r = client.patch(
        f"/api/projects/{pid}", json={"name": "New", "status": "active"}
    )
    assert r.status_code == 200
    assert r.json()["name"] == "New"
    assert r.json()["status"] == "active"


def test_delete_project(client):
    login_as_user(client)
    pid = client.post(
        "/api/projects",
        json={"name": "P", "project_type_code": "value_discovery"},
    ).json()["id"]

    assert client.delete(f"/api/projects/{pid}").status_code == 204
    assert client.get(f"/api/projects/{pid}").status_code == 404


# --- Project validation ---

def test_create_project_rejects_unknown_type(client):
    login_as_user(client)
    r = client.post(
        "/api/projects", json={"name": "X", "project_type_code": "nope"}
    )
    assert r.status_code == 400


def test_create_project_rejects_inactive_type(client):
    login_as_user(client)
    r = client.post(
        "/api/projects",
        json={"name": "X", "project_type_code": "ai_assessment"},
    )
    assert r.status_code == 400


def test_create_project_rejects_empty_name(client):
    login_as_user(client)
    r = client.post(
        "/api/projects",
        json={"name": "", "project_type_code": "value_discovery"},
    )
    assert r.status_code == 422


def test_update_project_rejects_invalid_status(client):
    login_as_user(client)
    pid = client.post(
        "/api/projects",
        json={"name": "P", "project_type_code": "value_discovery"},
    ).json()["id"]
    r = client.patch(f"/api/projects/{pid}", json={"status": "totally-bogus"})
    assert r.status_code == 422


def test_get_missing_project_returns_404(client):
    login_as_user(client)
    assert client.get("/api/projects/9999").status_code == 404


# --- Cross-user isolation ---

def test_user_only_lists_their_own_projects(client, db):
    login_as_user(client)
    client.post(
        "/api/projects",
        json={"name": "Mine", "project_type_code": "value_discovery"},
    )

    client.cookies.clear()
    login_as(client, db, "intruder")

    r = client.get("/api/projects")
    assert r.status_code == 200
    assert r.json() == []


def test_cross_user_get_patch_delete_return_404(client, db):
    login_as_user(client)
    pid = client.post(
        "/api/projects",
        json={"name": "Mine", "project_type_code": "value_discovery"},
    ).json()["id"]

    client.cookies.clear()
    login_as(client, db, "intruder")

    assert client.get(f"/api/projects/{pid}").status_code == 404
    assert (
        client.patch(f"/api/projects/{pid}", json={"name": "Stolen"}).status_code
        == 404
    )
    assert client.delete(f"/api/projects/{pid}").status_code == 404


# --- Opportunities ---

def test_create_and_list_opportunity(client):
    login_as_user(client)
    pid = client.post(
        "/api/projects",
        json={"name": "P", "project_type_code": "value_discovery"},
    ).json()["id"]

    r = client.post(
        f"/api/projects/{pid}/opportunities",
        json={
            "title": "Reduce invoice processing time",
            "description": "Automate manual entry",
            "estimated_annual_value_cents": 50_000_000,
            "effort": "medium",
            "priority": "high",
        },
    )
    assert r.status_code == 201
    opp = r.json()
    assert opp["title"] == "Reduce invoice processing time"
    assert opp["status"] == "identified"
    assert opp["estimated_annual_value_cents"] == 50_000_000

    listed = client.get(f"/api/projects/{pid}/opportunities")
    assert listed.status_code == 200
    assert len(listed.json()) == 1


def test_create_opportunity_rejects_empty_title(client):
    login_as_user(client)
    pid = client.post(
        "/api/projects",
        json={"name": "P", "project_type_code": "value_discovery"},
    ).json()["id"]
    r = client.post(f"/api/projects/{pid}/opportunities", json={"title": ""})
    assert r.status_code == 422


def test_create_opportunity_rejects_negative_value(client):
    login_as_user(client)
    pid = client.post(
        "/api/projects",
        json={"name": "P", "project_type_code": "value_discovery"},
    ).json()["id"]
    r = client.post(
        f"/api/projects/{pid}/opportunities",
        json={"title": "T", "estimated_annual_value_cents": -1},
    )
    assert r.status_code == 422


def test_update_opportunity(client):
    login_as_user(client)
    pid = client.post(
        "/api/projects",
        json={"name": "P", "project_type_code": "value_discovery"},
    ).json()["id"]
    oid = client.post(
        f"/api/projects/{pid}/opportunities", json={"title": "T"}
    ).json()["id"]

    r = client.patch(
        f"/api/projects/{pid}/opportunities/{oid}",
        json={"status": "validated", "priority": "high"},
    )
    assert r.status_code == 200
    assert r.json()["status"] == "validated"
    assert r.json()["priority"] == "high"


def test_delete_opportunity(client):
    login_as_user(client)
    pid = client.post(
        "/api/projects",
        json={"name": "P", "project_type_code": "value_discovery"},
    ).json()["id"]
    oid = client.post(
        f"/api/projects/{pid}/opportunities", json={"title": "T"}
    ).json()["id"]

    assert (
        client.delete(f"/api/projects/{pid}/opportunities/{oid}").status_code
        == 204
    )
    assert client.get(f"/api/projects/{pid}/opportunities").json() == []


def test_opportunities_cascade_when_project_deleted(client, db):
    login_as_user(client)
    pid = client.post(
        "/api/projects",
        json={"name": "P", "project_type_code": "value_discovery"},
    ).json()["id"]
    client.post(f"/api/projects/{pid}/opportunities", json={"title": "T"})

    db.expire_all()
    assert db.query(ValueDiscoveryOpportunity).count() == 1

    client.delete(f"/api/projects/{pid}")

    db.expire_all()
    assert db.query(ValueDiscoveryOpportunity).count() == 0


def test_cross_user_opportunity_blocked(client, db):
    login_as_user(client)
    pid = client.post(
        "/api/projects",
        json={"name": "Mine", "project_type_code": "value_discovery"},
    ).json()["id"]
    oid = client.post(
        f"/api/projects/{pid}/opportunities", json={"title": "Mine"}
    ).json()["id"]

    client.cookies.clear()
    login_as(client, db, "intruder")

    assert client.get(f"/api/projects/{pid}/opportunities").status_code == 404
    assert (
        client.patch(
            f"/api/projects/{pid}/opportunities/{oid}", json={"title": "Stolen"}
        ).status_code
        == 404
    )
    assert (
        client.delete(f"/api/projects/{pid}/opportunities/{oid}").status_code
        == 404
    )
