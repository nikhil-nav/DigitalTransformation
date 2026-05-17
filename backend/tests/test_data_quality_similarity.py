"""Tests for the per-column similarity algorithms.

Each algorithm is exercised against:
  - the identical-input case (must return 1.0)
  - a known-distance case (regression check with a hand-computed value)
  - the disjoint case (must return 0.0)
  - the null/empty case (must return 0.0, never raise)
  - the symmetry case (score(a,b) == score(b,a))
"""
from __future__ import annotations

from math import isclose

import pytest

from app.data_quality.similarity import (
    ALGORITHMS,
    AlgorithmDef,
    get_algorithm,
    score_cosine_tokens,
    score_date_proximity,
    score_exact,
    score_jaccard_tokens,
    score_jaro_winkler,
    score_levenshtein,
    score_metaphone,
    score_ngram,
    score_numeric_tolerance,
    score_soundex,
)


# ---------------------------------------------------------------------------
# exact
# ---------------------------------------------------------------------------


def test_exact_identical() -> None:
    assert score_exact("foo", "foo") == 1.0


def test_exact_different() -> None:
    assert score_exact("foo", "bar") == 0.0


def test_exact_case_sensitive() -> None:
    # Caller is expected to normalize beforehand if they want case-insensitive.
    assert score_exact("Foo", "foo") == 0.0


def test_exact_null_inputs() -> None:
    assert score_exact(None, "foo") == 0.0
    assert score_exact("foo", None) == 0.0
    assert score_exact(None, None) == 0.0
    assert score_exact("", "foo") == 0.0


# ---------------------------------------------------------------------------
# levenshtein
# ---------------------------------------------------------------------------


def test_levenshtein_kitten_sitting() -> None:
    # Classic example: 3 edits over 7 chars -> 1 - 3/7 = 0.5714
    s = score_levenshtein("kitten", "sitting")
    assert isclose(s, 1 - 3 / 7, abs_tol=1e-6)


def test_levenshtein_identical_is_one() -> None:
    assert score_levenshtein("hello", "hello") == 1.0


def test_levenshtein_disjoint_is_zero_ish() -> None:
    # No common characters -> normalized distance is 1.0 -> similarity 0.0
    assert score_levenshtein("abc", "xyz") == 0.0


def test_levenshtein_symmetric() -> None:
    a, b = "Acme Robotics", "Acme Robatics"
    assert score_levenshtein(a, b) == score_levenshtein(b, a)


# ---------------------------------------------------------------------------
# jaro_winkler
# ---------------------------------------------------------------------------


def test_jaro_winkler_classic_martha() -> None:
    # Famous Jaro-Winkler example
    s = score_jaro_winkler("MARTHA", "MARHTA")
    assert s > 0.95


def test_jaro_winkler_prefix_boost() -> None:
    # Same 3-char prefix earns the Winkler boost on top of Jaro.
    # We assert the score is materially above the disjoint-tail Jaro
    # baseline (~0.49 for these inputs).
    short = score_jaro_winkler("Jonathan", "Jonny")
    assert short > 0.6


# ---------------------------------------------------------------------------
# jaccard tokens
# ---------------------------------------------------------------------------


def test_jaccard_tokens_half_overlap() -> None:
    # {a,b,c} vs {b,c,d}: inter=2, union=4 -> 0.5
    assert score_jaccard_tokens("a b c", "b c d") == 0.5


def test_jaccard_tokens_full_overlap_with_repeats() -> None:
    # Set-based: repeats do not change the score
    assert score_jaccard_tokens("foo bar", "foo foo bar") == 1.0


def test_jaccard_tokens_disjoint_is_zero() -> None:
    assert score_jaccard_tokens("foo bar", "baz qux") == 0.0


# ---------------------------------------------------------------------------
# cosine tokens
# ---------------------------------------------------------------------------


def test_cosine_tokens_identical_freq_is_one() -> None:
    # Floating-point dot/sqrt rarely lands on an exact 1.0; allow tiny epsilon.
    assert isclose(score_cosine_tokens("foo bar", "foo bar"), 1.0, abs_tol=1e-9)


def test_cosine_tokens_repeat_distinguished_from_unique() -> None:
    # "the the cat" vs "the cat" should be below 1.0 (Jaccard would say 1.0)
    s = score_cosine_tokens("the the cat", "the cat")
    assert s < 1.0
    assert s > 0.8


def test_cosine_tokens_disjoint_is_zero() -> None:
    assert score_cosine_tokens("foo", "bar") == 0.0


# ---------------------------------------------------------------------------
# soundex
# ---------------------------------------------------------------------------


def test_soundex_robert_rupert_match() -> None:
    # Both encode to R163 in classical Soundex
    assert score_soundex("Robert", "Rupert") == 1.0


def test_soundex_clearly_different_names_dont_match() -> None:
    assert score_soundex("Robert", "Anderson") == 0.0


def test_soundex_handles_non_alpha_gracefully() -> None:
    # Numeric / empty / punctuation-only inputs return 0 without raising.
    assert score_soundex("123", "456") == 0.0
    assert score_soundex("", "Smith") == 0.0


