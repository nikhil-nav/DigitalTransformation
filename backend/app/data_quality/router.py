"""Data Quality HTTP endpoints.

Workbooks are stored on local disk (Anthropic Files API does not accept
.xlsx) under `{DT_DATA_DIR}/data_quality/{project_id}/{sha256}.xlsx`. The
per-project upload size cap is 25 MB to bound parsing cost.
"""
from __future__ import annotations

import hashlib
import json
import os
from collections.abc import Sequence
from dataclasses import asdict
from pathlib import Path
from typing import Annotated

from fastapi import (
    APIRouter,
    BackgroundTasks,
    Cookie,
    Depends,
    File,
    HTTPException,
    UploadFile,
    status,
)
from fastapi.responses import StreamingResponse
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

import json
from datetime import datetime, timezone

from app.auth import SESSION_COOKIE, get_current_user_row
from app.data_quality.agent import (
    DQ_TOOLS,
    SYSTEM_PROMPT as DQ_SYSTEM_PROMPT,
    make_dq_tool_dispatch,
)
from app.data_quality.annotator import annotate_dataset
from app.data_quality.cluster import (
    CLUSTER_VERSION,
    SimilarityRunError,
    load_sheet_rows,
    run_similarity,
)
from app.data_quality.inspect import (
    BadWorkbookError,
    INSPECTOR_VERSION,
    PasswordProtectedError,
    inspect_workbook,
)
from app.data_quality.normalize import NORMALIZE_VERSION
from app.data_quality.profile import profile_dataset
from app.data_quality.recommend import (
    ColumnFacts,
    RecommendedMapping,
    recommend_config,
)
from app.data_quality.similarity_llm import refine_mappings_with_llm
from app.db import get_db
from app.llm.agent import run_agent_turn_stream
from app.llm.session import LlmKeys, session_keys
from app.models import (
    ChatMessage,
    ChatThread,
    DataQualityColumnMapping,
    DataQualityColumnProfile,
    DataQualityDataset,
    DataQualityFunctionalDependency,
    DataQualityIssue,
    DataQualityProfileConfig,
    DataQualityRecordCluster,
    DataQualityRecordPair,
    DataQualityRelationship,
    DataQualitySheetProfile,
    DataQualitySimilarityRun,
    Project,
    User,
)
from app.schemas import (
    ChatMessageCreate,
    ChatMessageOut,
    DataQualityBoundsUpdate,
    DataQualityClusterDetailOut,
    DataQualityConfigDraftOut,
    DataQualityDatasetOut,
    DataQualityFunctionalDependencyOut,
    DataQualityIssueOut,
    DataQualityProfileConfigIn,
    DataQualityProfileConfigOut,
    DataQualityRecommendIn,
    DataQualityRecommendOut,
    DataQualityRecordClusterOut,
    DataQualityRelationshipOut,
    DataQualityRelationshipStatusUpdate,
    DataQualitySheetProfileOut,
    DataQualitySimilarityRunOut,
    DataQualitySkipConfigOut,
)

DQ_SCOPE = "data_quality"

router = APIRouter(tags=["data_quality"])

DATA_QUALITY_CODE = "data_quality_assessment"
MAX_UPLOAD_BYTES = 25 * 1024 * 1024  # 25 MB
ALLOWED_EXTENSIONS = {".xlsx"}
ALLOWED_MIMES = {
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    "application/vnd.ms-excel",  # some browsers send this for .xlsx
    "application/octet-stream",  # fallback when the browser can't tell
}


def _data_quality_project_or_404(
    db: Session, project_id: int, user: User
) -> Project:
    project = (
        db.query(Project).filter_by(id=project_id, user_id=user.id).one_or_none()
    )
    if project is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Project not found"
        )
    if project.project_type.code != DATA_QUALITY_CODE:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                f"Data Quality endpoints are only available for "
                f"data_quality_assessment projects "
                f"(this project is '{project.project_type.code}')"
            ),
        )
    return project


def _project_dataset_or_404(
    db: Session, project: Project, dataset_id: int
) -> DataQualityDataset:
    row = (
        db.query(DataQualityDataset)
        .filter_by(id=dataset_id, project_id=project.id)
        .one_or_none()
    )
    if row is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Dataset not found"
        )
    return row


def _data_dir() -> Path:
    # Mirror app.db._data_dir's resolution so tests and prod agree.
    return Path(
        os.environ.get(
            "DT_DATA_DIR", str(Path(__file__).resolve().parents[2] / "data")
        )
    )


def _dataset_dir(project_id: int) -> Path:
    d = _data_dir() / "data_quality" / str(project_id)
    d.mkdir(parents=True, exist_ok=True)
    return d


@router.get(
    "/api/projects/{project_id}/dq/datasets",
    response_model=list[DataQualityDatasetOut],
)
def list_datasets(
    project_id: int,
    user: Annotated[User, Depends(get_current_user_row)],
    db: Annotated[Session, Depends(get_db)],
) -> Sequence[DataQualityDataset]:
    project = _data_quality_project_or_404(db, project_id, user)
    return (
        db.query(DataQualityDataset)
        .filter_by(project_id=project.id)
        .order_by(DataQualityDataset.uploaded_at.desc())
        .all()
    )


