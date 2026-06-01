"""IT Map Agent HTTP endpoints — Part 1.

Application inventories are uploaded xlsx workbooks for a Value Discovery
project. Stored on local disk at
``{DT_DATA_DIR}/it_map/{project_id}/{sha256}.xlsx``; only metadata sits
in the DB. 25 MB per-file cap (mirrors the DQ uploader) to bound parsing
cost.

The IT Map module is project-type-gated to ``value_discovery`` — the
agent maps to the BCM that lives on the same project, so it only makes
sense in that context.
"""
from __future__ import annotations

import hashlib
import json
import os
from collections.abc import Sequence
from dataclasses import asdict
from datetime import datetime, timezone
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
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from app.auth import SESSION_COOKIE, get_current_user_row
from app.data_quality.inspect import (
    BadWorkbookError,
    PasswordProtectedError,
    inspect_workbook,
)
from app.db import get_db
from app.it_map.run import (
    ItMapRunError,
    engine_version,
    run_it_map_agent,
)
from app.llm.session import LlmKeys, session_keys
from app.models import (
    Application,
    ApplicationCapabilityMapping,
    ApplicationInventory,
    BcmCapability,
    ITMapAgentRun,
    Project,
    User,
)
from app.schemas import (
    ApplicationCapabilityMappingCreate,
    ApplicationCapabilityMappingOut,
    ApplicationCapabilityMappingStatusUpdate,
    ApplicationInventoryOut,
    ApplicationOut,
    ITMapAgentRunOut,
)

router = APIRouter(tags=["it_map"])

VALUE_DISCOVERY_CODE = "value_discovery"
MAX_UPLOAD_BYTES = 25 * 1024 * 1024  # 25 MB — same cap as the DQ uploader
ALLOWED_EXTENSIONS = {".xlsx"}
ALLOWED_MIMES = {
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    "application/vnd.ms-excel",  # some browsers send this for .xlsx
    "application/octet-stream",  # fallback when the browser can't tell
}

IT_MAP_INVENTORY_VERSION = "1.0.0"


def _value_discovery_project_or_404(
    db: Session, project_id: int, user: User
) -> Project:
    project = (
        db.query(Project).filter_by(id=project_id, user_id=user.id).one_or_none()
    )
    if project is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Project not found"
        )
    if project.project_type.code != VALUE_DISCOVERY_CODE:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                f"IT Map endpoints are only available for "
                f"value_discovery projects "
                f"(this project is '{project.project_type.code}')."
            ),
        )
    return project


def _project_inventory_or_404(
    db: Session, project: Project, inventory_id: int
) -> ApplicationInventory:
    row = (
        db.query(ApplicationInventory)
        .filter_by(id=inventory_id, project_id=project.id)
        .one_or_none()
    )
    if row is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Inventory not found"
        )
    return row


def _data_dir() -> Path:
    # Mirror app.db._data_dir's resolution so tests and prod agree.
    return Path(
        os.environ.get(
            "DT_DATA_DIR", str(Path(__file__).resolve().parents[2] / "data")
        )
    )


def _inventory_dir(project_id: int) -> Path:
    d = _data_dir() / "it_map" / str(project_id)
    d.mkdir(parents=True, exist_ok=True)
    return d


def _pick_primary_sheet(sheets: list[dict]) -> str:
    """Pick the sheet the agent will process.

    Per the spec's single-sheet-inventory assumption: largest sheet by
    row count. Ties broken by source order. Falls back to the first
    sheet name when row counts are all zero / unknown.
    """
    if not sheets:
        raise BadWorkbookError("Workbook contains no sheets.")
    return max(sheets, key=lambda s: (s.get("row_count", 0), -sheets.index(s)))[
        "name"
    ]


