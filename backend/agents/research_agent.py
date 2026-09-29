"""
ResearchAgent — Research Planning & Concurrent Execution Agent (Stage 2 of Haven pipeline).

Responsibility
--------------
1. Accept a structured ``Situation`` object.
2. Formulate a ``ResearchPlan`` containing specific ``ResearchTask`` items.
3. Vertical Routing Rules:
   - Official sources preferred for procedures (Consumer Helpline, Govt portals).
   - Google News for recent policy changes or active developments.
   - Google Maps / Local for physical assistance (nearby consumer court, cyber cell).
   - General Google Web Search for factual background & policies.
   - Avoid duplicate queries & prioritize freshness for urgent cases.
4. Execute independent tasks concurrently using asyncio.gather().
5. Record a per-case research trace for transparency (WHY SEARCHED, QUERY, ENGINE, RESULTS FOUND, TIME TAKEN).
"""

from __future__ import annotations

import asyncio
import logging
import time
import uuid
from typing import TYPE_CHECKING, List, Optional

from backend.models.case import Location
from backend.models.research import (
    ResearchExecutionResult,
    ResearchPlan,
    ResearchTask,
    ResearchTraceEntry,
    SearchResult,
    SearchVertical,
    Situation,
)

if TYPE_CHECKING:
    from backend.services.llm_service import LLMService
    from backend.services.serpapi_service import SerpApiService

logger = logging.getLogger(__name__)

_PLANNER_SYSTEM_PROMPT = """\
You are the Research Planning Agent for Haven.

Given a structured Situation object, create a targeted research plan containing 2 to 5 distinct ResearchTask items.

RULES & ROUTING STRATEGY:

1. WOMEN'S SAFETY & PROTECTION DISPUTES:
   If the category is domestic_violence, sexual_harassment, stalking, online_harassment, threats, coercive_control, unsafe_relationship, workplace_harassment, other_women_safety, or safety:
   - Task 1: Search official national/state women's helpline numbers and 24/7 emergency support portals (e.g., "National Women Helpline official contact", "Women in distress helpline").
   - Task 2: Search for official legal rights & protection acts (e.g., "Protection of Women from Domestic Violence Act official procedure", "POSH Act workplace harassment procedure", "cyber stalking complaint official process").
   - Task 3: Search for nearby women's shelters, One Stop Support Centres (Sakhi), or women's police cell (vertical="maps" or "local").
   - Task 4: Prefer authoritative government, police, or NGO sources.

2. OFFICIAL PROCEDURES & GENERAL DISPUTES:
   - Set vertical="web", official_source_preference="preferred".
   - Purpose: Find official complaint procedures or legal rights.

3. RECENT DEVELOPMENTS / NEWS:
   - Set vertical="news" if the situation involves a recent policy, news event, or ongoing company issue.

4. PHYSICAL RESOURCES / NEARBY HELPLINES:
   - Set vertical="maps" or vertical="local" if user needs physical help (e.g. nearby court, cyber cell, police station).

5. NO DUPLICATES:
   - Ensure every query is unique and serves a specific purpose.
   - Do NOT send the raw user text as a search query. Create short, effective keywords.

Respond with valid JSON matching the ResearchPlan schema.
"""


class ResearchAgent:
    """Plans and concurrently executes SerpApi research for a case."""

    def __init__(self, llm: LLMService, serpapi: SerpApiService) -> None:
        self._llm = llm
        self._serpapi = serpapi

    async def plan(
        self,
        case_id: str,
        situation: Situation,
        user_location: Optional[Location] = None,
    ) -> ResearchPlan:
        """Formulate a structured ResearchPlan for the given situation."""
        loc_str = situation.location or (user_location.display_name if user_location else None)

        prompt = (
            f"Case Summary: {situation.case_summary}\n"
            f"Category: {situation.category.value}\n"
            f"User Goal: {situation.user_goal}\n"
            f"Known Facts: {situation.known_facts}\n"
            f"User Claims: {situation.user_claims}\n"
            f"Unknowns: {situation.unknowns}\n"
            f"Location: {loc_str or 'Not specified'}\n"
            f"Recommended verticals: {situation.recommended_research_types}\n"
        )

        class _PlanWrapper(ResearchPlan):
            case_id: str = case_id  # type: ignore[assignment]

        plan = await self._llm.structured_generate(
            system_prompt=_PLANNER_SYSTEM_PROMPT,
            user_prompt=prompt,
            output_schema=_PlanWrapper,
        )
        plan.case_id = case_id

        # Ensure unique task IDs
        for idx, task in enumerate(plan.tasks):
            if not task.task_id:
                task.task_id = f"TASK_{idx + 1:02d}"

        logger.info("ResearchAgent: Formulated %d research tasks for case %s", len(plan.tasks), case_id)
        return plan

    async def execute(self, plan: ResearchPlan) -> ResearchExecutionResult:
        """Execute all research tasks concurrently and produce a trace."""
        logger.info("ResearchAgent: Executing %d tasks concurrently", len(plan.tasks))

        async def _run_single_task(task: ResearchTask) -> tuple[ResearchTraceEntry, List[SearchResult]]:
            start_t = time.time()
            s_id = f"srch_{uuid.uuid4().hex[:6]}"
            try:
                # Direct method dispatch based on vertical
                if task.vertical in (SearchVertical.NEWS, "news"):
                    results = await self._serpapi.search_news(
                        query=task.query,
                        location=task.location,
                        case_id=plan.case_id,
                        search_id=s_id,
                    )
                elif task.vertical in (SearchVertical.MAPS, SearchVertical.LOCAL, "maps", "local"):
                    results = await self._serpapi.search_maps(
                        query=task.query,
                        location=task.location,
                        case_id=plan.case_id,
                        search_id=s_id,
                    )
                else:
                    results = await self._serpapi.search_web(
                        query=task.query,
                        location=task.location,
                        case_id=plan.case_id,
                        search_id=s_id,
                    )

                time_taken = round((time.time() - start_t) * 1000, 2)
                trace = ResearchTraceEntry(
                    task_id=task.task_id,
                    why_searched=task.purpose,
                    query=task.query,
                    engine=task.vertical.value if hasattr(task.vertical, "value") else str(task.vertical),
                    results_found=len(results),
                    time_taken_ms=time_taken,
                    success=True,
                )
                return trace, results

            except Exception as exc:
                time_taken = round((time.time() - start_t) * 1000, 2)
                logger.error("ResearchAgent task %s failed: %s", task.task_id, exc)
                trace = ResearchTraceEntry(
                    task_id=task.task_id,
                    why_searched=task.purpose,
                    query=task.query,
                    engine=str(task.vertical),
                    results_found=0,
                    time_taken_ms=time_taken,
                    success=False,
                    error=str(exc),
                )
                return trace, []

        # Execute all tasks concurrently via asyncio.gather
        task_futures = [_run_single_task(t) for t in plan.tasks]
        executed_pairs = await asyncio.gather(*task_futures)

        trace_entries: List[ResearchTraceEntry] = []
        all_results: List[SearchResult] = []
        seen_urls: set[str] = set()

        for trace, results in executed_pairs:
            trace_entries.append(trace)
            for r in results:
                if r.url and r.url in seen_urls:
                    continue
                if r.url:
                    seen_urls.add(r.url)
                all_results.append(r)

        logger.info(
            "ResearchAgent: Completed execution. Total unique results: %d across %d tasks",
            len(all_results),
            len(plan.tasks),
        )

        return ResearchExecutionResult(
            plan=plan,
            results=all_results,
            trace=trace_entries,
        )

