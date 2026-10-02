"""
Safety Center models — user-owned plans, trusted contacts and check-ins.

Relationship to the existing ``SafetyPlan``
------------------------------------------
``backend/models/safety_plan.py`` already defines ``SafetyPlan``: the
AI-generated crisis plan, embedded inside a ``Case`` document, phased into
"right now / next 24h / document if safe / support network / formal options".
That model is **not replaced and not modified**. It keeps working exactly as it
did, and ``safety_plan_agent`` keeps producing it.

What this module adds is a different object with a different owner and
lifetime: a plan the *user* writes and keeps. It belongs to a person rather
than an incident, survives beyond any one case, and can hold several plans at
once ("getting home late", "when he is released"). It can reference a case and
an AI-generated ``SafetyPlan``, but it does not copy their contents.

The distinction that drives the schema
--------------------------------------
``PlanStep.origin`` separates what HerWay suggested from what the user actually
accepted. A plan is the user's; an AI suggestion sitting in it unreviewed is
not the same as a step she decided on, and the interface must be able to tell
them apart. ``user_edited_text`` preserves her wording when she rewrites a
suggestion, because the phrasing someone chooses for their own safety plan
matters.

Privacy posture
---------------
These records hold the most sensitive data in the product: who a woman trusts,
where she is going, and what she plans to do if something goes wrong. So:

- Everything is scoped to one owner and never surfaces on a community endpoint.
- Contact details are not logged (see the route handlers).
- Location is optional, free-text, and never collected automatically.
- ``model_dump`` is the only serialisation path; there is no "share everything"
  helper that could be called by accident.
"""

from __future__ import annotations

import re
from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field, field_validator


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------

class PlanStatus(str, Enum):
    ACTIVE = "active"
    PAUSED = "paused"
    ARCHIVED = "archived"


class StepOrigin(str, Enum):
    """Where a step came from. The honesty boundary of this model."""

    #: The user wrote it.
    USER = "user"
    #: HerWay suggested it and the user explicitly accepted it.
    ACCEPTED_SUGGESTION = "accepted_suggestion"
    #: HerWay suggested it and the user has not decided yet. Not part of the
    #: plan proper — shown separately, never counted as the user's own step.
    SUGGESTED = "suggested"


class StepStatus(str, Enum):
    TODO = "todo"
    DONE = "done"
    NOT_APPLICABLE = "not_applicable"


class CheckInStatus(str, Enum):
    ACTIVE = "active"
    #: The user confirmed they are safe.
    COMPLETED_SAFE = "completed_safe"
    CANCELLED = "cancelled"
    #: The expected time passed with no confirmation. This is a *status*, not
    #: an alert: nothing was sent to anyone. See the route documentation.
    OVERDUE = "overdue"


class ContactMethod(str, Enum):
    PHONE = "phone"
    EMAIL = "email"
    OTHER = "other"


# ---------------------------------------------------------------------------
# Validation helpers
# ---------------------------------------------------------------------------

#: Deliberately permissive. Indian numbers appear as +91XXXXXXXXXX, 0XXXXXXXXXX,
#: with spaces or hyphens, and a landline has an STD code of varying length.
#: Users also save international numbers for family abroad. Rejecting a real
#: number someone needs in an emergency is far worse than storing an odd one,
#: so this checks shape, not conformance to one national format.
_PHONE_RE = re.compile(r"^\+?[0-9][0-9\s\-().]{5,20}$")
_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[A-Za-z]{2,}$")


def looks_like_phone(value: str) -> bool:
    return bool(value and _PHONE_RE.match(value.strip()))


def looks_like_email(value: str) -> bool:
    return bool(value and _EMAIL_RE.match(value.strip()))


# ---------------------------------------------------------------------------
# Trusted contacts
# ---------------------------------------------------------------------------

class TrustedContactCreate(BaseModel):
    """A person the user chooses to record. No ``user_id`` — the server decides."""

    display_name: str = Field(..., min_length=1, max_length=80)
    method: ContactMethod = ContactMethod.PHONE
    value: Optional[str] = Field(
        None, max_length=120, description="Phone number or email, if the user gave one"
    )
    relationship: Optional[str] = Field(
        None, max_length=60, description="A label the user chooses: 'sister', 'friend'"
    )
    notes: Optional[str] = Field(None, max_length=500)
    enabled: bool = Field(
        True,
        description="Whether the user wants this contact offered in check-in and "
        "sharing flows. Enabling never notifies the contact.",
    )

    @field_validator("value")
    @classmethod
    def _validate_contact_value(cls, v, info):
        if v is None or not v.strip():
            return None
        method = (info.data or {}).get("method", ContactMethod.PHONE)
        cleaned = v.strip()
        if method == ContactMethod.PHONE and not looks_like_phone(cleaned):
            raise ValueError(
                "That does not look like a phone number. Include the digits, with "
                "or without a country code."
            )
        if method == ContactMethod.EMAIL and not looks_like_email(cleaned):
            raise ValueError("That does not look like an email address.")
        return cleaned


