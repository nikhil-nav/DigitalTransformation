"""Tests for the LLM keys endpoints, the agent loop (with both providers mocked),
and the SSRF/security guards on the network-touching tools."""
from __future__ import annotations

import json
from types import SimpleNamespace
from typing import Any

import pytest

from app.auth import SESSION_COOKIE, sessions
from app.llm.session import session_keys
from app.llm.tools import fetch_url, set_capabilities
from app.models import BcmCapability, User


# --- helpers ---

def login_as(client, db, username: str = "user"):
    user = db.query(User).filter_by(username=username).one_or_none()
    if user is None:
        user = User(username=username)
        db.add(user)
        db.commit()
        db.refresh(user)
    session_id = f"test-session-{username}"
    sessions[session_id] = username
    client.cookies.set(SESSION_COOKIE, session_id)
    return user, session_id


def make_value_discovery_project(client):
    r = client.post(
        "/api/projects",
        json={"name": "BCM", "project_type_code": "value_discovery"},
    )
    assert r.status_code == 201
    return r.json()["id"]


def _ensure_default_thread(db, project_id: int) -> int:
    """Create a default chat thread for a project and return its id."""
    from app.models import ChatThread

    thread = ChatThread(project_id=project_id, scope="bcm", title="test thread")
    db.add(thread)
    db.commit()
    db.refresh(thread)
    return thread.id


# --- Mock Anthropic SDK ---

class FakeTextBlock:
    type = "text"

    def __init__(self, text: str) -> None:
        self.text = text

    def model_dump(self, **_: Any) -> dict[str, Any]:
        return {"type": "text", "text": self.text}


class FakeToolUseBlock:
    type = "tool_use"

    def __init__(self, id: str, name: str, input: dict[str, Any]) -> None:
        self.id = id
        self.name = name
        self.input = input

    def model_dump(self, **_: Any) -> dict[str, Any]:
        return {
            "type": "tool_use",
            "id": self.id,
            "name": self.name,
            "input": self.input,
        }


class FakeResponse:
    def __init__(self, content: list[Any], stop_reason: str) -> None:
        self.content = content
        self.stop_reason = stop_reason


class FakeMessages:
    def __init__(self, scripted: list[FakeResponse]) -> None:
        self._scripted = list(scripted)
        self.calls: list[dict[str, Any]] = []

    def create(self, **kwargs: Any) -> FakeResponse:
        self.calls.append(kwargs)
        if not self._scripted:
            raise RuntimeError("FakeMessages: ran out of scripted responses")
        return self._scripted.pop(0)


class FakeAnthropic:
    last: "FakeAnthropic | None" = None

    def __init__(self, scripted: list[FakeResponse], **kwargs: Any) -> None:
        self.api_key = kwargs.get("api_key")
        self.messages = FakeMessages(scripted)
        FakeAnthropic.last = self


def install_mock_anthropic(monkeypatch, scripted: list[FakeResponse]) -> None:
    def factory(**kwargs: Any) -> FakeAnthropic:
        return FakeAnthropic(scripted, **kwargs)

    monkeypatch.setattr("app.llm.anthropic_provider.Anthropic", factory)


# --- Mock OpenAI SDK ---

class FakeOpenAICompletions:
    def __init__(self, scripted: list[Any]) -> None:
        self._scripted = list(scripted)
        self.calls: list[dict[str, Any]] = []

    def create(self, **kwargs: Any) -> Any:
        self.calls.append(kwargs)
        if not self._scripted:
            raise RuntimeError("FakeOpenAICompletions: ran out of scripted responses")
        return self._scripted.pop(0)


class FakeOpenAI:
    last: "FakeOpenAI | None" = None

    def __init__(self, scripted: list[Any], **kwargs: Any) -> None:
        self.api_key = kwargs.get("api_key")
        self.chat = SimpleNamespace(completions=FakeOpenAICompletions(scripted))
        FakeOpenAI.last = self


def openai_completion(
    text: str | None = None,
    tool_calls: list[tuple[str, str, dict[str, Any]]] | None = None,
) -> SimpleNamespace:
    tc_list = []
    for tid, tname, targs in tool_calls or []:
        tc_list.append(
            SimpleNamespace(
                id=tid,
                type="function",
                function=SimpleNamespace(
                    name=tname, arguments=json.dumps(targs)
                ),
            )
        )
    message = SimpleNamespace(content=text, tool_calls=tc_list or None)
    return SimpleNamespace(choices=[SimpleNamespace(message=message)])


def install_mock_openai(monkeypatch, scripted: list[Any]) -> None:
    def factory(**kwargs: Any) -> FakeOpenAI:
        return FakeOpenAI(scripted, **kwargs)

    monkeypatch.setattr("app.llm.openai_provider.OpenAI", factory)


