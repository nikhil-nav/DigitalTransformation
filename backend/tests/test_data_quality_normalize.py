"""Tests for Epic 3 normalization rules and field-specific parsers.

Each rule is tested against the spec's exact example from
DataQualityagent.md US 3.2. A hypothesis property test verifies that
applying any combination of rules twice yields the same result as
applying it once.
"""
from __future__ import annotations

import string

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from app.data_quality.normalize import (
    ALL_RULES,
    RULE_CASE_FOLD,
    RULE_COLLAPSE_WHITESPACE,
    RULE_EXPAND_ADDRESS,
    RULE_NFKD_FOLD,
    RULE_STRIP_CORP_SUFFIX,
    RULE_STRIP_PUNCTUATION,
    RULE_STRIP_SPECIAL,
    Normalizer,
    case_fold,
    collapse_whitespace,
    expand_address_abbrev,
    nfkd_fold,
    strip_corporate_suffix,
    strip_punctuation,
    strip_special_chars,
)
from app.data_quality.parsers import (
    parse_date_iso,
    parse_email,
    parse_phone_e164,
)


# ---------------------------------------------------------------------------
# Rule unit tests (spec examples)
# ---------------------------------------------------------------------------


def test_case_fold_spec_example() -> None:
    # US 3.2: ACME ROBOTICS INC -> acme robotics inc
    assert case_fold("ACME ROBOTICS INC") == "acme robotics inc"


def test_collapse_whitespace_spec_examples() -> None:
    # US 3.2: "  Helix Pharmaceuticals  " -> "Helix Pharmaceuticals"
    assert collapse_whitespace("  Helix Pharmaceuticals  ") == "Helix Pharmaceuticals"
    # US 3.2: "Brightlight  Media   LLC" -> "Brightlight Media LLC"
    assert collapse_whitespace("Brightlight  Media   LLC") == "Brightlight Media LLC"


def test_strip_punctuation_spec_example() -> None:
    # US 3.2: "Acme Robotics, Inc" -> "Acme Robotics Inc"
    # Note: our rule replaces with single space; the followup
    # collapse_whitespace tightens it. We assert both stages.
    stripped = strip_punctuation("Acme Robotics, Inc")
    assert collapse_whitespace(stripped) == "Acme Robotics Inc"


def test_nfkd_fold_spec_example() -> None:
    # US 3.2: "Café Lumière" -> "Cafe Lumiere"
    assert nfkd_fold("Café Lumière") == "Cafe Lumiere"


def test_strip_special_chars_drops_emoji_and_zwsp() -> None:
    # Coffee cup emoji + zero-width space + Café
    raw = "Café Lumière ​☕"
    assert strip_special_chars(raw) == "Café Lumière "


def test_strip_corporate_suffix_spec_example() -> None:
    # US 3.2: Acme Robotics Inc / Acme Robotics / Acme Robotics LLC
    # all reduce to acme robotics.  We strip the suffix on the
    # case-folded representation so the assertion can compare directly.
    assert strip_corporate_suffix("Acme Robotics Inc") == "Acme Robotics"
    assert strip_corporate_suffix("Acme Robotics") == "Acme Robotics"
    assert strip_corporate_suffix("Acme Robotics LLC") == "Acme Robotics"
    # Chained suffixes also handled in a single pass.
    assert strip_corporate_suffix("Acme Robotics Inc LLC") == "Acme Robotics"


def test_strip_corporate_suffix_leaves_interior_occurrences() -> None:
    # We must NOT trim "Inc" / "LLC" appearing inside a name; only the
    # trailing legal entity hint.
    assert strip_corporate_suffix("LLC Holdings") == "LLC Holdings"


def test_expand_address_abbrev_spec_examples() -> None:
    # US 3.2: "120 Market St." -> "120 Market Street"
    assert expand_address_abbrev("120 Market St.") == "120 Market Street"
    # US 3.2: "30 St Clair Ave W" -> "30 Saint Clair Avenue West"
    assert expand_address_abbrev("30 St Clair Ave W") == "30 Saint Clair Avenue West"


# ---------------------------------------------------------------------------
# Composed pipeline tests
# ---------------------------------------------------------------------------


def test_full_pipeline_matches_spec_full_walk() -> None:
    # ACME ROBOTICS INC (EX-1042) -> acme robotics
    # via case_fold + collapse + strip_punct + strip_corp_suffix.
    norm = Normalizer.from_toggles(
        {
            RULE_CASE_FOLD: True,
            RULE_COLLAPSE_WHITESPACE: True,
            RULE_STRIP_PUNCTUATION: True,
            RULE_STRIP_CORP_SUFFIX: True,
        }
    )
    assert norm.apply("ACME ROBOTICS INC") == "acme robotics"
    assert norm.apply("Acme Robotics, Inc.") == "acme robotics"
    assert norm.apply("Acme Robotics LLC") == "acme robotics"


