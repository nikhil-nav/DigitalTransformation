"""Per-column similarity algorithms for Epic 3 (US 3.4).

Each ``score_*`` function returns a float in [0.0, 1.0] where 1.0 is an
exact match and 0.0 is no match. All functions:

- accept ``None`` or empty inputs and return 0.0 rather than raising
- are symmetric: ``score(a, b) == score(b, a)``
- assume the inputs have already been normalized by the caller when
  applicable (the caller composes ``Normalizer.apply`` + parser, then calls
  the algorithm)
- never modify their inputs

The ``ALGORITHMS`` registry is the source of truth for which algorithms
are available; the SQLAlchemy CHECK constraint on
``DataQualityColumnMapping.algorithm`` mirrors this list.
"""
from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from datetime import date
from math import sqrt
from typing import Any, Callable

import jellyfish
from rapidfuzz.distance import JaroWinkler, Levenshtein

from app.data_quality.parsers import parse_date_iso

SIMILARITY_VERSION = "1.0.0"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _both_present(a: Any, b: Any) -> bool:
    """Both inputs are non-empty strings (or coercible to non-empty)."""
    if a is None or b is None:
        return False
    sa, sb = str(a), str(b)
    return sa != "" and sb != ""


def _tokens(value: str) -> list[str]:
    return [t for t in value.split() if t]


def _ngrams(value: str, n: int) -> list[str]:
    if n <= 0 or len(value) < n:
        return [value] if value else []
    return [value[i : i + n] for i in range(len(value) - n + 1)]


# ---------------------------------------------------------------------------
# Algorithms
# ---------------------------------------------------------------------------


def score_exact(a: Any, b: Any) -> float:
    """1.0 iff inputs are byte-identical (after coercion to ``str``),
    else 0.0. Use after normalization/parsing for "same canonical form"
    semantics; use without normalization for strict case/whitespace match.
    """
    if not _both_present(a, b):
        return 0.0
    return 1.0 if str(a) == str(b) else 0.0


def score_levenshtein(a: Any, b: Any) -> float:
    """Normalized Levenshtein similarity: ``1 - lev(a,b) / max(len(a),len(b))``.

    Sensitive to per-character substitutions, insertions, deletions. Best
    for short strings (names, codes) of comparable length.
    """
    if not _both_present(a, b):
        return 0.0
    return float(Levenshtein.normalized_similarity(str(a), str(b)))


def score_jaro_winkler(a: Any, b: Any) -> float:
    """Jaro-Winkler similarity. Boosts the score when the inputs share a
    common prefix; useful for personal/company names where the start of
    the string is more informative than the tail."""
    if not _both_present(a, b):
        return 0.0
    return float(JaroWinkler.normalized_similarity(str(a), str(b)))


def score_jaccard_tokens(a: Any, b: Any) -> float:
    """Jaccard similarity over whitespace-split tokens.

    |A ∩ B| / |A ∪ B|. Good for short multi-word strings (company names,
    addresses) where the SET of tokens matters more than their order or
    repetition.
    """
    if not _both_present(a, b):
        return 0.0
    ta, tb = set(_tokens(str(a))), set(_tokens(str(b)))
    if not ta and not tb:
        return 0.0
    inter = len(ta & tb)
    union = len(ta | tb)
    if union == 0:
        return 0.0
    return inter / union


def score_cosine_tokens(a: Any, b: Any) -> float:
    """Cosine similarity on token-frequency vectors.

    Unlike Jaccard, this accounts for repeated tokens (so "the the cat"
    vs "the cat" is below 1.0). Better than Jaccard for longer free-text
    fields like descriptions or notes.
    """
    if not _both_present(a, b):
        return 0.0
    ca, cb = Counter(_tokens(str(a))), Counter(_tokens(str(b)))
    if not ca or not cb:
        return 0.0
    shared = set(ca) & set(cb)
    dot = sum(ca[t] * cb[t] for t in shared)
    norm_a = sqrt(sum(v * v for v in ca.values()))
    norm_b = sqrt(sum(v * v for v in cb.values()))
    if norm_a == 0 or norm_b == 0:
        return 0.0
    return dot / (norm_a * norm_b)