@router.get(
    "/api/projects/{project_id}/it-map/inventories",
    response_model=list[ApplicationInventoryOut],
)
def list_inventories(
    project_id: int,
    user: Annotated[User, Depends(get_current_user_row)],
    db: Annotated[Session, Depends(get_db)],
) -> Sequence[ApplicationInventory]:
    project = _value_discovery_project_or_404(db, project_id, user)
    return (
        db.query(ApplicationInventory)
        .filter_by(project_id=project.id)
        .order_by(ApplicationInventory.uploaded_at.desc())
        .all()
    )


@router.post(
    "/api/projects/{project_id}/it-map/inventories",
    response_model=ApplicationInventoryOut,
    status_code=status.HTTP_201_CREATED,
)
def upload_inventory(
    project_id: int,
    user: Annotated[User, Depends(get_current_user_row)],
    db: Annotated[Session, Depends(get_db)],
    upload: Annotated[UploadFile, File()],
) -> ApplicationInventory:
    project = _value_discovery_project_or_404(db, project_id, user)

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
    existing = (
        db.query(ApplicationInventory)
        .filter_by(project_id=project.id, file_sha256=sha)
        .one_or_none()
    )
    if existing is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                f"This file (sha256={sha}) is already uploaded to this "
                f"project as inventory {existing.id}."
            ),
        )

    target = _inventory_dir(project.id) / f"{sha}.xlsx"
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

    sheets = [asdict(s) for s in summary.sheets]
    try:
        primary_sheet = _pick_primary_sheet(sheets)
    except BadWorkbookError as e:
        target.unlink(missing_ok=True)
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail=str(e)
        ) from e

    row = ApplicationInventory(
        project_id=project.id,
        original_filename=filename,
        local_path=str(target),
        file_sha256=sha,
        size_bytes=size,
        sheets_json=json.dumps(sheets),
        primary_sheet=primary_sheet,
        engine_version=IT_MAP_INVENTORY_VERSION,
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


@router.delete(
    "/api/projects/{project_id}/it-map/inventories/{inventory_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
def delete_inventory(
    project_id: int,
    inventory_id: int,
    user: Annotated[User, Depends(get_current_user_row)],
    db: Annotated[Session, Depends(get_db)],
) -> None:
    project = _value_discovery_project_or_404(db, project_id, user)
    row = _project_inventory_or_404(db, project, inventory_id)
    Path(row.local_path).unlink(missing_ok=True)
    db.delete(row)
    db.commit()


# ============================================================================
# IT Map Agent — Part 3: run endpoint + listing
# ============================================================================


@router.post(
    "/api/projects/{project_id}/it-map/inventories/{inventory_id}/run",
    response_model=ITMapAgentRunOut,
)
def trigger_run(
    project_id: int,
    inventory_id: int,
    background_tasks: BackgroundTasks,
    user: Annotated[User, Depends(get_current_user_row)],
    db: Annotated[Session, Depends(get_db)],
    session_id: Annotated[str | None, Cookie(alias=SESSION_COOKIE)] = None,
) -> ITMapAgentRun:
    """Schedule an IT Map Agent run against the inventory.

    The run row is created with ``status='running'`` and returned
    immediately; the actual agent loop runs as a FastAPI BackgroundTask
    so wide BCMs / long inventories don't block the request thread.
    The frontend polls ``GET /runs`` to flip the status badge.

    Pre-flight failures (no LLM key, no inventory) surface as 400/404
    BEFORE creating the run row, so a failed attempt doesn't leave a
    ``failed`` run lying around that wasn't really attempted.
    """
    project = _value_discovery_project_or_404(db, project_id, user)
    inventory = _project_inventory_or_404(db, project, inventory_id)

    keys: LlmKeys | None = session_keys.get(session_id) if session_id else None
    if keys is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="LLM API key not configured. Set it in Chat Settings.",
        )

    run = ITMapAgentRun(
        inventory_id=inventory.id,
        status="running",
        engine_version=engine_version(),
    )
    db.add(run)
    db.commit()
    db.refresh(run)

    background_tasks.add_task(
        _run_in_background, db.get_bind(), run.id, inventory.id, project.id, keys
    )
    return run


def _run_in_background(
    engine: Engine,
    run_id: int,
    inventory_id: int,
    project_id: int,
    keys: LlmKeys,
) -> None:
    """Execute the IT Map Agent loop with a fresh DB session bound to
    the same engine as the request that scheduled this task.

    All exceptions are contained — the run row is marked
    ``status='failed'`` with the error string preserved. The request
    that scheduled this task has already returned 200 to the user;
    nothing here can affect that response.
    """
    SessionLocal = sessionmaker(bind=engine)
    with SessionLocal() as task_db:
        run = (
            task_db.query(ITMapAgentRun).filter_by(id=run_id).one_or_none()
        )
        if run is None:
            return
        inventory = (
            task_db.query(ApplicationInventory)
            .filter_by(id=inventory_id)
            .one_or_none()
        )
        if inventory is None:
            run.status = "failed"
            run.error = "Inventory deleted before run could start"
            run.finished_at = datetime.now(timezone.utc)
            task_db.commit()
            return
        try:
            counts = run_it_map_agent(task_db, inventory, project_id, keys)
            run.status = "done"
            run.tool_call_count = counts.tool_call_count
            run.application_count = counts.application_count
            run.mapping_count = counts.mapping_count
            run.unmappable_count = counts.unmappable_count
            run.finished_at = datetime.now(timezone.utc)
            task_db.commit()
        except ItMapRunError as e:
            task_db.rollback()
            run = (
                task_db.query(ITMapAgentRun).filter_by(id=run_id).one_or_none()
            )
            if run is not None:
                run.status = "failed"
                run.error = str(e)[:500]
                run.finished_at = datetime.now(timezone.utc)
                task_db.commit()
        except Exception as e:  # noqa: BLE001 - never propagate from a bg task
            task_db.rollback()
            run = (
                task_db.query(ITMapAgentRun).filter_by(id=run_id).one_or_none()
            )
            if run is not None:
                run.status = "failed"
                run.error = f"{type(e).__name__}: {e}"[:500]
                run.finished_at = datetime.now(timezone.utc)
                task_db.commit()


@router.get(
    "/api/projects/{project_id}/it-map/inventories/{inventory_id}/runs",
    response_model=list[ITMapAgentRunOut],
)
def list_runs(
    project_id: int,
    inventory_id: int,
    user: Annotated[User, Depends(get_current_user_row)],
    db: Annotated[Session, Depends(get_db)],
) -> Sequence[ITMapAgentRun]:
    project = _value_discovery_project_or_404(db, project_id, user)
    inventory = _project_inventory_or_404(db, project, inventory_id)
    return (
        db.query(ITMapAgentRun)
        .filter_by(inventory_id=inventory.id)
        .order_by(ITMapAgentRun.started_at.desc())
        .all()
    )


@router.get(
    "/api/projects/{project_id}/it-map/inventories/{inventory_id}/applications",
    response_model=list[ApplicationOut],
)
def list_applications(
    project_id: int,
    inventory_id: int,
    user: Annotated[User, Depends(get_current_user_row)],
    db: Annotated[Session, Depends(get_db)],
) -> Sequence[Application]:
    """Return every Application materialised from this inventory with
    its full set of mappings (every status). Part 5's kanban consumes
    this; tests in Part 3 use it to verify agent output."""
    project = _value_discovery_project_or_404(db, project_id, user)
    inventory = _project_inventory_or_404(db, project, inventory_id)
    return (
        db.query(Application)
        .filter_by(inventory_id=inventory.id)
        .order_by(Application.row_index.asc())
        .all()
    )


# ============================================================================
# IT Map Agent — Part 5: user-driven mapping CRUD for the kanban
# ============================================================================


def _project_app_or_404(
    db: Session, project: Project, application_id: int
) -> Application:
    """Resolve an Application by id AND verify it belongs to an
    inventory owned by the supplied (user-owned, value_discovery)
    project. Without the join, a user could read or mutate another
    user's applications by guessing ids."""
    app = (
        db.query(Application)
        .join(
            ApplicationInventory,
            Application.inventory_id == ApplicationInventory.id,
        )
        .filter(
            Application.id == application_id,
            ApplicationInventory.project_id == project.id,
        )
        .one_or_none()
    )
    if app is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Application not found",
        )
    return app


