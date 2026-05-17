"""End-to-end tests for the Epic 3 similarity engine + HTTP endpoints.

Strategy:
- A two-sheet xlsx fixture with planted duplicates (Acme variants on one
  side, Acme variants on the other) — the engine should cluster them
  together.
- A "deliberately disjoint" pair to verify the importance gate rejects
  it.
- An oversized fixture to verify the pair-cap rejects without scoring.

Auth and project setup follow the same pattern as
``test_data_quality_agent.py`` so the smoke utilities (``login_as_user``,
``make_dq_project``) are reusable.
"""
from __future__ import annotations

import io

import openpyxl

from app.data_quality.cluster import (
    MAX_PAIRS_PER_RUN,
    SimilarityRunError,
    _blocking_key,
    block_candidates,
    run_similarity,
)
from app.models import (
    DataQualityColumnMapping,
    DataQualityDataset,
    DataQualityProfileConfig,
    DataQualityRecordCluster,
    DataQualityRecordPair,
    DataQualitySimilarityRun,
)

XLSX_MIME = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


# ---------------------------------------------------------------------------
# Fixtures
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
        json={"name": "DQ Epic3", "project_type_code": "data_quality_assessment"},
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
    """Two sheets with three obvious cross-sheet matches.

    customers: Acme Robotics, Brightlight Media, Helix Pharmaceuticals.
    leads: ACME ROBOTICS INC, Bright Light Media LLC,
    Helix Pharma Inc.
    All three should pair up after normalization (case_fold +
    strip_corp_suffix + collapse_whitespace)."""
    return build_xlsx(
        {
            "customers": [
                ["id", "name", "email"],
                [1, "Acme Robotics", "ar@example.com"],
                [2, "Brightlight Media", "bm@example.com"],
                [3, "Helix Pharmaceuticals", "hp@example.com"],
                [4, "Unrelated Co", "uc@example.com"],
            ],
            "leads": [
                ["lead_id", "company", "contact_email"],
                [101, "ACME ROBOTICS INC", "ar@example.com"],
                [102, "Bright Light Media LLC", "bm@example.com"],
                [103, "Helix Pharma Inc", "hp@example.com"],
                [104, "Globex Corp", "gc@example.com"],
            ],
        }
    )


def _save_minimal_config(
    db, dataset_id: int, *, sheet_a="customers", sheet_b="leads"
) -> DataQualityProfileConfig:
    """Helper for engine-level tests that bypass the HTTP layer."""
    cfg = DataQualityProfileConfig(
        dataset_id=dataset_id,
        sheet_a=sheet_a,
        sheet_b=sheet_b,
        normalization_json='{"case_fold": true, "collapse_whitespace": true, "strip_corporate_suffix": true}',
        threshold=0.85,
        engine_version="1.0.0",
    )
    db.add(cfg)
    db.flush()
    db.add(
        DataQualityColumnMapping(
            config_id=cfg.id,
            column_a="name",
            column_b="company",
            algorithm="jaro_winkler",
            weight=1.0,
            is_important=True,
            parser=None,
            recommended_by="heuristic",
        )
    )
    db.add(
        DataQualityColumnMapping(
            config_id=cfg.id,
            column_a="email",
            column_b="contact_email",
            algorithm="exact",
            weight=1.0,
            is_important=False,
            parser="email",
            recommended_by="heuristic",
        )
    )
    db.commit()
    db.refresh(cfg)
    return cfg


# ---------------------------------------------------------------------------
# Pure-engine tests
# ---------------------------------------------------------------------------


def test_blocking_key_combines_prefix_and_soundex() -> None:
    # "acme robotics" -> prefix "acm" + soundex("acme") = "A500"
    key = _blocking_key("acme robotics")
    assert key is not None
    assert key.startswith("acm|")


def test_blocking_key_returns_none_for_empty() -> None:
    assert _blocking_key(None) is None
    assert _blocking_key("") is None
    assert _blocking_key("   ") is None


def test_block_candidates_pairs_same_key_only() -> None:
    keys_a = ["acm|A500", "bri|B632", None]
    keys_b = ["acm|A500", "xxx|X000", "acm|A500"]
    pairs = block_candidates(keys_a, keys_b)
    # idx_a=0 matches idx_b=0 and idx_b=2; idx_a=1 no match; idx_a=2 (None) skipped.
    assert sorted(pairs) == [(0, 0), (0, 2)]


