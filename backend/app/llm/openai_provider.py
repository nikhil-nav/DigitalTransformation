from __future__ import annotations

import json
from collections.abc import Iterator
from typing import Any

from openai import OpenAI

from app.llm.provider import (
    Provider,
    ProviderResponse,
    StreamEvent,
    ToolResult,
    ToolUse,
)


class OpenAIProvider(Provider):
    name = "openai"
    default_model = "gpt-4o"

    def __init__(self, keys) -> None:
        super().__init__(keys)
        self.client = OpenAI(api_key=keys.llm_api_key)

    def translate_tools(self, tools: list[dict[str, Any]]) -> list[dict[str, Any]]:
        # Skip Anthropic server-side tools (they have no input_schema and a
        # provider-specific "type" like "web_search_20250305" - OpenAI cannot
        # run them, so we drop them silently in "Lite" mode.
        return [
            {
                "type": "function",
                "function": {
                    "name": t["name"],
                    "description": t["description"],
                    "parameters": t["input_schema"],
                },
            }
            for t in tools
            if "input_schema" in t and "description" in t
        ]

    def call(
        self,
        *,
        system: str,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]],
        model: str,
        max_tokens: int,
    ) -> ProviderResponse:
        full_messages = [{"role": "system", "content": system}, *messages]

        completion = self.client.chat.completions.create(
            model=model,
            messages=full_messages,
            tools=tools,
            max_tokens=max_tokens,
        )
        choice = completion.choices[0].message
        text = choice.content or ""
        raw_tool_calls = list(choice.tool_calls or [])

        tool_uses: list[ToolUse] = []
        for tc in raw_tool_calls:
            args_raw = tc.function.arguments
            if isinstance(args_raw, str):
                try:
                    parsed = json.loads(args_raw) if args_raw else {}
                except json.JSONDecodeError:
                    parsed = {}
            else:
                parsed = args_raw or {}
            tool_uses.append(
                ToolUse(id=tc.id, name=tc.function.name, input=parsed)
            )

        assistant_message: dict[str, Any] = {
            "role": "assistant",
            "content": text or None,
        }
        if raw_tool_calls:
            assistant_message["tool_calls"] = [
                {
                    "id": tc.id,
                    "type": "function",
                    "function": {
                        "name": tc.function.name,
                        "arguments": tc.function.arguments,
                    },
                }
                for tc in raw_tool_calls
            ]

        return ProviderResponse(
            text=text,
            tool_uses=tool_uses,
            assistant_message=assistant_message,
        )

    def stream(
        self,
        *,
        system: str,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]],
        model: str,
        max_tokens: int,
    ) -> Iterator[StreamEvent]:
        full_messages = [{"role": "system", "content": system}, *messages]

        chunks = self.client.chat.completions.create(
            model=model,
            messages=full_messages,
            tools=tools,
            max_tokens=max_tokens,
            stream=True,
        )

        text_parts: list[str] = []
        # index -> {id, name, arguments(str), emitted(bool)}
        tool_acc: dict[int, dict[str, Any]] = {}

        for chunk in chunks:
            choices = getattr(chunk, "choices", None) or []
            if not choices:
                continue
            choice = choices[0]
            delta = getattr(choice, "delta", None)
            if delta is None:
                continue

            content = getattr(delta, "content", None)
            if content:
                text_parts.append(content)
                yield StreamEvent(kind="text_delta", text=content)

            tool_deltas = getattr(delta, "tool_calls", None) or []
            for tc_delta in tool_deltas:
                idx = getattr(tc_delta, "index", 0) or 0
                slot = tool_acc.setdefault(
                    idx,
                    {
                        "id": "",
                        "name": "",
                        "arguments": "",
                        "emitted": False,
                    },
                )
                if getattr(tc_delta, "id", None):
                    slot["id"] = tc_delta.id
                fn = getattr(tc_delta, "function", None)
                if fn is not None:
                    name = getattr(fn, "name", None)
                    if name:
                        slot["name"] = name
                    args = getattr(fn, "arguments", None)
                    if args:
                        slot["arguments"] += args

            finish_reason = getattr(choice, "finish_reason", None)
            if finish_reason:
                # Stream is wrapping up; emit any unemitted tool calls.
                for slot in tool_acc.values():
                    if slot["emitted"]:
                        continue
                    try:
                        parsed = (
                            json.loads(slot["arguments"])
                            if slot["arguments"]
                            else {}
                        )
                    except json.JSONDecodeError:
                        parsed = {}
                    tu = ToolUse(
                        id=slot["id"],
                        name=slot["name"],
                        input=parsed,
                    )
                    slot["emitted"] = True
                    slot["parsed"] = parsed
                    yield StreamEvent(kind="tool_use_complete", tool_use=tu)

        text = "".join(text_parts)
        tool_uses: list[ToolUse] = []
        raw_tool_calls: list[dict[str, Any]] = []
        for idx in sorted(tool_acc.keys()):
            slot = tool_acc[idx]
            parsed = slot.get("parsed")
            if parsed is None:
                try:
                    parsed = (
                        json.loads(slot["arguments"]) if slot["arguments"] else {}
                    )
                except json.JSONDecodeError:
                    parsed = {}
                if not slot["emitted"]:
                    yield StreamEvent(
                        kind="tool_use_complete",
                        tool_use=ToolUse(
                            id=slot["id"], name=slot["name"], input=parsed
                        ),
                    )
                    slot["emitted"] = True
            tool_uses.append(
                ToolUse(id=slot["id"], name=slot["name"], input=parsed)
            )
            raw_tool_calls.append(
                {
                    "id": slot["id"],
                    "type": "function",
                    "function": {
                        "name": slot["name"],
                        "arguments": slot["arguments"],
                    },
                }
            )

        assistant_message: dict[str, Any] = {
            "role": "assistant",
            "content": text or None,
        }
        if raw_tool_calls:
            assistant_message["tool_calls"] = raw_tool_calls

        response = ProviderResponse(
            text=text,
            tool_uses=tool_uses,
            assistant_message=assistant_message,
        )
        yield StreamEvent(kind="message_complete", response=response)

    def append_tool_results(
        self,
        messages: list[dict[str, Any]],
        response: ProviderResponse,
        results: list[ToolResult],
    ) -> list[dict[str, Any]]:
        out = list(messages)
        out.append(response.assistant_message)
        for r in results:
            out.append(
                {
                    "role": "tool",
                    "tool_call_id": r.tool_use_id,
                    "content": r.content,
                }
            )
        return out
