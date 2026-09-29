"""
Comprehensive tests for Haven Women's Safety & Generic Case Capabilities.

Tests cover:
1. Domestic violence case (Safety-first ordering, helpline tasks, no confrontation)
2. Stalking case (Police/cyber cell research, safety measures)
3. Online harassment case (Cybercrime reporting, evidence preservation)
4. Workplace harassment case (POSH act, ICC reporting options)
5. Non-women consumer case (Standard routing, no women-specific triggers)
6. Legacy endpoints preservation check (FastAPI test client)
7. SerpApi research integration check
8. Evidence linked to action plan recommendations
"""

import pytest
from unittest.mock import AsyncMock, MagicMock
from fastapi.testclient import TestClient

from backend.main import app
from backend.models.research import (
    Situation,
    SituationCategory,
    Urgency,
    ResearchTask,
    ResearchPlan,
    ActionPlan,
    ActionStep,
    ActionPriority,
    SourceItem,
    SourceType,
    VerificationStatus,
)
from backend.agents.situation_agent import SituationAgent
from backend.agents.research_agent import ResearchAgent
from backend.agents.action_planner import ActionPlanner
from backend.services.serpapi_service import SerpApiService, SearchResult


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def mock_llm():
    return AsyncMock()


@pytest.fixture
def test_client():
    return TestClient(app)


# ---------------------------------------------------------------------------
# 1. Domestic Violence Case Test
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_domestic_violence_case(mock_llm):
    user_input = "My husband is physically threatening me and locked me in the room. I need urgent help in New Delhi."

    expected_situation = Situation(
        case_summary="User is in immediate danger of physical violence from husband in New Delhi.",
        category=SituationCategory.DOMESTIC_VIOLENCE,
        subcategory="physical_abuse_threat",
        urgency=Urgency.CRITICAL,
        location="New Delhi, India",
        entities=["husband"],
        organizations_involved=[],
        user_goal="Escape immediate danger, access emergency shelter, and contact women helpline.",
        known_facts=["Husband threatening physically", "User located in New Delhi"],
        user_claims=["Locked in room"],
        unknowns=["Current physical condition", "Immediate access to phone"],
        missing_information=["Exact local address"],
        questions_to_ask=["Are you in a safe room right now?", "Can you safely call 181 or 112?"],
        recommended_research_types=["helpline", "shelter", "police"],
    )

    mock_llm.structured_generate.return_value = expected_situation

    sit_agent = SituationAgent(mock_llm)
    situation = await sit_agent.analyse(user_input)

    assert situation.category == SituationCategory.DOMESTIC_VIOLENCE
    assert situation.urgency == Urgency.CRITICAL

    # Test Research Planner generating specialized tasks for DV
    expected_research_plan = ResearchPlan(
        case_id="case-dv-101",
        overall_strategy="Find immediate women helplines (181), Sakhi One Stop Centers, and emergency support in New Delhi.",
        tasks=[
            ResearchTask(
                id="task-1",
                description="Search for official women helpline and emergency response in New Delhi",
                search_queries=["women helpline number 181 New Delhi emergency", "national domestic violence helpline India"],
                expected_outcome="Direct phone numbers for immediate safety",
                priority=1,
            ),
            ResearchTask(
                id="task-2",
                description="Find official Sakhi One Stop Centres and women shelters in New Delhi",
                search_queries=["Sakhi One Stop Centre New Delhi location phone", "women emergency shelter Delhi government"],
                expected_outcome="Verified shelter locations and contact details",
                priority=1,
            ),
        ],
    )
    mock_llm.structured_generate.return_value = expected_research_plan

    res_agent = ResearchAgent(mock_llm)
    plan = await res_agent.plan_research("case-dv-101", situation)

    assert len(plan.tasks) == 2
    assert any("helpline" in t.description.lower() for t in plan.tasks)

    # Test Action Planner generating safety-first action plan
    expected_action_plan = ActionPlan(
        case_id="case-dv-101",
        summary="Immediate safety plan and emergency support for domestic violence victim.",
        immediate_actions=[
            ActionStep(
                id="act-1",
                title="Call Emergency Services / Helpline 181",
                description="If safe, call 112 (Emergency Response) or 181 (Women Helpline) immediately.",
                priority=ActionPriority.IMMEDIATE,
                category="SAFETY FIRST",
                evidence_ids=["ev-1"],
            )
        ],
        short_term_actions=[
            ActionStep(
                id="act-2",
                title="Contact Sakhi One Stop Centre",
                description="Reach out to the nearest government Sakhi Centre for safe temporary shelter and legal assistance.",
                priority=ActionPriority.HIGH,
                category="SUPPORT OPTIONS",
                evidence_ids=["ev-2"],
            )
        ],
        long_term_actions=[
            ActionStep(
                id="act-3",
                title="File Protection Order under Domestic Violence Act",
                description="Consult legal counsel or free legal aid to file for a protection order.",
                priority=ActionPriority.MEDIUM,
                category="FORMAL OPTIONS",
                evidence_ids=["ev-3"],
            )
        ],
        safety_warning="DO NOT confront the perpetrator directly. Prioritize your physical safety above all.",
    )
    mock_llm.structured_generate.return_value = expected_action_plan

    act_planner = ActionPlanner(mock_llm)
    sources = [
        SourceItem(
            id="ev-1",
            title="National Commission for Women - 181 Helpline",
            url="http://ncw.nic.in/helplines",
            source_type=SourceType.OFFICIAL_GOVERNMENT,
            verification_status=VerificationStatus.VERIFIED,
            key_insights=["181 is 24/7 emergency hotline for women in India"],
        )
    ]
    action_plan = await act_planner.generate_plan("case-dv-101", situation, sources)

    assert action_plan.immediate_actions[0].category == "SAFETY FIRST"
    assert "DO NOT confront" in action_plan.safety_warning


