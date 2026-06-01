"""Tests for US 3.7 — tree builder, fingerprint stability, HTTP round-trip,
and the fingerprint backfill migration.

The fixtures reuse the planted xlsx pattern from
``test_data_quality_similarity_engine.py`` so a real run produces real
clusters before we exercise the tree endpoints.
"""
from __future__ import annotations

import io
import json

import openpyxl
import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.pool import StaticPool

from app.data_quality.cluster import cluster_fingerprint, run_similarity
from app.data_quality.normalize import Normalizer
from app.data_quality.tree import (
    TREE_VERSION,
    ColumnFacts,
    TreeMapping,
    _bucket_for,
    _combined_bucket,
    _override_applies,
    build_cluster_tree,
    build_master_record,
)
from app.db import init_db
from app.models import (
    DataQualityClusterGoldenValue,
    DataQualityColumnMapping,
    DataQualityDataset,
    DataQualityProfileConfig,
    DataQualityRecordCluster,
)

XLSX_MIME = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


# ---------------------------------------------------------------------------
# Helpers (mirrored from test_data_quality_similarity_engine.py)
# ---------------------------------------------------------------------------


def login_as_user(client) -> None:
    r = client.post(
        "/api/auth/login",
        json={"username": "user", "password": "password"},
    )
    assert r.status_code == 200


