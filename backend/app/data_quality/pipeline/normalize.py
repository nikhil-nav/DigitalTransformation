"""Reversible normalization rules for Epic 3 record-level similarity.

Each rule is a pure function operating on a string. Rules never mutate the
raw cell value persisted in the database; they produce a *comparison key*
used by the similarity engine. The displayed value to the user is always
the original.

Design notes (precision first):
- Order matters. The composed pipeline always runs in the same fixed order
  regardless of toggle order so that equivalent rule-sets produce
  byte-identical keys.
- Rules are idempotent: applying any combination twice yields the same
  output as applying it once (verified by hypothesis test).
- Non-string inputs are coerced to ``str(value)`` so the engine can compare
  numbers/booleans by representation when configured to.
- ``None`` / NaN / empty string short-circuit to ``None`` so callers can
  detect "nothing to compare" without sprinkling truthiness checks.
"""
from __future__ import annotations

import re
import unicodedata
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from typing import Any

import pandas as pd
from unidecode import unidecode

NORMALIZE_VERSION = "1.0.0"

# ---------------------------------------------------------------------------
# Rule catalogue. Keys are the canonical rule identifiers persisted on the
# DataQualityProfileConfig.normalization_json blob. The frontend uses the
# same identifiers when rendering toggles, so renaming is a breaking change.
# ---------------------------------------------------------------------------
RULE_CASE_FOLD = "case_fold"
RULE_COLLAPSE_WHITESPACE = "collapse_whitespace"
RULE_STRIP_PUNCTUATION = "strip_punctuation"
RULE_NFKD_FOLD = "nfkd_fold"
RULE_STRIP_SPECIAL = "strip_special_chars"
RULE_STRIP_CORP_SUFFIX = "strip_corporate_suffix"
RULE_EXPAND_ADDRESS = "expand_address_abbrev"

# Authoritative, ordered list. The Normalizer always applies rules in this
# order regardless of how the toggles arrive from the UI.
ALL_RULES: tuple[str, ...] = (
    RULE_NFKD_FOLD,           # before case-fold so unicode case-folds correctly
    RULE_STRIP_SPECIAL,       # remove zero-width / emoji / control chars
    RULE_EXPAND_ADDRESS,      # BEFORE case_fold: its replacement table values are
                              # capitalised English; running case_fold afterwards
                              # makes the pipeline idempotent (re-running it on
                              # the already-folded output is a no-op).
    RULE_CASE_FOLD,
    RULE_STRIP_PUNCTUATION,
    RULE_STRIP_CORP_SUFFIX,
    RULE_COLLAPSE_WHITESPACE, # always last — earlier rules may insert whitespace
)


# ---------------------------------------------------------------------------
# Individual rules
# ---------------------------------------------------------------------------


def case_fold(value: str) -> str:
    """Unicode-aware lowercase. ``"".casefold()`` handles e.g. German ß."""
    return value.casefold()


_WHITESPACE_RE = re.compile(r"\s+")


def collapse_whitespace(value: str) -> str:
    """Trim edges and collapse internal whitespace runs to a single space."""
    return _WHITESPACE_RE.sub(" ", value).strip()


# Curated punctuation set. We deliberately keep '+' (phone), '@' (email),
# and '.' (numeric decimals/abbreviations) so this rule does not interact
# destructively with field-specific parsers.
_PUNCT_RE = re.compile(r"[,;:!?\"'`()\[\]{}<>/\\|_*~^]")


def strip_punctuation(value: str) -> str:
    """Strip standardisable punctuation. Replaces with single space so
    "Acme,Inc" → "Acme Inc" rather than "AcmeInc"."""
    return _PUNCT_RE.sub(" ", value)


def nfkd_fold(value: str) -> str:
    """NFKD decompose, then drop combining marks. Folds "Café" → "Cafe".

    NFKD also normalises ligatures and compatibility-equivalent forms (e.g.
    "ﬁ" → "fi"), which is important for OCR'd data. We additionally run
    ``unidecode`` to fold characters that NFKD alone cannot (e.g. "ß", "Ø")
    so the comparison key is reliably ASCII-safe."""
    decomposed = unicodedata.normalize("NFKD", value)
    no_marks = "".join(c for c in decomposed if not unicodedata.combining(c))
    return unidecode(no_marks)


# Control chars (Cc), format chars (Cf, includes zero-width joiners / BOM),
# private-use (Co), unassigned (Cn), surrogate halves (Cs). Symbols (S*) are
# also stripped so emojis/maths symbols don't pollute the key.
_STRIP_SPECIAL_CATEGORIES = {"Cc", "Cf", "Co", "Cn", "Cs", "So", "Sk"}


def strip_special_chars(value: str) -> str:
    """Drop emojis, control chars, zero-width spaces, private-use glyphs."""
    return "".join(
        c for c in value if unicodedata.category(c) not in _STRIP_SPECIAL_CATEGORIES
    )


# Common corporate / legal-entity suffixes. We match as whole-word tokens
# (case-insensitive, possibly trailing dot) at the END of the string only;
# stripping interior occurrences risks mutilating names like "LLC Holdings".
_CORP_SUFFIXES = (
    "inc",
    "incorporated",
    "llc",
    "l.l.c",
    "ltd",
    "limited",
    "co",
    "company",
    "corp",
    "corporation",
    "plc",
    "gmbh",
    "ag",
    "sa",
    "s.a",
    "nv",
    "n.v",
    "pty",
    "bv",
    "b.v",
)
_CORP_SUFFIX_RE = re.compile(
    r"(?:[\s,]+(?:" + "|".join(re.escape(s) for s in _CORP_SUFFIXES) + r")\.?)+\s*$",
    flags=re.IGNORECASE,
)


