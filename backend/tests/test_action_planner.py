"""
Unit tests for Action Planning Agent (Task 5).

Tests:
1. Generation of evidence-linked ActionPlan.
2. Separation into timing phases (DO NOW, NEXT, IF THAT DOES NOT WORK).
3. Document collection checklists and things to avoid.
"""

import pytest
from unittest.mock import AsyncMock

from backend.agents.action_planner import ActionPlanner
from backend.models.action_plan import (
    ActionItem,
    ActionPlan,
    ActionPriority,
    ActionStatus,
    ActionTimingPhase,
    ActionType,
)
from backend.models.research import (
    EvidenceConfidence,
    EvidenceItem,
    EvidenceStatus,
    FinalResearchReport,
    Situation,
    SituationCategory,
    SourceType,
    Urgency,
)


@pytest.fixture
def sample_report():
    situation = Situation(
        case_summary="User bought a laptop online that arrived damaged. Seller refuses replacement/refund.",
        category=SituationCategory.CONSUMER,
        urgency=Urgency.HIGH,
        user_goal="Obtain full refund or replacement",
        known_facts=["Purchased laptop for $1,200", "Arrived with cracked screen"],
    )

    evidence = [
        EvidenceItem(
            id="EVIDENCE_01",
            source_title="National Consumer Helpline Guidelines",
            url="https://consumerhelpline.gov.in/rules",
            domain="consumerhelpline.gov.in",
            source_type=SourceType.OFFICIAL_GOVERNMENT,
            relevance=0.95,
            freshness=0.9,
            authority=0.95,
            supports_claim=True,
            claim_supported="Consumers can lodge complaints for damaged products delivered by e-commerce platforms within 7-14 days.",
            extracted_facts=["14-day online complaint window for e-commerce damaged goods"],
            confidence=EvidenceConfidence.HIGH,
            confidence_score=0.92,
            status=EvidenceStatus.VERIFIED_STRONGLY_SUPPORTED,
            why_this_source_matters="Official government helpline portal.",
        ),
        EvidenceItem(
            id="EVIDENCE_02",
            source_title="E-Daakhil Online Filing Portal",
            url="https://edaakhil.nic.in",
            domain="edaakhil.nic.in",
            source_type=SourceType.OFFICIAL_GOVERNMENT,
            relevance=0.90,
            freshness=0.95,
            authority=0.95,
            supports_claim=True,
            claim_supported="Formal consumer disputes can be filed electronically through E-Daakhil without hiring a lawyer.",
            extracted_facts=["File formal consumer court cases online via E-Daakhil"],
            confidence=EvidenceConfidence.HIGH,
            confidence_score=0.94,
            status=EvidenceStatus.VERIFIED_STRONGLY_SUPPORTED,
            why_this_source_matters="Official consumer court e-filing system.",
        ),
    ]

    return FinalResearchReport(
        case_id="case_12345",
        situation=situation,
        evidence=evidence,
        searches_executed=2,
        sources_verified=2,
    )


@pytest.mark.asyncio
async def test_action_planner_pipeline(sample_report):
    mock_llm = AsyncMock()

    expected_plan = ActionPlan(
        case_id="case_12345",
        summary="File a formal written complaint with the seller citing National Consumer Helpline rules, then escalate to E-Daakhil if unresolved.",
        immediate_actions=[
            ActionItem(
                id="ACTION_NOW_01",
                title="Gather invoice, order ID, and clear unboxing photos",
                description="Collect your original invoice, order receipt, photos of the cracked screen, and chat logs before sending a final written notice.",
                action_type=ActionType.DOCUMENT,
                priority=ActionPriority.IMMEDIATE,
                timing_phase=ActionTimingPhase.DO_NOW,
                evidence_ids=["EVIDENCE_01"],
                status=ActionStatus.TODO,
            ),
        ],
        next_actions=[
            ActionItem(
                id="ACTION_NEXT_01",
                title="Lodge a complaint on National Consumer Helpline (NCH)",
                description="Submit an online grievance or call 1915 with your order ID and seller details.",
                action_type=ActionType.COMPLAINT,
                priority=ActionPriority.SHORT_TERM,
                timing_phase=ActionTimingPhase.NEXT,
                evidence_ids=["EVIDENCE_01"],
                supporting_url="https://consumerhelpline.gov.in/rules",
                status=ActionStatus.TODO,
            ),
        ],
        escalation_options=[
            ActionItem(
                id="ACTION_ESC_01",
                title="File a formal case on E-Daakhil consumer court portal",
                description="If NCH mediation fails within 15 days, file a formal dispute on E-Daakhil.",
                action_type=ActionType.LEGAL,
                priority=ActionPriority.MEDIUM_TERM,
                timing_phase=ActionTimingPhase.IF_THAT_DOES_NOT_WORK,
                evidence_ids=["EVIDENCE_02"],
                supporting_url="https://edaakhil.nic.in",
                status=ActionStatus.TODO,
            ),
        ],
        documents_or_evidence_to_collect=[
            "Original e-commerce invoice",
            "Photos of damaged package and cracked laptop screen",
            "Customer support chat transcripts and email threads",
        ],
        things_to_avoid=[
            "Do not throw away the original shipping box",
            "Do not attempt self-repair as it voids warranty",
        ],
    )

    mock_llm.structured_generate.return_value = expected_plan

    planner = ActionPlanner(mock_llm)
    result = await planner.plan(sample_report)

    assert result.case_id == "case_12345"
    assert len(result.immediate_actions) == 1
    assert result.immediate_actions[0].evidence_ids == ["EVIDENCE_01"]

    assert len(result.next_actions) == 1
    assert result.next_actions[0].supporting_url == "https://consumerhelpline.gov.in/rules"

    assert len(result.escalation_options) == 1
    assert result.escalation_options[0].evidence_ids == ["EVIDENCE_02"]

    assert len(result.documents_or_evidence_to_collect) == 3
    assert len(result.things_to_avoid) == 2