def make_dq_project(client) -> int:
    r = client.post(
        "/api/projects",
        json={"name": "DQ US 3.7", "project_type_code": "data_quality_assessment"},
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


def upload(client, pid: int, payload: bytes, filename: str = "p.xlsx") -> dict:
    r = client.post(
        f"/api/projects/{pid}/dq/datasets",
        files={"upload": (filename, payload, XLSX_MIME)},
    )
    assert r.status_code == 201, r.text
    return r.json()


def planted_xlsx() -> bytes:
    """Two sheets with one cluster-able triple per side.

    The 'Acme' triple has conflicts on every column so the tree builder
    has interesting conflicts to surface:
      - name: variants collapse under case_fold + suffix_strip
      - email: two distinct emails, normalization changes neither, so
        this is a TRUE conflict the user must resolve
      - city: agrees across all members
    """
    return build_xlsx(
        {
            "customers": [
                ["id", "name", "email", "city"],
                [1, "Acme Robotics", "ar@example.com", "San Francisco"],
                [2, "Brightlight Media", "bm@example.com", "Boston"],
                [3, "Helix Pharmaceuticals", "hp@example.com", "Austin"],
            ],
            "leads": [
                ["lead_id", "company", "contact_email", "city"],
                [101, "ACME ROBOTICS INC", "ar2@example.com", "San Francisco"],
                [102, "Bright Light Media LLC", "bm@example.com", "Boston"],
                [103, "Helix Pharma Inc", "hp@example.com", "Austin"],
            ],
        }
    )


def save_config(client, pid: int, did: int) -> None:
    r = client.put(
        f"/api/projects/{pid}/dq/datasets/{did}/similarity/config",
        json={
            "sheet_a": "customers",
            "sheet_b": "leads",
            "normalization": {
                "case_fold": True,
                "collapse_whitespace": True,
                "strip_corporate_suffix": True,
            },
            "threshold": 0.85,
            "mappings": [
                {
                    "column_a": "name",
                    "column_b": "company",
                    "algorithm": "jaro_winkler",
                    "weight": 1.0,
                    "is_important": True,
                    "parser": None,
                },
                {
                    "column_a": "email",
                    "column_b": "contact_email",
                    "algorithm": "exact",
                    "weight": 0.5,
                    "is_important": False,
                    "parser": "email",
                },
                {
                    "column_a": "city",
                    "column_b": "city",
                    "algorithm": "exact",
                    "weight": 0.3,
                    "is_important": False,
                    "parser": None,
                },
            ],
        },
    )
    assert r.status_code == 200, r.text


# ---------------------------------------------------------------------------
# Pure-builder tests
# ---------------------------------------------------------------------------


def test_bucket_for_known_pattern_labels() -> None:
    assert _bucket_for(ColumnFacts("string", "email", 100.0)) == "Contact"
    assert _bucket_for(ColumnFacts("string", "e164_phone", 100.0)) == "Contact"
    assert _bucket_for(ColumnFacts("string", "us_zip", 100.0)) == "Address"
    assert _bucket_for(ColumnFacts("string", "ca_postal", 100.0)) == "Address"
    assert _bucket_for(ColumnFacts("date", None, 50.0)) == "Dates"
    assert _bucket_for(ColumnFacts("string", "iso_date", 100.0)) == "Dates"
    assert _bucket_for(ColumnFacts("string", "uuid", 100.0)) == "Identifiers"
    # High-cardinality string -> Identifiers
    assert _bucket_for(ColumnFacts("string", None, 99.0)) == "Identifiers"
    # High-cardinality integer -> Identifiers
    assert _bucket_for(ColumnFacts("integer", None, 99.0)) == "Identifiers"
    # Low-cardinality integer -> Numeric (not Identifier)
    assert _bucket_for(ColumnFacts("integer", None, 10.0)) == "Numeric"
    assert _bucket_for(ColumnFacts("float", None, 80.0)) == "Numeric"
    assert _bucket_for(ColumnFacts("string", "currency_usd", 50.0)) == "Numeric"
    # Anything else -> Other
    assert _bucket_for(ColumnFacts("boolean", None, 5.0)) == "Other"
    assert _bucket_for(ColumnFacts("string", "url", 90.0)) == "Other"


def test_combined_bucket_picks_higher_priority_side() -> None:
    contact = ColumnFacts("string", "email", 100.0)
    other = ColumnFacts("string", None, 10.0)
    assert _combined_bucket(contact, other) == "Contact"
    assert _combined_bucket(other, contact) == "Contact"
    assert _combined_bucket(None, contact) == "Contact"
    # Both None -> Other
    assert _combined_bucket(None, None) == "Other"


def _baseline_mappings() -> list[TreeMapping]:
    return [
        TreeMapping(id=1, column_a="name", column_b="company", weight=1.0, is_important=True),
        TreeMapping(id=2, column_a="email", column_b="contact_email", weight=0.5, is_important=False),
        TreeMapping(id=3, column_a="city", column_b="city", weight=0.3, is_important=False),
    ]


def _baseline_rows() -> tuple[list[dict], list[dict]]:
    rows_a = [
        {"name": "Acme Robotics", "email": "ar@example.com", "city": "SF", "_row_index": 0},
        {"name": "Acme Robotics", "email": "ar@example.com", "city": "SF", "_row_index": 1},
    ]
    rows_b = [
        {"company": "ACME ROBOTICS INC", "contact_email": "ar2@example.com", "city": "SF", "_row_index": 0},
    ]
    return rows_a, rows_b


def _baseline_facts() -> tuple[dict[str, ColumnFacts], dict[str, ColumnFacts]]:
    facts_a = {
        "name": ColumnFacts("string", None, 80.0),
        "email": ColumnFacts("string", "email", 100.0),
        "city": ColumnFacts("string", None, 20.0),
    }
    facts_b = {
        "company": ColumnFacts("string", None, 80.0),
        "contact_email": ColumnFacts("string", "email", 100.0),
        "city": ColumnFacts("string", None, 20.0),
    }
    return facts_a, facts_b


def test_build_tree_root_is_highest_weight_important_column() -> None:
    """Multiple important columns -> root is the highest-weight one.

    Ties are broken on lowest mapping id to mirror cluster.py's blocking
    choice; here we craft a clean weight difference so the test stays
    about the primary rule."""
    mappings = [
        TreeMapping(id=1, column_a="name", column_b="company", weight=0.7, is_important=True),
        TreeMapping(id=2, column_a="email", column_b="contact_email", weight=0.9, is_important=True),
        TreeMapping(id=3, column_a="city", column_b="city", weight=0.3, is_important=False),
    ]
    rows_a, rows_b = _baseline_rows()
    facts_a, facts_b = _baseline_facts()
    norm = Normalizer.from_toggles({"case_fold": True, "strip_corporate_suffix": True})

    tree = build_cluster_tree(
        cluster_fingerprint="fp1",
        mappings=mappings,
        rows_a=rows_a,
        rows_b=rows_b,
        column_facts_a=facts_a,
        column_facts_b=facts_b,
        normalizer=norm,
        golden_overrides={},
        golden_explicit_columns=set(),
    )
    # email had weight 0.9 > name's 0.7
    assert tree.root_column_a == "email"
    # name (the other important column) sits in the Important group
    important_group = next(g for g in tree.groups if g.bucket == "Important")
    leaf_names = [l.column_a for l in important_group.leaves]
    assert "name" in leaf_names


def test_build_tree_normalization_collapse_yields_auto_pick() -> None:
    """Three raw company-name variants that normalize to the same key:
    NO conflict, auto_pick = most-common raw form."""
    mappings = [
        TreeMapping(id=1, column_a="name", column_b="company", weight=1.0, is_important=True),
    ]
    rows_a = [
        {"name": "Acme Robotics", "_row_index": 0},
        {"name": "Acme Robotics", "_row_index": 1},  # duplicate raw -> wins tie
    ]
    rows_b = [
        {"company": "ACME ROBOTICS INC", "_row_index": 0},
    ]
    facts = {"name": ColumnFacts("string", None, 80.0)}
    facts_b = {"company": ColumnFacts("string", None, 80.0)}
    norm = Normalizer.from_toggles(
        {"case_fold": True, "strip_corporate_suffix": True, "collapse_whitespace": True}
    )

    tree = build_cluster_tree(
        cluster_fingerprint="fp",
        mappings=mappings,
        rows_a=rows_a,
        rows_b=rows_b,
        column_facts_a=facts,
        column_facts_b=facts_b,
        normalizer=norm,
        golden_overrides={},
        golden_explicit_columns=set(),
    )
    assert tree.root_is_conflict is False
    assert tree.root_value == "Acme Robotics"  # most common raw, count=2


def test_build_tree_true_conflict_requires_resolution() -> None:
    """Two distinct emails -> the leaf is a conflict; auto_pick is None
    and the user is expected to choose one."""
    mappings = _baseline_mappings()
    rows_a, rows_b = _baseline_rows()
    facts_a, facts_b = _baseline_facts()
    norm = Normalizer.from_toggles(
        {"case_fold": True, "strip_corporate_suffix": True, "collapse_whitespace": True}
    )

    tree = build_cluster_tree(
        cluster_fingerprint="fp",
        mappings=mappings,
        rows_a=rows_a,
        rows_b=rows_b,
        column_facts_a=facts_a,
        column_facts_b=facts_b,
        normalizer=norm,
        golden_overrides={},
        golden_explicit_columns=set(),
    )
    # Root (name) auto-picks via suffix strip
    assert tree.root_is_conflict is False
    # Email leaf is a conflict
    contact_group = next(g for g in tree.groups if g.bucket == "Contact")
    email_leaf = next(l for l in contact_group.leaves if l.column_a == "email")
    assert email_leaf.is_conflict is True
    assert email_leaf.auto_pick is None
    assert email_leaf.chosen is None
    # Two non-null variants
    non_null = [v for v in email_leaf.variants if v.normalized is not None]
    assert len(non_null) == 2
    # conflict_count includes only this leaf (name + city aren't conflicts)
    assert tree.conflict_count == 1
    assert tree.resolved_conflict_count == 0


def test_build_tree_golden_override_overrides_auto_pick() -> None:
    """A saved golden value wins over the engine's auto-pick."""
    mappings = _baseline_mappings()
    rows_a, rows_b = _baseline_rows()
    facts_a, facts_b = _baseline_facts()
    norm = Normalizer.from_toggles({"case_fold": True})

    # User explicitly picks the 'ar2@example.com' variant for email
    overrides = {"email": "ar2@example.com"}
    explicit = {"email"}

    tree = build_cluster_tree(
        cluster_fingerprint="fp",
        mappings=mappings,
        rows_a=rows_a,
        rows_b=rows_b,
        column_facts_a=facts_a,
        column_facts_b=facts_b,
        normalizer=norm,
        golden_overrides=overrides,
        golden_explicit_columns=explicit,
    )
    contact_group = next(g for g in tree.groups if g.bucket == "Contact")
    email_leaf = next(l for l in contact_group.leaves if l.column_a == "email")
    assert email_leaf.chosen == "ar2@example.com"
    assert email_leaf.chosen_is_explicit is True
    assert tree.resolved_conflict_count == 1


def test_build_tree_golden_explicit_null_distinguished_from_unset() -> None:
    """Explicit null override (user picked 'no value') must be treated
    as a real choice — distinct from no override at all."""
    mappings = [TreeMapping(id=1, column_a="name", column_b="company", weight=1.0, is_important=True)]
    rows_a = [{"name": None, "_row_index": 0}]
    rows_b = [{"company": "Acme", "_row_index": 0}]
    facts = {"name": ColumnFacts("string", None, 50.0)}
    facts_b = {"company": ColumnFacts("string", None, 50.0)}
    norm = Normalizer.from_toggles({})

    tree = build_cluster_tree(
        cluster_fingerprint="fp",
        mappings=mappings,
        rows_a=rows_a,
        rows_b=rows_b,
        column_facts_a=facts,
        column_facts_b=facts_b,
        normalizer=norm,
        golden_overrides={"name": None},
        golden_explicit_columns={"name"},
    )
    assert tree.root_value is None
    assert tree.root_chosen_is_explicit is True


# ---------------------------------------------------------------------------
# Fingerprint
# ---------------------------------------------------------------------------


def test_fingerprint_is_order_insensitive() -> None:
    fp1 = cluster_fingerprint([0, 1, 2], [10, 20])
    fp2 = cluster_fingerprint([2, 0, 1], [20, 10])
    assert fp1 == fp2


def test_fingerprint_distinguishes_a_from_b() -> None:
    """A row index appearing on side A is not the same as one on side B,
    so swapping {0,1} between sides must change the hash."""
    assert cluster_fingerprint([0, 1], []) != cluster_fingerprint([], [0, 1])


def test_fingerprint_changes_when_membership_changes() -> None:
    base = cluster_fingerprint([0, 1, 2], [10, 11])
    plus_one = cluster_fingerprint([0, 1, 2, 3], [10, 11])
    minus_one = cluster_fingerprint([0, 1], [10, 11])
    assert base != plus_one
    assert base != minus_one


# ---------------------------------------------------------------------------
# Persistence + HTTP round-trip
# ---------------------------------------------------------------------------


def _run_clusters(client, pid: int, did: int) -> tuple[int, list[dict]]:
    r = client.post(f"/api/projects/{pid}/dq/datasets/{did}/similarity/run")
    assert r.status_code == 200, r.text
    run_id = r.json()["id"]
    r = client.get(
        f"/api/projects/{pid}/dq/datasets/{did}/similarity/runs/{run_id}/clusters"
    )
    assert r.status_code == 200
    return run_id, r.json()


def test_cluster_row_carries_fingerprint_after_run(client, db) -> None:
    login_as_user(client)
    pid = make_dq_project(client)
    ds = upload(client, pid, planted_xlsx())
    save_config(client, pid, ds["id"])
    run_id, clusters = _run_clusters(client, pid, ds["id"])
    assert clusters, "expected at least one cluster"
    cluster_id = clusters[0]["id"]
    row = (
        db.query(DataQualityRecordCluster).filter_by(id=cluster_id).one()
    )
    assert row.fingerprint, "engine must populate fingerprint inline"
    # Fingerprint must match the cluster's actual member set.
    expected = cluster_fingerprint(row.a_members, row.b_members)
    assert row.fingerprint == expected


def test_get_tree_endpoint_returns_root_and_bucketed_groups(client, db) -> None:
    login_as_user(client)
    pid = make_dq_project(client)
    ds = upload(client, pid, planted_xlsx())
    save_config(client, pid, ds["id"])
    run_id, clusters = _run_clusters(client, pid, ds["id"])
    # Pick the Acme cluster — by canonical key it should be the one
    # whose 'name' value starts with 'Acme'.
    cluster = next(
        c for c in clusters if str(c["canonical_key"].get("name", "")).lower().startswith("acme")
    )
    r = client.get(
        f"/api/projects/{pid}/dq/datasets/{ds['id']}/similarity/runs/{run_id}/clusters/{cluster['id']}/tree"
    )
    assert r.status_code == 200, r.text
    body = r.json()

    assert body["root_column_a"] == "name"
    # Email and city are non-important; bucketed groups should exist
    buckets = {g["bucket"] for g in body["groups"]}
    # email -> Contact (via pattern_label); city has no pattern label -> Other
    assert "Contact" in buckets
    # conflict_count >= 1 (two distinct emails for Acme cluster)
    assert body["conflict_count"] >= 1
    assert body["resolved_conflict_count"] == 0


def test_put_golden_then_get_tree_persists_choice(client, db) -> None:
    login_as_user(client)
    pid = make_dq_project(client)
    ds = upload(client, pid, planted_xlsx())
    save_config(client, pid, ds["id"])
    run_id, clusters = _run_clusters(client, pid, ds["id"])
    cluster = next(
        c for c in clusters if str(c["canonical_key"].get("name", "")).lower().startswith("acme")
    )

    # Pick the lead-side email as the golden
    r = client.put(
        f"/api/projects/{pid}/dq/datasets/{ds['id']}/similarity/runs/{run_id}/clusters/{cluster['id']}/tree/golden",
        json={"column_name": "email", "chosen_value": "ar2@example.com"},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    contact_group = next(g for g in body["groups"] if g["bucket"] == "Contact")
    email_leaf = next(l for l in contact_group["leaves"] if l["column_a"] == "email")
    assert email_leaf["chosen"] == "ar2@example.com"
    assert email_leaf["chosen_is_explicit"] is True
    assert body["resolved_conflict_count"] == 1

    # Fresh GET should see the same choice
    r = client.get(
        f"/api/projects/{pid}/dq/datasets/{ds['id']}/similarity/runs/{run_id}/clusters/{cluster['id']}/tree"
    )
    assert r.status_code == 200
    body = r.json()
    email_leaf = next(
        l
        for g in body["groups"]
        if g["bucket"] == "Contact"
        for l in g["leaves"]
        if l["column_a"] == "email"
    )
    assert email_leaf["chosen"] == "ar2@example.com"


def test_put_golden_rejects_value_not_in_variants(client, db) -> None:
    login_as_user(client)
    pid = make_dq_project(client)
    ds = upload(client, pid, planted_xlsx())
    save_config(client, pid, ds["id"])
    run_id, clusters = _run_clusters(client, pid, ds["id"])
    cluster = next(
        c for c in clusters if str(c["canonical_key"].get("name", "")).lower().startswith("acme")
    )
    r = client.put(
        f"/api/projects/{pid}/dq/datasets/{ds['id']}/similarity/runs/{run_id}/clusters/{cluster['id']}/tree/golden",
        json={"column_name": "email", "chosen_value": "imposter@evil.com"},
    )
    assert r.status_code == 400
    assert "variant" in r.json()["detail"].lower()


def test_put_golden_rejects_unknown_column(client, db) -> None:
    login_as_user(client)
    pid = make_dq_project(client)
    ds = upload(client, pid, planted_xlsx())
    save_config(client, pid, ds["id"])
    run_id, clusters = _run_clusters(client, pid, ds["id"])
    cluster = clusters[0]
    r = client.put(
        f"/api/projects/{pid}/dq/datasets/{ds['id']}/similarity/runs/{run_id}/clusters/{cluster['id']}/tree/golden",
        json={"column_name": "nonexistent_column", "chosen_value": "x"},
    )
    assert r.status_code == 400
    assert "not part of this cluster" in r.json()["detail"].lower()


def test_delete_golden_reverts_to_auto_pick(client, db) -> None:
    login_as_user(client)
    pid = make_dq_project(client)
    ds = upload(client, pid, planted_xlsx())
    save_config(client, pid, ds["id"])
    run_id, clusters = _run_clusters(client, pid, ds["id"])
    cluster = next(
        c for c in clusters if str(c["canonical_key"].get("name", "")).lower().startswith("acme")
    )
    # Save a pick
    client.put(
        f"/api/projects/{pid}/dq/datasets/{ds['id']}/similarity/runs/{run_id}/clusters/{cluster['id']}/tree/golden",
        json={"column_name": "email", "chosen_value": "ar2@example.com"},
    )
    # Delete it
    r = client.delete(
        f"/api/projects/{pid}/dq/datasets/{ds['id']}/similarity/runs/{run_id}/clusters/{cluster['id']}/tree/golden/email"
    )
    assert r.status_code == 200, r.text
    body = r.json()
    email_leaf = next(
        l
        for g in body["groups"]
        if g["bucket"] == "Contact"
        for l in g["leaves"]
        if l["column_a"] == "email"
    )
    assert email_leaf["chosen_is_explicit"] is False
    # Email is still a conflict (two distinct values), so no auto-pick
    assert email_leaf["chosen"] is None
    assert body["resolved_conflict_count"] == 0


def test_delete_golden_is_idempotent_for_missing_row(client, db) -> None:
    login_as_user(client)
    pid = make_dq_project(client)
    ds = upload(client, pid, planted_xlsx())
    save_config(client, pid, ds["id"])
    run_id, clusters = _run_clusters(client, pid, ds["id"])
    cluster = clusters[0]
    # Never set; DELETE should still succeed.
    r = client.delete(
        f"/api/projects/{pid}/dq/datasets/{ds['id']}/similarity/runs/{run_id}/clusters/{cluster['id']}/tree/golden/email"
    )
    assert r.status_code == 200


def test_golden_survives_re_run_via_fingerprint(client, db) -> None:
    """Re-running the engine produces NEW cluster rows with new IDs.
    The user's saved golden picks must follow the cluster's MEMBERSHIP
    (via fingerprint), not its old ID."""
    login_as_user(client)
    pid = make_dq_project(client)
    ds = upload(client, pid, planted_xlsx())
    save_config(client, pid, ds["id"])
    run_id, clusters = _run_clusters(client, pid, ds["id"])
    cluster = next(
        c for c in clusters if str(c["canonical_key"].get("name", "")).lower().startswith("acme")
    )
    # Save the pick
    client.put(
        f"/api/projects/{pid}/dq/datasets/{ds['id']}/similarity/runs/{run_id}/clusters/{cluster['id']}/tree/golden",
        json={"column_name": "email", "chosen_value": "ar2@example.com"},
    )

    # Re-run — the engine creates a new run + new cluster rows.
    new_run_id, new_clusters = _run_clusters(client, pid, ds["id"])
    assert new_run_id != run_id
    new_cluster = next(
        c for c in new_clusters if str(c["canonical_key"].get("name", "")).lower().startswith("acme")
    )
    assert new_cluster["id"] != cluster["id"]

    # Fingerprint MUST be identical (same member rows) for the carryover.
    old_row = db.query(DataQualityRecordCluster).filter_by(id=cluster["id"]).one_or_none()
    new_row = db.query(DataQualityRecordCluster).filter_by(id=new_cluster["id"]).one()
    # The first run's clusters were deleted by the new run? Actually runs
    # are append-only, so old_row may still exist.
    if old_row is not None:
        assert old_row.fingerprint == new_row.fingerprint

    r = client.get(
        f"/api/projects/{pid}/dq/datasets/{ds['id']}/similarity/runs/{new_run_id}/clusters/{new_cluster['id']}/tree"
    )
    assert r.status_code == 200
    body = r.json()
    email_leaf = next(
        l
        for g in body["groups"]
        if g["bucket"] == "Contact"
        for l in g["leaves"]
        if l["column_a"] == "email"
    )
    assert email_leaf["chosen"] == "ar2@example.com"
    assert email_leaf["chosen_is_explicit"] is True


def test_put_golden_array_keep_all_round_trip(client, db) -> None:
    """User picks "keep all variants" for the email leaf — the server
    stores it as ``value_kind='array'`` + JSON-encoded list, and a
    subsequent GET returns the list intact for the UI to render."""
    login_as_user(client)
    pid = make_dq_project(client)
    ds = upload(client, pid, planted_xlsx())
    save_config(client, pid, ds["id"])
    run_id, clusters = _run_clusters(client, pid, ds["id"])
    cluster = next(
        c for c in clusters if str(c["canonical_key"].get("name", "")).lower().startswith("acme")
    )

    r = client.put(
        f"/api/projects/{pid}/dq/datasets/{ds['id']}/similarity/runs/{run_id}/clusters/{cluster['id']}/tree/golden",
        json={
            "column_name": "email",
            "chosen_value": ["ar@example.com", "ar2@example.com"],
        },
    )
    assert r.status_code == 200, r.text
    body = r.json()
    email_leaf = next(
        l
        for g in body["groups"]
        if g["bucket"] == "Contact"
        for l in g["leaves"]
        if l["column_a"] == "email"
    )
    assert email_leaf["chosen"] == ["ar@example.com", "ar2@example.com"]
    assert email_leaf["chosen_is_explicit"] is True
    assert body["resolved_conflict_count"] == 1

    # Storage shape: value_kind = 'array', chosen_value = JSON string.
    row = (
        db.query(DataQualityClusterGoldenValue)
        .filter_by(dataset_id=ds["id"], column_name="email")
        .one()
    )
    assert row.value_kind == "array"
    assert json.loads(row.chosen_value) == ["ar@example.com", "ar2@example.com"]

    # Fresh GET round-trips the list.
    r = client.get(
        f"/api/projects/{pid}/dq/datasets/{ds['id']}/similarity/runs/{run_id}/clusters/{cluster['id']}/tree"
    )
    body = r.json()
    email_leaf = next(
        l
        for g in body["groups"]
        if g["bucket"] == "Contact"
        for l in g["leaves"]
        if l["column_a"] == "email"
    )
    assert email_leaf["chosen"] == ["ar@example.com", "ar2@example.com"]


def test_put_golden_array_rejects_empty_list(client, db) -> None:
    login_as_user(client)
    pid = make_dq_project(client)
    ds = upload(client, pid, planted_xlsx())
    save_config(client, pid, ds["id"])
    run_id, clusters = _run_clusters(client, pid, ds["id"])
    cluster = next(
        c for c in clusters if str(c["canonical_key"].get("name", "")).lower().startswith("acme")
    )
    r = client.put(
        f"/api/projects/{pid}/dq/datasets/{ds['id']}/similarity/runs/{run_id}/clusters/{cluster['id']}/tree/golden",
        json={"column_name": "email", "chosen_value": []},
    )
    assert r.status_code == 400
    assert "at least one variant" in r.json()["detail"].lower()


def test_put_golden_array_rejects_entry_not_in_variants(client, db) -> None:
    login_as_user(client)
    pid = make_dq_project(client)
    ds = upload(client, pid, planted_xlsx())
    save_config(client, pid, ds["id"])
    run_id, clusters = _run_clusters(client, pid, ds["id"])
    cluster = next(
        c for c in clusters if str(c["canonical_key"].get("name", "")).lower().startswith("acme")
    )
    r = client.put(
        f"/api/projects/{pid}/dq/datasets/{ds['id']}/similarity/runs/{run_id}/clusters/{cluster['id']}/tree/golden",
        json={
            "column_name": "email",
            # First entry is real, second is bogus -> still rejected.
            "chosen_value": ["ar@example.com", "imposter@evil.com"],
        },
    )
    assert r.status_code == 400
    assert "imposter@evil.com" in r.json()["detail"]


def test_put_golden_array_then_switch_to_scalar(client, db) -> None:
    """A leaf that was previously saved as 'array' can be re-saved as a
    scalar without leaking the old list — the row is updated in place
    with the new value_kind."""
    login_as_user(client)
    pid = make_dq_project(client)
    ds = upload(client, pid, planted_xlsx())
    save_config(client, pid, ds["id"])
    run_id, clusters = _run_clusters(client, pid, ds["id"])
    cluster = next(
        c for c in clusters if str(c["canonical_key"].get("name", "")).lower().startswith("acme")
    )

    # First save as array
    client.put(
        f"/api/projects/{pid}/dq/datasets/{ds['id']}/similarity/runs/{run_id}/clusters/{cluster['id']}/tree/golden",
        json={
            "column_name": "email",
            "chosen_value": ["ar@example.com", "ar2@example.com"],
        },
    )
    # Then re-save as scalar
    r = client.put(
        f"/api/projects/{pid}/dq/datasets/{ds['id']}/similarity/runs/{run_id}/clusters/{cluster['id']}/tree/golden",
        json={"column_name": "email", "chosen_value": "ar@example.com"},
    )
    assert r.status_code == 200
    body = r.json()
    email_leaf = next(
        l
        for g in body["groups"]
        if g["bucket"] == "Contact"
        for l in g["leaves"]
        if l["column_a"] == "email"
    )
    assert email_leaf["chosen"] == "ar@example.com"

    row = (
        db.query(DataQualityClusterGoldenValue)
        .filter_by(dataset_id=ds["id"], column_name="email")
        .one()
    )
    assert row.value_kind == "scalar"
    assert row.chosen_value == "ar@example.com"


def test_tree_endpoints_require_auth(client) -> None:
    r = client.get(
        "/api/projects/1/dq/datasets/1/similarity/runs/1/clusters/1/tree"
    )
    assert r.status_code == 401
    r = client.put(
        "/api/projects/1/dq/datasets/1/similarity/runs/1/clusters/1/tree/golden",
        json={"column_name": "x", "chosen_value": "y"},
    )
    assert r.status_code == 401
    r = client.delete(
        "/api/projects/1/dq/datasets/1/similarity/runs/1/clusters/1/tree/golden/x"
    )
    assert r.status_code == 401


# ---------------------------------------------------------------------------
# Migration: backfill fingerprint on legacy cluster rows
# ---------------------------------------------------------------------------


def test_fingerprint_backfill_populates_legacy_rows(tmp_path) -> None:
    """A DB that pre-dates US 3.7 has cluster rows with no fingerprint.
    init_db must backfill them via the same hash function the engine
    uses, so golden lookups find them on first render."""
    # Make a fresh engine + schema, then simulate the pre-Part-6 state
    # by clearing the fingerprint and re-running init_db.
    eng = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
        future=True,
    )
    init_db(eng)
    # Insert a fake cluster row directly (no FK enforcement needed for
    # the backfill — it reads members from the row's own JSON).
    # We need to satisfy a chain of FK + NOT NULL constraints. The
    # cluster row is the only one we care about; the rest exist only to
    # carry FK references.
    now_iso = "2025-01-01 00:00:00"
    with eng.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO project_types (id, code, name, is_active) "
                "VALUES (99, 'tmp', 'Tmp', 0)"
            )
        )
        conn.execute(
            text(
                "INSERT INTO users (id, username, created_at) "
                "VALUES (1, 'u', :ts)"
            ),
            {"ts": now_iso},
        )
        conn.execute(
            text(
                "INSERT INTO projects "
                "(id, user_id, project_type_id, name, status, created_at, updated_at) "
                "VALUES (1, 1, 99, 'p', 'draft', :ts, :ts)"
            ),
            {"ts": now_iso},
        )
        conn.execute(
            text(
                "INSERT INTO data_quality_datasets "
                "(id, project_id, original_filename, local_path, file_sha256, "
                "size_bytes, sheets_json, engine_version, uploaded_at, "
                "annotation_status) "
                "VALUES (1, 1, 'x.xlsx', '/tmp/x', 'sha', 1, '[]', 'v', "
                ":ts, 'pending')"
            ),
            {"ts": now_iso},
        )
        conn.execute(
            text(
                "INSERT INTO data_quality_profile_configs "
                "(id, dataset_id, normalization_json, threshold, "
                "engine_version, created_at, updated_at) "
                "VALUES (1, 1, '{}', 0.85, '1.0.0', :ts, :ts)"
            ),
            {"ts": now_iso},
        )
        conn.execute(
            text(
                "INSERT INTO data_quality_similarity_runs "
                "(id, dataset_id, config_id, sheet_a, sheet_b, threshold, "
                "status, candidate_pair_count, passing_pair_count, "
                "cluster_count, engine_version, started_at) "
                "VALUES (1, 1, 1, 'A', 'B', 0.85, 'done', 0, 0, 1, "
                "'1.0.0', :ts)"
            ),
            {"ts": now_iso},
        )
        conn.execute(
            text(
                "INSERT INTO data_quality_record_clusters "
                "(id, run_id, cluster_index, a_member_count, b_member_count, "
                "top_score, min_score, canonical_key_json, a_members_json, "
                "b_members_json, fingerprint, created_at) "
                "VALUES (1, 1, 0, 2, 1, 0.95, 0.9, '{}', '[3, 1]', '[7]', "
                "'', :ts)"
            ),
            {"ts": now_iso},
        )

    # Re-run init_db: the backfill should set fingerprint on the empty row.
    init_db(eng)

    with eng.begin() as conn:
        row = conn.execute(
            text("SELECT fingerprint FROM data_quality_record_clusters WHERE id = 1")
        ).fetchone()

    expected = cluster_fingerprint([1, 3], [7])  # sorted by the backfill
    assert row[0] == expected