@router.get(
    "/api/projects/{project_id}/dq/datasets/{dataset_id}",
    response_model=DataQualityDatasetOut,
)
def get_dataset(
    project_id: int,
    dataset_id: int,
    user: Annotated[User, Depends(get_current_user_row)],
    db: Annotated[Session, Depends(get_db)],
) -> DataQualityDataset:
    project = _data_quality_project_or_404(db, project_id, user)
    return _project_dataset_or_404(db, project, dataset_id)


@router.post(
    "/api/projects/{project_id}/dq/datasets",
    response_model=DataQualityDatasetOut,
    status_code=status.HTTP_201_CREATED,
)
def upload_dataset(
    project_id: int,
    background_tasks: BackgroundTasks,
    user: Annotated[User, Depends(get_current_user_row)],
    db: Annotated[Session, Depends(get_db)],
    upload: Annotated[UploadFile, File()],
    session_id: Annotated[str | None, Cookie(alias=SESSION_COOKIE)] = None,
) -> DataQualityDataset:
    project = _data_quality_project_or_404(db, project_id, user)

    filename = upload.filename or ""
    suffix = Path(filename).suffix.lower()
    if suffix not in ALLOWED_EXTENSIONS:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Unsupported file extension '{suffix}'. Upload an .xlsx.",
        )

    mime = upload.content_type or "application/octet-stream"
    if mime not in ALLOWED_MIMES:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Unsupported mime type for .xlsx: {mime}",
        )

    contents = upload.file.read()
    size = len(contents)
    if size == 0:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="Empty file"
        )
    if size > MAX_UPLOAD_BYTES:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                f"File too large: {size} bytes "
                f"(max {MAX_UPLOAD_BYTES} bytes)"
            ),
        )

    sha = hashlib.sha256(contents).hexdigest()

    # Reject re-uploads of the exact same file to keep the dataset list clean.
    existing = (
        db.query(DataQualityDataset)
        .filter_by(project_id=project.id, file_sha256=sha)
        .one_or_none()
    )
    if existing is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                f"This file (sha256={sha}) is already uploaded to this "
                f"project as dataset {existing.id}."
            ),
        )

    target = _dataset_dir(project.id) / f"{sha}.xlsx"
    target.write_bytes(contents)

    try:
        summary = inspect_workbook(target)
    except PasswordProtectedError as e:
        target.unlink(missing_ok=True)
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail=str(e)
        ) from e
    except BadWorkbookError as e:
        target.unlink(missing_ok=True)
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail=str(e)
        ) from e

    sheets_json = json.dumps([asdict(s) for s in summary.sheets])

    row = DataQualityDataset(
        project_id=project.id,
        original_filename=filename,
        local_path=str(target),
        file_sha256=sha,
        size_bytes=size,
        sheets_json=sheets_json,
        engine_version=INSPECTOR_VERSION,
    )
    db.add(row)
    db.flush()  # need row.id before profiling

    # Synchronously profile. The plan calls for this so the dashboard has
    # numbers as soon as the upload returns; for 10k-row workbooks it
    # completes in well under a second.
    try:
        profile_dataset(db, row)
    except Exception as e:  # noqa: BLE001 - any failure invalidates the upload
        db.rollback()
        target.unlink(missing_ok=True)
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Profiling failed: {e}",
        ) from e

    # Annotation runs as a FastAPI BackgroundTask so a wide workbook
    # (many columns -> many issues -> many LLM batches) doesn't make the
    # upload request itself block past browser/proxy timeouts. We mark the
    # status 'running' here, commit, and return; the task below mutates
    # the row with a FRESH SQLAlchemy session (the request-scoped one is
    # closed once the response is sent).
    keys = session_keys.get(session_id) if session_id else None
    if keys is not None:
        row.annotation_status = "running"
        row.annotation_error = None
        db.commit()
        # Bind the background task to THIS request's engine — picks up the
        # per-test in-memory engine under pytest and the prod engine in
        # prod, with no global-singleton/dependency-override gymnastics.
        background_tasks.add_task(
            _run_annotation_in_background, db.get_bind(), row.id, keys
        )
    else:
        db.commit()
    db.refresh(row)
    return row


def _run_annotation_in_background(
    engine: Engine, dataset_id: int, keys: LlmKeys
) -> None:
    """Run AI annotation against the dataset using a fresh DB session
    bound to the same engine as the request that scheduled this task.

    Any exception here is contained — the row's annotation_status is set
    to 'failed' with the error message, so the dashboard can surface a
    degraded state. The upload that scheduled this task has already
    returned 201 to the user; nothing here can affect that response.
    """
    SessionLocal = sessionmaker(bind=engine)
    with SessionLocal() as task_db:
        dataset = (
            task_db.query(DataQualityDataset).filter_by(id=dataset_id).one_or_none()
        )
        if dataset is None:
            # The dataset was deleted between scheduling and the task
            # running. Nothing to do.
            return
        try:
            annotate_dataset(task_db, dataset, keys)
            task_db.commit()
        except Exception as e:  # noqa: BLE001 - never propagate from a bg task
            task_db.rollback()
            dataset = (
                task_db.query(DataQualityDataset)
                .filter_by(id=dataset_id)
                .one_or_none()
            )
            if dataset is not None:
                dataset.annotation_status = "failed"
                dataset.annotation_error = str(e)[:500]
                task_db.commit()