def test_run_similarity_clusters_planted_duplicates(client, db) -> None:
    login_as_user(client)
    pid = make_dq_project(client)
    ds = upload(client, pid, planted_xlsx())
    cfg = _save_minimal_config(db, ds["id"])

    dataset = db.query(DataQualityDataset).filter_by(id=ds["id"]).one()
    run = run_similarity(db, dataset, cfg)
    db.commit()

    assert run.status == "done", run.error
    # 3 of the 4 customers should pair with 3 of the 4 leads.
    assert run.cluster_count == 3
    assert run.passing_pair_count == 3


def test_run_similarity_rejects_no_important_mapping(client, db) -> None:
    login_as_user(client)
    pid = make_dq_project(client)
    ds = upload(client, pid, planted_xlsx())
    cfg = DataQualityProfileConfig(
        dataset_id=ds["id"],
        sheet_a="customers",
        sheet_b="leads",
        normalization_json="{}",
        threshold=0.85,
        engine_version="1.0.0",
    )
    db.add(cfg)
    db.flush()
    db.add(
        DataQualityColumnMapping(
            config_id=cfg.id,
            column_a="name",
            column_b="company",
            algorithm="jaro_winkler",
            weight=1.0,
            is_important=False,  # NOT important
            parser=None,
        )
    )
    db.commit()

    dataset = db.query(DataQualityDataset).filter_by(id=ds["id"]).one()
    try:
        run_similarity(db, dataset, cfg)
        raise AssertionError("expected SimilarityRunError")
    except SimilarityRunError as e:
        assert "important" in str(e).lower()


def test_run_similarity_within_sheet_dedup_finds_planted_duplicates(
    client, db
) -> None:
    """Within-sheet dedup: a sheet with three pairs of duplicate-ish rows
    should produce three clusters when scored on the company-name column
    using jaro_winkler + corporate-suffix strip."""
    login_as_user(client)
    pid = make_dq_project(client)
    payload = build_xlsx(
        {
            "customers": [
                ["id", "name"],
                [1, "Acme Robotics"],
                [2, "ACME ROBOTICS INC"],         # dup of #1
                [3, "Brightlight Media"],
                [4, "Bright Light Media LLC"],    # dup of #3
                [5, "Helix Pharmaceuticals"],
                [6, "Helix Pharma Inc"],          # dup of #5
                [7, "Globex Corp"],                # singleton (no dup)
            ],
        }
    )
    ds = upload(client, pid, payload)
    cfg = DataQualityProfileConfig(
        dataset_id=ds["id"],
        sheet_a="customers",
        sheet_b="customers",  # within-sheet dedup
        normalization_json=(
            '{"case_fold": true, "collapse_whitespace": true, '
            '"strip_corporate_suffix": true}'
        ),
        threshold=0.85,
        engine_version="1.0.0",
    )
    db.add(cfg)
    db.flush()
    db.add(
        DataQualityColumnMapping(
            config_id=cfg.id,
            column_a="name",
            column_b="name",  # self-mapping
            algorithm="jaro_winkler",
            weight=1.0,
            is_important=True,
            parser=None,
            recommended_by="heuristic",
        )
    )
    db.commit()

    dataset = db.query(DataQualityDataset).filter_by(id=ds["id"]).one()
    run = run_similarity(db, dataset, cfg)
    db.commit()

    assert run.status == "done", run.error
    # 3 planted duplicate pairs -> 3 clusters of size 2; the singleton
    # row (Globex) doesn't form a cluster.
    assert run.cluster_count == 3, (
        f"expected 3 clusters, got {run.cluster_count} "
        f"(passing pairs: {run.passing_pair_count})"
    )
    # In within-sheet mode the engine only enumerates idx_a < idx_b, so
    # passing pairs == cluster count when every cluster is a single pair.
    assert run.passing_pair_count == 3


def test_run_similarity_within_sheet_skips_self_pairs(client, db) -> None:
    """Sanity: a row must NEVER be matched against itself, even with an
    algorithm that would score 1.0 on identical inputs (here: exact)."""
    login_as_user(client)
    pid = make_dq_project(client)
    payload = build_xlsx(
        {
            "items": [
                ["sku"],
                ["A1"],
                ["B2"],
                ["C3"],
            ]
        }
    )
    ds = upload(client, pid, payload)
    cfg = DataQualityProfileConfig(
        dataset_id=ds["id"],
        sheet_a="items",
        sheet_b="items",
        normalization_json="{}",
        threshold=0.5,
        engine_version="1.0.0",
    )
    db.add(cfg)
    db.flush()
    db.add(
        DataQualityColumnMapping(
            config_id=cfg.id,
            column_a="sku",
            column_b="sku",
            algorithm="exact",
            weight=1.0,
            is_important=True,
            parser=None,
        )
    )
    db.commit()

    dataset = db.query(DataQualityDataset).filter_by(id=ds["id"]).one()
    run = run_similarity(db, dataset, cfg)
    db.commit()
    assert run.status == "done", run.error
    # All three SKUs are distinct -> no clusters AND no self-pairs.
    assert run.passing_pair_count == 0
    assert run.cluster_count == 0


