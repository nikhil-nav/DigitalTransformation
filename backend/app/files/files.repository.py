"""Files repository — SQLAlchemy queries only. No FastAPI imports allowed."""
from __future__ import annotations

from sqlalchemy.orm import Session


def list_project_files(db: Session, project_id: int):
    """Return all BcmFile rows for a project ordered by upload time descending."""
    from app.models import BcmFile
    return (
        db.query(BcmFile)
        .filter_by(project_id=project_id)
        .order_by(BcmFile.uploaded_at.desc())
        .all()
    )


def get_file(db: Session, file_id: int, project_id: int):
    """Return a BcmFile row or None."""
    from app.models import BcmFile
    return db.query(BcmFile).filter_by(id=file_id, project_id=project_id).one_or_none()


def create_file(
    db: Session,
    project_id: int,
    anthropic_file_id: str,
    original_filename: str,
    kind: str,
    mime_type: str,
    size_bytes: int,
):
    """Insert a BcmFile row and return it."""
    from app.models import BcmFile
    row = BcmFile(
        project_id=project_id,
        anthropic_file_id=anthropic_file_id,
        original_filename=original_filename,
        kind=kind,
        mime_type=mime_type,
        size_bytes=size_bytes,
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


def delete_file(db: Session, row) -> None:
    """Delete a BcmFile row."""
    db.delete(row)
    db.commit()