# --- Streaming fakes ---


class FakeAnthropicStream:
    """Mimics the context manager returned by `client.messages.stream(...)`."""

    def __init__(self, events: list[Any], final_message: Any) -> None:
        self._events = list(events)
        self._final = final_message

    def __enter__(self) -> "FakeAnthropicStream":
        return self

    def __exit__(self, *_: Any) -> None:
        return None

    def __iter__(self):
        return iter(self._events)

    def get_final_message(self) -> Any:
        return self._final


class FakeAnthropicMessagesStream:
    def __init__(self, scripted_streams: list[FakeAnthropicStream]) -> None:
        self._scripted = list(scripted_streams)
        self.stream_calls: list[dict[str, Any]] = []

    def stream(self, **kwargs: Any) -> FakeAnthropicStream:
        self.stream_calls.append(kwargs)
        if not self._scripted:
            raise RuntimeError(
                "FakeAnthropicMessagesStream: out of scripted streams"
            )
        return self._scripted.pop(0)


class FakeAnthropicStreaming:
    last: "FakeAnthropicStreaming | None" = None

    def __init__(
        self, scripted: list[FakeAnthropicStream], **kwargs: Any
    ) -> None:
        self.api_key = kwargs.get("api_key")
        self.messages = FakeAnthropicMessagesStream(scripted)
        FakeAnthropicStreaming.last = self


def anthropic_stream(
    text: str | None = None,
    tool_uses: list[tuple[str, str, dict[str, Any]]] | None = None,
) -> FakeAnthropicStream:
    """Build a scripted Anthropic stream."""
    events: list[SimpleNamespace] = []
    blocks: list[Any] = []

    if text:
        events.append(
            SimpleNamespace(
                type="content_block_delta",
                delta=SimpleNamespace(type="text_delta", text=text),
            )
        )
        blocks.append(FakeTextBlock(text))

    for tu_id, tu_name, tu_input in tool_uses or []:
        block = FakeToolUseBlock(tu_id, tu_name, tu_input)
        events.append(
            SimpleNamespace(type="content_block_stop", content_block=block)
        )
        blocks.append(block)

    final = SimpleNamespace(content=blocks)
    return FakeAnthropicStream(events, final)


def install_mock_anthropic_streaming(
    monkeypatch, scripted: list[FakeAnthropicStream]
) -> None:
    def factory(**kwargs: Any) -> FakeAnthropicStreaming:
        return FakeAnthropicStreaming(scripted, **kwargs)

    monkeypatch.setattr("app.llm.anthropic_provider.Anthropic", factory)


def openai_stream_chunks(
    text: str | None = None,
    tool_calls: list[tuple[str, str, dict[str, Any]]] | None = None,
) -> list[SimpleNamespace]:
    """Build a list of streamed OpenAI chunks."""
    chunks: list[SimpleNamespace] = []
    if text:
        chunks.append(
            SimpleNamespace(
                choices=[
                    SimpleNamespace(
                        delta=SimpleNamespace(content=text, tool_calls=None),
                        finish_reason=None,
                    )
                ]
            )
        )
    for i, (tc_id, tc_name, tc_input) in enumerate(tool_calls or []):
        chunks.append(
            SimpleNamespace(
                choices=[
                    SimpleNamespace(
                        delta=SimpleNamespace(
                            content=None,
                            tool_calls=[
                                SimpleNamespace(
                                    index=i,
                                    id=tc_id,
                                    function=SimpleNamespace(
                                        name=tc_name,
                                        arguments=json.dumps(tc_input),
                                    ),
                                )
                            ],
                        ),
                        finish_reason=None,
                    )
                ]
            )
        )
    chunks.append(
        SimpleNamespace(
            choices=[
                SimpleNamespace(
                    delta=SimpleNamespace(content=None, tool_calls=None),
                    finish_reason="tool_calls" if tool_calls else "stop",
                )
            ]
        )
    )
    return chunks


class FakeOpenAIStreamCompletions:
    def __init__(self, scripted_chunks: list[list[SimpleNamespace]]) -> None:
        self._scripted = list(scripted_chunks)
        self.calls: list[dict[str, Any]] = []

    def create(self, **kwargs: Any):
        self.calls.append(kwargs)
        if not self._scripted:
            raise RuntimeError(
                "FakeOpenAIStreamCompletions: out of scripted chunks"
            )
        return iter(self._scripted.pop(0))