def test_block_candidates_same_sheet_avoids_duplicates_and_selfpairs() -> None:
    """Pure-engine test of the i<j invariant for same-sheet blocking."""
    keys = ["acm|A500", "acm|A500", "acm|A500"]
    pairs = block_candidates(keys, keys, same_sheet=True)
    # 3 rows in same block -> C(3,2) = 3 pairs (0,1) (0,2) (1,2)
    assert sorted(pairs) == [(0, 1), (0, 2), (1, 2)]


def test_threshold_higher_yields_fewer_clusters(client, db) -> None:
    """Tightening the threshold filters out borderline matches without
    re-running profiling."""
    login_as_user(client)
    pid = make_dq_project(client)
    ds = upload(client, pid, planted_xlsx())
    from app.models import DataQualityDataset as _DS

    dataset = db.query(DataQualityDataset).filter_by(id=ds["id"]).one()

    cfg = _save_minimal_config(db, ds["id"])
    cfg.threshold = 0.5
    db.commit()
    run_low = run_similarity(db, dataset, cfg)
    db.commit()
    low_clusters = run_low.cluster_count

    # Wipe and re-save at a stricter threshold
    db.query(DataQualityRecordPair).delete()
    db.query(DataQualityRecordCluster).delete()
    db.query(DataQualitySimilarityRun).delete()
    cfg.threshold = 0.99
    db.commit()
    run_high = run_similarity(db, dataset, cfg)
    db.commit()

    assert run_high.cluster_count <= low_clusters


# ---------------------------------------------------------------------------
# HTTP endpoint tests
# ---------------------------------------------------------------------------


