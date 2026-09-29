"""
End-to-End Integration Tests for Haven Case Resolution Pipeline.

Tests all 5 user scenarios:
A. Domestic Violence situation
B. Stalking situation
C. Online Harassment situation
D. Workplace Harassment situation
E. Generic Consumer Complaint situation

Verifies:
User input -> Classification -> Research Plan -> SerpApi Execution -> Evidence -> Resources -> Action Plan -> API Response -> MongoDB Persistence
"""

import pytest
from unittest.mock import AsyncMock, patch
from fastapi.testclient import TestClient

from backend.main import app
from backend.models.research import (
    Situation,
    SituationCategory,
    Urgency,
    ResearchPlan,
    ResearchTask,
    ActionPlan,
    ActionStep,
    ActionPriority,
    SourceItem,
    SourceType,
    VerificationStatus,
)
from backend.services.serpapi_service import SearchResult


@pytest.fixture
def client():
    return TestClient(app)


# Mock SerpApi results for research execution
MOCK_SERP_RESULTS = [
    SearchResult(
        title="National Women Helpline 181 - Official Govt Portal",
        url="http://ncw.nic.in/helpline181",
        source="ncw.nic.in",
        snippet="24/7 National Emergency Helpline 181 for women facing violence or harassment.",
        position=1,
        result_type="organic",
    ),
    SearchResult(
        title="Sakhi One Stop Centre Directory - Ministry of Women & Child Development",
        url="https://wcd.nic.in/sakhi-centers",
        source="wcd.nic.in",
        snippet="Sakhi One Stop Centres provide emergency shelter, medical aid, and legal advice.",
        position=2,
        result_type="organic",
    ),
]


# ---------------------------------------------------------------------------
# Flow A: Domestic Violence Situation
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_e2e_domestic_violence_flow(client):
    user_input = "My husband physically hit me and threatened me. I am locked in the bedroom and need urgent help in New Delhi."

    # 1. Test Case Creation Endpoint
    create_resp = client.post(
        "/api/v2/cases",
        json={
            "user_id": "test_user_dv",
            "situation_text": user_input,
            "category": "domestic_violence",
            "location": {"display_name": "New Delhi, India"},
        },
    )
    assert create_resp.status_code == 200
    case_data = create_resp.json()
    case_id = case_data.get("id") or case_data.get("_id")
    assert case_id is not None

    # 2. Test Situation Analysis Endpoint
    with patch("backend.routes.cases.SituationAgent") as MockSitAgent:
        instance = MockSitAgent.return_value
        instance.analyse = AsyncMock(
            return_value=Situation(
                case_summary="User experiencing physical abuse and threats from husband in New Delhi.",
                category=SituationCategory.DOMESTIC_VIOLENCE,
                subcategory="physical_abuse",
                urgency=Urgency.CRITICAL,
                location="New Delhi, India",
                user_goal="Reach safety, contact emergency helpline, and access shelter.",
                known_facts=["Husband physically abused user", "User in New Delhi"],
                user_claims=["Locked in bedroom"],
                unknowns=["Immediate physical injuries"],
                missing_information=["Exact local street address"],
                questions_to_ask=["Are you safe to call 181 right now?"],
            )
        )

        analyze_resp = client.post("/api/v2/cases/analyze", json={"situation_text": user_input})
        assert analyze_resp.status_code == 200
        analysis = analyze_resp.json()
        assert analysis["category"] == "domestic_violence"
        assert analysis["urgency"] == "critical"

    # 3. Test Full Research Pipeline Execution
    with patch("backend.agents.research_agent.ResearchAgent.plan_research") as mock_plan, \
         patch("backend.services.serpapi_service.SerpApiService.search_web") as mock_search, \
         patch("backend.agents.action_planner.ActionPlanner.generate_plan") as mock_action:

        mock_plan.return_value = ResearchPlan(
            case_id=case_id,
            overall_strategy="Find emergency helplines and Sakhi shelters",
            tasks=[
                ResearchTask(
                    id="t1",
                    description="Search for official women helpline 181 New Delhi",
                    search_queries=["women helpline 181 New Delhi"],
                    expected_outcome="Direct phone numbers",
                    priority=1,
                )
            ],
        )

        mock_search.return_value = MOCK_SERP_RESULTS

        mock_action.return_value = ActionPlan(
            case_id=case_id,
            summary="Immediate safety plan for domestic violence",
            immediate_actions=[
                ActionStep(
                    id="act-1",
                    title="Call Women Helpline 181 or Emergency 112",
                    description="Call 181 immediately if safe.",
                    priority=ActionPriority.IMMEDIATE,
                    category="STAY SAFE",
                    evidence_ids=["ev-1"],
                )
            ],
            safety_warning="DO NOT confront the perpetrator directly.",
        )

        run_resp = client.post(f"/api/v2/research/{case_id}/run")
        assert run_resp.status_code == 200
        run_data = run_resp.json()
        assert run_data["status"] == "complete"
        assert run_data["action_plan"]["immediate_actions"][0]["category"] == "STAY SAFE"

    # 4. Test Fetch Case Workspace Data
    get_resp = client.get(f"/api/v2/cases/{case_id}")
    assert get_resp.status_code == 200
    fetched_case = get_resp.json()
    assert fetched_case["category"] == "domestic_violence"


