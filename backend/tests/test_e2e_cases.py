"""
End-to-end pipeline tests for the seven journeys HerWay must support.

A. Domestic violence / immediate danger
B. Workplace sexual harassment (POSH)
C. Online harassment / stalking
D. Non-emergency legal question
E. Emotional distress (no legal escalation)
F. Community browsing and case creation
G. Discreet communication (encode → decode round trip)

Plus the failure paths: Gemini down, SerpApi down, invalid LLM JSON, and case
persistence across a reload.

Every external call is mocked, so this suite runs offline and spends no API
credit. This module previously imported names that do not exist in
``backend.models.research`` and so never ran at all.
"""

from __future__ import annotations

import base64
import io
from contextlib import contextmanager
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient
from PIL import Image

from backend.main import app
from backend.models.action_plan import ActionItem, ActionPlan, ActionPriority, ActionType
from backend.models.research import (
    EvidenceItem,
    EvidenceStatus,
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
from backend.models.safety_plan import (
    SafetyActionItem,
    SafetyAssessment,
    SafetyPlanPhase,
)
from backend.services.llm_service import LLMUnavailableError


# ---------------------------------------------------------------------------
# Fixtures and helpers
# ---------------------------------------------------------------------------

@pytest.fixture
def client():
    return TestClient(app)


MOCK_WEB_RESULTS = [
    SearchResult(
        title="Women Helpline Scheme — Ministry of Women and Child Development",
        url="https://wcd.gov.in/schemes/women-helpline-scheme",
        snippet="181 provides 24x7 support to women affected by violence.",
        domain="wcd.gov.in",
        result_type="web",
    ),
    SearchResult(
        title="One Stop Centre Scheme (Sakhi)",
        url="https://wcd.gov.in/schemes/one-stop-centre-scheme-1",
        snippet="Integrated support to women affected by violence at district level.",
        domain="wcd.gov.in",
        result_type="web",
    ),
]

MOCK_MAPS_RESULTS = [
    SearchResult(
        title="One Stop Centre (Sakhi), Pune",
        url="https://pune.gov.in/one-stop-centre",
        address="Shivajinagar, Pune, Maharashtra 411005",
        domain="pune.gov.in",
        result_type="maps",
    )
]


def _search_outcome(vertical: str, results, success: bool = True) -> SearchOutcome:
    return SearchOutcome(
        vertical=vertical,
        query="q",
        success=success,
        results=list(results),
        failure_reason=SearchFailureReason.NONE if success else SearchFailureReason.HTTP_ERROR,
        error_message=None if success else "SerpApi returned HTTP 503.",
    )


def _fake_serpapi(web=None, maps=None, web_ok=True, maps_ok=True):
    """Build a SerpApiService stand-in that routes by vertical."""

    async def _search_detailed(query, vertical=SearchVertical.WEB, **kwargs):
        name = getattr(vertical, "value", str(vertical))
        if "map" in name or "local" in name:
            return _search_outcome("maps", maps if maps is not None else MOCK_MAPS_RESULTS, maps_ok)
        if "news" in name:
            return _search_outcome("news", [], True)
        return _search_outcome("web", web if web is not None else MOCK_WEB_RESULTS, web_ok)

    serp = MagicMock()
    serp.search_detailed = AsyncMock(side_effect=_search_detailed)
    serp.search_web = AsyncMock(return_value=list(web if web is not None else MOCK_WEB_RESULTS))
    serp.search_maps = AsyncMock(return_value=list(maps if maps is not None else MOCK_MAPS_RESULTS))
    serp.search_news = AsyncMock(return_value=[])
    return serp


def _situation(category: SituationCategory, summary: str, **kwargs) -> Situation:
    defaults = dict(
        case_summary=summary,
        category=category,
        urgency=Urgency.HIGH,
        user_goal="Understand my options and stay safe.",
        known_facts=[],
        user_claims=[],
        unknowns=[],
    )
    defaults.update(kwargs)
    return Situation(**defaults)


def _evidence() -> list[EvidenceItem]:
    return [
        EvidenceItem(
            id="EVIDENCE_01",
            source_title="Women Helpline Scheme",
            url="https://wcd.gov.in/schemes/women-helpline-scheme",
            domain="wcd.gov.in",
            source_type=SourceType.OFFICIAL_GOVERNMENT,
            claim_supported="181 is the national 24x7 women helpline.",
            extracted_facts=["181 operates 24x7"],
            authority=0.95,
            confidence_score=0.92,
            status=EvidenceStatus.VERIFIED_STRONGLY_SUPPORTED,
            why_this_source_matters="Published by the administering ministry.",
        )
    ]


def _action_plan(case_id: str) -> ActionPlan:
    return ActionPlan(
        case_id=case_id,
        summary="Safety first, then support, then formal options.",
        immediate_actions=[
            ActionItem(
                id="ACTION_NOW_01",
                title="Call 181 or 112 if you are in danger",
                description="181 is the national women helpline, available 24x7.",
                action_type=ActionType.CONTACT,
                priority=ActionPriority.IMMEDIATE,
                evidence_ids=["EVIDENCE_01"],
            )
        ],
        things_to_avoid=["Do not confront the person causing harm."],
    )


def _assessment() -> SafetyAssessment:
    return SafetyAssessment(
        immediate_safety_concern=True,
        threats_present=True,
        context_summary="Threats made inside the home.",
        indicator_justifications={"threats_present": "User reports being threatened."},
        critical_safety_notes=["Do not confront the person causing harm."],
    )


class _SynthOutput:
    """Shape returned by the safety plan synthesis step."""

    right_now_actions = [
        SafetyActionItem(
            id="SAFE_RIGHT_NOW_01",
            title="Move to a room with a door you can lock, or a neighbour's home",
            description="Choose somewhere with a second exit if you can.",
            phase=SafetyPlanPhase.RIGHT_NOW,
            priority=ActionPriority.IMMEDIATE,
        )
    ]
    next_24h_actions = []
    document_safe_actions = [
        SafetyActionItem(
            id="SAFE_DOC_01",
            title="Save messages to a device he cannot reach",
            description="Forward them to an account he does not know about.",
            phase=SafetyPlanPhase.DOCUMENT_SAFE,
            priority=ActionPriority.MEDIUM,
            safety_caveat="Only if it is safe to do so.",
        )
    ]
    support_network_actions = []
    formal_options_actions = []
    ongoing_actions = []
    things_to_avoid = ["Do not confront him.", "Do not warn him that you are leaving."]


@contextmanager
def _mocked_pipeline(
    situation: Situation,
    serpapi=None,
    verify_evidence=None,
    local_resources=None,
    action_plan_for=None,
):
    """Patch every external dependency used by POST /research/{id}/run."""
    serp = serpapi or _fake_serpapi()

    llm = MagicMock()
    llm.is_configured = True
    llm.structured_generate = AsyncMock()

    plan = ResearchPlan(
        case_id="pending",
        reasoning="Targeted India-first research.",
        tasks=[
            ResearchTask(
                task_id="TASK_01",
                query="women helpline 181 official site",
                vertical=SearchVertical.WEB,
                purpose="Confirm the official national helpline",
                expected_information="Helpline number and operating hours",
                priority="high",
            )
        ],
    )

    def _structured(*, system_prompt, user_prompt, output_schema):
        name = getattr(output_schema, "__name__", "")
        if output_schema is Situation or name == "Situation":
            return situation
        if name == "_PlanWrapper":
            return plan
        if output_schema is ActionPlan or name == "ActionPlan":
            return (action_plan_for or _action_plan)("pending")
        if name == "SafetyAssessment":
            return _assessment()
        if name == "_PlanSynthesisOutput":
            return _SynthOutput()
        raise AssertionError(f"Unexpected schema requested: {name}")

    llm.structured_generate.side_effect = _structured

    verifier_evidence = _evidence() if verify_evidence is None else verify_evidence

    with patch("backend.routes.research.LLMService", return_value=llm), patch(
        "backend.routes.research.SerpApiService", return_value=serp
    ), patch(
        "backend.agents.source_verifier.SourceVerifier.verify",
        new=AsyncMock(return_value=verifier_evidence),
    ), patch(
        "backend.services.maps_service.MapsService.discover_local_resources_detailed",
        new=AsyncMock(return_value=_local_discovery(local_resources)),
    ):
        yield llm, serp


def _local_discovery(resources):
    from backend.services.maps_service import LocalDiscoveryResult

    if resources is None:
        resources = [
            LocalResource(
                name="One Stop Centre (Sakhi), Pune",
                type="One Stop Centre & women's shelter",
                address="Shivajinagar, Pune, Maharashtra 411005",
                verification=ResourceVerification.LIKELY_OFFICIAL,
                verification_note="Name matches a government service.",
            )
        ]
    return LocalDiscoveryResult(resources=resources, success=True, location_used="Pune, Maharashtra")


def _create_case(c: TestClient, text: str, category: str, location: str | None = None) -> str:
    payload = {"situation_text": text, "category": category}
    if location:
        payload["location"] = {"display_name": location}
    resp = c.post("/api/v2/cases", json=payload)
    assert resp.status_code == 200, resp.text
    return resp.json()["id"]


# ---------------------------------------------------------------------------
# FLOW A — Domestic violence / immediate danger
# ---------------------------------------------------------------------------

def test_flow_a_domestic_violence_end_to_end(client):
    case_id = _create_case(
        client,
        "I am being threatened by my partner and I don't know what to do.",
        "domestic_violence",
        location="Pune, Maharashtra",
    )

    situation = _situation(
        SituationCategory.DOMESTIC_VIOLENCE,
        "User is being threatened by their partner at home.",
        urgency=Urgency.CRITICAL,
        location="Pune, Maharashtra",
    )

    with _mocked_pipeline(situation):
        resp = client.post(f"/api/v2/research/{case_id}/run")

    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["safety_plan_generated"] is True
    assert body["evidence_count"] >= 1

    # The case must persist with everything attached.
    case = client.get(f"/api/v2/cases/{case_id}").json()
    assert case["category"] == "domestic_violence"
    assert case["safety_plan"] is not None
    assert case["evidence"]
    assert case["research_trace"]

    plan = case["safety_plan"]
    assert plan["right_now_actions"], "An acute DV case must have immediate steps"

    # Safety mandate: nothing in the plan may tell her to confront him.
    plan_text = " ".join(
        f"{a['title']} {a['description']}" for a in plan["actions"]
    ).lower()
    assert "confront" not in plan_text

    # India-first resources with honest provenance.
    numbers = {r.get("phone") for r in plan["matched_resources"]}
    assert "112" in numbers and "181" in numbers
    assert "911" not in numbers
    for r in plan["matched_resources"]:
        assert r["verification"] in {"official_source", "likely_official", "unverified_listing"}
        assert r["verification_note"] != "" or r["verification"] == "unverified_listing"


def test_flow_a_case_survives_a_reload(client):
    """Create → research → re-fetch with a fresh request: nothing is lost."""
    case_id = _create_case(
        client, "He threatened me again last night.", "domestic_violence", "Nagpur, Maharashtra"
    )
    situation = _situation(
        SituationCategory.DOMESTIC_VIOLENCE, "Repeated threats at home.", location="Nagpur, Maharashtra"
    )
    with _mocked_pipeline(situation):
        client.post(f"/api/v2/research/{case_id}/run")

    first = client.get(f"/api/v2/cases/{case_id}").json()
    second = client.get(f"/api/v2/cases/{case_id}").json()

    assert first["safety_plan"] == second["safety_plan"]
    assert first["evidence"] == second["evidence"]
    assert second["title"]


@pytest.mark.parametrize("new_status", ["paused", "resolved", "archived", "active"])
def test_flow_a_case_lifecycle_statuses(client, new_status):
    case_id = _create_case(client, "A situation description long enough to validate.", "safety")
    resp = client.patch(f"/api/v2/cases/{case_id}", json={"status": new_status})
    assert resp.status_code == 200
    assert client.get(f"/api/v2/cases/{case_id}").json()["status"] == new_status


# ---------------------------------------------------------------------------
# FLOW B — Workplace sexual harassment (POSH)
# ---------------------------------------------------------------------------

def test_flow_b_workplace_harassment_surfaces_posh_route(client):
    case_id = _create_case(
        client,
        "My manager keeps making sexual comments and I don't know how to complain.",
        "workplace_harassment",
    )

    situation = _situation(
        SituationCategory.WORKPLACE_HARASSMENT,
        "Repeated sexual comments from a manager at work.",
        urgency=Urgency.MEDIUM,
        user_goal="Understand how to complain safely.",
    )

    with _mocked_pipeline(situation):
        resp = client.post(f"/api/v2/research/{case_id}/run")

    assert resp.status_code == 200
    case = client.get(f"/api/v2/cases/{case_id}").json()
    assert case["safety_plan"] is not None

    resources = case["safety_plan"]["matched_resources"]
    assert any(r["category"] == "posh_icc" for r in resources), "POSH route must be offered"
    assert any("shebox" in (r.get("url") or "").lower() for r in resources)
    # Legal aid must be offered — women are entitled to it free of charge.
    assert any(r["category"] == "legal_aid" for r in resources)


# ---------------------------------------------------------------------------
# FLOW C — Online harassment / stalking
# ---------------------------------------------------------------------------

def test_flow_c_online_harassment_surfaces_cyber_reporting(client):
    case_id = _create_case(
        client, "Someone is repeatedly threatening me on Instagram.", "online_harassment"
    )

    situation = _situation(
        SituationCategory.ONLINE_HARASSMENT,
        "Repeated threatening messages from an account on Instagram.",
    )

    with _mocked_pipeline(situation):
        resp = client.post(f"/api/v2/research/{case_id}/run")

    assert resp.status_code == 200
    case = client.get(f"/api/v2/cases/{case_id}").json()
    plan = case["safety_plan"]
    assert plan is not None

    urls = " ".join((r.get("url") or "") for r in plan["matched_resources"])
    assert "cybercrime.gov.in" in urls
    assert any(r.get("phone") == "1930" for r in plan["matched_resources"])

    # Evidence preservation must be offered with a safety caveat attached.
    doc_actions = plan["document_safe_actions"]
    assert doc_actions, "Online harassment needs evidence-preservation guidance"
    assert any(a.get("safety_caveat") for a in doc_actions)


# ---------------------------------------------------------------------------
# FLOW D — Non-emergency legal question
# ---------------------------------------------------------------------------

def test_flow_d_legal_question_does_not_force_a_safety_plan(client):
    """A pure information request must not be escalated into a crisis case."""
    case_id = _create_case(
        client,
        "What is the notice period my landlord has to give before eviction?",
        "housing",
    )

    situation = _situation(
        SituationCategory.HOUSING,
        "User wants to know the notice period required before eviction.",
        urgency=Urgency.LOW,
        user_goal="Understand the notice requirements.",
    )

    with _mocked_pipeline(situation):
        resp = client.post(f"/api/v2/research/{case_id}/run")

    assert resp.status_code == 200
    assert resp.json()["safety_plan_generated"] is False

    case = client.get(f"/api/v2/cases/{case_id}").json()
    assert case["safety_plan"] is None
    assert case["action_plan"] is not None


def test_flow_d_lawbot_prompt_separates_information_from_advice():
    from backend.agents.chat_agent import _LEGAL_MODE_PROMPT

    assert "not a lawyer" in _LEGAL_MODE_PROMPT
    assert "legal information, not legal advice" in _LEGAL_MODE_PROMPT
    assert "Never invent a section number" in _LEGAL_MODE_PROMPT
    # The claim-labelling vocabulary the spec asks for.
    for label in ("**Fact:**", "**Legal information:**", "**Possible option:**", "**Needs verification:**"):
        assert label in _LEGAL_MODE_PROMPT


# ---------------------------------------------------------------------------
# FLOW E — Emotional distress
# ---------------------------------------------------------------------------

def test_flow_e_therapy_mode_avoids_legal_escalation_and_search():
    from backend.agents.chat_agent import ChatAgent, _THERAPY_MODE_PROMPT

    agent = ChatAgent(MagicMock(), MagicMock())
    prompt = agent._system_prompt("therapy")

    assert _THERAPY_MODE_PROMPT in prompt
    assert "Do NOT escalate to legal steps" in prompt
    assert "Do NOT call search tools for feelings" in prompt
    # Tele-MANAS is the Indian mental-health line and must be what we surface.
    assert "14416" in prompt


def test_flow_e_therapy_chat_returns_a_real_reply(client):
    """Niva must answer through the agent, not a hardcoded script."""
    llm = MagicMock()
    llm.is_configured = True
    llm.structured_generate = AsyncMock()

    agent_result = {
        "reply": "That sounds exhausting. I'm here. Tell me what today has been like.",
        "tool_used": "answer_user",
    }

    with patch("backend.routes.chat.LLMService", return_value=llm), patch(
        "backend.routes.chat.SerpApiService", return_value=_fake_serpapi()
    ), patch(
        "backend.agents.chat_agent.ChatAgent.converse", new=AsyncMock(return_value=agent_result)
    ):
        resp = client.post(
            "/api/v2/chat",
            json={"message": "I feel completely overwhelmed today.", "mode": "therapy"},
        )

    assert resp.status_code == 200
    body = resp.json()
    assert body["reply"] == agent_result["reply"]
    assert body["tool_used"] == "answer_user"


# ---------------------------------------------------------------------------
# FLOW F — Community
# ---------------------------------------------------------------------------

def test_flow_f_community_list_and_detail(client):
    posts = client.get("/get-admin-posts").json()
    assert isinstance(posts, list)
    if not posts:
        pytest.skip("No seeded community posts in this environment")

    post_id = posts[0]["_id"]
    detail = client.get(f"/get-post/{post_id}")
    assert detail.status_code == 200
    assert "Contact info" not in detail.json()


def test_flow_f_community_detail_handles_bad_and_missing_ids(client):
    assert client.get("/get-post/not-an-id").status_code == 400
    assert client.get("/get-post/660000000000000000009999").status_code == 404


def test_flow_f_case_can_be_started_from_a_community_situation(client):
    """Creating a case from community content must work and stay private."""
    case_id = _create_case(
        client,
        "Nature: isolation and harassment over dowry demands. Severity: medium.",
        "domestic_violence",
    )
    case = client.get(f"/api/v2/cases/{case_id}").json()
    assert case["id"] == case_id

    # A different visitor must not see it in the community feed or by listing.
    other = TestClient(app)
    assert other.get("/api/v2/cases").json() == []


def test_flow_f_posting_only_stores_allowed_fields(client):
    resp = client.post(
        "/save-extracted-data",
        json={
            "Name": "Anonymous",
            "Other info": "Sharing my experience.",
            "Contact info": "me@example.com",
            "status": "closed",
            "_id": "deadbeefdeadbeefdeadbeef",
        },
    )
    assert resp.status_code == 200
    new_id = resp.json()["id"]
    assert new_id != "deadbeefdeadbeefdeadbeef", "Caller must not control the document id"

    stored = client.get(f"/get-post/{new_id}").json()
    assert "Contact info" not in stored
    assert stored["status"] == "pending", "status is server-controlled"


# ---------------------------------------------------------------------------
# FLOW G — Discreet communication round trip
# ---------------------------------------------------------------------------

def _png_bytes(width=120, height=120) -> bytes:
    img = Image.new("RGB", (width, height), (180, 140, 160))
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def test_flow_g_encode_then_decode_round_trip(client):
    secret = "I am not safe at home. Please come to the back gate at 7."

    encode_resp = client.post(
        "/api/v2/discreet/encode",
        data={"message": secret},
        files={"file": ("photo.png", _png_bytes(), "image/png")},
    )
    assert encode_resp.status_code == 200, encode_resp.text
    encoded = encode_resp.json()
    assert encoded["message_length"] == len(secret)
    assert encoded["limitations"], "The honest limitations must always be returned"

    image_bytes = base64.b64decode(encoded["image_base64"])

    decode_resp = client.post(
        "/api/v2/discreet/decode",
        files={"file": ("photo.png", image_bytes, "image/png")},
    )
    assert decode_resp.status_code == 200, decode_resp.text
    body = decode_resp.json()
    assert body["found"] is True
    assert body["message"] == secret


def test_flow_g_round_trip_preserves_indian_language_text(client):
    """Non-ASCII must survive — many users will not write in English."""
    secret = "मैं सुरक्षित नहीं हूँ। कृपया मदद करें।"

    encode_resp = client.post(
        "/api/v2/discreet/encode",
        data={"message": secret},
        files={"file": ("photo.png", _png_bytes(200, 200), "image/png")},
    )
    assert encode_resp.status_code == 200
    image_bytes = base64.b64decode(encode_resp.json()["image_base64"])

    decode_resp = client.post(
        "/api/v2/discreet/decode",
        files={"file": ("photo.png", image_bytes, "image/png")},
    )
    assert decode_resp.json()["message"] == secret


def test_flow_g_encoded_image_still_looks_like_the_original(client):
    """The carrier must be visually unchanged, or it defeats the purpose."""
    original = _png_bytes(100, 100)
    resp = client.post(
        "/api/v2/discreet/encode",
        data={"message": "help"},
        files={"file": ("photo.png", original, "image/png")},
    )
    encoded = Image.open(io.BytesIO(base64.b64decode(resp.json()["image_base64"]))).convert("RGB")
    source = Image.open(io.BytesIO(original)).convert("RGB")

    assert encoded.size == source.size
    # Only the low bit of the red channel may differ, and only by one.
    for xy in [(0, 0), (5, 5), (50, 50), (99, 99)]:
        er, eg, eb = encoded.getpixel(xy)
        sr, sg, sb = source.getpixel(xy)
        assert abs(er - sr) <= 1
        assert (eg, eb) == (sg, sb)


def test_flow_g_image_too_small_is_a_clear_error(client):
    resp = client.post(
        "/api/v2/discreet/encode",
        data={"message": "x" * 500},
        files={"file": ("tiny.png", _png_bytes(8, 8), "image/png")},
    )
    assert resp.status_code == 400
    assert "too small" in resp.json()["detail"].lower()


def test_flow_g_decoding_a_plain_image_reports_nothing_found(client):
    resp = client.post(
        "/api/v2/discreet/decode",
        files={"file": ("photo.png", _png_bytes(), "image/png")},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["found"] is False
    assert "compressed" in body["note"].lower()


def test_flow_g_non_image_upload_is_rejected(client):
    resp = client.post(
        "/api/v2/discreet/decode",
        files={"file": ("notes.txt", b"this is not an image", "text/plain")},
    )
    assert resp.status_code == 400


def test_flow_g_feature_is_not_described_as_secure(client):
    """We must not claim encryption we do not provide."""
    body = client.get("/api/v2/discreet/limitations").json()
    assert body["is_encryption"] is False
    joined = " ".join(body["limitations"]).lower()
    assert "not encryption" in joined
    assert "compress" in joined


# ---------------------------------------------------------------------------
# Failure paths
# ---------------------------------------------------------------------------

def test_research_reports_llm_outage_instead_of_inventing(client):
    case_id = _create_case(client, "I am scared of my husband and need help.", "domestic_violence")

    llm = MagicMock()
    llm.is_configured = True
    llm.structured_generate = AsyncMock(side_effect=LLMUnavailableError("Gemini down"))

    with patch("backend.routes.research.LLMService", return_value=llm), patch(
        "backend.routes.research.SerpApiService", return_value=_fake_serpapi()
    ):
        resp = client.post(f"/api/v2/research/{case_id}/run")

    assert resp.status_code == 503
    assert "unavailable" in resp.json()["detail"].lower()

    # The case must survive the failure, back in a usable state.
    case = client.get(f"/api/v2/cases/{case_id}").json()
    assert case["status"] == "active"
    assert case["situation_text"]


def test_research_survives_a_total_serpapi_outage(client):
    """No sources is a valid, honest outcome — it must not break the case."""
    case_id = _create_case(client, "Someone keeps following me home.", "stalking", "Indore, Madhya Pradesh")

    situation = _situation(
        SituationCategory.STALKING, "Being followed home repeatedly.", location="Indore, Madhya Pradesh"
    )
    dead_serp = _fake_serpapi(web=[], maps=[], web_ok=False, maps_ok=False)

    with _mocked_pipeline(situation, serpapi=dead_serp, verify_evidence=[]):
        resp = client.post(f"/api/v2/research/{case_id}/run")

    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "partial"
    assert body["degradations"], "A failed search must be reported, not hidden"
    assert any("did not complete" in d["user_message"] for d in body["degradations"])

    case = client.get(f"/api/v2/cases/{case_id}").json()
    assert case["research_degradations"]


def test_partial_failure_keeps_web_results_and_flags_maps(client):
    """Web succeeds, maps fails: show the web results, state the maps failure."""
    case_id = _create_case(client, "He has been threatening me.", "domestic_violence", "Surat, Gujarat")

    situation = _situation(
        SituationCategory.DOMESTIC_VIOLENCE, "Threats at home.", location="Surat, Gujarat"
    )
    mixed = _fake_serpapi(maps_ok=False)

    with _mocked_pipeline(situation, serpapi=mixed):
        resp = client.post(f"/api/v2/research/{case_id}/run")

    assert resp.status_code == 200
    assert resp.json()["evidence_count"] >= 1
    case = client.get(f"/api/v2/cases/{case_id}").json()
    assert case["evidence"], "Verified web sources must still be delivered"


def test_invalid_llm_json_is_reported_not_faked(client):
    """A model that returns unusable JSON must not become a confident answer."""
    case_id = _create_case(client, "I need help understanding my rights.", "legal_information")

    llm = MagicMock()
    llm.is_configured = True
    llm.structured_generate = AsyncMock(
        side_effect=ValueError("LLM output failed Pydantic validation after retry")
    )

    with patch("backend.routes.research.LLMService", return_value=llm), patch(
        "backend.routes.research.SerpApiService", return_value=_fake_serpapi()
    ):
        resp = client.post(f"/api/v2/research/{case_id}/run")

    assert resp.status_code in (500, 503)
    case = client.get(f"/api/v2/cases/{case_id}").json()
    assert case["status"] == "active"


def test_chat_reports_outage_rather_than_answering_from_memory(client):
    llm = MagicMock()
    llm.is_configured = False

    with patch("backend.routes.chat.LLMService", return_value=llm):
        resp = client.post("/api/v2/chat", json={"message": "What are my rights?"})

    assert resp.status_code == 503
    detail = resp.json()["detail"]
    assert "112" in detail or "181" in detail


def test_analyze_rejects_empty_input(client):
    resp = client.post("/api/v2/cases/analyze", json={"situation_text": "   abc   "})
    assert resp.status_code == 422 or resp.status_code == 400


def test_case_creation_rejects_too_short_text(client):
    resp = client.post("/api/v2/cases", json={"situation_text": "help"})
    assert resp.status_code == 422


# ---------------------------------------------------------------------------
# India resources endpoint
# ---------------------------------------------------------------------------

def test_national_resources_are_attributed(client):
    body = client.get("/api/v2/resources/national").json()
    assert body["helplines"]
    for h in body["helplines"]:
        assert h["official_source_url"].startswith("https://")
        assert h["number"]


def test_regions_endpoint_lists_states_and_uts(client):
    body = client.get("/api/v2/resources/regions").json()
    assert "Maharashtra" in body["states"]
    assert "Delhi" in body["union_territories"]
    assert len(body["all"]) == len(body["states"]) + len(body["union_territories"])


def test_national_resources_filter_by_category(client):
    body = client.get("/api/v2/resources/national", params={"category": "online_harassment"}).json()
    numbers = {h["number"] for h in body["helplines"]}
    assert "1930" in numbers
    urls = " ".join(p["url"] for p in body["portals"])
    assert "cybercrime.gov.in" in urls