class TrustedContactUpdate(BaseModel):
    display_name: Optional[str] = Field(None, min_length=1, max_length=80)
    method: Optional[ContactMethod] = None
    value: Optional[str] = Field(None, max_length=120)
    relationship: Optional[str] = Field(None, max_length=60)
    notes: Optional[str] = Field(None, max_length=500)
    enabled: Optional[bool] = None


class TrustedContact(BaseModel):
    """A stored contact.

    **Storing someone here does not mean they agreed to anything.** They are not
    notified when added, they have no account, and they have not consented to be
    part of a safety workflow. Every surface that uses this must reflect that.
    """

    id: str
    owner_id: str
    display_name: str
    method: ContactMethod = ContactMethod.PHONE
    value: Optional[str] = None
    relationship: Optional[str] = None
    notes: Optional[str] = None
    enabled: bool = True
    #: Always false. There is no mechanism in HerWay to obtain a contact's
    #: consent, so this cannot become true, and nothing may assume otherwise.
    contact_has_consented: bool = False
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)


# ---------------------------------------------------------------------------
# Plan steps
# ---------------------------------------------------------------------------

class PlanStep(BaseModel):
    """One step in a user's plan."""

    id: str
    text: str = Field(..., min_length=1, max_length=1000)
    origin: StepOrigin = StepOrigin.USER
    status: StepStatus = StepStatus.TODO
    #: Present when the user rewrote a suggestion. Her wording is what the plan
    #: shows; the original is kept so the provenance is still inspectable.
    user_edited_text: Optional[str] = Field(None, max_length=1000)
    original_suggestion: Optional[str] = Field(None, max_length=1000)
    #: URLs backing a research-derived step, so the user can re-check the source.
    source_urls: List[str] = Field(default_factory=list)
    created_at: datetime = Field(default_factory=datetime.utcnow)

    @property
    def display_text(self) -> str:
        return self.user_edited_text or self.text

    @property
    def is_user_owned(self) -> bool:
        """Whether the user has actually taken this step on."""
        return self.origin in (StepOrigin.USER, StepOrigin.ACCEPTED_SUGGESTION)


# ---------------------------------------------------------------------------
# Plans
# ---------------------------------------------------------------------------

class SafetyCenterPlanCreate(BaseModel):
    title: str = Field(..., min_length=1, max_length=120)
    purpose: Optional[str] = Field(
        None, max_length=500, description="What this plan is for, in the user's words"
    )
    context: Optional[str] = Field(
        None, max_length=80, description="A situation label the user picked"
    )
    steps: List[str] = Field(default_factory=list, max_length=40)
    contact_ids: List[str] = Field(default_factory=list, max_length=20)
    locations: List[str] = Field(
        default_factory=list,
        max_length=10,
        description="Free-text places the user chose to note. Never collected automatically.",
    )
    safe_word: Optional[str] = Field(
        None, max_length=60, description="A word the user picks to signal trouble"
    )
    review_date: Optional[datetime] = None
    #: Optional links. Referencing a case does not copy its contents.
    case_id: Optional[str] = None
    research_refs: List[str] = Field(default_factory=list, max_length=20)


class SafetyCenterPlanUpdate(BaseModel):
    title: Optional[str] = Field(None, min_length=1, max_length=120)
    purpose: Optional[str] = Field(None, max_length=500)
    context: Optional[str] = Field(None, max_length=80)
    status: Optional[PlanStatus] = None
    contact_ids: Optional[List[str]] = Field(None, max_length=20)
    locations: Optional[List[str]] = Field(None, max_length=10)
    safe_word: Optional[str] = Field(None, max_length=60)
    review_date: Optional[datetime] = None
    case_id: Optional[str] = None
    research_refs: Optional[List[str]] = Field(None, max_length=20)


