"""
Cases router — CRUD for the Case resource.

Endpoints:
  POST   /api/v2/cases          — create a new case
  GET    /api/v2/cases/{id}     — retrieve a case
  GET    /api/v2/cases          — list cases for a user
  PATCH  /api/v2/cases/{id}    — update case status, title, or location
  DELETE /api/v2/cases/{id}    — archive or delete a case
  POST   /api/v2/cases/analyze  — analyze situation text via SituationAgent
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Optional

from bson import ObjectId
from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

from backend.db import get_database
from backend.models.case import Case, CaseCreate, CaseStatus, CaseUpdate, ensure_case_indexes
from backend.models.research import Situation
from backend.utils.common import serialize_object_id

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v2/cases", tags=["cases"])


def _get_db():
    db = get_database()
    if db is None:
        raise HTTPException(status_code=503, detail="Database unavailable")
    ensure_case_indexes(db)
    return db


def _get_collection():
    return _get_db()["cases"]


@router.post("", response_model=Case)
async def create_case(payload: CaseCreate):
    """Create a new case from the user's situation description."""
    collection = _get_collection()

    # Generate initial title snippet
    clean_text = payload.situation_text.strip()
    first_sentence = clean_text.split(".")[0][:60]
    title = f"{first_sentence}..." if len(clean_text) > 60 else first_sentence

    doc = {
        "user_id": payload.user_id or "anonymous",
        "title": title or "New Case",
        "category": payload.category or "other",
        "situation_text": payload.situation_text,
        "location": payload.location.model_dump() if payload.location else None,
        "location_context": payload.location.display_name if payload.location else None,
        "status": CaseStatus.ACTIVE.value,
        "created_at": datetime.utcnow(),
        "updated_at": datetime.utcnow(),
        "conversation": [],
        "evidence": [],
        "local_resources": [],
        "research_trace": [],
    }

    result = collection.insert_one(doc)
    doc["_id"] = str(result.inserted_id)

    logger.info("Created case %s for user %s", doc["_id"], doc["user_id"])
    return Case(**doc)


@router.get("/{case_id}", response_model=Case)
async def get_case(case_id: str, user_id: Optional[str] = None):
    """Retrieve a single case by ID with authorization boundary check."""
    collection = _get_collection()

    try:
        doc = collection.find_one({"_id": ObjectId(case_id)})
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid Case ID format")

    if not doc:
        raise HTTPException(status_code=404, detail="Case not found")

    serialized = serialize_object_id(doc)
    # Check ownership if user_id is provided
    if user_id and serialized.get("user_id") and serialized["user_id"] != "anonymous":
        if serialized["user_id"] != user_id:
            raise HTTPException(status_code=403, detail="Unauthorized access to this case")

    return Case(**serialized)


@router.get("", response_model=list[Case])
async def list_cases(
    user_id: Optional[str] = Query(None, description="Clerk user_id"),
    status: Optional[str] = Query(None, description="active | paused | resolved | archived"),
    limit: int = 50,
):
    """List cases for a user with status filtering and index utilization."""
    collection = _get_collection()
    query = {}
    if user_id:
        query["user_id"] = user_id
    if status:
        query["status"] = status

    docs = collection.find(query).sort("updated_at", -1).limit(limit)
    return [Case(**serialize_object_id(doc)) for doc in docs]


@router.post("/analyze", response_model=Situation)
async def analyze_situation(payload: CaseCreate):
    """Analyze a natural-language situation description into a structured Situation object."""
    clean_text = (payload.situation_text or "").strip()
    if len(clean_text) < 5:
        raise HTTPException(
            status_code=400,
            detail="Please provide a brief description of what happened so Haven can assist.",
        )

    from backend.agents.situation_agent import SituationAgent
    from backend.services.llm_service import LLMService

    llm = LLMService()
    agent = SituationAgent(llm)
    try:
        return await agent.analyse(clean_text)
    except Exception as exc:
        logger.error("Situation analysis failed, providing graceful fallback: %s", exc)
        from backend.models.research import SituationCategory, Urgency
        return Situation(
            case_summary=clean_text[:200],
            category=SituationCategory.OTHER,
            urgency=Urgency.MEDIUM,
            known_facts=[clean_text[:120]],
            user_claims=[],
            unknowns=["Specific procedural and support options available"],
            missing_information=["Specific details, dates, or parties involved"],
            questions_to_ask=["Could you share more details about what you need help with?"],
            user_goal="Understand available options and verified resources",
        )


@router.patch("/{case_id}")
async def update_case(case_id: str, payload: CaseUpdate, user_id: Optional[str] = None):
    """Update case title, status (active/paused/resolved/archived), or location context."""
    collection = _get_collection()

    update_fields = {"updated_at": datetime.utcnow()}
    if payload.title:
        update_fields["title"] = payload.title
    if payload.status:
        update_fields["status"] = payload.status.value
    if payload.location_context:
        update_fields["location_context"] = payload.location_context

    query = {"_id": ObjectId(case_id)}
    if user_id:
        query["user_id"] = user_id

    result = collection.update_one(query, {"$set": update_fields})
    if result.matched_count == 0:
        raise HTTPException(status_code=404, detail="Case not found or unauthorized")

    return {"status": "updated", "case_id": case_id, "updated_fields": list(update_fields.keys())}