@router.delete(
    "/api/projects/{project_id}/dq/datasets/{dataset_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
def delete_dataset(
    project_id: int,
    dataset_id: int,
    user: Annotated[User, Depends(get_current_user_row)],
    db: Annotated[Session, Depends(get_db)],
) -> None:
    project = _data_quality_project_or_404(db, project_id, user)
    row = _project_dataset_or_404(db, project, dataset_id)
    Path(row.local_path).unlink(missing_ok=True)
    db.delete(row)
    db.commit()


# --- Profile + issues ---

@router.get(
    "/api/projects/{project_id}/dq/datasets/{dataset_id}/profile",
    response_model=list[DataQualitySheetProfileOut],
)
def get_profile(
    project_id: int,
    dataset_id: int,
    user: Annotated[User, Depends(get_current_user_row)],
    db: Annotated[Session, Depends(get_db)],
) -> Sequence[DataQualitySheetProfile]:
    project = _data_quality_project_or_404(db, project_id, user)
    dataset = _project_dataset_or_404(db, project, dataset_id)
    return (
        db.query(DataQualitySheetProfile)
        .filter_by(dataset_id=dataset.id)
        .order_by(DataQualitySheetProfile.id.asc())
        .all()
    )


@router.post(
    "/api/projects/{project_id}/dq/datasets/{dataset_id}/profile",
    response_model=list[DataQualitySheetProfileOut],
)
def recompute_profile(
    project_id: int,
    dataset_id: int,
    user: Annotated[User, Depends(get_current_user_row)],
    db: Annotated[Session, Depends(get_db)],
) -> Sequence[DataQualitySheetProfile]:
    project = _data_quality_project_or_404(db, project_id, user)
    dataset = _project_dataset_or_404(db, project, dataset_id)
    try:
        rows = profile_dataset(db, dataset)
    except Exception as e:  # noqa: BLE001
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Profiling failed: {e}",
        ) from e
    db.commit()
    return rows


@router.get(
    "/api/projects/{project_id}/dq/datasets/{dataset_id}/issues",
    response_model=list[DataQualityIssueOut],
)
def list_issues(
    project_id: int,
    dataset_id: int,
    user: Annotated[User, Depends(get_current_user_row)],
    db: Annotated[Session, Depends(get_db)],
    sheet: str | None = None,
    severity: str | None = None,
) -> Sequence[DataQualityIssue]:
    project = _data_quality_project_or_404(db, project_id, user)
    dataset = _project_dataset_or_404(db, project, dataset_id)
    q = db.query(DataQualityIssue).filter_by(dataset_id=dataset.id)
    if sheet is not None:
        q = q.filter(DataQualityIssue.sheet_name == sheet)
    if severity is not None:
        q = q.filter(DataQualityIssue.severity == severity)
    return q.order_by(
        DataQualityIssue.severity.desc(), DataQualityIssue.id.asc()
    ).all()


@router.patch(
    "/api/projects/{project_id}/dq/datasets/{dataset_id}/sheets/{sheet}/columns/{column}/bounds",
    response_model=list[DataQualitySheetProfileOut],
)
def set_column_bounds(
    project_id: int,
    dataset_id: int,
    sheet: str,
    column: str,
    body: DataQualityBoundsUpdate,
    user: Annotated[User, Depends(get_current_user_row)],
    db: Annotated[Session, Depends(get_db)],
) -> Sequence[DataQualitySheetProfile]:
    """Set min/max bounds for a numeric column and re-profile the dataset.

    Bounds are stored on the ColumnProfile and survive re-profiling. Setting
    both `range_min` and `range_max` to null clears the bounds. Validation
    of min <= max is enforced here, but type compatibility (column must be
    numeric) is enforced at profile time by the stats engine, which simply
    skips bounds for non-numeric columns.
    """
    if (
        body.range_min is not None
        and body.range_max is not None
        and body.range_min > body.range_max
    ):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="range_min must be <= range_max",
        )

    project = _data_quality_project_or_404(db, project_id, user)
    dataset = _project_dataset_or_404(db, project, dataset_id)

    target = (
        db.query(DataQualityColumnProfile)
        .join(
            DataQualitySheetProfile,
            DataQualityColumnProfile.sheet_profile_id == DataQualitySheetProfile.id,
        )
        .filter(
            DataQualitySheetProfile.dataset_id == dataset.id,
            DataQualitySheetProfile.sheet_name == sheet,
            DataQualityColumnProfile.name == column,
        )
        .one_or_none()
    )
    if target is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Column '{column}' on sheet '{sheet}' not found",
        )
    target.range_min = body.range_min
    target.range_max = body.range_max
    db.flush()

    try:
        rows = profile_dataset(db, dataset)
    except Exception as e:  # noqa: BLE001
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Re-profiling failed: {e}",
        ) from e
    db.commit()
    return rows


# --- Cross-analysis: functional dependencies + relationships ---

