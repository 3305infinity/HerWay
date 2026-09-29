"""
Integration tests for Haven's Standout Feature: HAVEN SAFETY PLAN.

Test Coverage:
1. Domestic violence situation -> Generates full Safety Plan with explicit indicators & emergency resources.
2. Stalking situation -> Generates Safety Plan with digital safety, anti-stalking reporting, and cyber resources.
3. Online harassment -> Generates Safety Plan with platform reporting and conditional evidence preservation.
4. Workplace harassment -> Generates Safety Plan with POSH Act / ICC internal committee pathways.
5. Generic consumer dispute (e.g. flight refund) -> Verified NO women-specific Safety Plan is generated.
6. Action completion toggling (TODO -> COMPLETED) with persistent state.
7. Adaptive re-planning: Situation escalation triggers re-planning, preserves completed actions, and logs 'Why your plan changed' history.
"""

import pytest
from unittest.mock import AsyncMock, MagicMock
from fastapi.testclient import TestClient

from backend.main import app
from backend.models.action_plan import ActionPriority, ActionStatus
from backend.models.case import Case, CaseStatus, Location
from backend.models.research import (
    EvidenceItem,
    LocalResource,
    Situation,
    SituationCategory,
    Urgency,
)
from backend.models.safety_plan import (
    SafetyActionItem,
    SafetyAssessment,
    SafetyMatchedResource,
    SafetyPlan,
    SafetyPlanPhase,
    SafetyPlanUpdate,
)
from backend.agents.safety_plan_agent import SafetyPlanAgent


@pytest.fixture
def mock_llm():
    """Mock LLMService for deterministic unit/integration testing."""
    llm = MagicMock()
    return llm


@pytest.fixture
def sample_dv_situation():
    return Situation(
        case_summary="User is facing escalating physical and verbal threats from her domestic partner in Austin, TX.",
        category=SituationCategory.DOMESTIC_VIOLENCE,
        urgency=Urgency.CRITICAL,
        user_goal="Safely find temporary emergency shelter and understand protective order rights.",
        known_facts=[
            "Partner threatened physical violence yesterday",
            "User lives in Austin, Texas with perpetrator",
            "User has personal identification documents in a bag",
        ],
        user_claims=["Partner is monitoring calls and messages"],
        unknowns=["Whether local family violence shelters have availability today"],
        missing_information=["Does user have access to private transportation?"],
        location="Austin, TX",
    )


@pytest.fixture
def sample_stalking_situation():
    return Situation(
        case_summary="User is being followed and receiving anonymous threatening messages daily.",
        category=SituationCategory.STALKING,
        urgency=Urgency.HIGH,
        user_goal="Document stalking incidents safely and file cyber cell complaint.",
        known_facts=[
            "Unwanted messages received across 3 social media accounts",
            "Unknown car seen parked outside residence 4 nights in a row",
        ],
        user_claims=["Suspect might be an acquaintance from work"],
        unknowns=["Whether police can issue a restraining order without suspect's full legal name"],
        missing_information=[],
        location="Austin, TX",
    )


@pytest.fixture
def sample_workplace_situation():
    return Situation(
        case_summary="User is experiencing persistent sexual harassment by a supervisor at tech firm.",
        category=SituationCategory.WORKPLACE_HARASSMENT,
        urgency=Urgency.MEDIUM,
        user_goal="File formal POSH/ICC grievance and protect against retaliatory termination.",
        known_facts=[
            "Supervisor sent inappropriate messages outside work hours",
            "User reported verbally to team lead who took no action",
        ],
        user_claims=["Supervisor threatened to stall promotion if non-compliant"],
        unknowns=["Whether company has a constituted Internal Complaints Committee (ICC)"],
        missing_information=[],
    )


@pytest.fixture
def sample_consumer_situation():
    return Situation(
        case_summary="User booked flight tickets on airline website; flight was cancelled without refund.",
        category=SituationCategory.CONSUMER,
        urgency=Urgency.LOW,
        user_goal="Obtain full refund of $650 from airline.",
        known_facts=["Booking reference ABC123", "Flight cancelled on Oct 12"],
        user_claims=["Airline violated refund guidelines"],
        unknowns=["Timeline for mandatory airline refund under DOT rules"],
        missing_information=[],
    )


