"""
Deterministic safety triage.

Why this is not an LLM call
---------------------------
Gemini's free tier is ~20 requests a day and is currently exhausted; a model can
also be rate-limited, slow or retired at any moment (two model retirements have
already broken this app). A woman typing "he is outside my door right now" must
reach emergency guidance **regardless of whether any model is reachable**.

So the triage below is pure Python: regex over the user's own words, plus a
lookup from category and urgency to a workflow. It is cheap, instant, offline
and unit-testable. The LLM still produces the rich ``Situation``; this module
decides routing and can only ever *raise* the urgency the model assigned, never
lower it.

Conservatism
------------
The asymmetry is deliberate. Treating a safe situation as urgent costs the user
a visible helpline she can ignore. Treating a dangerous situation as routine
costs something that cannot be undone. Where the two are in tension, this module
escalates.

It does **not** infer facts the user did not state. Detecting the phrase "he has
a knife" marks danger; it does not add "the abuser is armed" to ``known_facts``.
"""

from __future__ import annotations

import re
from typing import List, Optional, Tuple

from backend.models.research import (
    SafetyWorkflow,
    SituationCategory,
    SituationIntent,
    Urgency,
    WOMEN_SAFETY_CATEGORY_VALUES,
)

# ---------------------------------------------------------------------------
# Immediate-danger signals
# ---------------------------------------------------------------------------
# Phrases that indicate danger happening NOW or within minutes. Kept narrow on
# purpose: this set triggers the emergency interface, and firing it on ordinary
# past-tense disclosure would make the interface meaningless through repetition.
#
# Word-boundary anchored, because substring matching previously produced
# false positives elsewhere in this codebase ("icc" inside "hiccups").
_IMMEDIATE_DANGER_PATTERNS: List[str] = [
    # Happening right now
    r"right now\b.{0,40}\b(hit|hurt|beat|attack|hitting|beating|attacking|follow)",
    # The subject may be a pronoun ("he is hitting me") or a noun phrase
    # ("my husband is hitting me", "the landlord is attacking me"). Requiring a
    # pronoun missed the most common way this is actually written.
    r"\b(?:he|she|they|someone|my\s+\w+|the\s+\w+)\s+(?:is|was|keeps)\s+"
    r"(?:hitting|beating|attacking|choking|strangling|hurting|assaulting)\s+me",
    r"\bis\s+(outside|at)\s+(my|the)\s+(door|house|home|flat|gate|window)",
    r"\b(breaking|broke)\s+(in|into)\b",
    r"\btrying to (break|get) in\b",
    r"\bbanging on (the|my) door\b",
    r"\bfollowing me (right )?now\b",
    r"\b(he|she|they)('s| is) following me\b",
    r"\bi('m| am) being followed\b",
    r"\blocked me (in|inside|up)\b",
    r"\bwon'?t let me (leave|go|out)\b",
    r"\bnot letting me (leave|go|out)\b",
    # Weapons and lethality
    r"\b(knife|gun|weapon|acid|petrol|kerosene|blade)\b",
    r"\bthreatening to kill\b",
    r"\b(going|about) to kill me\b",
    r"\bkill me\b",
    r"\bstrangl(e|ed|ing)\b",
    r"\bchok(e|ed|ing) me\b",
    r"\bcan'?t breathe\b",
    # Immediate flight
    r"\bi need to (leave|get out|escape) (now|tonight|immediately|right now)\b",
    r"\bhelp me (now|please now)\b",
    r"\bi('m| am) (hiding|locked) in\b",
    r"\bin danger (right )?now\b",
    # Self-harm and medical emergency
    r"\bkill myself\b",
    r"\bend my life\b",
    r"\bsuicid(e|al)\b",
    r"\bbleeding\b",
    r"\bunconscious\b",
]

_IMMEDIATE_DANGER_RE = re.compile(
    r"(?:" + "|".join(_IMMEDIATE_DANGER_PATTERNS) + r")", re.IGNORECASE
)

#: Signals that danger is escalating but may not be this minute. These raise
#: urgency to HIGH rather than triggering the emergency interface.
_ESCALATION_PATTERNS: List[str] = [
    r"\bgetting worse\b",
    r"\bescalat(ed|ing)\b",
    r"\bfirst time he('s| has)? (hit|hurt)\b",
    r"\bthreatened (me|to)\b",
    r"\bafraid (he|she|they) will\b",
    r"\bscared (he|she|they) will\b",
    r"\bwhat if he (finds|comes|kills)\b",
    r"\bfound out\b.{0,30}\b(leaving|police|complaint)\b",
    r"\bbail\b",
    r"\breleased from (jail|custody)\b",
]