@router.get(
    "/api/projects/{project_id}/dq/datasets/{dataset_id}/functional-dependencies",
    response_model=list[DataQualityFunctionalDependencyOut],
)
def list_functional_dependencies(
    project_id: int,
    dataset_id: int,
    user: Annotated[User, Depends(get_current_user_row)],
    db: Annotated[Session, Depends(get_db)],
) -> Sequence[DataQualityFunctionalDependency]:
    project = _data_quality_project_or_404(db, project_id, user)
    dataset = _project_dataset_or_404(db, project, dataset_id)
    return (
        db.query(DataQualityFunctionalDependency)
        .filter_by(dataset_id=dataset.id)
        .order_by(
            DataQualityFunctionalDependency.sheet_name.asc(),
            DataQualityFunctionalDependency.confidence_pct.desc(),
            DataQualityFunctionalDependency.id.asc(),
        )
        .all()
    )


@router.get(
    "/api/projects/{project_id}/dq/datasets/{dataset_id}/relationships",
    response_model=list[DataQualityRelationshipOut],
)
def list_relationships(
    project_id: int,
    dataset_id: int,
    user: Annotated[User, Depends(get_current_user_row)],
    db: Annotated[Session, Depends(get_db)],
    status_filter: str | None = None,
) -> Sequence[DataQualityRelationship]:
    project = _data_quality_project_or_404(db, project_id, user)
    dataset = _project_dataset_or_404(db, project, dataset_id)
    q = db.query(DataQualityRelationship).filter_by(dataset_id=dataset.id)
    if status_filter is not None:
        q = q.filter(DataQualityRelationship.status == status_filter)
    return q.order_by(
        DataQualityRelationship.confidence_pct.desc(),
        DataQualityRelationship.id.asc(),
    ).all()


@router.patch(
    "/api/projects/{project_id}/dq/datasets/{dataset_id}/relationships/{relationship_id}",
    response_model=DataQualityRelationshipOut,
)
def update_relationship_status(
    project_id: int,
    dataset_id: int,
    relationship_id: int,
    body: DataQualityRelationshipStatusUpdate,
    user: Annotated[User, Depends(get_current_user_row)],
    db: Annotated[Session, Depends(get_db)],
) -> DataQualityRelationship:
    """Confirm or dismiss a suggested relationship.

    Confirming runs a fresh FK-violation check immediately so the user sees
    the consequences of the decision in the dashboard's issues list without
    a separate round-trip. Dismissing is a no-op for issues - we just
    record the user's judgement so re-profiling doesn't keep proposing
    the same pair.
    """
    project = _data_quality_project_or_404(db, project_id, user)
    dataset = _project_dataset_or_404(db, project, dataset_id)

    rel = (
        db.query(DataQualityRelationship)
        .filter_by(id=relationship_id, dataset_id=dataset.id)
        .one_or_none()
    )
    if rel is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Relationship not found"
        )

    now = datetime.now(timezone.utc)
    if body.status == "confirmed":
        rel.status = "confirmed"
        rel.confirmed_at = now
        rel.dismissed_at = None
    else:  # dismissed
        rel.status = "dismissed"
        rel.dismissed_at = now
        rel.confirmed_at = None
    # Flush so _capture_relationship_decisions() inside profile_dataset
    # observes the new status (the app session has autoflush=False).
    db.flush()

    # Re-evaluate FK-violation issues for THIS dataset so the dashboard
    # reflects the user's decision immediately. We trigger a full re-
    # profile (cheap for the workbook sizes we support) so any prior
    # FK-violation issues from this pair are cleared on a dismissal, and
    # fresh ones are emitted on a confirmation.
    try:
        profile_dataset(db, dataset)
    except Exception as e:  # noqa: BLE001
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Re-profiling after status change failed: {e}",
        ) from e
    db.commit()

    # The rel row was expunged inside profile_dataset; reload by composite
    # key so the response carries the freshly-persisted row.
    refreshed = (
        db.query(DataQualityRelationship)
        .filter_by(
            dataset_id=dataset.id,
            parent_sheet=rel.parent_sheet,
            parent_column=rel.parent_column,
            child_sheet=rel.child_sheet,
            child_column=rel.child_column,
        )
        .one()
    )
    return refreshed


# --- AI annotation (manual retry) ---

@router.post(
    "/api/projects/{project_id}/dq/datasets/{dataset_id}/annotate",
    response_model=DataQualityDatasetOut,
)
def recompute_annotations(
    project_id: int,
    dataset_id: int,
    background_tasks: BackgroundTasks,
    user: Annotated[User, Depends(get_current_user_row)],
    db: Annotated[Session, Depends(get_db)],
    session_id: Annotated[str | None, Cookie(alias=SESSION_COOKIE)] = None,
) -> DataQualityDataset:
    """Re-run the AI annotator over every issue in the dataset.

    Same background-task pattern as the upload path: missing/invalid LLM
    key is a hard 400 (because the user explicitly clicked "annotate"),
    but the LLM round-trips themselves run in the background so a wide
    workbook with many issues doesn't make the request hang past
    browser/proxy timeouts. The response returns the dataset row with
    annotation_status='running'; the frontend polls until done.
    """
    project = _data_quality_project_or_404(db, project_id, user)
    dataset = _project_dataset_or_404(db, project, dataset_id)

    keys: LlmKeys | None = session_keys.get(session_id) if session_id else None
    if keys is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="LLM API key not configured. Set it in Chat Settings.",
        )
    dataset.annotation_status = "running"
    dataset.annotation_error = None
    db.commit()
    db.refresh(dataset)
    background_tasks.add_task(
        _run_annotation_in_background, db.get_bind(), dataset.id, keys
    )
    return dataset