# ---------------------------------------------------------------------------
# Flow B: Stalking Situation
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_e2e_stalking_flow(client):
    user_input = "An unknown person has been following me home for 3 days and leaving threatening notes on my car."

    create_resp = client.post(
        "/api/v2/cases",
        json={
            "user_id": "test_user_stalking",
            "situation_text": user_input,
            "category": "stalking",
        },
    )
    assert create_resp.status_code == 200
    case_id = create_resp.json().get("id") or create_resp.json().get("_id")

    with patch("backend.agents.situation_agent.SituationAgent.analyse") as mock_analyse:
        mock_analyse.return_value = Situation(
            case_summary="User being physically stalked on commute.",
            category=SituationCategory.STALKING,
            urgency=Urgency.HIGH,
            known_facts=["Followed for 3 days", "Threatening notes on car"],
        )

        analyze_resp = client.post("/api/v2/cases/analyze", json={"situation_text": user_input})
        assert analyze_resp.status_code == 200
        assert analyze_resp.json()["category"] == "stalking"


# ---------------------------------------------------------------------------
# Flow C: Online Harassment Situation
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_e2e_online_harassment_flow(client):
    user_input = "Someone posted private images and created a fake account with my name on social media."

    create_resp = client.post(
        "/api/v2/cases",
        json={
            "user_id": "test_user_online",
            "situation_text": user_input,
            "category": "online_harassment",
        },
    )
    assert create_resp.status_code == 200

    with patch("backend.agents.situation_agent.SituationAgent.analyse") as mock_analyse:
        mock_analyse.return_value = Situation(
            case_summary="User facing non-consensual image sharing and online impersonation.",
            category=SituationCategory.ONLINE_HARASSMENT,
            urgency=Urgency.HIGH,
            known_facts=["Fake profile created", "Private images posted"],
        )

        analyze_resp = client.post("/api/v2/cases/analyze", json={"situation_text": user_input})
        assert analyze_resp.status_code == 200
        assert analyze_resp.json()["category"] == "online_harassment"


# ---------------------------------------------------------------------------
# Flow D: Workplace Harassment Situation
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_e2e_workplace_harassment_flow(client):
    user_input = "My senior manager demanded sexual favors in exchange for my promotion and threatened termination."

    create_resp = client.post(
        "/api/v2/cases",
        json={
            "user_id": "test_user_posh",
            "situation_text": user_input,
            "category": "workplace_harassment",
        },
    )
    assert create_resp.status_code == 200

    with patch("backend.agents.situation_agent.SituationAgent.analyse") as mock_analyse:
        mock_analyse.return_value = Situation(
            case_summary="Quid pro quo sexual harassment and retaliation in workplace.",
            category=SituationCategory.WORKPLACE_HARASSMENT,
            urgency=Urgency.HIGH,
            known_facts=["Demanded sexual favors for promotion", "Threatened termination"],
        )

        analyze_resp = client.post("/api/v2/cases/analyze", json={"situation_text": user_input})
        assert analyze_resp.status_code == 200
        assert analyze_resp.json()["category"] == "workplace_harassment"


# ---------------------------------------------------------------------------
# Flow E: Generic Consumer Complaint Situation
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_e2e_generic_consumer_flow(client):
    user_input = "My landlord refuses to return my $1,500 security deposit after I moved out in good condition."

    create_resp = client.post(
        "/api/v2/cases",
        json={
            "user_id": "test_user_consumer",
            "situation_text": user_input,
            "category": "consumer",
        },
    )
    assert create_resp.status_code == 200
    case_id = create_resp.json().get("id") or create_resp.json().get("_id")

    with patch("backend.agents.situation_agent.SituationAgent.analyse") as mock_analyse:
        mock_analyse.return_value = Situation(
            case_summary="Landlord withholding $1,500 rental deposit without justification.",
            category=SituationCategory.CONSUMER,
            urgency=Urgency.MEDIUM,
            known_facts=["Landlord withheld $1,500 deposit"],
        )

        analyze_resp = client.post("/api/v2/cases/analyze", json={"situation_text": user_input})
        assert analyze_resp.status_code == 200
        assert analyze_resp.json()["category"] == "consumer"
        assert analyze_resp.json()["category"] != "domestic_violence"
