"""
ChatAgent behaviour after the Phase 2 changes.

``ChatAgent`` was deliberately **not** rewritten: it already wraps every legacy
HerWay capability as a tool, which is the architecture Phase 2 is meant to
strengthen rather than replace. These tests pin down what must not regress:

- the twelve tool names and the mode discriminator LawBot/TherapyBot rely on,
- that a failing tool degrades honestly instead of looking like a success,
- that one tool's failure does not take down the turn,
- that the prompt still tells the model not to search for emotional support.

LLM output is nondeterministic, so these assert **structural** properties —
which tool ran, what the response dict contains, whether a failure is flagged —
never exact wording. All offline.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from backend.agents.chat_agent import ChatAgent, ToolCallChoice
from backend.models.case import Case
from backend.models.research import SearchFailureReason, SearchOutcome
from backend.trace import trace_context


def _case() -> Case:
    return Case(
        id="507f1f77bcf86cd799439011",
        user_id="user_1",
        title="Workplace harassment",
        situation_text="My manager keeps making sexual comments at work in Pune.",
        status="active",
    )


def _llm_choosing(tool_name: str, arguments: dict) -> MagicMock:
    llm = MagicMock()
    llm.structured_generate = AsyncMock(
        return_value=ToolCallChoice(tool_name=tool_name, arguments=arguments)
    )
    return llm


def _serpapi() -> MagicMock:
    serp = MagicMock()
    serp.search_detailed = AsyncMock(
        return_value=SearchOutcome(vertical="web", query="q", success=True, results=[])
    )
    return serp


# ---------------------------------------------------------------------------
# The integration surface must not shrink
# ---------------------------------------------------------------------------

EXPECTED_TOOLS = {
    "answer_user",
    "search_web",
    "search_news",
    "search_local",
    "update_action_status",
    "adapt_safety_plan",
    "search_safety_resources",
    "invoke_lawbot",
    "search_community",
    "encode_message",
    "generate_formal_report",
    "generate_poem",
}


def test_all_twelve_tools_are_still_declared():
    """Phase 2 must not drop a capability while 'consolidating'."""
    import inspect

    import backend.agents.chat_agent as module

    source = inspect.getsource(module)
    for tool in EXPECTED_TOOLS:
        assert tool in source, f"tool '{tool}' disappeared from ChatAgent"


def test_legacy_capabilities_are_still_wrapped_not_reimplemented():
    """LawBot, community, stego and reports must be reused, not rebuilt."""
    import inspect

    import backend.agents.chat_agent as module

    source = inspect.getsource(module)
    for marker in ("EmbeddingService", "ReportService"):
        assert marker in source, f"ChatAgent no longer reuses {marker}"


# ---------------------------------------------------------------------------
# Mode discriminator — LawBot and TherapyBot depend on this
# ---------------------------------------------------------------------------

def test_therapy_mode_prompt_differs_from_default():
    agent = ChatAgent(MagicMock(), MagicMock())
    assert agent._system_prompt("therapy") != agent._system_prompt(None)


def test_legal_mode_prompt_differs_from_default():
    agent = ChatAgent(MagicMock(), MagicMock())
    assert agent._system_prompt("legal") != agent._system_prompt(None)


def test_unknown_mode_falls_back_to_default():
    agent = ChatAgent(MagicMock(), MagicMock())
    assert agent._system_prompt("nonsense") == agent._system_prompt(None)


def test_both_modes_keep_the_shared_base_prompt():
    """Mode guidance is additive; the safety rules in the base must survive."""
    agent = ChatAgent(MagicMock(), MagicMock())
    base = agent._system_prompt(None)
    for mode in ("therapy", "legal"):
        assert agent._system_prompt(mode).startswith(base)


# ---------------------------------------------------------------------------
# Research is chosen only when it is needed
# ---------------------------------------------------------------------------

def test_prompt_tells_the_model_not_to_search_for_feelings():
    agent = ChatAgent(MagicMock(), MagicMock())
    prompt = agent._system_prompt(None).lower()
    assert "do not search" in prompt or "only when" in prompt, (
        "the prompt must steer simple/emotional messages to a direct answer"
    )


def test_prompt_forbids_answering_from_memory_when_a_lookup_fails():
    agent = ChatAgent(MagicMock(), MagicMock())
    assert "memory" in agent._system_prompt(None).lower()


# ---------------------------------------------------------------------------
# Honest failure — a tool error must never read as a completed action
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_failed_search_is_not_presented_as_an_answer():
    serp = MagicMock()
    serp.search_detailed = AsyncMock(
        return_value=SearchOutcome(
            vertical="web",
            query="q",
            success=False,
            failure_reason=SearchFailureReason.RATE_LIMITED,
            error_message="rate limited",
            results=[],
        )
    )
    agent = ChatAgent(
        _llm_choosing("search_web", {"query": "posh act", "reason": "need procedure"}), serp
    )

    result = await agent.converse(_case(), "What is the POSH process?", [])

    assert result.get("degraded_notice"), "a failed search must be flagged as degraded"
    assert "could not" in result["reply"].lower() or "not going to" in result["reply"].lower()


@pytest.mark.asyncio
async def test_empty_results_are_distinguished_from_a_failed_search():
    """'Found nothing' and 'the lookup broke' are different answers."""
    agent = ChatAgent(
        _llm_choosing("search_web", {"query": "obscure", "reason": "r"}), _serpapi()
    )

    result = await agent.converse(_case(), "anything?", [])

    assert result["tool_used"] == "search_web"
    assert not result.get("degraded_notice"), (
        "a successful-but-empty search must not be reported as degraded"
    )


@pytest.mark.asyncio
async def test_an_exploding_tool_degrades_instead_of_raising():
    """One failed tool must not take down the whole turn."""
    serp = MagicMock()
    serp.search_detailed = AsyncMock(side_effect=RuntimeError("boom"))
    agent = ChatAgent(_llm_choosing("search_web", {"query": "x", "reason": "r"}), serp)

    result = await agent.converse(_case(), "What is the POSH process?", [])

    assert isinstance(result, dict)
    assert result.get("degraded_notice", "").startswith("tool_failed")
    assert result["reply"], "the user must still get something to read"
    assert "112" in result["reply"], "a degraded reply should still point at real help"


@pytest.mark.asyncio
async def test_degraded_reply_does_not_claim_an_action_succeeded():
    serp = MagicMock()
    serp.search_detailed = AsyncMock(side_effect=RuntimeError("boom"))
    agent = ChatAgent(_llm_choosing("search_web", {"query": "x", "reason": "r"}), serp)

    reply = (await agent.converse(_case(), "do it", []))["reply"].lower()

    for false_claim in ("i have updated", "i have added", "done", "successfully"):
        assert false_claim not in reply, f"degraded reply implied success: {false_claim!r}"


@pytest.mark.asyncio
async def test_unparseable_tool_arguments_do_not_produce_an_empty_bubble():
    agent = ChatAgent(_llm_choosing("answer_user", {"wrong_field": 1}), _serpapi())
    result = await agent.converse(_case(), "hello", [])
    assert result["reply"].strip(), "an empty reply is never acceptable"


# ---------------------------------------------------------------------------
# Trace propagation
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_response_carries_the_request_trace_id():
    agent = ChatAgent(
        _llm_choosing("answer_user", {"text": "Here is what I know.", "source_urls": []}),
        _serpapi(),
    )

    with trace_context("chat-trace-0001"):
        result = await agent.converse(_case(), "hello", [])

    assert result.get("trace_id") == "chat-trace-0001"


@pytest.mark.asyncio
async def test_tools_run_inside_the_request_trace_context():
    seen = []

    async def capture(*args, **kwargs):
        from backend.trace import get_trace_id

        seen.append(get_trace_id())
        return SearchOutcome(vertical="web", query="q", success=True, results=[])

    serp = MagicMock()
    serp.search_detailed = AsyncMock(side_effect=capture)
    agent = ChatAgent(_llm_choosing("search_web", {"query": "x", "reason": "r"}), serp)

    with trace_context("chat-trace-0002"):
        await agent.converse(_case(), "find something", [])

    assert seen == ["chat-trace-0002"]


# ---------------------------------------------------------------------------
# Response contract the frontend reads
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_response_keys_stay_compatible_with_the_frontend():
    """`frontend/src/lib/types.ts` and routes/chat.py read these keys."""
    agent = ChatAgent(
        _llm_choosing("answer_user", {"text": "An answer.", "source_urls": []}),
        _serpapi(),
    )
    result = await agent.converse(_case(), "hello", [])

    assert "reply" in result
    assert "tool_used" in result
    # Keys that may be absent must simply be absent, never a wrong type.
    for optional_key in ("sources", "community_posts", "lawbot_docs"):
        if optional_key in result:
            assert isinstance(result[optional_key], list)
