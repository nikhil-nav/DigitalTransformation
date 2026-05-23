"""IT Map Agent — batch-shaped run orchestrator.

The existing ``run_agent_turn_stream`` in ``app.llm.agent`` is chat-shaped
(per-turn streaming, history persisted as ChatMessage rows). The IT Map
agent is a batch job — one kick-off message, run until the LLM stops
calling tools, write everything to the IT Map tables — so it gets its
own loop here.

Re-run policy: before driving the loop, the orchestrator deletes
``status='suggested'`` mappings for the inventory's applications.
Confirmed and dismissed mappings are left untouched. The
``propose_mapping`` tool ALSO enforces this at the tool layer (see
``app.it_map.agent``) as defence in depth.
"""
from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.it_map.agent import (
    IT_MAP_AGENT_VERSION,
    IT_MAP_TOOLS,
    MAX_TOOL_CALLS_PER_RUN,
    SYSTEM_PROMPT,
    make_it_map_tool_dispatch,
)
from app.llm.provider import ToolResult, get_provider
from app.llm.session import LlmKeys
from app.models import (
    Application,
    ApplicationCapabilityMapping,
    ApplicationInventory,
)

# Bounds the number of provider.call() round-trips. With one tool call
# per turn this caps at the same number as MAX_TOOL_CALLS_PER_RUN, but
# the model usually emits several tools per turn so the turn cap is
# the smaller, secondary guard.
MAX_TURNS_PER_RUN = 60
MAX_TOKENS = 4096

# The kick-off user message. The agent's behaviour is fully specified by
# SYSTEM_PROMPT; this message just hands it the floor.
INITIAL_USER_MESSAGE = (
    "Begin mapping the inventory now. Follow the working order in your "
    "system prompt: describe the inventory, sample some rows, list the "
    "capabilities, propose a schema, then propose mappings (or "
    "propose_unmappable) for every row. When you are done, finish your "
    "turn without calling any further tools."
)


class ItMapRunError(Exception):
    """Raised by the orchestrator when a run cannot proceed. The HTTP
    layer maps this to a 400 (pre-flight) or persists it on the run
    row as ``status='failed'`` (in-flight)."""


@dataclass(frozen=True)
class RunCounts:
    tool_call_count: int
    application_count: int
    mapping_count: int
    unmappable_count: int


def _app_ids_for_inventory(inventory_id: int):
    """A scalar `select` of Application.id values for this inventory,
    safe to pass to `.in_(...)`. Using `select(...)` (not `query(...).subquery()`)
    avoids the SAWarning about coercing Subquery into select."""
    return select(Application.id).where(Application.inventory_id == inventory_id)


def _clear_suggested_mappings(db: Session, inventory_id: int) -> None:
    """Delete prior agent-suggested mappings for this inventory while
    preserving user-confirmed and user-dismissed decisions."""
    db.query(ApplicationCapabilityMapping).filter(
        ApplicationCapabilityMapping.application_id.in_(
            _app_ids_for_inventory(inventory_id)
        ),
        ApplicationCapabilityMapping.status == "suggested",
    ).delete(synchronize_session=False)
    db.flush()


def _count_final_state(db: Session, inventory_id: int) -> tuple[int, int, int]:
    """Return ``(application_count, mapping_count, unmappable_count)``
    for the inventory after a run completes. Mapping count is all rows
    regardless of status — the run's stat is "total mappings on the
    board", not "newly proposed". Unmappable is apps with a non-null
    reason."""
    app_count = (
        db.query(Application).filter_by(inventory_id=inventory_id).count()
    )
    unmappable_count = (
        db.query(Application)
        .filter(
            Application.inventory_id == inventory_id,
            Application.unmappable_reason.isnot(None),
        )
        .count()
    )
    mapping_count = (
        db.query(ApplicationCapabilityMapping)
        .filter(
            ApplicationCapabilityMapping.application_id.in_(
                _app_ids_for_inventory(inventory_id)
            )
        )
        .count()
    )
    return app_count, mapping_count, unmappable_count


def run_it_map_agent(
    db: Session,
    inventory: ApplicationInventory,
    project_id: int,
    keys: LlmKeys,
    *,
    max_tool_calls: int | None = None,
    max_turns: int | None = None,
) -> RunCounts:
    """Drive the IT Map agent loop end-to-end against ``inventory``.

    Loop ends when the model returns a turn with no tool uses (the
    agent considers itself done) OR when ``max_tool_calls`` /
    ``max_turns`` is reached (which raises ``ItMapRunError`` so the
    orchestrator can persist the failure).

    Both caps default to the module-level constants resolved at call
    time (NOT function-definition time), so tests can
    ``monkeypatch.setattr(app.it_map.run, "MAX_TURNS_PER_RUN", 3)`` and
    have it take effect without rebuilding the function defaults.

    The caller is responsible for the surrounding session/commit
    lifecycle. This function calls ``db.flush()`` between turns but
    not ``db.commit()`` so the caller can decide whether to roll back
    on failure.
    """
    if max_tool_calls is None:
        max_tool_calls = MAX_TOOL_CALLS_PER_RUN
    if max_turns is None:
        max_turns = MAX_TURNS_PER_RUN

    _clear_suggested_mappings(db, inventory.id)

    provider = get_provider(keys)
    model = keys.model or provider.default_model
    tools = provider.translate_tools(IT_MAP_TOOLS)
    dispatch = make_it_map_tool_dispatch(inventory.id)

    messages: list[dict] = [{"role": "user", "content": INITIAL_USER_MESSAGE}]
    tool_call_count = 0

    for _ in range(max_turns):
        response = provider.call(
            system=SYSTEM_PROMPT,
            messages=messages,
            tools=tools,
            model=model,
            max_tokens=MAX_TOKENS,
        )
        if not response.tool_uses:
            # Agent stopped voluntarily — clean termination.
            break

        # Cap check BEFORE dispatching this turn's tools so we never
        # exceed the budget by a whole burst.
        if tool_call_count + len(response.tool_uses) > max_tool_calls:
            raise ItMapRunError(
                f"Agent exceeded tool-call cap of {max_tool_calls} "
                f"({tool_call_count} prior + {len(response.tool_uses)} "
                f"queued this turn). Tighten the inventory or raise "
                f"the cap if you trust the agent's progress."
            )

        results: list[ToolResult] = []
        for tu in response.tool_uses:
            text, is_err = dispatch(
                tu.name, tu.input, db=db, project_id=project_id, keys=keys
            )
            results.append(
                ToolResult(tool_use_id=tu.id, content=text, is_error=is_err)
            )
            tool_call_count += 1

        db.flush()
        messages = provider.append_tool_results(messages, response, results)
    else:
        # Loop exhausted without break (no done turn) -> hard fail.
        raise ItMapRunError(
            f"Agent did not finish within {max_turns} turns "
            f"({tool_call_count} tool calls made). The agent may be "
            f"stuck in a loop; review the inventory or tighten the "
            f"system prompt."
        )

    apps, mappings, unmappable = _count_final_state(db, inventory.id)
    return RunCounts(
        tool_call_count=tool_call_count,
        application_count=apps,
        mapping_count=mappings,
        unmappable_count=unmappable,
    )


def engine_version() -> str:
    return f"it-map-agent/{IT_MAP_AGENT_VERSION}"