class SafetyCenterPlan(BaseModel):
    """A plan the user owns, writes and maintains."""

    id: str
    owner_id: str
    title: str
    purpose: Optional[str] = None
    context: Optional[str] = None
    status: PlanStatus = PlanStatus.ACTIVE

    #: Steps the user wrote or explicitly accepted.
    steps: List[PlanStep] = Field(default_factory=list)
    #: Suggestions awaiting a decision. Kept apart from ``steps`` so nothing
    #: unreviewed is ever presented as part of her plan.
    suggestions: List[PlanStep] = Field(default_factory=list)

    contact_ids: List[str] = Field(default_factory=list)
    locations: List[str] = Field(default_factory=list)
    safe_word: Optional[str] = None
    review_date: Optional[datetime] = None

    #: References, not copies. A deleted case leaves a dangling id, which the
    #: route handlers resolve to "no longer available" rather than failing.
    case_id: Optional[str] = None
    research_refs: List[str] = Field(default_factory=list)

    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)

    @property
    def accepted_step_count(self) -> int:
        return sum(1 for s in self.steps if s.is_user_owned)


# ---------------------------------------------------------------------------
# Check-ins
# ---------------------------------------------------------------------------

class CheckInCreate(BaseModel):
    """Start a check-in.

    A check-in is a note to oneself with an optional expected time. It is **not**
    GPS tracking and **not** monitoring: HerWay does not watch a timer on the
    user's behalf, and nothing is sent to anyone unless she sends it.
    """

    destination: Optional[str] = Field(
        None, max_length=160, description="Where she is going, if she wants to note it"
    )
    note: Optional[str] = Field(None, max_length=500)
    expected_back_at: Optional[datetime] = Field(
        None,
        description="Timezone-aware expected completion time. Naive datetimes are "
        "rejected rather than guessed at — assuming a server timezone would make "
        "a check-in overdue at the wrong moment.",
    )
    contact_id: Optional[str] = Field(
        None, description="A trusted contact the user may choose to message herself"
    )
    plan_id: Optional[str] = None

    @field_validator("expected_back_at")
    @classmethod
    def _require_timezone(cls, v):
        if v is not None and v.tzinfo is None:
            raise ValueError(
                "expected_back_at must include a timezone offset, so the check-in "
                "becomes overdue at the right moment wherever you are."
            )
        return v


class CheckIn(BaseModel):
    id: str
    owner_id: str
    status: CheckInStatus = CheckInStatus.ACTIVE
    destination: Optional[str] = None
    note: Optional[str] = None
    expected_back_at: Optional[datetime] = None
    contact_id: Optional[str] = None
    plan_id: Optional[str] = None
    started_at: datetime = Field(default_factory=datetime.utcnow)
    ended_at: Optional[datetime] = None
    #: Whether the user chose to send a message at any point. Records that she
    #: opened a share action — **not** that anything was delivered.
    share_opened: bool = False

    def is_overdue(self, now: Optional[datetime] = None) -> bool:
        """Whether the expected time has passed without confirmation.

        Computed on read rather than by a background timer. HerWay has no
        reliable background execution, and a timer that silently dies would be
        worse than no timer at all — it would look like monitoring while
        monitoring nothing.
        """
        if self.status is not CheckInStatus.ACTIVE or self.expected_back_at is None:
            return False
        from datetime import timezone

        current = now or datetime.now(timezone.utc)
        expected = self.expected_back_at
        if expected.tzinfo is None:
            expected = expected.replace(tzinfo=timezone.utc)
        if current.tzinfo is None:
            current = current.replace(tzinfo=timezone.utc)
        return current > expected


# ---------------------------------------------------------------------------
# Sharing
# ---------------------------------------------------------------------------

class ShareDraftRequest(BaseModel):
    check_in_id: Optional[str] = None
    plan_id: Optional[str] = None
    contact_id: Optional[str] = None
    include_destination: bool = False
    #: Off by default. Precise location is only ever included when the user
    #: turns it on for this specific message.
    include_location: bool = False
    location_text: Optional[str] = Field(None, max_length=200)
    custom_note: Optional[str] = Field(None, max_length=500)


class ShareDraft(BaseModel):
    """A message prepared for the user to review and send herself.

    HerWay has no SMS or WhatsApp provider configured. This produces text and,
    where a contact has a phone number, ``wa_me_url`` / ``sms_url`` links that
    open the user's own app with the message pre-filled.

    ``delivery_guarantee`` is always ``"none"``. Opening a messaging app is not
    delivery, and the interface must not imply it is.
    """

    message: str
    recipient_name: Optional[str] = None
    recipient_value: Optional[str] = None
    wa_me_url: Optional[str] = None
    sms_url: Optional[str] = None
    mailto_url: Optional[str] = None
    delivery_guarantee: str = "none"
    notice: str = (
        "Nothing has been sent. Review the message, then choose an app to send it "
        "yourself. HerWay cannot confirm it was delivered or read."
    )

    def to_dict(self) -> Dict[str, Any]:
        return self.model_dump()
