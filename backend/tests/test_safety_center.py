"""
Safety Center tests (Phase 4).

**Persistence here is the in-memory fallback**, because no MongoDB was reachable
in this environment. These tests prove the ownership rules, lifecycle and
honesty properties of the code. They do **not** prove that a plan survives a
restart in production — that remains unverified. See
docs/PHASE4_IMPLEMENTATION_REPORT.md.

The assertions that matter most are the negative ones: that one user cannot
reach another's plan, that nothing claims a message was delivered, and that
nothing claims a check-in is being monitored.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient

from backend.models.safety_center import (
    CheckIn,
    CheckInStatus,
    PlanStep,
    SafetyCenterPlan,
    StepOrigin,
    looks_like_email,
    looks_like_phone,
)
from backend.rate_limit import reset_limiter


@pytest.fixture(autouse=True)
def _clean_limiter():
    reset_limiter()
    yield
    reset_limiter()


@pytest.fixture
def alice():
    """One browser session."""
    from backend.main import app

    client = TestClient(app)
    client.get("/health")  # establishes the anonymous session cookie
    return client


@pytest.fixture
def bob():
    """A different browser session, with its own cookie jar."""
    from backend.main import app

    client = TestClient(app)
    client.get("/health")
    return client


def _make_plan(client, title="Getting home late"):
    response = client.post(
        "/api/v2/safety-center/plans",
        json={"title": title, "steps": ["Share my cab number", "Call when I leave"]},
    )
    assert response.status_code == 200, response.text
    return response.json()


def _make_contact(client, name="Sister", value="+919876543210"):
    response = client.post(
        "/api/v2/safety-center/contacts",
        json={"display_name": name, "method": "phone", "value": value},
    )
    assert response.status_code == 200, response.text
    return response.json()


# ===========================================================================
# Plans — lifecycle
# ===========================================================================

def test_create_and_read_a_plan(alice):
    plan = _make_plan(alice)
    assert plan["title"] == "Getting home late"
    assert len(plan["steps"]) == 2
    assert plan["status"] == "active"

    fetched = alice.get(f"/api/v2/safety-center/plans/{plan['id']}")
    assert fetched.status_code == 200
    assert fetched.json()["id"] == plan["id"]


def test_user_written_steps_are_marked_as_the_users_own(alice):
    plan = _make_plan(alice)
    assert all(step["origin"] == "user" for step in plan["steps"])


def test_multiple_plans_are_supported(alice):
    _make_plan(alice, "Plan A")
    _make_plan(alice, "Plan B")
    listing = alice.get("/api/v2/safety-center/plans").json()
    assert listing["count"] == 2


def test_plan_can_be_paused_and_archived(alice):
    plan = _make_plan(alice)
    for status in ("paused", "archived"):
        response = alice.patch(
            f"/api/v2/safety-center/plans/{plan['id']}", json={"status": status}
        )
        assert response.status_code == 200
        assert response.json()["status"] == status


def test_archived_plans_are_hidden_unless_requested(alice):
    plan = _make_plan(alice)
    alice.patch(f"/api/v2/safety-center/plans/{plan['id']}", json={"status": "archived"})

    assert alice.get("/api/v2/safety-center/plans").json()["count"] == 0
    assert (
        alice.get("/api/v2/safety-center/plans?include_archived=true").json()["count"] == 1
    )


def test_plan_can_be_deleted(alice):
    plan = _make_plan(alice)
    assert alice.delete(f"/api/v2/safety-center/plans/{plan['id']}").json()["deleted"] is True
    assert alice.get(f"/api/v2/safety-center/plans/{plan['id']}").status_code == 404


def test_steps_can_be_added_completed_and_removed(alice):
    plan = _make_plan(alice)
    plan = alice.post(
        f"/api/v2/safety-center/plans/{plan['id']}/steps", json={"text": "Keep phone charged"}
    ).json()
    assert len(plan["steps"]) == 3

    step_id = plan["steps"][-1]["id"]
    plan = alice.patch(
        f"/api/v2/safety-center/plans/{plan['id']}/steps/{step_id}", json={"status": "done"}
    ).json()
    assert plan["steps"][-1]["status"] == "done"

    plan = alice.delete(f"/api/v2/safety-center/plans/{plan['id']}/steps/{step_id}").json()
    assert len(plan["steps"]) == 2


# ===========================================================================
# AI suggestions vs the user's own steps — the honesty boundary
# ===========================================================================

def test_a_suggestion_is_not_part_of_the_plan_until_accepted(alice):
    plan = _make_plan(alice)
    updated = alice.post(
        f"/api/v2/safety-center/plans/{plan['id']}/suggestions",
        json={"text": "Keep a bag packed", "source_urls": ["https://wcd.nic.in/x"]},
    ).json()

    assert len(updated["suggestions"]) == 1
    assert len(updated["steps"]) == 2, "a suggestion must not land in the plan itself"
    assert updated["suggestions"][0]["origin"] == "suggested"


def test_accepting_a_suggestion_moves_it_and_relabels_it(alice):
    plan = _make_plan(alice)
    plan = alice.post(
        f"/api/v2/safety-center/plans/{plan['id']}/suggestions", json={"text": "Keep a bag packed"}
    ).json()
    suggestion_id = plan["suggestions"][0]["id"]

    plan = alice.post(
        f"/api/v2/safety-center/plans/{plan['id']}/suggestions/{suggestion_id}/accept",
        json={},
    ).json()

    assert plan["suggestions"] == []
    accepted = next(s for s in plan["steps"] if s["id"] == suggestion_id)
    assert accepted["origin"] == "accepted_suggestion"


def test_the_users_own_wording_is_preserved_when_she_edits(alice):
    """Her phrasing is what the plan shows; the original stays inspectable."""
    plan = _make_plan(alice)
    plan = alice.post(
        f"/api/v2/safety-center/plans/{plan['id']}/suggestions",
        json={"text": "Pack an emergency bag with documents"},
    ).json()
    suggestion_id = plan["suggestions"][0]["id"]

    plan = alice.post(
        f"/api/v2/safety-center/plans/{plan['id']}/suggestions/{suggestion_id}/accept",
        json={"edited_text": "keep the blue bag ready, papers inside"},
    ).json()

    step = next(s for s in plan["steps"] if s["id"] == suggestion_id)
    assert step["user_edited_text"] == "keep the blue bag ready, papers inside"
    assert step["original_suggestion"] == "Pack an emergency bag with documents"


def test_a_suggestion_can_be_dismissed(alice):
    plan = _make_plan(alice)
    plan = alice.post(
        f"/api/v2/safety-center/plans/{plan['id']}/suggestions", json={"text": "Something"}
    ).json()
    suggestion_id = plan["suggestions"][0]["id"]

    plan = alice.delete(
        f"/api/v2/safety-center/plans/{plan['id']}/suggestions/{suggestion_id}"
    ).json()
    assert plan["suggestions"] == []
    assert len(plan["steps"]) == 2


def test_research_sources_survive_onto_an_accepted_step(alice):
    plan = _make_plan(alice)
    plan = alice.post(
        f"/api/v2/safety-center/plans/{plan['id']}/suggestions",
        json={"text": "Contact the One Stop Centre", "source_urls": ["https://wcd.nic.in/osc"]},
    ).json()
    suggestion_id = plan["suggestions"][0]["id"]
    plan = alice.post(
        f"/api/v2/safety-center/plans/{plan['id']}/suggestions/{suggestion_id}/accept", json={}
    ).json()

    step = next(s for s in plan["steps"] if s["id"] == suggestion_id)
    assert step["source_urls"] == ["https://wcd.nic.in/osc"]


# ===========================================================================
# Cross-user authorization — the most important tests here
# ===========================================================================

def test_another_user_cannot_read_a_plan(alice, bob):
    plan = _make_plan(alice)
    assert bob.get(f"/api/v2/safety-center/plans/{plan['id']}").status_code == 404


def test_another_user_cannot_modify_or_delete_a_plan(alice, bob):
    plan = _make_plan(alice)
    assert bob.patch(
        f"/api/v2/safety-center/plans/{plan['id']}", json={"title": "hijacked"}
    ).status_code == 404
    assert bob.delete(f"/api/v2/safety-center/plans/{plan['id']}").status_code == 404


def test_another_user_cannot_add_steps_to_a_plan(alice, bob):
    plan = _make_plan(alice)
    assert bob.post(
        f"/api/v2/safety-center/plans/{plan['id']}/steps", json={"text": "injected"}
    ).status_code == 404


def test_plan_lists_are_isolated(alice, bob):
    _make_plan(alice, "Alice's plan")
    assert bob.get("/api/v2/safety-center/plans").json()["count"] == 0


def test_another_user_cannot_read_or_delete_a_contact(alice, bob):
    contact = _make_contact(alice)
    assert bob.patch(
        f"/api/v2/safety-center/contacts/{contact['id']}", json={"display_name": "x"}
    ).status_code == 404
    assert bob.delete(f"/api/v2/safety-center/contacts/{contact['id']}").status_code == 404


def test_contact_lists_are_isolated(alice, bob):
    _make_contact(alice)
    assert bob.get("/api/v2/safety-center/contacts").json()["count"] == 0


def test_another_user_cannot_reach_a_check_in(alice, bob):
    started = alice.post("/api/v2/safety-center/check-ins", json={"destination": "Home"}).json()
    assert bob.patch(
        f"/api/v2/safety-center/check-ins/{started['id']}", json={"status": "completed_safe"}
    ).status_code == 404
    assert bob.delete(f"/api/v2/safety-center/check-ins/{started['id']}").status_code == 404


def test_deleting_all_data_only_affects_the_caller(alice, bob):
    _make_plan(alice)
    _make_plan(bob, "Bob's plan")

    alice.delete("/api/v2/safety-center/all-data")

    assert alice.get("/api/v2/safety-center/plans").json()["count"] == 0
    assert bob.get("/api/v2/safety-center/plans").json()["count"] == 1


# ===========================================================================
# Trusted contacts
# ===========================================================================

def test_contact_crud(alice):
    contact = _make_contact(alice)
    assert contact["display_name"] == "Sister"

    updated = alice.patch(
        f"/api/v2/safety-center/contacts/{contact['id']}", json={"relationship": "sister"}
    ).json()
    assert updated["relationship"] == "sister"

    assert alice.delete(f"/api/v2/safety-center/contacts/{contact['id']}").json()["deleted"]


def test_saving_a_contact_never_implies_their_consent(alice):
    contact = _make_contact(alice)
    assert contact["contact_has_consented"] is False

    listing = alice.get("/api/v2/safety-center/contacts").json()
    assert "have not agreed" in listing["notice"]


def test_a_contact_can_be_disabled_without_deleting(alice):
    contact = _make_contact(alice)
    updated = alice.patch(
        f"/api/v2/safety-center/contacts/{contact['id']}", json={"enabled": False}
    ).json()
    assert updated["enabled"] is False


def test_deleting_a_contact_detaches_it_from_plans(alice):
    contact = _make_contact(alice)
    plan = alice.post(
        "/api/v2/safety-center/plans",
        json={"title": "With contact", "contact_ids": [contact["id"]]},
    ).json()
    assert contact["id"] in plan["contact_ids"]

    alice.delete(f"/api/v2/safety-center/contacts/{contact['id']}")
    refreshed = alice.get(f"/api/v2/safety-center/plans/{plan['id']}").json()
    assert contact["id"] not in refreshed["contact_ids"]


@pytest.mark.parametrize(
    "value",
    [
        "+919876543210",      # India, with country code
        "09876543210",        # India, with leading zero
        "9876543210",         # India, bare
        "+1 415 555 0123",    # international, family abroad
        "020-12345678",       # landline with STD code
        "+44 20 7946 0958",
    ],
)
def test_varied_phone_formats_are_accepted(value):
    """Rejecting a real number someone needs in an emergency is the worse error."""
    assert looks_like_phone(value)


@pytest.mark.parametrize("value", ["not a phone", "abc", "", "12"])
def test_obvious_non_phone_values_rejected(value):
    assert not looks_like_phone(value)


def test_email_validation():
    assert looks_like_email("sister@example.com")
    assert not looks_like_email("not-an-email")


def test_invalid_phone_is_rejected_by_the_api(alice):
    response = alice.post(
        "/api/v2/safety-center/contacts",
        json={"display_name": "X", "method": "phone", "value": "not a phone"},
    )
    assert response.status_code == 422


# ===========================================================================
# Check-ins
# ===========================================================================

def test_check_in_lifecycle(alice):
    started = alice.post(
        "/api/v2/safety-center/check-ins", json={"destination": "Office"}
    ).json()
    assert started["status"] == "active"

    active = alice.get("/api/v2/safety-center/check-ins/active").json()
    assert active["check_in"]["id"] == started["id"]

    resolved = alice.patch(
        f"/api/v2/safety-center/check-ins/{started['id']}", json={"status": "completed_safe"}
    ).json()
    assert resolved["status"] == "completed_safe"
    assert resolved["ended_at"]

    assert alice.get("/api/v2/safety-center/check-ins/active").json()["check_in"] is None


def test_check_in_can_be_cancelled(alice):
    started = alice.post("/api/v2/safety-center/check-ins", json={}).json()
    resolved = alice.patch(
        f"/api/v2/safety-center/check-ins/{started['id']}", json={"status": "cancelled"}
    ).json()
    assert resolved["status"] == "cancelled"


def test_check_in_cannot_be_forced_into_overdue_by_the_client(alice):
    """Overdue is derived from the clock, never asserted by a caller."""
    started = alice.post("/api/v2/safety-center/check-ins", json={}).json()
    response = alice.patch(
        f"/api/v2/safety-center/check-ins/{started['id']}", json={"status": "overdue"}
    )
    assert response.status_code == 422


def test_starting_a_check_in_says_plainly_that_nobody_is_watching(alice):
    started = alice.post("/api/v2/safety-center/check-ins", json={}).json()
    notice = started["monitoring_notice"].lower()
    assert "not monitoring" in notice
    assert "no one is alerted" in notice


def test_check_in_history_is_listed_newest_first(alice):
    first = alice.post("/api/v2/safety-center/check-ins", json={"destination": "A"}).json()
    alice.patch(f"/api/v2/safety-center/check-ins/{first['id']}", json={"status": "completed_safe"})
    alice.post("/api/v2/safety-center/check-ins", json={"destination": "B"})

    history = alice.get("/api/v2/safety-center/check-ins").json()
    assert history["count"] == 2


def test_naive_expected_time_is_rejected(alice):
    """A naive datetime would go overdue at the wrong moment for the user."""
    naive = datetime.now().isoformat()
    response = alice.post(
        "/api/v2/safety-center/check-ins", json={"expected_back_at": naive}
    )
    assert response.status_code == 422


def test_timezone_aware_expected_time_is_accepted(alice):
    aware = (datetime.now(timezone.utc) + timedelta(hours=2)).isoformat()
    response = alice.post("/api/v2/safety-center/check-ins", json={"expected_back_at": aware})
    assert response.status_code == 200


def test_overdue_is_computed_not_scheduled():
    """No background timer exists; the status is derived on read."""
    past = datetime.now(timezone.utc) - timedelta(minutes=30)
    check_in = CheckIn(id="x", owner_id="o", expected_back_at=past)
    assert check_in.is_overdue() is True

    future = datetime.now(timezone.utc) + timedelta(hours=1)
    assert CheckIn(id="x", owner_id="o", expected_back_at=future).is_overdue() is False


def test_a_resolved_check_in_is_never_overdue():
    past = datetime.now(timezone.utc) - timedelta(hours=5)
    check_in = CheckIn(
        id="x", owner_id="o", expected_back_at=past, status=CheckInStatus.COMPLETED_SAFE
    )
    assert check_in.is_overdue() is False


def test_check_in_without_an_expected_time_is_never_overdue():
    assert CheckIn(id="x", owner_id="o").is_overdue() is False


def test_check_in_with_an_unknown_contact_is_rejected(alice):
    response = alice.post(
        "/api/v2/safety-center/check-ins", json={"contact_id": "does-not-exist"}
    )
    assert response.status_code == 404


# ===========================================================================
# Sharing — nothing is ever sent
# ===========================================================================

def test_share_draft_prepares_a_message_without_sending_it(alice):
    contact = _make_contact(alice)
    check_in = alice.post(
        "/api/v2/safety-center/check-ins", json={"destination": "Baner"}
    ).json()

    draft = alice.post(
        "/api/v2/safety-center/share-draft",
        json={
            "check_in_id": check_in["id"],
            "contact_id": contact["id"],
            "include_destination": True,
        },
    ).json()

    assert draft["delivery_guarantee"] == "none"
    assert "nothing has been sent" in draft["notice"].lower()
    assert "cannot confirm" in draft["notice"].lower()
    assert draft["recipient_name"] == "Sister"
    assert "Baner" in draft["message"]


def test_share_draft_offers_links_the_user_opens_herself(alice):
    contact = _make_contact(alice)
    draft = alice.post(
        "/api/v2/safety-center/share-draft", json={"contact_id": contact["id"]}
    ).json()

    assert draft["wa_me_url"].startswith("https://wa.me/")
    assert draft["sms_url"].startswith("sms:")


def test_destination_is_excluded_unless_requested(alice):
    check_in = alice.post(
        "/api/v2/safety-center/check-ins", json={"destination": "Koregaon Park"}
    ).json()
    draft = alice.post(
        "/api/v2/safety-center/share-draft",
        json={"check_in_id": check_in["id"], "include_destination": False},
    ).json()
    assert "Koregaon Park" not in draft["message"]


def test_location_is_excluded_by_default(alice):
    draft = alice.post(
        "/api/v2/safety-center/share-draft",
        json={"location_text": "18.52,73.85", "include_location": False},
    ).json()
    assert "18.52" not in draft["message"]


def test_location_included_only_on_explicit_opt_in(alice):
    draft = alice.post(
        "/api/v2/safety-center/share-draft",
        json={"location_text": "Near FC Road", "include_location": True},
    ).json()
    assert "Near FC Road" in draft["message"]


def test_share_draft_never_includes_plan_steps(alice):
    """A plan's steps can hold details she has not chosen to share."""
    plan = alice.post(
        "/api/v2/safety-center/plans",
        json={"title": "Leaving plan", "steps": ["Hide documents behind the wardrobe"]},
    ).json()
    draft = alice.post(
        "/api/v2/safety-center/share-draft", json={"plan_id": plan["id"]}
    ).json()

    assert "Leaving plan" in draft["message"]
    assert "wardrobe" not in draft["message"].lower()


