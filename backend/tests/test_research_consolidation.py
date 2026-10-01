"""
Regression and compatibility tests for the research consolidation (Phase 2).

These were written **before** ``ResearchAgent`` was turned into a delegate, to
pin down the contract its two callers rely on:

  - ``backend/agents/chat_agent.py``   (the ``adapt_safety_plan`` tool)
  - ``backend/routes/cases.py``        (``POST .../safety-plan/adapt``)

Both construct ``ResearchAgent(llm, serpapi)`` and then call ``plan(case_id,
situation)`` followed by ``execute(plan)``. Those three signatures, and the
shape of what ``execute`` returns, are the compatibility surface.

Everything here is **mocked**. No Gemini, SerpApi, MongoDB or Atlas call is
made. The tests assert structural contracts — budgets, dedup, failure
propagation, trace shape — rather than LLM wording, which is nondeterministic.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from backend.agents.research_agent import ResearchAgent
from backend.models.research import (
    ResearchExecutionResult,
    ResearchPlan,
    ResearchTask,
    SearchOutcome,
    SearchResult,
    SearchVertical,
    Situation,
    SituationCategory,
    Urgency,
)
from backend.services.research_orchestrator import ResearchOrchestrator
from backend.trace import get_trace_id, trace_context


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

def _situation(**overrides) -> Situation:
    base = dict(
        case_summary="A woman reports repeated unwanted comments from her manager.",
        category=SituationCategory.WORKPLACE_HARASSMENT,
        urgency=Urgency.MEDIUM,
        user_goal="Understand how to file a POSH complaint",
        known_facts=["Comments occurred at work"],
        user_claims=["This is harassment"],
        unknowns=["Whether the employer has an Internal Committee"],
        location="Pune, Maharashtra",
    )
    base.update(overrides)
    return Situation(**base)


def _plan(case_id: str = "case_1", n_tasks: int = 3, **overrides) -> ResearchPlan:
    tasks = [
        ResearchTask(
            task_id=f"TASK_{i + 1:02d}",
            query=f"posh act complaint procedure {i}",
            purpose="Find the official complaint procedure",
            expected_information="The statutory complaint route and who receives it",
            vertical=SearchVertical.WEB,
        )
        for i in range(n_tasks)
    ]
    data = dict(case_id=case_id, tasks=tasks)
    data.update(overrides)
    return ResearchPlan(**data)


def _result(url: str, title: str = "Result") -> SearchResult:
    return SearchResult(title=title, url=url, snippet="snippet", source="example.gov.in")


def _mock_serpapi(results=None, *, outcome_success=True, error_message=None):
    """A SerpApiService stand-in covering both the old and new call styles."""
    results = results if results is not None else [_result("https://example.gov.in/a")]
    serp = MagicMock()
    serp.search_web = AsyncMock(return_value=results)
    serp.search_news = AsyncMock(return_value=results)
    serp.search_maps = AsyncMock(return_value=results)
    serp.search_detailed = AsyncMock(
        return_value=SearchOutcome(
            vertical="web",
            query="stub",
            results=results,
            success=outcome_success,
            error_message=error_message,
            from_cache=False,
        )
    )
    return serp


def _mock_llm(plan: ResearchPlan):
    llm = MagicMock()
    llm.structured_generate = AsyncMock(return_value=plan)
    return llm


# ---------------------------------------------------------------------------
# 1. Public interface compatibility — what the two callers depend on
# ---------------------------------------------------------------------------

def test_research_agent_constructor_signature_unchanged():
    """Both callers do ResearchAgent(llm, serpapi) positionally."""
    agent = ResearchAgent(_mock_llm(_plan()), _mock_serpapi())
    assert agent is not None


@pytest.mark.asyncio
async def test_plan_accepts_caller_signature_and_stamps_case_id():
    plan = _plan(case_id="PLACEHOLDER")
    agent = ResearchAgent(_mock_llm(plan), _mock_serpapi())

    produced = await agent.plan("case_abc", _situation())

    assert isinstance(produced, ResearchPlan)
    assert produced.case_id == "case_abc"
    assert all(t.task_id for t in produced.tasks), "every task needs an id"


@pytest.mark.asyncio
async def test_plan_accepts_optional_user_location():
    """routes/cases.py omits it; the parameter must stay optional."""
    from backend.models.case import Location

    agent = ResearchAgent(_mock_llm(_plan()), _mock_serpapi())
    produced = await agent.plan(
        "case_abc", _situation(location=None), Location(display_name="Nagpur, Maharashtra")
    )
    assert isinstance(produced, ResearchPlan)


@pytest.mark.asyncio
async def test_execute_returns_execution_result_with_plan_results_and_trace():
    agent = ResearchAgent(_mock_llm(_plan()), _mock_serpapi())
    plan = await agent.plan("case_abc", _situation())

    out = await agent.execute(plan)

    assert isinstance(out, ResearchExecutionResult)
    assert out.plan is not None
    assert isinstance(out.results, list)
    assert isinstance(out.trace, list)
    assert len(out.trace) >= 1
    entry = out.trace[0]
    for field in ("task_id", "why_searched", "query", "engine", "results_found", "success"):
        assert hasattr(entry, field), f"trace entry lost field {field}"


@pytest.mark.asyncio
async def test_execute_deduplicates_identical_urls():
    duplicate = [_result("https://same.gov.in/x"), _result("https://same.gov.in/x")]
    agent = ResearchAgent(_mock_llm(_plan(n_tasks=2)), _mock_serpapi(duplicate))
    plan = await agent.plan("case_abc", _situation())

    out = await agent.execute(plan)

    urls = [r.url for r in out.results]
    assert len(urls) == len(set(urls)), "duplicate URLs must be collapsed"


# ---------------------------------------------------------------------------
# 2. Graceful degradation — a provider failure must not raise
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_provider_exception_is_recorded_not_raised():
    """routes/cases.py relies on research failure not blocking plan adaptation."""
    serp = _mock_serpapi()
    serp.search_detailed = AsyncMock(side_effect=RuntimeError("serpapi exploded"))
    serp.search_web = AsyncMock(side_effect=RuntimeError("serpapi exploded"))

    agent = ResearchAgent(_mock_llm(_plan(n_tasks=2)), serp)
    plan = await agent.plan("case_abc", _situation())

    out = await agent.execute(plan)  # must not raise

    assert out.results == []
    assert all(entry.success is False for entry in out.trace)
    assert all(entry.error for entry in out.trace)


@pytest.mark.asyncio
async def test_upstream_failure_is_reported_as_failure_not_empty_success():
    """A failed search must be distinguishable from 'nothing found'."""
    serp = _mock_serpapi([], outcome_success=False, error_message="rate_limited")
    agent = ResearchAgent(_mock_llm(_plan(n_tasks=1)), serp)
    plan = await agent.plan("case_abc", _situation())

    out = await agent.execute(plan)

    assert out.trace[0].success is False
    assert out.trace[0].error == "rate_limited"


# ---------------------------------------------------------------------------
# 3. Consolidation behaviour inherited from ResearchOrchestrator
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_budget_is_enforced_through_the_delegate():
    """Previously ResearchAgent had no budget at all; now the cap applies."""
    oversized = _plan(n_tasks=12)
    agent = ResearchAgent(_mock_llm(oversized), _mock_serpapi())

    produced = await agent.plan("case_abc", _situation(urgency=Urgency.MEDIUM))

    assert len(produced.tasks) <= produced.search_budget
    assert produced.search_budget > 0, "budget must be explicit"


@pytest.mark.asyncio
async def test_critical_urgency_gets_a_larger_budget():
    normal = ResearchOrchestrator(MagicMock(), MagicMock()).determine_budget(
        _situation(urgency=Urgency.MEDIUM)
    )
    critical = ResearchOrchestrator(MagicMock(), MagicMock()).determine_budget(
        _situation(urgency=Urgency.CRITICAL)
    )
    assert critical > normal


@pytest.mark.asyncio
async def test_budget_is_configurable():
    orchestrator = ResearchOrchestrator(
        MagicMock(), MagicMock(), normal_budget=2, complex_budget=9
    )
    assert orchestrator.determine_budget(_situation(urgency=Urgency.MEDIUM)) == 2
    assert orchestrator.determine_budget(_situation(urgency=Urgency.CRITICAL)) == 9


@pytest.mark.asyncio
async def test_queries_are_pii_sanitised_through_the_delegate():
    """ResearchAgent used to send queries to SerpApi unsanitised."""
    leaky = _plan(n_tasks=1)
    leaky.tasks[0].query = "help for priya sharma priya@example.com 9876543210 pune"
    agent = ResearchAgent(_mock_llm(leaky), _mock_serpapi())

    produced = await agent.plan("case_abc", _situation())

    sent = produced.tasks[0].query
    assert "priya@example.com" not in sent, "email must not reach SerpApi"
    assert "9876543210" not in sent, "phone number must not reach SerpApi"


@pytest.mark.asyncio
async def test_repeated_identical_queries_are_not_searched_twice():
    """Avoid burning SerpApi credits on the same query within one plan."""
    repeated = _plan(n_tasks=3)
    for task in repeated.tasks:
        task.query = "one stop centre sakhi pune"
        task.vertical = SearchVertical.WEB

    serp = _mock_serpapi()
    agent = ResearchAgent(_mock_llm(repeated), serp)
    plan = await agent.plan("case_abc", _situation())
    await agent.execute(plan)

    assert serp.search_detailed.await_count == 1, (
        f"expected 1 upstream search for 3 identical queries, "
        f"got {serp.search_detailed.await_count}"
    )


# ---------------------------------------------------------------------------
# 4. Trace propagation
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_research_runs_inside_the_request_trace_context():
    seen: list[str | None] = []

    async def capture(*args, **kwargs):
        seen.append(get_trace_id())
        return SearchOutcome(vertical="web", query="stub", results=[], success=True, from_cache=False)

    serp = _mock_serpapi()
    serp.search_detailed = AsyncMock(side_effect=capture)

    agent = ResearchAgent(_mock_llm(_plan(n_tasks=3)), serp)

    with trace_context("research-trace-01"):
        plan = await agent.plan("case_abc", _situation())
        await agent.execute(plan)

    assert seen, "no searches were executed"
    assert set(seen) == {"research-trace-01"}, (
        "concurrent research tasks must inherit the request trace ID"
    )


# ---------------------------------------------------------------------------
# 5. Only one research pipeline exists
# ---------------------------------------------------------------------------

def test_research_agent_delegates_rather_than_reimplementing():
    """Guards against a second pipeline reappearing.

    ``ResearchAgent`` must not call SerpApi itself; it must hold a
    ``ResearchOrchestrator`` and defer to it.
    """
    agent = ResearchAgent(_mock_llm(_plan()), _mock_serpapi())
    assert isinstance(getattr(agent, "_orchestrator", None), ResearchOrchestrator), (
        "ResearchAgent should delegate to ResearchOrchestrator"
    )


def test_research_agent_module_has_no_independent_serpapi_dispatch():
    """The old module dispatched on vertical itself. That logic now lives once."""
    import inspect

    import backend.agents.research_agent as module

    source = inspect.getsource(module)
    for forbidden in ("search_news(", "search_maps(", "search_web("):
        assert forbidden not in source, (
            f"ResearchAgent still dispatches SerpApi directly via {forbidden}; "
            "that belongs only in ResearchOrchestrator"
        )
