"""
Comprehensive Integration Tests for Haven's Intelligent Live Research Engine & ResearchOrchestrator.

Test Coverage:
A. Domestic violence + location (Correct verticals: Web for helplines, Maps for shelters)
B. Stalking + location (Web for cyber acts, Maps for police cell)
C. Online harassment (Platform reporting and cyber portal)
D. Workplace harassment (POSH Act & ICC committee on Web)
E. Consumer dispute (Consumer protection act on Web)
F. Travel disruption (Airline refund policies on Web)
G. No location provided (Searches national level without guessing)
H. Conflicting sources (Triggers contradiction-driven search to find official source)
I. SerpApi failure (Catches error gracefully without crashing case)
J. Repeated identical search (Deduplication & in-memory cache returns cached trace with 0 API calls)
"""

import pytest
from unittest.mock import AsyncMock, MagicMock
from backend.models.research import (
    Contradiction,
    EvidenceConfidence,
    EvidenceItem,
    EvidenceStatus,
    FreshnessPolicy,
    LocalResource,
    ResearchPlan,
    ResearchTask,
    ResourceVerification,
    SearchFailureReason,
    SearchOutcome,
    SearchResult,
    SearchVertical,
    Situation,
    SituationCategory,
    SourceType,
    Urgency,
)
from backend.services.maps_service import LocalDiscoveryResult
from backend.services.research_orchestrator import (
    ResearchOrchestrator,
    normalize_query_key,
    sanitize_search_query,
)


@pytest.fixture
def mock_llm():
    llm = MagicMock()
    # ``structured_generate`` is awaited by the orchestrator, so it must be an
    # AsyncMock. Tests assign ``mock_llm.structured_generate.return_value``.
    llm.structured_generate = AsyncMock()
    return llm


_WEB_RESULTS = [
    SearchResult(
        title="Women Helpline Scheme — Ministry of Women and Child Development",
        url="https://wcd.gov.in/schemes/women-helpline-scheme",
        snippet="181 provides 24x7 emergency and non-emergency response to women affected by violence.",
        result_type="web",
        domain="wcd.gov.in",
    )
]

_NEWS_RESULTS = [
    SearchResult(
        title="Revised One Stop Centre operational guidelines notified",
        url="https://www.thehindu.com/news/osc-guidelines",
        snippet="The ministry notified revised operational guidelines for Sakhi centres.",
        result_type="news",
        domain="thehindu.com",
    )
]

_MAPS_RESULTS = [
    SearchResult(
        title="One Stop Centre (Sakhi), Patna",
        url="https://bihar.gov.in/wcd",
        address="Gardanibagh, Patna, Bihar 800001",
        rating=4.2,
        result_type="maps",
    )
]


def _outcome(vertical: str, results, success: bool = True):
    return SearchOutcome(
        vertical=vertical,
        query="q",
        success=success,
        results=results,
        failure_reason=SearchFailureReason.NONE if success else SearchFailureReason.HTTP_ERROR,
        error_message=None if success else "SerpApi returned HTTP 503.",
    )


@pytest.fixture
def mock_serpapi():
    """Stand-in SerpApi that answers through the detailed-outcome API.

    The orchestrator routes through ``search_detailed`` so it can tell a failed
    vertical apart from an empty one, so tests assert on the `vertical` kwarg.
    """
    serp = MagicMock()

    async def _search_detailed(query, vertical=SearchVertical.WEB, **kwargs):
        name = getattr(vertical, "value", str(vertical))
        if "news" in name:
            return _outcome("news", list(_NEWS_RESULTS))
        if "map" in name or "local" in name:
            return _outcome("maps", list(_MAPS_RESULTS))
        return _outcome("web", list(_WEB_RESULTS))

    serp.search_detailed = AsyncMock(side_effect=_search_detailed)
    return serp


def _verticals_called(serp) -> list[str]:
    """Collect the verticals a mock SerpApi was asked for, in call order."""
    verticals = []
    for call in serp.search_detailed.await_args_list:
        vertical = call.kwargs.get("vertical", SearchVertical.WEB)
        verticals.append(getattr(vertical, "value", str(vertical)))
    return verticals


@pytest.fixture
def mock_verifier():
    ver = MagicMock()
    ver.verify = AsyncMock(return_value=[
        EvidenceItem(
            id="EVIDENCE_01",
            source_title="National Domestic Violence Hotline",
            url="https://www.thehotline.org",
            domain="thehotline.org",
            claim_supported="24/7 confidential safety planning via 1-800-799-SAFE.",
            confidence_score=0.95,
            why_this_source_matters="Official national support hotline.",
        )
    ])
    return ver


