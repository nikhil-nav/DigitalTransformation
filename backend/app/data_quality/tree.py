"""Tree builder for US 3.7 — "superset of similar records" view.

Given a single cluster from the similarity engine, produce a hierarchical
view of its merged record where:
- The root node is the value of the highest-weight ``is_important``
  column (ties broken by lowest mapping id, matching ``cluster.py``'s
  blocking-column choice).
- A first-tier group "Important columns" contains every OTHER important
  mapping (so importance stays visually distinguished under the root).
- A second tier groups every non-important mapping by SEMANTIC BUCKET
  in a fixed order: Identifiers, Contact, Address, Dates, Numeric, Other.

For each column the tree carries:
- A set of ``variants`` — one per distinct normalized value across the
  cluster's members (raw + member_count).
- ``is_conflict`` — True when >1 normalized variant exists.
- ``auto_pick`` — the most-common raw form within the (sole) normalized
  bucket when there is no conflict. Deterministic tie-break: lexicographic
  ascending on the raw string.
- ``chosen`` — the user's golden-record pick if any, otherwise None.
  The HTTP layer overlays this on top before serializing.

The builder is pure: it consumes already-loaded rows, the saved config,
and a mapping of golden overrides. The HTTP layer in router.py is the
only place that talks to the DB.
"""
from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field
from typing import Any, Iterable, Literal

from app.data_quality.normalize import Normalizer

TREE_VERSION = "1.1.0"


Bucket = Literal[
    "Important",
    "Identifiers",
    "Contact",
    "Address",
    "Dates",
    "Numeric",
    "Other",
]

# Render order. "Important" only appears under the root for other important
# columns; the remaining buckets house non-important mappings in this order.
BUCKET_ORDER: tuple[Bucket, ...] = (
    "Important",
    "Identifiers",
    "Contact",
    "Address",
    "Dates",
    "Numeric",
    "Other",
)


@dataclass(frozen=True)
class _ColumnFact:
    """Profile-side facts needed to bucket a column. Built by the HTTP
    layer from the persisted Part-1 column profile so the tree builder
    itself stays DB-free."""

    semantic_type: str  # boolean | integer | float | date | string | empty
    pattern_label: str | None  # email | e164_phone | uuid | iso_date | us_zip | ...
    distinct_pct: float  # 0..100, used by the identifier heuristic


@dataclass(frozen=True)
class ColumnFacts:
    """Public form of _ColumnFact — exported so router.py can construct it
    from the persisted column profile rows."""

    semantic_type: str
    pattern_label: str | None
    distinct_pct: float


@dataclass(frozen=True)
class TreeVariant:
    normalized: str | None  # the Normalizer-produced key; None for null/empty
    raw: str | None         # the most-common raw value within this normalized group
    raw_examples: list[str]  # other raw forms collapsed into this variant (deduped)
    member_count: int       # how many cluster rows contributed this normalized value


@dataclass(frozen=True)
class TreeLeaf:
    column_a: str
    column_b: str
    # Display name = column_a when within-sheet dedup or columns match,
    # otherwise "column_a / column_b" to show the mapping.
    display_name: str
    bucket: Bucket
    is_important: bool
    weight: float
    is_conflict: bool
    variants: list[TreeVariant]
    auto_pick: str | None      # raw value the engine would pick if user hasn't chosen
    # User golden pick. A list represents "keep all variants" (US 3.7);
    # the router validates every entry is a real variant. A scalar string
    # is the conventional pick-one case. None means either no override or
    # explicit null pick (distinguished by chosen_is_explicit).
    chosen: str | list[str] | None
    chosen_is_explicit: bool   # True iff a golden override exists (even if value is None)


@dataclass(frozen=True)
class TreeGroup:
    bucket: Bucket
    leaves: list[TreeLeaf]


@dataclass(frozen=True)
class MasterRecordSubtree:
    """One per-variant subtree under the Master Record (US 3.8).

    ``variant_raw`` is the raw value the user kept for the root column
    (one entry from the keep-all list). ``subtree`` is the full
    ``ClusterTree`` computed from rows whose root cell normalizes to
    this variant."""

    variant_raw: str
    subtree: "ClusterTree"


@dataclass(frozen=True)
class MasterRecord:
    """The Master Record framing that wraps N per-variant subtrees.

    Only produced when the root column's golden pick is a list (US 3.7
    "keep all variants"). ``tag`` follows the spec's
    ``<{root_column_name}-Parent>`` template."""

    tag: str
    root_column_a: str
    subtrees: list[MasterRecordSubtree]


