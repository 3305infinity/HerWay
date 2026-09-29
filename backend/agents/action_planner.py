"""
ActionPlanner — Action Planning Agent (Stage 4 of Haven pipeline).

Responsibility
--------------
Accept a ``FinalResearchReport`` (containing ``Situation`` and verified ``EvidenceItem`` s)
and synthesize a concrete, structured ``ActionPlan``.

Strict Rules
------------
1. Every major action MUST reference one or more evidence_ids (e.g., ['EVIDENCE_01']).
2. DO NOT generate unsupported recommendations or invent deadlines.
3. Categorize timing phases cleanly:
   - immediate_actions ("DO NOW")
   - next_actions ("NEXT")
   - escalation_options ("IF THAT DOES NOT WORK")
4. Provide concrete checklists of evidence to collect, contacts, links, and things to avoid.
5. Clearly distinguish information from legal/medical advice.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, List

from backend.models.action_plan import (
    ActionItem,
    ActionPlan,
    ActionPriority,
    ActionStatus,
    ActionTimingPhase,
)
from backend.models.research import FinalResearchReport

if TYPE_CHECKING:
    from backend.services.llm_service import LLMService

logger = logging.getLogger(__name__)

_PLANNER_SYSTEM_PROMPT = """\
You are the Action Planning Agent for HerWay.

You receive a research report with:
- Situation summary, category, user goal, known facts, user claims, and unknowns.
- A list of verified EvidenceItem objects (each with an id like EVIDENCE_01, title, url, extracted facts).

Your Task:
Synthesize this evidence into a structured, highly actionable step-by-step resolution plan.

RULES:
1. WOMEN'S SAFETY & PROTECTION CASES (domestic_violence, sexual_harassment, stalking, online_harassment, threats, coercive_control, unsafe_relationship, workplace_harassment, other_women_safety, safety):
   - SAFETY FIRST ORDERING:
     immediate_actions: IMMEDIATE SAFETY & EMERGENCY RESOURCES (e.g. Move to a safe location if needed, contact emergency helplines 112/181/1091, reach out to trusted person).
     next_actions: SUPPORT OPTIONS & CONDITIONAL EVIDENCE PRESERVATION (e.g. Contact verified women's support center, save screenshots/messages ONLY IF SAFE to do so without escalating danger).
     escalation_options: FORMAL REPORTING & LEGAL OPTIONS (e.g. File complaint at Women's Police Cell or One Stop Centre Sakhi, POSH committee).
   - STRICT SAFETY MANDATE:
     - DO NOT tell a user to confront an abuser.
     - DO NOT generate dangerous instructions.
     - Conditional Evidence Preservation: Explicitly state "Preserve messages/screenshots ONLY if safe to do so."

2. EVIDENCE LINKING:
   - Every single ActionItem MUST include `evidence_ids` containing the exact IDs (e.g. ["EVIDENCE_01"]) of the supporting evidence items.
   - Do NOT suggest actions that are unsupported by the retrieved evidence.

3. CONCRETE ADVICE & CHECKLISTS:
   - Provide concrete, checklist-style instructions.
   - Do NOT invent deadlines unless explicitly stated in an evidence item.
   - documents_or_evidence_to_collect: Specific paperwork, screenshots, or receipts to collect (with safety caveat).
   - things_to_avoid: Dangerous mistakes (e.g. "Do not confront perpetrator alone", "Do not share passwords").

Respond ONLY with valid JSON matching the ActionPlan schema.
"""


class ActionPlanner:
    """Synthesizes verified evidence into concrete, evidence-backed action plans."""

    def __init__(self, llm: LLMService) -> None:
        self._llm = llm

    async def plan(self, report: FinalResearchReport) -> ActionPlan:
        """Generate a structured ActionPlan for a case."""
        evidence_text = "\n\n".join(
            f"ID: {e.id}\nTitle: {e.source_title}\nURL: {e.url or 'N/A'}\n"
            f"Facts: {e.extracted_facts}\nConfidence Score: {e.confidence_score}\n"
            f"Relevance: {e.why_this_source_matters}"
            for e in report.evidence
        )

        prompt = (
            f"Case ID: {report.case_id}\n"
            f"Summary: {report.situation.case_summary}\n"
            f"User Goal: {report.situation.user_goal}\n"
            f"Known Facts: {report.situation.known_facts}\n"
            f"User Claims: {report.situation.user_claims}\n"
            f"Unknowns: {report.situation.unknowns}\n"
            f"Missing Info Questions: {report.situation.missing_information}\n\n"
            f"VERIFIED EVIDENCE ({len(report.evidence)} items):\n{evidence_text or 'No verified evidence items.'}"
        )

        plan_result = await self._llm.structured_generate(
            system_prompt=_PLANNER_SYSTEM_PROMPT,
            user_prompt=prompt,
            output_schema=ActionPlan,
        )
        plan_result.case_id = report.case_id

        # Combine actions into flattened list for compatibility if empty
        all_actions: List[ActionItem] = []
        for idx, act in enumerate(plan_result.immediate_actions):
            act.timing_phase = ActionTimingPhase.DO_NOW
            if not act.id:
                act.id = f"ACTION_NOW_{idx + 1:02d}"
            all_actions.append(act)

        for idx, act in enumerate(plan_result.next_actions):
            act.timing_phase = ActionTimingPhase.NEXT
            if not act.id:
                act.id = f"ACTION_NEXT_{idx + 1:02d}"
            all_actions.append(act)

        for idx, act in enumerate(plan_result.escalation_options):
            act.timing_phase = ActionTimingPhase.IF_THAT_DOES_NOT_WORK
            if not act.id:
                act.id = f"ACTION_ESC_{idx + 1:02d}"
            all_actions.append(act)

        if not plan_result.actions and all_actions:
            plan_result.actions = all_actions

        logger.info(
            "ActionPlanner: Generated %d immediate, %d next, %d escalation actions for case %s",
            len(plan_result.immediate_actions),
            len(plan_result.next_actions),
            len(plan_result.escalation_options),
            report.case_id,
        )

        return plan_result

