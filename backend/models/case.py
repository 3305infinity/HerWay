"""
Case model — persistent Case Memory & lifecycle document stored in MongoDB.

Statuses
--------
- ACTIVE: Case is currently open and being researched or acted upon.
- PAUSED: User paused research/actions.
- RESOLVED: User successfully resolved the situation.
- ARCHIVED: Archived case.

Supports indexing on:
- user_id
- status
- updated_at
"""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field

from backend.models.action_plan import ActionPlan
from backend.models.safety_plan import SafetyPlan
from backend.models.research import (
    EvidenceItem,
    LocalResource,
    ResearchPlan,
    ResearchTraceEntry,
    Situation,
)


class CaseStatus(str, Enum):
    """Lifecycle states a case moves through."""
    ACTIVE = "active"
    PAUSED = "paused"
    RESOLVED = "resolved"
    ARCHIVED = "archived"

    # Compatibility aliases
    INTAKE = "intake"
    RESEARCHING = "researching"
    VERIFYING = "verifying"
    PLANNING = "planning"
    COMPLETE = "complete"


class CaseCategory(str, Enum):
    CONSUMER = "consumer"
    HOUSING = "housing"
    EMPLOYMENT = "employment"
    EDUCATION = "education"
    FINANCIAL = "financial"
    TRAVEL = "travel"
    CYBER = "cyber"
    LEGAL_INFORMATION = "legal_information"
    GOVERNMENT_SERVICE = "government_service"
    SAFETY = "safety"
    HEALTH_INFORMATION = "health_information"
    OTHER = "other"


class Location(BaseModel):
    """User location context."""
    lat: Optional[float] = None
    lng: Optional[float] = None
    display_name: Optional[str] = None


class CaseCreate(BaseModel):
    """Payload the frontend sends to create a new case."""
    user_id: Optional[str] = None
    situation_text: str = Field(..., min_length=10)
    location: Optional[Location] = None
    category: Optional[str] = None


class CaseUpdate(BaseModel):
    """Payload to update case title, status, or notes."""
    title: Optional[str] = None
    status: Optional[CaseStatus] = None
    location_context: Optional[str] = None


class Case(BaseModel):
    """Full persisted case document in MongoDB."""
    id: Optional[str] = Field(None, alias="_id")
    user_id: Optional[str] = None
    title: str = Field("Untitled Case", description="Short title generated from situation")
    category: str = Field("other", description="Primary category")
    situation_text: str
    status: CaseStatus = CaseStatus.ACTIVE
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)

    # Embedded Pipeline Objects
    situation: Optional[Situation] = None
    location: Optional[Location] = None
    location_context: Optional[str] = None
    research_summary: Optional[str] = None
    research_plan: Optional[ResearchPlan] = None
    evidence: List[EvidenceItem] = Field(default_factory=list)
    action_plan: Optional[ActionPlan] = Field(None)
    safety_plan: Optional[SafetyPlan] = Field(None, description="Personalized, adaptive safety plan for women-safety cases")
    local_resources: List[LocalResource] = Field(default_factory=list)
    research_trace: List[ResearchTraceEntry] = Field(default_factory=list)
    conversation: List[Dict[str, str]] = Field(
        default_factory=list,
        description='History as [{"role": "user"|"assistant", "content": "..."}]',
    )

    # ID References for sub-documents
    research_plan_id: Optional[str] = None
    research_report_id: Optional[str] = None
    action_plan_id: Optional[str] = None

    class Config:
        populate_by_name = True
        json_encoders = {datetime: lambda v: v.isoformat()}


_indexes_created = False

def ensure_case_indexes(db: Any) -> None:
    """Ensure indexes on 'user_id', 'status', and 'updated_at' for fast querying."""
    global _indexes_created
    if _indexes_created or db is None:
        return
    try:
        col = db["cases"]
        col.create_index([("user_id", 1)])
        col.create_index([("status", 1)])
        col.create_index([("updated_at", -1)])
        col.create_index([("user_id", 1), ("status", 1), ("updated_at", -1)])
        _indexes_created = True
    except Exception:
        pass

