"""
Cases router — CRUD for the Case resource.

Every endpoint here resolves the caller's identity server-side via
``backend.auth`` and refuses to touch a case the caller does not own. The
``user_id`` query parameter that these endpoints used to accept from the
browser has been removed: it let anyone read or modify any case.

Endpoints:
  POST   /api/v2/cases                              — create a new case
  GET    /api/v2/cases/{id}                         — retrieve a case
  GET    /api/v2/cases                              — list the caller's cases
  PATCH  /api/v2/cases/{id}                         — update status/title/location
  DELETE /api/v2/cases/{id}                         — archive a case
  POST   /api/v2/cases/analyze                      — analyze situation text
  GET    /api/v2/cases/{id}/safety-plan             — read the safety plan
  PATCH  /api/v2/cases/{id}/actions/{action_id}     — update an action's status
  POST   /api/v2/cases/{id}/safety-plan/adapt       — re-plan after an escalation
  POST   /api/v2/cases/{id}/safety-plan/research-more — find more local resources
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Any, Dict, Optional

from bson import ObjectId
from bson.errors import InvalidId
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from backend.demo_scenarios import demo_title, get_scenario
from backend.auth import Identity, assert_case_owner, get_identity, owner_filter
from backend.db import get_database
from backend.models.case import Case, CaseCreate, CaseStatus, CaseUpdate, ensure_case_indexes
from backend.models.research import ResourceVerification, Situation
from backend.utils.common import serialize_object_id

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v2/cases", tags=["cases"])

MAX_LIST_LIMIT = 100


def _get_db():
    db = get_database()
    if db is None:
        raise HTTPException(status_code=503, detail="Database unavailable")
    try:
        ensure_case_indexes(db)
    except Exception:
        pass
    return db


def _get_collection():
    return _get_db()["cases"]


def _object_id(case_id: str) -> ObjectId:
    try:
        return ObjectId(case_id)
    except (InvalidId, TypeError, ValueError):
        raise HTTPException(status_code=400, detail="Invalid case ID format")


def _load_owned_case(case_id: str, identity: Identity) -> Dict[str, Any]:
    """Fetch a case and verify the caller owns it, or raise."""
    collection = _get_collection()
    obj_id = _object_id(case_id)

    try:
        doc = collection.find_one({"_id": obj_id})
    except Exception as exc:
        logger.error("DB error loading case %s: %s", case_id, exc)
        raise HTTPException(status_code=503, detail="Database temporarily unavailable")

    if not doc:
        raise HTTPException(status_code=404, detail="Case not found")

    assert_case_owner(doc, identity)
    return doc


def _derive_title(situation_text: str) -> str:
    clean_text = (situation_text or "").strip()
    if not clean_text:
        return "New case"
    first_sentence = clean_text.split(".")[0][:60]
    return f"{first_sentence}…" if len(clean_text) > 60 else first_sentence


# ``response_model_by_alias=False`` emits ``id`` rather than the Mongo alias
# ``_id``, so clients have one consistent field name to read.
@router.post("", response_model=Case, response_model_by_alias=False)
async def create_case(
    payload: CaseCreate,
    identity: Identity = Depends(get_identity),
):
    """Create a new case owned by the authenticated caller or their session."""
    collection = _get_collection()

    # Resolve the demo scenario, if one was named. Looking it up rather than
    # trusting the string means an unknown id simply produces an ordinary case
    # instead of writing an arbitrary value onto the record.
    demo_scenario = (
        get_scenario(payload.demo_scenario_id) if payload.demo_scenario_id else None
    )

    now = datetime.utcnow()
    doc = {
        # Ownership comes from the server, never from the request body.
        "user_id": identity.owner_id,
        "owner_kind": identity.kind,
        "title": (
            demo_title(demo_scenario)
            if demo_scenario
            else (payload.title or _derive_title(payload.situation_text))
        ),
        "category": payload.category or "other",
        "situation_text": payload.situation_text,
        "location": payload.location.model_dump() if payload.location else None,
        "location_context": payload.location.display_name if payload.location else None,
        "status": CaseStatus.ACTIVE.value,
        # Demo provenance, persisted.
        #
        # A demo case is a *real* case: owned by the session that ran it,
        # processed by the ordinary pipeline, deletable like any other. The
        # only difference is that its text came from a written scenario rather
        # than from the user, and that needs to be visible in storage — not
        # only in the screen that created it — so a sample can never be
        # mistaken for someone's actual report.
        #
        # The id is validated against the known scenarios; an unrecognised
        # value is discarded rather than stored, so this cannot be used to
        # write arbitrary strings onto a case.
        "is_demo": demo_scenario is not None,
        "demo_scenario_id": demo_scenario.id if demo_scenario else None,
        "created_at": now,
        "updated_at": now,
        "conversation": [],
        "evidence": [],
        "local_resources": [],
        "research_trace": [],
    }

    result = collection.insert_one(doc)
    doc["_id"] = str(result.inserted_id)

    logger.info("Created case %s for %s identity", doc["_id"], identity.kind)
    return Case(**doc)


@router.get("", response_model=list[Case], response_model_by_alias=False)
async def list_cases(
    status: Optional[str] = Query(None, description="active | paused | resolved | archived"),
    limit: int = Query(50, ge=1, le=MAX_LIST_LIMIT),
    identity: Identity = Depends(get_identity),
):
    """List the caller's own cases. Never returns another user's case."""
    collection = _get_collection()
    query: Dict[str, Any] = owner_filter(identity)
    if status:
        query["status"] = status

    try:
        docs = collection.find(query).sort("updated_at", -1).limit(limit)
        return [Case(**serialize_object_id(doc)) for doc in docs]
    except Exception as exc:
        logger.error("Error fetching cases from DB: %s", exc)
        raise HTTPException(
            status_code=503,
            detail="We could not load your cases right now. Please try again.",
        )


@router.post("/analyze", response_model=Situation)
async def analyze_situation(payload: CaseCreate):
    """Analyze a natural-language situation description into a structured Situation."""
    clean_text = (payload.situation_text or "").strip()
    if len(clean_text) < 5:
        raise HTTPException(
            status_code=400,
            detail="Please provide a brief description of what happened so HerWay can assist.",
        )

    from backend.agents.situation_agent import SituationAgent
    from backend.services.llm_service import LLMService, LLMUnavailableError

    llm = LLMService()
    agent = SituationAgent(llm)
    try:
        return await agent.analyse(clean_text)
    except LLMUnavailableError as exc:
        logger.error("Situation analysis unavailable (%s): %s", exc.reason, exc)
        raise HTTPException(
            status_code=429 if exc.reason == "rate_limited" else 503,
            detail=f"{exc.user_message} Your text has not been lost.",
        )
    except Exception as exc:
        # The model replied but we could not parse it. Returning the user's own
        # words back as a "summary" is honest; inventing facts would not be.
        logger.error("Situation analysis failed, returning literal fallback: %s", exc)
        from backend.models.research import SituationCategory, Urgency

        return Situation(
            case_summary=clean_text[:400],
            category=SituationCategory(payload.category) if _is_valid_category(payload.category) else SituationCategory.OTHER,
            urgency=Urgency.MEDIUM,
            known_facts=[],
            user_claims=[],
            unknowns=["HerWay could not analyse this automatically."],
            missing_information=[],
            questions_to_ask=["Could you share a little more about what you need help with?"],
            user_goal="Understand available options and verified resources",
        )


def _is_valid_category(value: Optional[str]) -> bool:
    from backend.models.research import SituationCategory

    if not value:
        return False
    return value in {c.value for c in SituationCategory}


@router.get("/{case_id}", response_model=Case, response_model_by_alias=False)
async def get_case(case_id: str, identity: Identity = Depends(get_identity)):
    """Retrieve a single case the caller owns."""
    doc = _load_owned_case(case_id, identity)
    return Case(**serialize_object_id(doc))


@router.patch("/{case_id}")
async def update_case(
    case_id: str,
    payload: CaseUpdate,
    identity: Identity = Depends(get_identity),
):
    """Update case title, status (active/paused/resolved/archived), or location."""
    _load_owned_case(case_id, identity)
    collection = _get_collection()

    update_fields: Dict[str, Any] = {"updated_at": datetime.utcnow()}
    if payload.title:
        update_fields["title"] = payload.title
    if payload.status:
        update_fields["status"] = payload.status.value
    if payload.location_context:
        update_fields["location_context"] = payload.location_context

    collection.update_one(
        {"_id": _object_id(case_id), **owner_filter(identity)},
        {"$set": update_fields},
    )
    return {
        "status": "updated",
        "case_id": case_id,
        "updated_fields": [k for k in update_fields if k != "updated_at"],
    }


@router.delete("/{case_id}")
async def archive_or_delete_case(case_id: str, identity: Identity = Depends(get_identity)):
    """Archive a case the caller owns."""
    _load_owned_case(case_id, identity)
    _get_collection().update_one(
        {"_id": _object_id(case_id), **owner_filter(identity)},
        {"$set": {"status": CaseStatus.ARCHIVED.value, "updated_at": datetime.utcnow()}},
    )
    return {"status": "archived", "case_id": case_id}


# ---------------------------------------------------------------------------
# Safety Plan Endpoints
# ---------------------------------------------------------------------------

@router.get("/{case_id}/safety-plan")
async def get_safety_plan(case_id: str, identity: Identity = Depends(get_identity)):
    """Retrieve the active Safety Plan for a case the caller owns."""
    doc = _load_owned_case(case_id, identity)
    plan = doc.get("safety_plan")
    if not plan:
        raise HTTPException(status_code=404, detail="No safety plan exists for this case")
    return plan


class SafetyActionStatusUpdate(BaseModel):
    status: str = Field(..., description="todo | in_progress | completed | skipped")


_ALLOWED_ACTION_STATUSES = {"todo", "in_progress", "completed", "skipped", "blocked"}


@router.patch("/{case_id}/actions/{action_id}")
async def update_action_status(
    case_id: str,
    action_id: str,
    payload: SafetyActionStatusUpdate,
    identity: Identity = Depends(get_identity),
):
    """Update the status of a specific action in the action plan or safety plan."""
    doc = _load_owned_case(case_id, identity)

    new_status = payload.status.lower().strip()
    if new_status not in _ALLOWED_ACTION_STATUSES:
        raise HTTPException(
            status_code=400,
            detail=f"Status must be one of: {', '.join(sorted(_ALLOWED_ACTION_STATUSES))}",
        )

    is_completed = new_status == "completed"
    now = datetime.utcnow()
    updated_action = None
    update_doc: Dict[str, Any] = {"updated_at": now}

    # 1. Standard action plan
    plan_dict = doc.get("action_plan")
    if isinstance(plan_dict, dict):
        touched = False
        for key in ("actions", "immediate_actions", "next_actions", "escalation_options", "escalation_actions"):
            for act in plan_dict.get(key, []) or []:
                if act.get("id") == action_id:
                    act["status"] = new_status
                    act["completed"] = is_completed
                    updated_action = updated_action or act
                    touched = True
        if touched:
            update_doc["action_plan"] = plan_dict

    # 2. Safety plan
    safety_dict = doc.get("safety_plan")
    if isinstance(safety_dict, dict):
        touched = False
        for key in (
            "actions",
            "right_now_actions",
            "next_24h_actions",
            "document_safe_actions",
            "support_network_actions",
            "formal_options_actions",
            "ongoing_actions",
        ):
            for act in safety_dict.get(key, []) or []:
                if act.get("id") == action_id:
                    act["status"] = new_status
                    act["completed_at"] = now.isoformat() if is_completed else None
                    updated_action = updated_action or act
                    touched = True
        if touched:
            safety_dict["updated_at"] = now.isoformat()
            update_doc["safety_plan"] = safety_dict

    if not updated_action:
        raise HTTPException(status_code=404, detail=f"Action '{action_id}' not found in this case")

    _get_collection().update_one(
        {"_id": _object_id(case_id), **owner_filter(identity)},
        {"$set": update_doc},
    )
    logger.info("Updated action %s in case %s to '%s'", action_id, case_id, new_status)
    return {"status": "updated", "action": updated_action}


@router.patch("/{case_id}/safety-plan/actions/{action_id}")
async def update_safety_action_status_alias(
    case_id: str,
    action_id: str,
    payload: SafetyActionStatusUpdate,
    identity: Identity = Depends(get_identity),
):
    """Backward-compatible alias for update_action_status."""
    return await update_action_status(case_id, action_id, payload, identity=identity)


class AdaptSafetyPlanPayload(BaseModel):
    updated_situation_text: str = Field(
        ..., min_length=3, description="New situation narrative or escalation update"
    )
    state_change_reason: Optional[str] = Field(
        None, description="Explanation of why the plan is changing"
    )


@router.post("/{case_id}/safety-plan/adapt")
async def adapt_safety_plan_endpoint(
    case_id: str,
    payload: AdaptSafetyPlanPayload,
    identity: Identity = Depends(get_identity),
):
    """Adapt the Safety Plan when the situation changes.

    Preserves completed actions, re-assesses, refreshes resources, and records
    why the plan changed.
    """
    from backend.agents.research_agent import ResearchAgent
    from backend.agents.safety_plan_agent import SafetyPlanAgent
    from backend.agents.situation_agent import SituationAgent
    from backend.agents.source_verifier import SourceVerifier
    from backend.models.safety_plan import SafetyPlan
    from backend.services.llm_service import LLMService, LLMUnavailableError
    from backend.services.maps_service import MapsService
    from backend.services.serpapi_service import SerpApiService

    doc = _load_owned_case(case_id, identity)

    existing_plan_data = doc.get("safety_plan")
    if not existing_plan_data:
        raise HTTPException(
            status_code=400, detail="This case does not have a safety plan to adapt yet."
        )

    existing_plan = SafetyPlan.model_validate(existing_plan_data)

    llm = LLMService()
    serpapi = SerpApiService()
    sit_agent = SituationAgent(llm)
    safety_agent = SafetyPlanAgent(llm)

    full_new_text = f"{doc.get('situation_text', '')}\n\n[UPDATE]: {payload.updated_situation_text}"

    try:
        updated_situation = await sit_agent.analyse(full_new_text)
    except LLMUnavailableError:
        raise HTTPException(
            status_code=503,
            detail=(
                "HerWay cannot update your plan right now. Your existing plan is "
                "unchanged and still available."
            ),
        )

    research_agent = ResearchAgent(llm, serpapi)
    verifier = SourceVerifier(llm)
    maps_service = MapsService(serpapi)

    # Research failures must not block an escalation update — the adapted plan
    # is more important than fresh sources.
    new_evidence = []
    new_local_res = []
    try:
        plan = await research_agent.plan(case_id, updated_situation)
        exec_res = await research_agent.execute(plan)
        new_evidence = await verifier.verify(updated_situation, exec_res.results)
    except Exception as exc:
        logger.warning("Adapt: refreshed research unavailable for %s: %s", case_id, exc)

    loc_str = updated_situation.location or doc.get("location_context")
    if loc_str:
        try:
            new_local_res = await maps_service.discover_local_resources(
                category=updated_situation.category.value,
                location=loc_str,
                case_summary=updated_situation.case_summary,
            )
        except Exception as exc:
            logger.warning("Adapt: local resource refresh failed for %s: %s", case_id, exc)

    reason = payload.state_change_reason or (
        f"Situation update: {payload.updated_situation_text[:120]}"
    )

    try:
        adapted_plan = await safety_agent.adapt_plan(
            current_plan=existing_plan,
            updated_situation=updated_situation,
            new_evidence=new_evidence,
            new_local_resources=new_local_res,
            state_change_reason=reason,
        )
    except LLMUnavailableError:
        raise HTTPException(
            status_code=503,
            detail=(
                "HerWay cannot rebuild your plan right now. Your existing plan is "
                "unchanged and still available."
            ),
        )

    now = datetime.utcnow()
    _get_collection().update_one(
        {"_id": _object_id(case_id), **owner_filter(identity)},
        {
            "$set": {
                "situation_text": full_new_text,
                "situation": updated_situation.model_dump(),
                "safety_plan": adapted_plan.model_dump(),
                "updated_at": now,
            }
        },
    )

    logger.info("Adapted safety plan for case %s", case_id)
    return adapted_plan.model_dump()


class ResearchMorePayload(BaseModel):
    query: str = Field(..., min_length=2, description="Targeted resource search query")
    location: Optional[str] = Field(None, description="City, district, state, or PIN code")
    vertical: str = Field("maps", description="maps | local | web")


@router.post("/{case_id}/safety-plan/research-more")
async def research_more_resources(
    case_id: str,
    payload: ResearchMorePayload,
    identity: Identity = Depends(get_identity),
):
    """Search for more support resources and attach them to the Safety Plan."""
    from backend.models.research import SearchVertical
    from backend.models.safety_plan import SafetyMatchedResource
    from backend.services.maps_service import MapsService
    from backend.services.serpapi_service import SerpApiService

    doc = _load_owned_case(case_id, identity)

    plan_dict = doc.get("safety_plan")
    if not plan_dict:
        raise HTTPException(status_code=404, detail="No safety plan exists for this case")

    location = payload.location or doc.get("location_context")
    if payload.vertical in ("maps", "local") and not location:
        # Searching maps with no place would return results from anywhere.
        raise HTTPException(
            status_code=400,
            detail="Add a city or district so HerWay can look for services near you.",
        )

    serpapi = SerpApiService()
    vertical = (
        SearchVertical.MAPS if payload.vertical in ("maps", "local") else SearchVertical.WEB
    )
    outcome = await serpapi.search_detailed(
        query=payload.query,
        vertical=vertical,
        location=location,
        case_id=case_id,
        reason=f"User-requested resource search: {payload.query[:60]}",
    )

    if not outcome.success:
        raise HTTPException(
            status_code=503,
            detail=(
                "The resource search could not run just now. Your saved resources "
                "are unchanged — please try again shortly."
            ),
        )

    new_matched: list[dict] = []
    existing_names = {r.get("name") for r in plan_dict.get("matched_resources", []) or []}

    for idx, r in enumerate(outcome.results):
        if not r.title or r.title in existing_names:
            continue
        existing_names.add(r.title)

        domain = MapsService._domain_of(r.url)
        verification, note = MapsService._classify(r.title, domain)

        res_obj = SafetyMatchedResource(
            id=f"RES_SEARCH_{len(existing_names) + idx:02d}",
            name=r.title,
            category="crisis_center",
            phone=r.phone,
            address=r.address,
            url=r.url,
            rating=r.rating,
            source_domain=domain,
            # Never mark a freshly-found listing as verified just because the
            # user asked for it.
            verification=verification,
            verification_note=note,
            notes=f"Found by searching for '{payload.query}'.",
        )
        new_matched.append(res_obj.model_dump())

    if new_matched:
        plan_dict.setdefault("matched_resources", []).extend(new_matched)
        plan_dict["updated_at"] = datetime.utcnow().isoformat()
        _get_collection().update_one(
            {"_id": _object_id(case_id), **owner_filter(identity)},
            {"$set": {"safety_plan": plan_dict, "updated_at": datetime.utcnow()}},
        )

    return {
        "status": "success",
        "searched": True,
        "new_resources_added": len(new_matched),
        "total_results": len(outcome.results),
        "resources": new_matched,
        "message": (
            f"Added {len(new_matched)} new place(s)."
            if new_matched
            else "We searched but did not find any new places for that query."
        ),
    }