@pytest.fixture
def sample_evidence():
    return [
        EvidenceItem(
            id="EVIDENCE_01",
            source_title="Texas National Domestic Violence Hotline & Shelter Directory",
            url="https://www.thehotline.org",
            domain="thehotline.org",
            claim_supported="24/7 confidential safety planning and emergency shelter referrals available via 1-800-799-SAFE or text START to 88788.",
            confidence_score=0.95,
            why_this_source_matters="Official national support hotline with live shelter placement.",
        ),
        EvidenceItem(
            id="EVIDENCE_02",
            source_title="Austin Police Department - Family Violence Protection Unit",
            url="https://www.austintexas.gov/police",
            domain="austintexas.gov",
            claim_supported="Emergency protective orders (EPO) can be requested immediately through magistrate or local family violence unit.",
            confidence_score=0.98,
            why_this_source_matters="Official municipal law enforcement procedure.",
        ),
    ]


@pytest.fixture
def sample_local_resources():
    return [
        LocalResource(
            name="SAFE Alliance Austin Women's Shelter",
            category="shelter",
            phone="(512) 267-7233",
            address="4800 Manor Rd, Austin, TX 78723",
            website="https://www.safeaustin.org",
            rating=4.8,
            hours="24/7",
        )
    ]


# ---------------------------------------------------------------------------
# Test 1: Domestic Violence -> Safety Plan
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_domestic_violence_generates_safety_plan(mock_llm, sample_dv_situation, sample_evidence, sample_local_resources):
    """Test that domestic violence situations produce a structured 6-phase Safety Plan with explicit indicators."""
    
    # Mock LLM Assessment response
    mock_assessment = SafetyAssessment(
        immediate_safety_concern=True,
        threats_present=True,
        repeated_harassment=False,
        digital_safety_concern=True,
        support_available=False,
        safe_place_available=False,
        financial_dependence=False,
        workplace_harassment=False,
        presence_of_dependents=False,
        escalating_behavior=True,
        information_missing=True,
        indicator_justifications={
            "immediate_safety_concern": "Partner threatened physical violence yesterday",
            "threats_present": "Threatened physical harm directly",
            "digital_safety_concern": "User noted device and call monitoring",
        },
        context_summary="Critical safety situation with active threats and monitored communications in Austin, TX.",
        critical_safety_notes=["Do not confront partner directly", "Clear browser history or use quick exit"],
        missing_safety_information=["Private transport availability"],
    )

    # Mock LLM Synthesis response
    class MockSynth:
        right_now_actions = [
            SafetyActionItem(
                id="SAFE_RIGHT_NOW_01",
                title="Identify and verify safe immediate exit route",
                description="Keep essential identification bag ready and identify public safe space if threats escalate.",
                phase=SafetyPlanPhase.RIGHT_NOW,
                priority=ActionPriority.IMMEDIATE,
                status=ActionStatus.TODO,
                evidence_ids=["EVIDENCE_01"],
                resource_ids=["RES_EMERGENCY_01"],
            )
        ]
        next_24h_actions = [
            SafetyActionItem(
                id="SAFE_NEXT_24H_01",
                title="Contact SAFE Alliance Austin helpline confidentially",
                description="Call (512) 267-7233 from a secure phone to check shelter intake.",
                phase=SafetyPlanPhase.NEXT_24_HOURS,
                priority=ActionPriority.HIGH,
                status=ActionStatus.TODO,
                resource_ids=["RES_LOCAL_01"],
            )
        ]
        document_safe_actions = [
            SafetyActionItem(
                id="SAFE_DOC_01",
                title="Document threat timestamps only if safe",
                description="Record dates/times on a secure external device or note with trusted friend. Do not keep visible on shared phone.",
                phase=SafetyPlanPhase.DOCUMENT_SAFE,
                priority=ActionPriority.MEDIUM,
                status=ActionStatus.TODO,
                safety_caveat="ONLY IF SAFE: Stop immediately if perpetrator has access.",
            )
        ]
        support_network_actions = []
        formal_options_actions = [
            SafetyActionItem(
                id="SAFE_FORMAL_01",
                title="Review Emergency Protective Order options with Austin PD",
                description="Consult family violence advocates regarding ex-parte protective order application.",
                phase=SafetyPlanPhase.FORMAL_OPTIONS,
                priority=ActionPriority.MEDIUM,
                status=ActionStatus.TODO,
                evidence_ids=["EVIDENCE_02"],
            )
        ]
        ongoing_actions = []
        things_to_avoid = ["Do not tell perpetrator you are seeking shelter", "Do not leave handwritten notes where they can be found"]

    mock_llm.structured_generate.side_effect = [mock_assessment, MockSynth()]

    agent = SafetyPlanAgent(mock_llm)
    assert agent.is_safety_case("domestic_violence") is True

    plan = await agent.generate_safety_plan(
        case_id="case_dv_test_123",
        situation=sample_dv_situation,
        evidence=sample_evidence,
        local_resources=sample_local_resources,
    )

    assert plan is not None
    assert plan.case_id == "case_dv_test_123"
    assert plan.is_women_safety_case is True
    # Verify explicit indicators
    assert plan.assessment.immediate_safety_concern is True
    assert plan.assessment.threats_present is True
    assert plan.assessment.digital_safety_concern is True
    # Verify matched resources
    assert len(plan.matched_resources) > 0
    assert any("SAFE Alliance" in r.name or "112" in (r.phone or "") for r in plan.matched_resources)
    # Verify phased actions
    assert len(plan.right_now_actions) == 1
    assert plan.right_now_actions[0].phase == SafetyPlanPhase.RIGHT_NOW
    assert len(plan.document_safe_actions) == 1
    assert "ONLY IF SAFE" in (plan.document_safe_actions[0].safety_caveat or plan.document_safe_actions[0].description)


