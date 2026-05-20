"""Pydantic schemas for the projects module."""
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

ProjectStatus = Literal["draft", "active", "archived"]
OpportunityStatus = Literal["identified", "validated", "in_progress", "done"]
Effort = Literal["small", "medium", "large"]
Priority = Literal["low", "medium", "high"]


class ProjectTypeOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    code: str
    name: str
    is_active: bool


class ProjectCreate(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    description: str | None = None
    project_type_code: str


class ProjectUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=200)
    description: str | None = None
    status: ProjectStatus | None = None


class ProjectOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    name: str
    description: str | None
    status: ProjectStatus
    project_type: ProjectTypeOut
    created_at: datetime
    updated_at: datetime


class OpportunityCreate(BaseModel):
    title: str = Field(min_length=1, max_length=200)
    description: str | None = None
    business_unit: str | None = None
    estimated_annual_value_cents: int | None = Field(default=None, ge=0)
    effort: Effort | None = None
    priority: Priority | None = None
    status: OpportunityStatus = "identified"


class OpportunityUpdate(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=200)
    description: str | None = None
    business_unit: str | None = None
    estimated_annual_value_cents: int | None = Field(default=None, ge=0)
    effort: Effort | None = None
    priority: Priority | None = None
    status: OpportunityStatus | None = None


class OpportunityOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    project_id: int
    title: str
    description: str | None
    business_unit: str | None
    estimated_annual_value_cents: int | None
    effort: Effort | None
    priority: Priority | None
    status: OpportunityStatus
    created_at: datetime
    updated_at: datetime