@dataclass(frozen=True)
class ClusterTree:
    cluster_fingerprint: str
    root_column_a: str
    root_column_b: str
    root_display_name: str
    # See TreeLeaf.chosen for the list-vs-scalar semantics.
    root_value: str | list[str] | None
    root_is_conflict: bool
    root_variants: list[TreeVariant]
    root_chosen_is_explicit: bool
    groups: list[TreeGroup]
    conflict_count: int          # leaves needing resolution (including root if conflict)
    resolved_conflict_count: int # leaves with explicit golden pick
    # When set (US 3.8 Master Record mode), ``groups`` is empty — the
    # per-variant subtrees inside ``master_record`` hold the data
    # instead. Null when the root has a scalar pick (regular tree).
    master_record: MasterRecord | None = None
    tree_version: str = TREE_VERSION


# ---------------------------------------------------------------------------
# Bucket assignment
# ---------------------------------------------------------------------------


def _bucket_for(facts: ColumnFacts) -> Bucket:
    """Map a column's profile facts to a semantic bucket.

    Order of checks matters — the first match wins, so high-priority
    buckets (Contact, Address, Dates) shadow lower-priority ones (Numeric,
    Other) when both could apply.
    """
    label = facts.pattern_label
    semantic = facts.semantic_type

    if label in {"email", "e164_phone"}:
        return "Contact"
    if label in {"us_zip", "ca_postal"}:
        return "Address"
    if semantic == "date" or label == "iso_date":
        return "Dates"
    # Identifier heuristic: a known UUID OR a high-cardinality int/string
    # column. Floats are intentionally excluded — a high-cardinality float
    # is almost certainly a measurement, not an identifier.
    if label == "uuid":
        return "Identifiers"
    if facts.distinct_pct >= 95.0 and semantic in {"integer", "string"}:
        return "Identifiers"
    if semantic in {"integer", "float"} or label == "currency_usd":
        return "Numeric"
    return "Other"


def _combined_bucket(
    facts_a: ColumnFacts | None, facts_b: ColumnFacts | None
) -> Bucket:
    """Cross-sheet mappings can pair columns with different semantics
    (e.g. ``customer_id`` int on A vs ``ref_no`` string on B). Pick the
    higher-priority bucket of the two — earliness in BUCKET_ORDER wins —
    so a column-pair that is Contact on one side and Other on the other
    gets the Contact treatment.

    A missing side (no profile row) falls back to ``Other`` rather than
    short-circuiting the comparison."""
    bucket_a = _bucket_for(facts_a) if facts_a is not None else "Other"
    bucket_b = _bucket_for(facts_b) if facts_b is not None else "Other"
    priority = {b: i for i, b in enumerate(BUCKET_ORDER)}
    # "Important" is never produced by _bucket_for; safe to rank.
    return bucket_a if priority[bucket_a] <= priority[bucket_b] else bucket_b


# ---------------------------------------------------------------------------
# Variant assembly
# ---------------------------------------------------------------------------


def _stringify(value: Any) -> str | None:
    """Coerce a cell value to a string for display.

    The Normalizer already null-coerces empty / NaN / blank; this helper
    is for the RAW display value. We keep ``None`` distinct from ``""``
    so a leaf where every member has a null cell renders a single
    "(null)" variant rather than a confusing empty-string variant."""
    if value is None:
        return None
    s = str(value)
    if s == "" or s.lower() == "nan":
        return None
    return s


