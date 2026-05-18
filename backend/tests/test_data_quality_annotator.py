"""Tests for the AI annotator (Part 5).

We never call a real provider here - the annotator's contract is "give me
a callable that returns text, I'll parse it." We replace
`_call_provider_text` directly so we can drive every code path
deterministically: happy path, JSON parse failure + retry recovery,
double failure (preserved-but-marked), schema-shaped-but-incomplete
response, and LLM call exceptions.
"""
from __future__ import annotations

import io
import json
from typing import Any

import openpyxl

from app.auth import SESSION_COOKIE, sessions
from app.data_quality import annotator
from app.llm.session import LlmKeys, session_keys
from app.models import (
    DataQualityDataset,
    DataQualityIssue,
    User,
)

XLSX_MIME = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


# ---- helpers ------------------------------------------------------------


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
    return user, session_id


def make_dq_project(client) -> int:
    r = client.post(
        "/api/projects",
        json={"name": "DQ", "project_type_code": "data_quality_assessment"},
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


def _issues_xlsx() -> bytes:
    """Workbook that's guaranteed to produce a few precision-grade issues."""
    return build_xlsx(
        {
            "s": [
                ["x"],
                [None],
                [None],
                [None],
                [1],
                [2],  # 60% null -> high completeness issue
            ]
        }
    )


def _upload(client, pid: int, payload: bytes, filename: str = "p.xlsx") -> dict:
    r = client.post(
        f"/api/projects/{pid}/dq/datasets",
        files={"upload": (filename, payload, XLSX_MIME)},
    )
    assert r.status_code == 201, r.text
    return r.json()


def _refetch(client, pid: int, dataset_id: int) -> dict:
    """Annotation now runs as a BackgroundTask: the upload response captures
    the in-flight state ('running'), and the task mutates the row after the
    response is sent. Starlette's TestClient executes the task before
    client.post returns, so a refetch right after observes the final state
    ('done' or 'failed')."""
    r = client.get(f"/api/projects/{pid}/dq/datasets/{dataset_id}")
    assert r.status_code == 200, r.text
    return r.json()


def _good_response(issue_ids: list[int]) -> str:
    return json.dumps(
        {
            "annotations": [
                {
                    "issue_id": i,
                    "narrative": f"narrative for {i}",
                    "suggested_fix": f"fix for {i}",
                }
                for i in issue_ids
            ]
        }
    )


# ---- pure-function paths via the helpers --------------------------------


def test_strip_codefences_handles_markdown_wrapper():
    raw = "```json\n{\"annotations\": []}\n```"
    assert annotator._strip_codefences(raw) == '{"annotations": []}'


def test_parse_response_accepts_well_formed_json():
    parsed = annotator._parse_response(_good_response([1, 2, 3]))
    assert parsed is not None
    assert [a.issue_id for a in parsed.annotations] == [1, 2, 3]


def test_parse_response_rejects_bad_json():
    assert annotator._parse_response("not json at all") is None
    assert annotator._parse_response("{\"annotations\": [{\"issue_id\": 1}]}") is None


# ---- end-to-end annotation through the HTTP layer -----------------------


def _set_keys(session_id: str) -> None:
    session_keys[session_id] = LlmKeys(
        provider="anthropic", llm_api_key="sk-ant-test12345"
    )


def test_upload_with_keys_runs_annotation_and_marks_issues_done(
    client, db, monkeypatch
):
    """Upload with a configured key should run the annotator and mark
    every emitted issue ai_status='done' carrying ai_narrative + ai_fix.
    """
    _user, sid = login_as(client, db, "user")
    _set_keys(sid)
    pid = make_dq_project(client)

    captured_inputs: list[str] = []

    def fake_call(keys: LlmKeys, system: str, user: str) -> str:
        captured_inputs.append(user)
        # Echo back annotations for whatever issue_ids appear in the prompt.
        # We can extract them by searching for the JSON list of issues.
        ids: list[int] = []
        # Parse the issue list out of the user message
        payload = json.loads(user.split("Input:\n\n", 1)[1])
        for it in payload["issues"]:
            ids.append(int(it["issue_id"]))
        return _good_response(ids)

    monkeypatch.setattr(annotator, "_call_provider_text", fake_call)

    ds = _upload(client, pid, _issues_xlsx())
    # Upload response captures the in-flight 'running' state.
    assert ds["annotation_status"] == "running"
    # Background task has executed by now; refetch to see the final state.
    ds = _refetch(client, pid, ds["id"])
    assert ds["annotation_status"] == "done"
    assert ds["annotated_at"] is not None

    issues = client.get(
        f"/api/projects/{pid}/dq/datasets/{ds['id']}/issues"
    ).json()
    assert len(issues) >= 1
    for i in issues:
        assert i["ai_status"] == "done"
        assert i["ai_narrative"] and i["ai_narrative"].startswith("narrative for ")
        assert i["ai_fix"] and i["ai_fix"].startswith("fix for ")


def test_invalid_then_valid_response_recovers_via_one_retry(
    client, db, monkeypatch
):
    _user, sid = login_as(client, db, "user")
    _set_keys(sid)
    pid = make_dq_project(client)

    calls: list[str] = []

    def fake_call(keys: LlmKeys, system: str, user: str) -> str:
        calls.append(system)
        if len(calls) == 1:
            return "not valid json at all"
        # second call (retry) returns valid annotations
        ids = [int(it["issue_id"]) for it in json.loads(user.split("Input:\n\n", 1)[1])["issues"]]
        return _good_response(ids)

    monkeypatch.setattr(annotator, "_call_provider_text", fake_call)

    ds = _upload(client, pid, _issues_xlsx())
    ds = _refetch(client, pid, ds["id"])
    assert ds["annotation_status"] == "done"
    # The two calls used different system prompts
    assert calls[0] != calls[1]


def test_double_invalid_response_marks_issues_failed_with_raw_preserved(
    client, db, monkeypatch
):
    _user, sid = login_as(client, db, "user")
    _set_keys(sid)
    pid = make_dq_project(client)

    def fake_call(keys: LlmKeys, system: str, user: str) -> str:
        return "still not json"

    monkeypatch.setattr(annotator, "_call_provider_text", fake_call)

    ds = _upload(client, pid, _issues_xlsx())
    # Upload itself succeeded; the background task ran and recorded
    # the schema-validation failure on the dataset row.
    ds = _refetch(client, pid, ds["id"])
    assert ds["annotation_status"] == "failed"
    assert "schema validation" in (ds["annotation_error"] or "").lower()

    # Per-issue ai_status='failed' and raw response preserved
    db.expire_all()
    rows = (
        db.query(DataQualityIssue)
        .filter_by(dataset_id=ds["id"])
        .all()
    )
    assert rows
    for r in rows:
        assert r.ai_status == "failed"
        assert r.ai_raw == "still not json"
        assert r.ai_narrative is None


def test_partial_response_marks_missing_issues_failed_keeps_others_done(
    client, db, monkeypatch
):
    """If the LLM returns annotations for some issue_ids but skips others,
    the skipped ones must be marked failed (with the raw response) - never
    silently treated as done."""
    _user, sid = login_as(client, db, "user")
    _set_keys(sid)
    pid = make_dq_project(client)

    # Build a workbook with multiple issues so we have several ids to slice.
    payload = build_xlsx(
        {
            "s": [
                ["x", "y"],
                [None, 1],
                [None, 1],
                [None, 1],
                [1, 2],  # x: 75% null (medium), y: constant (low uniqueness)
                [2, 1],
            ]
        }
    )

    def fake_call(keys: LlmKeys, system: str, user: str) -> str:
        ids = [int(it["issue_id"]) for it in json.loads(user.split("Input:\n\n", 1)[1])["issues"]]
        # Only annotate the first issue id
        return _good_response(ids[:1])

    monkeypatch.setattr(annotator, "_call_provider_text", fake_call)

    ds = _upload(client, pid, payload)
    db.expire_all()
    rows = (
        db.query(DataQualityIssue)
        .filter_by(dataset_id=ds["id"])
        .order_by(DataQualityIssue.id.asc())
        .all()
    )
    assert rows
    done = [r for r in rows if r.ai_status == "done"]
    failed = [r for r in rows if r.ai_status == "failed"]
    assert len(done) == 1
    assert len(failed) == len(rows) - 1
    # The failed ones keep the raw payload so a human can audit
    for r in failed:
        assert r.ai_raw is not None


def test_provider_exception_marks_dataset_failed_no_upload_break(
    client, db, monkeypatch
):
    """If the LLM call itself throws (network, rate limit), upload still
    succeeds and the dataset shows annotation_status='failed' with the
    error message preserved (truncated to 500 chars)."""
    _user, sid = login_as(client, db, "user")
    _set_keys(sid)
    pid = make_dq_project(client)

    def fake_call(keys: LlmKeys, system: str, user: str) -> str:
        raise RuntimeError("boom from provider")

    monkeypatch.setattr(annotator, "_call_provider_text", fake_call)

    ds = _upload(client, pid, _issues_xlsx())
    ds = _refetch(client, pid, ds["id"])
    assert ds["annotation_status"] == "failed"
    assert "boom from provider" in (ds["annotation_error"] or "")


def test_upload_without_keys_leaves_annotation_pending(client, db):
    """No LLM key configured: upload + profile must still succeed; the
    dataset's annotation_status stays 'pending' so the user knows there's
    something to retry."""
    login_as_user(client)
    pid = make_dq_project(client)
    ds = _upload(client, pid, _issues_xlsx())
    assert ds["annotation_status"] == "pending"
    assert ds["annotated_at"] is None


def test_manual_annotate_endpoint_requires_llm_key(client, db):
    login_as_user(client)
    pid = make_dq_project(client)
    ds = _upload(client, pid, _issues_xlsx())  # no key, stays pending

    r = client.post(f"/api/projects/{pid}/dq/datasets/{ds['id']}/annotate")
    assert r.status_code == 400
    assert "LLM API key" in r.json()["detail"]


def test_manual_annotate_endpoint_runs_annotator(client, db, monkeypatch):
    _user, sid = login_as(client, db, "user")
    pid = make_dq_project(client)
    # Upload without keys first - annotation stays pending
    ds = _upload(client, pid, _issues_xlsx())
    assert ds["annotation_status"] == "pending"

    # Configure keys, then call the manual annotator endpoint
    _set_keys(sid)

    def fake_call(keys: LlmKeys, system: str, user: str) -> str:
        ids = [int(it["issue_id"]) for it in json.loads(user.split("Input:\n\n", 1)[1])["issues"]]
        return _good_response(ids)

    monkeypatch.setattr(annotator, "_call_provider_text", fake_call)

    r = client.post(f"/api/projects/{pid}/dq/datasets/{ds['id']}/annotate")
    assert r.status_code == 200, r.text
    # The annotator now runs as a FastAPI BackgroundTask: the response
    # captures the in-flight state ("running"), then the task runs after
    # the response is sent. Starlette's TestClient executes background
    # tasks before client.post() returns, so refetching here observes the
    # post-task state ("done").
    assert r.json()["annotation_status"] == "running"
    refreshed = client.get(
        f"/api/projects/{pid}/dq/datasets/{ds['id']}"
    ).json()
    assert refreshed["annotation_status"] == "done"


def test_upload_does_not_block_on_slow_llm(client, db, monkeypatch):
    """Regression: a slow LLM provider must NOT keep the upload request open.
    Annotation runs as a FastAPI BackgroundTask; the upload returns
    'running' immediately. For a real wide workbook with many issues this
    is what prevents browser/proxy timeouts from killing the upload."""
    import time

    _user, sid = login_as(client, db, "user")
    _set_keys(sid)
    pid = make_dq_project(client)

    call_count = {"n": 0}

    def slow_fake_call(keys: LlmKeys, system: str, user: str) -> str:
        call_count["n"] += 1
        time.sleep(0.4)  # exaggerated "slow LLM" to amplify any sync wait
        ids = [int(it["issue_id"]) for it in json.loads(user.split("Input:\n\n", 1)[1])["issues"]]
        return _good_response(ids)

    monkeypatch.setattr(annotator, "_call_provider_text", slow_fake_call)

    # Time the upload itself. Under the OLD sync flow this would have
    # included every LLM call's sleep. Under the new flow only the
    # profile + initial response are on the request thread.
    started = time.monotonic()
    ds = _upload(client, pid, _issues_xlsx())
    upload_elapsed = time.monotonic() - started

    # Background task runs synchronously in the TestClient AFTER the
    # response is sent; so when client.post returns, the task has run.
    # We assert the *response body* shows 'running' (proving the
    # endpoint did not wait on the LLM) and that the task DID eventually
    # complete (refetch shows 'done').
    assert ds["annotation_status"] == "running"
    refreshed = _refetch(client, pid, ds["id"])
    assert refreshed["annotation_status"] == "done"

    # The LLM was called at least once.
    assert call_count["n"] >= 1
    # Hard upper bound on response-cycle (incl. ALL LLM calls under
    # TestClient): if regression re-introduces sync waits, this fires.
    # Per-LLM-call sleep is 0.4s; with N batches we'd see ~0.4*N elapsed.
    # Real upload + profile is well under 2s for the fixture.
    assert upload_elapsed < 5.0, (
        f"upload took {upload_elapsed:.2f}s (LLM was called {call_count['n']}x). "
        f"If this regresses past 5s, sync annotation has likely been re-introduced."
    )


def test_re_profile_resets_annotation_status_to_pending(client, db, monkeypatch):
    """Re-profiling wipes prior issues, so previous AI annotations no longer
    apply. The dataset's annotation_status should reflect that the new
    issues haven't been annotated yet (until something runs the annotator
    again)."""
    _user, sid = login_as(client, db, "user")
    _set_keys(sid)
    pid = make_dq_project(client)

    def fake_call(keys: LlmKeys, system: str, user: str) -> str:
        ids = [int(it["issue_id"]) for it in json.loads(user.split("Input:\n\n", 1)[1])["issues"]]
        return _good_response(ids)

    monkeypatch.setattr(annotator, "_call_provider_text", fake_call)

    ds = _upload(client, pid, _issues_xlsx())
    ds = _refetch(client, pid, ds["id"])
    assert ds["annotation_status"] == "done"

    # Manual re-profile does NOT run annotation; it just regenerates stats.
    r = client.post(f"/api/projects/{pid}/dq/datasets/{ds['id']}/profile")
    assert r.status_code == 200

    db.expire_all()
    row = db.query(DataQualityDataset).filter_by(id=ds["id"]).one()
    # Issues were replaced; the annotator hasn't run since, so the per-issue
    # ai_status defaults are 'pending'.
    issues = (
        db.query(DataQualityIssue).filter_by(dataset_id=row.id).all()
    )
    for i in issues:
        assert i.ai_status == "pending"