def score_soundex(a: Any, b: Any) -> float:
    """1.0 iff the inputs produce the same Soundex code, else 0.0.

    Soundex collapses words to a 4-character phonetic code (1 letter +
    3 digits). It is an English-language algorithm with known limits on
    other languages; use only on English-language name columns.
    """
    if not _both_present(a, b):
        return 0.0
    # Soundex requires a leading letter; bail if the input has none.
    sa, sb = str(a).strip(), str(b).strip()
    if not sa or not sb or not sa[0].isalpha() or not sb[0].isalpha():
        return 0.0
    return 1.0 if jellyfish.soundex(sa) == jellyfish.soundex(sb) else 0.0


def score_metaphone(a: Any, b: Any) -> float:
    """1.0 iff the inputs produce the same Metaphone code, else 0.0.

    Metaphone is a more accurate English-language phonetic algorithm
    than Soundex; output is a variable-length code.
    """
    if not _both_present(a, b):
        return 0.0
    sa, sb = str(a).strip(), str(b).strip()
    if not sa or not sb:
        return 0.0
    ma, mb = jellyfish.metaphone(sa), jellyfish.metaphone(sb)
    # Both empty codes (e.g. for pure-numeric strings) is not a match —
    # phonetic comparison is undefined for those inputs.
    if not ma or not mb:
        return 0.0
    return 1.0 if ma == mb else 0.0


def score_ngram(a: Any, b: Any, n: int = 3) -> float:
    """Dice coefficient over character n-grams: ``2|A∩B| / (|A|+|B|)``.

    Robust to small typos and word-order changes. Default n=3 (trigrams)
    is a common compromise between sensitivity and noise.
    """
    if not _both_present(a, b):
        return 0.0
    ga, gb = _ngrams(str(a), n), _ngrams(str(b), n)
    if not ga or not gb:
        return 0.0
    ca, cb = Counter(ga), Counter(gb)
    intersection_count = sum((ca & cb).values())
    total = len(ga) + len(gb)
    if total == 0:
        return 0.0
    return (2 * intersection_count) / total


def score_numeric_tolerance(
    a: Any,
    b: Any,
    *,
    abs_tol: float = 0.01,
    rel_tol: float = 0.05,
) -> float:
    """Linear-falloff score combining absolute and relative tolerance.

    ``window = abs_tol + rel_tol * max(|a|, |b|)``. Score is
    ``max(0, 1 - |a-b| / window)`` so identical values score 1.0 and
    values whose difference exceeds the window score 0.0.

    Inputs are parsed to ``float``; failures return 0.0 (no match) rather
    than raising — the caller is told the pair is dissimilar, not given
    an exception to handle mid-clustering.
    """
    if not _both_present(a, b):
        return 0.0
    try:
        x = float(str(a))
        y = float(str(b))
    except (TypeError, ValueError):
        return 0.0
    diff = abs(x - y)
    window = abs_tol + rel_tol * max(abs(x), abs(y))
    if window == 0.0:
        return 1.0 if diff == 0.0 else 0.0
    return max(0.0, 1.0 - diff / window)


def score_date_proximity(
    a: Any,
    b: Any,
    *,
    days_tolerance: int = 7,
) -> float:
    """Score dates by absolute day difference under a linear falloff.

    0 days apart -> 1.0; ``days_tolerance`` days apart -> 0.0; beyond
    ``days_tolerance`` -> 0.0. Inputs are parsed via ``parse_date_iso``
    (STRICT, absolute-time only); unparseable inputs score 0.0.
    """
    if not _both_present(a, b) or days_tolerance <= 0:
        return 0.0
    ra = parse_date_iso(a)
    rb = parse_date_iso(b)
    if not ra.ok or not rb.ok:
        return 0.0
    try:
        da = date.fromisoformat(ra.value)
        db = date.fromisoformat(rb.value)
    except ValueError:
        return 0.0
    diff_days = abs((da - db).days)
    if diff_days >= days_tolerance:
        return 0.0
    return 1.0 - (diff_days / days_tolerance)


