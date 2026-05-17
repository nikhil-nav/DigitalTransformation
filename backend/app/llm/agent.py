"""Agent loops for the BCM creation feature.

Two parallel entry points:

- `run_agent_turn` — synchronous, uses `provider.call()`, used by the
  /chat endpoint and existing pytest mocks.
- `run_agent_turn_stream` — generator, uses `provider.stream()`, used by
  the /chat/stream SSE endpoint and the live frontend chat panel.

Both share helpers below; the structural logic is duplicated on purpose to
keep each path simple and to avoid having to re-mock at the SDK streaming
level for tests that already mock at the SDK call level.

History across turns is replayed as plain user/assistant text only - we do
not forward provider-native tool transcripts between turns. Slight efficiency
hit (the agent may re-fetch URLs in a follow-up turn) for portability across
provider switches.
"""
from __future__ import annotations

import json
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from sqlalchemy.orm import Session

from app.llm.provider import Provider, ProviderResponse, ToolResult, get_provider
from app.llm.session import LlmKeys
from app.llm.tools import (
    ANTHROPIC_TOOLS as CANONICAL_TOOLS,
    extract_pdf,
    fetch_url,
    set_capabilities,
)
from app.models import ChatMessage

MAX_TOOL_TURNS = 10
BCM_SCOPE = "bcm"
MAX_TOOL_RESULT_CHARS = 30_000
MAX_TOOL_RESULT_PREVIEW_CHARS = 300
MAX_TOKENS = 4096

SYSTEM_PROMPT = """\
You are a Business Capability Map (BCM) creation agent inside an enterprise \
digital transformation platform. Each conversation is scoped to a single \
project and a single company. Your job is to produce a high-quality, \
well-sourced L1 / L2 / L3 capability map and write it to the project via the \
set_capabilities tool.

# What a Business Capability Map is (and isn't)

A capability map answers "what does this enterprise do?" - the durable \
abilities that survive across reorganisations, not the processes, projects, \
or teams that deliver them. Good capabilities are nouns (e.g. "Order \
Management"), not verbs ("Manage Orders"). Bad capabilities are processes \
(e.g. "Onboard a new customer"), org units (e.g. "Marketing Department"), \
systems (e.g. "Salesforce"), or KPIs.

Levels:
- **L1**: top-level (5-10 per company). Broad business areas. Examples: \
"Customer Management", "Product Development", "Operations", "Finance & Risk".
- **L2**: 3-7 per L1. Distinct sub-capabilities. Examples under "Customer \
Management": "Acquisition", "Onboarding", "Service", "Retention".
- **L3**: 0-5 per L2, only where the evidence supports concrete decomposition. \
Don't pad L3s for symmetry.

# Reasoning rubric (follow this)

1. **Clarify scope**. If the user hasn't given a company name and at least \
one source (URL or pasted text), ask. Don't guess at the company.
2. **Research**. Use web_search to find the company's site/about/products, \
then fetch_url for the most relevant pages. If the user supplied a PDF URL, \
use extract_pdf. Stop researching once you can answer "what does this \
company actually do" in one paragraph.
3. **Identify the business model** in one sentence to yourself before \
mapping (B2B SaaS / retail / manufacturing / services / etc.). The model \
shapes the L1 list.
4. **Enumerate L1s**. Aim for 6-8 unless the company is unusually narrow or \
broad. Cover front-office, mid-office, back-office, and enabling.
5. **Decompose to L2** under each L1. Keep them mutually exclusive at the \
same level.
6. **Add L3s** only where you have concrete evidence (the company's \
website specifically describes that sub-capability). It's fine to leave most \
L2s with no L3s.

# Tools

- `web_search` (server-side): queries the web. Use focused queries; don't \
re-query for things you already learned.
- `fetch_url`: fetches a public URL's text content.
- `extract_pdf`: downloads a PDF URL and returns extracted text.
- `set_capabilities`: REPLACES the project's full BCM with the supplied \
L1/L2/L3 tree. Call this once you have enough information; you can call \
again later to refine.

# Worked example (small but well-formed)

For a fictional regional retailer with online + physical stores, an \
acceptable starter BCM is:

```
- Customer Management
    - Customer Acquisition
        - Marketing Campaigns
        - Loyalty Programmes
    - Customer Service
        - Inquiries & Complaints
        - Returns & Refunds
- Merchandising
    - Assortment Planning
    - Pricing & Promotions
- Supply Chain
    - Procurement
    - Inventory Management
        - Replenishment
        - Stock Forecasting
    - Logistics & Distribution
- Sales Channels
    - In-Store Sales
    - E-Commerce
- Finance & Compliance
    - Accounting & Reporting
    - Tax & Regulatory
- People & Workplace
    - HR Operations
    - Talent Development
```

# Rules

- DO cite the URL or PDF page where each L1 came from when summarising your \
draft to the user.
- DO call set_capabilities exactly once per "draft" - don't make many \
small edits via the tool.
- DO ask 1-2 clarifying questions if the company has multiple distinct \
business lines, instead of guessing which to map.
- DON'T invent URLs the user didn't give you. Use web_search to find them.
- DON'T fetch the same URL twice in one turn.
- DON'T pad with vague capabilities just to hit a target count.
- DON'T list processes, systems, departments, or KPIs as capabilities.
- After calling set_capabilities, give the user a 2-3 sentence summary and \
ask if they want to refine.
"""


