"""
Demonstration-scenario tests.

Two properties matter beyond "does it work":

1. **A demo case is still a real, owned case.** Running a scenario must not
   weaken ownership, create cases in anyone else's account, or become a path
   around authorisation.
2. **Sample data stays identifiable.** The label has to survive in storage, not
   just in the UI that created it, so a sample can never be read as someone's
   actual report.

All offline — storage is the in-memory fallback, and no scenario run here
reaches Gemini or SerpApi.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from backend.demo_scenarios import (
    DEMO_TITLE_PREFIX,
    SCENARIOS,
    get_scenario,
    is_demo_case,
    list_scenarios,
)
from backend.rate_limit import reset_limiter


@pytest.fixture(autouse=True)
def _clean_limiter():
    reset_limiter()
    yield
    reset_limiter()


@pytest.fixture
def client():
    from backend.main import app

    return TestClient(app)


@pytest.fixture
def other_client():
    from backend.main import app

    c = TestClient(app)
    c.get("/health")
    return c


# ---------------------------------------------------------------------------
# The scenarios themselves
# ---------------------------------------------------------------------------

def test_all_four_scenarios_exist():
    ids = {s.id for s in SCENARIOS}
    assert ids == {
        "late_night_travel",
        "workplace_harassment",
        "online_blackmail",
        "unfamiliar_area",
    }


def test_every_scenario_is_runnable_through_the_normal_api():
    """Situation text must satisfy CaseCreate, or 'Try this' would 422."""
    from backend.models.case import CaseCreate

    for scenario in SCENARIOS:
        payload = CaseCreate(
            situation_text=scenario.situation_text,
            category=scenario.category,
            demo_scenario_id=scenario.id,
        )
        assert len(payload.situation_text) >= 10


def test_every_scenario_carries_its_disclaimer():
    for scenario in list_scenarios():
        assert scenario["is_demo"] is True
        assert "fictional" in scenario["disclaimer"].lower()
        assert "not describe a real" in scenario["disclaimer"].lower()


def test_scenarios_are_written_as_a_person_would_write():
    """Legal vocabulary in the prompt would do the situation agent's job for it."""
    for scenario in SCENARIOS:
        lowered = scenario.situation_text.lower()
        for jargon in ("pursuant to", "section 354", "whereas", "hereby"):
            assert jargon not in lowered


def test_only_supported_engines_are_predicted():
    """Naming an engine the integration does not have would mislead a reviewer."""
    supported = {"google", "google_news", "google_maps"}
    for scenario in SCENARIOS:
        assert set(scenario.expected_engines) <= supported


def test_unknown_scenario_id_resolves_to_nothing():
    assert get_scenario("does_not_exist") is None


# ---------------------------------------------------------------------------
# API
# ---------------------------------------------------------------------------

def test_scenarios_endpoint_lists_them(client):
    body = client.get("/api/v2/demo/scenarios").json()
    assert body["count"] == 4
    assert "fictional" in body["notice"].lower()
    assert "real pipeline" in body["how_it_works"].lower()


def test_scenarios_endpoint_needs_no_account(client):
    """Static prose with no user content — a login wall would serve nobody."""
    from backend.main import app

    assert TestClient(app).get("/api/v2/demo/scenarios").status_code == 200


# ---------------------------------------------------------------------------
# A demo case is a real case
# ---------------------------------------------------------------------------

def _run(client, scenario_id="workplace_harassment"):
    scenario = get_scenario(scenario_id)
    response = client.post(
        "/api/v2/cases",
        json={
            "situation_text": scenario.situation_text,
            "category": scenario.category,
            "demo_scenario_id": scenario.id,
        },
    )
    assert response.status_code == 200, response.text
    return response.json()


def test_running_a_scenario_creates_a_labelled_case(client):
    case = _run(client)
    assert case["is_demo"] is True
    assert case["demo_scenario_id"] == "workplace_harassment"
    assert case["title"].startswith(DEMO_TITLE_PREFIX)


def test_demo_case_is_owned_like_any_other(client, other_client):
    """The whole risk of demo data is that it leaks. It must not."""
    case = _run(client)
    assert other_client.get(f"/api/v2/cases/{case['id']}").status_code == 403
    assert other_client.patch(
        f"/api/v2/cases/{case['id']}", json={"title": "hijacked"}
    ).status_code == 403
    assert other_client.delete(f"/api/v2/cases/{case['id']}").status_code == 403


def test_demo_case_does_not_appear_in_another_session(client, other_client):
    _run(client)
    listing = other_client.get("/api/v2/cases").json()
    items = listing if isinstance(listing, list) else listing.get("cases", listing.get("items", []))
    assert len(items) == 0


def test_demo_case_can_be_deleted_like_any_other(client):
    case = _run(client)
    assert client.delete(f"/api/v2/cases/{case['id']}").status_code == 200


def test_an_ordinary_case_is_not_marked_as_demo(client):
    response = client.post(
        "/api/v2/cases",
        json={"situation_text": "Something real that I am dealing with right now."},
    )
    case = response.json()
    assert case["is_demo"] is False
    assert case["demo_scenario_id"] is None
    assert not case["title"].startswith(DEMO_TITLE_PREFIX)


def test_unknown_scenario_id_produces_an_ordinary_case(client):
    """An unrecognised id must not be written onto the record verbatim."""
    response = client.post(
        "/api/v2/cases",
        json={
            "situation_text": "A real situation I need help with today.",
            "demo_scenario_id": "../../etc/passwd",
        },
    )
    case = response.json()
    assert case["is_demo"] is False
    assert case["demo_scenario_id"] is None


def test_demo_flag_cannot_be_used_to_claim_someone_elses_case(client, other_client):
    """It is a label, not a capability — ownership still comes from the session."""
    case = _run(client)
    assert other_client.patch(
        f"/api/v2/cases/{case['id']}",
        json={"title": "mine now"},
    ).status_code == 403


# ---------------------------------------------------------------------------
# Nothing is seeded
# ---------------------------------------------------------------------------

def test_no_demo_cases_exist_until_one_is_run(client):
    """Scenarios must not be written to storage at import or startup."""
    listing = client.get("/api/v2/cases").json()
    items = listing if isinstance(listing, list) else listing.get("cases", listing.get("items", []))
    assert not any(c.get("is_demo") for c in items)


def test_importing_the_module_writes_nothing():
    import importlib

    from backend.db import get_database

    before = get_database()["cases"].count_documents({})
    importlib.reload(__import__("backend.demo_scenarios", fromlist=["x"]))
    assert get_database()["cases"].count_documents({}) == before


# ---------------------------------------------------------------------------
# Identification helper
# ---------------------------------------------------------------------------

def test_is_demo_case_uses_the_flag():
    assert is_demo_case({"is_demo": True}) is True
    assert is_demo_case({"is_demo": False, "title": "Real case"}) is False


def test_is_demo_case_falls_back_to_the_title_prefix():
    """Cases created before the flag existed are still identifiable."""
    assert is_demo_case({"title": f"{DEMO_TITLE_PREFIX} Something"}) is True
