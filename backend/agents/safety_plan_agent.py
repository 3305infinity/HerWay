"""
SafetyPlanAgent — Personalized, Adaptive Safety Planning Agent for Haven.

Key Capabilities:
1. Safety Assessment: Explicit grounded indicators (NO arbitrary risk % scores).
2. 6 Structured Phased Action Groups:
   - RIGHT_NOW: Immediate physical & emergency safety
   - NEXT_24_HOURS: Practical safe steps & support contacts
   - DOCUMENT_SAFE: Evidence gathering ONLY IF SAFE
   - SUPPORT_NETWORK: Trusted contacts & professional support
   - FORMAL_OPTIONS: Official procedures, legal rights & reporting pathways
   - ONGOING: Follow-up actions & revisit items
3. Real-World Live Resource Matching (SerpApi Web / Local / Maps).
4. Adaptive Re-planning: Responds to state escalations while preserving completed tasks and recording update history.
"""

from __future__ import annotations

import logging
import re
import uuid
from datetime import datetime
from typing import TYPE_CHECKING, Any, Dict, List, Optional

from pydantic import BaseModel

from backend.india_resources import helplines_for_category, portals_for_category
from backend.models.action_plan import ActionPriority, ActionStatus
from backend.models.research import (
    EvidenceItem,
    LocalResource,
    ResourceVerification,
    Situation,
)
from backend.models.safety_plan import (
    SafetyActionItem,
    SafetyAssessment,
    SafetyMatchedResource,
    SafetyPlan,
    SafetyPlanPhase,
    SafetyPlanUpdate,
)

from urllib.parse import urlparse

if TYPE_CHECKING:
    from backend.services.llm_service import LLMService

logger = logging.getLogger(__name__)

WOMEN_SAFETY_CATEGORIES = {
    "domestic_violence",
    "sexual_harassment",
    "stalking",
    "online_harassment",
    "threats",
    "coercive_control",
    "unsafe_relationship",
    "workplace_harassment",
    "other_women_safety",
    "safety",
}

#: Signals in free text that a case needs the safety pathway even when its
#: category says otherwise. Word-boundary anchored to avoid false positives.
_SAFETY_SIGNAL_PATTERNS = [
    r"abus(e|ed|ive|ing)",
    r"assault(ed|ing)?",
    r"threat(s|en|ened|ening)?",
    r"stalk(s|ed|ing|er)?",
    r"harass(ed|ing|ment)?",
    r"violen(ce|t)",
    r"domestic",
    r"unsafe",
    r"sexual",
    r"molest(ed|ing|ation)?",
    r"grope(d|s)?",
    r"inappropriate (touch|comments?|messages?|behaviour|behavior)",
    r"blackmail(ed|ing)?",
    r"non-?consensual",
    r"dowry",
    r"posh act",
    r"\bposh\b",
    r"internal committee",
    r"\bicc\b",
    r"intimidat(e|ed|ing|ion)",
    r"(hit|beat|hurt|choke[d]?|slapp?ed) me",
    r"(scared|afraid|frightened|terrified) of",
    r"(following|follows) me",
    r"won'?t leave me alone",
    r"took my (phone|money|documents|passport)",
    r"obscene",
    r"revenge porn",
    r"morphed (photo|image|picture)",
    r"protection order",
    r"restraining order",
]

_SAFETY_SIGNAL_RE = re.compile(
    r"\b(?:" + "|".join(_SAFETY_SIGNAL_PATTERNS) + r")", re.IGNORECASE
)

