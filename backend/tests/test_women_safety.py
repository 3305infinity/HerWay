"""
Women's-safety behaviour tests.

These cover the judgement calls that matter most for this product:

1. Domestic violence  — safety-first ordering, no "confront them" advice.
2. Stalking           — police/cyber routing, evidence preservation caveats.
3. Online harassment  — Indian cyber reporting, not US portals.
4. Workplace (POSH)   — Internal Committee route, not generic advice.
5. A non-safety case  — must NOT trigger safety-specific machinery.
6. Legacy endpoints   — still mounted and responding.
7. Evidence linking   — actions reference the evidence that supports them.

This module previously imported ``ActionStep``, ``SourceItem`` and
``VerificationStatus`` from ``backend.models.research``. Those names have never
existed there, so the file failed at collection and none of it had run. It is
rewritten here against the actual model layer.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from unittest.mock import AsyncMock, MagicMock

from backend.agents.action_planner import ActionPlanner
from backend.agents.safety_plan_agent import SafetyPlanAgent
from backend.agents.situation_agent import SituationAgent
from backend.main import app
from backend.models.action_plan import (
    ActionItem,
    ActionPlan,
    ActionPriority,
    ActionStatus,
    ActionTimingPhase,
    ActionType,
)
from backend.models.research import (
    EvidenceItem,
    EvidenceStatus,
    FinalResearchReport,
    ResourceVerification,
    SearchVertical,
    Situation,
    SituationCategory,
    SourceType,
    Urgency,
)


@pytest.fixture
def mock_llm():
    llm = MagicMock()
    llm.structured_generate = AsyncMock()
    llm.is_configured = True
    return llm


@pytest.fixture
def client():
    return TestClient(app)


def _evidence(**kwargs) -> EvidenceItem:
    defaults = dict(
        id="EVIDENCE_01",
        source_title="Women Helpline Scheme — Ministry of Women and Child Development",
        url="https://wcd.gov.in/schemes/women-helpline-scheme",
        domain="wcd.gov.in",
        source_type=SourceType.OFFICIAL_GOVERNMENT,
        claim_supported="181 is the 24x7 national women helpline.",
        extracted_facts=["181 operates 24x7"],
        confidence_score=0.93,
        status=EvidenceStatus.VERIFIED_STRONGLY_SUPPORTED,
        why_this_source_matters="Scheme page published by the administering ministry.",
    )
    defaults.update(kwargs)
    return EvidenceItem(**defaults)


# ---------------------------------------------------------------------------
# 1. Domestic violence
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_domestic_violence_is_classified_and_routed(mock_llm):
    """A DV disclosure must be classified as such, with high urgency."""
    expected = Situation(
        case_summary="User is being threatened by their partner at home and is afraid.",
        category=SituationCategory.DOMESTIC_VIOLENCE,
        urgency=Urgency.CRITICAL,
        user_goal="Find a way to be safe and understand the available options.",
        known_facts=["Partner has made threats inside the home"],
        user_claims=[],
        unknowns=["Whether a safe place to go is available"],
    )
    mock_llm.structured_generate.return_value = expected

    situation = await SituationAgent(mock_llm).analyse(
        "I am being threatened by my partner and I don't know what to do."
    )

    assert situation.category == SituationCategory.DOMESTIC_VIOLENCE
    assert situation.urgency in (Urgency.HIGH, Urgency.CRITICAL)
    assert SafetyPlanAgent.is_safety_case(situation.category.value) is True


def test_domestic_violence_resources_are_indian_and_attributed():
    """National helplines must be Indian and each must carry its source."""
    agent = SafetyPlanAgent(MagicMock())
    resources = agent.match_resources("domestic_violence", local_resources=[], evidence=[])

    numbers = {r.phone for r in resources if r.phone}
    assert "112" in numbers
    assert "181" in numbers
    # No US emergency numbers anywhere in the output.
    assert "911" not in numbers

    for r in resources:
        assert r.verification == ResourceVerification.OFFICIAL_SOURCE
        assert r.verification_note, f"{r.name} has no provenance note"
        assert r.url, f"{r.name} has no official source URL"


def test_action_planner_prompt_forbids_confrontation():
    """The safety mandate against confronting an abuser must be in the prompt."""
    from backend.agents.action_planner import _PLANNER_SYSTEM_PROMPT

    lowered = _PLANNER_SYSTEM_PROMPT.lower()
    assert "do not tell a user to confront" in lowered or "never" in lowered
    assert "confront" in lowered


def test_safety_plan_prompt_forbids_confrontation_and_us_numbers():
    from backend.agents.safety_plan_agent import _SAFETY_PLAN_SYNTHESIS_PROMPT

    prompt = _SAFETY_PLAN_SYNTHESIS_PROMPT
    assert "NEVER suggest confronting" in prompt
    assert "911" in prompt and "NEVER mention 911" in prompt
    assert "112" in prompt and "181" in prompt


# ---------------------------------------------------------------------------
# 2 & 3. Stalking and online harassment route to Indian cyber resources
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("category", ["stalking", "online_harassment"])
def test_cyber_categories_surface_indian_cyber_reporting(category):
    agent = SafetyPlanAgent(MagicMock())
    resources = agent.match_resources(category, local_resources=[], evidence=[])

    urls = " ".join(r.url or "" for r in resources)
    assert "cybercrime.gov.in" in urls
    assert any(r.phone == "1930" for r in resources)


def test_maps_queries_are_india_specific():
    """Local searches must name the institutions that exist in India."""
    from backend.services.maps_service import MapsService

    dv_query, _ = MapsService.build_query("domestic_violence", "Bhopal, Madhya Pradesh")
    assert "One Stop Centre" in dv_query
    assert "Bhopal" in dv_query

    stalk_query, _ = MapsService.build_query("stalking", "Kochi, Kerala")
    assert "Mahila" in stalk_query or "women police" in stalk_query.lower()

    cyber_query, _ = MapsService.build_query("online_harassment", "Jaipur, Rajasthan")
    assert "cyber" in cyber_query.lower()

    legal_query, _ = MapsService.build_query("workplace_harassment", "Pune, Maharashtra")
    assert "Legal Services Authority" in legal_query


# ---------------------------------------------------------------------------
# 4. Workplace harassment (POSH)
# ---------------------------------------------------------------------------

def test_workplace_harassment_surfaces_posh_route():
    agent = SafetyPlanAgent(MagicMock())
    resources = agent.match_resources("workplace_harassment", local_resources=[], evidence=[])

    assert any(r.category == "posh_icc" for r in resources)
    assert any("shebox" in (r.url or "").lower() for r in resources)


def test_posh_is_recognised_as_a_safety_case_from_text():
    assert SafetyPlanAgent.is_safety_case("employment", "my manager keeps making sexual comments") is True
    assert SafetyPlanAgent.is_safety_case("other", "I need to file a POSH complaint") is True


# ---------------------------------------------------------------------------
# 5. Non-safety cases must not trigger safety machinery
# ---------------------------------------------------------------------------

def test_ordinary_consumer_case_is_not_a_safety_case():
    assert SafetyPlanAgent.is_safety_case("consumer", "My laptop arrived damaged and the seller won't refund it.") is False
    assert SafetyPlanAgent.is_safety_case("travel", "My flight was cancelled and I want a refund.") is False


def test_consumer_case_gets_consumer_resources_not_helplines():
    from backend.india_resources import portals_for_category

    portals = portals_for_category("consumer")
    assert portals, "A consumer case should still get the consumer redressal portal"
    assert any("consumerhelpline" in p.url for p in portals)


# ---------------------------------------------------------------------------
# 6. Legacy endpoints are preserved
# ---------------------------------------------------------------------------

def test_legacy_community_endpoint_still_responds(client):
    resp = client.get("/get-admin-posts")
    assert resp.status_code == 200
    assert isinstance(resp.json(), list)


def test_legacy_community_posts_do_not_expose_contact_details(client):
    """The community feed is public — contact fields must be stripped."""
    posts = client.get("/get-admin-posts").json()
    for post in posts:
        keys = {k.lower() for k in post}
        assert "contact info" not in keys
        assert "contact_info" not in keys
        assert "phone" not in keys
        assert "preferred way of contact" not in keys


def test_health_endpoint_reports_integration_status(client):
    resp = client.get("/health")
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "ok"
    assert "integrations" in body
    assert "database" in body


def test_find_match_rejects_arbitrary_collections(client):
    """The collection name must not be a free-text path into the database."""
    resp = client.get("/find-match", params={"info": "x", "collection": "cases"})
    assert resp.status_code == 400


# ---------------------------------------------------------------------------
# 7. Evidence linking
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_action_plan_actions_reference_their_evidence(mock_llm):
    """Every recommendation must point at the source that supports it."""
    evidence = [_evidence()]
    report = FinalResearchReport(
        case_id="case-dv-1",
        situation=Situation(
            case_summary="Threatened at home by a partner.",
            category=SituationCategory.DOMESTIC_VIOLENCE,
            urgency=Urgency.HIGH,
            user_goal="Be safe and understand my options.",
        ),
        evidence=evidence,
    )

    mock_llm.structured_generate.return_value = ActionPlan(
        case_id="case-dv-1",
        summary="Immediate safety first, then support and formal options.",
        immediate_actions=[
            ActionItem(
                id="",
                title="Call 181 or 112 if you are in danger",
                description="181 is the national women helpline and operates 24x7.",
                action_type=ActionType.CONTACT,
                priority=ActionPriority.IMMEDIATE,
                evidence_ids=["EVIDENCE_01"],
            )
        ],
        next_actions=[],
        escalation_options=[],
        things_to_avoid=["Do not confront the person causing harm."],
    )

    plan = await ActionPlanner(mock_llm).plan(report)

    assert plan.actions, "Actions should be flattened for the UI"
    first = plan.immediate_actions[0]
    assert first.id, "Missing action ids must be filled in"
    assert first.timing_phase == ActionTimingPhase.DO_NOW
    assert "EVIDENCE_01" in first.evidence_ids
    # The claimed evidence must actually exist in the report.
    known_ids = {e.id for e in evidence}
    assert set(first.evidence_ids).issubset(known_ids)
    assert any("confront" in t.lower() for t in plan.things_to_avoid)