class FakeOpenAIStreaming:
    last: "FakeOpenAIStreaming | None" = None

    def __init__(
        self, scripted: list[list[SimpleNamespace]], **kwargs: Any
    ) -> None:
        self.api_key = kwargs.get("api_key")
        self.chat = SimpleNamespace(
            completions=FakeOpenAIStreamCompletions(scripted)
        )
        FakeOpenAIStreaming.last = self


def install_mock_openai_streaming(
    monkeypatch, scripted: list[list[SimpleNamespace]]
) -> None:
    def factory(**kwargs: Any) -> FakeOpenAIStreaming:
        return FakeOpenAIStreaming(scripted, **kwargs)

    monkeypatch.setattr("app.llm.openai_provider.OpenAI", factory)


# --- LLM keys endpoint ---

def test_set_llm_keys_requires_auth(client):
    r = client.post(
        "/api/auth/llm-keys",
        json={"provider": "anthropic", "llm_api_key": "sk-ant-test12345"},
    )
    assert r.status_code == 401


def test_get_llm_keys_default_unconfigured(client, db):
    login_as(client, db)
    r = client.get("/api/auth/llm-keys")
    assert r.status_code == 200
    body = r.json()
    assert body["llm_configured"] is False
    assert body["provider"] is None


def test_set_then_get_llm_keys(client, db):
    login_as(client, db)
    r = client.post(
        "/api/auth/llm-keys",
        json={
            "provider": "anthropic",
            "llm_api_key": "sk-ant-test12345",
        },
    )
    assert r.status_code == 200
    # Part 5 added a `model` field (None when caller didn't pick one) and
    # the `available_models` catalogue per provider.
    body = r.json()
    assert body["provider"] == "anthropic"
    assert body["llm_configured"] is True
    assert body["model"] is None
    assert "claude-sonnet-4-6" in body["available_models"]

    follow = client.get("/api/auth/llm-keys").json()
    assert follow["llm_configured"] is True


def test_set_llm_keys_validates_provider(client, db):
    login_as(client, db)
    r = client.post(
        "/api/auth/llm-keys",
        json={"provider": "bogus", "llm_api_key": "sk-ant-test12345"},
    )
    assert r.status_code == 422


def test_clear_llm_keys(client, db):
    login_as(client, db)
    client.post(
        "/api/auth/llm-keys",
        json={"provider": "anthropic", "llm_api_key": "sk-ant-test12345"},
    )
    r = client.delete("/api/auth/llm-keys")
    assert r.status_code == 200
    assert r.json()["llm_configured"] is False


def test_logout_clears_llm_keys(client, db):
    login_as(client, db)
    client.post(
        "/api/auth/llm-keys",
        json={"provider": "anthropic", "llm_api_key": "sk-ant-test12345"},
    )
    # session id is in client cookie jar
    session_id = client.cookies.get(SESSION_COOKIE)
    assert session_id in session_keys

    client.post("/api/auth/logout")
    assert session_id not in session_keys


# --- Agent loop ---

def _set_keys(
    client,
    *,
    provider: str = "anthropic",
) -> None:
    payload: dict[str, Any] = {
        "provider": provider,
        "llm_api_key": "sk-test1234567890abcd",
    }
    r = client.post("/api/auth/llm-keys", json=payload)
    assert r.status_code == 200


def test_agent_text_only_response(client, db, monkeypatch):
    login_as(client, db)
    pid = make_value_discovery_project(client)
    _set_keys(client)

    install_mock_anthropic(
        monkeypatch,
        [FakeResponse([FakeTextBlock("Hello! Which company?")], "end_turn")],
    )

    r = client.post(f"/api/projects/{pid}/chat", json={"content": "Hi"})
    assert r.status_code == 201
    msgs = r.json()
    assert len(msgs) == 2
    assert msgs[0]["role"] == "user"
    assert msgs[1]["role"] == "assistant"
    assert "Which company" in msgs[1]["content"]
    assert msgs[1]["model_provider"] == "anthropic"


