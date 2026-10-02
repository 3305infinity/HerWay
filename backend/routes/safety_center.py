"""
Safety Center endpoints — plans, trusted contacts, check-ins and sharing.

Every route here resolves the owner from the verified session
(``backend.auth.get_identity``) and every repository call is scoped to that
owner. No route accepts a caller-supplied owner id, and there is no endpoint
that returns a record without an ownership filter.

What these endpoints do **not** do
----------------------------------
- They do not send anything to anyone. ``/share-draft`` prepares text and
  returns links the *user* chooses to open; HerWay has no SMS or WhatsApp
  provider configured and does not pretend otherwise.
- They do not monitor. An overdue check-in is computed when the user looks at
  it; nothing watches a timer, and nobody is alerted.
- They do not track location. Any location in these records is free text the
  user typed.

Emergency guidance is deliberately **not** behind any of this: it lives on the
public ``/api/v2/resources/national`` endpoint, needs no account, and is exempt
from rate limiting.
"""

from __future__ import annotations

import logging
import urllib.parse
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from backend.auth import Identity, get_identity
from backend.models.safety_center import (
    CheckIn,
    CheckInCreate,
    CheckInStatus,
    ContactMethod,
    PlanStatus,
    PlanStep,
    SafetyCenterPlan,
    SafetyCenterPlanCreate,
    SafetyCenterPlanUpdate,
    ShareDraft,
    ShareDraftRequest,
    StepOrigin,
    StepStatus,
    TrustedContact,
    TrustedContactCreate,
    TrustedContactUpdate,
)
from backend.rate_limit import rate_limit_submission
from backend.services.safety_center_repository import SafetyCenterRepository, new_id
from backend.trace import get_trace_id

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v2/safety-center", tags=["safety-center"])


def _repo() -> SafetyCenterRepository:
    return SafetyCenterRepository()


def _owned_plan(owner_id: str, plan_id: str) -> SafetyCenterPlan:
    plan = _repo().get_plan(owner_id, plan_id)
    if plan is None:
        # 404 rather than 403: confirming that a plan exists but belongs to
        # someone else is itself a disclosure.
        raise HTTPException(status_code=404, detail="Plan not found.")
    return plan


def _owned_contact(owner_id: str, contact_id: str) -> TrustedContact:
    contact = _repo().get_contact(owner_id, contact_id)
    if contact is None:
        raise HTTPException(status_code=404, detail="Contact not found.")
    return contact


# ===========================================================================
# Plans
# ===========================================================================

@router.post("/plans", dependencies=[Depends(rate_limit_submission)])
async def create_plan(
    payload: SafetyCenterPlanCreate, identity: Identity = Depends(get_identity)
) -> Dict[str, Any]:
    """Create a plan.

    Steps supplied here are the user's own words, so they are stored with
    ``origin=user``. A plan is never created automatically from a conversation
    — this endpoint requires an explicit request.
    """
    plan = SafetyCenterPlan(
        id=new_id(),
        owner_id=identity.owner_id,
        title=payload.title.strip(),
        purpose=payload.purpose,
        context=payload.context,
        steps=[
            PlanStep(id=new_id(), text=text.strip(), origin=StepOrigin.USER)
            for text in payload.steps
            if text and text.strip()
        ],
        contact_ids=payload.contact_ids,
        locations=payload.locations,
        safe_word=payload.safe_word,
        review_date=payload.review_date,
        case_id=payload.case_id,
        research_refs=payload.research_refs,
    )
    _repo().create_plan(identity.owner_id, plan)
    return plan.model_dump(mode="json")


@router.get("/plans")
async def list_plans(
    include_archived: bool = Query(False),
    identity: Identity = Depends(get_identity),
) -> Dict[str, Any]:
    plans = _repo().list_plans(identity.owner_id, include_archived=include_archived)
    return {"plans": [p.model_dump(mode="json") for p in plans], "count": len(plans)}


@router.get("/plans/{plan_id}")
async def get_plan(
    plan_id: str, identity: Identity = Depends(get_identity)
) -> Dict[str, Any]:
    return _owned_plan(identity.owner_id, plan_id).model_dump(mode="json")


@router.patch("/plans/{plan_id}")
async def update_plan(
    plan_id: str,
    payload: SafetyCenterPlanUpdate,
    identity: Identity = Depends(get_identity),
) -> Dict[str, Any]:
    plan = _owned_plan(identity.owner_id, plan_id)
    for field, value in payload.model_dump(exclude_unset=True).items():
        setattr(plan, field, value)
    _repo().save_plan(identity.owner_id, plan)
    return plan.model_dump(mode="json")


