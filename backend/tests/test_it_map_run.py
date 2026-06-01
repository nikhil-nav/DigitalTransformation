"""IT Map Agent — Part 3 end-to-end tests.

Drives the run endpoint with a fake LLM provider that emits a scripted
sequence of tool_uses. Verifies:

- Run requires an LLM key (400 if none).
- Run returns immediately with status='running'; background task
  finishes before TestClient.post() returns, so a follow-up GET shows
  'done' with non-zero counts.
- Applications are materialised and mappings persist with the right
  status/confidence/rationale/engine_version.
- Re-running clears prior suggested mappings but preserves
  user-confirmed and user-dismissed ones.
- Tool-call cap fires loudly (status='failed', error mentions the cap).
- Max turns cap fires loudly when the agent never stops.
"""
from __future__ import annotations

import io
import json

import openpyxl

from app.auth import SESSION_COOKIE, sessions
from app.it_map import run as it_run
from app.llm.provider import ProviderResponse, ToolResult, ToolUse
from app.llm.session import LlmKeys, session_keys
from app.models import (
    Application,
    ApplicationCapabilityMapping,
    BcmCapability,
    ITMapAgentRun,
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
    session_id = f"test-session-{username}"
    sessions[session_id] = username
    client.cookies.set(SESSION_COOKIE, session_id)
    return user, session_id


def _set_keys(sid: str) -> None:
    session_keys[sid] = LlmKeys(
        provider="anthropic", llm_api_key="sk-ant-test12345"
    )


def make_vd_project(client) -> int:
    r = client.post(
        "/api/projects",
        json={"name": "VD", "project_type_code": "value_discovery"},
    )
    assert r.status_code == 201, r.text
    return r.json()["id"]


def make_inventory(client, pid: int) -> int:
    wb = openpyxl.Workbook()
    ws = wb.active
    assert ws is not None
    ws.title = "apps"
    ws.append(["app_name", "description", "domain"])
    ws.append(["Salesforce", "CRM", "Sales"])
    ws.append(["Workday", "HCM", "HR"])
    ws.append(["Stripe", "Payments", "Finance"])
    buf = io.BytesIO()
    wb.save(buf)
    r = client.post(
        f"/api/projects/{pid}/it-map/inventories",
        files={"upload": ("inv.xlsx", buf.getvalue(), XLSX_MIME)},
    )
    assert r.status_code == 201, r.text
    return r.json()["id"]


def make_bcm(db, project_id: int) -> dict[str, int]:
    """Seed a minimal BCM with L2 nodes the fake agent can target."""
    l1 = BcmCapability(
        project_id=project_id, parent_id=None, level=1, name="Customer", position=0
    )
    db.add(l1)
    db.flush()
    sales = BcmCapability(
        project_id=project_id, parent_id=l1.id, level=2, name="Sales", position=0
    )
    finance = BcmCapability(
        project_id=project_id, parent_id=None, level=2, name="Finance", position=1
    )
    hr = BcmCapability(
        project_id=project_id, parent_id=None, level=2, name="HR", position=2
    )
    db.add_all([sales, finance, hr])
    db.commit()
    return {"Sales": sales.id, "Finance": finance.id, "HR": hr.id}


# ---------------------------------------------------------------------------
# Fake provider
# ---------------------------------------------------------------------------


class _ScriptedProvider:
    """A test provider that emits a pre-built sequence of ProviderResponse
    objects on successive ``call()`` invocations. ``append_tool_results``
    is a no-op (we don't need round-trip fidelity in tests because the
    next response is already determined)."""

    name = "anthropic"
    default_model = "claude-test"

    def __init__(self, responses: list[ProviderResponse]) -> None:
        self._responses = responses
        self._calls = 0

    def translate_tools(self, tools):
        return tools

    def call(self, **_):
        if self._calls >= len(self._responses):
            # If the test under-scripts, fall back to a "done" response so
            # the loop terminates rather than hanging.
            return ProviderResponse(text="", tool_uses=[], assistant_message={})
        r = self._responses[self._calls]
        self._calls += 1
        return r

    def stream(self, **_):  # pragma: no cover - unused by IT Map
        raise NotImplementedError

    def append_tool_results(self, messages, response, results):
        return messages + [
            {"role": "assistant", "content": ""},
            {"role": "user", "content": json.dumps([r.content for r in results])},
        ]


def _tool_use(tool_name: str, args: dict) -> ToolUse:
    return ToolUse(id=f"toolu_{tool_name}", name=tool_name, input=args)


def _resp(*uses: ToolUse) -> ProviderResponse:
    return ProviderResponse(
        text="",
        tool_uses=list(uses),
        assistant_message={},
    )


def _scripted_happy_path(caps: dict[str, int]) -> list[ProviderResponse]:
    """A scripted 5-turn run:
    1. describe + sample
    2. list_capabilities
    3. propose_schema
    4. propose_mapping x3 (one per row, each to a different L2)
    5. done (no tools)
    """
    return [
        _resp(
            _tool_use("describe_inventory", {}),
            _tool_use("read_sample", {"n": 5}),
        ),
        _resp(_tool_use("list_capabilities", {"level": 2})),
        _resp(
            _tool_use(
                "propose_schema",
                {
                    "name_column": "app_name",
                    "description_column": "description",
                    "business_function_column": "domain",
                },
            )
        ),
        _resp(
            _tool_use(
                "propose_mapping",
                {
                    "row_index": 0,
                    "capability_id": caps["Sales"],
                    "confidence": 0.95,
                    "rationale": "Salesforce CRM -> Sales",
                },
            ),
            _tool_use(
                "propose_mapping",
                {
                    "row_index": 1,
                    "capability_id": caps["HR"],
                    "confidence": 0.92,
                    "rationale": "Workday HCM -> HR",
                },
            ),
            _tool_use(
                "propose_mapping",
                {
                    "row_index": 2,
                    "capability_id": caps["Finance"],
                    "confidence": 0.9,
                    "rationale": "Stripe payments -> Finance",
                },
            ),
        ),
        # Done.
        _resp(),
    ]


# ---------------------------------------------------------------------------
# Endpoint tests
# ---------------------------------------------------------------------------


def test_run_requires_llm_key(client, db) -> None:
    login_as(client, db, "user")
    pid = make_vd_project(client)
    iid = make_inventory(client, pid)
    make_bcm(db, pid)
    r = client.post(
        f"/api/projects/{pid}/it-map/inventories/{iid}/run"
    )
    assert r.status_code == 400
    assert "LLM" in r.json()["detail"]


def test_run_endpoint_executes_agent_and_persists_mappings(
    client, db, monkeypatch
) -> None:
    _user, sid = login_as(client, db, "user")
    _set_keys(sid)
    pid = make_vd_project(client)
    iid = make_inventory(client, pid)
    caps = make_bcm(db, pid)

    fake = _ScriptedProvider(_scripted_happy_path(caps))
    monkeypatch.setattr(it_run, "get_provider", lambda _keys: fake)

    r = client.post(
        f"/api/projects/{pid}/it-map/inventories/{iid}/run"
    )
    assert r.status_code == 200, r.text
    body = r.json()
    # The endpoint returns the in-flight 'running' state; the BG task
    # finishes before TestClient.post() returns under Starlette's
    # testing harness, so a follow-up GET reflects the final state.
    assert body["status"] == "running"
    assert body["engine_version"].startswith("it-map-agent/")

    runs = client.get(
        f"/api/projects/{pid}/it-map/inventories/{iid}/runs"
    ).json()
    assert len(runs) == 1
    final = runs[0]
    assert final["status"] == "done", final.get("error")
    assert final["application_count"] == 3
    assert final["mapping_count"] == 3
    assert final["unmappable_count"] == 0
    assert final["tool_call_count"] >= 6  # describe+sample+list+schema+3xmapping

    # Applications materialised with the inferred fields.
    apps = client.get(
        f"/api/projects/{pid}/it-map/inventories/{iid}/applications"
    ).json()
    assert {a["inferred_name"] for a in apps} == {"Salesforce", "Workday", "Stripe"}
    sales_app = next(a for a in apps if a["inferred_name"] == "Salesforce")
    assert len(sales_app["mappings"]) == 1
    m = sales_app["mappings"][0]
    assert m["capability_id"] == caps["Sales"]
    assert m["confidence"] == 0.95
    assert m["status"] == "suggested"
    assert m["engine_version"].startswith("it-map-agent/")


def test_rerun_preserves_user_confirmed_and_dismissed_mappings(
    client, db, monkeypatch
) -> None:
    """The orchestrator deletes prior `suggested` mappings before re-
    running; confirmed and dismissed mappings must survive intact."""
    _user, sid = login_as(client, db, "user")
    _set_keys(sid)
    pid = make_vd_project(client)
    iid = make_inventory(client, pid)
    caps = make_bcm(db, pid)

    fake = _ScriptedProvider(_scripted_happy_path(caps))
    monkeypatch.setattr(it_run, "get_provider", lambda _keys: fake)

    # First run.
    client.post(f"/api/projects/{pid}/it-map/inventories/{iid}/run")
    db.expire_all()

    # User confirms the Salesforce -> Sales mapping and dismisses
    # Workday -> HR. Stripe -> Finance is left as suggested.
    apps = (
        db.query(Application).filter_by(inventory_id=iid).order_by(Application.row_index).all()
    )
    sf_map = (
        db.query(ApplicationCapabilityMapping)
        .filter_by(application_id=apps[0].id)
        .one()
    )
    sf_map.status = "confirmed"
    sf_map.rationale = "user-blessed: SF is our CRM"
    wd_map = (
        db.query(ApplicationCapabilityMapping)
        .filter_by(application_id=apps[1].id)
        .one()
    )
    wd_map.status = "dismissed"
    db.commit()

    # Second run with the EXACT same scripted agent — would normally
    # re-propose all three mappings, but Salesforce/Sales must stay as
    # confirmed (untouched) and Workday/HR must stay dismissed
    # (untouched). Stripe/Finance gets re-suggested (was just suggested
    # before, so allowed to be replaced).
    fake2 = _ScriptedProvider(_scripted_happy_path(caps))
    monkeypatch.setattr(it_run, "get_provider", lambda _keys: fake2)
    client.post(f"/api/projects/{pid}/it-map/inventories/{iid}/run")
    db.expire_all()

    # Salesforce mapping should be UNCHANGED.
    refreshed_sf = (
        db.query(ApplicationCapabilityMapping)
        .filter_by(id=sf_map.id)
        .one()
    )
    assert refreshed_sf.status == "confirmed"
    assert refreshed_sf.rationale == "user-blessed: SF is our CRM"

    # Workday mapping should still exist and be dismissed.
    refreshed_wd = (
        db.query(ApplicationCapabilityMapping)
        .filter_by(id=wd_map.id)
        .one()
    )
    assert refreshed_wd.status == "dismissed"

    # Stripe should have its (only) suggested mapping replaced.
    stripe_app = (
        db.query(Application).filter_by(inventory_id=iid, row_index=2).one()
    )
    stripe_maps = (
        db.query(ApplicationCapabilityMapping)
        .filter_by(application_id=stripe_app.id)
        .all()
    )
    assert len(stripe_maps) == 1
    assert stripe_maps[0].status == "suggested"


def test_run_records_failure_when_agent_exceeds_tool_call_cap(
    client, db, monkeypatch
) -> None:
    _user, sid = login_as(client, db, "user")
    _set_keys(sid)
    pid = make_vd_project(client)
    iid = make_inventory(client, pid)
    make_bcm(db, pid)

    # Pinch the cap small so a single read_sample bursting can blow it.
    monkeypatch.setattr(it_run, "MAX_TOOL_CALLS_PER_RUN", 2)

    # 3 tool uses in one turn -> exceeds cap of 2.
    over_cap = [
        _resp(
            _tool_use("describe_inventory", {}),
            _tool_use("read_sample", {}),
            _tool_use("read_sample", {}),
        ),
        _resp(),
    ]
    fake = _ScriptedProvider(over_cap)
    monkeypatch.setattr(it_run, "get_provider", lambda _keys: fake)

    client.post(f"/api/projects/{pid}/it-map/inventories/{iid}/run")
    db.expire_all()
    run = (
        db.query(ITMapAgentRun).filter_by(inventory_id=iid).one()
    )
    assert run.status == "failed"
    assert "tool-call cap" in (run.error or "")


def test_run_records_failure_when_agent_never_stops(
    client, db, monkeypatch
) -> None:
    _user, sid = login_as(client, db, "user")
    _set_keys(sid)
    pid = make_vd_project(client)
    iid = make_inventory(client, pid)
    make_bcm(db, pid)

    # Shrink turn cap; provider always returns a one-tool turn, never
    # an empty turn -> hits the cap.
    monkeypatch.setattr(it_run, "MAX_TURNS_PER_RUN", 3)
    endless = [
        _resp(_tool_use("describe_inventory", {})),
        _resp(_tool_use("describe_inventory", {})),
        _resp(_tool_use("describe_inventory", {})),
        _resp(_tool_use("describe_inventory", {})),
    ]
    fake = _ScriptedProvider(endless)
    monkeypatch.setattr(it_run, "get_provider", lambda _keys: fake)

    client.post(f"/api/projects/{pid}/it-map/inventories/{iid}/run")
    db.expire_all()
    run = (
        db.query(ITMapAgentRun).filter_by(inventory_id=iid).one()
    )
    assert run.status == "failed"
    assert "did not finish" in (run.error or "")


def test_run_endpoints_require_value_discovery_project(client, db) -> None:
    """Re-runs the project-type gate test from Part 1 on the new run
    endpoints, so a future router refactor that drops the gate fails
    loudly."""
    user, _ = login_as(client, db, "alice")
    # Create a DQ project directly to skip the project-type API gate.
    from app.models import Project, ProjectType
    pt = (
        db.query(ProjectType).filter_by(code="data_quality_assessment").one()
    )
    p = Project(user_id=user.id, project_type_id=pt.id, name="DQ")
    db.add(p)
    db.commit()
    db.refresh(p)
    pid = p.id
    r = client.post(f"/api/projects/{pid}/it-map/inventories/999/run")
    assert r.status_code == 400
    assert "value_discovery" in r.json()["detail"]