def test_agent_calls_set_capabilities_and_persists_tree(client, db, monkeypatch):
    login_as(client, db)
    pid = make_value_discovery_project(client)
    _set_keys(client)

    tree = [
        {
            "name": "Customer Management",
            "description": "Acquire and serve customers",
            "children": [
                {
                    "name": "Acquisition",
                    "children": [{"name": "Lead capture"}],
                }
            ],
        }
    ]
    install_mock_anthropic(
        monkeypatch,
        [
            FakeResponse(
                [FakeToolUseBlock("t1", "set_capabilities", {"tree": tree})],
                "tool_use",
            ),
            FakeResponse(
                [FakeTextBlock("Drafted the BCM. Want to refine?")],
                "end_turn",
            ),
        ],
    )

    r = client.post(
        f"/api/projects/{pid}/chat",
        json={"content": "Build a BCM for a SaaS company"},
    )
    assert r.status_code == 201
    msgs = r.json()
    assert "Drafted" in msgs[1]["content"]

    db.expire_all()
    caps = client.get(f"/api/projects/{pid}/capabilities").json()
    by_name = {c["name"]: c for c in caps}
    assert set(by_name.keys()) == {
        "Customer Management",
        "Acquisition",
        "Lead capture",
    }
    assert by_name["Customer Management"]["level"] == 1
    assert by_name["Customer Management"]["parent_id"] is None
    assert by_name["Acquisition"]["level"] == 2
    assert (
        by_name["Acquisition"]["parent_id"]
        == by_name["Customer Management"]["id"]
    )
    assert by_name["Lead capture"]["level"] == 3
    assert by_name["Lead capture"]["parent_id"] == by_name["Acquisition"]["id"]


def test_agent_unknown_tool_returns_error_to_model(client, db, monkeypatch):
    login_as(client, db)
    pid = make_value_discovery_project(client)
    _set_keys(client)

    install_mock_anthropic(
        monkeypatch,
        [
            FakeResponse(
                [FakeToolUseBlock("t1", "nonexistent_tool", {})],
                "tool_use",
            ),
            FakeResponse(
                [FakeTextBlock("Sorry, that tool isn't available.")],
                "end_turn",
            ),
        ],
    )

    r = client.post(f"/api/projects/{pid}/chat", json={"content": "Try it"})
    assert r.status_code == 201
    # The follow-up Claude call should have received a tool_result with is_error=True
    last_call = FakeAnthropic.last.messages.calls[-1]
    last_user = [m for m in last_call["messages"] if m["role"] == "user"][-1]
    tool_results = last_user["content"]
    assert any(
        block.get("is_error") and "Unknown tool" in block.get("content", "")
        for block in tool_results
    )


def test_agent_replaces_existing_tree_on_set_capabilities(
    client, db, monkeypatch
):
    login_as(client, db)
    pid = make_value_discovery_project(client)
    _set_keys(client)

    # seed a stray L1 directly
    db.add(
        BcmCapability(
            project_id=pid, parent_id=None, level=1, name="Stale", position=0
        )
    )
    db.commit()

    install_mock_anthropic(
        monkeypatch,
        [
            FakeResponse(
                [
                    FakeToolUseBlock(
                        "t1",
                        "set_capabilities",
                        {"tree": [{"name": "Fresh"}]},
                    )
                ],
                "tool_use",
            ),
            FakeResponse([FakeTextBlock("Done.")], "end_turn"),
        ],
    )

    client.post(f"/api/projects/{pid}/chat", json={"content": "Replace"})

    db.expire_all()
    names = [
        c.name for c in db.query(BcmCapability).filter_by(project_id=pid).all()
    ]
    assert names == ["Fresh"]


def test_anthropic_tools_include_server_web_search(
    client, db, monkeypatch
):
    """Anthropic always sees the server-side web_search tool now."""
    login_as(client, db)
    pid = make_value_discovery_project(client)
    _set_keys(client)

    install_mock_anthropic(
        monkeypatch,
        [FakeResponse([FakeTextBlock("ok")], "end_turn")],
    )

    client.post(f"/api/projects/{pid}/chat", json={"content": "Hi"})

    sent_tools = FakeAnthropic.last.messages.calls[0]["tools"]
    sent_names = {t["name"] for t in sent_tools}
    assert "web_search" in sent_names
    assert {"fetch_url", "extract_pdf", "set_capabilities"}.issubset(sent_names)
    web_search_tool = next(t for t in sent_tools if t["name"] == "web_search")
    assert web_search_tool["type"] == "web_search_20250305"


def test_anthropic_call_includes_thinking_kwarg(client, db, monkeypatch):
    login_as(client, db)
    pid = make_value_discovery_project(client)
    _set_keys(client)

    install_mock_anthropic(
        monkeypatch,
        [FakeResponse([FakeTextBlock("ok")], "end_turn")],
    )
    client.post(f"/api/projects/{pid}/chat", json={"content": "Hi"})

    kwargs = FakeAnthropic.last.messages.calls[0]
    assert "thinking" in kwargs
    assert kwargs["thinking"]["type"] == "enabled"
    assert kwargs["thinking"]["budget_tokens"] >= 1024


