"""
Action Plan model — the concrete, user-facing output of the pipeline.

An ActionPlan is a list of prioritised, categorised ActionItems that
translate research findings into things the user can *do*.
"""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


class ActionPriority(str, Enum):
    """Priority of an action.

    Two vocabularies are accepted. The ``*_TERM`` names express *when* a step
    belongs in a research-driven action plan; ``HIGH``/``MEDIUM``/``LOW``
    express *how urgent* a step is in a safety plan. Both are supported so that
    ``SafetyActionItem`` and ``ActionItem`` can share this type, and so that
    documents already stored in MongoDB keep validating.
    """

    IMMEDIATE = "immediate"     # Do this first / today
    SHORT_TERM = "short_term"   # Within the next few days
    MEDIUM_TERM = "medium_term" # Within weeks
    ONGOING = "ongoing"         # Recurring / background

    # Urgency-style aliases used by the Safety Plan.
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"


class ActionStatus(str, Enum):
    TODO = "todo"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    BLOCKED = "blocked"


class ActionTimingPhase(str, Enum):
    DO_NOW = "do_now"
    NEXT = "next"
    IF_THAT_DOES_NOT_WORK = "if_that_does_not_work"


class ActionType(str, Enum):
    """What kind of action this is."""
    CONTACT = "contact"           # Call / email someone
    DOCUMENT = "document"         # Gather / file paperwork
    COMPLAINT = "complaint"       # File a formal complaint
    VISIT = "visit"               # Go to a physical location
    RESEARCH = "research"         # Look up more information
    MONITOR = "monitor"           # Watch for updates
    SAFETY = "safety"             # Safety / protection action
    FINANCIAL = "financial"       # Money-related step
    LEGAL = "legal"               # Legal process step
    OTHER = "other"


class ActionItem(BaseModel):
    """A single actionable step for the user."""
    id: str = Field(..., description="Action ID, e.g. ACTION_01")
    title: str = Field(
        ..., description="Short imperative title (e.g. 'Gather invoice and order receipt')"
    )
    description: str = Field(
        ..., description="2-3 sentence explanation of concrete steps to take and why"
    )
    action_type: ActionType = ActionType.OTHER
    priority: ActionPriority = ActionPriority.SHORT_TERM
    timing_phase: ActionTimingPhase = ActionTimingPhase.DO_NOW
    evidence_ids: List[str] = Field(
        default_factory=list,
        description="IDs of EvidenceItems backing this action (e.g., ['EVIDENCE_01'])",
    )
    estimated_effort: Optional[str] = Field(
        None, description="e.g. '15-30 mins', '1-2 days'"
    )
    deadline: Optional[str] = Field(
        None, description="Explicit deadline if supported by retrieved evidence; NEVER invented"
    )
    status: ActionStatus = ActionStatus.TODO
    supporting_url: Optional[str] = Field(
        None, description="Link to an official portal or form"
    )
    supporting_evidence: Optional[str] = Field(
        None, description="Textual reference to supporting evidence"
    )
    completed: bool = False


class ActionPlan(BaseModel):
    """The full action plan for a case."""
    case_id: str
    summary: str = Field(
        ..., description="2-3 sentence overview of the recommended approach"
    )
    disclaimer: str = Field(
        default=(
            "HerWay is an information and action-planning assistant. "
            "This is not legal, medical, or professional advice. "
            "Please consult a qualified professional for authoritative guidance."
        ),
        description="Mandatory disclaimer shown with every action plan",
    )
    
    # Action Timing Breakdown
    immediate_actions: List[ActionItem] = Field(
        default_factory=list, description="DO NOW steps"
    )
    next_actions: List[ActionItem] = Field(
        default_factory=list, description="NEXT steps"
    )
    escalation_options: List[ActionItem] = Field(
        default_factory=list, description="IF THAT DOES NOT WORK steps"
    )

    # Flattened full list for legacy compatibility
    actions: List[ActionItem] = Field(
        default_factory=list, description="All actions combined"
    )

    # Resource and Evidence Lists
    documents_or_evidence_to_collect: List[str] = Field(
        default_factory=list, description="Checklist of paperwork/photos/receipts to gather"
    )
    relevant_contacts: List[Dict[str, Any]] = Field(
        default_factory=list, description="Helplines, email addresses, phone numbers"
    )
    relevant_links: List[Dict[str, Any]] = Field(
        default_factory=list, description="Official complaint portals and guide pages"
    )
    nearby_resources: List[Dict[str, Any]] = Field(
        default_factory=list, description="Physical locations found via maps search"
    )
    things_to_avoid: List[str] = Field(
        default_factory=list, description="Pitfalls or actions that could harm user's case"
    )
    unresolved_questions: List[str] = Field(
        default_factory=list, description="Questions that still need user input or further investigation"
    )

    created_at: datetime = Field(default_factory=datetime.utcnow)

    class Config:
        json_encoders = {datetime: lambda v: v.isoformat()}

