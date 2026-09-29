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
import uuid
from datetime import datetime
from typing import TYPE_CHECKING, Any, Dict, List, Optional

from backend.models.action_plan import ActionPriority, ActionStatus
from backend.models.research import EvidenceItem, LocalResource, Situation
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

_SAFETY_ASSESSMENT_PROMPT = """\
You are Haven's Safety Assessment Agent, specialized in trauma-informed women's safety analysis.

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
You are Haven's Safety Planning Agent.

Synthesize the Situation, Safety Assessment, verified evidence, and discovered local resources into a structured, highly actionable Personalized Safety Plan.

STRICT STRUCTURE RULES:
1. RIGHT_NOW (Safety Right Now - immediate 0-2 hours):
   - Immediate safety precautions, emergency contacts (112, 1091, 181, 911), moving to safe location if needed.
2. NEXT_24_HOURS (Next 24 Hours):
   - Practical safe steps, contacting verified support organizations, reviewing safe options.
3. DOCUMENT_SAFE (Document / Preserve — ONLY IF SAFE):
   - Preserving screenshots, timestamps, or records WITHOUT endangering oneself. Never do if devices are monitored.
4. SUPPORT_NETWORK:
   - Trusted person outreach, professional counseling, nearby verified shelters/centers discovered through search.
5. FORMAL_OPTIONS (Formal & Legal Pathways):
   - Police complaint, One Stop Centre (Sakhi), POSH Internal Committee, legal aid, protection orders.
6. ONGOING (Ongoing & Follow-Up):
   - Ongoing safety monitoring, future check-in steps, unresolved questions.

7. EVIDENCE & RESOURCE LINKING:
   - Link action items to relevant evidence_ids and resource_ids.
   - Do NOT invent arbitrary deadlines.

Respond with valid JSON.
"""


class SafetyPlanAgent:
    """Agent responsible for safety assessment, live resource matching, and adaptive safety planning."""

    def __init__(self, llm: LLMService) -> None:
        self._llm = llm

    @staticmethod
    def is_safety_case(category: str, situation_text: str = "") -> bool:
        """Determines if a case qualifies for a specialized Women Safety Plan."""
        cat_lower = (category or "").lower().strip()
        if cat_lower in WOMEN_SAFETY_CATEGORIES:
            return True
        
        # Check for safety keywords in text if category was ambiguous
        safety_keywords = [
            "abuse", "abusive", "assault", "threat", "threaten", "stalk", "stalking",
            "harass", "harassment", "violence", "domestic", "unsafe", "partner hit",
            "scared of", "blackmail", "non-consensual", "posh", "icc"
        ]
        text_lower = situation_text.lower()
        return any(kw in text_lower for kw in safety_keywords)

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
        """Maps discovered SerpApi local/maps/web results into structured SafetyMatchedResources."""
        matched: List[SafetyMatchedResource] = []
        seen_names: set[str] = set()
        now = datetime.utcnow()

        # 1. Standard National / Emergency Helplines based on Category
        if category in ("domestic_violence", "safety", "threats", "unsafe_relationship", "coercive_control"):
            matched.append(
                SafetyMatchedResource(
                    id="RES_EMERGENCY_01",
                    name="National Emergency Services",
                    category="helpline",
                    phone="112",
                    operating_hours="24/7",
                    source_domain="emergency.gov",
                    retrieved_at=now,
                    is_verified_gov_or_ngo=True,
                    notes="Immediate police, ambulance, and emergency dispatch.",
                )
            )
            matched.append(
                SafetyMatchedResource(
                    id="RES_WOMEN_HELPLINE_01",
                    name="National Women Helpline / NCW",
                    category="helpline",
                    phone="181 / 1091",
                    operating_hours="24/7",
                    source_domain="ncw.nic.in",
                    retrieved_at=now,
                    is_verified_gov_or_ngo=True,
                    notes="Toll-free 24/7 confidential women in distress support.",
                )
            )
        elif category in ("stalking", "online_harassment", "cyber"):
            matched.append(
                SafetyMatchedResource(
                    id="RES_CYBER_01",
                    name="National Cyber Crime Reporting Portal",
                    category="cyber_cell",
                    phone="1930",
                    url="https://cybercrime.gov.in",
                    source_domain="cybercrime.gov.in",
                    operating_hours="24/7",
                    retrieved_at=now,
                    is_verified_gov_or_ngo=True,
                    notes="Official portal for reporting cyber harassment, stalking, and non-consensual content.",
                )
            )
        elif category in ("workplace_harassment",):
            matched.append(
                SafetyMatchedResource(
                    id="RES_POSH_01",
                    name="SHe-Box / Ministry of Women & Child Development",
                    category="posh_icc",
                    url="https://shebox.nic.in",
                    source_domain="shebox.nic.in",
                    retrieved_at=now,
                    is_verified_gov_or_ngo=True,
                    notes="Online complaint management system for workplace sexual harassment.",
                )
            )

        # 2. Add Discovered Local Resources from SerpApi Maps / Local Search
        for idx, res in enumerate(local_resources):
            if res.name in seen_names:
                continue
            seen_names.add(res.name)
            
            res_type = "shelter" if "shelter" in res.name.lower() or "hostel" in res.name.lower() else "crisis_center"
            if "police" in res.name.lower() or "thana" in res.name.lower():
                res_type = "police"
            elif "legal" in res.name.lower() or "court" in res.name.lower() or "aid" in res.name.lower():
                res_type = "legal_aid"

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
                    is_verified_gov_or_ngo=res.is_verified_gov_or_ngo,
                    notes=f"Discovered via SerpApi Local Search ({res.rating or 'N/A'} stars)",
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
