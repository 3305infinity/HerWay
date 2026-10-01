"""
ChatAgent — Case-aware conversational assistant with tool calling (Stage 5 of Haven pipeline).

Tool Registry
-------------
1.  answer_user            — Provide final response with optional source URLs/IDs.
2.  search_web             — Execute live Google Web search for missing facts.
3.  search_news            — Execute live Google News search for policy/recent updates.
4.  search_local           — Execute live Google Maps search for nearby support offices.
5.  update_action_status   — Mark action step as completed/in_progress.
6.  adapt_safety_plan      — Re-run safety assessment on updated situation.
7.  search_safety_resources — Find specific local safety resources.

--- Original Haven capabilities, now wired as first-class tools ---
8.  invoke_lawbot          — Answer legal questions via existing RAG pipeline
                             (generate_text_embedding + MongoDB Atlas vector search
                             over doc_embedding collection).
9.  search_community       — Surface similar community posts via existing
                             embedding similarity search on admin collection.
10. encode_message         — Encode a help text into an image using the existing
                             LSB steganography pipeline (discreet communication).
11. generate_formal_report — Draft an authority-ready report using the existing
                             Gemini + Gemma text-expansion pipeline.
12. generate_poem          — Create an empowering poem using the existing
                             Gemini 1.5 Flash 8B poem-generation pipeline.
"""

from __future__ import annotations

import json
import logging
from typing import TYPE_CHECKING, Any, Dict, List, Optional
from pydantic import BaseModel, Field

from bson import ObjectId
from backend.models.agent_envelope import AgentExecution
from backend.models.case import Case, CaseStatus
from backend.trace import get_trace_id, log_fields
from backend.models.research import (
    ResourceVerification,
    SearchFailureReason,
    SearchVertical,
)

# Import thin-wrapper services that re-use existing Haven capabilities
from backend.services.embedding_service import EmbeddingService
from backend.services.report_service import ReportService
from backend.services.steganography_service import StegService

if TYPE_CHECKING:
    from backend.services.llm_service import LLMService
    from backend.services.serpapi_service import SerpApiService

logger = logging.getLogger(__name__)


#: Fields on a community post that identify or expose the person who wrote it.
#: Community posts are shared to help others, not to publish someone's phone
#: number — these never leave the server.
_COMMUNITY_PRIVATE_FIELDS = {
    "contact info",
    "contact_info",
    "phone",
    "email",
    "preferred way of contact",
    "preferred_contact_method",
    "culprit_embedding",
    "embedding",
    "user_id",
}


def _redact_community_post(post: Dict[str, Any]) -> Dict[str, Any]:
    """Return a community post with contact and identifying fields removed."""
    safe: Dict[str, Any] = {}
    for key, value in (post or {}).items():
        if key.lower().strip() in _COMMUNITY_PRIVATE_FIELDS:
            continue
        safe[key] = value
    return safe


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
    query: str = Field(
        ...,
        description=(
            "Specific resource search query, e.g. 'shelter home accepting women with children' "
            "or 'One Stop Centre Sakhi'. Do not include a place name here — pass it in `location`."
        ),
    )
    location: Optional[str] = Field(None, description="City, district or state in India")
    reason: str = Field(..., description="Why this specific safety resource search is needed")


# ---- New tool models (wrapping existing Haven capabilities) ----

class ToolInvokeLawbot(BaseModel):
    question: str = Field(..., description="The specific legal question to answer via RAG")
    reason: str = Field(..., description="Why legal RAG is needed for this question")


class ToolSearchCommunity(BaseModel):
    query: str = Field(..., description="Situation description to find similar community posts")
    reason: str = Field(..., description="Why community posts are relevant here")


class ToolEncodeMessage(BaseModel):
    message: str = Field(..., description="The help message to encode discreetly into an image")
    reason: str = Field(..., description="Why discreet communication is needed")


class ToolGenerateFormalReport(BaseModel):
    situation_summary: str = Field(..., description="Concise situation summary for the formal report")
    location: Optional[str] = Field(None, description="User location if known")
    reason: str = Field(..., description="Why a formal report is being generated")


class ToolGeneratePoem(BaseModel):
    context: str = Field(..., description="Brief emotional context to personalise the poem")
    reason: str = Field(..., description="Why an empowering poem is appropriate now")