def _collect_variants(
    raw_values: Iterable[Any], normalizer: Normalizer
) -> list[TreeVariant]:
    """Group raw values by their normalized key, then within each group
    pick a canonical raw form (most common; tie-break: lexicographic asc).

    Ordering of returned variants: by member_count desc, then by raw
    ascending — so the dashboard renders the "winning" variant first."""
    raw_list = [_stringify(v) for v in raw_values]
    norm_list = [normalizer.apply(v) for v in raw_list]

    by_norm: dict[str | None, list[str | None]] = {}
    for raw, norm in zip(raw_list, norm_list):
        by_norm.setdefault(norm, []).append(raw)

    out: list[TreeVariant] = []
    for norm, raws in by_norm.items():
        # Count raw forms; pick the most-common as the "canonical raw" for
        # this normalized bucket. Lexicographic tie-break keeps the choice
        # deterministic across re-runs.
        counts = Counter(r for r in raws if r is not None)
        if counts:
            top_count = max(counts.values())
            tied = sorted([r for r, c in counts.items() if c == top_count])
            canonical_raw = tied[0]
            other_raws = sorted(
                {r for r in counts if r != canonical_raw}
            )
        else:
            # Every raw in this group is None — the variant represents
            # "null" and there is no string form to display.
            canonical_raw = None
            other_raws = []
        out.append(
            TreeVariant(
                normalized=norm,
                raw=canonical_raw,
                raw_examples=other_raws,
                member_count=len(raws),
            )
        )

    # Stable sort: largest group first, then null variants last (so
    # actual values appear above the "(null)" row).
    def _sort_key(v: TreeVariant) -> tuple[int, int, str]:
        return (
            -v.member_count,
            1 if v.normalized is None else 0,
            v.raw or "",
        )
    out.sort(key=_sort_key)
    return out


def _auto_pick(variants: list[TreeVariant]) -> str | None:
    """The engine's default pick when no conflict exists (single variant).

    Falls back to None when the only variant is the null group — that's
    a coherent "every member has no value" state, not a value to pick."""
    if not variants:
        return None
    non_null = [v for v in variants if v.normalized is not None]
    if len(non_null) == 1:
        return non_null[0].raw
    # No non-null variants: every member's cell is empty.
    if not non_null and variants:
        return None
    # >1 non-null variants → it's a conflict, not an auto-pick.
    return None


def _override_applies(
    override: str | list[str] | None,
    variants: list[TreeVariant],
) -> bool:
    """Whether a cluster-wide golden override is renderable on THIS leaf.

    True when:
      - scalar string AND in this leaf's variant raws (incl. raw_examples)
      - None AND a null variant exists
      - list of strings AND every element is in this leaf's variant raws
    Otherwise false — the override was picked under a different per-variant
    subtree (US 3.8 Master Record mode) whose variant set differs from
    this one, and the leaf should fall back to its own auto-pick."""
    raws = variant_raws(variants)
    if isinstance(override, list):
        if not override:
            return False
        return all(v in raws for v in override)
    return override in raws


# ---------------------------------------------------------------------------
# Builder
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class TreeMapping:
    """Subset of a DataQualityColumnMapping the builder needs.

    Lifted out of the SQLAlchemy model so tree.py stays pure / unit-testable
    without a DB session."""

    id: int
    column_a: str
    column_b: str
    weight: float
    is_important: bool


def _display_name(mapping: TreeMapping) -> str:
    if mapping.column_a == mapping.column_b:
        return mapping.column_a
    return f"{mapping.column_a} / {mapping.column_b}"


def _root_mapping(mappings: list[TreeMapping]) -> TreeMapping | None:
    """Highest-weight important mapping; ties broken by lowest id.

    Mirrors ``_choose_blocking_mapping`` in cluster.py so the visual root
    aligns with the engine's blocking column whenever both pick from the
    same set."""
    important = [m for m in mappings if m.is_important]
    if not important:
        return None
    return max(important, key=lambda m: (m.weight, -m.id))


