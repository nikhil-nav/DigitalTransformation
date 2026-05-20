"""Threads module Pydantic schemas — no ORM, no FastAPI imports."""
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

ChatRole = Literal["user", "assistant"]


class ChatThreadCreate(BaseModel):
    title: str | None = Field(default=None, max_length=200)


class ChatThreadUpdate(BaseModel):
    title: str = Field(min_length=1, max_length=200)


class ChatThreadOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    project_id: int
    title: str
    created_at: datetime
    updated_at: datetime


class Citation(BaseModel):
    url: str
    title: str
    cited_text: str | None = None


class ChatMessageCreate(BaseModel):
    content: str = Field(min_length=1, max_length=10_000)
    file_ids: list[int] | None = None
    thread_id: int | None = None


class ChatMessageOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    role: ChatRole
    content: str
    thinking: str | None = None
    citations: list[Citation] = Field(default_factory=list)
    model_provider: str | None
    model_id: str | None
    created_at: datetime