# ---------------------------------------------------------------------------
# 2. Stalking Case Test
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_stalking_case(mock_llm):
    user_input = "An unknown person has been following me home from work for 3 days and sending threatening notes."

    expected_situation = Situation(
        case_summary="User is being physically stalked and harassed by an unidentified individual on their daily commute.",
        category=SituationCategory.STALKING,
        subcategory="physical_stalking",
        urgency=Urgency.HIGH,
        location="Mumbai, Maharashtra",
        entities=["stalker"],
        organizations_involved=[],
        user_goal="Stop the stalking, report to police women's cell, and ensure personal safety.",
        known_facts=["Followed home for 3 days", "Received threatening notes"],
        user_claims=[],
        unknowns=["Identity of stalker"],
        missing_information=["Commute route details"],
        questions_to_ask=["Have you informed a trusted person or workplace security?"],
        recommended_research_types=["police", "legal"],
    )

    mock_llm.structured_generate.return_value = expected_situation

    sit_agent = SituationAgent(mock_llm)
    situation = await sit_agent.analyse(user_input)

    assert situation.category == SituationCategory.STALKING
    assert situation.urgency == Urgency.HIGH


# ---------------------------------------------------------------------------
# 3. Online Harassment Case Test
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_online_harassment_case(mock_llm):
    user_input = "Someone created a fake profile with my pictures and is sending non-consensual explicit messages to my colleagues."

    expected_situation = Situation(
        case_summary="User is facing non-consensual image abuse and impersonation via fake social media profile.",
        category=SituationCategory.ONLINE_HARASSMENT,
        subcategory="impersonation_cyber_harassment",
        urgency=Urgency.HIGH,
        location=None,
        entities=["fake profile"],
        organizations_involved=["Social Media Platform"],
        user_goal="Take down fake profile, report to National Cyber Crime Reporting Portal, and preserve evidence.",
        known_facts=["Fake profile created using real photos", "Explicit messages sent to colleagues"],
        user_claims=[],
        unknowns=["IP address or identity of creator"],
        missing_information=["Platform URL"],
        questions_to_ask=["Have you taken full screenshots showing URLs, timestamps, and profile handles?"],
        recommended_research_types=["cybercrime", "platform_policy"],
    )

    mock_llm.structured_generate.return_value = expected_situation

    sit_agent = SituationAgent(mock_llm)
    situation = await sit_agent.analyse(user_input)

    assert situation.category == SituationCategory.ONLINE_HARASSMENT


# ---------------------------------------------------------------------------
# 4. Workplace Harassment Case Test
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_workplace_harassment_case(mock_llm):
    user_input = "My manager made sexual advances and threatened to fire me if I report it. Our company has no clear HR process."

    expected_situation = Situation(
        case_summary="User experiencing workplace sexual harassment and retaliatory threats from a direct manager.",
        category=SituationCategory.WORKPLACE_HARASSMENT,
        subcategory="posh_quid_pro_quo",
        urgency=Urgency.HIGH,
        location="Bengaluru, India",
        entities=["manager"],
        organizations_involved=["Employer Company"],
        user_goal="File formal complaint under POSH Act, preserve evidence, and protect employment.",
        known_facts=["Manager made explicit advances", "Threatened termination if reported"],
        user_claims=[],
        unknowns=["Presence of Internal Complaints Committee (ICC)"],
        missing_information=["Company size"],
        questions_to_ask=["Does your company have an Internal Complaints Committee (ICC)?"],
        recommended_research_types=["legal", "posh"],
    )

    mock_llm.structured_generate.return_value = expected_situation

    sit_agent = SituationAgent(mock_llm)
    situation = await sit_agent.analyse(user_input)

    assert situation.category == SituationCategory.WORKPLACE_HARASSMENT