@dataclass
class AgentResult:
    user_message: ChatMessage
    assistant_message: ChatMessage


def _truncate(text: str, limit: int = MAX_TOOL_RESULT_CHARS) -> str:
    if len(text) <= limit:
        return text
    return text[:limit] + f"\n\n[truncated, original was {len(text)} chars]"


def _preview(text: str, limit: int = MAX_TOOL_RESULT_PREVIEW_CHARS) -> str:
    if len(text) <= limit:
        return text
    return text[:limit] + f"... [+{len(text) - limit} more chars]"


def _serialize_message(row: ChatMessage) -> dict[str, Any]:
    created = row.created_at
    if isinstance(created, datetime):
        created_str = created.isoformat()
    else:
        created_str = str(created) if created is not None else None
    return {
        "id": row.id,
        "role": row.role,
        "content": row.content,
        "model_provider": row.model_provider,
        "model_id": row.model_id,
        "created_at": created_str,
    }


def _load_text_history(
    db: Session, project_id: int, thread_id: int, scope: str = BCM_SCOPE
) -> list[dict[str, Any]]:
    rows = (
        db.query(ChatMessage)
        .filter_by(project_id=project_id, thread_id=thread_id, scope=scope)
        .order_by(ChatMessage.created_at.asc(), ChatMessage.id.asc())
        .all()
    )
    return [
        {"role": r.role, "content": r.content}
        for r in rows
    ]


def _user_message_with_attachments(
    user_text: str, attachment_file_ids: list[str], provider_name: str
) -> dict[str, Any]:
    """Build the new user message, embedding Anthropic file references when present.

    For OpenAI we fall back to plain text (file uploads aren't supported on
    that path; the upload endpoint already rejects this case).
    """
    if not attachment_file_ids or provider_name != "anthropic":
        return {"role": "user", "content": user_text}

    content_blocks: list[dict[str, Any]] = [
        {"type": "text", "text": user_text}
    ]
    for file_id in attachment_file_ids:
        # Anthropic accepts document blocks with `source: {type: "file", file_id}`
        # for both PDFs (rendered with citations) and images.
        content_blocks.append(
            {
                "type": "document",
                "source": {"type": "file", "file_id": file_id},
            }
        )
    return {"role": "user", "content": content_blocks}


def _dispatch_tool(
    name: str,
    params: dict[str, Any],
    *,
    db: Session,
    project_id: int,
    keys: LlmKeys,
) -> tuple[str, bool]:
    try:
        if name == "fetch_url":
            return _truncate(fetch_url(params["url"])), False
        if name == "extract_pdf":
            return _truncate(extract_pdf(params["url"])), False
        if name == "set_capabilities":
            outcome = set_capabilities(db, project_id, params["tree"])
            return json.dumps(outcome), False
        return f"Unknown tool: {name}", True
    except Exception as e:  # noqa: BLE001 - report any failure back to the model
        return f"Tool {name} failed: {e}", True


def _join_turn_texts(turn_texts: list[str]) -> str:
    return "\n\n".join(t.strip() for t in turn_texts if t.strip()) or "(no text response)"


def _extract_thinking_from_assistant_message(message: dict[str, Any]) -> str:
    """Pull thinking content blocks out of a provider-native assistant message."""
    content = message.get("content")
    if not isinstance(content, list):
        return ""
    parts: list[str] = []
    for block in content:
        if isinstance(block, dict) and block.get("type") == "thinking":
            text = block.get("thinking") or ""
            if text:
                parts.append(text)
    return "\n\n".join(parts)