_ESCALATION_RE = re.compile(
    r"(?:" + "|".join(_ESCALATION_PATTERNS) + r")", re.IGNORECASE
)


def detect_immediate_danger(text: str) -> bool:
    """Whether ``text`` contains a signal of danger happening now.

    Conservative by design: a positive result shows emergency numbers, which is
    a cheap mistake to make.
    """
    return bool(text) and bool(_IMMEDIATE_DANGER_RE.search(text))


def matched_danger_signals(text: str) -> List[str]:
    """The user's own matched phrases, for display and for tests.

    Returns quoted fragments of what the user actually wrote — never an
    inference about their circumstances.
    """
    if not text:
        return []
    return [m.group(0).strip() for m in _IMMEDIATE_DANGER_RE.finditer(text)]


def detect_escalation(text: str) -> bool:
    """Whether ``text`` suggests the situation is worsening."""
    return bool(text) and bool(_ESCALATION_RE.search(text))


def is_women_safety_category(category: object) -> bool:
    """Whether ``category`` is a women's-safety concern."""
    value = getattr(category, "value", category)
    return str(value or "").lower().strip() in WOMEN_SAFETY_CATEGORY_VALUES


def assess_urgency(
    text: str,
    model_urgency: Optional[Urgency] = None,
    category: object = None,
) -> Tuple[Urgency, List[str]]:
    """Return the urgency to act on, plus the signals that justified it.

    The model's assessment is the starting point. This function may only raise
    it — if the model says ``LOW`` but the text says "he is breaking in", the
    answer is ``CRITICAL``. It never lowers a model's assessment, because the
    model has context this regex does not.
    """
    signals = matched_danger_signals(text)
    urgency = model_urgency or Urgency.MEDIUM

    if signals:
        return Urgency.CRITICAL, signals

    if detect_escalation(text):
        escalated = Urgency.HIGH
        return (escalated if _rank(escalated) > _rank(urgency) else urgency), []

    # An explicit immediate-danger category counts even without a phrase match.
    if getattr(category, "value", category) == SituationCategory.IMMEDIATE_DANGER.value:
        return Urgency.CRITICAL, []

    return urgency, []


_URGENCY_ORDER = {
    Urgency.LOW: 0,
    Urgency.MEDIUM: 1,
    Urgency.HIGH: 2,
    Urgency.CRITICAL: 3,
}


def _rank(urgency: Urgency) -> int:
    return _URGENCY_ORDER.get(urgency, 1)


# ---------------------------------------------------------------------------
# Workflow routing
# ---------------------------------------------------------------------------

#: Category → workflow for everything that is not urgency-driven.
_CATEGORY_WORKFLOW = {
    SituationCategory.IMMEDIATE_DANGER: SafetyWorkflow.EMERGENCY,
    SituationCategory.DOMESTIC_VIOLENCE: SafetyWorkflow.SAFETY_PLAN,
    SituationCategory.UNSAFE_RELATIONSHIP: SafetyWorkflow.SAFETY_PLAN,
    SituationCategory.COERCIVE_CONTROL: SafetyWorkflow.SAFETY_PLAN,
    SituationCategory.STALKING: SafetyWorkflow.SAFETY_PLAN,
    SituationCategory.THREATS: SafetyWorkflow.SAFETY_PLAN,
    SituationCategory.SAFETY_PLANNING: SafetyWorkflow.SAFETY_PLAN,
    SituationCategory.UNSAFE_TRAVEL: SafetyWorkflow.SAFETY_PLAN,
    SituationCategory.STREET_HARASSMENT: SafetyWorkflow.SAFETY_PLAN,
    SituationCategory.SEXUAL_HARASSMENT: SafetyWorkflow.LEGAL_INFO,
    SituationCategory.WORKPLACE_HARASSMENT: SafetyWorkflow.LEGAL_INFO,
    SituationCategory.CAMPUS_SAFETY: SafetyWorkflow.LEGAL_INFO,
    SituationCategory.ONLINE_HARASSMENT: SafetyWorkflow.LEGAL_INFO,
    SituationCategory.LEGAL_INFORMATION: SafetyWorkflow.LEGAL_INFO,
    SituationCategory.EMOTIONAL_DISTRESS: SafetyWorkflow.EMOTIONAL_SUPPORT,
    SituationCategory.LOCAL_DISCOVERY: SafetyWorkflow.LOCAL_RESOURCES,
}