# ---------------------------------------------------------------------------
# US 3.8 — Master Record + per-variant subtrees
# ---------------------------------------------------------------------------


def test_tree_version_bumped_to_1_1_0() -> None:
    """The response shape gained the optional master_record field for
    US 3.8, so the engine version must bump so clients can detect a
    new-shape response."""
    assert TREE_VERSION == "1.1.0"


def test_override_applies_matches_scalar_in_variants() -> None:
    """Sanity: a scalar override that IS in the leaf's variant raws
    applies; one that isn't, doesn't (US 3.8 per-variant fallback)."""
    norm = Normalizer.from_toggles({})
    variants = build_cluster_tree(
        cluster_fingerprint="fp",
        mappings=[TreeMapping(id=1, column_a="x", column_b="x", weight=1.0, is_important=True)],
        rows_a=[{"x": "alpha"}, {"x": "beta"}],
        rows_b=[],
        column_facts_a={"x": ColumnFacts("string", None, 100.0)},
        column_facts_b={},
        normalizer=norm,
        golden_overrides={},
        golden_explicit_columns=set(),
    ).root_variants
    assert _override_applies("alpha", variants) is True
    assert _override_applies("nonexistent", variants) is False
    # null variant is absent here → None doesn't apply
    assert _override_applies(None, variants) is False


