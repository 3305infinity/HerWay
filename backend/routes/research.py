"""
Research router — triggers and retrieves the research pipeline.

Every endpoint verifies that the caller owns the case first. Running research
on someone else's case would both leak its contents and spend their budget.

Endpoints:
  POST /api/v2/research/{case_id}/run     — run the full pipeline
  GET  /api/v2/research/{case_id}/report  — get the final research report
  GET  /api/v2/research/{case_id}/plan    — get the action plan
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Any, Dict

from bson import ObjectId
from bson.errors import InvalidId
from fastapi import APIRouter, Depends, HTTPException

from backend.agents.action_planner import ActionPlanner
from backend.agents.safety_plan_agent import SafetyPlanAgent
from backend.agents.situation_agent import SituationAgent
from backend.agents.source_verifier import SourceVerifier
from backend.auth import Identity, assert_case_owner, get_identity, owner_filter
from backend.db import get_database
from backend.models.case import CaseStatus, Location
from backend.services.llm_service import (
    LLMService,
    LLMUnavailableError,
    _classify_api_error,
)
from backend.services.maps_service import MapsService
from backend.services.research_orchestrator import ResearchOrchestrator
from backend.services.serpapi_service import SerpApiService
from backend.utils.common import serialize_object_id

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v2/research", tags=["research"])


def _get_db():
    db = get_database()
    if db is None:
        raise HTTPException(status_code=503, detail="Database unavailable")
    return db


def _object_id(case_id: str) -> ObjectId:
    try:
        return ObjectId(case_id)
    except (InvalidId, TypeError, ValueError):
        raise HTTPException(status_code=400, detail="Invalid case ID format")


def _load_owned_case(case_id: str, identity: Identity) -> Dict[str, Any]:
    doc = _get_db()["cases"].find_one({"_id": _object_id(case_id)})
    if not doc:
        raise HTTPException(status_code=404, detail="Case not found")
    assert_case_owner(doc, identity)
    return doc


@router.post("/{case_id}/run")
async def run_pipeline(case_id: str, identity: Identity = Depends(get_identity)):
    """Execute the full research → verification → action-plan pipeline.

    1. Loads the case (ownership checked).
    2. Runs the SituationAgent.
    3. Runs targeted research through the ResearchOrchestrator.
    4. Verifies sources.
    5. Builds an ActionPlan, and a SafetyPlan for safety categories.
    6. Persists results, including any partial failures.
    """
    db = _get_db()
    cases_col = db["cases"]
    reports_col = db["research_reports"]
    plans_col = db["action_plans"]

    case_doc = _load_owned_case(case_id, identity)
    obj_id = _object_id(case_id)
    scoped = {"_id": obj_id, **owner_filter(identity)}

    situation_text = case_doc.get("situation_text") or ""
    location = Location(**case_doc["location"]) if case_doc.get("location") else None

    cases_col.update_one(
        scoped,
        {"$set": {"status": CaseStatus.RESEARCHING.value, "updated_at": datetime.utcnow()}},
    )

    llm = LLMService()
    serpapi = SerpApiService()

    situation_agent = SituationAgent(llm)
    orchestrator = ResearchOrchestrator(llm, serpapi)
    verifier = SourceVerifier(llm)
    maps_service = MapsService(serpapi)
    planner = ActionPlanner(llm)

    try:
        # 1. Situation analysis — without this nothing downstream is meaningful.
        try:
            situation = await situation_agent.analyse(situation_text)
        except LLMUnavailableError as exc:
            logger.error(
                "Research: LLM unavailable for case %s (%s): %s", case_id, exc.reason, exc
            )
            cases_col.update_one(
                scoped,
                {"$set": {"status": CaseStatus.ACTIVE.value, "updated_at": datetime.utcnow()}},
            )
            raise HTTPException(
                status_code=429 if exc.reason == "rate_limited" else 503,
                detail=(
                    f"{exc.user_message} Your case is saved — open it and press "
                    f"Retry research when you are ready."
                ),
            )

        cases_col.update_one(
            scoped,
            {
                "$set": {
                    "category": getattr(situation.category, "value", str(situation.category)),
                    "status": CaseStatus.VERIFYING.value,
                    "updated_at": datetime.utcnow(),
                }
            },
        )

        # 2. Research + verification. Partial failures are recorded on the report.
        report = await orchestrator.run_full_orchestration(
            case_id=case_id,
            situation=situation,
            verifier=verifier,
            maps_service=maps_service,
            user_location=location,
        )

        report_result = reports_col.insert_one(report.model_dump())
        evidence = report.evidence
        local_resources = report.local_resources

        # 3. Action planning.
        cases_col.update_one(
            scoped,
            {"$set": {"status": CaseStatus.PLANNING.value, "updated_at": datetime.utcnow()}},
        )

        action_plan = None
        plan_result_id = None
        try:
            action_plan = await planner.plan(report)
            plan_result_id = str(plans_col.insert_one(action_plan.model_dump()).inserted_id)
        except Exception as exc:
            logger.error("Research: action planning failed for %s: %s", case_id, exc)
            report.degradations.append(
                _degradation(
                    "action_plan",
                    "planner_failed",
                    "We could not build a step-by-step plan from these sources. "
                    "The verified sources below are still available to you.",
                )
            )

        # 4. Safety plan for women-safety categories.
        safety_plan = None
        if SafetyPlanAgent.is_safety_case(situation.category.value, situation_text):
            try:
                safety_plan = await SafetyPlanAgent(llm).generate_safety_plan(
                    case_id=case_id,
                    situation=situation,
                    evidence=evidence,
                    local_resources=local_resources,
                )
            except Exception as exc:
                logger.error("Research: safety plan generation failed for %s: %s", case_id, exc)
                report.degradations.append(
                    _degradation(
                        "safety_plan",
                        "safety_plan_failed",
                        "We could not build your personalised safety plan automatically. "
                        "Emergency numbers 112 and 181 are available to you at any time.",
                    )
                )

        # 5. Persist.
        title_summary = situation.case_summary[:60]
        if len(situation.case_summary) > 60:
            title_summary += "…"

        case_update: Dict[str, Any] = {
            "title": title_summary or case_doc.get("title") or "Analyzed case",
            "category": situation.category.value,
            "status": CaseStatus.ACTIVE.value,
            "situation": situation.model_dump(),
            "evidence": [e.model_dump() for e in evidence],
            "local_resources": [r.model_dump() for r in local_resources],
            "research_trace": [t.model_dump() for t in report.trace],
            "research_degradations": [d.model_dump() for d in report.degradations],
            "research_location_used": report.location_used,
            "research_report_id": str(report_result.inserted_id),
            "updated_at": datetime.utcnow(),
        }
        if action_plan is not None:
            case_update["action_plan"] = action_plan.model_dump()
            case_update["action_plan_id"] = plan_result_id
        if safety_plan is not None:
            case_update["safety_plan"] = safety_plan.model_dump()

        cases_col.update_one(scoped, {"$set": case_update})

        return {
            "status": "complete" if not report.degradations else "partial",
            "case_id": case_id,
            "report_id": str(report_result.inserted_id),
            "action_plan_id": plan_result_id,
            "safety_plan_generated": safety_plan is not None,
            "evidence_count": len(evidence),
            "local_resources_count": len(local_resources),
            "action_count": len(action_plan.actions) if action_plan else 0,
            "trace_count": len(report.trace),
            "degradations": [d.model_dump() for d in report.degradations],
        }

    except HTTPException:
        raise
    except Exception as exc:
        logger.exception("Pipeline failed for case %s", case_id)
        cases_col.update_one(
            scoped,
            {"$set": {"status": CaseStatus.ACTIVE.value, "updated_at": datetime.utcnow()}},
        )

        # A provider rate limit is not a bug, and telling the user "something
        # went wrong" hides the one thing that would help them: waiting.
        classified = _classify_api_error(exc)
        if classified is not None:
            raise HTTPException(
                status_code=429 if classified.reason == "rate_limited" else 503,
                detail=f"{classified.user_message} Your case has been saved.",
            )

        raise HTTPException(
            status_code=500,
            detail=(
                "Research did not complete. Your case has been saved and you can "
                "retry from the case page."
            ),
        )


def _degradation(stage: str, reason: str, message: str):
    from backend.models.research import ResearchDegradation

    return ResearchDegradation(stage=stage, reason=reason, user_message=message)


@router.get("/{case_id}/report")
async def get_report(case_id: str, identity: Identity = Depends(get_identity)):
    """Retrieve the research report for a case the caller owns."""
    _load_owned_case(case_id, identity)
    doc = _get_db()["research_reports"].find_one({"case_id": case_id})
    if not doc:
        raise HTTPException(status_code=404, detail="No research report for this case yet")
    return serialize_object_id(doc)


@router.get("/{case_id}/plan")
async def get_action_plan(case_id: str, identity: Identity = Depends(get_identity)):
    """Retrieve the action plan for a case the caller owns."""
    _load_owned_case(case_id, identity)
    doc = _get_db()["action_plans"].find_one({"case_id": case_id})
    if not doc:
        raise HTTPException(status_code=404, detail="No action plan for this case yet")
    return serialize_object_id(doc)