def test_anthropic_call_marks_cache_control(client, db, monkeypatch):
    login_as(client, db)
    pid = make_value_discovery_project(client)
    _set_keys(client)

    install_mock_anthropic(
        monkeypatch,
        [FakeResponse([FakeTextBlock("ok")], "end_turn")],
    )
    client.post(f"/api/projects/{pid}/chat", json={"content": "Hi"})

    kwargs = FakeAnthropic.last.messages.calls[0]
    # System is now a list of blocks with a cache breakpoint at the end.
    assert isinstance(kwargs["system"], list)
    assert kwargs["system"][-1].get("cache_control") == {"type": "ephemeral"}
    # Last tool also carries a cache breakpoint.
    assert kwargs["tools"][-1].get("cache_control") == {"type": "ephemeral"}


def test_openai_tools_exclude_server_web_search(client, db, monkeypatch):
    login_as(client, db)
    pid = make_value_discovery_project(client)
    _set_keys(client, provider="openai")

    install_mock_openai(monkeypatch, [openai_completion(text="ok")])
    client.post(f"/api/projects/{pid}/chat", json={"content": "Hi"})

    sent_tools = FakeOpenAI.last.chat.completions.calls[0]["tools"]
    names = {t["function"]["name"] for t in sent_tools}
    assert "web_search" not in names
    assert {"fetch_url", "extract_pdf", "set_capabilities"} == names


# --- SSRF guards ---

def test_fetch_url_rejects_non_http_scheme():
    with pytest.raises(ValueError, match="http"):
        fetch_url("ftp://example.com/file")


def test_fetch_url_rejects_loopback_ip():
    with pytest.raises(ValueError, match="private|loopback|reserved"):
        fetch_url("http://127.0.0.1/")


def test_fetch_url_rejects_localhost_hostname():
    with pytest.raises(ValueError, match="private|loopback|reserved"):
        fetch_url("http://localhost/")


def test_fetch_url_rejects_link_local():
    with pytest.raises(ValueError, match="private|loopback|reserved"):
        fetch_url("http://169.254.169.254/")


# --- OpenAI provider parity ---

def test_openai_text_only_response(client, db, monkeypatch):
    login_as(client, db)
    pid = make_value_discovery_project(client)
    _set_keys(client, provider="openai")

    install_mock_openai(
        monkeypatch,
        [openai_completion(text="Hi! Which company shall we map?")],
    )

    r = client.post(f"/api/projects/{pid}/chat", json={"content": "Hi"})
    assert r.status_code == 201
    msgs = r.json()
    assert msgs[1]["model_provider"] == "openai"
    assert "Which company" in msgs[1]["content"]


def test_openai_calls_set_capabilities(client, db, monkeypatch):
    login_as(client, db)
    pid = make_value_discovery_project(client)
    _set_keys(client, provider="openai")

    tree = [
        {
            "name": "Operations",
            "children": [
                {
                    "name": "Order Fulfilment",
                    "children": [{"name": "Picking"}],
                }
            ],
        }
    ]
    install_mock_openai(
        monkeypatch,
        [
            openai_completion(
                tool_calls=[("call_1", "set_capabilities", {"tree": tree})]
            ),
            openai_completion(text="Done."),
        ],
    )

    r = client.post(
        f"/api/projects/{pid}/chat",
        json={"content": "Build a BCM for a logistics company"},
    )
    assert r.status_code == 201

    db.expire_all()
    caps = client.get(f"/api/projects/{pid}/capabilities").json()
    by_name = {c["name"]: c for c in caps}
    assert set(by_name.keys()) == {"Operations", "Order Fulfilment", "Picking"}
    assert by_name["Operations"]["level"] == 1
    assert by_name["Order Fulfilment"]["level"] == 2
    assert by_name["Picking"]["level"] == 3


def test_openai_translates_tools_to_function_format(client, db, monkeypatch):
    """OpenAI gets only the client-side tools (web_search server tool dropped)."""
    login_as(client, db)
    pid = make_value_discovery_project(client)
    _set_keys(client, provider="openai")

    install_mock_openai(monkeypatch, [openai_completion(text="ok")])
    client.post(f"/api/projects/{pid}/chat", json={"content": "Hi"})

    sent_tools = FakeOpenAI.last.chat.completions.calls[0]["tools"]
    names = {t["function"]["name"] for t in sent_tools}
    assert "set_capabilities" in names
    assert "fetch_url" in names
    assert "web_search" not in names  # Anthropic-only server tool
    for t in sent_tools:
        assert t["type"] == "function"
        assert "parameters" in t["function"]