def build_cluster_tree(
    *,
    cluster_fingerprint: str,
    mappings: list[TreeMapping],
    rows_a: list[dict[str, Any]],
    rows_b: list[dict[str, Any]],
    column_facts_a: dict[str, ColumnFacts],
    column_facts_b: dict[str, ColumnFacts],
    normalizer: Normalizer,
    golden_overrides: dict[str, str | list[str] | None],
    golden_explicit_columns: set[str],
) -> ClusterTree:
    """Build the rendered tree.

    Args:
      cluster_fingerprint: pre-computed by ``cluster_fingerprint``; the
        builder just forwards it for the response.
      mappings: every column mapping on the saved config. The root is
        picked from the ``is_important`` subset.
      rows_a / rows_b: the cluster's member rows (already loaded via
        ``load_sheet_rows``). When sheet_a == sheet_b the caller passes
        the deduplicated merged member list as ``rows_a`` and ``rows_b``
        is ignored — but we tolerate either pattern by iterating both.
      column_facts_a / column_facts_b: profile facts per column name, used
        for semantic bucketing.
      normalizer: the saved config's Normalizer.
      golden_overrides: {column_a: chosen_raw_value} for every column the
        user has saved a pick on. Values may be None (user explicitly
        chose "no value").
      golden_explicit_columns: which column_a names have an override at
        all — distinguishes "no override saved" from "override saved as
        None". Required because dict values of None are ambiguous.
    """
    if not mappings:
        raise ValueError("Tree builder requires at least one mapping")

    root_mapping = _root_mapping(mappings)
    if root_mapping is None:
        raise ValueError(
            "Tree builder requires at least one important mapping; "
            "the similarity engine's importance gate should have already "
            "prevented runs that violate this."
        )

    # ---- Build a leaf for every mapping ----
    leaves_by_mapping: dict[int, TreeLeaf] = {}
    for m in mappings:
        # Pull raw values for this column-pair from both sheets' members.
        # An A-only mapping (column_b missing from rows_b) and vice versa
        # both just contribute fewer raw values; we don't error here so
        # an in-flight schema drift is tolerated by the UI rather than 500ing.
        raw_values: list[Any] = []
        for r in rows_a:
            if m.column_a in r:
                raw_values.append(r[m.column_a])
        for r in rows_b:
            if m.column_b in r:
                raw_values.append(r[m.column_b])

        variants = _collect_variants(raw_values, normalizer)
        # Conflict iff >1 non-null normalized variants. The all-null case
        # is NOT a conflict — every member agrees that the cell is empty.
        non_null_variants = [v for v in variants if v.normalized is not None]
        is_conflict = len(non_null_variants) > 1
        auto = _auto_pick(variants)

        # Golden overlay: keyed on column_a (the persisted column_name).
        # In Master Record mode (US 3.8) the same cluster-wide override
        # is applied to every per-variant subtree's matching leaf — but
        # an override value picked for variant A may not appear in the
        # variant set of variant B's leaf (different members ⇒ different
        # variants). When that happens, the override doesn't apply to
        # THIS subtree's leaf and the leaf falls back to its own
        # auto-pick. For the regular (single-tree) case, the override
        # always matches because the user picked from the full variant
        # set, so this fallback is a no-op there.
        explicit = m.column_a in golden_explicit_columns
        if explicit:
            override = golden_overrides.get(m.column_a)
            if _override_applies(override, variants):
                chosen = override
                chosen_is_explicit = True
            else:
                chosen = auto
                chosen_is_explicit = False
        else:
            chosen = auto
            chosen_is_explicit = False

        # Bucket: tier 1 important goes into "Important"; everyone else
        # gets a semantic bucket. The root itself isn't placed in any
        # group — it's the root.
        if m.id == root_mapping.id:
            bucket: Bucket = "Important"  # not actually rendered as a group
        elif m.is_important:
            bucket = "Important"
        else:
            bucket = _combined_bucket(
                column_facts_a.get(m.column_a),
                column_facts_b.get(m.column_b),
            )

        leaf = TreeLeaf(
            column_a=m.column_a,
            column_b=m.column_b,
            display_name=_display_name(m),
            bucket=bucket,
            is_important=m.is_important,
            weight=m.weight,
            is_conflict=is_conflict,
            variants=variants,
            auto_pick=auto,
            chosen=chosen,
            chosen_is_explicit=chosen_is_explicit,
        )
        leaves_by_mapping[m.id] = leaf

    root_leaf = leaves_by_mapping[root_mapping.id]

    # ---- Group non-root leaves into bucketed tiers ----
    grouped: dict[Bucket, list[TreeLeaf]] = {b: [] for b in BUCKET_ORDER}
    for mid, leaf in leaves_by_mapping.items():
        if mid == root_mapping.id:
            continue
        grouped[leaf.bucket].append(leaf)

    # Within each bucket: weight desc, then display_name asc. Deterministic.
    for bucket in grouped:
        grouped[bucket].sort(key=lambda l: (-l.weight, l.display_name))

    groups: list[TreeGroup] = []
    for bucket in BUCKET_ORDER:
        leaves = grouped[bucket]
        if not leaves:
            continue
        groups.append(TreeGroup(bucket=bucket, leaves=leaves))

    # ---- Conflict accounting ----
    all_leaves = [root_leaf, *(l for g in groups for l in g.leaves)]
    conflict_count = sum(1 for l in all_leaves if l.is_conflict)
    resolved_count = sum(
        1 for l in all_leaves if l.is_conflict and l.chosen_is_explicit
    )

    return ClusterTree(
        cluster_fingerprint=cluster_fingerprint,
        root_column_a=root_leaf.column_a,
        root_column_b=root_leaf.column_b,
        root_display_name=root_leaf.display_name,
        root_value=root_leaf.chosen,
        root_is_conflict=root_leaf.is_conflict,
        root_variants=root_leaf.variants,
        root_chosen_is_explicit=root_leaf.chosen_is_explicit,
        groups=groups,
        conflict_count=conflict_count,
        resolved_conflict_count=resolved_count,
    )