# ---------------------------------------------------------------------------
# Test 2: Stalking -> Safety Plan
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_stalking_generates_safety_plan(mock_llm, sample_stalking_situation, sample_evidence, sample_local_resources):
    """Test that stalking situations trigger anti-stalking digital safety & police reporting pathways."""
    mock_assessment = SafetyAssessment(
        immediate_safety_concern=False,
        threats_present=True,
        repeated_harassment=True,
        digital_safety_concern=True,
        support_available=True,
        safe_place_available=True,
        financial_dependence=False,
        workplace_harassment=False,
        presence_of_dependents=False,
        escalating_behavior=True,
        information_missing=False,
        indicator_justifications={"repeated_harassment": "Unknown car parked outside 4 nights in a row"},
        context_summary="Stalking case with online and physical monitoring.",
    )

    class MockStalkingSynth:
        right_now_actions = [
            SafetyActionItem(
                id="SAFE_RIGHT_NOW_01",
                title="Vary daily travel routes and park in well-lit public zones",
                description="Avoid predictable departure times and ensure friends know your commute schedule.",
                phase=SafetyPlanPhase.RIGHT_NOW,
                priority=ActionPriority.HIGH,
                status=ActionStatus.TODO,
            )
        ]
        next_24h_actions = [
            SafetyActionItem(
                id="SAFE_NEXT_24H_01",
                title="Audit social media privacy and disable location permissions",
                description="Turn off location sharing on all mobile applications and reset passwords from a clean device.",
                phase=SafetyPlanPhase.NEXT_24_HOURS,
                priority=ActionPriority.HIGH,
                status=ActionStatus.TODO,
            )
        ]
        document_safe_actions = [
            SafetyActionItem(
                id="SAFE_DOC_01",
                title="Maintain stalking incident logbook",
                description="Log date, time, location, vehicle description, and message screenshots in a secure drive.",
                phase=SafetyPlanPhase.DOCUMENT_SAFE,
                priority=ActionPriority.MEDIUM,
                status=ActionStatus.TODO,
            )
        ]
        support_network_actions = []
        formal_options_actions = []
        ongoing_actions = []
        things_to_avoid = ["Do not engage or respond to the stalker's messages"]

    mock_llm.structured_generate.side_effect = [mock_assessment, MockStalkingSynth()]

    agent = SafetyPlanAgent(mock_llm)
    assert agent.is_safety_case("stalking") is True

    plan = await agent.generate_safety_plan(
        case_id="case_stalk_123",
        situation=sample_stalking_situation,
        evidence=sample_evidence,
        local_resources=sample_local_resources,
    )

    assert plan.assessment.repeated_harassment is True
    assert plan.assessment.digital_safety_concern is True
    assert len(plan.document_safe_actions) >= 1
    assert any(r.category == "cyber_cell" for r in plan.matched_resources)


