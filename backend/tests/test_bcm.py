from app.auth import SESSION_COOKIE, sessions
from app.models import BcmCapability, ProjectType, User


def login_as_user(client):
    r = client.post(
        "/api/auth/login",
        json={"username": "user", "password": "password"},
    )
    assert r.status_code == 200


def login_as(client, db, username: str):
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


def make_value_discovery_project(client, name: str = "VD"):
    r = client.post(
        "/api/projects",
        json={"name": name, "project_type_code": "value_discovery"},
    )
    assert r.status_code == 201
    return r.json()["id"]


def make_inactive_project_directly(db, user: User, code: str = "ai_assessment"):
    """Create a project of an inactive type, bypassing the API which would reject it."""
    from app.models import Project

    pt = db.query(ProjectType).filter_by(code=code).one()
    project = Project(user_id=user.id, project_type_id=pt.id, name=f"P-{code}")
    db.add(project)
    db.commit()
    db.refresh(project)
    return project.id


# --- Auth gate ---

def test_capability_endpoints_require_auth(client):
    assert client.get("/api/projects/1/capabilities").status_code == 401
    assert (
        client.post(
            "/api/projects/1/capabilities", json={"name": "x", "level": 1}
        ).status_code
        == 401
    )
    assert (
        client.patch(
            "/api/projects/1/capabilities/1", json={"name": "y"}
        ).status_code
        == 401
    )
    assert client.delete("/api/projects/1/capabilities/1").status_code == 401


def test_chat_endpoints_require_auth(client):
    assert client.get("/api/projects/1/chat").status_code == 401
    assert (
        client.post(
            "/api/projects/1/chat", json={"content": "hi"}
        ).status_code
        == 401
    )


# --- Project type gate ---

def test_capabilities_blocked_for_non_value_discovery_project(client, db):
    me = login_as(client, db, "user")
    pid = make_inactive_project_directly(db, me, code="ai_assessment")

    r = client.get(f"/api/projects/{pid}/capabilities")
    assert r.status_code == 400
    assert "Value Discovery" in r.json()["detail"]


def test_chat_blocked_for_non_value_discovery_project(client, db):
    me = login_as(client, db, "user")
    pid = make_inactive_project_directly(db, me, code="ai_assessment")

    r = client.post(f"/api/projects/{pid}/chat", json={"content": "hi"})
    assert r.status_code == 400


# --- Cross-user isolation ---

def test_cross_user_capabilities_return_404(client, db):
    login_as_user(client)
    pid = make_value_discovery_project(client)

    client.cookies.clear()
    login_as(client, db, "intruder")

    assert client.get(f"/api/projects/{pid}/capabilities").status_code == 404
    assert (
        client.post(
            f"/api/projects/{pid}/capabilities",
            json={"name": "x", "level": 1},
        ).status_code
        == 404
    )


# --- Capability happy path ---

def test_create_l1_l2_l3_chain(client):
    login_as_user(client)
    pid = make_value_discovery_project(client)

    r1 = client.post(
        f"/api/projects/{pid}/capabilities",
        json={"name": "Customer Management", "level": 1},
    )
    assert r1.status_code == 201
    l1 = r1.json()
    assert l1["level"] == 1
    assert l1["parent_id"] is None
    assert l1["position"] == 0

    r2 = client.post(
        f"/api/projects/{pid}/capabilities",
        json={"name": "Acquisition", "level": 2, "parent_id": l1["id"]},
    )
    assert r2.status_code == 201
    l2 = r2.json()
    assert l2["level"] == 2
    assert l2["parent_id"] == l1["id"]

    r3 = client.post(
        f"/api/projects/{pid}/capabilities",
        json={"name": "Lead capture", "level": 3, "parent_id": l2["id"]},
    )
    assert r3.status_code == 201
    l3 = r3.json()
    assert l3["level"] == 3
    assert l3["parent_id"] == l2["id"]


def test_position_auto_assigns_sequentially(client):
    login_as_user(client)
    pid = make_value_discovery_project(client)

    p0 = client.post(
        f"/api/projects/{pid}/capabilities",
        json={"name": "A", "level": 1},
    ).json()["position"]
    p1 = client.post(
        f"/api/projects/{pid}/capabilities",
        json={"name": "B", "level": 1},
    ).json()["position"]
    p2 = client.post(
        f"/api/projects/{pid}/capabilities",
        json={"name": "C", "level": 1},
    ).json()["position"]

    assert (p0, p1, p2) == (0, 1, 2)


def test_list_capabilities_returns_all_levels(client):
    login_as_user(client)
    pid = make_value_discovery_project(client)
    l1_id = client.post(
        f"/api/projects/{pid}/capabilities",
        json={"name": "L1", "level": 1},
    ).json()["id"]
    l2_id = client.post(
        f"/api/projects/{pid}/capabilities",
        json={"name": "L2", "level": 2, "parent_id": l1_id},
    ).json()["id"]
    client.post(
        f"/api/projects/{pid}/capabilities",
        json={"name": "L3", "level": 3, "parent_id": l2_id},
    )

    items = client.get(f"/api/projects/{pid}/capabilities").json()
    assert len(items) == 3
    assert sorted([c["level"] for c in items]) == [1, 2, 3]


# --- Hierarchy invariants ---

def test_l1_with_parent_rejected(client):
    login_as_user(client)
    pid = make_value_discovery_project(client)
    other = client.post(
        f"/api/projects/{pid}/capabilities", json={"name": "X", "level": 1}
    ).json()["id"]

    r = client.post(
        f"/api/projects/{pid}/capabilities",
        json={"name": "Y", "level": 1, "parent_id": other},
    )
    assert r.status_code == 400