# ---------------------------------------------------------------------------
# Validation helper used by PUT /golden
# ---------------------------------------------------------------------------


def variant_raws(variants: list[TreeVariant]) -> set[str | None]:
    """All raw values present in a leaf's variants (including the
    non-canonical ``raw_examples`` and the null variant). The PUT
    endpoint validates the user's pick against this set so we never
    persist a value the user couldn't actually have seen."""
    out: set[str | None] = set()
    for v in variants:
        if v.raw is None and v.normalized is None:
            out.add(None)
        else:
            out.add(v.raw)
            out.update(v.raw_examples)
    return out


# ---------------------------------------------------------------------------
# US 3.8 — Master Record + per-variant subtrees
# ---------------------------------------------------------------------------


def _master_record_tag(root_column_a: str) -> str:
    """Spec's literal template: ``<{column}-Parent>``."""
    return f"<{root_column_a}-Parent>"


def _filter_rows_by_root_variant(
    rows: list[dict[str, Any]],
    root_column: str,
    variant_raw: str,
    normalizer: Normalizer,
) -> list[dict[str, Any]]:
    """Keep only rows whose ``root_column`` cell normalizes to the same
    key as ``variant_raw``.

    Done in normalized space so the slice respects the saved
    normalization rules (e.g., "Acme Robotics Inc" and "ACME ROBOTICS"
    fall into the same variant when strip_corporate_suffix + case_fold
    are enabled). A row whose root cell is missing or null is excluded
    from every variant's slice — it doesn't contribute to ANY subtree.
    """
    target_key = normalizer.apply(variant_raw)
    if target_key is None:
        # The variant_raw itself normalizes to "nothing meaningful"
        # — no row can match, so the slice is empty (better than
        # accidentally matching every null-keyed row).
        return []
    out: list[dict[str, Any]] = []
    for r in rows:
        if root_column not in r:
            continue
        if normalizer.apply(r[root_column]) == target_key:
            out.append(r)
    return out


def build_master_record(
    *,
    cluster_fingerprint: str,
    kept_variants: list[str],
    mappings: list[TreeMapping],
    rows_a: list[dict[str, Any]],
    rows_b: list[dict[str, Any]],
    column_facts_a: dict[str, ColumnFacts],
    column_facts_b: dict[str, ColumnFacts],
    normalizer: Normalizer,
    golden_overrides: dict[str, str | list[str] | None],
    golden_explicit_columns: set[str],
) -> MasterRecord:
    """Build the Master Record + N per-variant subtrees.

    Each subtree is the result of calling ``build_cluster_tree`` on the
    subset of cluster rows whose root cell normalizes to that variant.
    Picks are CLUSTER-WIDE (the same ``golden_overrides`` are passed to
    every subtree); a subtree whose leaf doesn't contain the picked
    value falls back to its own auto-pick via ``_override_applies``.
    """
    root = _root_mapping(mappings)
    if root is None:
        raise ValueError(
            "Master record requires at least one important mapping."
        )
    if not kept_variants:
        raise ValueError(
            "Master record requires at least one kept variant; "
            "the caller should not invoke this path when the root pick "
            "is not a non-empty list."
        )

    subtrees: list[MasterRecordSubtree] = []
    for variant in kept_variants:
        slice_a = _filter_rows_by_root_variant(
            rows_a, root.column_a, variant, normalizer
        )
        slice_b = _filter_rows_by_root_variant(
            rows_b, root.column_b, variant, normalizer
        )
        subtree = build_cluster_tree(
            cluster_fingerprint=cluster_fingerprint,
            mappings=mappings,
            rows_a=slice_a,
            rows_b=slice_b,
            column_facts_a=column_facts_a,
            column_facts_b=column_facts_b,
            normalizer=normalizer,
            golden_overrides=golden_overrides,
            golden_explicit_columns=golden_explicit_columns,
        )
        subtrees.append(MasterRecordSubtree(variant_raw=variant, subtree=subtree))

    return MasterRecord(
        tag=_master_record_tag(root.column_a),
        root_column_a=root.column_a,
        subtrees=subtrees,
    )
