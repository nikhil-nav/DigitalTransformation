import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app import auth
from app.db import get_db, init_db
from app.llm.session import session_keys as llm_session_keys
from app.main import app


@pytest.fixture
def engine():
    eng = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
        future=True,
    )
    init_db(eng)
    yield eng
    eng.dispose()


@pytest.fixture
def db(engine):
    SessionLocal = sessionmaker(bind=engine)
    s = SessionLocal()
    try:
        yield s
    finally:
        s.close()


@pytest.fixture(autouse=True)
def _wire_app(engine, tmp_path, monkeypatch):
    """Per-test setup: route the app's get_db at the in-memory engine and clear sessions.

    Also points DT_DATA_DIR at a tmp dir as a safety net so any accidental access
    to the real engine doesn't pollute the developer's filesystem.
    """
    monkeypatch.setenv("DT_DATA_DIR", str(tmp_path))
    auth.sessions.clear()
    llm_session_keys.clear()

    SessionLocal = sessionmaker(bind=engine)

    def _get_db():
        s = SessionLocal()
        try:
            yield s
        finally:
            s.close()

    app.dependency_overrides[get_db] = _get_db
    yield
    app.dependency_overrides.clear()
    auth.sessions.clear()
    llm_session_keys.clear()


@pytest.fixture
def client():
    return TestClient(app)