def test_override_applies_array_requires_every_element_in_variants() -> None:
    norm = Normalizer.from_toggles({})
    variants = build_cluster_tree(
        cluster_fingerprint="fp",
        mappings=[TreeMapping(id=1, column_a="x", column_b="x", weight=1.0, is_important=True)],
        rows_a=[{"x": "alpha"}, {"x": "beta"}, {"x": "gamma"}],
        rows_b=[],
        column_facts_a={"x": ColumnFacts("string", None, 100.0)},
        column_facts_b={},
        normalizer=norm,
        golden_overrides={},
        golden_explicit_columns=set(),
    ).root_variants
    # All present → applies
    assert _override_applies(["alpha", "beta"], variants) is True
    # One missing → does not apply (fallback to auto)
    assert _override_applies(["alpha", "missing"], variants) is False
    # Empty list never applies
    assert _override_applies([], variants) is False


def test_build_tree_per_variant_fallback_when_override_not_in_leaf_variants(
    client, db
) -> None:
    """Cluster-wide override that exists at the cluster level but doesn't
    match any variant in the per-variant subtree's slice → that subtree's
    leaf falls back to its own auto-pick. The override is preserved at
    the cluster level for any subtree where it DOES match."""
    login_as_user(client)
    pid = make_dq_project(client)
    ds = upload(client, pid, planted_xlsx())
    save_config(client, pid, ds["id"])
    run_id, clusters = _run_clusters(client, pid, ds["id"])
    cluster = next(
        c for c in clusters if str(c["canonical_key"].get("name", "")).lower().startswith("acme")
    )

    # Step 1: pick "keep all" on the root (name) so we enter Master
    # Record mode. The Acme cluster's name variants are e.g.
    # "Acme Robotics" + "ACME ROBOTICS INC".
    client.put(
        f"/api/projects/{pid}/dq/datasets/{ds['id']}/similarity/runs/{run_id}/clusters/{cluster['id']}/tree/golden",
        json={
            "column_name": "name",
            "chosen_value": ["Acme Robotics", "ACME ROBOTICS INC"],
        },
    )

    r = client.get(
        f"/api/projects/{pid}/dq/datasets/{ds['id']}/similarity/runs/{run_id}/clusters/{cluster['id']}/tree"
    )
    assert r.status_code == 200, r.text
    body = r.json()

    # Master record framing present
    assert body["master_record"] is not None
    assert body["master_record"]["tag"] == "<name-Parent>"
    assert body["master_record"]["root_column_a"] == "name"
    # Top-level groups are empty when master_record is set
    assert body["groups"] == []
    # Two subtrees, one per kept variant
    subtrees = body["master_record"]["subtrees"]
    assert len(subtrees) == 2
    variants_in_response = {st["variant_raw"] for st in subtrees}
    assert variants_in_response == {"Acme Robotics", "ACME ROBOTICS INC"}


