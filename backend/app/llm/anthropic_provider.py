from __future__ import annotations

from collections.abc import Iterator
from typing import Any

from anthropic import Anthropic

from app.llm.provider import (
    Provider,
    ProviderResponse,
    StreamEvent,
    ToolResult,
    ToolUse,
)

THINKING_BUDGET_TOKENS = 8000


def _system_blocks(system: str) -> list[dict[str, Any]]:
    """System prompt as a single text block with a cache breakpoint."""
    return [
        {
            "type": "text",
            "text": system,
            "cache_control": {"type": "ephemeral"},
        }
    ]


def _tools_with_cache(tools: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Mark the end of the tools list as a cache breakpoint."""
    if not tools:
        return tools
    out = list(tools)
    out[-1] = {**out[-1], "cache_control": {"type": "ephemeral"}}
    return out


def _summarise_search_result(content: Any) -> str:
    """Build a short preview line for a web_search_tool_result block."""
    if not isinstance(content, list):
        return "(search complete)"
    titles: list[str] = []
    for entry in content:
        if isinstance(entry, dict):
            t = entry.get("title")
            if isinstance(t, str) and t:
                titles.append(t)
    if not titles:
        return f"{len(content)} result(s)"
    head = "; ".join(titles[:3])
    if len(titles) > 3:
        head += f" (+{len(titles) - 3} more)"
    return head


def _block_dump(block: Any) -> dict[str, Any]:
    if hasattr(block, "model_dump"):
        return block.model_dump(mode="json", exclude_none=True)
    if isinstance(block, dict):
        return dict(block)
    raise TypeError(f"Cannot serialise content block: {type(block).__name__}")


class AnthropicProvider(Provider):
    name = "anthropic"
    default_model = "claude-sonnet-4-6"

    def __init__(self, keys) -> None:
        super().__init__(keys)
        self.client = Anthropic(api_key=keys.llm_api_key)

    def translate_tools(self, tools: list[dict[str, Any]]) -> list[dict[str, Any]]:
        # Canonical schema is already Anthropic-shaped.
        return tools

    def _build_response(self, content_blocks: list[dict[str, Any]]) -> ProviderResponse:
        text_parts: list[str] = []
        client_tool_uses: list[ToolUse] = []
        for block_dict in content_blocks:
            btype = block_dict.get("type")
            if btype == "text":
                text_parts.append(block_dict.get("text", ""))
            elif btype == "tool_use":
                client_tool_uses.append(
                    ToolUse(
                        id=block_dict["id"],
                        name=block_dict["name"],
                        input=block_dict.get("input") or {},
                    )
                )
            # thinking / server_tool_use / web_search_tool_result blocks
            # stay in assistant_message but don't surface as client tool_uses.
        return ProviderResponse(
            text="".join(text_parts),
            tool_uses=client_tool_uses,
            assistant_message={"role": "assistant", "content": content_blocks},
        )

    def call(
        self,
        *,
        system: str,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]],
        model: str,
        max_tokens: int,
    ) -> ProviderResponse:
        response = self.client.messages.create(
            model=model,
            max_tokens=max_tokens,
            system=_system_blocks(system),
            tools=_tools_with_cache(tools),
            messages=messages,
            thinking={
                "type": "enabled",
                "budget_tokens": THINKING_BUDGET_TOKENS,
            },
        )
        content_blocks = [_block_dump(b) for b in response.content]
        return self._build_response(content_blocks)

    def stream(
        self,
        *,
        system: str,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]],
        model: str,
        max_tokens: int,
    ) -> Iterator[StreamEvent]:
        with self.client.messages.stream(
            model=model,
            max_tokens=max_tokens,
            system=_system_blocks(system),
            tools=_tools_with_cache(tools),
            messages=messages,
            thinking={
                "type": "enabled",
                "budget_tokens": THINKING_BUDGET_TOKENS,
            },
        ) as stream:
            for event in stream:
                etype = getattr(event, "type", None)

                if etype == "content_block_delta":
                    delta = getattr(event, "delta", None)
                    delta_type = getattr(delta, "type", None)
                    if delta_type == "text_delta":
                        text = getattr(delta, "text", "")
                        if text:
                            yield StreamEvent(kind="text_delta", text=text)
                    elif delta_type == "thinking_delta":
                        thinking_text = getattr(delta, "thinking", "")
                        if thinking_text:
                            yield StreamEvent(
                                kind="thinking_delta", text=thinking_text
                            )

                elif etype == "content_block_stop":
                    block = getattr(event, "content_block", None)
                    btype = getattr(block, "type", None)
                    if btype == "tool_use":
                        yield StreamEvent(
                            kind="tool_use_complete",
                            tool_use=ToolUse(
                                id=getattr(block, "id", ""),
                                name=getattr(block, "name", ""),
                                input=getattr(block, "input", None) or {},
                            ),
                        )
                    elif btype == "server_tool_use":
                        yield StreamEvent(
                            kind="server_tool_use",
                            tool_use=ToolUse(
                                id=getattr(block, "id", ""),
                                name=getattr(block, "name", ""),
                                input=getattr(block, "input", None) or {},
                            ),
                        )
                    elif btype == "web_search_tool_result":
                        result_content = getattr(block, "content", None)
                        is_error = False
                        if isinstance(result_content, dict) and result_content.get(
                            "type"
                        ) == "web_search_tool_result_error":
                            is_error = True
                            preview = str(
                                result_content.get("error_code")
                                or "search failed"
                            )
                        else:
                            preview = _summarise_search_result(result_content)
                        yield StreamEvent(
                            kind="server_tool_result",
                            tool_result=ToolResult(
                                tool_use_id=getattr(block, "tool_use_id", ""),
                                content=preview,
                                is_error=is_error,
                            ),
                        )

            final_message = stream.get_final_message()

        content_blocks = [_block_dump(b) for b in final_message.content]
        yield StreamEvent(
            kind="message_complete",
            response=self._build_response(content_blocks),
        )

    def append_tool_results(
        self,
        messages: list[dict[str, Any]],
        response: ProviderResponse,
        results: list[ToolResult],
    ) -> list[dict[str, Any]]:
        out = list(messages)
        out.append(response.assistant_message)
        out.append(
            {
                "role": "user",
                "content": [
                    {
                        "type": "tool_result",
                        "tool_use_id": r.tool_use_id,
                        "content": r.content,
                        "is_error": r.is_error,
                    }
                    for r in results
                ],
            }
        )
        return out
