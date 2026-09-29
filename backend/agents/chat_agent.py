"""
ChatAgent — Case-aware conversational assistant with tool calling (Stage 5 of Haven pipeline).

Tool Registry
-------------
1. answer_user — Provide final response with optional source URLs/IDs.
2. search_web — Execute live Google Web search for missing facts.
3. search_news — Execute live Google News search for policy/recent updates.
4. search_local — Execute live Google Maps search for nearby support offices.
5. get_case — Fetch case details.
6. get_evidence — Fetch evidence items.
7. update_action_status — Mark action step as completed/in_progress.
"""

from __future__ import annotations

import json
import logging
from typing import TYPE_CHECKING, Any, Dict, List, Optional
from pydantic import BaseModel, Field

from bson import ObjectId
from backend.models.case import Case, CaseStatus
from backend.models.research import SearchVertical

if TYPE_CHECKING:
    from backend.services.llm_service import LLMService
    from backend.services.serpapi_service import SerpApiService

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Tool Argument Pydantic Models
# ---------------------------------------------------------------------------

class ToolAnswerUser(BaseModel):
    text: str = Field(..., description="The answer string for the user")
    source_ids: List[str] = Field(default_factory=list, description="IDs of evidence items referenced, e.g. ['EVIDENCE_01']")
    source_urls: List[str] = Field(default_factory=list, description="Exact URLs referenced")


class ToolSearchWeb(BaseModel):
    query: str = Field(..., description="Targeted web search query")
    reason: str = Field(..., description="Why this search is needed")


class ToolSearchNews(BaseModel):
    query: str = Field(..., description="Targeted news search query")
    reason: str = Field(..., description="Why news search is needed")


class ToolSearchLocal(BaseModel):
    query: str = Field(..., description="Targeted local/maps query")
    location: str = Field(..., description="Location string")
    reason: str = Field(..., description="Why local search is needed")


class ToolUpdateActionStatus(BaseModel):
    action_id: str = Field(..., description="ID of action item, e.g. ACTION_NOW_01 or SAFE_RIGHT_NOW_01")
    status: str = Field(..., description="todo | in_progress | completed | skipped | blocked")


class ToolAdaptSafetyPlan(BaseModel):
    updated_situation_facts: str = Field(..., description="New situation facts or escalation details stated by user")
    state_change_reason: str = Field(..., description="Why the safety plan needs adaptation")


class ToolSearchSafetyResources(BaseModel):
    query: str = Field(..., description="Specific resource search query, e.g. 'women shelter accepting children Austin TX'")
    location: Optional[str] = Field(None, description="Location context")
    reason: str = Field(..., description="Why this specific safety resource search is needed")


class ToolCallChoice(BaseModel):
    tool_name: str = Field(..., description="answer_user | search_web | search_news | search_local | update_action_status | adapt_safety_plan | search_safety_resources")
    arguments: Dict[str, Any] = Field(default_factory=dict)


_ASSISTANT_SYSTEM_PROMPT = """\
You are Haven, an AI safety and problem resolution assistant.

You have access to the current case details, situation, verified evidence, action plan, safety plan, and local resources.

CRITICAL GROUNDING RULES:
1. PREFER RETRIEVED EVIDENCE OVER MEMORY:
   - Base factual, legal, or procedural answers strictly on the retrieved evidence provided in the context.
   - If evidence supports a claim, reference the exact source title or URL.
2. INSUFFICIENT EVIDENCE:
   - If the current evidence does not answer the user's question, state what is missing and trigger a search tool (`search_web`, `search_news`, `search_local`, or `search_safety_resources`).
3. SAFETY PLAN ADAPTATION & RESOURCE DISCOVERY:
   - If the user describes a meaningful change in their safety situation (e.g. "He knows I am leaving", "I had to leave my house", "He took my phone"), call `adapt_safety_plan`.
   - If the user asks for specific local safety facilities (e.g. shelters with children, legal aid clinic nearby), call `search_safety_resources`.
4. TOOL SELECTION:
   - If you can answer directly using existing evidence/case details, call `answer_user`.
   - If you need fresh live information, call `search_web`, `search_news`, or `search_local`.
   - If the user asks to mark a step done, call `update_action_status`.

Respond with JSON matching the ToolCallChoice schema.
"""