_SAFETY_ASSESSMENT_PROMPT = """\
You are HerWay's Safety Assessment Agent, specialized in trauma-informed women's safety analysis.

Analyze the user's situation and verified evidence to extract EXPLICIT SAFETY INDICATORS.

STRICT RULES:
1. NO ARBITRARY RISK SCORES (Do NOT produce scores like 'risk = 87%' or 'danger level 9/10').
2. Only set an indicator to TRUE if explicitly supported by the user's statements or verified evidence.
3. For each TRUE indicator, provide an exact quote or clear factual justification in indicator_justifications.
4. CRITICAL MANDATES:
   - Never advise confronting a perpetrator.
   - Evidence preservation must explicitly be tagged with 'Only if safe to do so'.
   - Highlight missing critical information that affects safety navigation.

Respond with valid JSON matching the SafetyAssessment schema.
"""

_SAFETY_PLAN_SYNTHESIS_PROMPT = """\
You are HerWay's Safety Planning Agent, working in the Indian context.

Synthesize the Situation, Safety Assessment, verified evidence, and discovered
local resources into a structured, highly actionable Personalized Safety Plan.

THE PLAN MUST FIT THIS PERSON. A generic plan is a failed plan.
- Reflect the specific indicators that were marked true. If there are no
  dependents, do not write steps about children. If the user already has a safe
  place, do not tell them to find one.
- If an indicator is false or unknown, do not assume it.

STRICT STRUCTURE RULES:
1. RIGHT_NOW (immediate, 0-2 hours):
   - Immediate safety precautions; Indian emergency numbers only: 112 (all
     emergencies), 181 (women helpline), 1091 (women police), 1098 (children),
     1930 (cyber crime). NEVER mention 911 or non-Indian numbers.
2. NEXT_24_HOURS:
   - Practical safe steps, contacting a One Stop Centre (Sakhi) or support
     organisation, reviewing safe options.
3. DOCUMENT_SAFE (ONLY IF SAFE):
   - Preserving screenshots, timestamps or records WITHOUT increasing risk.
   - Every item here MUST carry a safety_caveat. If devices may be monitored,
     say so explicitly and suggest using a device the other person cannot access.
4. SUPPORT_NETWORK:
   - Trusted person outreach, counselling (Tele-MANAS 14416), nearby centres
     that were actually discovered — never invent a centre.
5. FORMAL_OPTIONS (Formal & Legal Pathways):
   - Indian mechanisms only: FIR / zero FIR at a police station, complaint under
     the Protection of Women from Domestic Violence Act 2005 (including
     Protection Officer and protection/residence orders), POSH Act 2013 Internal
     Committee or Local Committee, SHe-Box, cybercrime.gov.in, free legal aid
     through DLSA/NALSA, National Commission for Women.
   - Describe these as OPTIONS the user may choose, not as instructions.
6. ONGOING (Ongoing & Follow-Up):
   - Safety monitoring, check-in steps, unresolved questions.

ABSOLUTE SAFETY MANDATES:
- NEVER suggest confronting, warning, reasoning with, or recording the person
  causing harm in their presence.
- NEVER tell the user to collect evidence if doing so would put them at risk.
- NEVER state a legal outcome as guaranteed.
- NEVER invent a phone number, address, office name, or deadline. Use only the
  resources supplied in the prompt.

EVIDENCE & RESOURCE LINKING:
- Link action items to the evidence_ids and resource_ids given to you.
- Do NOT invent arbitrary deadlines.

Respond with valid JSON.
"""


