"""
Tests for deterministic women-safety triage (``backend.safety_triage``).

No LLM is involved here, by design: this is the layer that must keep working
when Gemini is rate-limited, retired or slow. Every test runs offline.

The central property under test is **conservatism**. Triage may raise the
urgency a model assigned; it must never lower it.
"""

from __future__ import annotations

import pytest

from backend.models.research import (
    SafetyWorkflow,
    Situation,
    SituationCategory,
    SituationIntent,
    Urgency,
)
from backend.safety_triage import (
    apply_triage,
    apply_triage_to_text,
    assess_urgency,
    detect_escalation,
    detect_immediate_danger,
    is_women_safety_category,
    matched_danger_signals,
    recommend_workflow,
    triage,
)


def _situation(**overrides) -> Situation:
    base = dict(
        case_summary="A user describes a difficult situation.",
        user_goal="Understand what to do next",
    )
    base.update(overrides)
    return Situation(**base)


# ---------------------------------------------------------------------------
# Immediate danger detection
# ---------------------------------------------------------------------------

@pytest.mark.parametrize(
    "text",
    [
        "he is outside my door right now",
        "He is outside the house and banging on the door",
        "my husband is hitting me",
        "he's following me right now",
        "I am being followed",
        "he has a knife",
        "he threatened to kill me",
        "he is choking me",
        "he won't let me leave the house",
        "he locked me in the bedroom",
        "someone is trying to break in",
        "I need to leave now",
        "I'm hiding in the bathroom",
        "I am in danger right now",
        "I want to kill myself",
        "I am bleeding",
    ],
)
def test_immediate_danger_detected(text):
    assert detect_immediate_danger(text), f"should have flagged: {text!r}"


@pytest.mark.parametrize(
    "text",
    [
        "",
        "My manager keeps making sexual comments at work in Pune.",
        "I want to understand the POSH Act complaint process.",
        "What is a One Stop Centre and where is the nearest one?",
        "I would like to know my rights under PWDVA 2005.",
        "I am looking for a women's hostel in Nagpur.",
        "Can you help me write a complaint letter?",
        "I feel low today and wanted to talk to someone.",
        "My neighbour plays loud music at night.",
        "I had hiccups all morning.",
        "I want to plan a safe route home from college.",
    ],
)
def test_no_false_immediate_danger(text):
    """Firing on ordinary disclosure would make the emergency surface noise."""
    assert not detect_immediate_danger(text), f"false positive on: {text!r}"


def test_matched_signals_quote_the_user():
    signals = matched_danger_signals("he has a knife and he is outside my door")
    assert signals, "expected at least one quoted signal"
    joined = " ".join(signals).lower()
    assert "knife" in joined


def test_matched_signals_do_not_infer_beyond_the_text():
    """Triage reports phrases, never conclusions about the user's life."""
    signals = matched_danger_signals("he has a knife")
    assert all(s.lower() in "he has a knife" for s in signals)


# ---------------------------------------------------------------------------
# Escalation (worsening, but not this minute)
# ---------------------------------------------------------------------------

@pytest.mark.parametrize(
    "text",
    [
        "things are getting worse at home",
        "this is the first time he hit me",
        "he threatened me last week",
        "I am scared he will find out",
        "he was released from custody yesterday",
    ],
)
def test_escalation_detected(text):
    assert detect_escalation(text)


def test_escalation_raises_to_high_not_critical():
    urgency, signals = assess_urgency("things are getting worse at home", Urgency.LOW)
    assert urgency == Urgency.HIGH
    assert signals == [], "escalation is not an immediate-danger signal"


# ---------------------------------------------------------------------------
# Conservatism — the core guarantee
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("model_urgency", list(Urgency))
def test_immediate_danger_always_yields_critical(model_urgency):
    """Whatever the model thought, 'he is breaking in' is critical."""
    urgency, signals = assess_urgency("someone is trying to break in", model_urgency)
    assert urgency == Urgency.CRITICAL
    assert signals


