"""Rule-based recommender for Epic 3 (US 3.4).

Maps a column-pair to a similarity algorithm + parser + normalization
toggles based on column semantic type, pattern label, and length stats.
Deterministic, no AI: the same input always produces the same output, so
re-running the recommender after a re-profile yields a stable config the
user can trust.

The LLM "Improve with AI" path (deferred to Part 4) reuses the same
return types so the UI can present both heuristic and AI suggestions
through one widget. The recommender output is annotated with
``recommended_by='heuristic'``; the LLM path sets it to ``'llm'``.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Iterable

from app.data_quality.pipeline.normalize import (
    RULE_CASE_FOLD,
    RULE_COLLAPSE_WHITESPACE,
    RULE_EXPAND_ADDRESS,
    RULE_NFKD_FOLD,
    RULE_STRIP_CORP_SUFFIX,
    RULE_STRIP_PUNCTUATION,
    RULE_STRIP_SPECIAL,
)


# ---------------------------------------------------------------------------
# Inputs / outputs (DB-agnostic so the recommender is unit-testable without
# a session). Callers convert from SQLAlchemy rows.
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ColumnFacts:
    """The subset of column-profile information the recommender needs.

    Builders that load from the DB should populate these from the
    DataQualityColumnProfile row + sheet name. The recommender intentionally
    does not see raw cell values — recommendations must be reproducible
    from profile metadata alone."""

    name: str
    semantic_type: str  # boolean, integer, float, date, string, mixed, empty
    pattern_label: str | None = None
    avg_value_length: float | None = None
    distinct_pct: float = 100.0


@dataclass(frozen=True)
class RecommendedMapping:
    """Heuristic (or LLM) suggestion for one A.col ↔ B.col mapping."""

    column_a: str
    column_b: str
    algorithm: str
    parser: str | None
    weight: float
    is_important: bool
    recommended_by: str = "heuristic"  # one of 'heuristic'|'llm'|'user'


@dataclass(frozen=True)
class RecommendedConfig:
    """Top-level heuristic suggestion for a (sheet_a, sheet_b) pair."""

    normalization: dict[str, bool]
    mappings: list[RecommendedMapping] = field(default_factory=list)
    threshold: float = 0.85


# ---------------------------------------------------------------------------
# Per-column algorithm recommendation
# ---------------------------------------------------------------------------


# Column-name hints that flip a generic 'string' into a more specific
# decision. Order matters: first-match wins. Compare against the
# lower-cased column name with non-alphanumeric chars replaced by space.
_NAME_HINTS_ADDRESS = ("address", "street", "addr", "city", "state", "zip", "postal")
_NAME_HINTS_NAME = ("name", "company", "customer", "client", "vendor", "supplier", "account")
_NAME_HINTS_DESCRIPTION = ("description", "notes", "remarks", "comment", "summary", "details")
_NAME_HINTS_PHONE = ("phone", "mobile", "tel", "fax")
_NAME_HINTS_EMAIL = ("email", "mail")
_NAME_HINTS_ID = ("id", "code", "sku", "ref", "number")


def _norm_name(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", value.lower()).strip()


def _name_has(name: str, needles: Iterable[str]) -> bool:
    tokens = set(_norm_name(name).split())
    return any(n in tokens for n in needles)


def recommend_algorithm(a: ColumnFacts, b: ColumnFacts) -> tuple[str, str | None]:
    """Choose ``(algorithm, parser)`` for a column-pair.

    Decision tree, in precedence order:
    1. **Patterned strings** (email/phone/date detected by Part-1 profile)
       use ``exact`` after a matching parser, so "JAMES.CARTER@..." and
       "james.carter@..." map to the same canonical key.
    2. **Both date** semantic columns use ``date_proximity`` with the
       date parser.
    3. **Both numeric** use ``numeric_tolerance``.
    4. **String + name hint** → ``jaro_winkler`` (rewards shared prefix).
    5. **String + address hint** → ``jaccard_tokens`` (set of tokens
       matters more than order; numbers can move).
    6. **String + description/long-text** → ``cosine_tokens``.
    7. **String + ID/code hint** → ``exact``.
    8. **Anything else** → ``levenshtein`` for short strings,
       ``jaccard_tokens`` for long ones, ``exact`` for mismatched types.

    Returns ``(algorithm, parser)`` where parser is ``None`` for
    algorithms that don't need a field-specific parser.
    """
    # --- patterned strings ---
    if a.pattern_label and a.pattern_label == b.pattern_label:
        pat = a.pattern_label
        if pat == "email":
            return ("exact", "email")
        if pat == "e164_phone":
            return ("exact", "phone")
        if pat == "iso_date":
            return ("date_proximity", "date")
        if pat == "uuid":
            return ("exact", None)

    # --- both date ---
    if a.semantic_type == "date" and b.semantic_type == "date":
        return ("date_proximity", "date")

    # --- both numeric ---
    numeric_types = {"integer", "float"}
    if a.semantic_type in numeric_types and b.semantic_type in numeric_types:
        return ("numeric_tolerance", None)

    # --- mismatched types: safest fallback is exact ---
    if a.semantic_type != b.semantic_type and not {a.semantic_type, b.semantic_type} <= {"string", "mixed"}:
        return ("exact", None)

    # --- string family ---
    combined_name = f"{a.name} {b.name}"

    if _name_has(combined_name, _NAME_HINTS_EMAIL):
        return ("exact", "email")
    if _name_has(combined_name, _NAME_HINTS_PHONE):
        return ("exact", "phone")
    if _name_has(combined_name, _NAME_HINTS_ID):
        return ("exact", None)
    if _name_has(combined_name, _NAME_HINTS_NAME):
        return ("jaro_winkler", None)
    if _name_has(combined_name, _NAME_HINTS_ADDRESS):
        return ("jaccard_tokens", None)
    if _name_has(combined_name, _NAME_HINTS_DESCRIPTION):
        return ("cosine_tokens", None)

    # --- length-based fallback ---
    avg_len = max(a.avg_value_length or 0.0, b.avg_value_length or 0.0)
    if avg_len >= 60:
        return ("jaccard_tokens", None)
    return ("levenshtein", None)


def recommend_normalization(facts: Iterable[ColumnFacts]) -> dict[str, bool]:
    """Choose which normalization toggles to default-on for a sheet pair.

    Universal defaults: case fold, whitespace collapse, NFKD/accent fold,
    special-character strip. Optional defaults are switched on when at
    least one column's name suggests the rule is helpful:

    - any column looks address-like → ``expand_address_abbrev``
    - any column looks name-like → ``strip_corporate_suffix`` +
      ``strip_punctuation``
    """
    cols = list(facts)
    base: dict[str, bool] = {
        RULE_CASE_FOLD: True,
        RULE_COLLAPSE_WHITESPACE: True,
        RULE_NFKD_FOLD: True,
        RULE_STRIP_SPECIAL: True,
        RULE_STRIP_PUNCTUATION: False,
        RULE_STRIP_CORP_SUFFIX: False,
        RULE_EXPAND_ADDRESS: False,
    }
    if any(_name_has(c.name, _NAME_HINTS_ADDRESS) for c in cols):
        base[RULE_EXPAND_ADDRESS] = True
    if any(_name_has(c.name, _NAME_HINTS_NAME) for c in cols):
        base[RULE_STRIP_CORP_SUFFIX] = True
        base[RULE_STRIP_PUNCTUATION] = True
    return base


# ---------------------------------------------------------------------------
# Cross-sheet column pairing
# ---------------------------------------------------------------------------


def _name_jaccard(a: str, b: str) -> float:
    ta = set(_norm_name(a).split())
    tb = set(_norm_name(b).split())
    if not ta or not tb:
        return 0.0
    return len(ta & tb) / len(ta | tb)


def _types_compatible(a: ColumnFacts, b: ColumnFacts) -> bool:
    # Numeric-numeric, date-date, string-string (string and mixed grouped).
    numeric = {"integer", "float"}
    text = {"string", "mixed"}
    if a.semantic_type in numeric and b.semantic_type in numeric:
        return True
    if a.semantic_type == "date" and b.semantic_type == "date":
        return True
    if a.semantic_type in text and b.semantic_type in text:
        return True
    if a.semantic_type == b.semantic_type:
        return True
    return False


def recommend_mappings(
    columns_a: list[ColumnFacts],
    columns_b: list[ColumnFacts],
    *,
    name_similarity_threshold: float = 0.3,
) -> list[RecommendedMapping]:
    """Pair columns between two sheets by name similarity + type
    compatibility, then call ``recommend_algorithm`` per pair.

    Pairing is greedy: rank all candidate pairs by name similarity
    descending, then assign each A.col / B.col at most once (a single
    A column does not map to multiple B columns and vice versa). This
    avoids ambiguous duplicate mappings without requiring the optimiser
    overhead of a true assignment algorithm.

    Pairs whose name similarity falls below ``name_similarity_threshold``
    are excluded. Default 0.3 catches pairs like "customer_email" /
    "lead_email" (one shared token out of three union tokens) which are
    the common real-world case for cross-sheet mappings. Type-incompatible
    pairs (e.g. text on one side, numeric on the other) are also excluded —
    the user can add a manual mapping if they really want one.
    """
    candidates: list[tuple[float, ColumnFacts, ColumnFacts]] = []
    for ca in columns_a:
        for cb in columns_b:
            if not _types_compatible(ca, cb):
                continue
            sim = _name_jaccard(ca.name, cb.name)
            if sim < name_similarity_threshold:
                continue
            candidates.append((sim, ca, cb))
    candidates.sort(key=lambda x: x[0], reverse=True)

    used_a: set[str] = set()
    used_b: set[str] = set()
    out: list[RecommendedMapping] = []
    for _sim, ca, cb in candidates:
        if ca.name in used_a or cb.name in used_b:
            continue
        used_a.add(ca.name)
        used_b.add(cb.name)
        algorithm, parser = recommend_algorithm(ca, cb)
        out.append(
            RecommendedMapping(
                column_a=ca.name,
                column_b=cb.name,
                algorithm=algorithm,
                parser=parser,
                weight=1.0,
                is_important=False,
                recommended_by="heuristic",
            )
        )
    return out


def recommend_config(
    columns_a: list[ColumnFacts],
    columns_b: list[ColumnFacts],
    *,
    threshold: float = 0.85,
) -> RecommendedConfig:
    """One-shot recommender used by the config page on first load.

    The user is expected to review and adjust — particularly the
    ``is_important`` flags, which the recommender deliberately leaves
    all-False. Importance is a user-driven precision decision: marking a
    column as important hard-gates cluster formation on its score, so
    the system should never set it without explicit user intent.
    """
    mappings = recommend_mappings(columns_a, columns_b)
    norm = recommend_normalization(columns_a + columns_b)
    return RecommendedConfig(
        normalization=norm,
        mappings=mappings,
        threshold=threshold,
    )