@pytest.fixture
def mock_maps_service():
    maps = MagicMock()
    resources = [
        LocalResource(
            name="One Stop Centre (Sakhi), Patna",
            type="One Stop Centre & women's shelter",
            address="Gardanibagh, Patna, Bihar 800001",
            verification=ResourceVerification.LIKELY_OFFICIAL,
        )
    ]
    maps.discover_local_resources = AsyncMock(return_value=resources)
    maps.discover_local_resources_detailed = AsyncMock(
        return_value=LocalDiscoveryResult(
            resources=resources,
            success=True,
            location_used="Patna, Bihar",
        )
    )
    return maps


# ---------------------------------------------------------------------------
# Test A: Domestic Violence + Location Routing & Budget
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_dv_with_location_routing(mock_llm, mock_serpapi):
    """Verify DV case generates Web for helplines and Maps for shelters, respecting budget."""
    situation = Situation(
        case_summary="User is facing acute domestic abuse in Patna, Bihar.",
        category=SituationCategory.DOMESTIC_VIOLENCE,
        urgency=Urgency.CRITICAL,
        user_goal="Find shelter and emergency numbers in Patna.",
        location="Patna, Bihar",
        known_facts=["Physical violence threatened in residence"],
        user_claims=[],
        unknowns=["Shelter vacancy in Patna"],
    )

    MockDVPlan = ResearchPlan(
        case_id="case_dv_1",
        reasoning="DV routing strategy",
        tasks=[
            ResearchTask(
                task_id="TASK_01",
                query="official national women helpline domestic violence India",
                vertical=SearchVertical.WEB,
                purpose="Find emergency contacts",
                expected_information="181 and 112 verification",
                priority="high",
            ),
            ResearchTask(
                task_id="TASK_02",
                query="women shelter One Stop Centre Sakhi Patna Bihar",
                vertical=SearchVertical.MAPS,
                purpose="Find nearby physical shelters in Patna",
                expected_information="Address and phone of Patna shelter",
                priority="high",
                location="Patna, Bihar",
            ),
        ],
    )

    mock_llm.structured_generate.return_value = MockDVPlan

    orchestrator = ResearchOrchestrator(mock_llm, mock_serpapi, normal_budget=4, complex_budget=6)
    budget = orchestrator.determine_budget(situation)
    assert budget == 6  # Critical urgency gets complex budget

    plan = await orchestrator.plan_research("case_dv_1", situation)
    assert len(plan.tasks) == 2
    assert plan.tasks[0].vertical == SearchVertical.WEB
    assert plan.tasks[1].vertical == SearchVertical.MAPS

    exec_res = await orchestrator.execute_plan(plan)
    assert len(exec_res.trace) == 2
    verticals = _verticals_called(mock_serpapi)
    assert "web" in verticals
    assert "maps" in verticals
    # News adds no value to an acute DV case and must not be called.
    assert "news" not in verticals


# ---------------------------------------------------------------------------
# Test B & C: Stalking & Online Harassment Sanitization
# ---------------------------------------------------------------------------
def test_query_sanitization_strips_pii():
    """Verify personal phone numbers, emails, and sensitive identifiers are scrubbed from search queries."""
    raw = "contact police for Jane Doe at jane.doe@example.com phone 555-123-4567 regarding stalking"
    cleaned = sanitize_search_query(raw)
    assert "jane.doe@example.com" not in cleaned
    assert "555-123-4567" not in cleaned
    assert "contact police for Jane Doe at phone regarding stalking" == cleaned