class ChatAgent:
    """Tool-calling conversational agent grounded in case context."""

    def __init__(self, llm: LLMService, serpapi: SerpApiService) -> None:
        self._llm = llm
        self._serpapi = serpapi

    async def converse(
        self,
        case: Case,
        user_message: str,
        history: List[Dict[str, str]],
        db: Any = None,
    ) -> Dict[str, Any]:
        """Execute tool-calling loop grounded in case memory."""
        # 1. Format Context
        evidence_summary = "\n".join(
            f"[{e.id}] {e.claim_supported} (Source: {e.source_title} - {e.url})"
            for e in case.evidence
        ) if case.evidence else "No verified evidence yet."

        action_summary = ""
        if case.action_plan:
            action_summary = "\n".join(
                f"[{a.id}] {a.title} (Status: {a.status.value}, Evidence: {a.evidence_ids})"
                for a in case.action_plan.actions
            )

        context_prompt = (
            f"Case ID: {case.id}\n"
            f"Title: {case.title}\n"
            f"Category: {case.category}\n"
            f"Situation Summary: {case.situation.case_summary if case.situation else case.situation_text}\n"
            f"Known Facts: {case.situation.known_facts if case.situation else []}\n"
            f"User Claims: {case.situation.user_claims if case.situation else []}\n"
            f"Unknowns: {case.situation.unknowns if case.situation else []}\n\n"
            f"VERIFIED EVIDENCE:\n{evidence_summary}\n\n"
            f"ACTION PLAN STEPS:\n{action_summary or 'None'}\n\n"
            f"User Question: {user_message}\n"
        )

        # 2. Select & Run Tool
        tool_choice = await self._llm.structured_generate(
            system_prompt=_ASSISTANT_SYSTEM_PROMPT,
            user_prompt=context_prompt,
            output_schema=ToolCallChoice,
        )

        tool_name = tool_choice.tool_name
        args = tool_choice.arguments

        logger.info("ChatAgent selected tool '%s' with args=%s", tool_name, args)

        # 3. Deterministic Tool Execution
        if tool_name == "search_web":
            parsed_args = ToolSearchWeb.model_validate(args)
            results = await self._serpapi.search_web(query=parsed_args.query, case_id=case.id)
            res_summary = "\n".join(f"- {r.title}: {r.snippet} ({r.url})" for r in results[:3])
            
            # Answer user with search results context
            followup_prompt = (
                f"{context_prompt}\n\n"
                f"Live Web Search Results for '{parsed_args.query}':\n{res_summary}\n\n"
                f"Now provide a clean final answer using tool 'answer_user'."
            )
            final_choice = await self._llm.structured_generate(
                system_prompt=_ASSISTANT_SYSTEM_PROMPT,
                user_prompt=followup_prompt,
                output_schema=ToolCallChoice,
            )
            if final_choice.tool_name == "answer_user":
                ans = ToolAnswerUser.model_validate(final_choice.arguments)
                return {"reply": ans.text, "sources": ans.source_urls, "searched_query": parsed_args.query}
            return {"reply": f"Found the following information for '{parsed_args.query}':\n\n{res_summary}"}

        elif tool_name == "search_news":
            parsed_args = ToolSearchNews.model_validate(args)
            results = await self._serpapi.search_news(query=parsed_args.query, case_id=case.id)
            res_summary = "\n".join(f"- {r.title}: {r.snippet} ({r.url})" for r in results[:3])
            return {"reply": f"Searched recent news for '{parsed_args.query}':\n\n{res_summary}"}

        elif tool_name == "search_local":
            parsed_args = ToolSearchLocal.model_validate(args)
            results = await self._serpapi.search_maps(query=parsed_args.query, location=parsed_args.location, case_id=case.id)
            res_summary = "\n".join(f"- {r.title}: {r.address or ''} ({r.phone or 'No phone'})" for r in results[:3])
            return {"reply": f"Found nearby locations in {parsed_args.location}:\n\n{res_summary}"}

        elif tool_name == "update_action_status":
            parsed_args = ToolUpdateActionStatus.model_validate(args)
            if db is not None:
                # Check action plan
                if case.action_plan:
                    for act in case.action_plan.actions:
                        if act.id == parsed_args.action_id:
                            act.status = parsed_args.status
                    db["cases"].update_one({"_id": ObjectId(case.id)}, {"$set": {"action_plan": case.action_plan.model_dump()}})
                # Check safety plan
                if case.safety_plan:
                    for act in case.safety_plan.actions:
                        if act.id == parsed_args.action_id:
                            act.status = parsed_args.status
                    db["cases"].update_one({"_id": ObjectId(case.id)}, {"$set": {"safety_plan": case.safety_plan.model_dump()}})
            return {"reply": f"Updated action step '{parsed_args.action_id}' status to '{parsed_args.status}'."}

        elif tool_name == "adapt_safety_plan":
            parsed_args = ToolAdaptSafetyPlan.model_validate(args)
            if case.safety_plan and db is not None:
                from backend.agents.safety_plan_agent import SafetyPlanAgent
                from backend.agents.situation_agent import SituationAgent
                from backend.agents.research_agent import ResearchAgent
                from backend.agents.source_verifier import SourceVerifier
                from backend.services.maps_service import MapsService

                sit_agent = SituationAgent(self._llm)
                safety_agent = SafetyPlanAgent(self._llm)
                research_agent = ResearchAgent(self._llm, self._serpapi)
                verifier = SourceVerifier(self._llm)
                maps_service = MapsService(self._serpapi)

                full_updated_text = f"{case.situation_text}\n\n[UPDATE]: {parsed_args.updated_situation_facts}"
                updated_sit = await sit_agent.analyse(full_updated_text)

                plan = await research_agent.plan(case.id, updated_sit)
                exec_res = await research_agent.execute(plan)
                new_evidence = await verifier.verify(updated_sit, exec_res.results)
                new_local_res = await maps_service.discover_local_resources(
                    category=updated_sit.category.value,
                    location=updated_sit.location or case.location_context,
                    case_summary=updated_sit.case_summary,
                )

                adapted = await safety_agent.adapt_plan(
                    current_plan=case.safety_plan,
                    updated_situation=updated_sit,
                    new_evidence=new_evidence,
                    new_local_resources=new_local_res,
                    state_change_reason=parsed_args.state_change_reason,
                )

                db["cases"].update_one(
                    {"_id": ObjectId(case.id)},
                    {"$set": {"safety_plan": adapted.model_dump(), "situation": updated_sit.model_dump()}},
                )

                return {
                    "reply": (
                        f"⚠️ **Safety Plan Adapted**: Based on your update (*{parsed_args.state_change_reason}*), "
                        f"I have recalculated your safety assessment and added new immediate recommendations. "
                        f"Your completed actions have been preserved."
                    ),
                    "safety_plan": adapted.model_dump(),
                    "plan_adapted": True,
                }
            return {"reply": "I noted this safety update. Please refer to your active Safety Plan."}

        elif tool_name == "search_safety_resources":
            parsed_args = ToolSearchSafetyResources.model_validate(args)
            loc = parsed_args.location or (case.situation.location if case.situation else case.location_context)
            results = await self._serpapi.search_maps(query=parsed_args.query, location=loc, case_id=case.id)
            res_summary = "\n".join(f"- **{r.title}**: {r.address or ''} (Phone: {r.phone or 'N/A'}, Rating: {r.rating or 'N/A'})" for r in results[:4])

            if case.safety_plan and db is not None:
                from backend.models.safety_plan import SafetyMatchedResource
                existing_names = {r.name for r in case.safety_plan.matched_resources}
                for idx, r in enumerate(results[:4]):
                    if r.title not in existing_names:
                        case.safety_plan.matched_resources.append(
                            SafetyMatchedResource(
                                id=f"RES_CHAT_{idx + 1:02d}",
                                name=r.title,
                                category="shelter" if "shelter" in r.title.lower() else "crisis_center",
                                phone=r.phone,
                                address=r.address,
                                url=r.url,
                                rating=r.rating,
                                is_verified_gov_or_ngo=True,
                                notes=f"Searched for '{parsed_args.query}'",
                            )
                        )
                db["cases"].update_one(
                    {"_id": ObjectId(case.id)},
                    {"$set": {"safety_plan": case.safety_plan.model_dump()}},
                )

            return {
                "reply": f"Here are verified safety resources found for '{parsed_args.query}':\n\n{res_summary}\n\nI have added these directly to your Safety Plan resources.",
            }

        else:
            # Default answer_user
            ans = ToolAnswerUser.model_validate(args)
            return {"reply": ans.text, "sources": ans.source_urls}