def test_full_pipeline_handles_unicode_and_emoji_together() -> None:
    norm = Normalizer.from_toggles(
        {
            RULE_NFKD_FOLD: True,
            RULE_STRIP_SPECIAL: True,
            RULE_CASE_FOLD: True,
            RULE_COLLAPSE_WHITESPACE: True,
        }
    )
    assert norm.apply("Café Lumière ☕") == "cafe lumiere"


def test_normalizer_returns_none_for_nullish_inputs() -> None:
    n = Normalizer.from_toggles({RULE_CASE_FOLD: True})
    assert n.apply(None) is None
    assert n.apply("") is None
    assert n.apply("   ") is None
    # All-special-char input collapses to empty -> None.
    n2 = Normalizer.from_toggles({RULE_STRIP_SPECIAL: True})
    assert n2.apply("☕") is None


def test_normalizer_rejects_unknown_rule_names() -> None:
    with pytest.raises(ValueError, match="Unknown normalization rule"):
        Normalizer.from_toggles({"made_up_rule": True})


def test_normalizer_applies_rules_in_canonical_order_regardless_of_toggle_order() -> None:
    # The pipeline is order-stable so equivalent toggle sets produce the
    # same comparison key regardless of how the UI happened to enumerate them.
    a = Normalizer.from_toggles({RULE_CASE_FOLD: True, RULE_COLLAPSE_WHITESPACE: True})
    b = Normalizer.from_toggles({RULE_COLLAPSE_WHITESPACE: True, RULE_CASE_FOLD: True})
    assert a.enabled == b.enabled
    assert a.apply("Hello   World") == b.apply("Hello   World")


# ---------------------------------------------------------------------------
# Idempotence property test
# ---------------------------------------------------------------------------


@given(
    text=st.text(
        alphabet=st.characters(blacklist_categories=("Cs",)),
        min_size=0,
        max_size=80,
    ),
    toggles=st.lists(
        st.sampled_from(list(ALL_RULES)),
        min_size=0,
        max_size=len(ALL_RULES),
        unique=True,
    ),
)
@settings(max_examples=200, deadline=None)
def test_pipeline_is_idempotent(text: str, toggles: list[str]) -> None:
    norm = Normalizer.from_toggles({t: True for t in toggles})
    first = norm.apply(text)
    if first is None:
        return  # nullish: nothing to compare on second pass
    second = norm.apply(first)
    assert second == first


# ---------------------------------------------------------------------------
# Parser tests
# ---------------------------------------------------------------------------


def test_parse_phone_spec_examples_all_collapse_to_e164() -> None:
    expected = "+14155550142"
    for raw in [
        "(415) 555-0142",
        "415-555-0142",
        "4155550142",
        "415.555.0142",
        "+1 415 555 0142",
    ]:
        # The first four lack an international prefix; require region hint.
        result = parse_phone_e164(raw, default_region="US")
        assert result.ok, f"failed: {raw!r}"
        assert result.value == expected, f"got {result.value!r} for {raw!r}"


def test_parse_phone_no_region_rejects_local_format() -> None:
    # Without a region hint and without "+", we refuse to guess a country.
    result = parse_phone_e164("415-555-0142")
    assert result.ok is False
    assert result.value == "415-555-0142"


def test_parse_phone_handles_null() -> None:
    assert parse_phone_e164(None).ok is False
    assert parse_phone_e164("").ok is False


def test_parse_email_spec_example() -> None:
    # JAMES.CARTER@ACMEROBOTICS.COM -> james.carter@acmerobotics.com
    result = parse_email("JAMES.CARTER@ACMEROBOTICS.COM")
    assert result.ok
    assert result.value == "james.carter@acmerobotics.com"


def test_parse_email_rejects_obviously_invalid() -> None:
    assert parse_email("not-an-email").ok is False
    assert parse_email("missing@tld").ok is False
    assert parse_email("@nope.com").ok is False


def test_parse_date_spec_examples() -> None:
    # US 3.2: 08/15/2025, 15-Aug-2025, 2025.08.15 -> 2025-08-15
    for raw in ["08/15/2025", "15-Aug-2025", "2025.08.15", "2025-08-15"]:
        result = parse_date_iso(raw)
        assert result.ok, f"failed: {raw!r}"
        assert result.value == "2025-08-15", f"got {result.value!r} for {raw!r}"


def test_parse_date_rejects_freeform_language_under_strict_mode() -> None:
    # STRICT_PARSING must reject vague inputs to avoid silent guessing.
    assert parse_date_iso("next Tuesday").ok is False
    assert parse_date_iso("yesterday").ok is False
    assert parse_date_iso("").ok is False
