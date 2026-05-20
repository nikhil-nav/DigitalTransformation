from typing import Literal

from pydantic import BaseModel, Field

from app.llm.session import LlmProvider


class LoginRequest(BaseModel):
    username: str
    password: str


class UserResponse(BaseModel):
    username: str


class LlmKeysRequest(BaseModel):
    provider: Literal["anthropic", "openai"]
    llm_api_key: str = Field(min_length=10)
    model: str | None = None


class LlmKeysStatus(BaseModel):
    provider: LlmProvider | None = None
    llm_configured: bool
    model: str | None = None
    available_models: list[str] = Field(default_factory=list)