def test_openai_unknown_tool_returns_error_to_model(client, db, monkeypatch):
    login_as(client, db)
    pid = make_value_discovery_project(client)
    _set_keys(client, provider="openai")

    install_mock_openai(
        monkeypatch,
        [
            openai_completion(
                tool_calls=[("call_1", "nonexistent_tool", {})]
            ),
            openai_completion(text="Sorry, that tool isn't available."),
        ],
    )

    r = client.post(f"/api/projects/{pid}/chat", json={"content": "Try"})
    assert r.status_code == 201

    last_call = FakeOpenAI.last.chat.completions.calls[-1]
    tool_messages = [m for m in last_call["messages"] if m["role"] == "tool"]
    assert tool_messages
    assert "Unknown tool" in tool_messages[0]["content"]


def test_openai_appends_tool_messages_per_tool_call(client, db, monkeypatch):
    """Each tool call gets its own role=tool message in the next call."""
    login_as(client, db)
    pid = make_value_discovery_project(client)
    _set_keys(client, provider="openai")

    install_mock_openai(
        monkeypatch,
        [
            openai_completion(
                tool_calls=[
                    ("call_1", "set_capabilities", {"tree": [{"name": "A"}]}),
                ]
            ),
            openai_completion(text="ok"),
        ],
    )

    client.post(f"/api/projects/{pid}/chat", json={"content": "Build"})

    second_call = FakeOpenAI.last.chat.completions.calls[1]["messages"]
    # Expect: system, user, assistant (with tool_calls), tool (call_1)
    roles = [m["role"] for m in second_call]
    assert roles[-2:] == ["assistant", "tool"]
    tool_msg = second_call[-1]
    assert tool_msg["tool_call_id"] == "call_1"


# --- Streaming helpers for new content blocks (thinking, server tools) ---


def anthropic_thinking_delta(text: str) -> SimpleNamespace:
    return SimpleNamespace(
        type="content_block_delta",
        delta=SimpleNamespace(type="thinking_delta", thinking=text),
    )


def anthropic_server_tool_use_event(
    tu_id: str, tu_name: str, tu_input: dict[str, Any]
) -> SimpleNamespace:
    block = SimpleNamespace(
        type="server_tool_use",
        id=tu_id,
        name=tu_name,
        input=tu_input,
    )
    return SimpleNamespace(type="content_block_stop", content_block=block)


def anthropic_search_result_event(
    tu_id: str, titles: list[str]
) -> SimpleNamespace:
    block = SimpleNamespace(
        type="web_search_tool_result",
        tool_use_id=tu_id,
        content=[
            {"type": "web_search_result", "title": t, "url": f"https://example/{i}"}
            for i, t in enumerate(titles)
        ],
    )
    return SimpleNamespace(type="content_block_stop", content_block=block)


class FakeThinkingBlock:
    type = "thinking"

    def __init__(self, thinking: str) -> None:
        self.thinking = thinking

    def model_dump(self, **_: Any) -> dict[str, Any]:
        return {"type": "thinking", "thinking": self.thinking}


class FakeServerToolUseBlock:
    type = "server_tool_use"

    def __init__(self, id: str, name: str, input: dict[str, Any]) -> None:
        self.id = id
        self.name = name
        self.input = input

    def model_dump(self, **_: Any) -> dict[str, Any]:
        return {
            "type": "server_tool_use",
            "id": self.id,
            "name": self.name,
            "input": self.input,
        }


class FakeWebSearchResultBlock:
    type = "web_search_tool_result"

    def __init__(self, tool_use_id: str, content: Any) -> None:
        self.tool_use_id = tool_use_id
        self.content = content

    def model_dump(self, **_: Any) -> dict[str, Any]:
        return {
            "type": "web_search_tool_result",
            "tool_use_id": self.tool_use_id,
            "content": self.content,
        }


def anthropic_stream_with_thinking_and_search(
    thinking_text: str,
    search_query: str,
    final_text: str,
) -> FakeAnthropicStream:
    """Build a stream that emits thinking, a server-side web search, then final text."""
    server_call = FakeServerToolUseBlock(
        "srv_1", "web_search", {"query": search_query}
    )
    search_result = FakeWebSearchResultBlock(
        "srv_1",
        [{"type": "web_search_result", "title": "Acme Inc - About"}],
    )
    text_block = FakeTextBlock(final_text)
    thinking_block = FakeThinkingBlock(thinking_text)

    events: list[Any] = [
        anthropic_thinking_delta(thinking_text),
        SimpleNamespace(type="content_block_stop", content_block=server_call),
        SimpleNamespace(type="content_block_stop", content_block=search_result),
        SimpleNamespace(
            type="content_block_delta",
            delta=SimpleNamespace(type="text_delta", text=final_text),
        ),
    ]
    blocks: list[Any] = [thinking_block, server_call, search_result, text_block]
    return FakeAnthropicStream(events, SimpleNamespace(content=blocks))