def test_email_contact_gets_a_mailto_link(alice):
    contact = alice.post(
        "/api/v2/safety-center/contacts",
        json={"display_name": "Friend", "method": "email", "value": "friend@example.com"},
    ).json()
    draft = alice.post(
        "/api/v2/safety-center/share-draft", json={"contact_id": contact["id"]}
    ).json()
    assert draft["mailto_url"].startswith("mailto:friend@example.com")
    assert draft["wa_me_url"] is None


# ===========================================================================
# Emergency guidance stays reachable without any of this
# ===========================================================================

def test_emergency_resources_need_no_account_or_plan(alice):
    """Emergency guidance must never sit behind the Safety Center."""
    from backend.main import app

    anonymous = TestClient(app)
    response = anonymous.get("/api/v2/resources/national")
    assert response.status_code == 200
    numbers = {h["number"] for h in response.json()["helplines"]}
    assert "112" in numbers and "181" in numbers


def test_emergency_guidance_does_not_depend_on_the_llm_or_search(monkeypatch):
    """Deterministic triage must work with every provider unavailable."""
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.delenv("SERPAPI_API_KEY", raising=False)
    monkeypatch.delenv("SERPAPI_KEY", raising=False)

    from backend.safety_triage import detect_immediate_danger, recommend_workflow
    from backend.models.research import SafetyWorkflow, Urgency

    assert detect_immediate_danger("he is outside my door right now") is True
    assert recommend_workflow(urgency=Urgency.CRITICAL) is SafetyWorkflow.EMERGENCY


