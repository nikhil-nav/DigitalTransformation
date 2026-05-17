from app.auth import SESSION_COOKIE


def test_login_success_sets_cookie(client):
    r = client.post(
        "/api/auth/login",
        json={"username": "user", "password": "password"},
    )
    assert r.status_code == 200
    assert r.json() == {"username": "user"}
    assert SESSION_COOKIE in r.cookies


def test_login_wrong_password_returns_401_no_cookie(client):
    r = client.post(
        "/api/auth/login",
        json={"username": "user", "password": "wrong"},
    )
    assert r.status_code == 401
    assert SESSION_COOKIE not in r.cookies


def test_login_wrong_username_returns_401(client):
    r = client.post(
        "/api/auth/login",
        json={"username": "stranger", "password": "password"},
    )
    assert r.status_code == 401


def test_me_without_cookie_returns_401(client):
    r = client.get("/api/auth/me")
    assert r.status_code == 401


def test_me_with_valid_session_returns_user(client):
    client.post(
        "/api/auth/login",
        json={"username": "user", "password": "password"},
    )
    r = client.get("/api/auth/me")
    assert r.status_code == 200
    assert r.json() == {"username": "user"}


def test_me_with_unknown_cookie_returns_401(client):
    client.cookies.set(SESSION_COOKIE, "not-a-real-session")
    r = client.get("/api/auth/me")
    assert r.status_code == 401


def test_logout_clears_session(client):
    client.post(
        "/api/auth/login",
        json={"username": "user", "password": "password"},
    )
    r = client.post("/api/auth/logout")
    assert r.status_code == 200
    follow_up = client.get("/api/auth/me")
    assert follow_up.status_code == 401


def test_logout_without_session_is_ok(client):
    r = client.post("/api/auth/logout")
    assert r.status_code == 200


def test_login_issues_fresh_session_each_time(client):
    r1 = client.post(
        "/api/auth/login",
        json={"username": "user", "password": "password"},
    )
    first = r1.cookies.get(SESSION_COOKIE)
    client.cookies.clear()
    r2 = client.post(
        "/api/auth/login",
        json={"username": "user", "password": "password"},
    )
    second = r2.cookies.get(SESSION_COOKIE)
    assert first and second and first != second
