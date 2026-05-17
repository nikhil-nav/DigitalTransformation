# BCM Creation Feature - Implementation Plan

A 5-part plan, gated on user approval at each part (same rule as `docs/PLAN.md`).

## Overview

The BCM (Business Capability Map) creation feature lets a user chat with an AI agent that researches a company and produces an editable L1/L2/L3 capability map, displayed in a Kanban-style viewer. It is a sub-feature of a **Value Discovery project**: each project has at most one BCM.

Source spec: [`/BCMagent.md`](../BCMagent.md).

## Locked-in decisions (from the planning conversation)

1. **Sub-feature of a Value Discovery project** - lives on the project detail page; BCM endpoints reject other project types.
2. **MVP research scope** - company website (URL), annual report (URL or PDF upload), Tavily web search. LinkedIn out of scope.
3. **Two providers** - Claude (Anthropic) + OpenAI. User picks one per session and supplies that provider's API key.
4. **API keys per-session, never persisted** - kept in the in-memory session store next to the auth session. Cleared on logout / backend restart. Same security profile as the existing fake login.
5. **Capability storage is relational** - `bcm_capabilities` (adjacency list with explicit level), see [`bcm-schema.json`](bcm-schema.json).

## Defaults committed (push back any time)

- **Kanban layout** - L1 columns, L2 cards inside, click an L2 to expand its L3 children inline. Inline add / edit / delete with confirm. Reorder via up/down buttons (no drag-and-drop in v1).
- **Chat replies** - non-streaming for v1. Single HTTP call per turn; the response can take many seconds while the agent loops through tools.
- **Chat history** - persisted in `bcm_chat_messages`. Refreshing keeps the conversation.
- **Agent behaviour** - when the agent has enough info, it writes the tree directly via a `set_capabilities` tool. The user edits afterwards in the Kanban. (Alternative "propose, then accept" flow is a future addition.)
- **Web search** - Tavily, free tier. User pastes a Tavily key alongside the LLM key. If absent, the agent falls back to URLs the user paste / its own training knowledge.
- **Opportunities UI** - explicitly out of scope for this initiative, even though the Part 6 backend supports it.

## Architecture summary

- **Frontend** - new BCM section on the project detail page (only rendered for `value_discovery` projects). Two panels: chat (left) + Kanban tree viewer (right). Settings popover on the chat header for provider + API keys.
- **Backend** - new SQLAlchemy models (`BcmCapability`, `BcmChatMessage`); new routers `/api/projects/{id}/capabilities` and `/api/projects/{id}/chat`. New `app/llm/` package containing a provider abstraction with two implementations (Anthropic, OpenAI), tool definitions, and the agent loop.
- **Auth/keys** - extend the session store from a `dict[str, str]` (session_id -> username) to `dict[str, SessionState]` where `SessionState` adds `llm_provider`, `llm_api_key`, `tavily_api_key`. Set via a new `POST /api/auth/llm-keys` endpoint; cleared on logout.

## Sign-off needed before Part B

Confirm or push back on:

1. **Schema** - two new tables, hierarchy invariants enforced in the app layer (not via DB CHECK).
2. **Project type gating** - BCM endpoints return 400 if the target project is not of type `value_discovery`.
3. **Out of scope** - opportunities UI, drag-and-drop reordering, streaming chat, "propose then accept" agent diffs, persisted API keys.

---

## Part A - Plan + schema design (this part)

Goal: lock the plan + schema on paper. No code.

Checklist:
- [x] `docs/BCM_PLAN.md` (this file)
- [x] `docs/bcm-schema.json`
- [ ] User approves Part A

Tests:
- `bcm-schema.json` is valid JSON.
- `BCM_PLAN.md` answers what to build, where, and how it's tested.

Success criteria:
- User signs off before Part B begins.

---

## Part B - Schema + manual UI (no agent yet)

Goal: prove the data model and Kanban UI work end-to-end **without an LLM**. The user can build a capability tree by hand and a stub chat shell echoes a placeholder reply.