# ---------------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class AlgorithmDef:
    """Metadata + scoring function for one algorithm.

    ``valid_for`` is the set of column semantic types the algorithm is
    designed for. The recommender uses it to filter candidates; the UI
    uses it to grey-out incompatible choices."""

    name: str
    score: Callable[..., float]
    valid_for: frozenset[str]
    label: str
    description: str


ALGORITHMS: dict[str, AlgorithmDef] = {
    "exact": AlgorithmDef(
        name="exact",
        score=score_exact,
        valid_for=frozenset({"boolean", "integer", "float", "date", "string", "mixed"}),
        label="Exact match",
        description="Bit-identical comparison after normalization. Use for IDs, codes, normalised emails/phones.",
    ),
    "levenshtein": AlgorithmDef(
        name="levenshtein",
        score=score_levenshtein,
        valid_for=frozenset({"string", "mixed"}),
        label="Edit distance (Levenshtein)",
        description="Normalised character edit distance; sensitive to per-character typos.",
    ),
    "jaro_winkler": AlgorithmDef(
        name="jaro_winkler",
        score=score_jaro_winkler,
        valid_for=frozenset({"string", "mixed"}),
        label="Jaro-Winkler",
        description="Edit-distance variant that rewards shared prefixes; good for names.",
    ),
    "jaccard_tokens": AlgorithmDef(
        name="jaccard_tokens",
        score=score_jaccard_tokens,
        valid_for=frozenset({"string", "mixed"}),
        label="Token Jaccard",
        description="Whitespace-token set similarity. Use for company names, addresses.",
    ),
    "cosine_tokens": AlgorithmDef(
        name="cosine_tokens",
        score=score_cosine_tokens,
        valid_for=frozenset({"string", "mixed"}),
        label="Token cosine",
        description="Token-frequency vector cosine. Use for longer free-text fields.",
    ),
    "soundex": AlgorithmDef(
        name="soundex",
        score=score_soundex,
        valid_for=frozenset({"string", "mixed"}),
        label="Soundex",
        description="English-language phonetic exact match. Use for personal names.",
    ),
    "metaphone": AlgorithmDef(
        name="metaphone",
        score=score_metaphone,
        valid_for=frozenset({"string", "mixed"}),
        label="Metaphone",
        description="More accurate English phonetic match than Soundex.",
    ),
    "ngram": AlgorithmDef(
        name="ngram",
        score=score_ngram,
        valid_for=frozenset({"string", "mixed"}),
        label="Character n-gram",
        description="Dice coefficient on character trigrams. Robust to typos and word-order.",
    ),
    "numeric_tolerance": AlgorithmDef(
        name="numeric_tolerance",
        score=score_numeric_tolerance,
        valid_for=frozenset({"integer", "float"}),
        label="Numeric tolerance",
        description="Linear falloff combining absolute + relative tolerance.",
    ),
    "date_proximity": AlgorithmDef(
        name="date_proximity",
        score=score_date_proximity,
        valid_for=frozenset({"date", "string", "mixed"}),
        label="Date proximity",
        description="Linear falloff on day-difference; identical dates score 1.0.",
    ),
}


def get_algorithm(name: str) -> AlgorithmDef:
    """Look up an algorithm by name; raise ``ValueError`` with a useful
    message if unknown. The cluster engine calls this once per mapping
    before the scoring loop, so an invalid algorithm fails fast."""
    if name not in ALGORITHMS:
        raise ValueError(
            f"Unknown similarity algorithm: {name!r}. "
            f"Valid: {sorted(ALGORITHMS.keys())}"
        )
    return ALGORITHMS[name]