@router.delete("/plans/{plan_id}")
async def delete_plan(
    plan_id: str, identity: Identity = Depends(get_identity)
) -> Dict[str, Any]:
    _owned_plan(identity.owner_id, plan_id)
    deleted = _repo().delete_plan(identity.owner_id, plan_id)
    return {"deleted": deleted}


class StepPayload(BaseModel):
    text: str = Field(..., min_length=1, max_length=1000)
    source_urls: List[str] = Field(default_factory=list, max_length=10)


@router.post("/plans/{plan_id}/steps", dependencies=[Depends(rate_limit_submission)])
async def add_step(
    plan_id: str, payload: StepPayload, identity: Identity = Depends(get_identity)
) -> Dict[str, Any]:
    plan = _owned_plan(identity.owner_id, plan_id)
    step = PlanStep(
        id=new_id(),
        text=payload.text.strip(),
        origin=StepOrigin.USER,
        source_urls=payload.source_urls,
    )
    plan.steps.append(step)
    _repo().save_plan(identity.owner_id, plan)
    return plan.model_dump(mode="json")


class SuggestionPayload(BaseModel):
    text: str = Field(..., min_length=1, max_length=1000)
    source_urls: List[str] = Field(default_factory=list, max_length=10)


@router.post("/plans/{plan_id}/suggestions", dependencies=[Depends(rate_limit_submission)])
async def add_suggestion(
    plan_id: str, payload: SuggestionPayload, identity: Identity = Depends(get_identity)
) -> Dict[str, Any]:
    """Record a suggestion for the user to decide on.

    It lands in ``suggestions``, not ``steps``. Until she accepts it, it is not
    part of her plan and must not be displayed as though it were.
    """
    plan = _owned_plan(identity.owner_id, plan_id)
    plan.suggestions.append(
        PlanStep(
            id=new_id(),
            text=payload.text.strip(),
            origin=StepOrigin.SUGGESTED,
            source_urls=payload.source_urls,
        )
    )
    _repo().save_plan(identity.owner_id, plan)
    return plan.model_dump(mode="json")


class AcceptSuggestionPayload(BaseModel):
    edited_text: Optional[str] = Field(
        None, max_length=1000, description="The user's own rewording, if she changed it"
    )


@router.post(
    "/plans/{plan_id}/suggestions/{step_id}/accept",
    dependencies=[Depends(rate_limit_submission)],
)
async def accept_suggestion(
    plan_id: str,
    step_id: str,
    payload: AcceptSuggestionPayload,
    identity: Identity = Depends(get_identity),
) -> Dict[str, Any]:
    """Move a suggestion into the plan, preserving the user's wording."""
    plan = _owned_plan(identity.owner_id, plan_id)
    match = next((s for s in plan.suggestions if s.id == step_id), None)
    if match is None:
        raise HTTPException(status_code=404, detail="Suggestion not found.")

    match.origin = StepOrigin.ACCEPTED_SUGGESTION
    if payload.edited_text and payload.edited_text.strip():
        match.original_suggestion = match.text
        match.user_edited_text = payload.edited_text.strip()

    plan.suggestions = [s for s in plan.suggestions if s.id != step_id]
    plan.steps.append(match)
    _repo().save_plan(identity.owner_id, plan)
    return plan.model_dump(mode="json")


@router.delete("/plans/{plan_id}/suggestions/{step_id}")
async def dismiss_suggestion(
    plan_id: str, step_id: str, identity: Identity = Depends(get_identity)
) -> Dict[str, Any]:
    plan = _owned_plan(identity.owner_id, plan_id)
    plan.suggestions = [s for s in plan.suggestions if s.id != step_id]
    _repo().save_plan(identity.owner_id, plan)
    return plan.model_dump(mode="json")


class StepStatusPayload(BaseModel):
    status: StepStatus


@router.patch("/plans/{plan_id}/steps/{step_id}")
async def update_step(
    plan_id: str,
    step_id: str,
    payload: StepStatusPayload,
    identity: Identity = Depends(get_identity),
) -> Dict[str, Any]:
    plan = _owned_plan(identity.owner_id, plan_id)
    match = next((s for s in plan.steps if s.id == step_id), None)
    if match is None:
        raise HTTPException(status_code=404, detail="Step not found.")
    match.status = payload.status
    _repo().save_plan(identity.owner_id, plan)
    return plan.model_dump(mode="json")


@router.delete("/plans/{plan_id}/steps/{step_id}")
async def delete_step(
    plan_id: str, step_id: str, identity: Identity = Depends(get_identity)
) -> Dict[str, Any]:
    plan = _owned_plan(identity.owner_id, plan_id)
    plan.steps = [s for s in plan.steps if s.id != step_id]
    _repo().save_plan(identity.owner_id, plan)
    return plan.model_dump(mode="json")


