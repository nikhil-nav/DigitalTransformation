"""Tests for the heuristic similarity-config recommender."""
from __future__ import annotations

from app.data_quality.normalize import (
    RULE_CASE_FOLD,
    RULE_COLLAPSE_WHITESPACE,
    RULE_EXPAND_ADDRESS,
    RULE_STRIP_CORP_SUFFIX,
)
from app.data_quality.recommend import (
    ColumnFacts,
    recommend_algorithm,
    recommend_config,
    recommend_mappings,
    recommend_normalization,
)


def _facts(
    name: str,
    semantic_type: str = "string",
    pattern_label: str | None = None,
    avg_value_length: float | None = None,
) -> ColumnFacts:
    return ColumnFacts(
        name=name,
        semantic_type=semantic_type,
        pattern_label=pattern_label,
        avg_value_length=avg_value_length,
    )


# ---------------------------------------------------------------------------
# recommend_algorithm — patterned strings
# ---------------------------------------------------------------------------


def test_email_pattern_pair_recommends_exact_with_email_parser() -> None:
    a = _facts("email", pattern_label="email")
    b = _facts("contact_email", pattern_label="email")
    assert recommend_algorithm(a, b) == ("exact", "email")


def test_phone_pattern_pair_recommends_exact_with_phone_parser() -> None:
    a = _facts("phone", pattern_label="e164_phone")
    b = _facts("mobile_phone", pattern_label="e164_phone")
    assert recommend_algorithm(a, b) == ("exact", "phone")


def test_iso_date_pattern_pair_recommends_date_proximity() -> None:
    a = _facts("registered_on", pattern_label="iso_date")
    b = _facts("signup_date", pattern_label="iso_date")
    assert recommend_algorithm(a, b) == ("date_proximity", "date")


def test_uuid_pattern_pair_recommends_exact() -> None:
    a = _facts("uuid", pattern_label="uuid")
    b = _facts("identifier", pattern_label="uuid")
    assert recommend_algorithm(a, b) == ("exact", None)


# ---------------------------------------------------------------------------
# recommend_algorithm — typed columns
# ---------------------------------------------------------------------------


def test_both_date_recommends_date_proximity() -> None:
    a = _facts("birth_date", semantic_type="date")
    b = _facts("dob", semantic_type="date")
    assert recommend_algorithm(a, b) == ("date_proximity", "date")


def test_both_numeric_recommends_numeric_tolerance() -> None:
    a = _facts("amount", semantic_type="float")
    b = _facts("total_amount", semantic_type="float")
    assert recommend_algorithm(a, b) == ("numeric_tolerance", None)


def test_mismatched_types_falls_back_to_exact() -> None:
    a = _facts("ref", semantic_type="float")
    b = _facts("ref", semantic_type="date")
    assert recommend_algorithm(a, b) == ("exact", None)


# ---------------------------------------------------------------------------
# recommend_algorithm — string columns + name hints
# ---------------------------------------------------------------------------


def test_email_column_name_hint_picks_email_parser() -> None:
    a = _facts("customer_email", semantic_type="string")
    b = _facts("lead_email", semantic_type="string")
    assert recommend_algorithm(a, b) == ("exact", "email")


def test_phone_column_name_hint_picks_phone_parser() -> None:
    a = _facts("contact_phone", semantic_type="string")
    b = _facts("mobile", semantic_type="string")
    assert recommend_algorithm(a, b) == ("exact", "phone")


def test_id_column_name_hint_picks_exact() -> None:
    a = _facts("customer_id", semantic_type="string")
    b = _facts("cust_code", semantic_type="string")
    assert recommend_algorithm(a, b) == ("exact", None)


def test_name_column_hint_picks_jaro_winkler() -> None:
    a = _facts("customer_name", semantic_type="string", avg_value_length=20)
    b = _facts("account_name", semantic_type="string", avg_value_length=18)
    assert recommend_algorithm(a, b) == ("jaro_winkler", None)


def test_address_column_hint_picks_jaccard_tokens() -> None:
    a = _facts("street_address", semantic_type="string", avg_value_length=40)
    b = _facts("address", semantic_type="string", avg_value_length=35)
    assert recommend_algorithm(a, b) == ("jaccard_tokens", None)


def test_description_column_hint_picks_cosine_tokens() -> None:
    a = _facts("description", semantic_type="string", avg_value_length=120)
    b = _facts("notes", semantic_type="string", avg_value_length=200)
    assert recommend_algorithm(a, b) == ("cosine_tokens", None)