def _project_mapping_or_404(
    db: Session, project: Project, mapping_id: int
) -> ApplicationCapabilityMapping:
    row = (
        db.query(ApplicationCapabilityMapping)
        .join(Application, ApplicationCapabilityMapping.application_id == Application.id)
        .join(
            ApplicationInventory,
            Application.inventory_id == ApplicationInventory.id,
        )
        .filter(
            ApplicationCapabilityMapping.id == mapping_id,
            ApplicationInventory.project_id == project.id,
        )
        .one_or_none()
    )
    if row is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Mapping not found"
        )
    return row


@router.get(
    "/api/projects/{project_id}/it-map/applications/{application_id}",
    response_model=ApplicationOut,
)
def get_application(
    project_id: int,
    application_id: int,
    user: Annotated[User, Depends(get_current_user_row)],
    db: Annotated[Session, Depends(get_db)],
) -> Application:
    """Single-application detail for the kanban's app drawer."""
    project = _value_discovery_project_or_404(db, project_id, user)
    return _project_app_or_404(db, project, application_id)


_VALID_STATUS_FILTERS = ("suggested", "confirmed", "dismissed")


@router.get(
    "/api/projects/{project_id}/it-map/applications",
    response_model=list[ApplicationOut],
)
def list_project_applications(
    project_id: int,
    user: Annotated[User, Depends(get_current_user_row)],
    db: Annotated[Session, Depends(get_db)],
    status_filter: str | None = None,
) -> list[Application] | list[dict]:
    """Project-scoped list of every Application across all of the
    project's inventories.

    Without ``status_filter``: returns every app with every mapping. The
    inventory-scoped ``GET /inventories/{id}/applications`` exists for
    the kanban; this endpoint is for the project-wide BCM graph view
    (US 2.1) where one graph spans every inventory.

    With ``status_filter`` (one of suggested/confirmed/dismissed):
    returns only apps that have AT LEAST ONE mapping of that status,
    and their ``mappings`` list is filtered to that status only. The
    BCM graph passes ``status_filter=confirmed`` so it only renders
    user-vouched mappings as edges.

    Filtering builds the response dicts directly rather than mutating
    each Application's ``.mappings`` relationship — that relationship
    has ``cascade='all, delete-orphan'``, so reassigning it would
    cascade-delete the dropped mappings on commit.
    """
    project = _value_discovery_project_or_404(db, project_id, user)
    if status_filter is not None and status_filter not in _VALID_STATUS_FILTERS:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                f"status_filter must be one of {list(_VALID_STATUS_FILTERS)} "
                f"(got {status_filter!r})"
            ),
        )
    apps = (
        db.query(Application)
        .join(
            ApplicationInventory,
            Application.inventory_id == ApplicationInventory.id,
        )
        .filter(ApplicationInventory.project_id == project.id)
        .order_by(Application.inventory_id.asc(), Application.row_index.asc())
        .all()
    )
    if status_filter is None:
        return apps

    out: list[dict] = []
    for app in apps:
        kept = [m for m in app.mappings if m.status == status_filter]
        if not kept:
            continue
        out.append(
            {
                "id": app.id,
                "inventory_id": app.inventory_id,
                "sheet_name": app.sheet_name,
                "row_index": app.row_index,
                "raw_row": app.raw_row,
                "inferred_name": app.inferred_name,
                "inferred_description": app.inferred_description,
                "inferred_business_function": app.inferred_business_function,
                "inferred_technology": app.inferred_technology,
                "inferred_owner": app.inferred_owner,
                "inferred_criticality": app.inferred_criticality,
                "inferred_lifecycle": app.inferred_lifecycle,
                "unmappable_reason": app.unmappable_reason,
                "created_at": app.created_at,
                "mappings": [
                    {
                        "id": m.id,
                        "capability_id": m.capability_id,
                        "confidence": m.confidence,
                        "rationale": m.rationale,
                        "status": m.status,
                        "engine_version": m.engine_version,
                        "created_at": m.created_at,
                        "updated_at": m.updated_at,
                        "confirmed_at": m.confirmed_at,
                        "dismissed_at": m.dismissed_at,
                    }
                    for m in kept
                ],
            }
        )
    return out


