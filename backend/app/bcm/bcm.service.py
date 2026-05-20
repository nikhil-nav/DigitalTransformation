"""BCM service — business logic. No FastAPI imports allowed (AC-6)."""
from __future__ import annotations

from sqlalchemy.orm import Session

VALUE_DISCOVERY_CODE = "value_discovery"
BCM_SCOPE = "bcm"


def get_value_discovery_project_or_raise(db: Session, project_id: int, user_id: int):
    """Return a Value Discovery project row or raise ValueError."""
    from app.bcm.bcm_repository import get_project
    project = get_project(db, project_id, user_id)
    if project is None:
        raise ValueError("Project not found")
    if project.project_type.code != VALUE_DISCOVERY_CODE:
        raise ValueError(
            f"BCM is only available for Value Discovery projects "
            f"(this project is '{project.project_type.code}')"
        )
    return project


def validate_hierarchy(db: Session, project, level: int, parent_id: int | None) -> None:
    """Validate that a capability's level/parent combo is legal, else raise ValueError."""
    from app.bcm.bcm_repository import get_parent_capability
    if level == 1:
        if parent_id is not None:
            raise ValueError("L1 capabilities cannot have a parent")
        return

    if parent_id is None:
        raise ValueError(f"L{level} capabilities require a parent")

    parent = get_parent_capability(db, parent_id, project.id)
    if parent is None:
        raise ValueError("Parent capability not found in this project")

    expected = level - 1
    if parent.level != expected:
        raise ValueError(f"L{level} parent must be L{expected}, got L{parent.level}")


def resolve_attachment_file_ids(db: Session, project, ids: list[int] | None) -> list[str]:
    """Resolve BcmFile row ids to Anthropic file IDs, raising ValueError if any missing."""
    from app.bcm.bcm_repository import get_bcm_files_by_ids
    if not ids:
        return []
    rows = get_bcm_files_by_ids(db, project.id, ids)
    found = {row.id: row for row in rows}
    missing = [i for i in ids if i not in found]
    if missing:
        raise ValueError(f"File ids not found in this project: {missing}")
    return [found[i].anthropic_file_id for i in ids]
