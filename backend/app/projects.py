from collections.abc import Sequence
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.auth import get_current_user_row
from app.db import get_db
from app.models import Project, ProjectType, User, ValueDiscoveryOpportunity
from app.schemas import (
    OpportunityCreate,
    OpportunityOut,
    OpportunityUpdate,
    ProjectCreate,
    ProjectOut,
    ProjectTypeOut,
    ProjectUpdate,
)

router = APIRouter(tags=["projects"])


def _active_project_type(db: Session, code: str) -> ProjectType:
    pt = db.query(ProjectType).filter_by(code=code).one_or_none()
    if pt is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Unknown project type: {code}",
        )
    if not pt.is_active:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Project type '{code}' is not active for the MVP",
        )
    return pt


def _user_project_or_404(db: Session, project_id: int, user: User) -> Project:
    project = (
        db.query(Project).filter_by(id=project_id, user_id=user.id).one_or_none()
    )
    if project is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Project not found"
        )
    return project


def _project_opportunity_or_404(
    db: Session, project: Project, opportunity_id: int
) -> ValueDiscoveryOpportunity:
    opp = (
        db.query(ValueDiscoveryOpportunity)
        .filter_by(id=opportunity_id, project_id=project.id)
        .one_or_none()
    )
    if opp is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Opportunity not found"
        )
    return opp


@router.get("/api/project-types", response_model=list[ProjectTypeOut])
def list_project_types(
    _user: Annotated[User, Depends(get_current_user_row)],
    db: Annotated[Session, Depends(get_db)],
) -> Sequence[ProjectType]:
    return db.query(ProjectType).order_by(ProjectType.id.asc()).all()


@router.get("/api/projects", response_model=list[ProjectOut])
def list_projects(
    user: Annotated[User, Depends(get_current_user_row)],
    db: Annotated[Session, Depends(get_db)],
) -> Sequence[Project]:
    return (
        db.query(Project)
        .filter_by(user_id=user.id)
        .order_by(Project.created_at.desc())
        .all()
    )


@router.post(
    "/api/projects", response_model=ProjectOut, status_code=status.HTTP_201_CREATED
)
def create_project(
    body: ProjectCreate,
    user: Annotated[User, Depends(get_current_user_row)],
    db: Annotated[Session, Depends(get_db)],
) -> Project:
    pt = _active_project_type(db, body.project_type_code)
    project = Project(
        user_id=user.id,
        project_type_id=pt.id,
        name=body.name,
        description=body.description,
    )
    db.add(project)
    db.commit()
    db.refresh(project)
    return project


@router.get("/api/projects/{project_id}", response_model=ProjectOut)
def get_project(
    project_id: int,
    user: Annotated[User, Depends(get_current_user_row)],
    db: Annotated[Session, Depends(get_db)],
) -> Project:
    return _user_project_or_404(db, project_id, user)


@router.patch("/api/projects/{project_id}", response_model=ProjectOut)
def update_project(
    project_id: int,
    body: ProjectUpdate,
    user: Annotated[User, Depends(get_current_user_row)],
    db: Annotated[Session, Depends(get_db)],
) -> Project:
    project = _user_project_or_404(db, project_id, user)
    for key, value in body.model_dump(exclude_unset=True).items():
        setattr(project, key, value)
    db.commit()
    db.refresh(project)
    return project


@router.delete("/api/projects/{project_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_project(
    project_id: int,
    user: Annotated[User, Depends(get_current_user_row)],
    db: Annotated[Session, Depends(get_db)],
) -> None:
    project = _user_project_or_404(db, project_id, user)
    db.delete(project)
    db.commit()


@router.get(
    "/api/projects/{project_id}/opportunities",
    response_model=list[OpportunityOut],
)
def list_opportunities(
    project_id: int,
    user: Annotated[User, Depends(get_current_user_row)],
    db: Annotated[Session, Depends(get_db)],
) -> Sequence[ValueDiscoveryOpportunity]:
    project = _user_project_or_404(db, project_id, user)
    return (
        db.query(ValueDiscoveryOpportunity)
        .filter_by(project_id=project.id)
        .order_by(ValueDiscoveryOpportunity.created_at.asc())
        .all()
    )


@router.post(
    "/api/projects/{project_id}/opportunities",
    response_model=OpportunityOut,
    status_code=status.HTTP_201_CREATED,
)
def create_opportunity(
    project_id: int,
    body: OpportunityCreate,
    user: Annotated[User, Depends(get_current_user_row)],
    db: Annotated[Session, Depends(get_db)],
) -> ValueDiscoveryOpportunity:
    project = _user_project_or_404(db, project_id, user)
    opp = ValueDiscoveryOpportunity(project_id=project.id, **body.model_dump())
    db.add(opp)
    db.commit()
    db.refresh(opp)
    return opp


@router.patch(
    "/api/projects/{project_id}/opportunities/{opportunity_id}",
    response_model=OpportunityOut,
)
def update_opportunity(
    project_id: int,
    opportunity_id: int,
    body: OpportunityUpdate,
    user: Annotated[User, Depends(get_current_user_row)],
    db: Annotated[Session, Depends(get_db)],
) -> ValueDiscoveryOpportunity:
    project = _user_project_or_404(db, project_id, user)
    opp = _project_opportunity_or_404(db, project, opportunity_id)
    for key, value in body.model_dump(exclude_unset=True).items():
        setattr(opp, key, value)
    db.commit()
    db.refresh(opp)
    return opp


@router.delete(
    "/api/projects/{project_id}/opportunities/{opportunity_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
def delete_opportunity(
    project_id: int,
    opportunity_id: int,
    user: Annotated[User, Depends(get_current_user_row)],
    db: Annotated[Session, Depends(get_db)],
) -> None:
    project = _user_project_or_404(db, project_id, user)
    opp = _project_opportunity_or_404(db, project, opportunity_id)
    db.delete(opp)
    db.commit()