# ---------------------------------------------------------------------------
# metaphone
# ---------------------------------------------------------------------------


def test_metaphone_smith_smyth_match() -> None:
    # Both encode to "SM0" under jellyfish's original Metaphone.
    assert score_metaphone("Smith", "Smyth") == 1.0


def test_metaphone_catherine_katherine_match() -> None:
    # Both encode to "K0RN".
    assert score_metaphone("Catherine", "Katherine") == 1.0


def test_metaphone_different_words_dont_match() -> None:
    assert score_metaphone("Smith", "Johnson") == 0.0


# ---------------------------------------------------------------------------
# n-gram
# ---------------------------------------------------------------------------


def test_ngram_dice_one_typo() -> None:
    # "abcd" trigrams: {abc, bcd}
    # "abce" trigrams: {abc, bce}
    # |∩| = 1, total = 4, Dice = 2*1/4 = 0.5
    assert score_ngram("abcd", "abce", n=3) == 0.5


def test_ngram_identical_is_one() -> None:
    assert score_ngram("hello world", "hello world", n=3) == 1.0


def test_ngram_disjoint_is_zero() -> None:
    assert score_ngram("aaa", "bbb", n=3) == 0.0


# ---------------------------------------------------------------------------
# numeric tolerance
# ---------------------------------------------------------------------------


def test_numeric_tolerance_identical_is_one() -> None:
    assert score_numeric_tolerance("100", "100") == 1.0


def test_numeric_tolerance_small_diff_is_near_one() -> None:
    s = score_numeric_tolerance("100", "100.05", abs_tol=0.01, rel_tol=0.05)
    assert s > 0.95


def test_numeric_tolerance_diff_far_above_window_is_zero() -> None:
    # window = 0.01 + 0.05 * max(100, 200) = 10.01; diff = 100 -> score clamped 0.
    s = score_numeric_tolerance("100", "200", abs_tol=0.01, rel_tol=0.05)
    assert s == 0.0


def test_numeric_tolerance_window_uses_larger_magnitude() -> None:
    # max(|100|, |105|) = 105 -> window = 0.01 + 0.05*105 = 5.26.
    # diff = 5 -> score = 1 - 5/5.26 ≈ 0.0494.
    s = score_numeric_tolerance("100", "105", abs_tol=0.01, rel_tol=0.05)
    assert isclose(s, 1 - 5 / (0.01 + 0.05 * 105), abs_tol=1e-6)


def test_numeric_tolerance_garbage_input_is_zero() -> None:
    assert score_numeric_tolerance("not-a-number", "5") == 0.0


# ---------------------------------------------------------------------------
# date proximity
# ---------------------------------------------------------------------------


def test_date_proximity_identical_is_one() -> None:
    assert score_date_proximity("2025-08-15", "2025-08-15") == 1.0


def test_date_proximity_one_day_apart() -> None:
    s = score_date_proximity("2025-08-15", "2025-08-16", days_tolerance=7)
    assert isclose(s, 6 / 7, abs_tol=1e-6)


def test_date_proximity_beyond_tolerance_is_zero() -> None:
    s = score_date_proximity("2025-08-15", "2025-09-15", days_tolerance=7)
    assert s == 0.0


def test_date_proximity_accepts_multiple_input_formats() -> None:
    # Both inputs parsed via the same strict parser -> equal canonical dates
    s = score_date_proximity("08/15/2025", "2025-08-15")
    assert s == 1.0


def test_date_proximity_garbage_input_is_zero() -> None:
    assert score_date_proximity("yesterday", "2025-08-15") == 0.0


# ---------------------------------------------------------------------------
# registry
# ---------------------------------------------------------------------------


def test_registry_has_all_algorithms_documented_in_check_constraint() -> None:
    # CHECK constraint in models.py mirrors this set. Keep them in sync.
    expected = {
        "exact",
        "levenshtein",
        "jaro_winkler",
        "jaccard_tokens",
        "cosine_tokens",
        "soundex",
        "metaphone",
        "ngram",
        "numeric_tolerance",
        "date_proximity",
    }
    assert set(ALGORITHMS.keys()) == expected


def test_get_algorithm_returns_def_with_callable_score() -> None:
    a: AlgorithmDef = get_algorithm("exact")
    assert callable(a.score)
    assert a.score("foo", "foo") == 1.0


def test_get_algorithm_rejects_unknown_with_clear_error() -> None:
    with pytest.raises(ValueError, match="Unknown similarity algorithm"):
        get_algorithm("made_up")


def test_every_algorithm_is_symmetric_on_a_sample_input() -> None:
    samples = [
        ("Acme Robotics", "ACME Robatics"),
        ("john.smith@x.com", "john.smith@x.com"),
        ("100", "105"),
        ("2025-08-15", "2025-08-22"),
    ]
    for name, definition in ALGORITHMS.items():
        for a, b in samples:
            sa = definition.score(a, b)
            sb = definition.score(b, a)
            assert isclose(sa, sb, abs_tol=1e-9), f"{name} asymmetric on ({a!r}, {b!r})"