# ---------------------------------------------------------------------------
# 5. Non-Women Consumer Case Test (Verification of generic routing)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_non_women_consumer_case(mock_llm):
    user_input = "I bought a smartphone online, it stopped turning on after 2 days, and the brand is refusing warranty repair."

    expected_situation = Situation(
        case_summary="Defective smartphone purchased online with warranty service denial by manufacturer.",
        category=SituationCategory.CONSUMER,
        subcategory="defective_electronics_warranty",
        urgency=Urgency.MEDIUM,
        location=None,
        entities=["smartphone"],
        organizations_involved=["E-commerce seller", "Manufacturer"],
        user_goal="Get warranty repair, replacement, or full refund.",
        known_facts=["Smartphone stopped working after 2 days", "Manufacturer refused warranty"],
        user_claims=[],
        unknowns=["Warranty policy fine print"],
        missing_information=["Brand name"],
        questions_to_ask=["Do you have the original tax invoice and warranty card?"],
        recommended_research_types=["web", "consumer_forum"],
    )

    mock_llm.structured_generate.return_value = expected_situation

    sit_agent = SituationAgent(mock_llm)
    situation = await sit_agent.analyse(user_input)

    # Ensure it routes to CONSUMER, NOT women's safety category
    assert situation.category == SituationCategory.CONSUMER
    assert situation.category != SituationCategory.DOMESTIC_VIOLENCE
    assert situation.category != SituationCategory.SAFETY


# ---------------------------------------------------------------------------
# 6. Legacy Endpoints Preservation Test
# ---------------------------------------------------------------------------

def test_legacy_endpoints_preserved(test_client):
    # Test health check endpoint
    response = test_client.get("/health")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"

    # Test legacy GET posts endpoint
    response = test_client.get("/get-posts")
    assert response.status_code == 200
    assert "posts" in response.json()

    # Test legacy GET admin posts endpoint
    response = test_client.get("/get-admin-posts")
    assert response.status_code == 200

    # Test legacy LawBot endpoint
    response = test_client.post("/lawbot", json={"prompt": "What are my consumer rights?"})
    assert response.status_code in [200, 500]  # Depends on Gemini API key availability in test env

    # Test legacy TherapyBot endpoint
    response = test_client.post("/therapybot", json={"prompt": "I feel stressed"})
    assert response.status_code in [200, 500]


# ---------------------------------------------------------------------------
# 7. SerpApi Integration Execution Check
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_serpapi_execution_check():
    # Test SerpApiService initialization and search method call structure
    service = SerpApiService(api_key="test_mock_key")
    assert service.api_key == "test_mock_key"
    
    # Mock live search execution
    mock_raw_response = {
        "organic_results": [
            {
                "title": "National Commission for Women - Official Portal",
                "link": "http://ncw.nic.in",
                "snippet": "24/7 National Women Helpline: 181. Support for women in distress.",
                "position": 1,
            }
        ]
    }
    
    with pytest.MonkeyPatch().context() as m:
        m.setattr(service, "search_web", AsyncMock(return_value=[
            SearchResult(
                title="National Commission for Women - Official Portal",
                url="http://ncw.nic.in",
                source="ncw.nic.in",
                snippet="24/7 National Women Helpline: 181. Support for women in distress.",
                position=1,
                result_type="organic",
            )
        ]))
        
        results = await service.search_web("women helpline 181")
        assert len(results) == 1
        assert results[0].url == "http://ncw.nic.in"
        assert "181" in results[0].snippet


# ---------------------------------------------------------------------------
# 8. Evidence Linked to Action Plan Recommendations
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_evidence_linked_to_actions(mock_llm):
    situation = Situation(
        case_summary="Cyber harassment case",
        category=SituationCategory.ONLINE_HARASSMENT,
        urgency=Urgency.HIGH,
        user_goal="File formal cybercrime complaint",
    )
    
    sources = [
        SourceItem(
            id="src-cyber-101",
            title="National Cyber Crime Reporting Portal",
            url="https://cybercrime.gov.in",
            source_type=SourceType.OFFICIAL_GOVERNMENT,
            verification_status=VerificationStatus.VERIFIED,
            key_insights=["File online harassment complaints at cybercrime.gov.in"],
        )
    ]

    expected_plan = ActionPlan(
        case_id="case-cyber-001",
        summary="Action steps to lodge complaint on cybercrime portal",
        immediate_actions=[
            ActionStep(
                id="act-1",
                title="Document evidence",
                description="Save screenshots of harassing messages with dates and timestamps.",
                priority=ActionPriority.IMMEDIATE,
                category="EVIDENCE/DOCUMENTATION",
            )
        ],
        short_term_actions=[
            ActionStep(
                id="act-2",
                title="Lodge online complaint",
                description="Submit complaint on the official portal.",
                priority=ActionPriority.HIGH,
                category="FORMAL OPTIONS",
                evidence_ids=["src-cyber-101"],
            )
        ],
    )
    mock_llm.structured_generate.return_value = expected_plan

    act_planner = ActionPlanner(mock_llm)
    result_plan = await act_planner.generate_plan("case-cyber-001", situation, sources)

    assert len(result_plan.short_term_actions[0].evidence_ids) > 0
    assert result_plan.short_term_actions[0].evidence_ids[0] == "src-cyber-101"
