"""
Structured action workflow tests (Phase 4, Task 2).

All offline and deterministic — which is the property under test. The emergency
path must produce concrete steps with no LLM, no search and no database.
"""

from __future__ import annotations

import pytest

from backend.models.research import SafetyWorkflow, Urgency
from backend.services.action_workflow import (
    MAX_DO_NOW,
    ActionWorkflow,
    StepSource,
    WorkflowStep,
    build_workflow,
    emergency_fallback,
    from_action_plan,
    strip_confrontation,
    suggests_confrontation,
)


# ---------------------------------------------------------------------------
# Confrontation filter — the hardest safety rule in the product
# ---------------------------------------------------------------------------

@pytest.mark.parametrize(
    "text",
    [
        "Confront him about the messages",
        "Tell him you know what he did",
        "Ask her to stop directly",
        "Stand up to them",
        "Warn him that you will report this",
        "Demand an apology from him",
        "Face them and explain how you feel",
        "Threaten to expose him",
    ],
)
def test_confrontation_is_detected(text):
    assert suggests_confrontation(text)


@pytest.mark.parametrize(
    "text",
    [
        "Call 112 if you feel unsafe",
        "Keep copies of the messages somewhere safe",
        "Contact the One Stop Centre in your district",
        "Tell a friend where you are going",
        "File a complaint with the Internal Committee",
    ],
)
def test_safe_guidance_is_not_flagged(text):
    assert not suggests_confrontation(text)


def test_confrontation_steps_are_removed_whatever_their_source():
    steps = [
        WorkflowStep("Confront him about it", StepSource.RESEARCH),
        WorkflowStep("Call 181 for support", StepSource.DETERMINISTIC),
        WorkflowStep("Tell him you know", StepSource.GENERATED),
    ]
    kept = strip_confrontation(steps)
    assert len(kept) == 1
    assert "181" in kept[0].text


def test_build_workflow_never_emits_confrontation():
    workflow = build_workflow(
        suggested_steps=[WorkflowStep("Confront your manager", StepSource.GENERATED)]
    )
    all_text = " ".join(
        s.text for s in workflow.do_now + workflow.next_steps + workflow.alternatives
    )
    assert not suggests_confrontation(all_text)


# ---------------------------------------------------------------------------
# Emergency path — must work with everything down
# ---------------------------------------------------------------------------

def test_emergency_fallback_needs_no_provider(monkeypatch):
    """Strip every credential; the guidance must still be concrete."""
    for key in ("GEMINI_API_KEY", "SERPAPI_API_KEY", "SERPAPI_KEY", "MONGODB_URI"):
        monkeypatch.delenv(key, raising=False)

    workflow = emergency_fallback()
    assert workflow.do_now, "emergency guidance must never be empty"
    text = " ".join(s.text for s in workflow.do_now)
    assert "112" in text


def test_emergency_includes_the_women_helpline():
    text = " ".join(
        s.text for s in emergency_fallback().do_now + emergency_fallback().alternatives
    )
    assert "181" in text


def test_emergency_steps_are_marked_deterministic():
    assert all(s.source is StepSource.DETERMINISTIC for s in emergency_fallback().do_now)


def test_emergency_makes_no_promise_about_response_time():
    workflow = emergency_fallback()
    blob = " ".join(
        [s.text for s in workflow.do_now + workflow.alternatives] + workflow.limitations
    ).lower()
    for promise in ("will arrive", "within minutes", "immediately dispatch", "guarantee"):
        assert promise not in blob


def test_emergency_states_that_herway_cannot_contact_anyone():
    limitations = " ".join(emergency_fallback().limitations).lower()
    assert "cannot call anyone for you" in limitations
    assert "cannot tell anyone where you are" in limitations


def test_emergency_contains_no_confrontation_advice():
    workflow = emergency_fallback()
    blob = " ".join(
        s.text for s in workflow.do_now + workflow.alternatives + workflow.share
    )
    assert not suggests_confrontation(blob)


def test_critical_urgency_routes_to_emergency_regardless_of_suggestions():
    workflow = build_workflow(
        urgency=Urgency.CRITICAL,
        suggested_steps=[WorkflowStep("Read about your rights", StepSource.GENERATED)],
    )
    assert "112" in " ".join(s.text for s in workflow.do_now)


def test_emergency_workflow_type_also_routes_to_emergency():
    workflow = build_workflow(workflow_type=SafetyWorkflow.EMERGENCY)
    assert "112" in " ".join(s.text for s in workflow.do_now)