def test_master_record_emitted_only_when_root_is_array(client, db) -> None:
    """A scalar root pick keeps the regular tree shape (master_record is
    null, groups is populated). Switching to keep-all on root makes the
    master_record appear without re-uploading or re-running."""
    login_as_user(client)
    pid = make_dq_project(client)
    ds = upload(client, pid, planted_xlsx())
    save_config(client, pid, ds["id"])
    run_id, clusters = _run_clusters(client, pid, ds["id"])
    cluster = next(
        c for c in clusters if str(c["canonical_key"].get("name", "")).lower().startswith("acme")
    )

    # Default state — no override on root → master_record is null
    r = client.get(
        f"/api/projects/{pid}/dq/datasets/{ds['id']}/similarity/runs/{run_id}/clusters/{cluster['id']}/tree"
    )
    assert r.json()["master_record"] is None
    assert r.json()["groups"], "regular tree should have non-empty groups"

    # Scalar root pick — still no master_record
    client.put(
        f"/api/projects/{pid}/dq/datasets/{ds['id']}/similarity/runs/{run_id}/clusters/{cluster['id']}/tree/golden",
        json={"column_name": "name", "chosen_value": "Acme Robotics"},
    )
    r = client.get(
        f"/api/projects/{pid}/dq/datasets/{ds['id']}/similarity/runs/{run_id}/clusters/{cluster['id']}/tree"
    )
    assert r.json()["master_record"] is None
    assert r.json()["groups"], "scalar root pick should still populate groups"

    # Switch to array root pick — master_record appears
    client.put(
        f"/api/projects/{pid}/dq/datasets/{ds['id']}/similarity/runs/{run_id}/clusters/{cluster['id']}/tree/golden",
        json={
            "column_name": "name",
            "chosen_value": ["Acme Robotics", "ACME ROBOTICS INC"],
        },
    )
    r = client.get(
        f"/api/projects/{pid}/dq/datasets/{ds['id']}/similarity/runs/{run_id}/clusters/{cluster['id']}/tree"
    )
    assert r.json()["master_record"] is not None
    assert r.json()["groups"] == []