def test_get_config_returns_heuristic_draft_when_unsaved(client, db) -> None:
    login_as_user(client)
    pid = make_dq_project(client)
    ds = upload(client, pid, planted_xlsx())

    r = client.get(
        f"/api/projects/{pid}/dq/datasets/{ds['id']}/similarity/config"
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["saved"] is False
    assert "customers" in body["available_sheets"]
    assert "leads" in body["available_sheets"]
    assert body["suggested_sheet_a"] == "customers"
    assert body["suggested_sheet_b"] == "leads"
    # The heuristic should pair email column (high name overlap)
    mapping_pairs = {(m["column_a"], m["column_b"]) for m in body["mappings"]}
    assert ("email", "contact_email") in mapping_pairs


def test_save_config_rejects_no_important_mapping(client, db) -> None:
    login_as_user(client)
    pid = make_dq_project(client)
    ds = upload(client, pid, planted_xlsx())
    r = client.put(
        f"/api/projects/{pid}/dq/datasets/{ds['id']}/similarity/config",
        json={
            "sheet_a": "customers",
            "sheet_b": "leads",
            "normalization": {"case_fold": True},
            "threshold": 0.85,
            "mappings": [
                {
                    "column_a": "name",
                    "column_b": "company",
                    "algorithm": "jaro_winkler",
                    "weight": 1.0,
                    "is_important": False,  # missing
                    "parser": None,
                }
            ],
        },
    )
    assert r.status_code == 400
    assert "important" in r.json()["detail"].lower()


def test_save_config_accepts_same_sheet_for_within_sheet_dedup(
    client, db
) -> None:
    """Within-sheet dedup is a supported flow: sheet_a == sheet_b means
    "find duplicates within one sheet". The save endpoint must accept
    it (previously this was rejected, which broke single-sheet
    workbooks)."""
    login_as_user(client)
    pid = make_dq_project(client)
    ds = upload(client, pid, planted_xlsx())
    r = client.put(
        f"/api/projects/{pid}/dq/datasets/{ds['id']}/similarity/config",
        json={
            "sheet_a": "customers",
            "sheet_b": "customers",
            "normalization": {"case_fold": True},
            "threshold": 0.85,
            "mappings": [
                {
                    "column_a": "name",
                    "column_b": "name",
                    "algorithm": "exact",
                    "weight": 1.0,
                    "is_important": True,
                    "parser": None,
                }
            ],
        },
    )
    assert r.status_code == 200, r.text


def test_recommend_endpoint_single_sheet_returns_self_mappings(
    client, db
) -> None:
    """A single-sheet workbook should still produce a useful auto-map.
    POST /similarity/recommend with sheet_a == sheet_b returns each
    column mapped to itself (the greedy pairer awards self-mappings
    the top score of 1.0)."""
    login_as_user(client)
    pid = make_dq_project(client)
    payload = build_xlsx(
        {
            "people": [
                ["id", "full_name", "email_address"],
                [1, "Alice", "a@x.com"],
                [2, "Bob", "b@x.com"],
            ],
        }
    )
    ds = upload(client, pid, payload)
    r = client.post(
        f"/api/projects/{pid}/dq/datasets/{ds['id']}/similarity/recommend",
        json={"sheet_a": "people", "sheet_b": "people"},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    pairs = {(m["column_a"], m["column_b"]) for m in body["mappings"]}
    # Every column maps to itself.
    assert ("full_name", "full_name") in pairs
    assert ("email_address", "email_address") in pairs


def test_get_config_single_sheet_workbook_returns_self_draft(client, db) -> None:
    """A single-sheet workbook used to return suggested_sheet_b=null
    which left the user staring at an empty Sheet B picker. Now the
    draft suggests the same sheet on both sides AND pre-populates
    self-mappings so auto-map works out of the box."""
    login_as_user(client)
    pid = make_dq_project(client)
    payload = build_xlsx(
        {
            "people": [
                ["id", "full_name"],
                [1, "Alice"],
                [2, "Bob"],
            ],
        }
    )
    ds = upload(client, pid, payload)
    r = client.get(
        f"/api/projects/{pid}/dq/datasets/{ds['id']}/similarity/config"
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["saved"] is False
    assert body["suggested_sheet_a"] == "people"
    assert body["suggested_sheet_b"] == "people"
    pairs = {(m["column_a"], m["column_b"]) for m in body["mappings"]}
    assert ("full_name", "full_name") in pairs


def test_dataset_out_includes_config_completed_at_field(client, db) -> None:
    """Regression: the frontend's similarity gate keys on this field. If
    the schema drops it (we ship a model column but forget the response
    model), the gate is silently broken and the user can never reach the
    Profiling Setup page."""
    login_as_user(client)
    pid = make_dq_project(client)
    ds = upload(client, pid, planted_xlsx())
    # Newly-uploaded datasets have not cleared the gate.
    assert "config_completed_at" in ds
    assert ds["config_completed_at"] is None

    # List endpoint must include the field too.
    r = client.get(f"/api/projects/{pid}/dq/datasets")
    assert r.status_code == 200
    rows = r.json()
    assert rows, "expected at least the dataset we just uploaded"
    for row in rows:
        assert "config_completed_at" in row, (
            f"dataset {row.get('id')} missing config_completed_at"
        )


def test_save_config_marks_config_completed_at(client, db) -> None:
    login_as_user(client)
    pid = make_dq_project(client)
    ds = upload(client, pid, planted_xlsx())

    dataset = db.query(DataQualityDataset).filter_by(id=ds["id"]).one()
    assert dataset.config_completed_at is None

    r = client.put(
        f"/api/projects/{pid}/dq/datasets/{ds['id']}/similarity/config",
        json={
            "sheet_a": "customers",
            "sheet_b": "leads",
            "normalization": {"case_fold": True},
            "threshold": 0.85,
            "mappings": [
                {
                    "column_a": "name",
                    "column_b": "company",
                    "algorithm": "jaro_winkler",
                    "weight": 1.0,
                    "is_important": True,
                    "parser": None,
                }
            ],
        },
    )
    assert r.status_code == 200, r.text
    db.expire_all()
    dataset = db.query(DataQualityDataset).filter_by(id=ds["id"]).one()
    assert dataset.config_completed_at is not None


def test_skip_similarity_marks_gate_complete_without_config(client, db) -> None:
    login_as_user(client)
    pid = make_dq_project(client)
    ds = upload(client, pid, planted_xlsx())
    r = client.post(f"/api/projects/{pid}/dq/datasets/{ds['id']}/similarity/skip")
    assert r.status_code == 200
    assert r.json()["config_completed_at"] is not None


def test_run_endpoint_creates_run_and_clusters(client, db) -> None:
    login_as_user(client)
    pid = make_dq_project(client)
    ds = upload(client, pid, planted_xlsx())
    # Save a working config
    r = client.put(
        f"/api/projects/{pid}/dq/datasets/{ds['id']}/similarity/config",
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
                }
            ],
        },
    )
    assert r.status_code == 200, r.text

    r = client.post(
        f"/api/projects/{pid}/dq/datasets/{ds['id']}/similarity/run"
    )
    assert r.status_code == 200, r.text
    run = r.json()
    assert run["status"] == "done"
    assert run["cluster_count"] == 3
    run_id = run["id"]

    r = client.get(
        f"/api/projects/{pid}/dq/datasets/{ds['id']}/similarity/runs/{run_id}/clusters"
    )
    assert r.status_code == 200
    clusters = r.json()
    assert len(clusters) == 3
    # canonical key carries the important column's value
    assert all("name" in c["canonical_key"] for c in clusters)