# --- Chat (scoped to data_quality, bound to one dataset) ---


def _ensure_dq_thread(db: Session, project: Project) -> ChatThread:
    """Return the project's single data_quality chat thread, creating it on
    first use. Part 6 keeps DQ to one thread per project; the chat panel
    doesn't expose multi-thread management for this module."""
    thread = (
        db.query(ChatThread)
        .filter_by(project_id=project.id, scope=DQ_SCOPE)
        .order_by(ChatThread.created_at.asc(), ChatThread.id.asc())
        .first()
    )
    if thread is not None:
        return thread
    thread = ChatThread(
        project_id=project.id, scope=DQ_SCOPE, title="Data Quality chat"
    )
    db.add(thread)
    db.commit()
    db.refresh(thread)
    return thread


@router.get(
    "/api/projects/{project_id}/dq/datasets/{dataset_id}/chat",
    response_model=list[ChatMessageOut],
)
def list_dq_chat(
    project_id: int,
    dataset_id: int,
    user: Annotated[User, Depends(get_current_user_row)],
    db: Annotated[Session, Depends(get_db)],
) -> list[ChatMessage]:
    project = _data_quality_project_or_404(db, project_id, user)
    _project_dataset_or_404(db, project, dataset_id)
    thread = _ensure_dq_thread(db, project)
    return (
        db.query(ChatMessage)
        .filter_by(project_id=project.id, thread_id=thread.id, scope=DQ_SCOPE)
        .order_by(ChatMessage.created_at.asc(), ChatMessage.id.asc())
        .all()
    )


def _format_sse(event_type: str, data: dict | None = None) -> str:
    payload = json.dumps(data or {}, default=str)
    return f"event: {event_type}\ndata: {payload}\n\n"


@router.post(
    "/api/projects/{project_id}/dq/datasets/{dataset_id}/chat/stream",
)
def stream_dq_chat(
    project_id: int,
    dataset_id: int,
    body: ChatMessageCreate,
    user: Annotated[User, Depends(get_current_user_row)],
    db: Annotated[Session, Depends(get_db)],
    session_id: Annotated[str | None, Cookie(alias=SESSION_COOKIE)] = None,
) -> StreamingResponse:
    project = _data_quality_project_or_404(db, project_id, user)
    dataset = _project_dataset_or_404(db, project, dataset_id)

    if session_id is None or session_id not in session_keys:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="LLM API key not configured. Set it in Chat Settings.",
        )
    keys = session_keys[session_id]
    thread = _ensure_dq_thread(db, project)

    dispatch = make_dq_tool_dispatch(dataset.id)

    def event_stream():
        try:
            for event in run_agent_turn_stream(
                db=db,
                project_id=project.id,
                thread_id=thread.id,
                user_message=body.content,
                keys=keys,
                system_prompt=DQ_SYSTEM_PROMPT,
                tools=DQ_TOOLS,
                tool_dispatch=dispatch,
                scope=DQ_SCOPE,
            ):
                yield _format_sse(event["type"], event.get("data") or {})
            yield _format_sse("done")
        except Exception as e:  # noqa: BLE001 - surface as SSE error
            yield _format_sse("error", {"message": str(e)})

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


# ============================================================================
# Epic 3 — Record-Level Similarity Scoring (US 3.1–3.6)
# ============================================================================


def _facts_for_sheet(
    db: Session, dataset: DataQualityDataset, sheet_name: str
) -> list[ColumnFacts]:
    """Build ColumnFacts from the persisted profile (Part-1 stats engine).

    The heuristic recommender keys on semantic_type + pattern_label, both
    of which live on DataQualityColumnProfile. Falls back to an empty
    list when no profile exists for the sheet — the upload path
    auto-profiles, so this only happens in pathological cases."""
    sheet = (
        db.query(DataQualitySheetProfile)
        .filter_by(dataset_id=dataset.id, sheet_name=sheet_name)
        .one_or_none()
    )
    if sheet is None:
        return []
    out: list[ColumnFacts] = []
    for col in sheet.columns:
        avg_len: float | None = None
        # Approximate avg string length from the top-values list; the
        # full distribution isn't persisted, but the recommender only
        # needs a rough magnitude (short vs long) to route between
        # Levenshtein and Jaccard.
        top = col.top_values or []
        if top:
            try:
                avg_len = sum(len(str(v.get("value", ""))) for v in top) / len(top)
            except (TypeError, ValueError):
                avg_len = None
        out.append(
            ColumnFacts(
                name=col.name,
                semantic_type=col.semantic_type,
                pattern_label=col.pattern_label,
                avg_value_length=avg_len,
                distinct_pct=col.distinct_pct or 100.0,
            )
        )
    return out


def _config_or_none(
    db: Session, dataset_id: int
) -> DataQualityProfileConfig | None:
    return (
        db.query(DataQualityProfileConfig)
        .filter_by(dataset_id=dataset_id)
        .one_or_none()
    )