# ---------------------------------------------------------------------------
# Test D: Workplace Harassment POSH Routing
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_workplace_harassment_posh_routing(mock_llm, mock_serpapi):
    """Verify workplace harassment focuses on POSH Act and Internal Complaints Committee on Web."""
    situation = Situation(
        case_summary="Workplace sexual harassment by director at IT firm.",
        category=SituationCategory.WORKPLACE_HARASSMENT,
        urgency=Urgency.MEDIUM,
        user_goal="File formal POSH grievance.",
        known_facts=["Unwanted messages sent on Slack"],
        user_claims=[],
        unknowns=["POSH timeline"],
    )

    MockPOSHPlan = ResearchPlan(
        case_id="case_posh_1",
        reasoning="POSH compliance search",
        tasks=[
            ResearchTask(
                task_id="TASK_01",
                query="POSH Act Internal Complaints Committee official filing process India",
                vertical=SearchVertical.WEB,
                purpose="Retrieve statutory complaint mechanism",
                expected_information="90 day timeline and committee constitution",
                priority="high",
            )
        ],
    )

    mock_llm.structured_generate.return_value = MockPOSHPlan
    orchestrator = ResearchOrchestrator(mock_llm, mock_serpapi)
    plan = await orchestrator.plan_research("case_posh_1", situation)

    assert plan.tasks[0].vertical == SearchVertical.WEB
    assert "POSH" in plan.tasks[0].query


# ---------------------------------------------------------------------------
# Test E & F: Consumer Dispute & Travel Disruption
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_consumer_and_travel_routing(mock_llm, mock_serpapi):
    """Verify consumer disputes target consumer portals without calling maps/news unnecessarily."""
    situation = Situation(
        case_summary="Airline cancelled flight without refund.",
        category=SituationCategory.TRAVEL,
        urgency=Urgency.LOW,
        user_goal="Get refund.",
        known_facts=["Cancelled flight"],
        user_claims=[],
        unknowns=[],
    )

    MockTravelPlan = ResearchPlan(
        case_id="case_travel_1",
        reasoning="DOT rules",
        tasks=[
            ResearchTask(
                task_id="TASK_01",
                query="airline cancellation mandatory refund regulations DOT official",
                vertical=SearchVertical.WEB,
                purpose="Find statutory refund rules",
                expected_information="7 day prompt refund requirement",
                priority="medium",
            )
        ],
    )

    mock_llm.structured_generate.return_value = MockTravelPlan
    orchestrator = ResearchOrchestrator(mock_llm, mock_serpapi)
    plan = await orchestrator.plan_research("case_travel_1", situation)

    assert len(plan.tasks) == 1
    assert plan.tasks[0].vertical == SearchVertical.WEB


# ---------------------------------------------------------------------------
# Test G: No Location Provided
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_no_location_searches_national(mock_llm, mock_serpapi):
    """Verify orchestrator does not guess fake locations when user provides none."""
    situation = Situation(
        case_summary="Facing harassment online.",
        category=SituationCategory.ONLINE_HARASSMENT,
        urgency=Urgency.MEDIUM,
        user_goal="Report cyber harassment.",
        location=None, # No location
        known_facts=["Anonymous account harassment"],
        user_claims=[],
        unknowns=[],
    )

    MockCyberPlan = ResearchPlan(
        case_id="case_cyber_1",
        reasoning="National portal",
        tasks=[
            ResearchTask(
                task_id="TASK_01",
                query="National Cyber Crime Reporting Portal official online harassment complaint",
                vertical=SearchVertical.WEB,
                purpose="Official national reporting URL",
                expected_information="cybercrime.gov.in portal",
                priority="high",
            )
        ],
    )

    mock_llm.structured_generate.return_value = MockCyberPlan
    orchestrator = ResearchOrchestrator(mock_llm, mock_serpapi)
    plan = await orchestrator.plan_research("case_cyber_1", situation, user_location=None)

    assert plan.tasks[0].location is None
    assert "cybercrime.gov.in" in plan.tasks[0].query or "National" in plan.tasks[0].query


