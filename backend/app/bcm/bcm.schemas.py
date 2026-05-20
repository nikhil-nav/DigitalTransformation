"""BCM Pydantic schemas — no ORM, no FastAPI imports."""
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

CapabilityLevel = Literal[1, 2, 3]
ChatRole = Literal["user", "assistant"]


class CapabilityCreate(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    description: str | None = None
    level: CapabilityLevel
    parent_id: int | None = None
    position: int | None = Field(default=None, ge=0)


class CapabilityUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=200)
    description: str | None = None
    parent_id: int | None = None
    position: int | None = Field(default=None, ge=0)


class CapabilityOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    project_id: int
    parent_id: int | None
    level: int
    name: str
    description: str | None
    position: int
    created_at: datetime
    updated_at: datetime
