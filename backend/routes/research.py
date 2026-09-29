"""
Research router — triggers and retrieves the research pipeline.

Endpoints:
  POST /api/v2/research/{case_id}/run     — run the full pipeline
  GET  /api/v2/research/{case_id}/report  — get the final research report
  GET  /api/v2/research/{case_id}/plan    — get the action plan
"""

from __future__ import annotations

import logging
from datetime import datetime

from bson import ObjectId
from fastapi import APIRouter, HTTPException

from backend.agents.action_planner import ActionPlanner
from backend.agents.research_agent import ResearchAgent
from backend.agents.safety_plan_agent import SafetyPlanAgent
from backend.agents.situation_agent import SituationAgent
from backend.agents.source_verifier import SourceVerifier
from backend.db import get_database
from backend.models.case import CaseStatus, Location
from backend.models.research import FinalResearchReport
from backend.services.llm_service import LLMService
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


@router.post("/{case_id}/run")
async def run_pipeline(case_id: str):
    """Execute the full research → verification → action-plan pipeline.

    This is the main orchestration endpoint.  It:
    1. Loads the case.
    2. Runs the SituationAgent.
    3. Runs the ResearchAgent (plan + execute).
    4. Runs the SourceVerifier.
    5. Assembles the FinalResearchReport.
    6. Runs the ActionPlanner.
    7. Persists results and updates case status.
    """
    db = _get_db()
    cases_col = db["cases"]
    reports_col = db["research_reports"]
    plans_col = db["action_plans"]

    # 1. Load case
    case_doc = cases_col.find_one({"_id": ObjectId(case_id)})
    if not case_doc:
        raise HTTPException(status_code=404, detail="Case not found")

    situation_text = case_doc["situation_text"]
    location = None
    if case_doc.get("location"):
        location = Location(**case_doc["location"])

    # Update status
    cases_col.update_one(
        {"_id": ObjectId(case_id)},
        {"$set": {"status": CaseStatus.RESEARCHING.value, "updated_at": datetime.utcnow()}},
    )

    # Initialise services and agents
    llm = LLMService()
    serpapi = SerpApiService()

    situation_agent = SituationAgent(llm)
    orchestrator = ResearchOrchestrator(llm, serpapi)
    verifier = SourceVerifier(llm)
    maps_service = MapsService(serpapi)
    planner = ActionPlanner(llm)

    try:
        # 2. Situation analysis
        situation = await situation_agent.analyse(situation_text)

        # Update case with category
        cases_col.update_one(
            {"_id": ObjectId(case_id)},
            {"$set": {"category": situation.category.value if hasattr(situation.category, "value") else str(situation.category), "updated_at": datetime.utcnow()}},
        )

        # 3. Intelligent Multi-Pass Research Orchestration
        cases_col.update_one(
            {"_id": ObjectId(case_id)},
            {"$set": {"status": CaseStatus.VERIFYING.value, "updated_at": datetime.utcnow()}},
        )
        report = await orchestrator.run_full_orchestration(
            case_id=case_id,
            situation=situation,
            verifier=verifier,
            maps_service=maps_service,
            user_location=location,
        )

        report_doc = report.model_dump()
        report_result = reports_col.insert_one(report_doc)

        evidence = report.evidence
        local_resources = report.local_resources

        # 4. Action planning
        cases_col.update_one(
            {"_id": ObjectId(case_id)},
            {"$set": {"status": CaseStatus.PLANNING.value, "updated_at": datetime.utcnow()}},
        )
        action_plan = await planner.plan(report)
        plan_doc = action_plan.model_dump()
        plan_result = plans_col.insert_one(plan_doc)

        # 7b. Haven Safety Plan Generation (for women safety / protection cases)
        safety_plan = None
        is_safety = SafetyPlanAgent.is_safety_case(situation.category.value, situation_text)
        if is_safety:
            safety_agent = SafetyPlanAgent(llm)
            safety_plan = await safety_agent.generate_safety_plan(
                case_id=case_id,
                situation=situation,
                evidence=evidence,
                local_resources=local_resources,
            )

        # 8. Update case with embedded pipeline objects & references
        title_summary = f"{situation.case_summary[:60]}..." if len(situation.case_summary) > 60 else situation.case_summary
        case_update_dict = {
            "title": title_summary or "Analyzed Case",
            "category": situation.category.value,
            "status": CaseStatus.ACTIVE.value,
            "situation": situation.model_dump(),
            "evidence": [e.model_dump() for e in evidence],
            "action_plan": action_plan.model_dump(),
            "safety_plan": safety_plan.model_dump() if safety_plan else None,
            "local_resources": [r.model_dump() for r in local_resources],
            "research_trace": [t.model_dump() for t in report.trace],
            "research_report_id": str(report_result.inserted_id),
            "action_plan_id": str(plan_result.inserted_id),
            "updated_at": datetime.utcnow(),
        }
        cases_col.update_one(
            {"_id": ObjectId(case_id)},
            {"$set": case_update_dict},
        )

        return {
            "status": "complete",
            "case_id": case_id,
            "report_id": str(report_result.inserted_id),
            "action_plan_id": str(plan_result.inserted_id),
            "safety_plan_generated": safety_plan is not None,
            "evidence_count": len(evidence),
            "local_resources_count": len(local_resources),
            "action_count": len(action_plan.actions),
            "trace_count": len(report.trace),
        }

    except Exception as exc:
        logger.exception("Pipeline failed for case %s", case_id)
        cases_col.update_one(
            {"_id": ObjectId(case_id)},
            {"$set": {"status": CaseStatus.INTAKE.value, "updated_at": datetime.utcnow()}},
        )
        raise HTTPException(status_code=500, detail=f"Pipeline error: {exc}")


@router.get("/{case_id}/report")
async def get_report(case_id: str):
    """Retrieve the research report for a case."""
    db = _get_db()
    doc = db["research_reports"].find_one({"case_id": case_id})
    if not doc:
        raise HTTPException(status_code=404, detail="Report not found")
    return serialize_object_id(doc)


@router.get("/{case_id}/plan")
async def get_action_plan(case_id: str):
    """Retrieve the action plan for a case."""
    db = _get_db()
    doc = db["action_plans"].find_one({"case_id": case_id})
    if not doc:
        raise HTTPException(status_code=404, detail="Action plan not found")
    return serialize_object_id(doc)