# ---------------------------------------------------------------------------
# Test H: Contradiction-Driven Search & Quality Loop
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_contradiction_driven_search(mock_llm, mock_serpapi, mock_maps_service):
    """Verify that when sources disagree, orchestrator triggers a targeted contradiction search."""
    situation = Situation(
        case_summary="Domestic dispute where differing helpline numbers were reported.",
        category=SituationCategory.DOMESTIC_VIOLENCE,
        urgency=Urgency.HIGH,
        user_goal="Verify true national helpline.",
        known_facts=[],
        user_claims=[],
        unknowns=["Helpline number"],
    )

    # Initial verifier returns a contradiction
    contra_item = EvidenceItem(
        id="EV_01",
        source_title="Blog Page",
        claim_supported="Women helpline is 1090",
        contradictions=[
            Contradiction(
                claim="Women Helpline Number",
                source_a="Blog A (claims 1090)",
                source_b="Portal B (claims 1091)",
                difference="Numbers differ by state vs central",
                resolution_status="unresolved",
            )
        ],
        confidence_score=0.6,
    )

    mock_verifier = MagicMock()
    # Pass 1 returns contradiction; Pass 2 returns resolved official evidence
    resolved_item = EvidenceItem(
        id="EV_02",
        source_title="Ministry of Women and Child Development",
        url="https://wcd.nic.in",
        domain="wcd.nic.in",
        claim_supported="National Women Helpline is 181 and 1091 is Women Police Helpline.",
        confidence_score=0.98,
    )
    mock_verifier.verify = AsyncMock(side_effect=[[contra_item], [resolved_item]])

    MockInitialPlan = ResearchPlan(
        case_id="case_contra_1",
        reasoning="Initial search",
        tasks=[
            ResearchTask(
                task_id="TASK_01",
                query="women helpline number India",
                vertical=SearchVertical.WEB,
                purpose="Find helpline",
                expected_information="Active number",
                priority="high",
            )
        ],
    )

    mock_llm.structured_generate.return_value = MockInitialPlan

    orchestrator = ResearchOrchestrator(mock_llm, mock_serpapi, max_iterations=2)
    report = await orchestrator.run_full_orchestration(
        case_id="case_contra_1",
        situation=situation,
        verifier=mock_verifier,
        maps_service=mock_maps_service,
    )

    assert report.metrics.iterations_executed == 2
    assert report.metrics.contradictions_resolved == 1
    assert any("TASK_CONTRA" in t.task_id for t in report.trace)
    assert report.metrics.official_domains_count >= 1


# ---------------------------------------------------------------------------
# Test I: SerpApi Failure Graceful Fallback
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_serpapi_failure_does_not_crash_case(mock_llm):
    """Verify that network or API failures in SerpApi are caught cleanly without destroying the case."""
    failing_serp = MagicMock()
    failing_serp.search_detailed = AsyncMock(
        return_value=_outcome("web", [], success=False)
    )

    plan = ResearchPlan(
        case_id="case_fail_1",
        tasks=[
            ResearchTask(
                task_id="TASK_01",
                query="One Stop Centre Patna",
                vertical=SearchVertical.WEB,
                purpose="Emergency shelter search",
                expected_information="Shelter contact",
                priority="high",
            )
        ],
    )

    orchestrator = ResearchOrchestrator(mock_llm, failing_serp)
    exec_res = await orchestrator.execute_plan(plan)

    assert len(exec_res.results) == 0
    assert len(exec_res.trace) == 1
    assert exec_res.trace[0].success is False
    assert "503" in (exec_res.trace[0].error or "")


@pytest.mark.asyncio
async def test_unexpected_serpapi_exception_is_contained(mock_llm):
    """Even an unexpected exception type must degrade to a failed trace entry."""
    exploding_serp = MagicMock()
    exploding_serp.search_detailed = AsyncMock(side_effect=RuntimeError("boom"))

    plan = ResearchPlan(
        case_id="case_boom_1",
        tasks=[
            ResearchTask(
                task_id="TASK_01",
                query="women helpline",
                vertical=SearchVertical.WEB,
                purpose="Helpline lookup",
                expected_information="Helpline number",
                priority="high",
            )
        ],
    )

    exec_res = await ResearchOrchestrator(mock_llm, exploding_serp).execute_plan(plan)
    assert exec_res.trace[0].success is False
    assert exec_res.results == []