class ToolCallChoice(BaseModel):
    tool_name: str = Field(
        ...,
        description=(
            "answer_user | search_web | search_news | search_local | "
            "update_action_status | adapt_safety_plan | search_safety_resources | "
            "invoke_lawbot | search_community | encode_message | "
            "generate_formal_report | generate_poem"
        ),
    )
    arguments: Dict[str, Any] = Field(default_factory=dict)


_ASSISTANT_SYSTEM_PROMPT = """\
You are HerWay (with supportive companion identity Niva), a safety and problem
resolution assistant for women in India.

You have access to the current case details, situation, verified evidence,
action plan, safety plan, and local resources.

JURISDICTION: India. All law, procedure, helplines and services you refer to
must be Indian. Never cite US or UK law, and never mention 911.

CRITICAL GROUNDING RULES:
1. PREFER RETRIEVED EVIDENCE OVER MEMORY:
   - Base factual, legal, or procedural answers strictly on the retrieved
     evidence in the context. Reference the exact source title or URL.
   - If you are drawing on general knowledge rather than a retrieved source,
     say so plainly.
2. INSUFFICIENT EVIDENCE:
   - If the evidence does not answer the question, say what is missing and call
     a search tool (`search_web`, `search_news`, `search_local`,
     `search_safety_resources`). Do not fill the gap from memory.
3. NEVER INVENT:
   - Never invent a phone number, address, office name, section number, case
     name, deadline, or fee. If you do not have it from a source, say so.

SAFETY MANDATES (absolute):
- Never suggest confronting, warning, or recording the person causing harm.
- Never suggest collecting evidence if it could increase risk; always attach
  "only if it is safe to do so".
- Never promise a legal outcome.
- If the user describes immediate danger, lead with 112 and 181.

SAFETY PLAN ADAPTATION & RESOURCE DISCOVERY:
   - If the user describes a meaningful change in their safety situation
     (e.g. "He knows I am leaving", "I had to leave my house", "He took my
     phone"), call `adapt_safety_plan`.
   - If the user asks for specific local facilities (shelters that accept
     children, a legal aid clinic nearby), call `search_safety_resources`.

TOOL SELECTION:
   - Answer directly with `answer_user` when existing case evidence suffices.
   - Use a search tool only when fresh or missing information is genuinely
     needed. Do not search for emotional-support messages.
   - If the user asks to mark a step done, call `update_action_status`.

HAVEN CAPABILITIES (integrated as tools):
   - LEGAL QUESTIONS (`invoke_lawbot`): for a specific question about Indian law
     (PWDVA 2005, POSH Act 2013, BNS/IPC, IT Act, consumer rights). Use this
     before a web search for settled statutory questions.
   - COMMUNITY POSTS (`search_community`): when peer experience would help.
   - DISCREET COMMUNICATION (`encode_message`): for domestic_violence or
     coercive_control cases, when the user asks how to send a hidden message.
   - FORMAL REPORT (`generate_formal_report`): when the user wants a written
     report for police, NCW, or a POSH Internal Committee.
   - ENCOURAGEMENT (`generate_poem`): only if the user asks for encouragement.

Respond with JSON matching the ToolCallChoice schema.
"""

#: Appended when the user is in the Niva / emotional-support surface.
_THERAPY_MODE_PROMPT = """\

MODE: EMOTIONAL SUPPORT (Niva).
The user came here to be heard, not to be processed.
- Lead with warmth and acknowledgement. Reflect what they said before anything else.
- Do NOT escalate to legal steps, complaint procedures, or action plans unless the
  user asks for them, or they describe immediate danger.
- Do NOT call search tools for feelings. Prefer `answer_user`.
- Keep replies short and human. No bullet-point checklists unless asked.
- If they mention immediate danger or self-harm, gently surface 112 and
  Tele-MANAS 14416, and stay with them.
"""