def test_research_steps_are_appended_after_emergency_guidance():
    """Getting safe comes first; useful detail follows."""
    workflow = build_workflow(
        urgency=Urgency.CRITICAL,
        suggested_steps=[
            WorkflowStep("One Stop Centre address", StepSource.RESEARCH, ["https://wcd.nic.in"])
        ],
    )
    # The first step is getting to a populated place; 112 follows immediately.
    # What matters is that emergency guidance occupies `do_now` entirely and the
    # research step is pushed to `next`.
    assert "112" in " ".join(s.text for s in workflow.do_now)
    assert all(s.source is StepSource.DETERMINISTIC for s in workflow.do_now)
    assert any("One Stop Centre" in s.text for s in workflow.next_steps)


# ---------------------------------------------------------------------------
# Proportionality
# ---------------------------------------------------------------------------

def test_a_simple_question_does_not_produce_a_programme():
    workflow = build_workflow(
        suggested_steps=[WorkflowStep("Check the portal", StepSource.RESEARCH)]
    )
    assert len(workflow.do_now) == 1
    assert workflow.next_steps == []


def test_do_now_is_capped():
    steps = [WorkflowStep(f"Step {i}", StepSource.GENERATED) for i in range(20)]
    workflow = build_workflow(suggested_steps=steps)
    assert len(workflow.do_now) <= MAX_DO_NOW


def test_research_backed_steps_are_surfaced_first():
    workflow = build_workflow(
        suggested_steps=[
            WorkflowStep("A guess", StepSource.GENERATED),
            WorkflowStep("From an official source", StepSource.RESEARCH, ["https://x.gov.in"]),
        ]
    )
    assert workflow.do_now[0].source is StepSource.RESEARCH


# ---------------------------------------------------------------------------
# Provenance and honesty
# ---------------------------------------------------------------------------

def test_generated_steps_are_labelled_as_suggestions():
    workflow = build_workflow(
        suggested_steps=[WorkflowStep("Something generated", StepSource.GENERATED)]
    )
    assert any("suggestions rather than information" in lim for lim in workflow.limitations)


def test_research_steps_keep_their_urls():
    workflow = build_workflow(
        suggested_steps=[
            WorkflowStep("Official procedure", StepSource.RESEARCH, ["https://indiacode.nic.in/x"])
        ]
    )
    assert workflow.do_now[0].source_urls == ["https://indiacode.nic.in/x"]
    assert workflow.do_now[0].to_dict()["is_verified_fact"] is True


def test_generated_steps_are_not_marked_as_verified():
    step = WorkflowStep("A suggestion", StepSource.GENERATED)
    assert step.to_dict()["is_verified_fact"] is False


def test_workflow_disclaims_professional_representation():
    payload = build_workflow().to_dict()
    assert "not legal, medical or psychological advice" in payload["not_professional_advice"]
    assert "not representing you" in payload["not_professional_advice"]


# ---------------------------------------------------------------------------
# Reporting is never mandatory
# ---------------------------------------------------------------------------

def test_no_step_is_mandatory_except_immediate_safety():
    """Only getting to safety is non-optional. Reporting never is."""
    workflow = emergency_fallback()
    mandatory = [s for s in workflow.do_now if not s.optional]
    assert mandatory, "immediate safety steps should be non-optional"
    for step in mandatory:
        assert "police station" not in step.text.lower() or "112" in step.text


def test_formal_reporting_is_not_forced_in_a_normal_workflow():
    workflow = build_workflow(
        suggested_steps=[WorkflowStep("File a police complaint", StepSource.RESEARCH)]
    )
    assert all(s.optional for s in workflow.do_now)


# ---------------------------------------------------------------------------
# Clarification
# ---------------------------------------------------------------------------

def test_clarification_is_carried_when_supplied():
    workflow = build_workflow(needs_clarification="Which city are you in?")
    assert workflow.to_dict()["needs_clarification"] == "Which city are you in?"


def test_no_clarification_by_default():
    assert build_workflow().to_dict()["needs_clarification"] is None


# ---------------------------------------------------------------------------
# Bucketing an existing ActionPlan
# ---------------------------------------------------------------------------

def test_from_action_plan_marks_evidence_backed_items_as_research():
    class Item:
        def __init__(self, title, evidence_ids=None, source_urls=None):
            self.title = title
            self.evidence_ids = evidence_ids or []
            self.source_urls = source_urls or []

    class Plan:
        actions = [
            Item("Backed by evidence", evidence_ids=["EVIDENCE_01"]),
            Item("No evidence"),
        ]

    workflow = from_action_plan(Plan())
    sources = {s.text: s.source for s in workflow.do_now}
    assert sources["Backed by evidence"] is StepSource.RESEARCH
    assert sources["No evidence"] is StepSource.GENERATED


def test_from_action_plan_tolerates_an_unexpected_shape():
    class Empty:
        pass

    assert from_action_plan(Empty()).is_empty


def test_empty_workflow_is_detectable():
    assert ActionWorkflow().is_empty is True
    assert build_workflow(suggested_steps=[WorkflowStep("x")]).is_empty is False
