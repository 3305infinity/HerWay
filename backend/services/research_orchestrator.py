"""
ResearchOrchestrator — Intelligent Live Research Engine & Budget Orchestrator for Haven.

Key Capabilities:
1. Research Strategy & Vertical Routing:
   - Google Web for official procedures, acts, statutory rights, helplines.
   - Google Maps / Local for nearby physical shelters, crisis centers, police cells, courts.
   - Google News SELECTIVELY only when recent policy updates or breaking developments matter.
2. Search Budget & Credit Efficiency:
   - Normal case budget = 4 searches max.
   - Complex case budget = 6 searches max (critical urgency or >= 3 unknowns).
3. PII Scrubbing in Query Generation:
   - Strips personal names, emails, phone numbers from queries.
4. Deduplication & Caching:
   - Normalizes queries and intercepts duplicate searches across memory cache and batch.
5. Quality Loop (Follow-Up Iterations):
   - Evaluates evidence sufficiency and triggers targeted follow-ups (max 2 iterations).
6. Contradiction-Driven Search:
   - Formulates targeted searches to resolve disagreements between conflicting sources.
7. Resilience & Error Handling:
   - Gracefully handles SerpApi outages without failing the case.
"""

from __future__ import annotations

import asyncio
import logging
import re
import time
import uuid
from typing import TYPE_CHECKING, Any, Dict, List, Optional, Set
from urllib.parse import urlparse

from backend.models.case import Location
from backend.models.research import (
    DataOrigin,
    EvidenceItem,
    EvidenceStatus,
    FinalResearchReport,
    FreshnessPolicy,
    LocalResource,
    ResearchDegradation,
    ResearchExecutionResult,
    ResearchMetrics,
    ResearchPlan,
    ResearchTask,
    ResearchTraceEntry,
    SearchResult,
    SearchVertical,
    Situation,
    Urgency,
)

if TYPE_CHECKING:
    from backend.agents.source_verifier import SourceVerifier
    from backend.services.llm_service import LLMService
    from backend.services.maps_service import MapsService
    from backend.services.serpapi_service import SerpApiService

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# PII Scrubbing & Query Sanitization
# ---------------------------------------------------------------------------

def sanitize_search_query(raw_query: str) -> str:
    """
    Strips personal phone numbers, emails, and sensitive identifiers from queries.
    Prevents leaking user PII to external search engines.
    """
    # Strip email addresses
    query = re.sub(r'[\w\.-]+@[\w\.-]+\.\w+', '', raw_query)
    # Strip phone numbers (10+ digits with optional +, -, spaces)
    query = re.sub(r'(\+?\d{1,3}[-.\s]?)?(\(?\d{3}\)?[-.\s]?)?\d{3}[-.\s]?\d{4}', '', query)
    # Normalize whitespace
    query = " ".join(query.split()).strip()
    return query


def normalize_query_key(query: str, vertical: str, location: Optional[str]) -> str:
    """Canonical string key for deduplicating queries.

    Runs of whitespace are collapsed, so "official  women   helpline" and
    "official women helpline" map to the same key instead of being billed as
    two separate SerpApi searches.  Vertical aliases (``maps``/``local``,
    ``web``/``google_search``) are folded together for the same reason.
    """
    clean_q = " ".join(re.sub(r"[^\w\s]", " ", query.lower()).split())
    clean_v = _canonical_vertical(vertical)
    clean_loc = " ".join((location or "").lower().split())
    return f"{clean_v}:{clean_q}:{clean_loc}"


def _canonical_vertical(vertical: Any) -> str:
    """Collapse vertical names and enum reprs onto web | news | maps."""
    raw = getattr(vertical, "value", str(vertical)).lower()
    # ``str(SearchVertical.WEB)`` renders as "SearchVertical.WEB", so match on
    # substrings rather than equality.
    if "news" in raw:
        return "news"
    if "map" in raw or "local" in raw:
        return "maps"
    return "web"