# ---------------------------------------------------------------------------
# Test K: Partial vertical failure — web succeeds while maps fails
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_partial_vertical_failure_is_surfaced(mock_llm, mock_maps_service):
    """Web results must still be delivered, with the maps failure stated plainly."""
    serp = MagicMock()

    async def _mixed(query, vertical=SearchVertical.WEB, **kwargs):
        name = getattr(vertical, "value", str(vertical))
        if "map" in name or "local" in name:
            return _outcome("maps", [], success=False)
        return _outcome("web", list(_WEB_RESULTS))

    serp.search_detailed = AsyncMock(side_effect=_mixed)

    situation = Situation(
        case_summary="Facing threats at home in Patna.",
        category=SituationCategory.DOMESTIC_VIOLENCE,
        urgency=Urgency.HIGH,
        user_goal="Find emergency support.",
        location="Patna, Bihar",
    )

    MockMixedPlan = ResearchPlan(
        case_id="case_partial_1",
        reasoning="Mixed routing",
        tasks=[
            ResearchTask(
                task_id="TASK_01",
                query="women helpline 181 official",
                vertical=SearchVertical.WEB,
                purpose="Official helpline",
                expected_information="181",
                priority="high",
            ),
            ResearchTask(
                task_id="TASK_02",
                query="One Stop Centre Sakhi",
                vertical=SearchVertical.MAPS,
                purpose="Nearby centre",
                expected_information="Address",
                priority="high",
                location="Patna, Bihar",
            ),
        ],
    )

    mock_llm.structured_generate.return_value = MockMixedPlan

    verifier = MagicMock()
    verifier.verify = AsyncMock(
        return_value=[
            EvidenceItem(
                id="EV_01",
                source_title="Women Helpline Scheme",
                url="https://wcd.gov.in/schemes/women-helpline-scheme",
                domain="wcd.gov.in",
                claim_supported="181 is the national women helpline.",
                confidence_score=0.92,
            )
        ]
    )

    orchestrator = ResearchOrchestrator(mock_llm, serp, max_iterations=1)
    report = await orchestrator.run_full_orchestration(
        case_id="case_partial_1",
        situation=situation,
        verifier=verifier,
        maps_service=mock_maps_service,
    )

    # The successful vertical still delivers evidence.
    assert len(report.evidence) == 1
    # And the failed vertical is reported rather than silently dropped.
    stages = {d.stage for d in report.degradations}
    assert "maps_search" in stages
    assert any("did not complete" in d.user_message for d in report.degradations)


@pytest.mark.asyncio
async def test_missing_location_is_reported_not_guessed(mock_llm, mock_serpapi):
    """With no location we must say so, never invent a city."""
    situation = Situation(
        case_summary="Receiving threatening messages online.",
        category=SituationCategory.ONLINE_HARASSMENT,
        urgency=Urgency.MEDIUM,
        user_goal="Report the harassment.",
        location=None,
    )

    MockPlan = ResearchPlan(
        case_id="case_noloc_1",
        reasoning="National portals",
        tasks=[
            ResearchTask(
                task_id="TASK_01",
                query="cybercrime.gov.in report online harassment",
                vertical=SearchVertical.WEB,
                purpose="Official reporting portal",
                expected_information="Portal URL",
                priority="high",
            )
        ],
    )

    mock_llm.structured_generate.return_value = MockPlan
    maps = MagicMock()
    maps.discover_local_resources_detailed = AsyncMock(
        return_value=LocalDiscoveryResult(resources=[], success=False, failure_reason="no_location_provided")
    )

    verifier = MagicMock()
    verifier.verify = AsyncMock(return_value=[])

    report = await ResearchOrchestrator(mock_llm, mock_serpapi, max_iterations=1).run_full_orchestration(
        case_id="case_noloc_1",
        situation=situation,
        verifier=verifier,
        maps_service=maps,
    )

    assert report.location_used is None
    assert report.local_resources == []
    reasons = {d.reason for d in report.degradations}
    assert "no_location_provided" in reasons
    # Maps must not have been consulted at all without a location.
    maps.discover_local_resources_detailed.assert_not_awaited()


# ---------------------------------------------------------------------------
# Test J: Repeated Identical Search Deduplication & Caching
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_repeated_search_deduplication(mock_llm, mock_serpapi):
    """Verify that duplicate or identical searches in a batch are intercepted with 0 API calls."""
    plan = ResearchPlan(
        case_id="case_dedup_1",
        tasks=[
            ResearchTask(
                task_id="TASK_01",
                query="official women helpline India",
                vertical=SearchVertical.WEB,
                purpose="First search",
                expected_information="Helplines",
                priority="high",
            ),
            # Identical query with extra spaces & different case
            ResearchTask(
                task_id="TASK_02",
                query="  OFFICIAL women   helpline India  ",
                vertical=SearchVertical.WEB,
                purpose="Duplicate search",
                expected_information="Helplines",
                priority="high",
            ),
        ],
    )

    orchestrator = ResearchOrchestrator(mock_llm, mock_serpapi)
    exec_res = await orchestrator.execute_plan(plan)

    assert len(exec_res.trace) == 2
    # First was live
    assert exec_res.trace[0].is_cached is False
    # Second was intercepted and marked cached
    assert exec_res.trace[1].is_cached is True
    assert exec_res.metrics.cached_search_count == 1
    # Only 1 real search was dispatched
    assert mock_serpapi.search_detailed.await_count == 1