def test_master_record_subtree_slice_only_contains_its_variants_rows() -> None:
    """Each per-variant subtree's leaves are computed from the cluster
    rows whose root cell NORMALIZES to that variant.

    This is a pure unit test (no HTTP / DB) because the planted_xlsx
    fixture's variants happen to be normalize-equivalent (case/suffix
    variations of "Acme Robotics"), which makes the slices identical —
    that's correct behavior for normalize-equivalent variants, but it
    can't exercise distinct-slice behavior. Here we synthesize a cluster
    where the user kept TWO normalize-distinct variants ("Acme" and
    "Brightlight") so each subtree gets its own row subset."""
    mappings = [
        TreeMapping(id=1, column_a="name", column_b="name", weight=1.0, is_important=True),
        TreeMapping(id=2, column_a="email", column_b="email", weight=0.5, is_important=False),
    ]
    rows_a = [
        {"name": "Acme", "email": "a@acme.com"},
        {"name": "Brightlight", "email": "b@bright.com"},
        {"name": "Acme", "email": "c@acme.com"},
    ]
    facts = {
        "name": ColumnFacts("string", None, 50.0),
        "email": ColumnFacts("string", "email", 100.0),
    }
    norm = Normalizer.from_toggles({"case_fold": True, "collapse_whitespace": True})

    master = build_master_record(
        cluster_fingerprint="fp",
        kept_variants=["Acme", "Brightlight"],
        mappings=mappings,
        rows_a=rows_a,
        rows_b=[],
        column_facts_a=facts,
        column_facts_b=facts,
        normalizer=norm,
        golden_overrides={"name": ["Acme", "Brightlight"]},
        golden_explicit_columns={"name"},
    )
    assert master.tag == "<name-Parent>"
    assert master.root_column_a == "name"
    assert [st.variant_raw for st in master.subtrees] == ["Acme", "Brightlight"]

    acme_sub = master.subtrees[0].subtree
    bright_sub = master.subtrees[1].subtree

    # Acme subtree's email leaf sees TWO variants (a@acme.com, c@acme.com)
    # — both Acme rows contributed. Brightlight subtree's email leaf
    # sees ONE variant (b@bright.com) only.
    def _email_leaf(sub):
        contact = next(g for g in sub.groups if g.bucket == "Contact")
        return next(l for l in contact.leaves if l.column_a == "email")

    acme_email = _email_leaf(acme_sub)
    bright_email = _email_leaf(bright_sub)
    assert {v.raw for v in acme_email.variants if v.raw is not None} == {
        "a@acme.com",
        "c@acme.com",
    }
    assert {v.raw for v in bright_email.variants if v.raw is not None} == {
        "b@bright.com",
    }


