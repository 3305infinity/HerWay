"""
Safety Plan Model — Personalized, stateful, and adaptive safety planning for Haven.

Core Concepts:
1. Safety Assessment: Explicit, grounded indicators (NO arbitrary risk scores, NO 'risk = 87%').
2. Structured Phased Actions:
   - RIGHT_NOW: Immediate physical & emergency safety
   - NEXT_24_HOURS: Practical safe steps & support contacts
   - DOCUMENT_SAFE: Evidence gathering ONLY IF SAFE
   - SUPPORT_NETWORK: Trusted contacts & professional support
   - FORMAL_OPTIONS: Official procedures, legal rights & reporting pathways
   - ONGOING: Follow-up actions & revisit items
3. Live Resource Matching: Live SerpApi Web, Local, and Maps resources with verified phone/address/hours.
4. State & History: Checkable tasks and 'Why your plan changed' update history.
"""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field

from backend.models.action_plan import ActionPriority, ActionStatus
from backend.models.research import ResourceVerification


class SafetyPlanPhase(str, Enum):
    RIGHT_NOW = "right_now"              # Safety Right Now (0-2 hours)
    NEXT_24_HOURS = "next_24_hours"      # Next 24 Hours
    DOCUMENT_SAFE = "document_safe"      # Document / Preserve — ONLY IF SAFE
    SUPPORT_NETWORK = "support_network"  # Support Network & Discovered Resources
    FORMAL_OPTIONS = "formal_options"    # Formal, Legal & Reporting Pathways
    ONGOING = "ongoing"                  # Ongoing & Follow-Up


class SafetyAssessment(BaseModel):
    """
    Explicit safety indicators extracted strictly from user input and evidence.
    NO arbitrary percentage risk scores.
    """
    immediate_safety_concern: bool = Field(False, description="Explicit imminent physical danger or active threats")
    threats_present: bool = Field(False, description="Verbal, physical, or digital threats made by perpetrator")
    repeated_harassment: bool = Field(False, description="Pattern of recurring unwanted contact or intimidation")
    digital_safety_concern: bool = Field(False, description="Device monitoring, spyware, online stalking, or unauthorized access")
    support_available: bool = Field(False, description="User explicitly has trusted friends, family, or support")
    safe_place_available: bool = Field(False, description="User has identified a safe location to stay")
    financial_dependence: bool = Field(False, description="Perpetrator controls finances or user lacks funds")
    workplace_harassment: bool = Field(False, description="Occurring in employment or professional setting")
    presence_of_dependents: bool = Field(False, description="Children or dependents involved in the unsafe situation")
    escalating_behavior: bool = Field(False, description="Perpetrator's actions are becoming more severe over time")
    information_missing: bool = Field(False, description="Critical context needed to ensure safety is unknown")

    # Traceable justifications quoting or referencing facts
    indicator_justifications: Dict[str, str] = Field(
        default_factory=dict,
        description="Justification for each marked indicator based strictly on user input",
    )
    context_summary: str = Field(
        ..., description="Objective, non-judgmental summary of safety considerations"
    )
    critical_safety_notes: List[str] = Field(
        default_factory=list,
        description="Essential safety caveats (e.g., 'Never confront perpetrator', 'Use private browsing')",
    )
    missing_safety_information: List[str] = Field(
        default_factory=list,
        description="Critical questions that could alter safety recommendations",
    )


class SafetyMatchedResource(BaseModel):
    """A real-world resource offered to the user, with explicit provenance.

    ``verification`` must reflect what we actually checked.  The field used to
    be a boolean defaulting to ``True``, which meant every unchecked Google
    Maps listing was presented to a woman in crisis as a "verified" government
    service.
    """
    id: str = Field(..., description="Unique resource ID, e.g. RES_01")
    name: str = Field(..., description="Name of shelter, helpline, police cell, or support org")
    category: str = Field(
        ...,
        description=(
            "helpline | portal | shelter | police | legal_aid | crisis_center | "
            "cyber_cell | one_stop_centre | posh_icc"
        ),
    )
    phone: Optional[str] = Field(None, description="Direct contact phone number")
    address: Optional[str] = Field(None, description="Physical street address if relevant")
    url: Optional[str] = Field(None, description="Official portal or verification URL")
    operating_hours: Optional[str] = Field(None, description="e.g., '24x7' or 'Mon-Fri 10am-5pm'")
    rating: Optional[float] = Field(None, description="Google Maps / Local user rating")
    verification: ResourceVerification = Field(
        ResourceVerification.UNVERIFIED_LISTING,
        description="official_source | likely_official | unverified_listing",
    )
    verification_note: str = Field(
        "",
        description="Plain-English explanation of the verification level, shown to the user",
    )
    notes: Optional[str] = Field(None, description="Special instructions, e.g. 'Accepts mothers with children'")
    source_domain: Optional[str] = Field(None, description="Extracted domain of source URL")
    retrieved_at: datetime = Field(default_factory=datetime.utcnow, description="Timestamp when resource was retrieved")

    @property
    def is_verified_gov_or_ngo(self) -> bool:
        """Backward-compatible flag for callers written against the old field."""
        return self.verification in (
            ResourceVerification.OFFICIAL_SOURCE,
            ResourceVerification.LIKELY_OFFICIAL,
        )