### Backend checklist
- [ ] `BcmCapability` and `BcmChatMessage` SQLAlchemy models (matches `bcm-schema.json`).
- [ ] `init_db` creates the new tables (`create_all` is idempotent).
- [ ] Hierarchy validator: when inserting/updating a row, verify that level/parent are consistent (level=1 has no parent; level=2 parent is L1 in same project; level=3 parent is L2 in same project).
- [ ] Project-type guard helper: `_require_value_discovery(project)` that 400s otherwise.
- [ ] Endpoints (all auth-required, all user-scoped, all guarded to `value_discovery`):
  - `GET /api/projects/{id}/capabilities` - returns the full tree, ordered by `(parent_id, position)`.
  - `POST /api/projects/{id}/capabilities` - create one node.
  - `PATCH /api/projects/{id}/capabilities/{cap_id}` - rename / re-describe / reposition / move under a different parent.
  - `DELETE /api/projects/{id}/capabilities/{cap_id}` - cascades to descendants via FK.
  - `GET /api/projects/{id}/chat` - returns persisted message list.
  - `POST /api/projects/{id}/chat` - **stub**: persists the user message, persists a fixed assistant reply ("LLM integration lands in Part C"), returns both.
- [ ] Backend tests (pytest):
  - Capability CRUD happy paths.
  - Hierarchy invariants (e.g. trying to insert a level-2 with a level-2 parent returns 400).
  - Cross-user 404 on every endpoint.
  - 401 without session.
  - 400 when the project's type is not `value_discovery`.
  - Cascade delete: deleting an L1 removes its L2/L3 descendants.
  - Chat persistence + ordering by `created_at`.

### Frontend checklist
- [ ] Project detail page gains a `BcmSection` component that renders only when `project.project_type.code === "value_discovery"`.
- [ ] `KanbanBoard` component: L1 columns; each column lists L2 cards; clicking an L2 expands its L3 children inline.
- [ ] Inline add (a `+` action at the bottom of a column / a `+` on each L2 card to add an L3).
- [ ] Inline edit: click the name to rename in place; description editable in a popover or expanded view.
- [ ] Delete with the existing confirm-dialog pattern.
- [ ] Reorder: small up/down buttons.
- [ ] `ChatPanel` component: scrollable message list (assistant + user), textarea, send button. **No model picker yet.** Sends to `POST /api/projects/{id}/chat`, displays the stub reply.
- [ ] Loading + error states on every async call (matches the project list pattern).
- [ ] Vitest tests for `KanbanBoard` (renders tree, add/edit/delete) and `ChatPanel` (sends, renders messages).

### Tests / success
- All previous test suites still green.
- New backend pytest cases pass.
- New Vitest cases pass.
- Manually: a user can build a 3x3x3 tree and refresh - the structure persists.
- User approves Part B.

---

## Part C - Claude agent (single provider)

Goal: replace the chat stub with a real agent loop using Anthropic's Claude. After this part, a user can say "Build a BCM for Acme Corp, here's their site `https://acme.example/about`" and watch the Kanban populate.

### Backend checklist
- [ ] `anthropic` SDK added to `pyproject.toml`.
- [ ] `app/llm/` package:
  - `app/llm/session.py` - extend the auth `SessionState` with `llm_provider`, `llm_api_key`, `tavily_api_key`.
  - `app/llm/tools.py` - tool definitions and Python implementations:
    - `fetch_url(url: str) -> str` - GET, 5s timeout, 1 MB cap, must be http(s) and not a private IP (SSRF guard).
    - `extract_pdf(url: str) -> str` - download + parse text via `pypdf`. Same network guards.
    - `web_search(query: str) -> list[{title, url, snippet}]` - Tavily; only available if `tavily_api_key` is set.
    - `set_capabilities(tree: list[L1]) -> {ok: True}` - replace the project's capability tree with the supplied L1/L2/L3 nodes. Transactional: succeeds atomically or not at all.
    - `upsert_capability(parent_id|null, level, name, description, position) -> {id}` - granular edit.
  - `app/llm/agent.py` - the loop. Loads prior `bcm_chat_messages.raw`, appends the new user message, calls Claude with the tools, dispatches each `tool_use` block, sends results back, repeats until Claude emits a text-only stop. Persists the user row + final assistant row (with the full provider transcript in `raw`).
  - `app/llm/anthropic_provider.py` - thin wrapper around `anthropic.Anthropic`.
