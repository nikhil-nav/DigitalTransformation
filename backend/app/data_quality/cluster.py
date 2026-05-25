"""Cross-sheet record-linkage engine for Epic 3 (US 3.5–3.6).

Inputs: a saved ``DataQualityProfileConfig`` with at least one mapping
marked ``is_important``.

Pipeline:
  1. Load sheet_a and sheet_b as DataFrames (``dtype=object`` so cell
     values arrive untouched).
  2. For every mapping, project the relevant column into a normalized /
     parsed comparison key. Parsers (phone/email/date) replace the
     normalizer for that mapping; otherwise the workbook-level normalizer
     is applied.
  3. Choose a blocking mapping (highest-weight TEXT mapping among the
     important ones). Build candidate pairs by grouping rows with the
     same blocking key. If no text mapping among the important ones,
     fall back to brute-force pair enumeration.
  4. Enforce ``MAX_PAIRS_PER_RUN`` BEFORE scoring; raise loudly if
     exceeded so the user can tighten blocking or split the workbook.
  5. Score every candidate pair, recording per-column scores AND the
     weighted-average pair score. A pair only joins a cluster when its
     per-column score on EVERY important mapping meets the threshold —
     non-important columns are scored for display only.
  6. Union-find over the surviving pairs forms clusters.
  7. Persist run + clusters + pairs.

Precision commitments:
- Rows whose blocking-column value is null/empty are excluded from
  clustering (never silently matched against everything else).
- Pair-count cap is a hard reject, never a silent truncation.
- Importance gate is mandatory: at least one column must be marked
  important. The orchestrator refuses to run otherwise.
- All blocking keys, pair counts, and cluster assignments are
  deterministic for a given (config snapshot, dataset bytes) pair so
  re-runs are byte-stable.
"""
from __future__ import annotations

import hashlib
import json
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Iterable

import jellyfish
import pandas as pd
from sqlalchemy.orm import Session

from app.data_quality.normalize import Normalizer
from app.data_quality.parsers import PARSERS
from app.data_quality.similarity import get_algorithm
from app.models import (
    DataQualityColumnMapping,
    DataQualityDataset,
    DataQualityProfileConfig,
    DataQualityRecordCluster,
    DataQualityRecordPair,
    DataQualitySimilarityRun,
)

CLUSTER_VERSION = "1.0.0"
MAX_PAIRS_PER_RUN = 100_000
BLOCKING_PREFIX_LEN = 3


def cluster_fingerprint(a_members: Iterable[int], b_members: Iterable[int]) -> str:
    """Stable identifier for a cluster's MEMBERSHIP.

    sha256 over ``a:<sorted_a>|b:<sorted_b>`` where each member-set is
    rendered as a comma-joined list of decimal ints. Sorting makes the
    fingerprint order-insensitive; the prefix tags distinguish A from B
    so a same-sheet dedup with members ``{0,1}`` (which appear on both
    sides) hashes the same regardless of which side a row was attributed
    to. Returned as a hex string short enough to index but long enough
    that collisions are not a practical concern for the dataset sizes
    Epic 3 supports."""
    a_sorted = ",".join(str(int(i)) for i in sorted(a_members))
    b_sorted = ",".join(str(int(i)) for i in sorted(b_members))
    payload = f"a:{a_sorted}|b:{b_sorted}".encode("utf-8")
    return hashlib.sha256(payload).hexdigest()