def _summarise_search_block(block: dict[str, Any]) -> tuple[str, bool]:
    """Produce (preview, is_error) for a web_search_tool_result content block."""
    content = block.get("content")
    if isinstance(content, dict) and content.get("type") == "web_search_tool_result_error":
        return str(content.get("error_code") or "search failed"), True
    if not isinstance(content, list):
        return "(search complete)", False
    titles: list[str] = []
    for entry in content:
        if isinstance(entry, dict):
            title = entry.get("title")
            if isinstance(title, str) and title:
                titles.append(title)
    if not titles:
        return f"{len(content)} result(s)", False
    head = "; ".join(titles[:3])
    if len(titles) > 3:
        head += f" (+{len(titles) - 3} more)"
    return head, False


# --- Non-streaming path (provider.call) ---

def run_agent_turn(
    *,
    db: Session,
    project_id: int,
    thread_id: int,
    user_message: str,
    keys: LlmKeys,
    model: str | None = None,
    attachment_file_ids: list[str] | None = None,
) -> AgentResult:
    provider: Provider = get_provider(keys)
    chosen_model = model or keys.model or provider.default_model

    history = _load_text_history(db, project_id, thread_id)
    history.append(
        _user_message_with_attachments(
            user_message, attachment_file_ids or [], provider.name
        )
    )

    user_row = ChatMessage(
        project_id=project_id,
        thread_id=thread_id,
        scope=BCM_SCOPE,
        role="user",
        content=user_message,
    )
    db.add(user_row)
    db.commit()
    db.refresh(user_row)

    native_tools = provider.translate_tools(CANONICAL_TOOLS)

    messages: list[dict[str, Any]] = list(history)
    turn_texts: list[str] = []
    turn_segments: list[dict[str, Any]] = []
    completed = False

    for _ in range(MAX_TOOL_TURNS):
        response = provider.call(
            system=SYSTEM_PROMPT,
            messages=messages,
            tools=native_tools,
            model=chosen_model,
            max_tokens=MAX_TOKENS,
        )
        turn_segments.append(response.assistant_message)
        if response.text and response.text.strip():
            turn_texts.append(response.text)

        if not response.tool_uses:
            completed = True
            break

        results: list[ToolResult] = []
        for tu in response.tool_uses:
            text, is_error = _dispatch_tool(
                tu.name, tu.input, db=db, project_id=project_id, keys=keys
            )
            results.append(
                ToolResult(tool_use_id=tu.id, content=text, is_error=is_error)
            )

        messages = provider.append_tool_results(messages, response, results)

    if not completed:
        turn_texts.append(
            f"\n\n[Stopped after {MAX_TOOL_TURNS} tool turns; ask me to continue.]"
        )

    final_text = _join_turn_texts(turn_texts)
    thinking_text = "\n\n".join(
        filter(
            None,
            (_extract_thinking_from_assistant_message(seg) for seg in turn_segments),
        )
    ) or None

    assistant_row = ChatMessage(
        project_id=project_id,
        thread_id=thread_id,
        scope=BCM_SCOPE,
        role="assistant",
        content=final_text,
        raw=json.dumps(turn_segments),
        thinking=thinking_text,
        model_provider=provider.name,
        model_id=chosen_model,
    )
    db.add(assistant_row)
    db.commit()
    db.refresh(assistant_row)

    return AgentResult(user_message=user_row, assistant_message=assistant_row)


# --- Streaming path (provider.stream) ---

ToolDispatch = Callable[..., tuple[str, bool]]


