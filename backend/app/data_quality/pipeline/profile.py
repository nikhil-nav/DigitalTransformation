"""Profile orchestration: load workbook, run stats, persist results.

This module sits between the HTTP router and `stats.py`. Its job is to:

1. Load every sheet of an .xlsx into a DataFrame (`dtype=object` so the
   stats engine sees raw Python values, not pandas-coerced ones).
2. Capture any user-supplied bounds from a prior profile so re-running
   doesn't lose them.
3. Replace the entire profile graph (sheet profiles, column profiles,
   issues) for the dataset in one transaction so the dashboard never sees
   a partial run.
4. Stamp `dataset.profiled_at` so the API can advertise freshness.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd
from sqlalchemy.orm import Session

from app.data_quality.pipeline.cross import (
    CROSS_ENGINE_VERSION,
    CrossAnalysisResult,
    analyse_workbook,
    fk_violations,
)
from app.data_quality.pipeline.stats import (
    STATS_ENGINE_VERSION,
    IssueDraft,
    SheetProfile,
    profile_sheet,
)
from app.models import (
    DataQualityColumnProfile,
    DataQualityDataset,
    DataQualityFunctionalDependency,
    DataQualityIssue,
    DataQualityRelationship,
    DataQualitySheetProfile,
)


def _load_workbook(path: Path) -> dict[str, pd.DataFrame]:
    """Load every sheet with raw object dtype so stats.py owns the typing."""
    # `sheet_name=None` returns a dict, `dtype=object` keeps cells as-is.
    return pd.read_excel(path, sheet_name=None, dtype=object)


def _capture_existing_bounds(
    db: Session, dataset_id: int
) -> dict[str, dict[str, tuple[float | None, float | None]]]:
    """Map of {sheet_name: {column_name: (range_min, range_max)}} from any
    prior profile, so a re-profile preserves bounds the user has set."""
    rows = (
        db.query(
            DataQualitySheetProfile.sheet_name,
            DataQualityColumnProfile.name,
            DataQualityColumnProfile.range_min,
            DataQualityColumnProfile.range_max,
        )
        .join(
            DataQualityColumnProfile,
            DataQualityColumnProfile.sheet_profile_id
            == DataQualitySheetProfile.id,
        )
        .filter(DataQualitySheetProfile.dataset_id == dataset_id)
        .all()
    )
    out: dict[str, dict[str, tuple[float | None, float | None]]] = {}
    for sheet, col, rmin, rmax in rows:
        if rmin is None and rmax is None:
            continue
        out.setdefault(sheet, {})[col] = (rmin, rmax)
    return out


def _persist_sheet(
    db: Session,
    dataset_id: int,
    sheet: SheetProfile,
) -> None:
    sheet_row = DataQualitySheetProfile(
        dataset_id=dataset_id,
        sheet_name=sheet.sheet_name,
        row_count=sheet.row_count,
        column_count=sheet.column_count,
        exact_duplicate_row_count=sheet.exact_duplicate_row_count,
        completeness_pct=sheet.completeness_pct,
        rag=sheet.rag,
        engine_version=STATS_ENGINE_VERSION,
    )
    db.add(sheet_row)
    db.flush()  # need sheet_row.id for the column FK

    for col in sheet.columns:
        db.add(
            DataQualityColumnProfile(
                sheet_profile_id=sheet_row.id,
                name=col.name,
                ordinal=col.ordinal,
                inferred_dtype=col.inferred_dtype,
                semantic_type=col.semantic_type,
                type_mismatch_count=col.type_mismatch_count,
                null_count=col.null_count,
                null_pct=col.null_pct,
                distinct_count=col.distinct_count,
                distinct_pct=col.distinct_pct,
                top_values_json=json.dumps(
                    [{"value": v, "count": c} for v, c in col.top_values]
                ),
                numeric_min=col.numeric_min,
                numeric_max=col.numeric_max,
                numeric_mean=col.numeric_mean,
                numeric_median=col.numeric_median,
                numeric_std=col.numeric_std,
                numeric_p25=col.numeric_p25,
                numeric_p75=col.numeric_p75,
                date_min=col.date_min,
                date_max=col.date_max,
                pattern_label=col.pattern_label,
                pattern_conformance_pct=col.pattern_conformance_pct,
                outlier_iqr_count=col.outlier_iqr_count,
                outlier_mad_count=col.outlier_mad_count,
                range_min=col.range_min,
                range_max=col.range_max,
                range_violation_count=col.range_violation_count,
                rag=col.rag,
            )
        )


def _persist_issues(
    db: Session, dataset_id: int, drafts: list[IssueDraft]
) -> None:
    for d in drafts:
        db.add(
            DataQualityIssue(
                dataset_id=dataset_id,
                sheet_name=d.sheet_name,
                column_name=d.column_name,
                dimension=d.dimension,
                severity=d.severity,
                description=d.description,
                sample_value_count=len(d.sample_values),
                sample_values_json=json.dumps(d.sample_values),
                engine_version=STATS_ENGINE_VERSION,
            )
        )


def _capture_relationship_decisions(
    db: Session, dataset_id: int
) -> dict[tuple[str, str, str, str], tuple[str, datetime | None, datetime | None]]:
    """Map of relationship key -> (status, confirmed_at, dismissed_at) for
    any prior `confirmed` or `dismissed` rows. Re-suggested relationships
    that the user has already judged keep their decision; relationships the
    user hasn't touched (`status='suggested'`) are dropped so the new run
    can replace them cleanly."""
    rows = (
        db.query(DataQualityRelationship)
        .filter(
            DataQualityRelationship.dataset_id == dataset_id,
            DataQualityRelationship.status != "suggested",
        )
        .all()
    )
    out: dict[
        tuple[str, str, str, str], tuple[str, datetime | None, datetime | None]
    ] = {}
    for r in rows:
        key = (r.parent_sheet, r.parent_column, r.child_sheet, r.child_column)
        out[key] = (r.status, r.confirmed_at, r.dismissed_at)
    return out


def _persist_cross_results(
    db: Session,
    dataset_id: int,
    sheets_by_name: dict[str, pd.DataFrame],
    cross: CrossAnalysisResult,
    decisions: dict[
        tuple[str, str, str, str], tuple[str, datetime | None, datetime | None]
    ],
) -> None:
    """Persist FDs, redundancy issues, relationship suggestions, and (for
    relationships that were previously confirmed) FK-violation issues."""
    # Functional dependencies: informational, persisted as their own rows.
    for fd in cross.functional_dependencies:
        db.add(
            DataQualityFunctionalDependency(
                dataset_id=dataset_id,
                sheet_name=fd.sheet_name,
                determinant_column=fd.determinant_column,
                dependent_column=fd.dependent_column,
                confidence_pct=fd.confidence_pct,
                counter_example_count=fd.counter_example_count,
                sample_counter_examples_json=json.dumps(fd.sample_counter_examples),
                engine_version=CROSS_ENGINE_VERSION,
            )
        )

    # Numeric redundancy: surfaced as a regular Issue under 'redundancy'.
    for corr in cross.correlations:
        db.add(
            DataQualityIssue(
                dataset_id=dataset_id,
                sheet_name=corr.sheet_name,
                column_name=None,
                dimension="redundancy",
                severity="medium",
                description=(
                    f"Columns '{corr.column_a}' and '{corr.column_b}' on "
                    f"sheet '{corr.sheet_name}' have Pearson r={corr.pearson_r:.3f} "
                    f"(|r| >= 0.95); consider whether they are redundant."
                ),
                sample_value_count=2,
                sample_values_json=json.dumps([corr.column_a, corr.column_b]),
                engine_version=CROSS_ENGINE_VERSION,
            )
        )

    # Relationships: preserve prior confirmed/dismissed state.
    for rel in cross.relationships:
        key = (rel.parent_sheet, rel.parent_column, rel.child_sheet, rel.child_column)
        prior = decisions.get(key)
        status = prior[0] if prior else "suggested"
        confirmed_at = prior[1] if prior else None
        dismissed_at = prior[2] if prior else None
        db.add(
            DataQualityRelationship(
                dataset_id=dataset_id,
                parent_sheet=rel.parent_sheet,
                parent_column=rel.parent_column,
                child_sheet=rel.child_sheet,
                child_column=rel.child_column,
                type_match=rel.type_match,
                name_similarity=rel.name_similarity,
                subset_coverage=rel.subset_coverage,
                cardinality=rel.cardinality,
                confidence_pct=rel.confidence_pct,
                status=status,
                engine_version=CROSS_ENGINE_VERSION,
                confirmed_at=confirmed_at,
                dismissed_at=dismissed_at,
            )
        )
    db.flush()

    # FK-violation issues only for relationships that are CURRENTLY
    # confirmed (and were also re-suggested, so the new data confirms the
    # earlier judgement still applies). If a previously-confirmed
    # relationship is no longer suggested by the engine (e.g. coverage
    # dropped), it stays confirmed in the table - but we don't emit
    # violation issues for it because the underlying data has changed
    # enough that the relationship is no longer trustworthy.
    for rel in cross.relationships:
        key = (rel.parent_sheet, rel.parent_column, rel.child_sheet, rel.child_column)
        prior = decisions.get(key)
        if not prior or prior[0] != "confirmed":
            continue
        violation = fk_violations(
            sheets_by_name[rel.parent_sheet],
            rel.parent_column,
            sheets_by_name[rel.child_sheet],
            rel.child_column,
        )
        if violation is None:
            continue
        db.add(
            DataQualityIssue(
                dataset_id=dataset_id,
                sheet_name=rel.child_sheet,
                column_name=rel.child_column,
                dimension="validity",
                severity="high",
                description=(
                    f"[FK violation] {rel.child_sheet}.{rel.child_column} has "
                    f"{violation.missing_value_count} value(s) not present in "
                    f"{rel.parent_sheet}.{rel.parent_column}."
                ),
                sample_value_count=len(violation.sample_missing_values),
                sample_values_json=json.dumps(violation.sample_missing_values),
                engine_version=CROSS_ENGINE_VERSION,
            )
        )


def profile_dataset(
    db: Session, dataset: DataQualityDataset
) -> list[DataQualitySheetProfile]:
    """Recompute the full profile graph for one dataset.

    Wipes prior profile rows (sheet profiles, column profiles via cascade,
    issues, functional dependencies, and relationships that were never
    confirmed/dismissed by the user) before inserting fresh ones.
    User-supplied bounds and relationship decisions (confirmed/dismissed)
    are preserved across runs. The dataset row's `profiled_at` is set to
    the current UTC time.

    Returns the newly-inserted sheet profile rows, ordered by sheet name as
    they appeared in the workbook.
    """
    bounds_by_sheet = _capture_existing_bounds(db, dataset.id)
    relationship_decisions = _capture_relationship_decisions(db, dataset.id)

    # Clear prior profile graph. Column profiles cascade from sheet profiles.
    db.query(DataQualitySheetProfile).filter_by(dataset_id=dataset.id).delete(
        synchronize_session=False
    )
    db.query(DataQualityIssue).filter_by(dataset_id=dataset.id).delete(
        synchronize_session=False
    )
    db.query(DataQualityFunctionalDependency).filter_by(
        dataset_id=dataset.id
    ).delete(synchronize_session=False)
    # Relationships: wipe everything; we re-create from suggestions and
    # carry over status/decisions via `relationship_decisions`.
    db.query(DataQualityRelationship).filter_by(dataset_id=dataset.id).delete(
        synchronize_session=False
    )
    db.flush()
    # Evict any leftover rows the caller pre-loaded (e.g. the
    # ColumnProfile that the bounds endpoint just modified, or a
    # Relationship the PATCH endpoint just updated). Without this, the
    # next INSERT can collide on the SQLite-reused primary key and
    # SQLAlchemy raises an identity-map warning. Dataset stays in the
    # session because we still write `profiled_at` to it below.
    for obj in list(db.identity_map.values()):
        if isinstance(
            obj,
            (
                DataQualityColumnProfile,
                DataQualitySheetProfile,
                DataQualityIssue,
                DataQualityFunctionalDependency,
                DataQualityRelationship,
            ),
        ):
            db.expunge(obj)

    sheets_by_name = _load_workbook(Path(dataset.local_path))
    semantic_types_by_sheet: dict[str, dict[str, str]] = {}
    numeric_columns_by_sheet: dict[str, list[str]] = {}
    for sheet_name, df in sheets_by_name.items():
        result = profile_sheet(
            df,
            sheet_name=sheet_name,
            bounds=bounds_by_sheet.get(sheet_name),
        )
        _persist_sheet(db, dataset.id, result)
        _persist_issues(db, dataset.id, result.issues)
        semantic_types_by_sheet[sheet_name] = {
            c.name: c.semantic_type for c in result.columns
        }
        numeric_columns_by_sheet[sheet_name] = [
            c.name for c in result.columns if c.semantic_type in {"integer", "float"}
        ]

    cross = analyse_workbook(
        sheets_by_name,
        semantic_types_by_sheet,
        numeric_columns_by_sheet,
    )
    _persist_cross_results(
        db, dataset.id, sheets_by_name, cross, relationship_decisions
    )

    dataset.profiled_at = datetime.now(timezone.utc)
    db.flush()

    # Re-fetch ordered so the caller can serialise without surprises.
    new_sheet_rows = (
        db.query(DataQualitySheetProfile)
        .filter_by(dataset_id=dataset.id)
        .order_by(DataQualitySheetProfile.id.asc())
        .all()
    )
    return new_sheet_rows
