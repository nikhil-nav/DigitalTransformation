"""Data Quality service — business logic. No FastAPI imports allowed (AC-6)."""
from __future__ import annotations

import os
from pathlib import Path

from sqlalchemy.orm import Session

DATA_QUALITY_CODE = "data_quality_assessment"
DQ_SCOPE = "data_quality"
MAX_UPLOAD_BYTES = 25 * 1024 * 1024  # 25 MB
ALLOWED_EXTENSIONS = {".xlsx"}
ALLOWED_MIMES = {
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    "application/vnd.ms-excel",
    "application/octet-stream",
}


def get_data_dir() -> Path:
    """Resolve the data directory from the environment, mirroring app.db."""
    return Path(
        os.environ.get(
            "DT_DATA_DIR", str(Path(__file__).resolve().parents[2] / "data")
        )
    )


def get_dataset_dir(project_id: int) -> Path:
    """Return (and create) the per-project dataset storage directory."""
    d = get_data_dir() / "data_quality" / str(project_id)
    d.mkdir(parents=True, exist_ok=True)
    return d


def get_data_quality_project_or_raise(db: Session, project_id: int, user_id: int):
    """Return a DQ project or raise ValueError."""
    from app.data_quality.data_quality_repository import get_project
    project = get_project(db, project_id, user_id)
    if project is None:
        raise ValueError("Project not found")
    if project.project_type.code != DATA_QUALITY_CODE:
        raise ValueError(
            f"Data Quality endpoints are only available for "
            f"data_quality_assessment projects "
            f"(this project is '{project.project_type.code}')"
        )
    return project


def get_dataset_or_raise(db: Session, project, dataset_id: int):
    """Return a dataset belonging to the project or raise ValueError."""
    from app.data_quality.data_quality_repository import get_dataset
    row = get_dataset(db, dataset_id, project.id)
    if row is None:
        raise ValueError("Dataset not found")
    return row


def validate_upload(filename: str, size: int, suffix: str, mime: str) -> None:
    """Validate an uploaded workbook. Raises ValueError on any violation."""
    if suffix not in ALLOWED_EXTENSIONS:
        raise ValueError(
            f"Only .xlsx files are accepted (got '{suffix}')"
        )
    if mime not in ALLOWED_MIMES:
        raise ValueError(
            f"MIME type '{mime}' is not accepted for workbooks"
        )
    if size > MAX_UPLOAD_BYTES:
        raise ValueError(
            f"Upload too large: {size} bytes (max {MAX_UPLOAD_BYTES} bytes)"
        )


def require_llm_keys(session_id: str | None, session_keys: dict):
    """Return LlmKeys for the session or raise ValueError."""
    if session_id is None or session_id not in session_keys:
        raise ValueError("LLM API key not configured. Set it in Chat Settings.")
    return session_keys[session_id]