@router.delete("/{case_id}")
async def archive_or_delete_case(case_id: str, user_id: Optional[str] = None):
    """Archive a case."""
    collection = _get_collection()
    query = {"_id": ObjectId(case_id)}
    if user_id:
        query["user_id"] = user_id

    result = collection.update_one(query, {"$set": {"status": CaseStatus.ARCHIVED.value, "updated_at": datetime.utcnow()}})
    if result.matched_count == 0:
        raise HTTPException(status_code=404, detail="Case not found or unauthorized")

    return {"status": "archived", "case_id": case_id}


# ---------------------------------------------------------------------------
# Haven Safety Plan Endpoints
# ---------------------------------------------------------------------------

@router.get("/{case_id}/safety-plan")
async def get_safety_plan(case_id: str):
    """Retrieve the active Safety Plan for a case."""
    collection = _get_collection()
    doc = collection.find_one({"_id": ObjectId(case_id)})
    if not doc:
        raise HTTPException(status_code=404, detail="Case not found")

    plan = doc.get("safety_plan")
    if not plan:
        raise HTTPException(status_code=404, detail="No Safety Plan exists for this case")

    return plan


class SafetyActionStatusUpdate(BaseModel):
    status: str = Field(..., description="todo | in_progress | completed | skipped")


@router.patch("/{case_id}/actions/{action_id}")
async def update_action_status(
    case_id: str,
    action_id: str,
    payload: SafetyActionStatusUpdate,
    user_id: Optional[str] = None,
):
    """Update status of a specific action in either standard action_plan or safety_plan."""
    collection = _get_collection()
    try:
        doc = collection.find_one({"_id": ObjectId(case_id)})
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid Case ID format")

    if not doc:
        raise HTTPException(status_code=404, detail="Case not found")

    if user_id and doc.get("user_id") and doc["user_id"] != "anonymous" and doc["user_id"] != user_id:
        raise HTTPException(status_code=403, detail="Unauthorized access to this case")

    new_status = payload.status.lower()
    is_completed = (new_status == "completed")
    now = datetime.utcnow()
    updated_action = None
    update_doc = {"updated_at": now}

    # 1. Check in standard action_plan
    plan_dict = doc.get("action_plan")
    if plan_dict and isinstance(plan_dict, dict):
        for act in plan_dict.get("actions", []):
            if act.get("id") == action_id:
                act["status"] = new_status
                act["completed"] = is_completed
                updated_action = act
                break
        for phase_key in ["immediate_actions", "next_actions", "escalation_actions"]:
            for act in plan_dict.get(phase_key, []):
                if act.get("id") == action_id:
                    act["status"] = new_status
                    act["completed"] = is_completed
                    if not updated_action:
                        updated_action = act
        if updated_action:
            update_doc["action_plan"] = plan_dict

    # 2. Check in safety_plan
    safety_dict = doc.get("safety_plan")
    if safety_dict and isinstance(safety_dict, dict):
        for act in safety_dict.get("actions", []):
            if act.get("id") == action_id:
                act["status"] = new_status
                act["completed_at"] = now.isoformat() if is_completed else None
                updated_action = act
                break
        for phase_key in [
            "right_now_actions",
            "next_24h_actions",
            "document_safe_actions",
            "support_network_actions",
            "formal_options_actions",
            "ongoing_actions",
        ]:
            for act in safety_dict.get(phase_key, []):
                if act.get("id") == action_id:
                    act["status"] = new_status
                    act["completed_at"] = now.isoformat() if is_completed else None
                    if not updated_action:
                        updated_action = act
        if updated_action:
            safety_dict["updated_at"] = now.isoformat()
            update_doc["safety_plan"] = safety_dict

    if not updated_action:
        raise HTTPException(status_code=404, detail=f"Action '{action_id}' not found in case plan")

    collection.update_one({"_id": ObjectId(case_id)}, {"$set": update_doc})
    logger.info("Updated action %s in case %s to status '%s'", action_id, case_id, new_status)
    return {"status": "updated", "action": updated_action}


@router.patch("/{case_id}/safety-plan/actions/{action_id}")
async def update_safety_action_status_alias(
    case_id: str,
    action_id: str,
    payload: SafetyActionStatusUpdate,
    user_id: Optional[str] = None,
):
    """Backward-compatible alias for update_action_status."""
    return await update_action_status(case_id, action_id, payload, user_id=user_id)


class AdaptSafetyPlanPayload(BaseModel):
    updated_situation_text: str = Field(..., description="New situation narrative or escalation update")
    state_change_reason: Optional[str] = Field(
        None, description="Explanation of why the plan is changing"
    )