def test_triage_never_lowers_model_urgency():
    """The model sees context a regex cannot; its judgement is a floor."""
    for model_urgency in Urgency:
        urgency, _ = assess_urgency("I want to understand my options", model_urgency)
        assert urgency == model_urgency, (
            f"triage downgraded {model_urgency} to {urgency}"
        )


def test_immediate_danger_category_is_critical_without_phrase_match():
    urgency, _ = assess_urgency(
        "please help", Urgency.LOW, SituationCategory.IMMEDIATE_DANGER
    )
    assert urgency == Urgency.CRITICAL


def test_ambiguous_text_is_resolved_upward():
    """'Plausible but uncertain' must land on the safety interface."""
    situation = _situation(
        case_summary="She says he gets angry and she is afraid he will hurt her.",
        category=SituationCategory.UNSAFE_RELATIONSHIP,
        urgency=Urgency.LOW,
    )
    urgency, workflow, _ = triage(situation)
    assert urgency in (Urgency.HIGH, Urgency.CRITICAL)
    assert workflow in (SafetyWorkflow.EMERGENCY, SafetyWorkflow.SAFETY_PLAN)


# ---------------------------------------------------------------------------
# Workflow routing — every category in the brief must route somewhere sensible
# ---------------------------------------------------------------------------

@pytest.mark.parametrize(
    "category,expected",
    [
        (SituationCategory.IMMEDIATE_DANGER, SafetyWorkflow.EMERGENCY),
        (SituationCategory.STREET_HARASSMENT, SafetyWorkflow.SAFETY_PLAN),
        (SituationCategory.STALKING, SafetyWorkflow.SAFETY_PLAN),
        (SituationCategory.UNSAFE_TRAVEL, SafetyWorkflow.SAFETY_PLAN),
        (SituationCategory.WORKPLACE_HARASSMENT, SafetyWorkflow.LEGAL_INFO),
        (SituationCategory.CAMPUS_SAFETY, SafetyWorkflow.LEGAL_INFO),
        (SituationCategory.ONLINE_HARASSMENT, SafetyWorkflow.LEGAL_INFO),
        (SituationCategory.THREATS, SafetyWorkflow.SAFETY_PLAN),
        (SituationCategory.COERCIVE_CONTROL, SafetyWorkflow.SAFETY_PLAN),
        (SituationCategory.UNSAFE_RELATIONSHIP, SafetyWorkflow.SAFETY_PLAN),
        (SituationCategory.LEGAL_INFORMATION, SafetyWorkflow.LEGAL_INFO),
        (SituationCategory.EMOTIONAL_DISTRESS, SafetyWorkflow.EMOTIONAL_SUPPORT),
        (SituationCategory.SAFETY_PLANNING, SafetyWorkflow.SAFETY_PLAN),
        (SituationCategory.LOCAL_DISCOVERY, SafetyWorkflow.LOCAL_RESOURCES),
        (SituationCategory.DOMESTIC_VIOLENCE, SafetyWorkflow.SAFETY_PLAN),
    ],
)
def test_every_brief_category_routes(category, expected):
    assert recommend_workflow(category=category, urgency=Urgency.MEDIUM) == expected


def test_critical_urgency_overrides_every_category():
    for category in SituationCategory:
        assert (
            recommend_workflow(category=category, urgency=Urgency.CRITICAL)
            is SafetyWorkflow.EMERGENCY
        ), f"{category} must still route to emergency when critical"


def test_get_to_safety_intent_overrides_category():
    assert (
        recommend_workflow(
            category=SituationCategory.CONSUMER,
            urgency=Urgency.LOW,
            intent=SituationIntent.GET_TO_SAFETY,
        )
        is SafetyWorkflow.EMERGENCY
    )


def test_unknown_category_falls_back_to_general_research():
    assert recommend_workflow(category="not_a_real_category") is SafetyWorkflow.GENERAL_RESEARCH