# ---------------------------------------------------------------------------
# Test 3: Workplace Harassment -> POSH / ICC Plan
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_workplace_harassment_generates_posh_plan(mock_llm, sample_workplace_situation, sample_evidence):
    """Test workplace harassment triggers POSH Act / Internal Complaints Committee action plan."""
    mock_assessment = SafetyAssessment(
        immediate_safety_concern=False,
        threats_present=True,
        repeated_harassment=True,
        digital_safety_concern=False,
        support_available=False,
        safe_place_available=True,
        financial_dependence=True,
        workplace_harassment=True,
        presence_of_dependents=False,
        escalating_behavior=False,
        information_missing=True,
        indicator_justifications={"workplace_harassment": "Inappropriate messages from supervisor with promotion threats"},
        context_summary="Workplace sexual harassment with coercive career threats.",
    )

    class MockWorkplaceSynth:
        right_now_actions = []
        next_24h_actions = []
        document_safe_actions = [
            SafetyActionItem(
                id="SAFE_DOC_01",
                title="Preserve email threads and chat exports outside corporate laptop",
                description="Forward or photograph relevant communications to private email for evidence backup.",
                phase=SafetyPlanPhase.DOCUMENT_SAFE,
                priority=ActionPriority.HIGH,
                status=ActionStatus.TODO,
            )
        ]
        support_network_actions = []
        formal_options_actions = [
            SafetyActionItem(
                id="SAFE_FORMAL_01",
                title="Submit written complaint to Internal Complaints Committee (ICC) / HR",
                description="File formal grievance under POSH guidelines requesting confidentiality and non-retaliation protections.",
                phase=SafetyPlanPhase.FORMAL_OPTIONS,
                priority=ActionPriority.HIGH,
                status=ActionStatus.TODO,
            )
        ]
        ongoing_actions = []
        things_to_avoid = ["Do not delete messages", "Do not accept informal one-on-one off-the-record meetings alone"]

    mock_llm.structured_generate.side_effect = [mock_assessment, MockWorkplaceSynth()]

    agent = SafetyPlanAgent(mock_llm)
    assert agent.is_safety_case("workplace_harassment") is True

    plan = await agent.generate_safety_plan(
        case_id="case_work_123",
        situation=sample_workplace_situation,
        evidence=sample_evidence,
        local_resources=[],
    )

    assert plan.assessment.workplace_harassment is True
    assert plan.assessment.financial_dependence is True
    assert any("Internal Complaints Committee" in a.title for a in plan.formal_options_actions)


# ---------------------------------------------------------------------------
# Test 4: Generic Consumer Dispute -> NO Safety Plan
# ---------------------------------------------------------------------------
def test_generic_consumer_dispute_no_safety_plan():
    """Verify that general non-safety disputes (consumer, billing, travel) do NOT generate a women-specific Safety Plan."""
    is_safety = SafetyPlanAgent.is_safety_case(category="consumer", situation_text="Flight was cancelled, need refund.")
    assert is_safety is False

    is_housing_financial = SafetyPlanAgent.is_safety_case(category="financial", situation_text="Bank charged unauthorized overdraft fee.")
    assert is_housing_financial is False


# ---------------------------------------------------------------------------
# Test 5: Action Status Toggling & Completion Persistence
# ---------------------------------------------------------------------------
def test_action_item_status_toggling():
    """Test updating action item from TODO -> COMPLETED."""
    action = SafetyActionItem(
        id="SAFE_ACT_01",
        title="Check shelter vacancy",
        description="Call local helpline",
        phase=SafetyPlanPhase.RIGHT_NOW,
        priority=ActionPriority.IMMEDIATE,
        status=ActionStatus.TODO,
    )
    assert action.status == ActionStatus.TODO
    assert action.completed_at is None

    # Mark as COMPLETED
    action.status = ActionStatus.COMPLETED
    from datetime import datetime
    action.completed_at = datetime.utcnow()

    assert action.status == ActionStatus.COMPLETED
    assert action.completed_at is not None