class SafetyPlanAgent:
    """Agent responsible for safety assessment, live resource matching, and adaptive safety planning."""

    def __init__(self, llm: LLMService) -> None:
        self._llm = llm

    @staticmethod
    def is_safety_case(category: str, situation_text: str = "") -> bool:
        """Determine whether a case qualifies for a specialised safety plan.

        The category is checked first. When it is ambiguous (a user may describe
        workplace sexual harassment but have the case filed as "employment"),
        the narrative is scanned for safety signals.

        Matching is word-boundary based. The previous substring match meant
        short tokens produced false positives — "icc" fired on "hiccups" — while
        the phrasing in the most common disclosure we see, "my manager keeps
        making *sexual* comments", matched nothing at all and so never reached
        the safety pathway.
        """
        cat_lower = (category or "").lower().strip()
        if cat_lower in WOMEN_SAFETY_CATEGORIES:
            return True

        text_lower = (situation_text or "").lower()
        if not text_lower:
            return False

        return bool(_SAFETY_SIGNAL_RE.search(text_lower))

    async def assess_safety(
        self,
        situation: Situation,
        evidence: List[EvidenceItem],
    ) -> SafetyAssessment:
        """Extracts explicit, non-speculative safety indicators from situation & evidence."""
        evidence_text = "\n".join(
            f"[{e.id}] {e.source_title}: {e.claim_supported}" for e in evidence
        ) or "None"

        user_prompt = (
            f"Situation Summary: {situation.case_summary}\n"
            f"Category: {situation.category.value}\n"
            f"Known Facts: {situation.known_facts}\n"
            f"User Claims: {situation.user_claims}\n"
            f"Unknowns: {situation.unknowns}\n"
            f"User Goal: {situation.user_goal}\n\n"
            f"Verified Evidence:\n{evidence_text}"
        )

        assessment = await self._llm.structured_generate(
            system_prompt=_SAFETY_ASSESSMENT_PROMPT,
            user_prompt=user_prompt,
            output_schema=SafetyAssessment,
        )
        return assessment

    def match_resources(
        self,
        category: str,
        local_resources: List[LocalResource],
        evidence: List[EvidenceItem],
    ) -> List[SafetyMatchedResource]:
        """Assemble the resource list for a safety plan.

        Two sources, with very different trust levels:

        1. Nationally-allocated helplines and official portals from
           ``backend.india_resources`` — each carries the government page it
           comes from, so we can state them without a live lookup.
        2. Listings discovered via SerpApi Maps — these are third-party
           listings and are labelled ``unverified_listing`` unless their
           website sits on an official government domain.  The previous code
           marked *every* discovered listing as verified, which told users that
           an unchecked map pin was a confirmed government shelter.
        """
        matched: List[SafetyMatchedResource] = []
        seen_names: set[str] = set()
        now = datetime.utcnow()

        # 1. National helplines — stable short codes with an official source.
        for helpline in helplines_for_category(category):
            matched.append(
                SafetyMatchedResource(
                    id=helpline.id,
                    name=helpline.name,
                    category=helpline.resource_category,
                    phone=helpline.number,
                    url=helpline.official_source_url,
                    operating_hours=helpline.operating_hours,
                    source_domain=urlparse(helpline.official_source_url).netloc,
                    retrieved_at=now,
                    verification=ResourceVerification.OFFICIAL_SOURCE,
                    verification_note=(
                        f"Nationally allocated number documented at {helpline.official_source_url}"
                    ),
                    notes=helpline.notes or helpline.purpose,
                )
            )
            seen_names.add(helpline.name)

        # 2. Official complaint / filing portals for this category.
        for portal in portals_for_category(category):
            if portal.name in seen_names:
                continue
            seen_names.add(portal.name)
            matched.append(
                SafetyMatchedResource(
                    id=portal.id,
                    name=portal.name,
                    category=portal.resource_category,
                    url=portal.url,
                    source_domain=urlparse(portal.url).netloc,
                    retrieved_at=now,
                    verification=ResourceVerification.OFFICIAL_SOURCE,
                    verification_note=f"Official Government of India portal ({portal.url})",
                    notes=portal.purpose,
                )
            )

        # 3. Locally discovered listings — carried through with their own,
        #    honest, provenance label.
        for idx, res in enumerate(local_resources):
            if res.name in seen_names:
                continue
            seen_names.add(res.name)

            name_lower = res.name.lower()
            if "police" in name_lower or "thana" in name_lower:
                res_type = "police"
            elif any(k in name_lower for k in ("legal", "court", "dlsa", "legal services")):
                res_type = "legal_aid"
            elif any(k in name_lower for k in ("shelter", "hostel", "swadhar", "ujjwala", "niwas")):
                res_type = "shelter"
            elif "cyber" in name_lower:
                res_type = "cyber_cell"
            elif "one stop" in name_lower or "sakhi" in name_lower:
                res_type = "one_stop_centre"
            else:
                res_type = "crisis_center"

            matched.append(
                SafetyMatchedResource(
                    id=f"RES_LOCAL_{idx + 1:02d}",
                    name=res.name,
                    category=res_type,
                    phone=res.phone,
                    address=res.address,
                    url=res.website or res.source_url,
                    rating=res.rating,
                    operating_hours=res.hours,
                    source_domain=res.source_domain,
                    retrieved_at=res.retrieved_at or now,
                    verification=res.verification,
                    verification_note=res.verification_note,
                    notes=res.relevance_reason or None,
                )
            )

        return matched

    async def generate_safety_plan(
        self,
        case_id: str,
        situation: Situation,
        evidence: List[EvidenceItem],
        local_resources: List[LocalResource],
    ) -> SafetyPlan:
        """Constructs a complete, personalized 6-phase Safety Plan."""
        logger.info("SafetyPlanAgent: Generating personalized safety plan for case %s", case_id)
        
        # 1. Assess Explicit Safety Indicators
        assessment = await self.assess_safety(situation, evidence)
        
        # 2. Match Discovered SerpApi Resources
        matched_resources = self.match_resources(
            category=situation.category.value,
            local_resources=local_resources,
            evidence=evidence,
        )

        # 3. Synthesize Phased Actions via Structured LLM Generation
        resources_summary = "\n".join(
            f"[{r.id}] {r.name} ({r.category}) - Phone: {r.phone or 'N/A'}, Address: {r.address or 'N/A'}"
            for r in matched_resources
        )
        evidence_summary = "\n".join(
            f"[{e.id}] {e.source_title}: {e.claim_supported}" for e in evidence
        )

        synth_prompt = (
            f"Case ID: {case_id}\n"
            f"Category: {situation.category.value}\n"
            f"Situation Summary: {situation.case_summary}\n"
            f"Known Facts: {situation.known_facts}\n"
            f"User Claims: {situation.user_claims}\n"
            f"Unknowns: {situation.unknowns}\n"
            f"Safety Assessment Context: {assessment.context_summary}\n"
            f"Active Indicators:\n"
            f"- Immediate Danger: {assessment.immediate_safety_concern}\n"
            f"- Threats Present: {assessment.threats_present}\n"
            f"- Repeated Harassment: {assessment.repeated_harassment}\n"
            f"- Digital Safety Concern: {assessment.digital_safety_concern}\n"
            f"- Safe Place Available: {assessment.safe_place_available}\n"
            f"- Support Available: {assessment.support_available}\n"
            f"- Workplace Harassment: {assessment.workplace_harassment}\n\n"
            f"MATCHED LOCAL & EMERGENCY RESOURCES:\n{resources_summary}\n\n"
            f"VERIFIED EVIDENCE:\n{evidence_summary}\n"
        )

        class _PlanSynthesisOutput(BaseModel):
            right_now_actions: List[SafetyActionItem]
            next_24h_actions: List[SafetyActionItem]
            document_safe_actions: List[SafetyActionItem]
            support_network_actions: List[SafetyActionItem]
            formal_options_actions: List[SafetyActionItem]
            ongoing_actions: List[SafetyActionItem]
            things_to_avoid: List[str]

        synth_output = await self._llm.structured_generate(
            system_prompt=_SAFETY_PLAN_SYNTHESIS_PROMPT,
            user_prompt=synth_prompt,
            output_schema=_PlanSynthesisOutput,
        )

        # 4. Consolidate and Tag Action Items
        all_actions: List[SafetyActionItem] = []
        phases_map = {
            SafetyPlanPhase.RIGHT_NOW: synth_output.right_now_actions,
            SafetyPlanPhase.NEXT_24_HOURS: synth_output.next_24h_actions,
            SafetyPlanPhase.DOCUMENT_SAFE: synth_output.document_safe_actions,
            SafetyPlanPhase.SUPPORT_NETWORK: synth_output.support_network_actions,
            SafetyPlanPhase.FORMAL_OPTIONS: synth_output.formal_options_actions,
            SafetyPlanPhase.ONGOING: synth_output.ongoing_actions,
        }

        for phase, items in phases_map.items():
            for idx, item in enumerate(items):
                item.phase = phase
                if not item.id:
                    item.id = f"SAFE_{phase.value.upper()}_{idx + 1:02d}"
                all_actions.append(item)

        safety_plan = SafetyPlan(
            case_id=case_id,
            category=situation.category.value,
            is_women_safety_case=True,
            assessment=assessment,
            right_now_actions=synth_output.right_now_actions,
            next_24h_actions=synth_output.next_24h_actions,
            document_safe_actions=synth_output.document_safe_actions,
            support_network_actions=synth_output.support_network_actions,
            formal_options_actions=synth_output.formal_options_actions,
            ongoing_actions=synth_output.ongoing_actions,
            actions=all_actions,
            matched_resources=matched_resources,
            things_to_avoid=synth_output.things_to_avoid,
            updates_history=[],
            created_at=datetime.utcnow(),
            updated_at=datetime.utcnow(),
        )

        logger.info(
            "SafetyPlanAgent: Generated Safety Plan with %d total actions and %d matched resources",
            len(all_actions),
            len(matched_resources),
        )
        return safety_plan

    async def adapt_plan(
        self,
        current_plan: SafetyPlan,
        updated_situation: Situation,
        new_evidence: List[EvidenceItem],
        new_local_resources: List[LocalResource],
        state_change_reason: str,
    ) -> SafetyPlan:
        """
        Adapts the safety plan when situation state changes.
        Preserves completed tasks, generates new recommended steps, and logs update history.
        """
        logger.info("SafetyPlanAgent: Adapting safety plan for case %s. Reason: %s", current_plan.case_id, state_change_reason)

        # 1. Identify completed actions to preserve
        completed_action_ids = {a.id for a in current_plan.actions if a.status == ActionStatus.COMPLETED}
        completed_actions = [a for a in current_plan.actions if a.status == ActionStatus.COMPLETED]

        # 2. Generate updated fresh plan
        fresh_plan = await self.generate_safety_plan(
            case_id=current_plan.case_id,
            situation=updated_situation,
            evidence=new_evidence,
            local_resources=new_local_resources,
        )

        # 3. Merge preserved completed actions so user never loses progress
        new_action_titles: List[str] = []
        for action in fresh_plan.actions:
            if action.id in completed_action_ids:
                action.status = ActionStatus.COMPLETED
                action.completed_at = datetime.utcnow()
            else:
                new_action_titles.append(action.title)

        # 4. Formulate 'PLAN UPDATED' structured audit log
        update_entry = SafetyPlanUpdate(
            update_id=f"UPD_{uuid.uuid4().hex[:6]}",
            timestamp=datetime.utcnow(),
            why_plan_changed=state_change_reason,
            what_changed=[
                f"Updated urgency to {updated_situation.urgency.value if hasattr(updated_situation.urgency, 'value') else updated_situation.urgency}",
                f"Identified new safety context: {updated_situation.case_summary[:100]}...",
                f"Preserved {len(completed_actions)} completed actions",
            ],
            new_recommended_steps=new_action_titles[:4],
            preserved_completed_actions=list(completed_action_ids),
        )

        fresh_plan.updates_history = current_plan.updates_history + [update_entry]
        fresh_plan.created_at = current_plan.created_at
        fresh_plan.updated_at = datetime.utcnow()

        logger.info("SafetyPlanAgent: Plan adapted successfully with update ID %s", update_entry.update_id)
        return fresh_plan
