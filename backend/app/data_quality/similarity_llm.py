"""LLM-driven refinement of column-mapping recommendations (US 3.4).

Used by the "Improve with AI" button on the Profiling Setup &
Configuration page. The heuristic recommender always runs first
(server-side via ``recommend_config``) so the page is usable even
without an LLM key; this module REFINES that recommendation rather
than replacing it.

Precision commitments:
- The LLM is asked for ``algorithm`` and ``parser`` per existing mapping.
  It cannot invent new mappings, drop existing ones, change column names,
  flip ``is_important``, or alter weights — those are user decisions and
  the LLM cannot override them.
- The response is validated against a pydantic schema with a strict
  algorithm/parser enum. One retry on parse/validation failure; the
  whole call returns the heuristic mappings unchanged if both attempts
  fail, with the raw error attached to the response so the UI can
  surface it.
- Each refined mapping is annotated ``recommended_by='llm'`` so the
  user can see at a glance which suggestions came from AI vs. heuristic
  vs. their own edits.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Literal

from pydantic import BaseModel, Field, ValidationError

from app.data_quality.annotator import _call_provider_text, _strip_codefences
from app.data_quality.recommend import ColumnFacts, RecommendedMapping
from app.llm.session import LlmKeys

LLM_REFINER_VERSION = "1.0.0"
LLM_REFINER_MAX_TOKENS = 2048

_VALID_ALGORITHMS: tuple[str, ...] = (
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
)
_VALID_PARSERS: tuple[str, ...] = ("phone", "email", "date")

SYSTEM_PROMPT = """\
You are a senior data engineer helping refine cross-sheet record-linkage
configuration. The user has chosen a set of column mappings between two
spreadsheet tables. For each mapping, choose the BEST similarity algorithm
and (optionally) a field-specific parser.

You may ONLY pick an algorithm from this whitelist:
  exact, levenshtein, jaro_winkler, jaccard_tokens, cosine_tokens, soundex,
  metaphone, ngram, numeric_tolerance, date_proximity

You may ONLY pick a parser from this whitelist (or null for no parser):
  phone, email, date

Rules:
- Output JSON ONLY. No prose, no markdown fences.
- The output schema is exactly:
  {"refinements": [{"column_a": <str>, "column_b": <str>,
                    "algorithm": <enum>, "parser": <enum|null>,
                    "rationale": <str>}]}
- Cover every input mapping. Do not add, remove, or rename mappings.
- Do not alter the user's weight or is_important flag — those are
  precision-critical user decisions.
- numeric_tolerance is ONLY valid for numeric columns.
- date_proximity is ONLY valid for date columns or string columns that
  have a date pattern label.
- If unsure, prefer the more conservative algorithm (exact > levenshtein
  > jaccard_tokens > cosine_tokens).
"""

RETRY_PROMPT = (
    "Your previous response was not valid JSON matching the required schema. "
    "Return ONLY a JSON object with the exact schema:\n"
    '{"refinements": [{"column_a": str, "column_b": str, '
    '"algorithm": enum, "parser": enum|null, "rationale": str}]}.\n'
    "Cover every input mapping. No prose, no markdown."
)


class _LlmRefinement(BaseModel):
    column_a: str
    column_b: str
    algorithm: Literal[
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
    ]
    parser: Literal["phone", "email", "date"] | None = None
    rationale: str = Field(default="", max_length=500)


class _LlmRefinementBatch(BaseModel):
    refinements: list[_LlmRefinement]


@dataclass(frozen=True)
class LlmRefinementResult:
    mappings: list[RecommendedMapping]
    raw: str
    error: str | None  # populated when both LLM attempts failed validation


def _facts_to_prompt(facts: ColumnFacts) -> dict[str, Any]:
    return {
        "name": facts.name,
        "semantic_type": facts.semantic_type,
        "pattern_label": facts.pattern_label,
        "avg_value_length": facts.avg_value_length,
        "distinct_pct": facts.distinct_pct,
    }


def _build_user_message(
    sheet_a: str,
    sheet_b: str,
    facts_a_by_name: dict[str, ColumnFacts],
    facts_b_by_name: dict[str, ColumnFacts],
    existing: list[RecommendedMapping],
) -> str:
    payload = {
        "sheet_a": sheet_a,
        "sheet_b": sheet_b,
        "mappings": [
            {
                "column_a": m.column_a,
                "column_b": m.column_b,
                "current_algorithm": m.algorithm,
                "current_parser": m.parser,
                "weight": m.weight,
                "is_important": m.is_important,
                "column_a_profile": _facts_to_prompt(facts_a_by_name[m.column_a])
                if m.column_a in facts_a_by_name
                else None,
                "column_b_profile": _facts_to_prompt(facts_b_by_name[m.column_b])
                if m.column_b in facts_b_by_name
                else None,
            }
            for m in existing
        ],
    }
    return (
        "Refine the similarity algorithm + parser for each mapping below.\n\n"
        + json.dumps(payload, indent=2)
    )


def _parse_response(raw: str) -> _LlmRefinementBatch | None:
    try:
        loaded = json.loads(_strip_codefences(raw))
    except (ValueError, TypeError):
        return None
    try:
        return _LlmRefinementBatch.model_validate(loaded)
    except ValidationError:
        return None


def refine_mappings_with_llm(
    keys: LlmKeys,
    sheet_a: str,
    sheet_b: str,
    facts_a: list[ColumnFacts],
    facts_b: list[ColumnFacts],
    existing_mappings: list[RecommendedMapping],
) -> LlmRefinementResult:
    """Single batched LLM call. Returns refined mappings (or originals,
    unchanged, if the LLM response can't be validated after one retry).

    The caller persists nothing — this is a pure recommendation. The user
    reviews the result on the config page and clicks Save to commit.
    """
    if not existing_mappings:
        return LlmRefinementResult(mappings=[], raw="", error=None)

    facts_a_by_name = {f.name: f for f in facts_a}
    facts_b_by_name = {f.name: f for f in facts_b}
    user_message = _build_user_message(
        sheet_a, sheet_b, facts_a_by_name, facts_b_by_name, existing_mappings
    )

    raw = _call_provider_text(keys, SYSTEM_PROMPT, user_message)
    parsed = _parse_response(raw)
    if parsed is None:
        raw2 = _call_provider_text(keys, RETRY_PROMPT, user_message)
        parsed2 = _parse_response(raw2)
        if parsed2 is None:
            return LlmRefinementResult(
                mappings=existing_mappings,
                raw=raw2,
                error="LLM response failed schema validation after one retry.",
            )
        parsed = parsed2
        raw = raw2

    by_key = {(r.column_a, r.column_b): r for r in parsed.refinements}
    refined: list[RecommendedMapping] = []
    for m in existing_mappings:
        ref = by_key.get((m.column_a, m.column_b))
        if ref is None:
            # LLM dropped a mapping; honour precision-first by keeping
            # the user's mapping unchanged with the original provenance.
            refined.append(m)
            continue
        refined.append(
            RecommendedMapping(
                column_a=m.column_a,
                column_b=m.column_b,
                algorithm=ref.algorithm,
                parser=ref.parser,
                weight=m.weight,           # NEVER touched by LLM
                is_important=m.is_important,  # NEVER touched by LLM
                recommended_by="llm",
            )
        )
    return LlmRefinementResult(mappings=refined, raw=raw, error=None)