# ===========================================================================
# Trusted contacts
# ===========================================================================

@router.post("/contacts", dependencies=[Depends(rate_limit_submission)])
async def create_contact(
    payload: TrustedContactCreate, identity: Identity = Depends(get_identity)
) -> Dict[str, Any]:
    """Save a trusted contact.

    The contact is **not** notified. They have not agreed to anything, and
    ``contact_has_consented`` is permanently false.
    """
    contact = TrustedContact(
        id=new_id(),
        owner_id=identity.owner_id,
        display_name=payload.display_name.strip(),
        method=payload.method,
        value=payload.value,
        relationship=payload.relationship,
        notes=payload.notes,
        enabled=payload.enabled,
    )
    _repo().create_contact(identity.owner_id, contact)
    return contact.model_dump(mode="json")


@router.get("/contacts")
async def list_contacts(identity: Identity = Depends(get_identity)) -> Dict[str, Any]:
    contacts = _repo().list_contacts(identity.owner_id)
    return {
        "contacts": [c.model_dump(mode="json") for c in contacts],
        "count": len(contacts),
        "notice": (
            "Saving someone here does not tell them. They have not agreed to be "
            "part of a safety plan — if you want them to know, ask them yourself."
        ),
    }


@router.patch("/contacts/{contact_id}")
async def update_contact(
    contact_id: str,
    payload: TrustedContactUpdate,
    identity: Identity = Depends(get_identity),
) -> Dict[str, Any]:
    contact = _owned_contact(identity.owner_id, contact_id)
    updates = payload.model_dump(exclude_unset=True)

    # Re-validate the contact value against the (possibly new) method.
    method = updates.get("method", contact.method)
    value = updates.get("value", contact.value)
    if value:
        from backend.models.safety_center import looks_like_email, looks_like_phone

        if method == ContactMethod.PHONE and not looks_like_phone(value):
            raise HTTPException(status_code=422, detail="That does not look like a phone number.")
        if method == ContactMethod.EMAIL and not looks_like_email(value):
            raise HTTPException(status_code=422, detail="That does not look like an email address.")

    for field, new_value in updates.items():
        setattr(contact, field, new_value)
    _repo().save_contact(identity.owner_id, contact)
    return contact.model_dump(mode="json")


@router.delete("/contacts/{contact_id}")
async def delete_contact(
    contact_id: str, identity: Identity = Depends(get_identity)
) -> Dict[str, Any]:
    _owned_contact(identity.owner_id, contact_id)
    deleted = _repo().delete_contact(identity.owner_id, contact_id)
    return {"deleted": deleted, "detached_from_plans": True}


# ===========================================================================
# Check-ins
# ===========================================================================

@router.post("/check-ins", dependencies=[Depends(rate_limit_submission)])
async def start_check_in(
    payload: CheckInCreate, identity: Identity = Depends(get_identity)
) -> Dict[str, Any]:
    """Start a check-in.

    Nothing is scheduled and nobody is watching. The response says so, because
    an interface that implies monitoring where there is none is the most
    dangerous thing this feature could do.
    """
    if payload.contact_id:
        _owned_contact(identity.owner_id, payload.contact_id)

    check_in = CheckIn(
        id=new_id(),
        owner_id=identity.owner_id,
        destination=payload.destination,
        note=payload.note,
        expected_back_at=payload.expected_back_at,
        contact_id=payload.contact_id,
        plan_id=payload.plan_id,
    )
    _repo().create_check_in(identity.owner_id, check_in)
    return {
        **check_in.model_dump(mode="json"),
        "monitoring_notice": (
            "HerWay is not monitoring this check-in. No one is alerted if the time "
            "passes. If you want someone to know, send them a message yourself."
        ),
    }


@router.get("/check-ins")
async def list_check_ins(
    identity: Identity = Depends(get_identity), limit: int = Query(50, ge=1, le=200)
) -> Dict[str, Any]:
    check_ins = _repo().list_check_ins(identity.owner_id, limit=limit)
    now = datetime.now(timezone.utc)
    return {
        "check_ins": [
            {**c.model_dump(mode="json"), "is_overdue": c.is_overdue(now)} for c in check_ins
        ],
        "count": len(check_ins),
    }


@router.get("/check-ins/active")
async def get_active_check_in(
    identity: Identity = Depends(get_identity),
) -> Dict[str, Any]:
    check_in = _repo().active_check_in(identity.owner_id)
    if check_in is None:
        return {"check_in": None}
    return {
        "check_in": check_in.model_dump(mode="json"),
        "is_overdue": check_in.is_overdue(),
    }


class CheckInResolution(BaseModel):
    status: CheckInStatus