def test_everyday_request_stays_on_the_ordinary_path():
    """A non-safety question must not be dragged into the emergency surface."""
    workflow = recommend_workflow(
        category=SituationCategory.CONSUMER, urgency=Urgency.LOW
    )
    assert workflow is SafetyWorkflow.GENERAL_RESEARCH


# ---------------------------------------------------------------------------
# Category helpers
# ---------------------------------------------------------------------------

def test_women_safety_categories_recognised():
    for category in (
        SituationCategory.DOMESTIC_VIOLENCE,
        SituationCategory.STREET_HARASSMENT,
        SituationCategory.IMMEDIATE_DANGER,
        SituationCategory.CAMPUS_SAFETY,
    ):
        assert is_women_safety_category(category)


def test_non_safety_categories_not_misclassified():
    for category in (SituationCategory.CONSUMER, SituationCategory.HOUSING):
        assert not is_women_safety_category(category)


# ---------------------------------------------------------------------------
# apply_triage / apply_triage_to_text
# ---------------------------------------------------------------------------

def test_apply_triage_sets_workflow_and_urgency():
    situation = _situation(
        case_summary="He is outside my door right now.",
        category=SituationCategory.DOMESTIC_VIOLENCE,
        urgency=Urgency.LOW,
    )
    apply_triage(situation)
    assert situation.urgency is Urgency.CRITICAL
    assert situation.recommended_workflow is SafetyWorkflow.EMERGENCY
    assert situation.immediate_danger_signals


def test_raw_text_catches_what_a_summary_smoothed_away():
    """The model's paraphrase is where urgent detail gets lost."""
    situation = _situation(
        case_summary="The user reports feeling unsafe at home.",
        category=SituationCategory.DOMESTIC_VIOLENCE,
        urgency=Urgency.MEDIUM,
    )
    # Nothing in the summary alone is an immediate-danger signal.
    assert not detect_immediate_danger(situation.case_summary)

    apply_triage_to_text(situation, "he is outside my door with a knife")
    assert situation.urgency is Urgency.CRITICAL
    assert situation.recommended_workflow is SafetyWorkflow.EMERGENCY


def test_apply_triage_to_text_is_never_weaker_than_apply_triage():
    situation = _situation(
        case_summary="He threatened to kill me last night.",
        category=SituationCategory.DOMESTIC_VIOLENCE,
        urgency=Urgency.LOW,
    )
    apply_triage_to_text(situation, "hi")
    assert situation.urgency is Urgency.CRITICAL


def test_apply_triage_does_not_invent_constraints_or_facts():
    situation = _situation(
        case_summary="He has a knife.",
        category=SituationCategory.DOMESTIC_VIOLENCE,
    )
    apply_triage(situation)
    assert situation.constraints == [], "triage must not infer constraints"
    assert situation.known_facts == [], "triage must not add facts"


# ---------------------------------------------------------------------------
# Backward compatibility of the Situation schema
# ---------------------------------------------------------------------------

def test_situation_still_validates_without_the_new_fields():
    """A Situation persisted before Phase 2 must still load."""
    legacy = {
        "case_summary": "Pre-existing stored case.",
        "user_goal": "Get a refund",
        "category": "consumer",
        "urgency": "medium",
    }
    situation = Situation.model_validate(legacy)
    assert situation.intent is SituationIntent.OTHER
    assert situation.constraints == []
    assert situation.recommended_workflow is None
    assert situation.immediate_danger_signals == []


def test_all_pre_phase2_category_values_still_valid():
    for value in [
        "consumer", "housing", "employment", "education", "financial", "travel",
        "cyber", "legal_information", "government_service", "safety",
        "health_information", "domestic_violence", "sexual_harassment",
        "stalking", "online_harassment", "threats", "coercive_control",
        "unsafe_relationship", "workplace_harassment", "other_women_safety",
        "other",
    ]:
        assert SituationCategory(value).value == value