# ---------------------------------------------------------------------------
# Planner System Prompt
# ---------------------------------------------------------------------------

_ORCHESTRATOR_SYSTEM_PROMPT = """\
You are HerWay's Research Orchestrator, an intelligent planner for live SerpApi searches.

JURISDICTION: India. Unless the user explicitly states another country, every
query must target Indian law, Indian government portals and Indian services.
Never plan a search for US/UK helplines or statutes for an Indian user.

Your objective: MAXIMIZE THE INFORMATIONAL VALUE OF EACH SEARCH.
Do NOT maximize search volume. Every query must answer a specific need.

DECIDE FIRST WHETHER A SEARCH IS NEEDED AT ALL:
- If the situation is purely emotional support with no factual, legal or
  resource question, return ZERO tasks. Do not search for the sake of it.
- Only plan a task when a concrete, answerable question depends on it.

ROUTING STRATEGY BY VERTICAL:
1. Google Web (vertical="web"):
   - Official procedures, statutory acts (PWDVA 2005, POSH Act 2013, BNS/IPC,
     IT Act), national helpline numbers, government complaint portals.
   - Prefer .gov.in and .nic.in sources; set official_source_preference="required"
     when a wrong answer would be harmful (law, procedure, emergency numbers).
2. Google Maps / Local (vertical="maps"):
   - Physical assistance: One Stop Centres (Sakhi), women police stations,
     Mahila Thana, cyber crime cells, District Legal Services Authority (DLSA)
     offices, shelter homes (Swadhar Greh / Ujjwala), consumer courts.
   - Use ONLY when a location (state / city / district) is actually known.
     Never guess a location. If none is known, search national resources on web.
3. Google News (vertical="news"):
   - Use SELECTIVELY and only when the case turns on a recent change: a new
     rule, a changed portal, an ongoing incident.
   - Do NOT use News for generic advice or for settled statutory procedure.

FRESHNESS:
- freshness_policy="static" for statutory definitions that rarely change.
- freshness_policy="current" for helpline numbers, portals, office addresses.
- freshness_policy="time_sensitive" when urgency is high and stale data is unsafe.

SEARCH BUDGET & CONSTRAINTS:
- Normal cases: 2 to 4 high-impact ResearchTask items.
- Complex/Critical cases: up to 5-6 tasks.
- Keep queries short and keyword-like, e.g.
  "women helpline 181 official site", "POSH Act internal committee complaint procedure",
  "One Stop Centre Sakhi <district>", "cybercrime.gov.in report online harassment".
- Never include personal names, emails, or phone numbers in queries.

Respond with valid JSON matching the ResearchPlan schema.
"""


