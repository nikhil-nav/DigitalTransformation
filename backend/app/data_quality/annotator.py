"""AI annotation of data-quality issues.

Reads the persisted (stats-engine-produced) issues for a dataset, batches
them, asks the configured provider for structured JSON annotations
({issue_id, narrative, suggested_fix}), validates the JSON, and writes
ai_narrative + ai_fix + ai_status back onto each row.

# Precision commitments (Part 5 plan)

- **No issue cap.** Every issue is annotated. Batches of up to
  `MAX_BATCH_SIZE` issues per LLM call manage cost without dropping data.
- **Schema validation, not free-form parsing.** The LLM response must be a
  JSON object matching `AnnotationBatchResponse`. We try one retry with a
  corrective prompt; if the response still fails validation, every issue
  in the batch is marked `ai_status='failed'` and the raw response is
  preserved in `ai_raw` so a human can audit.
- **AI cannot override stats.** This module only writes `ai_narrative`,
  `ai_fix`, `ai_status`, and `ai_raw` on the issue row. The deterministic
  fields (severity, description, sample values, etc.) are untouched.
- **Graceful degradation.** If the LLM call itself errors (no key,
  network, rate limit), the whole annotation pass is marked failed on the
  dataset, the per-issue status remains `pending` for retry, and the
  dashboard still works on stats alone.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from pydantic import BaseModel, Field, ValidationError
from sqlalchemy.orm import Session

from app.llm.provider import get_provider
from app.llm.session import LlmKeys
from app.models import DataQualityDataset, DataQualityIssue

ANNOTATOR_VERSION = "1.0.0"
MAX_BATCH_SIZE = 20
ANNOTATION_MAX_TOKENS = 4096

SYSTEM_PROMPT = """\
You are a senior data-quality analyst helping a domain expert triage issues \
found in an uploaded Excel workbook. For each numbered issue below, write:

- `narrative`: 1-2 sentences in plain English explaining what the issue \
means in business terms (not just restating the data).
- `suggested_fix`: 1-2 concrete, actionable sentences proposing how to \
investigate or remediate.

Rules:
- Output JSON ONLY. No prose, no markdown fences, no explanation.
- The output schema is exactly:
  {"annotations": [{"issue_id": <int>, "narrative": <str>, "suggested_fix": <str>}]}
- Every input issue must appear in `annotations`. Do not skip any.
- Keep narrative and suggested_fix short (under ~250 chars each).
- Do not invent counts, percentages, or column names. Refer only to what \
the issue description states.
- Do not contradict the issue's severity or dimension.
"""

RETRY_PROMPT = """\
Your previous response was not valid JSON matching the required schema. \
Return ONLY a JSON object with the exact schema:
{"annotations": [{"issue_id": <int>, "narrative": <str>, "suggested_fix": <str>}]}
Cover every issue_id in the input. No prose, no markdown.
"""


# --- Result schema -------------------------------------------------------


class _AnnotationItem(BaseModel):
    issue_id: int
    narrative: str = Field(min_length=1, max_length=1000)
    suggested_fix: str = Field(min_length=1, max_length=1000)


class _AnnotationBatchResponse(BaseModel):
    annotations: list[_AnnotationItem]


@dataclass(frozen=True)
class AnnotationReport:
    annotated_count: int
    failed_count: int
    batches: int
    error: str | None = None


# --- Helpers -------------------------------------------------------------


def _issue_for_prompt(issue: DataQualityIssue) -> dict[str, Any]:
    return {
        "issue_id": issue.id,
        "sheet_name": issue.sheet_name,
        "column_name": issue.column_name,
        "dimension": issue.dimension,
        "severity": issue.severity,
        "description": issue.description,
        "sample_values": issue.sample_values,
    }


def _dataset_summary(dataset: DataQualityDataset) -> dict[str, Any]:
    return {
        "filename": dataset.original_filename,
        "sheets": dataset.sheets,
    }


def _build_user_message(
    dataset: DataQualityDataset, batch: list[DataQualityIssue]
) -> str:
    payload = {
        "dataset": _dataset_summary(dataset),
        "issues": [_issue_for_prompt(i) for i in batch],
    }
    return (
        "Annotate the following data-quality issues. Input:\n\n"
        + json.dumps(payload, indent=2)
    )


def _strip_codefences(raw: str) -> str:
    s = raw.strip()
    if s.startswith("```"):
        # Drop the opening fence (with optional language tag) and the trailing fence.
        s = s.split("\n", 1)[1] if "\n" in s else s[3:]
        if s.endswith("```"):
            s = s[: -3]
    return s.strip()


def _parse_response(raw: str) -> _AnnotationBatchResponse | None:
    """Parse the LLM's JSON. Returns None on any failure."""
    try:
        loaded = json.loads(_strip_codefences(raw))
    except (ValueError, TypeError):
        return None
    try:
        return _AnnotationBatchResponse.model_validate(loaded)
    except ValidationError:
        return None