# --- Streaming agent (Anthropic + OpenAI) ---

def _consume_stream_events(events_iter):
    return list(events_iter)


def test_anthropic_stream_emits_text_deltas(client, db, monkeypatch):
    me = login_as(client, db)
    pid = make_value_discovery_project(client)
    _set_keys(client)

    install_mock_anthropic_streaming(
        monkeypatch,
        [anthropic_stream(text="Hello world!")],
    )

    from app.llm.agent import run_agent_turn_stream
    from app.llm.session import session_keys as _sk

    keys = next(iter(_sk.values()))
    events = _consume_stream_events(
        run_agent_turn_stream(
            db=db,
            project_id=pid,
            thread_id=_ensure_default_thread(db, pid),
            user_message="Hi",
            keys=keys,
        )
    )

    types = [e["type"] for e in events]
    assert types[0] == "user_message"
    assert types[-1] == "assistant_message"
    text_deltas = [e for e in events if e["type"] == "text_delta"]
    assert text_deltas, "expected at least one text_delta event"
    assert "".join(e["data"]["text"] for e in text_deltas) == "Hello world!"

    assistant = events[-1]["data"]
    assert assistant["content"] == "Hello world!"
    assert assistant["model_provider"] == "anthropic"


def test_anthropic_stream_emits_tool_call_and_result(client, db, monkeypatch):
    login_as(client, db)
    pid = make_value_discovery_project(client)
    _set_keys(client)

    tree = [{"name": "Customer Mgmt"}]
    install_mock_anthropic_streaming(
        monkeypatch,
        [
            anthropic_stream(
                tool_uses=[("toolu_1", "set_capabilities", {"tree": tree})]
            ),
            anthropic_stream(text="BCM ready."),
        ],
    )

    from app.llm.agent import run_agent_turn_stream
    from app.llm.session import session_keys as _sk

    keys = next(iter(_sk.values()))
    events = _consume_stream_events(
        run_agent_turn_stream(
            db=db,
            project_id=pid,
            thread_id=_ensure_default_thread(db, pid),
            user_message="Build it",
            keys=keys,
        )
    )

    type_seq = [e["type"] for e in events]
    assert type_seq.count("tool_call") == 1
    assert type_seq.count("tool_result") == 1
    # ordering: tool_call before tool_result
    assert type_seq.index("tool_call") < type_seq.index("tool_result")

    tc = next(e for e in events if e["type"] == "tool_call")
    assert tc["data"]["name"] == "set_capabilities"
    tr = next(e for e in events if e["type"] == "tool_result")
    assert tr["data"]["tool_use_id"] == "toolu_1"
    assert tr["data"]["is_error"] is False

    db.expire_all()
    caps = client.get(f"/api/projects/{pid}/capabilities").json()
    assert any(c["name"] == "Customer Mgmt" for c in caps)


def test_openai_stream_emits_text_deltas(client, db, monkeypatch):
    login_as(client, db)
    pid = make_value_discovery_project(client)
    _set_keys(client, provider="openai")

    install_mock_openai_streaming(
        monkeypatch,
        [openai_stream_chunks(text="OpenAI streaming hello")],
    )

    from app.llm.agent import run_agent_turn_stream
    from app.llm.session import session_keys as _sk

    keys = next(iter(_sk.values()))
    events = _consume_stream_events(
        run_agent_turn_stream(
            db=db,
            project_id=pid,
            thread_id=_ensure_default_thread(db, pid),
            user_message="Hi",
            keys=keys,
        )
    )

    text_deltas = [e for e in events if e["type"] == "text_delta"]
    assert text_deltas
    combined = "".join(e["data"]["text"] for e in text_deltas)
    assert combined == "OpenAI streaming hello"
    assert events[-1]["data"]["model_provider"] == "openai"


def test_openai_stream_emits_tool_call_and_result(client, db, monkeypatch):
    login_as(client, db)
    pid = make_value_discovery_project(client)
    _set_keys(client, provider="openai")

    install_mock_openai_streaming(
        monkeypatch,
        [
            openai_stream_chunks(
                tool_calls=[
                    (
                        "call_1",
                        "set_capabilities",
                        {"tree": [{"name": "Ops"}]},
                    )
                ]
            ),
            openai_stream_chunks(text="Done."),
        ],
    )

    from app.llm.agent import run_agent_turn_stream
    from app.llm.session import session_keys as _sk

    keys = next(iter(_sk.values()))
    events = _consume_stream_events(
        run_agent_turn_stream(
            db=db,
            project_id=pid,
            thread_id=_ensure_default_thread(db, pid),
            user_message="Build",
            keys=keys,
        )
    )

    types = [e["type"] for e in events]
    assert "tool_call" in types
    assert "tool_result" in types

    db.expire_all()
    caps = client.get(f"/api/projects/{pid}/capabilities").json()
    assert any(c["name"] == "Ops" for c in caps)