class SafetyActionItem(BaseModel):
    """A single stateful action step within the Safety Plan."""
    id: str = Field(..., description="Unique action ID, e.g. SAFETY_ACT_01")
    title: str = Field(..., description="Imperative, practical action title")
    description: str = Field(..., description="Concrete step instructions with safety caveats")
    phase: SafetyPlanPhase = Field(..., description="Which phase of the safety plan this belongs to")
    priority: ActionPriority = Field(ActionPriority.IMMEDIATE, description="immediate | high | medium | low")
    status: ActionStatus = Field(ActionStatus.TODO, description="todo | in_progress | completed | skipped")
    evidence_ids: List[str] = Field(default_factory=list, description="IDs of supporting evidence items")
    resource_ids: List[str] = Field(default_factory=list, description="IDs of matched resources")
    safety_caveat: Optional[str] = Field(
        None, description="Crucial safety warning for this specific step (e.g. 'Only if safe to do so')"
    )
    supporting_url: Optional[str] = Field(None, description="Link to official resource/portal")
    created_at: datetime = Field(default_factory=datetime.utcnow)
    completed_at: Optional[datetime] = None


class SafetyPlanUpdate(BaseModel):
    """Audit log entry capturing stateful plan adaptations when situation changes."""
    update_id: str = Field(..., description="Unique update identifier")
    timestamp: datetime = Field(default_factory=datetime.utcnow)
    why_plan_changed: str = Field(..., description="Explanation of new facts or state escalation triggering update")
    what_changed: List[str] = Field(..., description="List of key assessment or strategy changes")
    new_recommended_steps: List[str] = Field(..., description="Titles of newly added action items")
    preserved_completed_actions: List[str] = Field(
        default_factory=list, description="IDs of completed actions that were preserved"
    )


class SafetyPlan(BaseModel):
    """
    The full Haven Personalized Safety Plan.
    Persisted inside the Case document in MongoDB.
    """
    case_id: str
    category: str = Field(..., description="Safety category (e.g., domestic_violence, stalking, online_harassment, workplace_harassment)")
    is_women_safety_case: bool = Field(True, description="True if case pertains to women's safety / protection")
    
    assessment: SafetyAssessment
    
    # Phased Action Items
    right_now_actions: List[SafetyActionItem] = Field(default_factory=list, description="SAFETY RIGHT NOW")
    next_24h_actions: List[SafetyActionItem] = Field(default_factory=list, description="NEXT 24 HOURS")
    document_safe_actions: List[SafetyActionItem] = Field(default_factory=list, description="DOCUMENT — ONLY IF SAFE")
    support_network_actions: List[SafetyActionItem] = Field(default_factory=list, description="SUPPORT NETWORK")
    formal_options_actions: List[SafetyActionItem] = Field(default_factory=list, description="FORMAL & LEGAL OPTIONS")
    ongoing_actions: List[SafetyActionItem] = Field(default_factory=list, description="ONGOING & REVISIT")
    
    # Flattened list of all actions for unified indexing & status checks
    actions: List[SafetyActionItem] = Field(default_factory=list)
    
    # Matched Live Resources (from SerpApi)
    matched_resources: List[SafetyMatchedResource] = Field(default_factory=list)
    
    # Guidance and Avoidance
    things_to_avoid: List[str] = Field(
        default_factory=list,
        description="Dangerous actions to avoid (e.g. 'Do not confront abuser', 'Do not share escape plans online')",
    )
    
    # History of Plan Updates
    updates_history: List[SafetyPlanUpdate] = Field(default_factory=list)
    
    disclaimer: str = Field(
        default=(
            "This safety plan is information and crisis navigation, not legal or "
            "medical advice. If you are in immediate danger, call 112 (emergency) "
            "or 181 (women helpline), or move to a safe public place."
        )
    )
    
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)

    class Config:
        json_encoders = {datetime: lambda v: v.isoformat()}