@router.patch(
    "/api/projects/{project_id}/it-map/mappings/{mapping_id}",
    response_model=ApplicationCapabilityMappingOut,
)
def update_mapping_status(
    project_id: int,
    mapping_id: int,
    body: ApplicationCapabilityMappingStatusUpdate,
    user: Annotated[User, Depends(get_current_user_row)],
    db: Annotated[Session, Depends(get_db)],
) -> ApplicationCapabilityMapping:
    """Confirm or dismiss a mapping.

    Stamps the corresponding ``*_at`` timestamp and clears the opposite
    one — so a user can revise (confirm a previously-dismissed mapping,
    or vice versa) without a stale timestamp suggesting both states
    happened simultaneously. The agent's re-run policy honours the
    LATEST status, so flipping a dismissed mapping back to confirmed
    works correctly across subsequent runs."""
    project = _value_discovery_project_or_404(db, project_id, user)
    mapping = _project_mapping_or_404(db, project, mapping_id)
    now = datetime.now(timezone.utc)
    if body.status == "confirmed":
        mapping.status = "confirmed"
        mapping.confirmed_at = now
        mapping.dismissed_at = None
    else:  # dismissed
        mapping.status = "dismissed"
        mapping.dismissed_at = now
        mapping.confirmed_at = None
    db.commit()
    db.refresh(mapping)
    return mapping


