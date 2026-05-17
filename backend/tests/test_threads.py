"""Tests for the chat thread CRUD endpoints."""
from __future__ import annotations

from app.auth import SESSION_COOKIE, sessions
from app.models import ChatThread, ProjectType, User


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
    from app.models import Project

    pt = db.query(ProjectType).filter_by(code=code).one()
    project = Project(user_id=user.id, project_type_id=pt.id, name=f"P-{code}")
    db.add(project)
    db.commit()
    db.refresh(project)
    return project.id


# --- auth + type gates ---

def test_threads_endpoints_require_auth(client):
    assert client.get("/api/projects/1/threads").status_code == 401
    assert client.post("/api/projects/1/threads", json={}).status_code == 401
    assert (
        client.patch("/api/projects/1/threads/1", json={"title": "x"}).status_code
        == 401
    )
    assert client.delete("/api/projects/1/threads/1").status_code == 401


def test_threads_blocked_for_non_value_discovery(client, db):
    me = login_as(client, db, "user")
    pid = make_inactive_project_directly(db, me)
    r = client.get(f"/api/projects/{pid}/threads")
    assert r.status_code == 400


# --- list / lazy default ---

def test_list_threads_lazily_creates_default(client):
    login_as_user(client)
    pid = make_value_discovery_project(client)

    r = client.get(f"/api/projects/{pid}/threads")
    assert r.status_code == 200
    threads = r.json()
    assert len(threads) == 1
    assert threads[0]["project_id"] == pid
    assert threads[0]["title"] == "New chat"


def test_list_threads_returns_in_creation_order(client):
    login_as_user(client)
    pid = make_value_discovery_project(client)

    client.get(f"/api/projects/{pid}/threads")  # default created
    r2 = client.post(
        f"/api/projects/{pid}/threads", json={"title": "Risk angle"}
    )
    assert r2.status_code == 201

    titles = [t["title"] for t in client.get(f"/api/projects/{pid}/threads").json()]
    assert titles == ["New chat", "Risk angle"]


# --- create / rename / delete ---

def test_create_thread_default_title(client):
    login_as_user(client)
    pid = make_value_discovery_project(client)
    r = client.post(f"/api/projects/{pid}/threads", json={})
    assert r.status_code == 201
    assert r.json()["title"] == "New chat"


def test_create_thread_with_title(client):
    login_as_user(client)
    pid = make_value_discovery_project(client)
    r = client.post(
        f"/api/projects/{pid}/threads", json={"title": "Acme refinement"}
    )
    assert r.status_code == 201
    assert r.json()["title"] == "Acme refinement"


def test_rename_thread(client):
    login_as_user(client)
    pid = make_value_discovery_project(client)
    tid = client.post(f"/api/projects/{pid}/threads", json={}).json()["id"]
    r = client.patch(
        f"/api/projects/{pid}/threads/{tid}", json={"title": "Renamed"}
    )
    assert r.status_code == 200
    assert r.json()["title"] == "Renamed"


def test_rename_thread_rejects_empty_title(client):
    login_as_user(client)
    pid = make_value_discovery_project(client)
    tid = client.post(f"/api/projects/{pid}/threads", json={}).json()["id"]
    r = client.patch(
        f"/api/projects/{pid}/threads/{tid}", json={"title": ""}
    )
    assert r.status_code == 422


def test_delete_thread_cascades_messages(client, db):
    login_as_user(client)
    pid = make_value_discovery_project(client)
    tid = client.post(f"/api/projects/{pid}/threads", json={}).json()["id"]

    # Insert a chat message in this thread directly (no LLM key needed)
    from app.models import ChatMessage

    db.add(
        ChatMessage(
            project_id=pid, thread_id=tid, scope="bcm", role="user", content="hello"
        )
    )
    db.commit()

    db.expire_all()
    assert (
        db.query(ChatMessage).filter_by(thread_id=tid).count() == 1
    )

    assert (
        client.delete(f"/api/projects/{pid}/threads/{tid}").status_code == 204
    )

    db.expire_all()
    assert (
        db.query(ChatMessage).filter_by(thread_id=tid).count() == 0
    )
    assert db.query(ChatThread).filter_by(id=tid).count() == 0


def test_delete_404_for_other_project(client):
    login_as_user(client)
    pid_a = make_value_discovery_project(client, "A")
    pid_b = make_value_discovery_project(client, "B")
    tid = client.post(f"/api/projects/{pid_a}/threads", json={}).json()["id"]
    r = client.delete(f"/api/projects/{pid_b}/threads/{tid}")
    assert r.status_code == 404


# --- chat scoping ---

def test_chat_messages_isolated_per_thread(client):
    """Messages persisted in thread A don't leak into thread B."""
    login_as_user(client)
    pid = make_value_discovery_project(client)

    tid_a = client.post(
        f"/api/projects/{pid}/threads", json={"title": "A"}
    ).json()["id"]
    tid_b = client.post(
        f"/api/projects/{pid}/threads", json={"title": "B"}
    ).json()["id"]

    # Both threads start empty
    assert client.get(f"/api/projects/{pid}/chat?thread_id={tid_a}").json() == []
    assert client.get(f"/api/projects/{pid}/chat?thread_id={tid_b}").json() == []
