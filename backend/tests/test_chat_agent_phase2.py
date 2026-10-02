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

#: The twelve tools that existed before Phase 2. Phase 3 added `research_place`
#: and `compare_places` alongside them; none of these may disappear.
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

#: Added in Phase 3 for local discovery.
PHASE3_TOOLS = {"research_place", "compare_places"}


def test_all_twelve_tools_are_still_declared():
    """Phase 2 must not drop a capability while 'consolidating'."""
    import inspect

    import backend.agents.chat_agent as module

    source = inspect.getsource(module)
    for tool in EXPECTED_TOOLS:
        assert tool in source, f"tool '{tool}' disappeared from ChatAgent"


def test_phase3_local_tools_are_declared():
    import inspect

    import backend.agents.chat_agent as module

    source = inspect.getsource(module)
    for tool in PHASE3_TOOLS:
        assert tool in source, f"Phase 3 tool '{tool}' is missing"


def test_phase3_reuses_the_local_services_rather_than_searching_directly():
    """New tools must compose the resolver/research services, not re-roll them."""
    import inspect

    import backend.agents.chat_agent as module

    source = inspect.getsource(module)
    assert "ResourceResolver" in source
    assert "PlaceResearchService" in source
    assert "compare_options" in source


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

# ---------------------------------------------------------------------------
# Phase 3 local-discovery tools, reached through the existing tool mechanism
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_research_place_returns_a_structured_profile():
    from backend.models.research import SearchResult

    serp = MagicMock()
    serp.search_detailed = AsyncMock(
        return_value=SearchOutcome(
            vertical="maps",
            query="q",
            success=True,
            results=[
                SearchResult(
                    title="Ruby Hall Clinic",
                    url="https://example.com/x",
                    snippet="clean and tidy",
                    address="Sassoon Road, Pune",
                    rating=4.1,
                    reviews=120,
                )
            ],
        )
    )
    agent = ChatAgent(
        _llm_choosing(
            "research_place",
            {"place_name": "Ruby Hall Clinic", "location": "Pune", "reason": "user asked"},
        ),
        serp,
    )

    result = await agent.converse(_case(), "tell me about Ruby Hall Clinic", [])

    assert result["tool_used"] == "research_place"
    assert result["place_profile"]["listing"]["name"] == "Ruby Hall Clinic"
    assert result["place_profile"]["listing"]["open_now_known"] is False


@pytest.mark.asyncio
async def test_place_research_reply_never_claims_safety():
    from backend.models.research import SearchResult

    serp = MagicMock()
    serp.search_detailed = AsyncMock(
        return_value=SearchOutcome(
            vertical="maps", query="q", success=True,
            results=[SearchResult(title="A Place", rating=5.0, reviews=900, snippet="great")],
        )
    )
    agent = ChatAgent(
        _llm_choosing("research_place", {"place_name": "A Place", "reason": "r"}), serp
    )
    reply = (await agent.converse(_case(), "is this place safe?", []))["reply"].lower()

    assert "it is not a judgement about whether it is safe" in reply
    for claim in ("this place is safe", "safe for you to visit", "perfectly safe"):
        assert claim not in reply


@pytest.mark.asyncio
async def test_failed_place_lookup_is_flagged_not_answered_from_memory():
    serp = MagicMock()
    serp.search_detailed = AsyncMock(
        return_value=SearchOutcome(
            vertical="maps", query="q", success=False,
            failure_reason=SearchFailureReason.RATE_LIMITED, results=[],
        )
    )
    agent = ChatAgent(
        _llm_choosing("research_place", {"place_name": "Somewhere", "reason": "r"}), serp
    )
    result = await agent.converse(_case(), "tell me about Somewhere", [])

    assert result["degraded_notice"].startswith("place_lookup_failed")
    assert "could not look up" in result["reply"].lower()


@pytest.mark.asyncio
async def test_compare_places_requires_a_location_and_does_not_guess():
    serp = MagicMock()
    serp.search_detailed = AsyncMock()
    case = _case()
    case.location_context = None
    agent = ChatAgent(
        _llm_choosing("compare_places", {"category": "hospital", "reason": "r"}), serp
    )

    result = await agent.converse(case, "compare hospitals", [])

    assert "will not guess a location" in result["reply"]
    serp.search_detailed.assert_not_awaited()


@pytest.mark.asyncio
async def test_compare_places_returns_a_table_without_ranking():
    from backend.models.research import SearchResult

    serp = MagicMock()
    serp.search_detailed = AsyncMock(
        return_value=SearchOutcome(
            vertical="maps", query="q", success=True,
            results=[
                SearchResult(title="Hospital A", rating=4.5, snippet="s", address="Road 1"),
                SearchResult(title="Hospital B", rating=3.1, snippet="s"),
            ],
        )
    )
    agent = ChatAgent(
        _llm_choosing(
            "compare_places",
            {"category": "hospital", "location": "Pune", "priorities": [], "reason": "r"},
        ),
        serp,
    )

    result = await agent.converse(_case(), "compare hospitals in Pune", [])

    assert result["comparison"]["has_overall_ranking"] is False
    assert "I have not ranked these" in result["reply"]
    assert len(result["comparison"]["option_names"]) == 2


@pytest.mark.asyncio
async def test_comparison_search_failure_is_not_shown_as_no_options():
    serp = MagicMock()
    serp.search_detailed = AsyncMock(
        return_value=SearchOutcome(
            vertical="maps", query="q", success=False,
            failure_reason=SearchFailureReason.TIMEOUT, results=[],
        )
    )
    agent = ChatAgent(
        _llm_choosing(
            "compare_places", {"category": "hospital", "location": "Pune", "reason": "r"}
        ),
        serp,
    )
    result = await agent.converse(_case(), "compare hospitals", [])

    assert result["degraded_notice"].startswith("comparison_search_failed")
    assert "not a sign that there is nothing near you" in result["reply"]


@pytest.mark.asyncio
async def test_local_tools_run_inside_the_trace_context():
    from backend.models.research import SearchResult

    seen = []

    async def capture(*args, **kwargs):
        from backend.trace import get_trace_id

        seen.append(get_trace_id())
        return SearchOutcome(
            vertical="maps", query="q", success=True,
            results=[SearchResult(title="X", snippet="s")],
        )

    serp = MagicMock()
    serp.search_detailed = AsyncMock(side_effect=capture)
    agent = ChatAgent(
        _llm_choosing("research_place", {"place_name": "X", "location": "Pune", "reason": "r"}),
        serp,
    )

    with trace_context("phase3-trace-001"):
        await agent.converse(_case(), "about X", [])

    assert seen == ["phase3-trace-001"]


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