@router.post(
    "/api/projects/{project_id}/it-map/mappings",
    response_model=ApplicationCapabilityMappingOut,
    status_code=status.HTTP_201_CREATED,
)
def create_mapping(
    project_id: int,
    body: ApplicationCapabilityMappingCreate,
    user: Annotated[User, Depends(get_current_user_row)],
    db: Annotated[Session, Depends(get_db)],
) -> ApplicationCapabilityMapping:
    """User-driven mapping creation (the kanban's "Add mapping" button).

    Differs from the agent's ``propose_mapping`` in three ways:

      - ``engine_version='user'`` so audits can distinguish.
      - ``status='confirmed'`` immediately — the user explicitly created
        this, so no suggested-stage review is needed.
      - On a (application_id, capability_id) collision with a prior
        mapping, returns 409 surfacing the existing mapping's id. The
        client should PATCH that existing mapping if it wants to change
        its status, not POST a duplicate.

    The capability MUST be at level 2 (mirroring the agent's tool
    enforcement) so the kanban cannot end up with cards under L1 or L3
    columns by accident."""
    project = _value_discovery_project_or_404(db, project_id, user)
    app = _project_app_or_404(db, project, body.application_id)
    cap = (
        db.query(BcmCapability)
        .filter_by(id=body.capability_id, project_id=project.id)
        .one_or_none()
    )
    if cap is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Capability not found in this project",
        )
    if cap.level != 2:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                f"capability_id {cap.id} is at level {cap.level}; only "
                f"L2 capabilities are valid mapping targets."
            ),
        )
    existing = (
        db.query(ApplicationCapabilityMapping)
        .filter_by(application_id=app.id, capability_id=cap.id)
        .one_or_none()
    )
    if existing is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                f"Mapping already exists with id={existing.id} "
                f"(status={existing.status}). PATCH it instead of POSTing."
            ),
        )
    now = datetime.now(timezone.utc)
    row = ApplicationCapabilityMapping(
        application_id=app.id,
        capability_id=cap.id,
        confidence=1.0,
        rationale=body.rationale,
        status="confirmed",
        engine_version="user",
        confirmed_at=now,
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return row