#: Appended when the user is in the LawBot surface.
_LEGAL_MODE_PROMPT = """\

MODE: LEGAL INFORMATION (LawBot).
You are not a lawyer and must say so when it matters.

Label claims so the user can judge them. Use these prefixes in your answer:
- **Fact:** something stated in the case or a retrieved source.
- **Legal information:** what a law or official procedure says, with the source.
- **Possible option:** a route the user could consider, not a recommendation.
- **Needs verification:** anything you are not sure of, or that varies by state.

Rules:
- Cite the Act by name and year (e.g. "Protection of Women from Domestic
  Violence Act, 2005"). Only give a section number if a retrieved source states it.
- Never invent a section number, judgment, or precedent.
- Say clearly that this is legal information, not legal advice, and that free
  legal aid is available to women through DLSA / NALSA.
- Where procedure differs by state, say so rather than guessing.
"""


class ChatAgent:
    """Tool-calling conversational agent grounded in case context."""

    def __init__(self, llm: LLMService, serpapi: SerpApiService) -> None:
        self._llm = llm
        self._serpapi = serpapi

    # ------------------------------------------------------------------
    # Honest failure helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _search_unavailable(kind: str, query: str, outcome) -> Dict[str, Any]:
        """Tell the user a search failed instead of answering from memory.

        Answering anyway would look identical to a researched answer, which is
        exactly the failure mode this product cannot have.
        """
        if outcome.failure_reason == SearchFailureReason.NOT_CONFIGURED:
            detail = "Live search is not configured on this deployment."
        elif outcome.failure_reason == SearchFailureReason.RATE_LIMITED:
            detail = "The search service is temporarily rate limited."
        elif outcome.failure_reason == SearchFailureReason.TIMEOUT:
            detail = "The search service did not respond in time."
        else:
            detail = "The search service could not be reached."

        return {
            "reply": (
                f"I tried to look this up and could not. {detail}\n\n"
                f"I am not going to answer from memory, because out-of-date "
                f"information could put you at risk.\n\n"
                f"If this is urgent: 112 for emergencies, 181 for the women helpline, "
                f"1930 for cyber crime. Please try asking me again in a few minutes."
            ),
            "tool_used": f"search_{kind}",
            "searched_query": query,
            "degraded_notice": f"{kind} search unavailable: {outcome.failure_reason.value}",
        }

    @staticmethod
    def _format_place(r) -> str:
        """Render a map listing without implying it has been verified."""
        parts = [f"**{r.title}**"]
        if r.address:
            parts.append(f"  {r.address}")
        if r.phone:
            parts.append(f"  Phone: {r.phone}")
        if r.url:
            parts.append(f"  {r.url}")
        if not r.phone:
            parts.append("  (No phone number listed — please verify before visiting.)")
        return "\n".join(parts)

    def _system_prompt(self, mode: Optional[str]) -> str:
        """Base prompt plus the surface-specific guidance for this session."""
        if mode == "therapy":
            return _ASSISTANT_SYSTEM_PROMPT + _THERAPY_MODE_PROMPT
        if mode == "legal":
            return _ASSISTANT_SYSTEM_PROMPT + _LEGAL_MODE_PROMPT
        return _ASSISTANT_SYSTEM_PROMPT

    async def converse(
        self,
        case: Case,
        user_message: str,
        history: List[Dict[str, str]],
        db: Any = None,
        mode: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Execute tool-calling loop grounded in case memory."""
        system_prompt = self._system_prompt(mode)

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

        safety_summary = ""
        if case.safety_plan:
            safety_summary = "\n".join(
                f"[{a.id}] {a.title} (Phase: {a.phase.value}, Status: {a.status.value})"
                for a in case.safety_plan.actions
            )

        location_line = case.location_context or (
            case.situation.location if case.situation else None
        )

        recent_history = "\n".join(
            f"{m.get('role', 'user')}: {m.get('content', '')}" for m in history[-6:]
        )

        context_prompt = (
            f"Case ID: {case.id}\n"
            f"Title: {case.title}\n"
            f"Category: {case.category}\n"
            f"Known location: {location_line or 'Not provided — do not guess one'}\n"
            f"Situation Summary: {case.situation.case_summary if case.situation else case.situation_text}\n"
            f"Known Facts: {case.situation.known_facts if case.situation else []}\n"
            f"User Claims: {case.situation.user_claims if case.situation else []}\n"
            f"Unknowns: {case.situation.unknowns if case.situation else []}\n\n"
            f"VERIFIED EVIDENCE:\n{evidence_summary}\n\n"
            f"ACTION PLAN STEPS:\n{action_summary or 'None'}\n\n"
            f"SAFETY PLAN STEPS:\n{safety_summary or 'None'}\n\n"
            f"RECENT CONVERSATION:\n{recent_history or 'None'}\n\n"
            f"User Question: {user_message}\n"
        )

        # 2. Select the tool
        tool_choice = await self._llm.structured_generate(
            system_prompt=system_prompt,
            user_prompt=context_prompt,
            output_schema=ToolCallChoice,
        )

        tool_name = tool_choice.tool_name
        args = tool_choice.arguments

        # Tool name and mode only. The user's message, their location and the
        # case contents must never reach the log.
        logger.info(
            "ChatAgent tool selected %s",
            log_fields(tool=tool_name, mode=mode or "default", case_id=case.id),
        )

        # 3. Execute it, isolated.
        #
        # The dispatch below is wrapped rather than inlined so that one tool
        # raising cannot take down the whole turn: a failed community lookup
        # should not stop the user getting an answer, and an unexpected
        # exception must never surface as a stack trace or an empty bubble.
        execution = await AgentExecution.run(
            f"chat_tool:{tool_name}",
            lambda: self._execute_tool(
                tool_name=tool_name,
                args=args,
                case=case,
                context_prompt=context_prompt,
                system_prompt=system_prompt,
                db=db,
                mode=mode,
            ),
            tool=tool_name,
            mode=mode or "default",
        )

        logger.info(
            "ChatAgent tool finished %s",
            log_fields(
                tool=tool_name,
                status=execution.status.value,
                duration_ms=execution.duration_ms,
                error_reason=execution.error.reason if execution.error else None,
            ),
        )

        if execution.ok and execution.result is not None:
            result = dict(execution.result)
            result.setdefault("trace_id", get_trace_id())
            return result

        # The tool raised. Say so plainly — never present a failure as a
        # completed action, and never fall back to answering from memory.
        return {
            "reply": (
                "I ran into a problem carrying that out, so I have stopped rather "
                "than guess. Nothing you told me has been lost — please try again "
                "in a moment.\n\n"
                "If you need help right now: 112 for emergencies, 181 for the "
                "women helpline."
            ),
            "tool_used": tool_name,
            "degraded_notice": (
                f"tool_failed: {execution.error.reason}" if execution.error else "tool_failed"
            ),
            "trace_id": get_trace_id(),
        }

    async def _execute_tool(
        self,
        *,
        tool_name: str,
        args: Dict[str, Any],
        case: Case,
        context_prompt: str,
        system_prompt: str,
        db: Any,
        mode: Optional[str],
    ) -> Dict[str, Any]:
        """Deterministic dispatch for the selected tool.

        Extracted from ``converse`` so the call can be timed, logged and
        isolated. The dispatch logic itself is unchanged — each branch still
        wraps an existing HerWay capability rather than reimplementing it.
        """
        if tool_name == "search_web":
            parsed_args = ToolSearchWeb.model_validate(args)
            outcome = await self._serpapi.search_detailed(
                query=parsed_args.query,
                vertical=SearchVertical.WEB,
                case_id=case.id,
                reason=parsed_args.reason,
            )
            if not outcome.success:
                return self._search_unavailable("web", parsed_args.query, outcome)
            if not outcome.results:
                return {
                    "reply": (
                        f"I searched for \"{parsed_args.query}\" but did not find anything "
                        f"useful. I would rather tell you that than guess. Could you give "
                        f"me a little more detail, or try different wording?"
                    ),
                    "tool_used": "search_web",
                    "searched_query": parsed_args.query,
                }

            res_summary = "\n".join(
                f"- {r.title}: {r.snippet} ({r.url})" for r in outcome.results[:4]
            )
            followup_prompt = (
                f"{context_prompt}\n\n"
                f"Live web search results for '{parsed_args.query}':\n{res_summary}\n\n"
                f"Answer using ONLY these results plus the case context. "
                f"Call tool 'answer_user' and include the exact URLs you used."
            )
            final_choice = await self._llm.structured_generate(
                system_prompt=system_prompt,
                user_prompt=followup_prompt,
                output_schema=ToolCallChoice,
            )
            if final_choice.tool_name == "answer_user":
                ans = ToolAnswerUser.model_validate(final_choice.arguments)
                return {
                    "reply": ans.text,
                    "sources": ans.source_urls or [r.url for r in outcome.results[:3] if r.url],
                    "searched_query": parsed_args.query,
                    "tool_used": "search_web",
                }
            return {
                "reply": f"Here is what I found for '{parsed_args.query}':\n\n{res_summary}",
                "sources": [r.url for r in outcome.results[:4] if r.url],
                "searched_query": parsed_args.query,
                "tool_used": "search_web",
            }

        elif tool_name == "search_news":
            parsed_args = ToolSearchNews.model_validate(args)
            outcome = await self._serpapi.search_detailed(
                query=parsed_args.query,
                vertical=SearchVertical.NEWS,
                case_id=case.id,
                reason=parsed_args.reason,
            )
            if not outcome.success:
                return self._search_unavailable("news", parsed_args.query, outcome)
            if not outcome.results:
                return {
                    "reply": (
                        f"I checked recent news for \"{parsed_args.query}\" and found nothing "
                        f"relevant. That may simply mean there has been no recent change."
                    ),
                    "tool_used": "search_news",
                    "searched_query": parsed_args.query,
                }
            res_summary = "\n".join(
                f"- {r.title} ({r.source or r.domain}, {r.published_at or 'date not stated'})\n  {r.snippet}\n  {r.url}"
                for r in outcome.results[:3]
            )
            return {
                "reply": f"Recent coverage for '{parsed_args.query}':\n\n{res_summary}",
                "sources": [r.url for r in outcome.results[:3] if r.url],
                "searched_query": parsed_args.query,
                "tool_used": "search_news",
            }

        elif tool_name == "search_local":
            parsed_args = ToolSearchLocal.model_validate(args)
            location = parsed_args.location or case.location_context or (
                case.situation.location if case.situation else None
            )
            if not location:
                return {
                    "reply": (
                        "I do not know where you are, and I will not guess. "
                        "Tell me your city or district and I will look for support "
                        "services near you."
                    ),
                    "tool_used": "search_local",
                }
            outcome = await self._serpapi.search_detailed(
                query=parsed_args.query,
                vertical=SearchVertical.MAPS,
                location=location,
                case_id=case.id,
                reason=parsed_args.reason,
            )
            if not outcome.success:
                return self._search_unavailable("local", parsed_args.query, outcome)
            if not outcome.results:
                return {
                    "reply": (
                        f"I searched near {location} but did not find a matching service. "
                        f"You can still reach the national women helpline on 181, or 112 in "
                        f"an emergency. Trying a nearby larger town may also help."
                    ),
                    "tool_used": "search_local",
                    "searched_query": parsed_args.query,
                }
            res_summary = "\n".join(self._format_place(r) for r in outcome.results[:4])
            return {
                "reply": (
                    f"Places near {location} matching '{parsed_args.query}':\n\n{res_summary}\n\n"
                    f"These come from public map listings. Please call ahead to confirm "
                    f"before travelling."
                ),
                "sources": [r.url for r in outcome.results[:4] if r.url],
                "searched_query": parsed_args.query,
                "tool_used": "search_local",
            }

        elif tool_name == "update_action_status":
            parsed_args = ToolUpdateActionStatus.model_validate(args)
            if db is None or not case.id:
                return {
                    "reply": "I can only update steps on a saved case.",
                    "tool_used": "update_action_status",
                }

            matched_title: Optional[str] = None
            if case.action_plan:
                for act in case.action_plan.actions:
                    if act.id == parsed_args.action_id:
                        act.status = parsed_args.status
                        matched_title = act.title
                if matched_title:
                    db["cases"].update_one(
                        {"_id": ObjectId(case.id)},
                        {"$set": {"action_plan": case.action_plan.model_dump()}},
                    )
            if case.safety_plan and not matched_title:
                for act in case.safety_plan.actions:
                    if act.id == parsed_args.action_id:
                        act.status = parsed_args.status
                        matched_title = act.title
                if matched_title:
                    db["cases"].update_one(
                        {"_id": ObjectId(case.id)},
                        {"$set": {"safety_plan": case.safety_plan.model_dump()}},
                    )

            if not matched_title:
                # Confirming an update that never happened is worse than failing.
                return {
                    "reply": (
                        "I could not find that step in your plan, so I have not changed "
                        "anything. You can tick steps off directly on the plan."
                    ),
                    "tool_used": "update_action_status",
                }

            return {
                "reply": f"Marked “{matched_title}” as {parsed_args.status.replace('_', ' ')}.",
                "tool_used": "update_action_status",
                "plan_adapted": True,
            }

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
                        f"I have updated your safety plan based on what you told me "
                        f"(*{parsed_args.state_change_reason}*). Your completed steps have "
                        f"been kept. Please review the new steps at the top of your plan."
                    ),
                    "safety_plan": adapted.model_dump(),
                    "plan_adapted": True,
                    "tool_used": "adapt_safety_plan",
                }
            return {
                "reply": (
                    "I have noted this update. This case does not have a safety plan yet — "
                    "you can run research on the case page to create one."
                ),
                "tool_used": "adapt_safety_plan",
            }

        elif tool_name == "search_safety_resources":
            parsed_args = ToolSearchSafetyResources.model_validate(args)
            loc = parsed_args.location or case.location_context or (
                case.situation.location if case.situation else None
            )
            if not loc:
                return {
                    "reply": (
                        "Tell me your city or district and I will look for support services "
                        "near you. I will not guess a location."
                    ),
                    "tool_used": "search_safety_resources",
                }

            outcome = await self._serpapi.search_detailed(
                query=parsed_args.query,
                vertical=SearchVertical.MAPS,
                location=loc,
                case_id=case.id,
                reason=parsed_args.reason,
            )
            if not outcome.success:
                return self._search_unavailable("local", parsed_args.query, outcome)
            if not outcome.results:
                return {
                    "reply": (
                        f"I searched near {loc} for '{parsed_args.query}' and found nothing. "
                        f"The women helpline on 181 can refer you to the nearest One Stop "
                        f"Centre, and 112 reaches police anywhere in India."
                    ),
                    "tool_used": "search_safety_resources",
                    "searched_query": parsed_args.query,
                }

            from backend.models.safety_plan import SafetyMatchedResource
            from backend.services.maps_service import MapsService

            added = 0
            if case.safety_plan and db is not None and case.id:
                existing_names = {r.name for r in case.safety_plan.matched_resources}
                for idx, r in enumerate(outcome.results[:4]):
                    if not r.title or r.title in existing_names:
                        continue
                    existing_names.add(r.title)
                    domain = MapsService._domain_of(r.url)
                    verification, note = MapsService._classify(r.title, domain)
                    case.safety_plan.matched_resources.append(
                        SafetyMatchedResource(
                            id=f"RES_CHAT_{idx + 1:02d}",
                            name=r.title,
                            category="shelter" if "shelter" in r.title.lower() else "crisis_center",
                            phone=r.phone,
                            address=r.address,
                            url=r.url,
                            rating=r.rating,
                            source_domain=domain,
                            # Honest provenance — a map listing is not a verified
                            # government service until we have checked it.
                            verification=verification,
                            verification_note=note,
                            notes=f"Found by searching for '{parsed_args.query}' near {loc}.",
                        )
                    )
                    added += 1
                if added:
                    db["cases"].update_one(
                        {"_id": ObjectId(case.id)},
                        {"$set": {"safety_plan": case.safety_plan.model_dump()}},
                    )

            res_summary = "\n".join(self._format_place(r) for r in outcome.results[:4])
            tail = (
                f"\n\nI have added {added} of these to your plan's resources."
                if added
                else ""
            )
            return {
                "reply": (
                    f"Here is what I found near {loc} for '{parsed_args.query}':\n\n{res_summary}\n\n"
                    f"These are public map listings, not confirmed government records. "
                    f"Please call before travelling.{tail}"
                ),
                "sources": [r.url for r in outcome.results[:4] if r.url],
                "searched_query": parsed_args.query,
                "tool_used": "search_safety_resources",
                "plan_adapted": added > 0,
            }

        elif tool_name == "invoke_lawbot":
            # ── Reuse existing Haven RAG pipeline ──────────────────────────
            parsed_args = ToolInvokeLawbot.model_validate(args)
            embedding_svc = EmbeddingService()
            # NOTE: `search_legal_docs` returns [] both when nothing matched and
            # when retrieval is unavailable (missing Atlas index, embedding
            # outage) — see docs/KNOWN_ISSUES.md B-02. Either way the branch
            # below goes to live official sources instead of answering from the
            # model's own memory, which is the behaviour that actually matters
            # for a legal question: an invented section number is worse than no
            # answer.
            docs = embedding_svc.search_legal_docs(query=parsed_args.question, top_k=3)
            logger.info(
                "ChatAgent lawbot retrieval %s",
                log_fields(documents_found=len(docs), fell_back_to_search=not docs),
            )

            if docs:
                doc_context = "\n".join(
                    f"- [{d.get('filename', 'Document')}]: {d.get('content', '')[:300]}"
                    for d in docs
                )
                followup_prompt = (
                    f"{context_prompt}\n\n"
                    f"Legal RAG Results for '{parsed_args.question}':\n{doc_context}\n\n"
                    f"Now provide a clear, accurate legal answer using tool 'answer_user'."
                )
                final_choice = await self._llm.structured_generate(
                    system_prompt=self._system_prompt(mode or "legal"),
                    user_prompt=followup_prompt,
                    output_schema=ToolCallChoice,
                )
                if final_choice.tool_name == "answer_user":
                    ans = ToolAnswerUser.model_validate(final_choice.arguments)
                    return {
                        "reply": ans.text,
                        "sources": ans.source_urls,
                        "lawbot_docs": [d.get("filename") for d in docs if d.get("filename")],
                        "tool_used": "invoke_lawbot",
                    }
                return {
                    "reply": f"Here is what the legal documents say:\n\n{doc_context}",
                    "lawbot_docs": [d.get("filename") for d in docs if d.get("filename")],
                    "tool_used": "invoke_lawbot",
                }
            else:
                # No indexed legal document matched — go to live official sources
                # rather than answering from model memory.
                outcome = await self._serpapi.search_detailed(
                    query=f"{parsed_args.question} India law site:indiacode.nic.in OR site:gov.in",
                    vertical=SearchVertical.WEB,
                    case_id=case.id,
                    reason=f"Legal lookup: {parsed_args.reason}",
                )
                if not outcome.success:
                    return self._search_unavailable("web", parsed_args.question, outcome)
                if not outcome.results:
                    return {
                        "reply": (
                            f"I could not find an authoritative source for "
                            f"\"{parsed_args.question}\", so I am not going to state the law "
                            f"from memory.\n\n"
                            f"**Needs verification:** please check with a legal aid lawyer. "
                            f"Free legal aid is available to women through your District Legal "
                            f"Services Authority (DLSA) — see nalsa.gov.in."
                        ),
                        "tool_used": "invoke_lawbot",
                        "searched_query": parsed_args.question,
                    }

                res_summary = "\n".join(
                    f"- {r.title} ({r.domain})\n  {r.snippet}\n  {r.url}"
                    for r in outcome.results[:3]
                )
                return {
                    "reply": (
                        f"I did not have an indexed document for this, so I searched official "
                        f"sources for \"{parsed_args.question}\":\n\n{res_summary}\n\n"
                        f"*This is legal information, not legal advice. Free legal aid is "
                        f"available to women through DLSA/NALSA.*"
                    ),
                    "sources": [r.url for r in outcome.results[:3] if r.url],
                    "searched_query": parsed_args.question,
                    "tool_used": "invoke_lawbot",
                }

        elif tool_name == "search_community":
            # ── Reuse existing Haven community embedding search ─────────────
            parsed_args = ToolSearchCommunity.model_validate(args)
            embedding_svc = EmbeddingService()
            posts = embedding_svc.search_community_posts(query=parsed_args.query, top_k=3)
            safe_posts = [_redact_community_post(p) for p in posts]

            if safe_posts:
                post_summary = "\n".join(
                    f"- {p.get('name') or 'Anonymous'}"
                    + (f" · {p['location']}" if p.get("location") else "")
                    + (f" · severity: {p['severity']}" if p.get("severity") else "")
                    for p in safe_posts
                )
                return {
                    "reply": (
                        f"Other women have shared experiences like yours:\n\n{post_summary}\n\n"
                        f"You are not alone. You can also share your own experience "
                        f"anonymously if that would help."
                    ),
                    "community_posts": safe_posts,
                    "tool_used": "search_community",
                }
            return {
                "reply": (
                    "I did not find a closely matching community post right now. "
                    "That does not mean no one has been through this — you can share "
                    "your experience anonymously to connect with others."
                ),
                "community_posts": [],
                "tool_used": "search_community",
            }

        elif tool_name == "encode_message":
            # ── Point at the real encode/decode flow ───────────────────────
            parsed_args = ToolEncodeMessage.model_validate(args)
            return {
                "reply": (
                    "You can hide a message inside an ordinary-looking photo, so the image "
                    "looks like any other picture if someone checks your phone.\n\n"
                    "**How to do it:**\n"
                    "1. Open **Discreet message** from the menu.\n"
                    "2. Upload an ordinary photo (a PNG works best).\n"
                    "3. Type your message and download the new image.\n"
                    "4. Send that image normally. The person receiving it opens the same "
                    "page, chooses **Read a message**, and uploads it.\n\n"
                    "**Please read this before you rely on it:** this hides the message from "
                    "a casual look. It is not encryption. Someone with technical skill, or an "
                    "app that monitors your phone, could still find it. WhatsApp and Instagram "
                    "re-compress photos, which destroys the hidden message — send the file as "
                    "a *document*, or by email.\n\n"
                    f"Your message would be: *{parsed_args.message[:120]}"
                    f"{'…' if len(parsed_args.message) > 120 else ''}*"
                ),
                "tool_used": "encode_message",
            }

        elif tool_name == "generate_formal_report":
            # ── Reuse existing Haven text-expansion pipeline ───────────────
            parsed_args = ToolGenerateFormalReport.model_validate(args)
            report_svc = ReportService()
            try:
                result = await report_svc.generate_formal_report(
                    situation_text=parsed_args.situation_summary,
                    location=parsed_args.location or (case.situation.location if case.situation else case.location_context),
                )
                report_text = result.get("gemini_response") or result.get("gemma_response") or ""
                if not report_text.strip():
                    raise RuntimeError("Both report generators returned empty text")
                return {
                    "reply": (
                        f"Here is a draft you can take to a police station, the National "
                        f"Commission for Women, or a POSH Internal Committee:\n\n"
                        f"---\n\n{report_text}\n\n---\n\n"
                        f"*Please read it through and correct anything that is not accurate "
                        f"before you submit it. You are not required to use these words.*"
                    ),
                    "formal_report": report_text,
                    "tool_used": "generate_formal_report",
                }
            except Exception as exc:
                logger.warning("ChatAgent: formal report generation failed: %s", exc)
                return {
                    "reply": (
                        "I could not draft the report just now. Nothing has been lost — "
                        "please try again shortly. You can also write it in your own words; "
                        "a complaint does not have to be formal to be valid."
                    ),
                    "tool_used": "generate_formal_report",
                    "degraded_notice": "report_generation_failed",
                }

        elif tool_name == "generate_poem":
            # ── Reuse existing Haven poem-generation pipeline ──────────────
            parsed_args = ToolGeneratePoem.model_validate(args)
            report_svc = ReportService()
            try:
                poem = report_svc.generate_poem(
                    parsed_args.context or case.situation_text[:200]
                )
            except Exception as exc:
                # A comfort feature failing must not cost the user their turn.
                logger.warning(
                    "ChatAgent poem generation failed %s",
                    log_fields(reason=type(exc).__name__),
                )
                poem = ""
            if not (poem or "").strip():
                return {
                    "reply": (
                        "I could not find the right words just now. That does not "
                        "change what I think of you for reaching out. Is there "
                        "something practical I can help with instead?"
                    ),
                    "tool_used": "generate_poem",
                    "degraded_notice": "poem_generation_failed",
                }
            return {
                "reply": f"A few words for you:\n\n*{poem}*\n\nYou are not alone in this.",
                "tool_used": "generate_poem",
            }

        else:
            # Default: answer_user. If the model returned something unparseable,
            # say so rather than emitting an empty bubble.
            try:
                ans = ToolAnswerUser.model_validate(args)
            except Exception as exc:
                logger.warning("ChatAgent: could not parse answer_user args: %s", exc)
                return {
                    "reply": (
                        "I did not manage to put that into words properly. "
                        "Could you ask me again, perhaps a little differently?"
                    ),
                    "tool_used": "answer_user",
                    "degraded_notice": "answer_parse_failed",
                }
            return {
                "reply": ans.text,
                "sources": ans.source_urls,
                "tool_used": "answer_user",
            }
