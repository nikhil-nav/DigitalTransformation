"""Projects router — thin HTTP layer. Calls controller functions only."""
from collections.abc import Sequence
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.auth import get_current_user_row
from app.common.db import get_db
from app.schemas import (
    OpportunityCreate,
    OpportunityOut,
    OpportunityUpdate,
    ProjectCreate,
    ProjectOut,
    ProjectTypeOut,
    ProjectUpdate,
)

import app.projects.projects_repository as repo
from app.projects.projects_controller import (
    require_active_project_type,
    require_user_project,
    require_project_opportunity,
)

router = APIRouter(tags=["projects"])


@router.get("/api/project-types", response_model=list[ProjectTypeOut])
def list_project_types(
    _user: Annotated[object, Depends(get_current_user_row)],
    db: Annotated[Session, Depends(get_db)],
) -> Sequence:
    return repo.list_project_types(db)


@router.get("/api/projects", response_model=list[ProjectOut])
def list_projects(
    user: Annotated[object, Depends(get_current_user_row)],
    db: Annotated[Session, Depends(get_db)],
) -> Sequence:
    return repo.list_user_projects(db, user.id)


@router.post(
    "/api/projects", response_model=ProjectOut, status_code=status.HTTP_201_CREATED
)
def create_project(
    body: ProjectCreate,
    user: Annotated[object, Depends(get_current_user_row)],
    db: Annotated[Session, Depends(get_db)],
):
    pt = require_active_project_type(db, body.project_type_code)
    return repo.create_project(db, user.id, pt.id, body.name, body.description)


@router.get("/api/projects/{project_id}", response_model=ProjectOut)
def get_project(
    project_id: int,
    user: Annotated[object, Depends(get_current_user_row)],
    db: Annotated[Session, Depends(get_db)],
):
    return require_user_project(db, project_id, user)


@router.patch("/api/projects/{project_id}", response_model=ProjectOut)
def update_project(
    project_id: int,
    body: ProjectUpdate,
    user: Annotated[object, Depends(get_current_user_row)],
    db: Annotated[Session, Depends(get_db)],
):
    project = require_user_project(db, project_id, user)
    return repo.update_project(db, project, **body.model_dump(exclude_unset=True))


@router.delete("/api/projects/{project_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_project(
    project_id: int,
    user: Annotated[object, Depends(get_current_user_row)],
    db: Annotated[Session, Depends(get_db)],
) -> None:
    project = require_user_project(db, project_id, user)
    repo.delete_project(db, project)


@router.get(
    "/api/projects/{project_id}/opportunities",
    response_model=list[OpportunityOut],
)
def list_opportunities(
    project_id: int,
    user: Annotated[object, Depends(get_current_user_row)],
    db: Annotated[Session, Depends(get_db)],
) -> Sequence:
    project = require_user_project(db, project_id, user)
    return repo.list_project_opportunities(db, project.id)


@router.post(
    "/api/projects/{project_id}/opportunities",
    response_model=OpportunityOut,
    status_code=status.HTTP_201_CREATED,
)
def create_opportunity(
    project_id: int,
    body: OpportunityCreate,
    user: Annotated[object, Depends(get_current_user_row)],
    db: Annotated[Session, Depends(get_db)],
):
    project = require_user_project(db, project_id, user)
    return repo.create_opportunity(db, project.id, **body.model_dump())


@router.patch(
    "/api/projects/{project_id}/opportunities/{opportunity_id}",
    response_model=OpportunityOut,
)
def update_opportunity(
    project_id: int,
    opportunity_id: int,
    body: OpportunityUpdate,
    user: Annotated[object, Depends(get_current_user_row)],
    db: Annotated[Session, Depends(get_db)],
):
    project = require_user_project(db, project_id, user)
    opp = require_project_opportunity(db, project.id, opportunity_id)
    return repo.update_opportunity(db, opp, **body.model_dump(exclude_unset=True))


@router.delete(
    "/api/projects/{project_id}/opportunities/{opportunity_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
def delete_opportunity(
    project_id: int,
    opportunity_id: int,
    user: Annotated[object, Depends(get_current_user_row)],
    db: Annotated[Session, Depends(get_db)],
) -> None:
    project = require_user_project(db, project_id, user)
    opp = require_project_opportunity(db, project.id, opportunity_id)
    repo.delete_opportunity(db, opp)
