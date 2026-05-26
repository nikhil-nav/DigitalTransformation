"""Projects repository — SQLAlchemy queries only. No FastAPI imports allowed."""
from __future__ import annotations

from sqlalchemy.orm import Session, joinedload

# Import models via the package (models are loaded eagerly in __init__.py)
from app.projects import Project, ProjectType, ValueDiscoveryOpportunity


def get_project_type_by_code(db: Session, code: str) -> ProjectType | None:
    return db.query(ProjectType).filter_by(code=code).one_or_none()


def list_project_types(db: Session) -> list[ProjectType]:
    return db.query(ProjectType).order_by(ProjectType.id.asc()).all()


def get_user_project(db: Session, project_id: int, user_id: int) -> Project | None:
    return db.query(Project).filter_by(id=project_id, user_id=user_id).one_or_none()


def list_user_projects(db: Session, user_id: int) -> list[Project]:
    return (
        db.query(Project)
        .options(joinedload(Project.project_type))
        .filter_by(user_id=user_id)
        .order_by(Project.created_at.desc())
        .all()
    )


def create_project(
    db: Session, user_id: int, project_type_id: int, name: str, description: str | None
) -> Project:
    project = Project(
        user_id=user_id,
        project_type_id=project_type_id,
        name=name,
        description=description,
    )
    db.add(project)
    db.commit()
    db.refresh(project)
    return project


def update_project(db: Session, project: Project, **updates) -> Project:
    for key, value in updates.items():
        setattr(project, key, value)
    db.commit()
    db.refresh(project)
    return project


def delete_project(db: Session, project: Project) -> None:
    db.delete(project)
    db.commit()


def get_project_opportunity(
    db: Session, project_id: int, opportunity_id: int
) -> ValueDiscoveryOpportunity | None:
    return (
        db.query(ValueDiscoveryOpportunity)
        .filter_by(id=opportunity_id, project_id=project_id)
        .one_or_none()
    )


def list_project_opportunities(db: Session, project_id: int) -> list[ValueDiscoveryOpportunity]:
    return (
        db.query(ValueDiscoveryOpportunity)
        .filter_by(project_id=project_id)
        .order_by(ValueDiscoveryOpportunity.created_at.asc())
        .all()
    )


def create_opportunity(db: Session, project_id: int, **kwargs) -> ValueDiscoveryOpportunity:
    opp = ValueDiscoveryOpportunity(project_id=project_id, **kwargs)
    db.add(opp)
    db.commit()
    db.refresh(opp)
    return opp


def update_opportunity(db: Session, opp: ValueDiscoveryOpportunity, **updates) -> ValueDiscoveryOpportunity:
    for key, value in updates.items():
        setattr(opp, key, value)
    db.commit()
    db.refresh(opp)
    return opp


def delete_opportunity(db: Session, opp: ValueDiscoveryOpportunity) -> None:
    db.delete(opp)
    db.commit()