@router.patch("/check-ins/{check_in_id}")
async def resolve_check_in(
    check_in_id: str,
    payload: CheckInResolution,
    identity: Identity = Depends(get_identity),
) -> Dict[str, Any]:
    """Mark a check-in safe, or cancel it."""
    check_in = _repo().get_check_in(identity.owner_id, check_in_id)
    if check_in is None:
        raise HTTPException(status_code=404, detail="Check-in not found.")

    if payload.status not in (CheckInStatus.COMPLETED_SAFE, CheckInStatus.CANCELLED):
        raise HTTPException(
            status_code=422,
            detail="A check-in can only be marked safe or cancelled.",
        )

    check_in.status = payload.status
    check_in.ended_at = datetime.now(timezone.utc)
    _repo().save_check_in(identity.owner_id, check_in)
    return check_in.model_dump(mode="json")


@router.delete("/check-ins/{check_in_id}")
async def delete_check_in(
    check_in_id: str, identity: Identity = Depends(get_identity)
) -> Dict[str, Any]:
    if _repo().get_check_in(identity.owner_id, check_in_id) is None:
        raise HTTPException(status_code=404, detail="Check-in not found.")
    return {"deleted": _repo().delete_check_in(identity.owner_id, check_in_id)}


# ===========================================================================
# Sharing
# ===========================================================================

def _digits(value: Optional[str]) -> Optional[str]:
    if not value:
        return None
    cleaned = "".join(ch for ch in value if ch.isdigit() or ch == "+")
    return cleaned or None


@router.post("/share-draft", dependencies=[Depends(rate_limit_submission)])
async def build_share_draft(
    payload: ShareDraftRequest, identity: Identity = Depends(get_identity)
) -> Dict[str, Any]:
    """Prepare a message for the user to review and send herself.

    **Nothing is sent.** HerWay has no messaging provider configured. The
    returned links open the user's own WhatsApp, SMS or mail app with the text
    pre-filled; she chooses whether to press send, and HerWay never learns
    whether it arrived.

    Case contents are never included. Destination and location are opt-in per
    message and default to off.
    """
    owner_id = identity.owner_id
    contact: Optional[TrustedContact] = None
    if payload.contact_id:
        contact = _owned_contact(owner_id, payload.contact_id)

    parts: List[str] = []
    if payload.check_in_id:
        check_in = _repo().get_check_in(owner_id, payload.check_in_id)
        if check_in is None:
            raise HTTPException(status_code=404, detail="Check-in not found.")
        parts.append("I'm heading out and wanted someone to know.")
        if payload.include_destination and check_in.destination:
            parts.append(f"Going to: {check_in.destination}")
        if check_in.expected_back_at:
            parts.append(
                f"I expect to be done around {check_in.expected_back_at.strftime('%I:%M %p on %d %b')}."
            )

    if payload.plan_id:
        plan = _owned_plan(owner_id, payload.plan_id)
        # The title only. Steps can contain details she has not chosen to share.
        parts.append(f"This relates to my plan: {plan.title}")

    if payload.include_location and payload.location_text:
        parts.append(f"My location: {payload.location_text}")

    if payload.custom_note:
        parts.append(payload.custom_note.strip())

    if not parts:
        parts.append("Just letting you know I'm checking in.")

    message = "\n".join(parts)
    encoded = urllib.parse.quote(message)

    draft = ShareDraft(
        message=message,
        recipient_name=contact.display_name if contact else None,
        recipient_value=contact.value if contact else None,
    )

    if contact and contact.method == ContactMethod.PHONE and contact.value:
        number = _digits(contact.value)
        if number:
            draft.wa_me_url = f"https://wa.me/{number.lstrip('+')}?text={encoded}"
            draft.sms_url = f"sms:{number}?body={encoded}"
    elif contact and contact.method == ContactMethod.EMAIL and contact.value:
        draft.mailto_url = (
            f"mailto:{contact.value}?subject={urllib.parse.quote('Checking in')}&body={encoded}"
        )

    return {**draft.to_dict(), "trace_id": get_trace_id()}


# ===========================================================================
# Delete everything
# ===========================================================================

@router.delete("/all-data")
async def delete_all_data(identity: Identity = Depends(get_identity)) -> Dict[str, Any]:
    """Remove every Safety Center record belonging to this owner.

    Returns exact per-collection counts rather than a vague success, so the user
    can see what was actually removed.
    """
    counts = _repo().delete_all_for_owner(identity.owner_id)
    return {
        "deleted": counts,
        "notice": (
            "Your plans, contacts and check-in history have been removed from "
            "HerWay. Messages you already sent from your own phone are not "
            "affected — we never had those."
        ),
    }