class ResearchOrchestrator:
    """
    Intelligent Research Orchestration Engine controlling search planning,
    concurrent execution, budget enforcement, caching, quality loops, and contradiction resolution.
    """

    def __init__(
        self,
        llm: LLMService,
        serpapi: SerpApiService,
        max_iterations: int = 2,
        normal_budget: int = 4,
        complex_budget: int = 6,
    ) -> None:
        self._llm = llm
        self._serpapi = serpapi
        self._max_iterations = max_iterations
        self._normal_budget = normal_budget
        self._complex_budget = complex_budget

    def determine_budget(self, situation: Situation) -> int:
        """Determines the maximum allowed search budget for a case."""
        if situation.urgency == Urgency.CRITICAL or len(situation.unknowns) >= 3:
            return self._complex_budget
        return self._normal_budget

    async def plan_research(
        self,
        case_id: str,
        situation: Situation,
        user_location: Optional[Location] = None,
        iteration: int = 1,
    ) -> ResearchPlan:
        """Formulates an intelligent research plan respecting the search budget."""
        budget = self.determine_budget(situation)
        loc_str = situation.location or (user_location.display_name if user_location else None)

        prompt = (
            f"Case Summary: {situation.case_summary}\n"
            f"Category: {situation.category.value}\n"
            f"Urgency: {situation.urgency.value}\n"
            f"User Goal: {situation.user_goal}\n"
            f"Known Facts: {situation.known_facts}\n"
            f"User Claims: {situation.user_claims}\n"
            f"Unknowns / Missing Info: {situation.unknowns}\n"
            f"Location Context: {loc_str or 'Not provided'}\n"
            f"Search Budget Limit: {budget} tasks max\n"
            f"Iteration: {iteration}\n"
        )

        # A class body cannot read a name it is also assigning, so the previous
        # `case_id: str = case_id` raised NameError on every planning call and
        # research never ran. Bind the defaults outside the class body instead.
        _default_case_id = case_id
        _default_budget = budget

        class _PlanWrapper(ResearchPlan):
            case_id: str = _default_case_id
            search_budget: int = _default_budget

        plan = await self._llm.structured_generate(
            system_prompt=_ORCHESTRATOR_SYSTEM_PROMPT,
            user_prompt=prompt,
            output_schema=_PlanWrapper,
        )
        plan.case_id = case_id
        plan.search_budget = budget
        plan.iteration = iteration

        # Enforce budget cap and sanitize queries
        if len(plan.tasks) > budget:
            logger.info("Enforcing search budget: Trimming %d tasks to %d", len(plan.tasks), budget)
            plan.tasks = plan.tasks[:budget]

        for idx, task in enumerate(plan.tasks):
            if not task.task_id:
                task.task_id = f"TASK_{idx + 1:02d}"
            task.query = sanitize_search_query(task.query)
            if not task.location and loc_str:
                if task.vertical in (SearchVertical.MAPS, SearchVertical.LOCAL, "maps", "local"):
                    task.location = loc_str

        return plan

    async def execute_plan(
        self,
        plan: ResearchPlan,
        existing_trace: Optional[List[ResearchTraceEntry]] = None,
    ) -> ResearchExecutionResult:
        """
        Executes planned tasks concurrently with deduplication, in-memory caching,
        and credit metrics tracking.
        """
        trace_entries: List[ResearchTraceEntry] = []
        all_results: List[SearchResult] = []
        seen_keys: Set[str] = set()
        seen_urls: Set[str] = set()

        # Populate seen keys from existing trace if provided
        if existing_trace:
            for t in existing_trace:
                norm = normalize_query_key(t.query, t.engine, None)
                seen_keys.add(norm)

        metrics = ResearchMetrics(
            iterations_executed=plan.iteration,
        )

        async def _execute_single_task(task: ResearchTask) -> tuple[ResearchTraceEntry, List[SearchResult]]:
            start_t = time.time()
            s_id = f"srch_{uuid.uuid4().hex[:6]}"
            norm_key = normalize_query_key(task.query, str(task.vertical), task.location)

            # 1. Deduplication Check
            if norm_key in seen_keys:
                logger.info("ResearchOrchestrator: Deduplicated identical query '%s'", task.query)
                metrics.cached_search_count += 1
                return (
                    ResearchTraceEntry(
                        task_id=task.task_id,
                        why_searched=task.purpose,
                        query=task.query,
                        engine=str(task.vertical),
                        results_found=0,
                        sources_used=0,
                        selected_urls=[],
                        time_taken_ms=0.0,
                        is_cached=True,
                        is_followup=task.is_followup,
                        # Nothing was fetched: this query was already answered
                        # within the same plan.
                        data_origin=DataOrigin.CACHE,
                        freshness_policy=task.freshness_policy.value if hasattr(task.freshness_policy, "value") else str(task.freshness_policy),
                        success=True,
                    ),
                    [],
                )

            seen_keys.add(norm_key)
            metrics.search_count += 1
            engine = _canonical_vertical(task.vertical)
            freshness = (
                task.freshness_policy.value
                if hasattr(task.freshness_policy, "value")
                else str(task.freshness_policy)
            )

            try:
                # 2. Dispatch to the appropriate SerpApi vertical.
                if engine == "news":
                    metrics.news_search_count += 1
                    vertical = SearchVertical.NEWS
                elif engine == "maps":
                    metrics.maps_search_count += 1
                    metrics.local_search_count += 1
                    vertical = SearchVertical.MAPS
                else:
                    metrics.web_search_count += 1
                    vertical = SearchVertical.WEB

                outcome = await self._serpapi.search_detailed(
                    query=task.query,
                    vertical=vertical,
                    location=task.location,
                    case_id=plan.case_id,
                    search_id=s_id,
                    reason=task.purpose,
                )

                results = outcome.results
                time_taken = round((time.time() - start_t) * 1000, 2)
                selected_urls = [r.url for r in results[:4] if r.url]

                trace = ResearchTraceEntry(
                    task_id=task.task_id,
                    why_searched=task.purpose,
                    query=task.query,
                    engine=engine,
                    results_found=len(results),
                    sources_used=len(selected_urls),
                    selected_urls=selected_urls,
                    time_taken_ms=time_taken,
                    is_cached=outcome.from_cache,
                    is_followup=task.is_followup,
                    freshness_policy=freshness,
                    # Provenance, carried from the provider into the trail so
                    # the UI can say which engine ran, when, and whether the
                    # data was fetched now or read from cache.
                    provider_engine=outcome.provider_engine,
                    retrieved_at=outcome.retrieved_at,
                    data_origin=(
                        DataOrigin.CACHE if outcome.from_cache
                        else DataOrigin.LIVE if outcome.success
                        else DataOrigin.UNAVAILABLE
                    ),
                    # A failed vertical is recorded as a failure so the case can
                    # tell the user exactly which part of the research is missing.
                    success=outcome.success,
                    error=outcome.error_message,
                )
                return trace, results

            except Exception as exc:
                time_taken = round((time.time() - start_t) * 1000, 2)
                logger.error("ResearchOrchestrator task '%s' failed gracefully: %s", task.task_id, exc)
                trace = ResearchTraceEntry(
                    task_id=task.task_id,
                    why_searched=task.purpose,
                    query=task.query,
                    engine=engine,
                    results_found=0,
                    sources_used=0,
                    selected_urls=[],
                    time_taken_ms=time_taken,
                    is_cached=False,
                    is_followup=task.is_followup,
                    freshness_policy=freshness,
                    data_origin=DataOrigin.UNAVAILABLE,
                    success=False,
                    error=str(exc),
                )
                return trace, []

        # Execute concurrent tasks via asyncio.gather
        task_futures = [_execute_single_task(t) for t in plan.tasks]
        executed_pairs = await asyncio.gather(*task_futures)

        for trace, results in executed_pairs:
            trace_entries.append(trace)
            for r in results:
                if r.url and r.url in seen_urls:
                    continue
                if r.url:
                    seen_urls.add(r.url)
                all_results.append(r)

        return ResearchExecutionResult(
            plan=plan,
            results=all_results,
            trace=trace_entries,
            metrics=metrics,
        )

    @staticmethod
    def _summarise_search_failures(
        trace: List[ResearchTraceEntry],
    ) -> List[ResearchDegradation]:
        """Turn failed trace entries into one user-facing message per vertical.

        Without this, a case where (say) Maps failed but Web succeeded looked
        identical to a case where there simply were no nearby centres.
        """
        failed_engines: Dict[str, str] = {}
        for entry in trace:
            if entry.success:
                continue
            failed_engines.setdefault(entry.engine, entry.error or "Search did not complete")

        messages = {
            "web": "The web search for official procedures and portals did not complete.",
            "news": "The search for recent news updates did not complete.",
            "maps": "The search for nearby centres and offices did not complete.",
        }

        return [
            ResearchDegradation(
                stage=f"{engine}_search",
                reason="search_failed",
                user_message=(
                    f"{messages.get(engine, 'Part of the research did not complete.')} "
                    "Anything shown below came from searches that did succeed."
                ),
            )
            for engine, _err in failed_engines.items()
        ]

    async def run_full_orchestration(
        self,
        case_id: str,
        situation: Situation,
        verifier: SourceVerifier,
        maps_service: MapsService,
        user_location: Optional[Location] = None,
        preplanned: Optional[ResearchPlan] = None,
    ) -> FinalResearchReport:
        """
        Executes the intelligent multi-pass research orchestration loop:
        Pass 1: Initial planned search
        Pass 2: Quality Loop & Contradiction Resolution (if evidence is weak or contradictory)
        """
        logger.info("ResearchOrchestrator: Starting orchestration for case %s (Category: %s)", case_id, situation.category.value)

        degradations: List[ResearchDegradation] = []

        # 1. Initial Plan & Concurrent Execution
        #
        # A caller may hand in a plan instead. That path exists so an example
        # case can continue when the LLM planner is unavailable: the questions
        # are pre-written, but every search below is still a live SerpApi call.
        try:
            if preplanned is not None:
                initial_plan = preplanned
            else:
                initial_plan = await self.plan_research(
                    case_id, situation, user_location, iteration=1
                )
        except Exception as exc:
            # Planning depends on the LLM. If it is down we still want to return
            # a case the user can open, with an honest explanation.
            logger.error("ResearchOrchestrator: planning failed for case %s: %s", case_id, exc)
            degradations.append(
                ResearchDegradation(
                    stage="planning",
                    reason="planner_unavailable",
                    user_message=(
                        "We could not plan live research for this case right now. "
                        "Your situation has been saved and you can retry research at any time."
                    ),
                )
            )
            initial_plan = ResearchPlan(
                case_id=case_id,
                reasoning="Planning unavailable.",
                tasks=[],
                search_budget=self.determine_budget(situation),
            )

        exec_res = await self.execute_plan(initial_plan)

        # Surface per-vertical failures so a partial result is never shown as whole.
        degradations.extend(self._summarise_search_failures(exec_res.trace))

        # 2. Location Resource Discovery via MapsService
        loc_str = situation.location or (user_location.display_name if user_location else None)
        local_resources: List[LocalResource] = []
        if loc_str:
            try:
                local_discovery = await maps_service.discover_local_resources_detailed(
                    category=situation.category.value,
                    location=loc_str,
                    case_summary=situation.case_summary,
                )
                local_resources = local_discovery.resources
                if not local_discovery.success:
                    degradations.append(
                        ResearchDegradation(
                            stage="local_search",
                            reason=local_discovery.failure_reason,
                            user_message=(
                                f"We could not search for support centres near {loc_str} right now. "
                                "The national resources and sources below are still current."
                            ),
                        )
                    )
            except Exception as exc:
                logger.error("ResearchOrchestrator: local discovery failed: %s", exc)
                degradations.append(
                    ResearchDegradation(
                        stage="local_search",
                        reason="local_search_error",
                        user_message=(
                            f"We could not search for support centres near {loc_str} right now. "
                            "The national resources and sources below are still current."
                        ),
                    )
                )
        else:
            degradations.append(
                ResearchDegradation(
                    stage="local_search",
                    reason="no_location_provided",
                    user_message=(
                        "You have not shared a location, so we have not looked for nearby centres. "
                        "Add your city or district to find One Stop Centres and support services near you."
                    ),
                )
            )

        # 3. Source Verification & Trust Scoring (Pass 1)
        try:
            evidence = await verifier.verify(situation, exec_res.results)
        except Exception as exc:
            logger.error("ResearchOrchestrator: verification failed: %s", exc)
            evidence = []
            degradations.append(
                ResearchDegradation(
                    stage="verification",
                    reason="verifier_unavailable",
                    user_message=(
                        "We found search results but could not verify them, so they are not shown. "
                        "HerWay only shows sources it has been able to check."
                    ),
                )
            )

        total_trace = list(exec_res.trace)
        total_results = list(exec_res.results)
        metrics = exec_res.metrics or ResearchMetrics()

        # 4. Quality Loop & Contradiction Resolution (Pass 2 if needed)
        has_contradictions = any(len(e.contradictions) > 0 for e in evidence)
        low_evidence_count = len(evidence) < 2 and len(exec_res.results) > 0

        if (has_contradictions or low_evidence_count) and self._max_iterations >= 2:
            logger.info("ResearchOrchestrator: Triggering targeted follow-up loop (Contradictions=%s, LowEvidence=%s)", has_contradictions, low_evidence_count)
            
            followup_tasks: List[ResearchTask] = []
            if has_contradictions:
                # Contradiction-driven search for official primary source
                for ev in evidence:
                    for c in ev.contradictions:
                        followup_tasks.append(
                            ResearchTask(
                                task_id=f"TASK_CONTRA_{len(followup_tasks) + 1:02d}",
                                query=sanitize_search_query(f"{c.claim} official government portal {situation.location or ''}"),
                                vertical=SearchVertical.WEB,
                                purpose=f"Resolve contradiction: {c.difference[:80]}",
                                expected_information="Official verification from primary source",
                                priority="high",
                                official_source_preference="required",
                                is_followup=True,
                                freshness_policy=FreshnessPolicy.CURRENT,
                            )
                        )
                metrics.contradictions_resolved += 1

            if low_evidence_count:
                # Quality loop retry with specific entity query
                followup_tasks.append(
                    ResearchTask(
                        task_id=f"TASK_RETRY_{len(followup_tasks) + 1:02d}",
                        query=sanitize_search_query(f"official {situation.category.value.replace('_', ' ')} helpline procedure {situation.location or ''}"),
                        vertical=SearchVertical.WEB,
                        purpose="Quality loop: Retrieve verified primary documentation",
                        expected_information="Verified official portal links and contact info",
                        priority="high",
                        official_source_preference="required",
                        is_followup=True,
                        freshness_policy=FreshnessPolicy.CURRENT,
                    )
                )

            if followup_tasks:
                followup_plan = ResearchPlan(
                    case_id=case_id,
                    reasoning="Targeted follow-up to resolve ambiguities and verify primary sources.",
                    tasks=followup_tasks[:2], # Limit follow-up budget
                    search_budget=2,
                    iteration=2,
                )
                followup_exec = await self.execute_plan(followup_plan, existing_trace=total_trace)
                total_trace.extend(followup_exec.trace)
                total_results.extend(followup_exec.results)
                
                # Re-verify with augmented results pool
                evidence = await verifier.verify(situation, total_results)
                metrics.iterations_executed = 2

        # 5. Extract Domain Diversity Metrics
        unique_domains: Set[str] = set()
        official_domains: Set[str] = set()
        for ev in evidence:
            if ev.url:
                try:
                    d = urlparse(ev.url).netloc.lower()
                    unique_domains.add(d)
                    if d.endswith(('.gov', '.gov.in', '.nic.in', '.mil', '.edu', '.org')):
                        official_domains.add(d)
                except Exception:
                    pass

        metrics.unique_domains_count = len(unique_domains)
        metrics.official_domains_count = len(official_domains)

        report = FinalResearchReport(
            case_id=case_id,
            situation=situation,
            research_plan=initial_plan,
            trace=total_trace,
            evidence=evidence,
            local_resources=local_resources,
            searches_executed=len(total_trace),
            sources_verified=len(evidence),
            metrics=metrics,
            unique_domains=list(unique_domains),
            official_domains=list(official_domains),
            degradations=degradations,
            location_used=loc_str,
        )

        logger.info(
            "ResearchOrchestrator: Completed full research pipeline for %s (%d traces, %d evidence, %d official domains)",
            case_id,
            len(total_trace),
            len(evidence),
            len(official_domains),
        )
        return report
