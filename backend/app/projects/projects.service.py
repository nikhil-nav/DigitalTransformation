"""Projects service — business logic. No FastAPI imports allowed (AC-6)."""
from __future__ import annotations

from sqlalchemy.orm import Session

import app.projects.projects_repository as repo  # registered in __init__.py


def get_active_project_type(db: Session, code: str):
    """Return an active project type or raise ValueError."""
    pt = repo.get_project_type_by_code(db, code)
    if pt is None:
        raise ValueError(f"Unknown project type: {code}")
    if not pt.is_active:
        raise ValueError(f"Project type '{code}' is not active for the MVP")
    return pt


def get_user_project_or_raise(db: Session, project_id: int, user_id: int):
    """Return a user's project or raise ValueError."""
    project = repo.get_user_project(db, project_id, user_id)
    if project is None:
        raise ValueError("Project not found")
    return project


def get_project_opportunity_or_raise(db: Session, project_id: int, opportunity_id: int):
    """Return an opportunity belonging to the project or raise ValueError."""
    opp = repo.get_project_opportunity(db, project_id, opportunity_id)
    if opp is None:
        raise ValueError("Opportunity not found")
    return opp