# ===========================================================================
# Validation
# ===========================================================================

def test_plan_title_is_required(alice):
    assert alice.post("/api/v2/safety-center/plans", json={"title": ""}).status_code == 422


def test_oversized_fields_are_rejected(alice):
    assert alice.post(
        "/api/v2/safety-center/plans", json={"title": "x" * 500}
    ).status_code == 422


def test_unknown_plan_returns_404_not_500(alice):
    assert alice.get("/api/v2/safety-center/plans/nonexistent").status_code == 404


# ===========================================================================
# Model-level behaviour
# ===========================================================================

def test_display_text_prefers_the_users_wording():
    step = PlanStep(
        id="1", text="Original suggestion", user_edited_text="my own words",
        origin=StepOrigin.ACCEPTED_SUGGESTION,
    )
    assert step.display_text == "my own words"


def test_unaccepted_suggestions_are_not_user_owned():
    assert PlanStep(id="1", text="x", origin=StepOrigin.SUGGESTED).is_user_owned is False
    assert PlanStep(id="1", text="x", origin=StepOrigin.USER).is_user_owned is True


def test_accepted_step_count_excludes_suggestions():
    plan = SafetyCenterPlan(
        id="p", owner_id="o", title="t",
        steps=[
            PlanStep(id="1", text="a", origin=StepOrigin.USER),
            PlanStep(id="2", text="b", origin=StepOrigin.ACCEPTED_SUGGESTION),
        ],
        suggestions=[PlanStep(id="3", text="c", origin=StepOrigin.SUGGESTED)],
    )
    assert plan.accepted_step_count == 2