def run_agent_turn_stream(
    *,
    db: Session,
    project_id: int,
    thread_id: int,
    user_message: str,
    keys: LlmKeys,
    model: str | None = None,
    attachment_file_ids: list[str] | None = None,
    system_prompt: str | None = None,
    tools: list[dict[str, Any]] | None = None,
    tool_dispatch: ToolDispatch | None = None,
    scope: str = BCM_SCOPE,
) -> Iterator[dict[str, Any]]:
    """Yields event dicts as the agent works.

    Persistence-bearing events (`user_message`, `assistant_message`) carry
    the SQLAlchemy row in a "row" key for in-process callers; the SSE
    endpoint drops that before serialising.

    Optional `system_prompt`, `tools`, `tool_dispatch`, and `scope` let other
    modules (e.g. `app.data_quality.agent`) reuse the loop with their own
    system prompt and tool set. Defaults preserve BCM behaviour.
    """
    chosen_system = system_prompt if system_prompt is not None else SYSTEM_PROMPT
    chosen_tools = tools if tools is not None else CANONICAL_TOOLS
    chosen_dispatch: ToolDispatch = tool_dispatch or _dispatch_tool

    provider: Provider = get_provider(keys)
    chosen_model = model or keys.model or provider.default_model

    history = _load_text_history(db, project_id, thread_id, scope=scope)
    history.append(
        _user_message_with_attachments(
            user_message, attachment_file_ids or [], provider.name
        )
    )

    user_row = ChatMessage(
        project_id=project_id,
        thread_id=thread_id,
        scope=scope,
        role="user",
        content=user_message,
    )
    db.add(user_row)
    db.commit()
    db.refresh(user_row)
    yield {
        "type": "user_message",
        "data": _serialize_message(user_row),
        "row": user_row,
    }

    native_tools = provider.translate_tools(chosen_tools)

    messages: list[dict[str, Any]] = list(history)
    turn_texts: list[str] = []
    turn_thinking_parts: list[str] = []
    turn_segments: list[dict[str, Any]] = []
    completed = False

    for _ in range(MAX_TOOL_TURNS):
        response: ProviderResponse | None = None
        for ev in provider.stream(
            system=chosen_system,
            messages=messages,
            tools=native_tools,
            model=chosen_model,
            max_tokens=MAX_TOKENS,
        ):
            if ev.kind == "text_delta" and ev.text:
                yield {
                    "type": "text_delta",
                    "data": {"text": ev.text},
                }
            elif ev.kind == "thinking_delta" and ev.text:
                turn_thinking_parts.append(ev.text)
                yield {
                    "type": "thinking_delta",
                    "data": {"text": ev.text},
                }
            elif ev.kind == "tool_use_complete":
                tu = ev.tool_use
                if tu is not None:
                    yield {
                        "type": "tool_call",
                        "data": {
                            "id": tu.id,
                            "name": tu.name,
                            "input": tu.input,
                        },
                    }
            elif ev.kind == "server_tool_use":
                tu = ev.tool_use
                if tu is not None:
                    yield {
                        "type": "tool_call",
                        "data": {
                            "id": tu.id,
                            "name": tu.name,
                            "input": tu.input,
                        },
                    }
            elif ev.kind == "server_tool_result":
                tr = ev.tool_result
                if tr is not None:
                    yield {
                        "type": "tool_result",
                        "data": {
                            "tool_use_id": tr.tool_use_id,
                            "is_error": tr.is_error,
                            "preview": tr.content,
                        },
                    }
            elif ev.kind == "message_complete":
                response = ev.response

        if response is None:
            raise RuntimeError(
                "Provider stream finished without message_complete"
            )

        turn_segments.append(response.assistant_message)
        if response.text and response.text.strip():
            turn_texts.append(response.text)

        if not response.tool_uses:
            completed = True
            break

        results: list[ToolResult] = []
        for tu in response.tool_uses:
            text, is_error = chosen_dispatch(
                tu.name, tu.input, db=db, project_id=project_id, keys=keys
            )
            yield {
                "type": "tool_result",
                "data": {
                    "tool_use_id": tu.id,
                    "is_error": is_error,
                    "preview": _preview(text),
                },
            }
            results.append(
                ToolResult(tool_use_id=tu.id, content=text, is_error=is_error)
            )

        messages = provider.append_tool_results(messages, response, results)

    if not completed:
        turn_texts.append(
            f"\n\n[Stopped after {MAX_TOOL_TURNS} tool turns; ask me to continue.]"
        )

    final_text = _join_turn_texts(turn_texts)
    thinking_text = "".join(turn_thinking_parts).strip() or None

    assistant_row = ChatMessage(
        project_id=project_id,
        thread_id=thread_id,
        scope=scope,
        role="assistant",
        content=final_text,
        raw=json.dumps(turn_segments),
        thinking=thinking_text,
        model_provider=provider.name,
        model_id=chosen_model,
    )
    db.add(assistant_row)
    db.commit()
    db.refresh(assistant_row)
    yield {
        "type": "assistant_message",
        "data": _serialize_message(assistant_row),
        "row": assistant_row,
    }