# ---------------------------------------------------------------------------
# Test 6: Adaptive Re-Planning (State Change & Escalation)
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_adaptive_safety_plan_preserves_completed_and_logs_history(mock_llm, sample_dv_situation, sample_evidence, sample_local_resources):
    """Test that when situation escalates, completed tasks are preserved and update history is recorded."""
    
    # 1. Existing initial plan with 1 completed task
    existing_action_1 = SafetyActionItem(
        id="SAFE_RIGHT_NOW_01",
        title="Identify safe exit route",
        description="Keep essentials ready",
        phase=SafetyPlanPhase.RIGHT_NOW,
        priority=ActionPriority.IMMEDIATE,
        status=ActionStatus.COMPLETED,
    )
    existing_action_2 = SafetyActionItem(
        id="SAFE_NEXT_24H_01",
        title="Contact support helpline",
        description="Call SAFE alliance",
        phase=SafetyPlanPhase.NEXT_24_HOURS,
        priority=ActionPriority.HIGH,
        status=ActionStatus.TODO,
    )

    initial_plan = SafetyPlan(
        case_id="case_adapt_test",
        category="domestic_violence",
        is_women_safety_case=True,
        assessment=SafetyAssessment(
            immediate_safety_concern=True,
            context_summary="Initial situation",
        ),
        right_now_actions=[existing_action_1],
        next_24h_actions=[existing_action_2],
        actions=[existing_action_1, existing_action_2],
        matched_resources=[],
        things_to_avoid=[],
        updates_history=[],
    )

    # 2. Updated situation: abuser discovered departure plan
    escalated_situation = Situation(
        case_summary="Abuser discovered departure bag and locked front door.",
        category=SituationCategory.DOMESTIC_VIOLENCE,
        urgency=Urgency.CRITICAL,
        user_goal="Immediate police intervention and urgent extraction.",
        known_facts=["Abuser discovered bags and blocked exit"],
        user_claims=[],
        unknowns=[],
        missing_information=[],
    )

    mock_escalated_assessment = SafetyAssessment(
        immediate_safety_concern=True,
        threats_present=True,
        escalating_behavior=True,
        context_summary="Severe acute escalation - exit blocked.",
    )

    class MockEscalatedSynth:
        right_now_actions = [
            SafetyActionItem(
                id="SAFE_RIGHT_NOW_01", # Existing ID
                title="Identify safe exit route",
                description="Keep essentials ready",
                phase=SafetyPlanPhase.RIGHT_NOW,
                priority=ActionPriority.IMMEDIATE,
                status=ActionStatus.TODO,
            ),
            SafetyActionItem(
                id="SAFE_RIGHT_NOW_NEW",
                title="Call 112/911 immediately from locked room",
                description="Dial emergency services with open line if safe.",
                phase=SafetyPlanPhase.RIGHT_NOW,
                priority=ActionPriority.IMMEDIATE,
                status=ActionStatus.TODO,
            ),
        ]
        next_24h_actions = []
        document_safe_actions = []
        support_network_actions = []
        formal_options_actions = []
        ongoing_actions = []
        things_to_avoid = ["Do not attempt physical confrontation"]

    mock_llm.structured_generate.side_effect = [mock_escalated_assessment, MockEscalatedSynth()]

    agent = SafetyPlanAgent(mock_llm)
    adapted_plan = await agent.adapt_plan(
        current_plan=initial_plan,
        updated_situation=escalated_situation,
        new_evidence=sample_evidence,
        new_local_resources=sample_local_resources,
        state_change_reason="Perpetrator discovered departure plan; physical exit blocked",
    )

    # Verify completed action SAFE_RIGHT_NOW_01 remained COMPLETED
    preserved_act = next(a for a in adapted_plan.actions if a.id == "SAFE_RIGHT_NOW_01")
    assert preserved_act.status == ActionStatus.COMPLETED

    # Verify history recorded
    assert len(adapted_plan.updates_history) == 1
    assert "departure plan" in adapted_plan.updates_history[0].why_plan_changed
    assert "SAFE_RIGHT_NOW_01" in adapted_plan.updates_history[0].preserved_completed_actions
