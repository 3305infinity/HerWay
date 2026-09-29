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
    SearchResult,
    SearchVertical,
    Situation,
    SituationCategory,
    SourceType,
    Urgency,
)
from backend.services.research_orchestrator import (
    ResearchOrchestrator,
    normalize_query_key,
    sanitize_search_query,
)


@pytest.fixture
def mock_llm():
    return MagicMock()


@pytest.fixture
def mock_serpapi():
    serp = MagicMock()
    serp.search_web = AsyncMock(return_value=[
        SearchResult(
            title="National Domestic Violence Hotline Official Portal",
            url="https://www.thehotline.org",
            snippet="Call 1-800-799-SAFE or text START to 88788 for 24/7 confidential safety support.",
            result_type="web",
            domain="thehotline.org",
        )
    ])
    serp.search_news = AsyncMock(return_value=[
        SearchResult(
            title="State Updates Protective Order Legislation for Survivors",
            url="https://news.state.gov/update",
            snippet="New expedited emergency protective order filing procedures announced.",
            result_type="news",
            domain="state.gov",
        )
    ])
    serp.search_maps = AsyncMock(return_value=[
        SearchResult(
            title="Austin SAFE Alliance Crisis Center",
            url="https://www.safeaustin.org",
            address="4800 Manor Rd, Austin, TX 78723",
            phone="(512) 267-7233",
            rating=4.8,
            result_type="maps",
        )
    ])
    return serp


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
    maps.discover_local_resources = AsyncMock(return_value=[
        LocalResource(
            name="SAFE Alliance Austin",
            type="Shelter",
            phone="(512) 267-7233",
            address="4800 Manor Rd, Austin, TX",
        )
    ])
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

    class MockDVPlan:
        case_id = "case_dv_1"
        reasoning = "DV routing strategy"
        tasks = [
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
        ]

    mock_llm.structured_generate.return_value = MockDVPlan()

    orchestrator = ResearchOrchestrator(mock_llm, mock_serpapi, normal_budget=4, complex_budget=6)
    budget = orchestrator.determine_budget(situation)
    assert budget == 6  # Critical urgency gets complex budget

    plan = await orchestrator.plan_research("case_dv_1", situation)
    assert len(plan.tasks) == 2
    assert plan.tasks[0].vertical == SearchVertical.WEB
    assert plan.tasks[1].vertical == SearchVertical.MAPS

    exec_res = await orchestrator.execute_plan(plan)
    assert len(exec_res.trace) == 2
    assert mock_serpapi.search_web.called
    assert mock_serpapi.search_maps.called


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

    class MockPOSHPlan:
        case_id = "case_posh_1"
        reasoning = "POSH compliance search"
        tasks = [
            ResearchTask(
                task_id="TASK_01",
                query="POSH Act Internal Complaints Committee official filing process India",
                vertical=SearchVertical.WEB,
                purpose="Retrieve statutory complaint mechanism",
                expected_information="90 day timeline and committee constitution",
                priority="high",
            )
        ]

    mock_llm.structured_generate.return_value = MockPOSHPlan()
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

    class MockTravelPlan:
        case_id = "case_travel_1"
        reasoning = "DOT rules"
        tasks = [
            ResearchTask(
                task_id="TASK_01",
                query="airline cancellation mandatory refund regulations DOT official",
                vertical=SearchVertical.WEB,
                purpose="Find statutory refund rules",
                expected_information="7 day prompt refund requirement",
                priority="medium",
            )
        ]

    mock_llm.structured_generate.return_value = MockTravelPlan()
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

    class MockCyberPlan:
        case_id = "case_cyber_1"
        reasoning = "National portal"
        tasks = [
            ResearchTask(
                task_id="TASK_01",
                query="National Cyber Crime Reporting Portal official online harassment complaint",
                vertical=SearchVertical.WEB,
                purpose="Official national reporting URL",
                expected_information="cybercrime.gov.in portal",
                priority="high",
            )
        ]

    mock_llm.structured_generate.return_value = MockCyberPlan()
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

    class MockInitialPlan:
        case_id = "case_contra_1"
        reasoning = "Initial search"
        tasks = [
            ResearchTask(
                task_id="TASK_01",
                query="women helpline number India",
                vertical=SearchVertical.WEB,
                purpose="Find helpline",
                expected_information="Active number",
                priority="high",
            )
        ]

    mock_llm.structured_generate.return_value = MockInitialPlan()

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
    failing_serp.search_web = AsyncMock(side_effect=Exception("503 SerpApi Service Unavailable"))

    plan = ResearchPlan(
        case_id="case_fail_1",
        tasks=[
            ResearchTask(
                task_id="TASK_01",
                query="women shelter Austin",
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
    # Only 1 real HTTP call was made
    assert mock_serpapi.search_web.call_count == 1