@router.get(
    "/api/projects/{project_id}/dq/datasets/{dataset_id}/similarity/config",
    response_model=DataQualityProfileConfigOut | DataQualityConfigDraftOut,
)
def get_similarity_config(
    project_id: int,
    dataset_id: int,
    user: Annotated[User, Depends(get_current_user_row)],
    db: Annotated[Session, Depends(get_db)],
):
    """Return the saved config if any; otherwise a heuristic draft.

    The draft includes the list of available sheets, a suggested
    sheet_a/sheet_b pair (the first two), and a pre-filled mapping list
    so the config page can render an editable starting point."""
    project = _data_quality_project_or_404(db, project_id, user)
    dataset = _project_dataset_or_404(db, project, dataset_id)
    existing = _config_or_none(db, dataset.id)
    if existing is not None:
        return existing

    sheets = [s["name"] for s in dataset.sheets]
    suggested_a = sheets[0] if sheets else None
    # When the workbook has only one sheet, suggest within-sheet dedup
    # (sheet_b defaults to the same sheet). The recommender will produce
    # self-mappings from identical column lists, so the user lands on a
    # fully-populated form rather than an empty Sheet B picker.
    suggested_b = sheets[1] if len(sheets) > 1 else suggested_a
    if suggested_a and suggested_b:
        facts_a = _facts_for_sheet(db, dataset, suggested_a)
        facts_b = _facts_for_sheet(db, dataset, suggested_b)
        rec = recommend_config(facts_a, facts_b)
        mappings = [
            {
                "column_a": m.column_a,
                "column_b": m.column_b,
                "algorithm": m.algorithm,
                "weight": m.weight,
                "is_important": m.is_important,
                "parser": m.parser,
                "recommended_by": m.recommended_by,
            }
            for m in rec.mappings
        ]
        normalization = rec.normalization
        threshold = rec.threshold
    else:
        mappings = []
        normalization = {}
        threshold = 0.85

    return DataQualityConfigDraftOut(
        saved=False,
        available_sheets=sheets,
        suggested_sheet_a=suggested_a,
        suggested_sheet_b=suggested_b,
        normalization=normalization,
        threshold=threshold,
        mappings=mappings,
    )


@router.put(
    "/api/projects/{project_id}/dq/datasets/{dataset_id}/similarity/config",
    response_model=DataQualityProfileConfigOut,
)
def save_similarity_config(
    project_id: int,
    dataset_id: int,
    body: DataQualityProfileConfigIn,
    user: Annotated[User, Depends(get_current_user_row)],
    db: Annotated[Session, Depends(get_db)],
) -> DataQualityProfileConfig:
    """Upsert the dataset's similarity config + mappings.

    Validations (all rejected with 400 so a known-bad config never
    survives the save):
      - sheet_a != sheet_b (cross-sheet linkage by definition)
      - both sheets must exist on the dataset
      - every mapped column must exist on the chosen sheet
      - at least one mapping must be ``is_important``
    """
    project = _data_quality_project_or_404(db, project_id, user)
    dataset = _project_dataset_or_404(db, project, dataset_id)

    # sheet_a == sheet_b is allowed and means within-sheet dedup. The
    # engine in cluster.py handles the i<j pair generation so we don't
    # self-pair rows or double-count.
    sheet_names = {s["name"] for s in dataset.sheets}
    for label, sheet in (("sheet_a", body.sheet_a), ("sheet_b", body.sheet_b)):
        if sheet not in sheet_names:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"{label}={sheet!r} is not a sheet in this workbook.",
            )

    # Per-sheet column membership check.
    def _columns_for(sheet_name: str) -> set[str]:
        sheet_profile = (
            db.query(DataQualitySheetProfile)
            .filter_by(dataset_id=dataset.id, sheet_name=sheet_name)
            .one_or_none()
        )
        if sheet_profile is None:
            return set()
        return {c.name for c in sheet_profile.columns}

    cols_a = _columns_for(body.sheet_a)
    cols_b = _columns_for(body.sheet_b)
    for m in body.mappings:
        if cols_a and m.column_a not in cols_a:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Column '{m.column_a}' not found on sheet '{body.sheet_a}'.",
            )
        if cols_b and m.column_b not in cols_b:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Column '{m.column_b}' not found on sheet '{body.sheet_b}'.",
            )

    if not any(m.is_important for m in body.mappings):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                "At least one column mapping must be marked important. "
                "Important columns drive cluster formation."
            ),
        )

    existing = _config_or_none(db, dataset.id)
    if existing is None:
        cfg = DataQualityProfileConfig(
            dataset_id=dataset.id,
            sheet_a=body.sheet_a,
            sheet_b=body.sheet_b,
            normalization_json=json.dumps(body.normalization),
            threshold=body.threshold,
            engine_version=NORMALIZE_VERSION,
        )
        db.add(cfg)
        db.flush()
    else:
        cfg = existing
        cfg.sheet_a = body.sheet_a
        cfg.sheet_b = body.sheet_b
        cfg.normalization_json = json.dumps(body.normalization)
        cfg.threshold = body.threshold
        cfg.engine_version = NORMALIZE_VERSION
        # Wipe existing mappings; the input is the new truth. Done in one
        # query so SQLAlchemy doesn't generate a per-row DELETE.
        db.query(DataQualityColumnMapping).filter_by(config_id=cfg.id).delete()
        db.flush()

    for m in body.mappings:
        db.add(
            DataQualityColumnMapping(
                config_id=cfg.id,
                column_a=m.column_a,
                column_b=m.column_b,
                algorithm=m.algorithm,
                weight=m.weight,
                is_important=m.is_important,
                parser=m.parser,
                recommended_by=m.recommended_by,
            )
        )

    # Saving the config implies the user has completed the gate step,
    # whether or not they have run yet.
    dataset.config_completed_at = datetime.now(timezone.utc)
    db.commit()
    db.refresh(cfg)
    return cfg