def test_anthropic_stream_emits_thinking_deltas(client, db, monkeypatch):
    login_as(client, db)
    pid = make_value_discovery_project(client)
    _set_keys(client)

    install_mock_anthropic_streaming(
        monkeypatch,
        [
            anthropic_stream_with_thinking_and_search(
                thinking_text="Need to look up Acme.",
                search_query="Acme Inc capabilities",
                final_text="Drafted from one source.",
            )
        ],
    )

    from app.llm.agent import run_agent_turn_stream
    from app.llm.session import session_keys as _sk

    keys = next(iter(_sk.values()))
    events = list(
        run_agent_turn_stream(
            db=db,
            project_id=pid,
            thread_id=_ensure_default_thread(db, pid),
            user_message="Build it",
            keys=keys,
        )
    )
    types = [e["type"] for e in events]

    # thinking comes through as its own event kind
    assert "thinking_delta" in types
    thinking_idx = types.index("thinking_delta")
    assert thinking_idx < types.index("assistant_message")

    # server tool call AND its result are surfaced for UI parity
    assert "tool_call" in types
    assert "tool_result" in types

    # thinking text persisted on the row
    assistant_data = events[-1]["data"]
    assert assistant_data["model_provider"] == "anthropic"

    # the persisted DB row carries thinking content
    db.expire_all()
    from app.models import ChatMessage
    row = (
        db.query(ChatMessage)
        .filter_by(project_id=pid, role="assistant")
        .order_by(ChatMessage.created_at.desc())
        .first()
    )
    assert row is not None
    assert row.thinking == "Need to look up Acme."


# --- SSE endpoint ---

def _parse_sse(raw: str) -> list[dict[str, Any]]:
    events: list[dict[str, Any]] = []
    for chunk in raw.split("\n\n"):
        chunk = chunk.strip("\r")
        if not chunk:
            continue
        evt: dict[str, Any] = {}
        for line in chunk.split("\n"):
            if line.startswith("event:"):
                evt["type"] = line[6:].strip()
            elif line.startswith("data:"):
                try:
                    evt["data"] = json.loads(line[5:].strip())
                except json.JSONDecodeError:
                    evt["data"] = {}
        if evt:
            events.append(evt)
    return events


def test_chat_stream_endpoint_returns_sse(client, db, monkeypatch):
    login_as(client, db)
    pid = make_value_discovery_project(client)
    _set_keys(client)

    install_mock_anthropic_streaming(
        monkeypatch,
        [anthropic_stream(text="Hi from SSE")],
    )

    with client.stream(
        "POST",
        f"/api/projects/{pid}/chat/stream",
        json={"content": "Hello"},
    ) as r:
        assert r.status_code == 200
        assert r.headers["content-type"].startswith("text/event-stream")
        body = "".join(r.iter_text())

    events = _parse_sse(body)
    types = [e["type"] for e in events]
    assert types[0] == "user_message"
    assert "text_delta" in types
    assert "assistant_message" in types
    assert types[-1] == "done"


def test_chat_stream_without_llm_key_returns_400(client, db):
    login_as(client, db)
    pid = make_value_discovery_project(client)
    r = client.post(
        f"/api/projects/{pid}/chat/stream",
        json={"content": "Hi"},
    )
    assert r.status_code == 400


def test_chat_stream_requires_auth(client):
    r = client.post(
        "/api/projects/1/chat/stream", json={"content": "Hi"}
    )
    assert r.status_code == 401


# --- set_capabilities tool (direct) ---

def test_set_capabilities_writes_full_tree(client, db):
    login_as(client, db)
    pid = make_value_discovery_project(client)

    set_capabilities(
        db,
        pid,
        [
            {
                "name": "L1A",
                "children": [
                    {
                        "name": "L2A",
                        "children": [
                            {"name": "L3A"},
                            {"name": "L3B"},
                        ],
                    }
                ],
            },
            {"name": "L1B"},
        ],
    )

    db.expire_all()
    caps = client.get(f"/api/projects/{pid}/capabilities").json()
    by_level = {1: [], 2: [], 3: []}
    for c in caps:
        by_level[c["level"]].append(c["name"])
    assert sorted(by_level[1]) == ["L1A", "L1B"]
    assert by_level[2] == ["L2A"]
    assert sorted(by_level[3]) == ["L3A", "L3B"]