def strip_corporate_suffix(value: str) -> str:
    """Trim trailing legal-entity suffixes. Repeats the match so chains
    like "Acme Robotics Inc LLC" reduce to "Acme Robotics"."""
    return _CORP_SUFFIX_RE.sub("", value)


# Address abbreviation table. Conservative — only common US postal
# abbreviations and cardinal directions. We expand BOTH dotted and
# undotted forms so "St." and "St" both expand to "Street".
_ADDRESS_EXPANSIONS = {
    "st": "Street",
    "ave": "Avenue",
    "av": "Avenue",
    "blvd": "Boulevard",
    "rd": "Road",
    "dr": "Drive",
    "ln": "Lane",
    "ct": "Court",
    "pl": "Place",
    "sq": "Square",
    "ter": "Terrace",
    "pkwy": "Parkway",
    "hwy": "Highway",
    "n": "North",
    "s": "South",
    "e": "East",
    "w": "West",
    "ne": "Northeast",
    "nw": "Northwest",
    "se": "Southeast",
    "sw": "Southwest",
    "fl": "Floor",
    "ste": "Suite",
    "apt": "Apartment",
}
# Match a word and (optionally) a trailing dot when followed by whitespace
# or end-of-string. The closing lookahead is required because a default
# `\b` would not match between "." and end-of-string (both non-word), so a
# trailing dot would otherwise be left behind after the substitution.
_ADDRESS_TOKEN_RE = re.compile(r"\b([A-Za-z]+)(?:\.(?=\s|$))?")


def expand_address_abbrev(value: str) -> str:
    """Expand common US postal abbreviations as whole tokens.

    Also expands "St" → "Saint" when it appears immediately before a capitalised
    word (e.g. "St Clair"), distinguishing saint-prefix from "Street" suffix.
    """
    def _replace(match: re.Match[str]) -> str:
        word = match.group(1)
        # Special case: "St Clair" / "St. Clair" → "Saint Clair"
        # Detected by upper-case word immediately following.
        if word.lower() == "st":
            suffix_pos = match.end()
            rest = value[suffix_pos:].lstrip()
            if rest and rest[0].isalpha() and rest[0].isupper():
                return "Saint"
        replacement = _ADDRESS_EXPANSIONS.get(word.lower())
        if replacement is None:
            return match.group(0)
        # Single-character abbreviations (e.g. "e", "n", "s", "w") are only
        # expanded when they appear in uppercase form in the original text —
        # real address abbreviations like "123 E Main St" use uppercase.
        # Lowercased single-letter tokens are too ambiguous and cause
        # non-idempotency when strip_punctuation has revealed them as new
        # word-boundary tokens after a prior pipeline pass.
        if len(word) == 1 and word.islower():
            return match.group(0)
        return replacement

    return _ADDRESS_TOKEN_RE.sub(_replace, value)


# ---------------------------------------------------------------------------
# Composed pipeline
# ---------------------------------------------------------------------------


_RULE_FUNCS: dict[str, Callable[[str], str]] = {
    RULE_CASE_FOLD: case_fold,
    RULE_COLLAPSE_WHITESPACE: collapse_whitespace,
    RULE_STRIP_PUNCTUATION: strip_punctuation,
    RULE_NFKD_FOLD: nfkd_fold,
    RULE_STRIP_SPECIAL: strip_special_chars,
    RULE_STRIP_CORP_SUFFIX: strip_corporate_suffix,
    RULE_EXPAND_ADDRESS: expand_address_abbrev,
}


def _is_nullish(value: Any) -> bool:
    if value is None:
        return True
    if isinstance(value, float):
        # NaN is the only float that is not equal to itself.
        if value != value:
            return True
    try:
        # pandas treats NaT / NA as null
        if pd.isna(value):
            return True
    except (TypeError, ValueError):
        pass
    return False


@dataclass(frozen=True)
class Normalizer:
    """Frozen pipeline of normalization rules, applied in canonical order.

    Construct via ``Normalizer.from_toggles({...})`` so unknown rule names
    fail loudly rather than silently dropping a toggle. Use ``apply(value)``
    to compute the comparison key for a raw cell value.
    """

    enabled: frozenset[str]

    @classmethod
    def from_toggles(cls, toggles: dict[str, bool] | None) -> "Normalizer":
        if not toggles:
            return cls(enabled=frozenset())
        unknown = set(toggles) - set(ALL_RULES)
        if unknown:
            raise ValueError(
                f"Unknown normalization rule(s): {sorted(unknown)}. "
                f"Valid: {list(ALL_RULES)}"
            )
        return cls(enabled=frozenset(k for k, v in toggles.items() if v))

    def apply(self, value: Any) -> str | None:
        """Return the comparison key, or None if value is nullish/empty."""
        if _is_nullish(value):
            return None
        s = str(value)
        if s == "":
            return None
        for rule in ALL_RULES:
            if rule in self.enabled:
                s = _RULE_FUNCS[rule](s)
        # An entirely-stripped value (e.g. "☕" with strip_special_chars on)
        # is meaningless to compare; surface as null.
        if s == "" or s.isspace():
            return None
        return s

    def apply_many(self, values: Iterable[Any]) -> list[str | None]:
        return [self.apply(v) for v in values]