def test_long_unhinted_strings_fall_back_to_jaccard_tokens() -> None:
    a = _facts("anything", semantic_type="string", avg_value_length=120)
    b = _facts("anything_else", semantic_type="string", avg_value_length=80)
    assert recommend_algorithm(a, b) == ("jaccard_tokens", None)


def test_short_unhinted_strings_fall_back_to_levenshtein() -> None:
    a = _facts("anything", semantic_type="string", avg_value_length=10)
    b = _facts("anything_else", semantic_type="string", avg_value_length=8)
    assert recommend_algorithm(a, b) == ("levenshtein", None)


# ---------------------------------------------------------------------------
# recommend_normalization
# ---------------------------------------------------------------------------


def test_normalization_universal_defaults_always_on() -> None:
    norms = recommend_normalization([_facts("anything")])
    assert norms[RULE_CASE_FOLD] is True
    assert norms[RULE_COLLAPSE_WHITESPACE] is True


def test_normalization_enables_address_expansion_when_address_column_present() -> None:
    norms = recommend_normalization([_facts("street_address"), _facts("city")])
    assert norms[RULE_EXPAND_ADDRESS] is True


def test_normalization_enables_corp_suffix_strip_when_name_column_present() -> None:
    norms = recommend_normalization([_facts("company_name")])
    assert norms[RULE_STRIP_CORP_SUFFIX] is True


def test_normalization_leaves_address_off_when_no_address_column() -> None:
    norms = recommend_normalization([_facts("amount", semantic_type="float")])
    assert norms[RULE_EXPAND_ADDRESS] is False


# ---------------------------------------------------------------------------
# recommend_mappings — pairing across two sheets
# ---------------------------------------------------------------------------


def test_mappings_pair_by_name_similarity() -> None:
    a = [
        _facts("customer_email", pattern_label="email"),
        _facts("customer_name"),
    ]
    b = [
        _facts("lead_email", pattern_label="email"),
        _facts("annual_revenue", semantic_type="float"),  # 0 shared tokens, incompatible type
    ]
    mappings = recommend_mappings(a, b)
    pair_names = {(m.column_a, m.column_b) for m in mappings}
    # email <-> email shares the "email" token -> Jaccard 1/3 above the 0.3 default.
    assert ("customer_email", "lead_email") in pair_names
    # customer_name <-> annual_revenue: 0 shared tokens AND type mismatch.
    assert ("customer_name", "annual_revenue") not in pair_names


def test_mappings_skip_type_incompatible_pairs() -> None:
    a = [_facts("amount", semantic_type="float")]
    b = [_facts("amount", semantic_type="string")]
    mappings = recommend_mappings(a, b)
    assert mappings == []


def test_mappings_each_column_used_at_most_once() -> None:
    a = [
        _facts("customer_name"),
        _facts("client_name"),  # also matches "customer" loosely
    ]
    b = [_facts("name")]
    mappings = recommend_mappings(a, b)
    used_a = [m.column_a for m in mappings]
    used_b = [m.column_b for m in mappings]
    assert len(used_a) == len(set(used_a))
    assert len(used_b) == len(set(used_b))


def test_mappings_inherit_recommended_algorithm() -> None:
    a = [_facts("email", pattern_label="email")]
    b = [_facts("email", pattern_label="email")]
    mappings = recommend_mappings(a, b)
    assert len(mappings) == 1
    assert mappings[0].algorithm == "exact"
    assert mappings[0].parser == "email"
    assert mappings[0].recommended_by == "heuristic"
    # Importance is NEVER set by the recommender; it is a precision-critical
    # user decision per Epic 3.
    assert mappings[0].is_important is False


# ---------------------------------------------------------------------------
# recommend_config — top-level entry point
# ---------------------------------------------------------------------------


def test_recommend_config_returns_mappings_and_normalization() -> None:
    a = [_facts("customer_email", pattern_label="email"), _facts("customer_name")]
    b = [_facts("lead_email", pattern_label="email"), _facts("customer_name")]
    cfg = recommend_config(a, b)
    assert cfg.threshold == 0.85
    assert any(m.column_a == "customer_email" for m in cfg.mappings)
    assert cfg.normalization[RULE_CASE_FOLD] is True
    # "customer_name" appearing in either side -> strip corporate suffixes on.
    assert cfg.normalization[RULE_STRIP_CORP_SUFFIX] is True