- [ ] System prompt: stored in code; explains the goal (build a BCM for an enterprise), the available tools, and the L1/L2/L3 conventions (with a short example).
- [ ] New endpoint: `POST /api/auth/llm-keys` accepting `{provider, llm_api_key, tavily_api_key?}`. Stores in session. `DELETE /api/auth/llm-keys` clears them. `GET /api/auth/llm-keys` returns whether keys are present (booleans only - never the keys themselves).
- [ ] Replace the chat stub in `POST /api/projects/{id}/chat`:
  - Returns 400 if no LLM key in session.
  - Runs the agent loop synchronously.
  - Returns the persisted assistant message.
- [ ] Guardrails:
  - Max 10 tool calls per turn (prevents runaway loops).
  - Each tool call wrapped in try/except; failures returned to Claude as `tool_result` with `is_error: true` so it can recover gracefully.
- [ ] Backend tests (LLM mocked - no real API calls in CI):
  - Mock `anthropic.Anthropic` to script a sequence of tool calls; assert that the agent dispatches them, persists the right rows, and writes the capability tree.
  - Tool unit tests: SSRF guard rejects `127.0.0.1`, `localhost`, `169.254.x.x`, etc. URL/PDF size caps fire.
  - 400 when the user has not set an LLM key.

### Frontend checklist
- [ ] `LlmSettings` component: provider dropdown (Claude only for now), API key field (type=password), optional Tavily key field. Calls `POST /api/auth/llm-keys` on save. Shows "Keys configured" / "Not configured" without ever displaying the keys.
- [ ] `ChatPanel`: gains the settings popover; disables send when no key is set.
- [ ] After a successful chat turn, refetch capabilities so the Kanban shows the new tree.
- [ ] Loading state while the agent runs (it can take 10-30 seconds; the spinner needs to make this obvious).
- [ ] Vitest for `LlmSettings`.

### Tests / success
- Mocked-LLM pytest covering the agent loop.
- Vitest for the settings UI.
- **Manually verified** (not automated, since it costs API tokens): chatting with a real key against `https://example.com` produces a small BCM and populates the Kanban.
- User approves Part C.

---

## Part D - Multi-provider (OpenAI added)

Goal: the same chat UI now works against either Claude or OpenAI; the user picks per session.

### Backend checklist
- [ ] `openai` SDK added.
- [ ] `app/llm/openai_provider.py` - mirrors the Anthropic wrapper. Uses OpenAI's tool-calling protocol (function calling).
- [ ] Provider abstraction in `app/llm/agent.py`: a small interface that takes (messages, tools, model) and returns either a list of tool_calls or a final text. Both providers conform.
- [ ] Tool definitions reused unchanged - the abstraction layer translates to each provider's tool schema.
- [ ] Validation: when the user sets keys, accept `provider in {"anthropic", "openai"}` only.
- [ ] Backend tests parameterised over both providers.

### Frontend checklist
- [ ] Provider dropdown gains "OpenAI" with the appropriate label and link to the OpenAI key page.
- [ ] When the user changes provider, the API key field clears (different keys per provider).

### Tests / success
- Same agent loop tests pass for both providers.
- Manually verified with a real OpenAI key on the same prompt as Part C.
- User approves Part D.

---

## Part E - Tests + polish

Goal: tighten edges; documentation current; full E2E runs locally.

Checklist:
- [ ] Empty state on the Kanban: when a project has no capabilities, show a friendly call to action ("Start a chat to draft a BCM, or add capabilities by hand.").
- [ ] Empty state on chat: a one-line hint about what to type first (with an example prompt).
- [ ] Error states on every async call (chat send, capability mutations, settings save) - reuse the existing pattern (`role="alert"` + a banner under the action).
- [ ] Update `frontend/AGENTS.md` and `docs/database.md` to describe the BCM feature.
- [ ] Update `docs/PLAN.md` only if any decisions there are now wrong (none expected).
- [ ] Playwright E2E (LLM mocked at the proxy boundary or skipped):
  - Manual happy path: open a Value Discovery project -> add an L1 -> add an L2 under it -> add an L3 -> reorder -> reload -> structure persists -> delete the L1 -> tree is empty.
- [ ] Final pass: `pytest`, `vitest`, `next build`, `playwright test` all green.

Success criteria:
- All test suites green.
- Docs reflect the shipped feature.
- User approval - feature complete.