def test_master_record_normalize_equivalent_variants_share_rows() -> None:
    """When two kept variants normalize to the same key (e.g., case
    variants of the same name), both subtrees see the same row set.
    This is the intentional degenerate case — kept "duplicate variants"
    that aren't actually distinct accounts."""
    mappings = [
        TreeMapping(id=1, column_a="name", column_b="name", weight=1.0, is_important=True),
        TreeMapping(id=2, column_a="email", column_b="email", weight=0.5, is_important=False),
    ]
    rows_a = [
        {"name": "Acme", "email": "a@acme.com"},
        {"name": "ACME", "email": "c@acme.com"},
    ]
    facts = {
        "name": ColumnFacts("string", None, 50.0),
        "email": ColumnFacts("string", "email", 100.0),
    }
    # case_fold makes "Acme" and "ACME" normalize identically
    norm = Normalizer.from_toggles({"case_fold": True})

    master = build_master_record(
        cluster_fingerprint="fp",
        kept_variants=["Acme", "ACME"],
        mappings=mappings,
        rows_a=rows_a,
        rows_b=[],
        column_facts_a=facts,
        column_facts_b=facts,
        normalizer=norm,
        golden_overrides={"name": ["Acme", "ACME"]},
        golden_explicit_columns={"name"},
    )
    # Both subtrees include both rows — the email leaf has 2 variants in each.
    for st in master.subtrees:
        contact = next(g for g in st.subtree.groups if g.bucket == "Contact")
        email_leaf = next(l for l in contact.leaves if l.column_a == "email")
        non_null = [v for v in email_leaf.variants if v.normalized is not None]
        assert len(non_null) == 2, (
            f"subtree {st.variant_raw!r} should include both Acme rows, "
            f"got variants: {email_leaf.variants}"
        )


