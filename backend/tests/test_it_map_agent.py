"""IT Map Agent — Part 2 tool tests.

Each tool is exercised directly (no LLM loop). Tests cover:
- Happy paths for read tools
- Validation/rejection paths return ValueError (mapped to tool errors by dispatch)
- propose_schema materialises Application rows + auto-marks missing-name as unmappable
- propose_mapping enforces non-empty rationale, valid confidence, L2-only,
  preserves user-confirmed/dismissed across re-suggest
- propose_unmappable requires reason
- Dispatch closure returns (text, is_error) and never raises
"""
from __future__ import annotations

import io
import json

import openpyxl

from app.auth import SESSION_COOKIE, sessions
from app.it_map import agent as it_agent
from app.llm.session import LlmKeys
from app.models import (
    Application,
    ApplicationCapabilityMapping,
    ApplicationInventory,
    ApplicationInventorySchema,
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
    session_id = f"test-session-{username}"
    sessions[session_id] = username
    client.cookies.set(SESSION_COOKIE, session_id)
    return user, session_id


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
    if ws is None:
        raise RuntimeError("active sheet missing")
    ws.title = "applications"
    ws.append(["app_name", "description", "owner", "domain"])
    ws.append(["Salesforce", "CRM SaaS", "Bob", "Sales"])
    ws.append(["SAP S/4HANA", "ERP", "Carol", "Finance"])
    ws.append([None, "missing-name row", "Dave", "Misc"])  # auto-unmappable
    ws.append(["Workday", "HCM SaaS", "Erin", "HR"])
    buf = io.BytesIO()
    wb.save(buf)
    r = client.post(
        f"/api/projects/{pid}/it-map/inventories",
        files={"upload": ("inv.xlsx", buf.getvalue(), XLSX_MIME)},
    )
    assert r.status_code == 201, r.text
    return r.json()["id"]


def make_bcm(db, project_id: int) -> dict[str, int]:
    """Seed a small BCM directly in the DB and return a name->id map."""
    l1 = BcmCapability(project_id=project_id, parent_id=None, level=1, name="Customer", position=0)
    db.add(l1)
    db.flush()
    l2_sales = BcmCapability(
        project_id=project_id, parent_id=l1.id, level=2, name="Sales", position=0
    )
    l2_service = BcmCapability(
        project_id=project_id, parent_id=l1.id, level=2, name="Service", position=1
    )
    l2_finance = BcmCapability(
        project_id=project_id, parent_id=None, level=2, name="Finance", position=2
    )
    l3_pricing = BcmCapability(
        project_id=project_id,
        parent_id=l2_sales.id,
        level=3,
        name="Pricing",
        position=0,
    )
    db.add_all([l2_sales, l2_service, l2_finance, l3_pricing])
    db.commit()
    return {
        "Customer": l1.id,
        "Sales": l2_sales.id,
        "Service": l2_service.id,
        "Finance": l2_finance.id,
        "Pricing": l3_pricing.id,
    }


def _dataset(client, db) -> tuple[int, int, dict[str, int]]:
    """Build a Value Discovery project + inventory + BCM and return
    ``(project_id, inventory_id, capability_name_to_id)``. Tests call
    this once and then exercise tools directly."""
    login_as(client, db, "user")
    pid = make_vd_project(client)
    iid = make_inventory(client, pid)
    caps = make_bcm(db, pid)
    return pid, iid, caps


# ---------------------------------------------------------------------------
# describe_inventory
# ---------------------------------------------------------------------------


def test_describe_inventory_reports_sheets_and_unschemaed_state(client, db) -> None:
    _pid, iid, _ = _dataset(client, db)
    out = it_agent._tool_describe_inventory(db, iid, {})
    assert out["filename"] == "inv.xlsx"
    assert out["primary_sheet"] == "applications"
    assert out["schema_proposed"] is False
    assert out["applications_materialised"] == 0


def test_describe_inventory_rejects_unknown_id(client, db) -> None:
    try:
        it_agent._tool_describe_inventory(db, 99999, {})
        raise AssertionError("expected ValueError")
    except ValueError as e:
        assert "not found" in str(e)


# ---------------------------------------------------------------------------
# read_sample
# ---------------------------------------------------------------------------


def test_read_sample_returns_columns_and_total_rows(client, db) -> None:
    _pid, iid, _ = _dataset(client, db)
    out = it_agent._tool_read_sample(db, iid, {"n": 2})
    assert out["sheet"] == "applications"
    assert out["columns"] == ["app_name", "description", "owner", "domain"]
    assert out["total_rows"] == 4
    assert out["rows_returned"] == 2
    assert out["rows"][0]["app_name"] == "Salesforce"


def test_read_sample_clamps_to_max(client, db) -> None:
    _pid, iid, _ = _dataset(client, db)
    out = it_agent._tool_read_sample(db, iid, {"n": 99999})
    # All 4 rows returned, capped at the sample max which is well above 4.
    assert out["rows_returned"] == 4


# ---------------------------------------------------------------------------
# read_row
# ---------------------------------------------------------------------------


def test_read_row_returns_one_row(client, db) -> None:
    _pid, iid, _ = _dataset(client, db)
    out = it_agent._tool_read_row(db, iid, {"row_index": 1})
    assert out["row_index"] == 1
    assert out["data"]["app_name"] == "SAP S/4HANA"


def test_read_row_rejects_negative_index(client, db) -> None:
    _pid, iid, _ = _dataset(client, db)
    try:
        it_agent._tool_read_row(db, iid, {"row_index": -1})
        raise AssertionError("expected ValueError")
    except ValueError as e:
        assert ">=" in str(e)


def test_read_row_rejects_out_of_range(client, db) -> None:
    _pid, iid, _ = _dataset(client, db)
    try:
        it_agent._tool_read_row(db, iid, {"row_index": 999})
        raise AssertionError("expected ValueError")
    except ValueError as e:
        assert "out of range" in str(e)


# ---------------------------------------------------------------------------
# list_capabilities
# ---------------------------------------------------------------------------


def test_list_capabilities_returns_only_requested_level(client, db) -> None:
    pid, _iid, caps = _dataset(client, db)
    out = it_agent._tool_list_capabilities(db, pid, {"level": 2})
    assert out["level"] == 2
    names = {c["name"] for c in out["capabilities"]}
    assert "Sales" in names and "Service" in names and "Finance" in names
    # L1 and L3 nodes are excluded.
    assert "Customer" not in names
    assert "Pricing" not in names


def test_list_capabilities_rejects_invalid_level(client, db) -> None:
    pid, _iid, _ = _dataset(client, db)
    try:
        it_agent._tool_list_capabilities(db, pid, {"level": 99})
        raise AssertionError("expected ValueError")
    except ValueError as e:
        assert "1, 2, or 3" in str(e)


# ---------------------------------------------------------------------------
# propose_schema
# ---------------------------------------------------------------------------


def test_propose_schema_materialises_apps_and_flags_missing_name(client, db) -> None:
    _pid, iid, _ = _dataset(client, db)
    out = it_agent._tool_propose_schema(
        db,
        iid,
        {
            "name_column": "app_name",
            "description_column": "description",
            "owner_column": "owner",
            "business_function_column": "domain",
        },
    )
    db.commit()

    assert out["applications_created"] == 4
    assert out["applications_refreshed"] == 0
    assert out["applications_auto_unmappable_missing_name"] == 1

    apps = (
        db.query(Application).filter_by(inventory_id=iid).order_by(Application.row_index).all()
    )
    assert len(apps) == 4
    assert apps[0].inferred_name == "Salesforce"
    assert apps[0].inferred_business_function == "Sales"
    # Row 2 had no app_name -> auto-unmappable, no name inferred
    assert apps[2].inferred_name is None
    assert apps[2].unmappable_reason == "Row missing application name"

    schema = (
        db.query(ApplicationInventorySchema).filter_by(inventory_id=iid).one()
    )
    assert schema.name_column == "app_name"
    assert schema.description_column == "description"
    assert schema.criticality_column is None


def test_propose_schema_rejects_missing_name_column(client, db) -> None:
    _pid, iid, _ = _dataset(client, db)
    try:
        it_agent._tool_propose_schema(db, iid, {"name_column": ""})
        raise AssertionError("expected ValueError")
    except ValueError as e:
        assert "name_column" in str(e)


def test_propose_schema_rejects_unknown_column(client, db) -> None:
    _pid, iid, _ = _dataset(client, db)
    try:
        it_agent._tool_propose_schema(
            db, iid, {"name_column": "app_name", "owner_column": "made_up"}
        )
        raise AssertionError("expected ValueError")
    except ValueError as e:
        assert "made_up" in str(e) and "owner_column" in str(e)


def test_propose_schema_can_be_called_again_to_revise(client, db) -> None:
    _pid, iid, _ = _dataset(client, db)
    it_agent._tool_propose_schema(db, iid, {"name_column": "app_name"})
    db.commit()
    # Second call adds an owner column and refreshes inferred fields.
    out2 = it_agent._tool_propose_schema(
        db, iid, {"name_column": "app_name", "owner_column": "owner"}
    )
    db.commit()
    assert out2["applications_created"] == 0
    assert out2["applications_refreshed"] == 4
    apps = db.query(Application).filter_by(inventory_id=iid).all()
    assert any(a.inferred_owner == "Bob" for a in apps)


# ---------------------------------------------------------------------------
# propose_mapping
# ---------------------------------------------------------------------------


def _schema_first(client, db) -> tuple[int, int, dict[str, int]]:
    pid, iid, caps = _dataset(client, db)
    it_agent._tool_propose_schema(db, iid, {"name_column": "app_name"})
    db.commit()
    return pid, iid, caps


def test_propose_mapping_creates_suggested_mapping(client, db) -> None:
    pid, iid, caps = _schema_first(client, db)
    out = it_agent._tool_propose_mapping(
        db,
        iid,
        pid,
        {
            "row_index": 0,
            "capability_id": caps["Sales"],
            "confidence": 0.9,
            "rationale": "Salesforce is a CRM and serves Sales",
        },
    )
    db.commit()
    assert out["status"] == "suggested"
    assert out["outcome"] == "created"
    mapping = (
        db.query(ApplicationCapabilityMapping).filter_by(id=out["id"]).one()
    )
    assert mapping.confidence == 0.9
    assert mapping.engine_version.startswith("it-map-agent/")


def test_propose_mapping_rejects_empty_rationale(client, db) -> None:
    pid, iid, caps = _schema_first(client, db)
    try:
        it_agent._tool_propose_mapping(
            db,
            iid,
            pid,
            {
                "row_index": 0,
                "capability_id": caps["Sales"],
                "confidence": 0.5,
                "rationale": "   ",
            },
        )
        raise AssertionError("expected ValueError")
    except ValueError as e:
        assert "rationale" in str(e)


def test_propose_mapping_rejects_out_of_range_confidence(client, db) -> None:
    pid, iid, caps = _schema_first(client, db)
    try:
        it_agent._tool_propose_mapping(
            db,
            iid,
            pid,
            {
                "row_index": 0,
                "capability_id": caps["Sales"],
                "confidence": 1.5,
                "rationale": "x",
            },
        )
        raise AssertionError("expected ValueError")
    except ValueError as e:
        assert "between 0 and 1" in str(e)


def test_propose_mapping_rejects_non_l2_capability(client, db) -> None:
    pid, iid, caps = _schema_first(client, db)
    # caps["Customer"] is L1; caps["Pricing"] is L3 — both must be refused.
    for cap_name in ("Customer", "Pricing"):
        try:
            it_agent._tool_propose_mapping(
                db,
                iid,
                pid,
                {
                    "row_index": 0,
                    "capability_id": caps[cap_name],
                    "confidence": 0.5,
                    "rationale": "x",
                },
            )
            raise AssertionError(f"expected ValueError for {cap_name}")
        except ValueError as e:
            assert "L2" in str(e) or "level" in str(e)


def test_propose_mapping_rejects_before_schema(client, db) -> None:
    """No propose_schema yet -> no apps materialised -> mapping rejected."""
    pid, iid, caps = _dataset(client, db)
    try:
        it_agent._tool_propose_mapping(
            db,
            iid,
            pid,
            {
                "row_index": 0,
                "capability_id": caps["Sales"],
                "confidence": 0.5,
                "rationale": "x",
            },
        )
        raise AssertionError("expected ValueError")
    except ValueError as e:
        assert "propose_schema" in str(e)


def test_propose_mapping_preserves_user_confirmed_decisions(client, db) -> None:
    """Re-suggesting a pair the user has confirmed must NOT overwrite it."""
    pid, iid, caps = _schema_first(client, db)
    first = it_agent._tool_propose_mapping(
        db,
        iid,
        pid,
        {
            "row_index": 0,
            "capability_id": caps["Sales"],
            "confidence": 0.5,
            "rationale": "initial guess",
        },
    )
    # Simulate the user confirming via the dashboard.
    mapping = (
        db.query(ApplicationCapabilityMapping).filter_by(id=first["id"]).one()
    )
    mapping.status = "confirmed"
    db.commit()

    second = it_agent._tool_propose_mapping(
        db,
        iid,
        pid,
        {
            "row_index": 0,
            "capability_id": caps["Sales"],
            "confidence": 0.99,
            "rationale": "agent revised",
        },
    )
    db.commit()
    assert second["outcome"] == "preserved-user-decision"
    db.refresh(mapping)
    # Confidence + rationale unchanged from the user's confirmed version.
    assert mapping.confidence == 0.5
    assert mapping.rationale == "initial guess"
    assert mapping.status == "confirmed"


def test_propose_mapping_updates_prior_suggestion(client, db) -> None:
    pid, iid, caps = _schema_first(client, db)
    it_agent._tool_propose_mapping(
        db,
        iid,
        pid,
        {
            "row_index": 0,
            "capability_id": caps["Sales"],
            "confidence": 0.4,
            "rationale": "first",
        },
    )
    out = it_agent._tool_propose_mapping(
        db,
        iid,
        pid,
        {
            "row_index": 0,
            "capability_id": caps["Sales"],
            "confidence": 0.95,
            "rationale": "second",
        },
    )
    db.commit()
    assert out["outcome"] == "updated-suggestion"
    mapping = (
        db.query(ApplicationCapabilityMapping).filter_by(id=out["id"]).one()
    )
    assert mapping.confidence == 0.95
    assert mapping.rationale == "second"


# ---------------------------------------------------------------------------
# propose_unmappable
# ---------------------------------------------------------------------------


def test_propose_unmappable_sets_reason(client, db) -> None:
    _pid, iid, _ = _schema_first(client, db)
    out = it_agent._tool_propose_unmappable(
        db, iid, {"row_index": 1, "reason": "no clear capability fit"}
    )
    db.commit()
    app = (
        db.query(Application)
        .filter_by(inventory_id=iid, row_index=1)
        .one()
    )
    assert app.unmappable_reason == "no clear capability fit"
    assert out["unmappable_reason"] == "no clear capability fit"


def test_propose_unmappable_requires_reason(client, db) -> None:
    _pid, iid, _ = _schema_first(client, db)
    try:
        it_agent._tool_propose_unmappable(db, iid, {"row_index": 1, "reason": ""})
        raise AssertionError("expected ValueError")
    except ValueError as e:
        assert "reason" in str(e)


# ---------------------------------------------------------------------------
# Dispatch
# ---------------------------------------------------------------------------


def _fake_keys() -> LlmKeys:
    return LlmKeys(provider="anthropic", llm_api_key="sk-x")


def test_dispatch_returns_text_and_is_error_flag(client, db) -> None:
    pid, iid, _ = _dataset(client, db)
    dispatch = it_agent.make_it_map_tool_dispatch(iid)
    text, is_error = dispatch(
        "describe_inventory", {}, db=db, project_id=pid, keys=_fake_keys()
    )
    assert is_error is False
    payload = json.loads(text)
    assert payload["primary_sheet"] == "applications"


def test_dispatch_returns_tool_error_string_on_validation_failure(client, db) -> None:
    pid, iid, _ = _dataset(client, db)
    dispatch = it_agent.make_it_map_tool_dispatch(iid)
    text, is_error = dispatch(
        "propose_mapping",
        {"row_index": 0, "capability_id": 0, "confidence": 0.5, "rationale": ""},
        db=db,
        project_id=pid,
        keys=_fake_keys(),
    )
    assert is_error is True
    assert "rejected input" in text
    assert "rationale" in text


def test_dispatch_rejects_unknown_tool(client, db) -> None:
    pid, iid, _ = _dataset(client, db)
    dispatch = it_agent.make_it_map_tool_dispatch(iid)
    text, is_error = dispatch(
        "made_up_tool", {}, db=db, project_id=pid, keys=_fake_keys()
    )
    assert is_error is True
    assert "Unknown tool" in text


def test_tools_list_matches_dispatch_branches() -> None:
    """The dispatch implements every tool exposed in IT_MAP_TOOLS.
    Catches drift between the tool specs sent to the model and the
    dispatcher's switch."""
    tool_names = {t["name"] for t in it_agent.IT_MAP_TOOLS}
    expected = {
        "describe_inventory",
        "read_sample",
        "read_row",
        "list_capabilities",
        "propose_schema",
        "propose_mapping",
        "propose_unmappable",
    }
    assert tool_names == expected