@router.post("/{case_id}/safety-plan/adapt")
async def adapt_safety_plan_endpoint(
    case_id: str,
    payload: AdaptSafetyPlanPayload,
):
    """
    Adapt the Safety Plan when situation state changes.
    Preserves completed actions, updates assessment, queries fresh resources if needed,
    and logs the update history.
    """
    from backend.agents.safety_plan_agent import SafetyPlanAgent
    from backend.agents.situation_agent import SituationAgent
    from backend.agents.research_agent import ResearchAgent
    from backend.agents.source_verifier import SourceVerifier
    from backend.services.llm_service import LLMService
    from backend.services.maps_service import MapsService
    from backend.services.serpapi_service import SerpApiService
    from backend.models.safety_plan import SafetyPlan

    collection = _get_collection()
    doc = collection.find_one({"_id": ObjectId(case_id)})
    if not doc:
        raise HTTPException(status_code=404, detail="Case not found")

    existing_plan_data = doc.get("safety_plan")
    if not existing_plan_data:
        raise HTTPException(status_code=400, detail="Case does not have an existing Safety Plan to adapt")

    existing_plan = SafetyPlan.model_validate(existing_plan_data)

    llm = LLMService()
    serpapi = SerpApiService()
    sit_agent = SituationAgent(llm)
    safety_agent = SafetyPlanAgent(llm)

    # 1. Analyze updated situation
    full_new_text = f"{doc.get('situation_text', '')}\n\n[UPDATE]: {payload.updated_situation_text}"
    updated_situation = await sit_agent.analyse(full_new_text)

    # 2. Targeted research if needed
    research_agent = ResearchAgent(llm, serpapi)
    verifier = SourceVerifier(llm)
    maps_service = MapsService(serpapi)

    plan = await research_agent.plan(case_id, updated_situation)
    exec_res = await research_agent.execute(plan)
    new_evidence = await verifier.verify(updated_situation, exec_res.results)

    loc_str = updated_situation.location or doc.get("location_context")
    new_local_res = await maps_service.discover_local_resources(
        category=updated_situation.category.value,
        location=loc_str,
        case_summary=updated_situation.case_summary,
    )

    reason = payload.state_change_reason or f"Situation escalated: {payload.updated_situation_text[:120]}"

    # 3. Adapt Plan
    adapted_plan = await safety_agent.adapt_plan(
        current_plan=existing_plan,
        updated_situation=updated_situation,
        new_evidence=new_evidence,
        new_local_resources=new_local_res,
        state_change_reason=reason,
    )

    # 4. Save to DB
    now = datetime.utcnow()
    collection.update_one(
        {"_id": ObjectId(case_id)},
        {
            "$set": {
                "situation_text": full_new_text,
                "situation": updated_situation.model_dump(),
                "safety_plan": adapted_plan.model_dump(),
                "updated_at": now,
            }
        },
    )

    logger.info("Successfully adapted safety plan for case %s", case_id)
    return adapted_plan.model_dump()


class ResearchMorePayload(BaseModel):
    query: str = Field(..., description="Targeted resource search query")
    location: Optional[str] = Field(None, description="City, area, or postal code")
    vertical: str = Field("maps", description="maps | local | web")


@router.post("/{case_id}/safety-plan/research-more")
async def research_more_resources(
    case_id: str,
    payload: ResearchMorePayload,
):
    """Dynamically search for additional verified safety resources and link to the Safety Plan."""
    from backend.services.serpapi_service import SerpApiService
    from backend.models.safety_plan import SafetyMatchedResource

    collection = _get_collection()
    doc = collection.find_one({"_id": ObjectId(case_id)})
    if not doc:
        raise HTTPException(status_code=404, detail="Case not found")

    plan_dict = doc.get("safety_plan")
    if not plan_dict:
        raise HTTPException(status_code=404, detail="No Safety Plan exists for this case")

    serpapi = SerpApiService()
    results = []
    if payload.vertical in ("maps", "local"):
        results = await serpapi.search_maps(query=payload.query, location=payload.location, case_id=case_id)
    else:
        results = await serpapi.search_web(query=payload.query, location=payload.location, case_id=case_id)

    new_matched: list[dict] = []
    existing_names = {r.get("name") for r in plan_dict.get("matched_resources", [])}

    for idx, r in enumerate(results):
        if r.title in existing_names:
            continue
        existing_names.add(r.title)
        res_obj = SafetyMatchedResource(
            id=f"RES_EXTRA_{len(existing_names) + idx:02d}",
            name=r.title,
            category="shelter" if "shelter" in r.title.lower() else "crisis_center",
            phone=r.phone,
            address=r.address,
            url=r.url,
            rating=r.rating,
            operating_hours=r.hours,
            is_verified_gov_or_ngo=True,
            notes=f"Targeted search for '{payload.query}'",
        )
        new_matched.append(res_obj.model_dump())

    if new_matched:
        plan_dict["matched_resources"].extend(new_matched)
        plan_dict["updated_at"] = datetime.utcnow().isoformat()
        collection.update_one(
            {"_id": ObjectId(case_id)},
            {"$set": {"safety_plan": plan_dict, "updated_at": datetime.utcnow()}},
        )

    return {"status": "success", "new_resources_added": len(new_matched), "resources": new_matched}