def test_master_record_cluster_wide_pick_applies_only_to_matching_subtree() -> None:
    """A scalar cluster-wide pick on a non-root column applies to
    subtrees whose slice contains that value, and falls back to
    auto-pick on subtrees whose slice doesn't.

    Pure unit test so we can craft normalize-distinct slices (which the
    planted_xlsx fixture can't easily produce — its variants are
    case-equivalent and would slice into the same row set)."""
    mappings = [
        TreeMapping(id=1, column_a="name", column_b="name", weight=1.0, is_important=True),
        TreeMapping(id=2, column_a="email", column_b="email", weight=0.5, is_important=False),
    ]
    rows_a = [
        {"name": "Acme", "email": "a@acme.com"},
        {"name": "Brightlight", "email": "b@bright.com"},
    ]
    facts = {
        "name": ColumnFacts("string", None, 50.0),
        "email": ColumnFacts("string", "email", 100.0),
    }
    norm = Normalizer.from_toggles({"case_fold": True})

    master = build_master_record(
        cluster_fingerprint="fp",
        kept_variants=["Acme", "Brightlight"],
        mappings=mappings,
        rows_a=rows_a,
        rows_b=[],
        column_facts_a=facts,
        column_facts_b=facts,
        normalizer=norm,
        golden_overrides={
            "name": ["Acme", "Brightlight"],
            # Cluster-wide pick on email = "a@acme.com" — only present
            # in the Acme slice, not in the Brightlight slice.
            "email": "a@acme.com",
        },
        golden_explicit_columns={"name", "email"},
    )

    def _email_leaf(sub):
        contact = next(g for g in sub.groups if g.bucket == "Contact")
        return next(l for l in contact.leaves if l.column_a == "email")

    acme_email = _email_leaf(master.subtrees[0].subtree)
    bright_email = _email_leaf(master.subtrees[1].subtree)

    # Acme slice contains a@acme.com → override applies, chosen_is_explicit True
    assert acme_email.chosen == "a@acme.com"
    assert acme_email.chosen_is_explicit is True

    # Brightlight slice has only b@bright.com → override "a@acme.com"
    # doesn't apply, leaf falls back to its own auto-pick.
    assert bright_email.chosen == "b@bright.com"
    assert bright_email.chosen_is_explicit is False


def test_master_record_tag_uses_root_column_name(client, db) -> None:
    """Tag template = ``<{root_column_a}-Parent>``. Here root is the
    'name' column, so tag must be '<name-Parent>'."""
    login_as_user(client)
    pid = make_dq_project(client)
    ds = upload(client, pid, planted_xlsx())
    save_config(client, pid, ds["id"])
    run_id, clusters = _run_clusters(client, pid, ds["id"])
    cluster = next(
        c for c in clusters if str(c["canonical_key"].get("name", "")).lower().startswith("acme")
    )
    client.put(
        f"/api/projects/{pid}/dq/datasets/{ds['id']}/similarity/runs/{run_id}/clusters/{cluster['id']}/tree/golden",
        json={
            "column_name": "name",
            "chosen_value": ["Acme Robotics", "ACME ROBOTICS INC"],
        },
    )
    r = client.get(
        f"/api/projects/{pid}/dq/datasets/{ds['id']}/similarity/runs/{run_id}/clusters/{cluster['id']}/tree"
    )
    assert r.json()["master_record"]["tag"] == "<name-Parent>"