# Algorithms for which text-based blocking is meaningful. Numeric-tolerance
# and date-proximity cannot use a prefix/soundex blocking key.
_TEXT_BLOCK_ALGORITHMS = frozenset(
    {
        "exact",
        "levenshtein",
        "jaro_winkler",
        "jaccard_tokens",
        "cosine_tokens",
        "soundex",
        "metaphone",
        "ngram",
    }
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _isodate_to_str(value: Any) -> Any:
    """Pandas can hand us pandas.Timestamp or datetime objects when a cell
    is date-typed. Convert to an ISO string so parsers/normalizers see a
    consistent input format."""
    if isinstance(value, pd.Timestamp):
        return value.date().isoformat()
    if isinstance(value, datetime):
        return value.date().isoformat()
    return value


def _prepare_column(
    raw_values: Iterable[Any],
    normalizer: Normalizer,
    parser_name: str | None,
) -> list[str | None]:
    """Apply parser if set, otherwise the normalizer, to every cell.

    For parser-using mappings (phone/email/date) we honour parser failures
    by emitting ``None`` for the failing cell — the similarity algorithms
    treat ``None`` as a 0.0 score, so a pair with one unparseable side
    is automatically counted as a per-column miss rather than being
    silently coerced to a match.
    """
    parser = PARSERS.get(parser_name) if parser_name else None
    out: list[str | None] = []
    for raw in raw_values:
        v = _isodate_to_str(raw)
        if parser is not None:
            result = parser(v)
            out.append(result.value if result.ok else None)
        else:
            out.append(normalizer.apply(v))
    return out


def _blocking_key(value: str | None) -> str | None:
    """Compose a blocking key as ``"<prefix>|<soundex of first word>"``.

    Both halves contribute: prefix catches typos at the end, soundex
    catches typos at the start. None when the value is too thin to
    produce a meaningful key — those rows skip clustering rather than
    being matched to everything else.
    """
    if value is None:
        return None
    cleaned = value.strip().lower()
    if not cleaned:
        return None
    prefix = cleaned[:BLOCKING_PREFIX_LEN]
    first_word = cleaned.split(maxsplit=1)[0] if cleaned else ""
    soundex_key = ""
    if first_word and first_word[0].isalpha():
        soundex_key = jellyfish.soundex(first_word)
    return f"{prefix}|{soundex_key}"


def _choose_blocking_mapping(
    mappings: list[DataQualityColumnMapping],
) -> DataQualityColumnMapping | None:
    """Pick the highest-weight TEXT mapping among the important ones.

    Falls back to None when no important mapping uses a text-based
    algorithm; the caller switches to brute-force pair enumeration in
    that case (subject to the pair cap)."""
    important_text = [
        m
        for m in mappings
        if m.is_important and m.algorithm in _TEXT_BLOCK_ALGORITHMS
    ]
    if not important_text:
        return None
    return max(important_text, key=lambda m: (m.weight, -m.id))


# ---------------------------------------------------------------------------
# Pair generation
# ---------------------------------------------------------------------------


def block_candidates(
    blocking_keys_a: list[str | None],
    blocking_keys_b: list[str | None],
    *,
    same_sheet: bool = False,
) -> list[tuple[int, int]]:
    """All (idx_a, idx_b) pairs whose blocking keys are equal and non-null.

    When ``same_sheet`` is True (within-sheet dedup), only emit pairs with
    ``idx_a < idx_b`` — that skips self-pairs (i, i) AND avoids generating
    both (i, j) and (j, i), which would otherwise double-count every
    comparison.

    Returned as a concrete list so the caller can immediately check the
    cap before paying scoring cost."""
    index_b: dict[str, list[int]] = defaultdict(list)
    for idx, key in enumerate(blocking_keys_b):
        if key is not None:
            index_b[key].append(idx)
    out: list[tuple[int, int]] = []
    for idx_a, key_a in enumerate(blocking_keys_a):
        if key_a is None:
            continue
        for idx_b in index_b.get(key_a, ()):
            if same_sheet and idx_a >= idx_b:
                continue
            out.append((idx_a, idx_b))
    return out


def brute_force_candidates(
    n_a: int, n_b: int, *, same_sheet: bool = False
) -> list[tuple[int, int]]:
    if same_sheet:
        return [(a, b) for a in range(n_a) for b in range(n_b) if a < b]
    return [(a, b) for a in range(n_a) for b in range(n_b)]


# ---------------------------------------------------------------------------
# Scoring + aggregation + cluster formation (pure)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class _MappingRuntime:
    """Snapshot of a mapping with its algorithm callable bound, so the
    inner scoring loop avoids repeated registry lookups."""

    column_a: str
    column_b: str
    algorithm: str
    weight: float
    is_important: bool
    parser: str | None
    score_fn: Any
    values_a: list[str | None]
    values_b: list[str | None]


def _materialize_mappings(
    mappings: list[DataQualityColumnMapping],
    df_a: pd.DataFrame,
    df_b: pd.DataFrame,
    normalizer: Normalizer,
) -> list[_MappingRuntime]:
    out: list[_MappingRuntime] = []
    for m in mappings:
        if m.column_a not in df_a.columns:
            raise ValueError(
                f"Sheet A is missing mapped column '{m.column_a}'"
            )
        if m.column_b not in df_b.columns:
            raise ValueError(
                f"Sheet B is missing mapped column '{m.column_b}'"
            )
        out.append(
            _MappingRuntime(
                column_a=m.column_a,
                column_b=m.column_b,
                algorithm=m.algorithm,
                weight=m.weight,
                is_important=m.is_important,
                parser=m.parser,
                score_fn=get_algorithm(m.algorithm).score,
                values_a=_prepare_column(df_a[m.column_a].tolist(), normalizer, m.parser),
                values_b=_prepare_column(df_b[m.column_b].tolist(), normalizer, m.parser),
            )
        )
    return out


def _score_pair(
    idx_a: int,
    idx_b: int,
    runtime: list[_MappingRuntime],
) -> dict[str, float]:
    return {
        f"{m.column_a}|{m.column_b}": float(
            m.score_fn(m.values_a[idx_a], m.values_b[idx_b])
        )
        for m in runtime
    }


def _aggregate_score(
    per_col: dict[str, float], runtime: list[_MappingRuntime]
) -> float:
    total_w = sum(m.weight for m in runtime)
    if total_w == 0:
        return 0.0
    weighted = sum(
        per_col[f"{m.column_a}|{m.column_b}"] * m.weight for m in runtime
    )
    return weighted / total_w


def _passes_importance_gate(
    per_col: dict[str, float],
    runtime: list[_MappingRuntime],
    threshold: float,
) -> bool:
    """A pair joins a cluster only when EVERY important column's
    per-column score meets the threshold. No important column == no run
    (the orchestrator rejects earlier), so this loop is guaranteed to
    enforce at least one check."""
    for m in runtime:
        if not m.is_important:
            continue
        if per_col[f"{m.column_a}|{m.column_b}"] < threshold:
            return False
    return True


@dataclass
class _UnionFind:
    parent: dict[str, str] = field(default_factory=dict)

    def add(self, x: str) -> None:
        self.parent.setdefault(x, x)

    def find(self, x: str) -> str:
        while self.parent[x] != x:
            self.parent[x] = self.parent[self.parent[x]]
            x = self.parent[x]
        return x

    def union(self, x: str, y: str) -> None:
        self.add(x)
        self.add(y)
        rx, ry = self.find(x), self.find(y)
        if rx != ry:
            self.parent[rx] = ry


@dataclass
class _ClusterAcc:
    a_members: set[int] = field(default_factory=set)
    b_members: set[int] = field(default_factory=set)
    top_score: float = 0.0
    min_score: float = 1.0
    representative_idx_a: int | None = None
    representative_idx_b: int | None = None
    representative_score: float = -1.0


def _form_clusters(
    passing: list[tuple[int, int, float]],
) -> dict[str, _ClusterAcc]:
    """Union-find on passing pairs; returns {root_key: acc}.

    ``passing`` is ``[(idx_a, idx_b, agg_score), ...]``. The accumulator
    tracks per-cluster max/min scores and a representative (highest-score)
    pair for canonical-key display.
    """
    uf = _UnionFind()
    for a, b, _s in passing:
        uf.union(f"a:{a}", f"b:{b}")
    clusters: dict[str, _ClusterAcc] = defaultdict(_ClusterAcc)
    for a, b, score in passing:
        root = uf.find(f"a:{a}")
        acc = clusters[root]
        acc.a_members.add(a)
        acc.b_members.add(b)
        acc.top_score = max(acc.top_score, score)
        acc.min_score = min(acc.min_score, score)
        if score > acc.representative_score:
            acc.representative_score = score
            acc.representative_idx_a = a
            acc.representative_idx_b = b
    return clusters


# ---------------------------------------------------------------------------
# Orchestrator + persistence
# ---------------------------------------------------------------------------


class SimilarityRunError(Exception):
    """Wrap engine-side errors so the HTTP layer can map to 400."""


def _canonical_key_from(
    important_mappings: list[_MappingRuntime],
    idx_a: int | None,
    idx_b: int | None,
) -> dict[str, Any]:
    """Build a display key from important columns of a representative pair.

    Uses sheet A's value first, falling back to sheet B when A is null —
    so the dashboard always has something to render, even when the
    matched A-side cell is blank."""
    out: dict[str, Any] = {}
    for m in important_mappings:
        va = m.values_a[idx_a] if idx_a is not None else None
        vb = m.values_b[idx_b] if idx_b is not None else None
        out[m.column_a] = va if va is not None else vb
    return out


def run_similarity(
    db: Session,
    dataset: DataQualityDataset,
    config: DataQualityProfileConfig,
) -> DataQualitySimilarityRun:
    """Execute the engine end-to-end and persist a run row + cluster +
    pair rows. Returns the run row. On engine error, the run row is still
    persisted with ``status='failed'`` and ``error`` populated so the
    user can see what happened."""
    if not config.sheet_a or not config.sheet_b:
        raise SimilarityRunError("Config is missing sheet_a or sheet_b")
    if not config.mappings:
        raise SimilarityRunError("Config has no column mappings")
    if not any(m.is_important for m in config.mappings):
        raise SimilarityRunError(
            "At least one column mapping must be marked important; "
            "important columns drive cluster formation."
        )
    # Within-sheet dedup (sheet_a == sheet_b) is supported alongside
    # cross-sheet linkage. The candidate generator below restricts pairs
    # to idx_a < idx_b in that case so we never self-pair a row or
    # double-count (i,j) and (j,i).
    same_sheet = config.sheet_a == config.sheet_b

    run = DataQualitySimilarityRun(
        dataset_id=dataset.id,
        config_id=config.id,
        sheet_a=config.sheet_a,
        sheet_b=config.sheet_b,
        threshold=config.threshold,
        status="running",
        engine_version=CLUSTER_VERSION,
    )
    db.add(run)
    db.flush()

    try:
        if same_sheet:
            # Load once and alias — saves a parse and guarantees df_a is df_b
            # so the runtime sees identical inputs on both sides.
            df_a = pd.read_excel(
                dataset.local_path, sheet_name=config.sheet_a, dtype=object
            )
            df_b = df_a
        else:
            df_a = pd.read_excel(
                dataset.local_path, sheet_name=config.sheet_a, dtype=object
            )
            df_b = pd.read_excel(
                dataset.local_path, sheet_name=config.sheet_b, dtype=object
            )

        normalizer = Normalizer.from_toggles(config.normalization)
        runtime = _materialize_mappings(config.mappings, df_a, df_b, normalizer)

        blocking_mapping = _choose_blocking_mapping(config.mappings)
        if blocking_mapping is not None:
            run.blocking_column = (
                f"{blocking_mapping.column_a}|{blocking_mapping.column_b}"
            )
            block_a = next(
                m for m in runtime if m.column_a == blocking_mapping.column_a
                and m.column_b == blocking_mapping.column_b
            )
            keys_a = [_blocking_key(v) for v in block_a.values_a]
            keys_b = [_blocking_key(v) for v in block_a.values_b]
            candidates = block_candidates(keys_a, keys_b, same_sheet=same_sheet)
        else:
            run.blocking_column = None
            candidates = brute_force_candidates(
                len(df_a), len(df_b), same_sheet=same_sheet
            )

        run.candidate_pair_count = len(candidates)

        if len(candidates) > MAX_PAIRS_PER_RUN:
            raise SimilarityRunError(
                f"Candidate pair count ({len(candidates):,}) exceeds the "
                f"hard cap of {MAX_PAIRS_PER_RUN:,}. Tighten blocking by "
                f"marking a more selective text column as important, or "
                f"filter the source workbook before re-running."
            )

        passing: list[tuple[int, int, float, dict[str, float]]] = []
        for idx_a, idx_b in candidates:
            per_col = _score_pair(idx_a, idx_b, runtime)
            if not _passes_importance_gate(per_col, runtime, config.threshold):
                continue
            agg = _aggregate_score(per_col, runtime)
            passing.append((idx_a, idx_b, agg, per_col))

        run.passing_pair_count = len(passing)
        clusters = _form_clusters([(a, b, s) for a, b, s, _ in passing])
        run.cluster_count = len(clusters)

        # Persist clusters first so we can attribute pairs to a cluster_id.
        # Map union-find root -> cluster row, then loop pairs to attach.
        important_runtime = [m for m in runtime if m.is_important]
        root_to_row: dict[str, DataQualityRecordCluster] = {}
        for cluster_index, (root, acc) in enumerate(
            sorted(clusters.items(), key=lambda kv: -kv[1].top_score)
        ):
            canonical = _canonical_key_from(
                important_runtime,
                acc.representative_idx_a,
                acc.representative_idx_b,
            )
            row = DataQualityRecordCluster(
                run_id=run.id,
                cluster_index=cluster_index,
                a_member_count=len(acc.a_members),
                b_member_count=len(acc.b_members),
                top_score=acc.top_score,
                min_score=acc.min_score,
                canonical_key_json=json.dumps(canonical, default=str),
                a_members_json=json.dumps(sorted(acc.a_members)),
                b_members_json=json.dumps(sorted(acc.b_members)),
                fingerprint=cluster_fingerprint(acc.a_members, acc.b_members),
            )
            db.add(row)
            root_to_row[root] = row
        db.flush()

        # Now persist pairs, attributed to their cluster.
        uf = _UnionFind()
        for a, b, _s, _ in passing:
            uf.union(f"a:{a}", f"b:{b}")
        for idx_a, idx_b, score, per_col in passing:
            cluster_row = root_to_row.get(uf.find(f"a:{idx_a}"))
            db.add(
                DataQualityRecordPair(
                    run_id=run.id,
                    cluster_id=cluster_row.id if cluster_row else None,
                    row_a_index=idx_a,
                    row_b_index=idx_b,
                    score=score,
                    per_column_scores_json=json.dumps(per_col),
                )
            )

        run.status = "done"
        run.finished_at = datetime.now(timezone.utc)
    except SimilarityRunError as e:
        run.status = "failed"
        run.error = str(e)
        run.finished_at = datetime.now(timezone.utc)
    except Exception as e:  # noqa: BLE001 - any other failure must surface, not crash
        run.status = "failed"
        run.error = f"{type(e).__name__}: {e}"
        run.finished_at = datetime.now(timezone.utc)

    db.flush()
    return run


# ---------------------------------------------------------------------------
# Row-level helpers used by the HTTP layer (so the router doesn't have to
# re-implement xlsx loading every time it serves a cluster-detail view).
# ---------------------------------------------------------------------------


def load_sheet_rows(
    dataset: DataQualityDataset,
    sheet_name: str,
    row_indices: list[int],
) -> list[dict[str, Any]]:
    """Return ``row_indices`` (0-based, data-row indexing — header is row
    0 of the underlying spreadsheet but pandas drops it before indexing)
    from ``sheet_name`` as a list of dicts. Out-of-range indices are
    silently skipped — the cluster only persists indices that existed at
    run time, but the workbook could have been replaced since."""
    if not row_indices:
        return []
    df = pd.read_excel(dataset.local_path, sheet_name=sheet_name, dtype=object)
    out: list[dict[str, Any]] = []
    for idx in row_indices:
        if 0 <= idx < len(df):
            row = {col: _isodate_to_str(df.iloc[idx][col]) for col in df.columns}
            # JSON-safe: pandas NaN -> None
            for k, v in list(row.items()):
                if isinstance(v, float) and v != v:
                    row[k] = None
            row["_row_index"] = idx
            out.append(row)
    return out