def test_l2_without_parent_rejected(client):
    login_as_user(client)
    pid = make_value_discovery_project(client)
    r = client.post(
        f"/api/projects/{pid}/capabilities",
        json={"name": "X", "level": 2},
    )
    assert r.status_code == 400


def test_l3_with_l1_parent_rejected(client):
    login_as_user(client)
    pid = make_value_discovery_project(client)
    l1_id = client.post(
        f"/api/projects/{pid}/capabilities", json={"name": "L1", "level": 1}
    ).json()["id"]
    r = client.post(
        f"/api/projects/{pid}/capabilities",
        json={"name": "L3", "level": 3, "parent_id": l1_id},
    )
    assert r.status_code == 400


def test_invalid_level_rejected(client):
    login_as_user(client)
    pid = make_value_discovery_project(client)
    assert (
        client.post(
            f"/api/projects/{pid}/capabilities",
            json={"name": "X", "level": 0},
        ).status_code
        == 422
    )
    assert (
        client.post(
            f"/api/projects/{pid}/capabilities",
            json={"name": "X", "level": 4},
        ).status_code
        == 422
    )


def test_empty_name_rejected(client):
    login_as_user(client)
    pid = make_value_discovery_project(client)
    r = client.post(
        f"/api/projects/{pid}/capabilities",
        json={"name": "", "level": 1},
    )
    assert r.status_code == 422


def test_parent_from_different_project_rejected(client):
    login_as_user(client)
    pid_a = make_value_discovery_project(client, "A")
    pid_b = make_value_discovery_project(client, "B")
    a_l1 = client.post(
        f"/api/projects/{pid_a}/capabilities", json={"name": "L1", "level": 1}
    ).json()["id"]

    r = client.post(
        f"/api/projects/{pid_b}/capabilities",
        json={"name": "L2", "level": 2, "parent_id": a_l1},
    )
    assert r.status_code == 400


# --- Update / delete ---

def test_update_capability_name(client):
    login_as_user(client)
    pid = make_value_discovery_project(client)
    cap_id = client.post(
        f"/api/projects/{pid}/capabilities", json={"name": "Old", "level": 1}
    ).json()["id"]

    r = client.patch(
        f"/api/projects/{pid}/capabilities/{cap_id}",
        json={"name": "New", "description": "new desc"},
    )
    assert r.status_code == 200
    assert r.json()["name"] == "New"
    assert r.json()["description"] == "new desc"


def test_update_capability_to_invalid_parent_rejected(client):
    login_as_user(client)
    pid = make_value_discovery_project(client)
    l1a = client.post(
        f"/api/projects/{pid}/capabilities", json={"name": "L1A", "level": 1}
    ).json()["id"]
    l1b = client.post(
        f"/api/projects/{pid}/capabilities", json={"name": "L1B", "level": 1}
    ).json()["id"]
    l2 = client.post(
        f"/api/projects/{pid}/capabilities",
        json={"name": "L2", "level": 2, "parent_id": l1a},
    ).json()["id"]

    # moving an L2 under another L1 is allowed
    ok = client.patch(
        f"/api/projects/{pid}/capabilities/{l2}", json={"parent_id": l1b}
    )
    assert ok.status_code == 200

    # but moving an L2 under another L2 is not
    other_l2 = client.post(
        f"/api/projects/{pid}/capabilities",
        json={"name": "L2X", "level": 2, "parent_id": l1a},
    ).json()["id"]
    bad = client.patch(
        f"/api/projects/{pid}/capabilities/{l2}",
        json={"parent_id": other_l2},
    )
    assert bad.status_code == 400


def test_delete_capability_cascades(client, db):
    login_as_user(client)
    pid = make_value_discovery_project(client)
    l1 = client.post(
        f"/api/projects/{pid}/capabilities", json={"name": "L1", "level": 1}
    ).json()["id"]
    l2 = client.post(
        f"/api/projects/{pid}/capabilities",
        json={"name": "L2", "level": 2, "parent_id": l1},
    ).json()["id"]
    client.post(
        f"/api/projects/{pid}/capabilities",
        json={"name": "L3", "level": 3, "parent_id": l2},
    )

    db.expire_all()
    assert db.query(BcmCapability).count() == 3

    r = client.delete(f"/api/projects/{pid}/capabilities/{l1}")
    assert r.status_code == 204

    db.expire_all()
    assert db.query(BcmCapability).count() == 0


def test_delete_capability_404_for_other_project(client):
    login_as_user(client)
    pid_a = make_value_discovery_project(client, "A")
    pid_b = make_value_discovery_project(client, "B")
    cap_id = client.post(
        f"/api/projects/{pid_a}/capabilities", json={"name": "X", "level": 1}
    ).json()["id"]

    r = client.delete(f"/api/projects/{pid_b}/capabilities/{cap_id}")
    assert r.status_code == 404


# --- Chat endpoint (with LLM mocked or absent) ---


def test_chat_initially_empty(client):
    login_as_user(client)
    pid = make_value_discovery_project(client)
    assert client.get(f"/api/projects/{pid}/chat").json() == []


def test_chat_without_llm_key_returns_400(client):
    login_as_user(client)
    pid = make_value_discovery_project(client)
    r = client.post(f"/api/projects/{pid}/chat", json={"content": "Hi"})
    assert r.status_code == 400
    assert "LLM API key" in r.json()["detail"]


def test_empty_chat_message_rejected(client):
    login_as_user(client)
    pid = make_value_discovery_project(client)
    r = client.post(f"/api/projects/{pid}/chat", json={"content": ""})
    assert r.status_code == 422