def test_run_endpoint_400_when_no_config(client, db) -> None:
    login_as_user(client)
    pid = make_dq_project(client)
    ds = upload(client, pid, planted_xlsx())
    r = client.post(
        f"/api/projects/{pid}/dq/datasets/{ds['id']}/similarity/run"
    )
    assert r.status_code == 400
    assert "No similarity config" in r.json()["detail"]


def test_cluster_detail_returns_rows_and_pairs(client, db) -> None:
    login_as_user(client)
    pid = make_dq_project(client)
    ds = upload(client, pid, planted_xlsx())
    client.put(
        f"/api/projects/{pid}/dq/datasets/{ds['id']}/similarity/config",
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
                }
            ],
        },
    )
    run_id = client.post(
        f"/api/projects/{pid}/dq/datasets/{ds['id']}/similarity/run"
    ).json()["id"]
    cluster_id = client.get(
        f"/api/projects/{pid}/dq/datasets/{ds['id']}/similarity/runs/{run_id}/clusters"
    ).json()[0]["id"]

    r = client.get(
        f"/api/projects/{pid}/dq/datasets/{ds['id']}/similarity/runs/{run_id}/clusters/{cluster_id}"
    )
    assert r.status_code == 200, r.text
    detail = r.json()
    assert detail["cluster"]["id"] == cluster_id
    assert len(detail["a_rows"]) >= 1
    assert len(detail["b_rows"]) >= 1
    assert len(detail["pairs"]) >= 1
    # Per-pair scores include the mapped column-pair score breakdown
    assert any(
        "name|company" in p["per_column_scores"] for p in detail["pairs"]
    )


def test_endpoints_require_auth(client) -> None:
    assert (
        client.get("/api/projects/1/dq/datasets/1/similarity/config").status_code
        == 401
    )
    assert (
        client.put(
            "/api/projects/1/dq/datasets/1/similarity/config",
            json={
                "sheet_a": "a",
                "sheet_b": "b",
                "normalization": {},
                "threshold": 0.85,
                "mappings": [],
            },
        ).status_code
        == 401
    )
    assert (
        client.post("/api/projects/1/dq/datasets/1/similarity/run").status_code
        == 401
    )


def test_run_endpoint_pair_cap_enforced(client, db, monkeypatch) -> None:
    """A run with a brute-force-only mapping over a too-large sheet pair
    must be rejected with a clear error, never silently truncated."""
    login_as_user(client)
    pid = make_dq_project(client)

    # Build a workbook that would generate > cap candidate pairs under
    # brute-force enumeration. We force brute-force by marking only a
    # numeric column as important (no text mapping to block on).
    rows_a = [["id", "amount"]] + [[i, float(i)] for i in range(100)]
    rows_b = [["lead_id", "value"]] + [[i, float(i)] for i in range(100)]
    payload = build_xlsx({"A": rows_a, "B": rows_b})
    ds = upload(client, pid, payload)

    # Reduce the cap so we can test without building 100k rows
    from app.data_quality import cluster as cluster_mod

    monkeypatch.setattr(cluster_mod, "MAX_PAIRS_PER_RUN", 50)

    client.put(
        f"/api/projects/{pid}/dq/datasets/{ds['id']}/similarity/config",
        json={
            "sheet_a": "A",
            "sheet_b": "B",
            "normalization": {},
            "threshold": 0.85,
            "mappings": [
                {
                    "column_a": "amount",
                    "column_b": "value",
                    "algorithm": "numeric_tolerance",
                    "weight": 1.0,
                    "is_important": True,
                    "parser": None,
                }
            ],
        },
    )
    r = client.post(
        f"/api/projects/{pid}/dq/datasets/{ds['id']}/similarity/run"
    )
    # Engine raises SimilarityRunError -> mapped to 200 with status=failed
    # OR raised pre-flight as 400. Either is acceptable; assert behavior.
    assert r.status_code == 200, r.text
    run = r.json()
    assert run["status"] == "failed"
    assert "cap" in (run["error"] or "").lower()
