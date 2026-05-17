from dataclasses import dataclass
from typing import Literal

LlmProvider = Literal["anthropic", "openai"]

# Allowed model variants per provider, exposed in the LlmSettings UI.
ANTHROPIC_MODELS = (
    "claude-opus-4-7",
    "claude-sonnet-4-6",
    "claude-haiku-4-5-20251001",
)
OPENAI_MODELS = (
    "gpt-4o",
    "gpt-4o-mini",
)
ALLOWED_MODELS_BY_PROVIDER: dict[LlmProvider, tuple[str, ...]] = {
    "anthropic": ANTHROPIC_MODELS,
    "openai": OPENAI_MODELS,
}


@dataclass
class LlmKeys:
    provider: LlmProvider
    llm_api_key: str
    # User-selected model variant. None means "use the provider default".
    model: str | None = None


# Maps auth session_id -> LlmKeys. Lives in process memory only; cleared on
# logout and on backend restart. Same security profile as auth.sessions.
session_keys: dict[str, LlmKeys] = {}
