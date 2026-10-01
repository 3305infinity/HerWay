"""
ResearchAgent — compatibility delegate over the canonical research pipeline.

History
-------
This module used to contain a *second*, independent research implementation:
its own planner prompt, its own SerpApi vertical dispatch and its own trace
assembly. It was reached from ``agents/chat_agent.py`` (the ``adapt_safety_plan``
tool) and ``routes/cases.py`` (``POST .../safety-plan/adapt``), while
``routes/research.py`` used :class:`~backend.services.research_orchestrator.ResearchOrchestrator`.
The same case therefore behaved differently depending on which door the user
came through.

Phase 2 made ``ResearchOrchestrator`` canonical. This class is kept — not
deleted — because two callers depend on its interface, and because removing a
public class is a breaking change that buys nothing. It is now a thin delegate:
it holds an orchestrator and forwards to it.

Why ``ResearchOrchestrator`` is the canonical one
-------------------------------------------------
It is a strict superset. Compared with the implementation this file used to
contain, it adds:

===========================  ======================  ==========================
Behaviour                    old ResearchAgent       ResearchOrchestrator
===========================  ======================  ==========================
Search budget                none (unbounded)        2–4 normal / 5–6 complex,
                                                     trimmed and configurable
PII scrubbing of queries     **none**                ``sanitize_search_query``
Duplicate-query suppression  URL-level only          normalised query key +
                                                     URL
Upstream failure signal      exceptions only         ``SearchOutcome.success``
                                                     and ``error_message``
Credit metrics               none                    ``ResearchMetrics``
Maps location backfill       none                    yes
Trace detail                 6 fields                + ``sources_used``,
                                                     ``selected_urls``,
                                                     ``is_cached``,
                                                     ``is_followup``,
                                                     ``freshness_policy``
Planner prompt               generic routing         India jurisdiction, named
                                                     statutes, One Stop Centre /
                                                     Mahila Thana / DLSA
                                                     routing, freshness policy,
                                                     "search only if needed"
===========================  ======================  ==========================

Nothing from the old planner prompt was lost: every routing rule it contained
(official sources for procedure, news for recent developments, maps for physical
help, no duplicate queries, no raw user text as a query) is present in
``_ORCHESTRATOR_SYSTEM_PROMPT`` in a stronger, India-specific form.

Intentional behaviour changes for the two existing callers
----------------------------------------------------------
Research reached through chat and through the safety-plan adapt route now also:

1. **Respects a search budget.** Previously the LLM could return any number of
   tasks and all of them ran. Configurable via the constructor.
2. **Has personal data stripped from queries** before they reach SerpApi. The
   old path sent planner output through unmodified, so a name, email or phone
   number appearing in a task query left the server.
3. **Reports a failed search as failed** rather than as a successful search that
   found nothing — which matters when telling a woman whether a resource truly
   does not exist nearby or whether the lookup simply broke.
4. **Skips a repeated identical query** within one plan instead of paying for it
   twice.

All four are improvements; none changes the method signatures, and
``ResearchExecutionResult`` gains fields rather than losing any.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Optional

from backend.models.research import (
    ResearchExecutionResult,
    ResearchPlan,
    Situation,
)
from backend.models.case import Location
from backend.services.research_orchestrator import ResearchOrchestrator
from backend.trace import log_fields

if TYPE_CHECKING:
    from backend.services.llm_service import LLMService
    from backend.services.serpapi_service import SerpApiService

logger = logging.getLogger(__name__)


class ResearchAgent:
    """Plans and executes research by delegating to :class:`ResearchOrchestrator`.

    The constructor and both methods keep the signatures their callers already
    use, so ``agents/chat_agent.py`` and ``routes/cases.py`` are unchanged.
    """

    def __init__(
        self,
        llm: "LLMService",
        serpapi: "SerpApiService",
        *,
        normal_budget: Optional[int] = None,
        complex_budget: Optional[int] = None,
    ) -> None:
        # Retained as attributes because they were part of this class's shape
        # before, and callers or tests may reasonably reach for them.
        self._llm = llm
        self._serpapi = serpapi

        budget_kwargs = {}
        if normal_budget is not None:
            budget_kwargs["normal_budget"] = normal_budget
        if complex_budget is not None:
            budget_kwargs["complex_budget"] = complex_budget

        #: The single canonical research implementation. There is deliberately
        #: no second pipeline in this module.
        self._orchestrator = ResearchOrchestrator(llm, serpapi, **budget_kwargs)

    async def plan(
        self,
        case_id: str,
        situation: Situation,
        user_location: Optional[Location] = None,
    ) -> ResearchPlan:
        """Formulate a :class:`ResearchPlan`, budget-capped and PII-scrubbed."""
        plan = await self._orchestrator.plan_research(
            case_id=case_id,
            situation=situation,
            user_location=user_location,
        )
        # Counts and identifiers only — never the query text or case content.
        logger.info(
            "ResearchAgent.plan %s",
            log_fields(
                case_id=case_id,
                tasks=len(plan.tasks),
                budget=plan.search_budget,
                category=situation.category.value,
                urgency=situation.urgency.value,
            ),
        )
        return plan

    async def execute(self, plan: ResearchPlan) -> ResearchExecutionResult:
        """Execute every task in ``plan`` concurrently.

        Never raises for a provider failure: a failed task is recorded in the
        trace with ``success=False`` so the caller can degrade gracefully.
        ``routes/cases.py`` depends on this when adapting a safety plan.
        """
        result = await self._orchestrator.execute_plan(plan)
        failed = sum(1 for entry in result.trace if not entry.success)
        logger.info(
            "ResearchAgent.execute %s",
            log_fields(
                case_id=plan.case_id,
                tasks=len(plan.tasks),
                results=len(result.results),
                failed_tasks=failed,
            ),
        )
        return result