#: Intent overrides category when the user has told us what they want.
_INTENT_WORKFLOW = {
    SituationIntent.GET_TO_SAFETY: SafetyWorkflow.EMERGENCY,
    SituationIntent.EMOTIONAL_SUPPORT: SafetyWorkflow.EMOTIONAL_SUPPORT,
    SituationIntent.FIND_LOCAL_HELP: SafetyWorkflow.LOCAL_RESOURCES,
    SituationIntent.UNDERSTAND_OPTIONS: SafetyWorkflow.LEGAL_INFO,
    SituationIntent.PLAN_AHEAD: SafetyWorkflow.SAFETY_PLAN,
}


def recommend_workflow(
    category: object = None,
    urgency: Optional[Urgency] = None,
    intent: Optional[SituationIntent] = None,
) -> SafetyWorkflow:
    """Pick the surface that should handle this situation.

    Order of precedence:

    1. **Critical urgency wins outright.** Whatever the category says, someone
       in danger gets the emergency surface.
    2. Explicit ``GET_TO_SAFETY`` intent, for the same reason.
    3. Category mapping.
    4. Remaining intent mapping.
    5. General research.
    """
    if urgency == Urgency.CRITICAL:
        return SafetyWorkflow.EMERGENCY

    if intent == SituationIntent.GET_TO_SAFETY:
        return SafetyWorkflow.EMERGENCY

    if category is not None:
        try:
            resolved = SituationCategory(getattr(category, "value", category))
        except ValueError:
            resolved = None
        if resolved is not None and resolved in _CATEGORY_WORKFLOW:
            return _CATEGORY_WORKFLOW[resolved]

    if intent is not None and intent in _INTENT_WORKFLOW:
        return _INTENT_WORKFLOW[intent]

    return SafetyWorkflow.GENERAL_RESEARCH


def triage(situation) -> Tuple[Urgency, SafetyWorkflow, List[str]]:
    """Apply triage to a ``Situation``, returning what to act on.

    Reads the user's own narrative fields rather than the full raw text, so a
    caller does not have to keep the original message around. Returns
    ``(urgency, workflow, danger_signals)`` and mutates nothing.
    """
    narrative = " ".join(
        part
        for part in (
            situation.case_summary or "",
            " ".join(situation.known_facts or []),
            " ".join(situation.immediate_danger_signals or []),
        )
        if part
    )

    urgency, signals = assess_urgency(
        narrative, getattr(situation, "urgency", None), getattr(situation, "category", None)
    )
    workflow = recommend_workflow(
        category=getattr(situation, "category", None),
        urgency=urgency,
        intent=getattr(situation, "intent", None),
    )
    return urgency, workflow, signals


def apply_triage(situation):
    """Return ``situation`` with conservative urgency and a routed workflow.

    Mutates and returns the same object so callers can use it inline. Urgency is
    only ever raised; ``recommended_workflow`` is set if not already present.
    """
    urgency, workflow, signals = triage(situation)
    situation.urgency = urgency
    situation.recommended_workflow = workflow
    if signals and not situation.immediate_danger_signals:
        situation.immediate_danger_signals = signals
    return situation


def apply_triage_to_text(situation, raw_text: str):
    """Like :func:`apply_triage`, but also scans the user's original message.

    Preferred where the raw text is still available. A model's ``case_summary``
    is a paraphrase, and paraphrase is exactly where an urgent detail gets
    smoothed away — "he's outside with a knife" can become "the user reports
    feeling unsafe at home".
    """
    urgency, signals = assess_urgency(
        raw_text or "",
        getattr(situation, "urgency", None),
        getattr(situation, "category", None),
    )

    # Fall back to the structured fields when the raw text yields nothing, so
    # this is never weaker than apply_triage.
    if not signals:
        fallback_urgency, fallback_workflow, fallback_signals = triage(situation)
        if _rank(fallback_urgency) > _rank(urgency):
            urgency = fallback_urgency
        signals = fallback_signals

    situation.urgency = urgency
    situation.recommended_workflow = recommend_workflow(
        category=getattr(situation, "category", None),
        urgency=urgency,
        intent=getattr(situation, "intent", None),
    )
    if signals and not situation.immediate_danger_signals:
        situation.immediate_danger_signals = signals
    return situation