@router.post(
    "/api/projects/{project_id}/dq/datasets/{dataset_id}/similarity/skip",
    response_model=DataQualitySkipConfigOut,
)
def skip_similarity_config(
    project_id: int,
    dataset_id: int,
    user: Annotated[User, Depends(get_current_user_row)],
    db: Annotated[Session, Depends(get_db)],
) -> dict[str, datetime]:
    """Mark the dataset as having passed the similarity gate without
    saving a config — so the user can see the DQ dashboard without
    being forced to configure linkage they don't want."""
    project = _data_quality_project_or_404(db, project_id, user)
    dataset = _project_dataset_or_404(db, project, dataset_id)
    now = datetime.now(timezone.utc)
    dataset.config_completed_at = now
    db.commit()
    return {"config_completed_at": now}


@router.post(
    "/api/projects/{project_id}/dq/datasets/{dataset_id}/similarity/recommend",
    response_model=DataQualityRecommendOut,
)
def recommend_similarity_config(
    project_id: int,
    dataset_id: int,
    body: DataQualityRecommendIn,
    user: Annotated[User, Depends(get_current_user_row)],
    db: Annotated[Session, Depends(get_db)],
) -> dict:
    """Heuristic recommendation for a specific sheet pair.

    Distinct from GET /config: that returns either the saved config or a
    default draft over the FIRST two sheets. This endpoint takes an explicit
    sheet pair and runs the heuristic over their column profiles — used
    when the user changes the sheet dropdowns and wants the form
    auto-repopulated for the new pair."""
    project = _data_quality_project_or_404(db, project_id, user)
    dataset = _project_dataset_or_404(db, project, dataset_id)

    sheet_names = {s["name"] for s in dataset.sheets}
    if body.sheet_a not in sheet_names or body.sheet_b not in sheet_names:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="sheet_a/sheet_b must be sheets in this workbook.",
        )
    # sheet_a == sheet_b means within-sheet dedup; explicitly allowed.

    facts_a = _facts_for_sheet(db, dataset, body.sheet_a)
    facts_b = _facts_for_sheet(db, dataset, body.sheet_b)
    rec = recommend_config(facts_a, facts_b)
    return {
        "normalization": rec.normalization,
        "threshold": rec.threshold,
        "mappings": [
            {
                "column_a": m.column_a,
                "column_b": m.column_b,
                "algorithm": m.algorithm,
                "weight": m.weight,
                "is_important": m.is_important,
                "parser": m.parser,
                "recommended_by": m.recommended_by,
            }
            for m in rec.mappings
        ],
        "llm_error": None,
    }


@router.post(
    "/api/projects/{project_id}/dq/datasets/{dataset_id}/similarity/recommend-llm",
    response_model=DataQualityRecommendOut,
)
def recommend_similarity_config_with_llm(
    project_id: int,
    dataset_id: int,
    body: DataQualityRecommendIn,
    user: Annotated[User, Depends(get_current_user_row)],
    db: Annotated[Session, Depends(get_db)],
    session_id: Annotated[str | None, Cookie(alias=SESSION_COOKIE)] = None,
) -> dict:
    """Refine the supplied mappings via a single batched LLM call.

    The LLM may only change ``algorithm`` and ``parser`` per mapping —
    weight, is_important, and the mapping list itself are user decisions
    and are preserved verbatim. If the LLM response fails schema
    validation after one retry, the original mappings are returned
    unchanged with ``llm_error`` populated so the UI can surface it.
    """
    project = _data_quality_project_or_404(db, project_id, user)
    dataset = _project_dataset_or_404(db, project, dataset_id)
    keys = session_keys.get(session_id) if session_id else None
    if keys is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="LLM API key not configured. Set it in Chat Settings.",
        )

    sheet_names = {s["name"] for s in dataset.sheets}
    if body.sheet_a not in sheet_names or body.sheet_b not in sheet_names:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="sheet_a/sheet_b must be sheets in this workbook.",
        )
    if not body.existing_mappings:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="existing_mappings must not be empty.",
        )

    facts_a = _facts_for_sheet(db, dataset, body.sheet_a)
    facts_b = _facts_for_sheet(db, dataset, body.sheet_b)
    # The LLM module re-uses the heuristic RecommendedMapping struct;
    # convert from the HTTP input model.
    existing = [
        RecommendedMapping(
            column_a=m.column_a,
            column_b=m.column_b,
            algorithm=m.algorithm,
            parser=m.parser,
            weight=m.weight,
            is_important=m.is_important,
            recommended_by=m.recommended_by,
        )
        for m in body.existing_mappings
    ]
    try:
        result = refine_mappings_with_llm(
            keys, body.sheet_a, body.sheet_b, facts_a, facts_b, existing
        )
    except Exception as e:  # noqa: BLE001 - provider/network/auth failures
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"LLM call failed: {e}",
        ) from e

    return {
        "normalization": {},  # LLM does not touch normalization
        "threshold": 0.85,    # nor threshold
        "mappings": [
            {
                "column_a": m.column_a,
                "column_b": m.column_b,
                "algorithm": m.algorithm,
                "weight": m.weight,
                "is_important": m.is_important,
                "parser": m.parser,
                "recommended_by": m.recommended_by,
            }
            for m in result.mappings
        ],
        "llm_error": result.error,
    }