def _call_provider_text(keys: LlmKeys, system: str, user: str) -> str:
    """One non-streaming call returning the model's text. No tools."""
    provider = get_provider(keys)
    model = keys.model or provider.default_model
    response = provider.call(
        system=system,
        messages=[{"role": "user", "content": user}],
        tools=[],
        model=model,
        max_tokens=ANNOTATION_MAX_TOKENS,
    )
    return response.text


def _annotate_batch(
    keys: LlmKeys,
    dataset: DataQualityDataset,
    batch: list[DataQualityIssue],
) -> tuple[_AnnotationBatchResponse | None, str]:
    """Returns (parsed_response | None, raw_text). Tries once, retries once
    with a corrective system prompt if the first response fails to parse.
    Raises if the LLM call itself errors."""
    user = _build_user_message(dataset, batch)

    raw = _call_provider_text(keys, SYSTEM_PROMPT, user)
    parsed = _parse_response(raw)
    if parsed is not None:
        return parsed, raw

    # One retry with a stricter system prompt.
    raw2 = _call_provider_text(keys, RETRY_PROMPT, user)
    parsed2 = _parse_response(raw2)
    if parsed2 is not None:
        return parsed2, raw2

    # Both attempts failed schema validation; return raw of the latest.
    return None, raw2


def _apply_batch(
    db: Session,
    batch: list[DataQualityIssue],
    parsed: _AnnotationBatchResponse | None,
    raw: str,
) -> tuple[int, int]:
    """Mutate the issue rows in `batch` based on the parsed response.

    Returns (annotated_count, failed_count). Issues whose `issue_id` isn't
    in the parsed payload are marked failed (with the raw response) so the
    user can see a partial response wasn't silently accepted.
    """
    if parsed is None:
        for issue in batch:
            issue.ai_status = "failed"
            issue.ai_raw = raw
        return (0, len(batch))

    by_id = {a.issue_id: a for a in parsed.annotations}
    annotated = 0
    failed = 0
    for issue in batch:
        item = by_id.get(issue.id)
        if item is None:
            issue.ai_status = "failed"
            issue.ai_raw = raw
            failed += 1
            continue
        issue.ai_narrative = item.narrative
        issue.ai_fix = item.suggested_fix
        issue.ai_status = "done"
        issue.ai_raw = None
        annotated += 1
    return (annotated, failed)


# --- Public entry point --------------------------------------------------


def annotate_dataset(
    db: Session, dataset: DataQualityDataset, keys: LlmKeys
) -> AnnotationReport:
    """Annotate every pending issue on this dataset.

    Mutates `dataset.annotation_status`/`annotation_error`/`annotated_at`
    and the per-issue `ai_*` columns. Caller is responsible for committing.
    """
    dataset.annotation_status = "running"
    dataset.annotation_error = None
    db.flush()

    issues = (
        db.query(DataQualityIssue)
        .filter_by(dataset_id=dataset.id)
        .order_by(DataQualityIssue.id.asc())
        .all()
    )
    if not issues:
        dataset.annotation_status = "done"
        dataset.annotated_at = datetime.now(timezone.utc)
        db.flush()
        return AnnotationReport(annotated_count=0, failed_count=0, batches=0)

    annotated_total = 0
    failed_total = 0
    batches = 0
    try:
        for start in range(0, len(issues), MAX_BATCH_SIZE):
            batch = issues[start : start + MAX_BATCH_SIZE]
            parsed, raw = _annotate_batch(keys, dataset, batch)
            annotated, failed = _apply_batch(db, batch, parsed, raw)
            annotated_total += annotated
            failed_total += failed
            batches += 1
            db.flush()
    except Exception as e:  # noqa: BLE001 - surface to caller
        dataset.annotation_status = "failed"
        dataset.annotation_error = str(e)[:500]
        db.flush()
        return AnnotationReport(
            annotated_count=annotated_total,
            failed_count=failed_total,
            batches=batches,
            error=str(e),
        )

    # If every issue ended up flagged failed (schema kept breaking), surface
    # that at the dataset level so the dashboard can show a degraded state.
    if annotated_total == 0 and failed_total > 0:
        dataset.annotation_status = "failed"
        dataset.annotation_error = (
            f"All {failed_total} issue(s) failed schema validation across "
            f"{batches} batch(es)."
        )
    else:
        dataset.annotation_status = "done"
    dataset.annotated_at = datetime.now(timezone.utc)
    db.flush()

    return AnnotationReport(
        annotated_count=annotated_total,
        failed_count=failed_total,
        batches=batches,
    )
