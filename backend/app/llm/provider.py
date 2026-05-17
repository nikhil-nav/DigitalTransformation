"""Provider abstraction for the BCM agent loop.

Both Anthropic and OpenAI conform to this small interface so the agent loop
can be provider-agnostic. The canonical tool schema is the Anthropic format
(see `tools.py`); each provider translates as needed.

Each provider exposes two entry points:

- `call(...)` for synchronous one-shot completion (used by the non-streaming
  /chat endpoint and existing tests).
- `stream(...)` yields `StreamEvent`s as the model produces text deltas, then
  one event per finalised tool_use, then a `message_complete` carrying the
  same `ProviderResponse` shape as `call(...)`. Used by the SSE endpoint.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Iterator
from dataclasses import dataclass
from typing import Any, Literal

from app.llm.session import LlmKeys, LlmProvider


@dataclass
class ToolUse:
    id: str
    name: str
    input: dict[str, Any]


@dataclass
class ToolResult:
    tool_use_id: str
    content: str
    is_error: bool


@dataclass
class ProviderResponse:
    text: str
    tool_uses: list[ToolUse]
    """The provider-native assistant message dict; appended back to messages
    before tool results when continuing the loop."""
    assistant_message: dict[str, Any]


@dataclass
class StreamEvent:
    """Streaming event from a Provider.

    Kinds:
    - `text_delta` — `text` carries the incremental visible text fragment.
    - `thinking_delta` — `text` carries an incremental fragment of extended-thinking content.
    - `tool_use_complete` — `tool_use` carries a finalised CLIENT-side ToolUse the agent must dispatch.
    - `server_tool_use` — `tool_use` carries a finalised server-side tool call (e.g. Anthropic web_search). UI-only; no dispatch.
    - `server_tool_result` — `tool_result` carries the server-produced result for a previous server_tool_use. UI-only.
    - `message_complete` — `response` carries the full `ProviderResponse`.
    """

    kind: Literal[
        "text_delta",
        "thinking_delta",
        "tool_use_complete",
        "server_tool_use",
        "server_tool_result",
        "message_complete",
    ]
    text: str = ""
    tool_use: ToolUse | None = None
    tool_result: ToolResult | None = None
    response: ProviderResponse | None = None


class Provider(ABC):
    name: LlmProvider
    default_model: str

    def __init__(self, keys: LlmKeys) -> None:
        self.keys = keys

    @abstractmethod
    def translate_tools(self, tools: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """Translate canonical (Anthropic-shaped) tool defs to the provider's format."""

    @abstractmethod
    def call(
        self,
        *,
        system: str,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]],
        model: str,
        max_tokens: int,
    ) -> ProviderResponse:
        """Run one model call. The `messages` are role/content dicts in the
        provider's expected format. `tools` is what `translate_tools` returned."""

    @abstractmethod
    def stream(
        self,
        *,
        system: str,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]],
        model: str,
        max_tokens: int,
    ) -> Iterator[StreamEvent]:
        """Stream the model response. Yields `text_delta`s as text arrives,
        then a `tool_use_complete` per finalised tool, then exactly one
        `message_complete` with the consolidated ProviderResponse."""

    @abstractmethod
    def append_tool_results(
        self,
        messages: list[dict[str, Any]],
        response: ProviderResponse,
        results: list[ToolResult],
    ) -> list[dict[str, Any]]:
        """Append the assistant turn + tool results so the next call has them."""


def get_provider(keys: LlmKeys) -> Provider:
    if keys.provider == "anthropic":
        from app.llm.anthropic_provider import AnthropicProvider

        return AnthropicProvider(keys)
    if keys.provider == "openai":
        from app.llm.openai_provider import OpenAIProvider

        return OpenAIProvider(keys)
    raise ValueError(f"Unknown provider: {keys.provider!r}")