@router.post(
    "/api/projects/{project_id}/dq/datasets/{dataset_id}/similarity/run",
    response_model=DataQualitySimilarityRunOut,
)
def run_similarity_endpoint(
    project_id: int,
    dataset_id: int,
    user: Annotated[User, Depends(get_current_user_row)],
    db: Annotated[Session, Depends(get_db)],
) -> DataQualitySimilarityRun:
    """Execute the cluster engine against the saved config.

    Returns the persisted run row. A failed run is returned with
    ``status='failed'`` and an ``error`` message — the HTTP response
    itself is still 200 so the user always sees a row in their run
    list. Validation errors (no saved config, missing important
    mapping) surface as 400 before the run starts.
    """
    project = _data_quality_project_or_404(db, project_id, user)
    dataset = _project_dataset_or_404(db, project, dataset_id)
    cfg = _config_or_none(db, dataset.id)
    if cfg is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="No similarity config saved for this dataset.",
        )
    try:
        run = run_similarity(db, dataset, cfg)
    except SimilarityRunError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail=str(e)
        ) from e
    db.commit()
    db.refresh(run)
    return run


@router.get(
    "/api/projects/{project_id}/dq/datasets/{dataset_id}/similarity/runs",
    response_model=list[DataQualitySimilarityRunOut],
)
def list_similarity_runs(
    project_id: int,
    dataset_id: int,
    user: Annotated[User, Depends(get_current_user_row)],
    db: Annotated[Session, Depends(get_db)],
) -> Sequence[DataQualitySimilarityRun]:
    project = _data_quality_project_or_404(db, project_id, user)
    dataset = _project_dataset_or_404(db, project, dataset_id)
    return (
        db.query(DataQualitySimilarityRun)
        .filter_by(dataset_id=dataset.id)
        .order_by(DataQualitySimilarityRun.started_at.desc())
        .all()
    )


@router.get(
    "/api/projects/{project_id}/dq/datasets/{dataset_id}/similarity/runs/{run_id}/clusters",
    response_model=list[DataQualityRecordClusterOut],
)
def list_similarity_clusters(
    project_id: int,
    dataset_id: int,
    run_id: int,
    user: Annotated[User, Depends(get_current_user_row)],
    db: Annotated[Session, Depends(get_db)],
) -> Sequence[DataQualityRecordCluster]:
    project = _data_quality_project_or_404(db, project_id, user)
    dataset = _project_dataset_or_404(db, project, dataset_id)
    run = (
        db.query(DataQualitySimilarityRun)
        .filter_by(id=run_id, dataset_id=dataset.id)
        .one_or_none()
    )
    if run is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Run not found"
        )
    return (
        db.query(DataQualityRecordCluster)
        .filter_by(run_id=run.id)
        .order_by(DataQualityRecordCluster.cluster_index.asc())
        .all()
    )


@router.get(
    "/api/projects/{project_id}/dq/datasets/{dataset_id}/similarity/runs/{run_id}/clusters/{cluster_id}",
    response_model=DataQualityClusterDetailOut,
)
def get_cluster_detail(
    project_id: int,
    dataset_id: int,
    run_id: int,
    cluster_id: int,
    user: Annotated[User, Depends(get_current_user_row)],
    db: Annotated[Session, Depends(get_db)],
) -> dict:
    """Return the cluster's metadata, per-pair scores, and the actual
    A-row + B-row contents so the dashboard can render the side-by-side
    comparison without a second round-trip."""
    project = _data_quality_project_or_404(db, project_id, user)
    dataset = _project_dataset_or_404(db, project, dataset_id)
    run = (
        db.query(DataQualitySimilarityRun)
        .filter_by(id=run_id, dataset_id=dataset.id)
        .one_or_none()
    )
    if run is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Run not found"
        )
    cluster = (
        db.query(DataQualityRecordCluster)
        .filter_by(id=cluster_id, run_id=run.id)
        .one_or_none()
    )
    if cluster is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Cluster not found"
        )
    pairs = (
        db.query(DataQualityRecordPair)
        .filter_by(cluster_id=cluster.id)
        .order_by(DataQualityRecordPair.score.desc())
        .all()
    )
    a_rows = load_sheet_rows(dataset, run.sheet_a, cluster.a_members)
    b_rows = load_sheet_rows(dataset, run.sheet_b, cluster.b_members)
    return {
        "cluster": cluster,
        "pairs": pairs,
        "a_rows": a_rows,
        "b_rows": b_rows,
    }
