"""
Research models — normalized data structures powering Haven's research pipeline.

Covers:
- Situation           — Structured understanding of user's situation.
- SearchIntent        — Query metadata & vertical routing request.
- SearchResult        — Normalized SerpApi result object.
- ResearchTask / Plan — Planner output & execution trace.
- EvidenceItem        — Verified evidence with authority, confidence, & contradictions.
- FinalResearchReport — Assembled output passed to ActionPlanner.
"""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field


# ---------------------------------------------------------------------------
# Situation Understanding Models
# ---------------------------------------------------------------------------

class Urgency(str, Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class SituationCategory(str, Enum):
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
    
    # Specialized Women's Safety Categories
    DOMESTIC_VIOLENCE = "domestic_violence"
    SEXUAL_HARASSMENT = "sexual_harassment"
    STALKING = "stalking"
    ONLINE_HARASSMENT = "online_harassment"
    THREATS = "threats"
    COERCIVE_CONTROL = "coercive_control"
    UNSAFE_RELATIONSHIP = "unsafe_relationship"
    WORKPLACE_HARASSMENT = "workplace_harassment"
    OTHER_WOMEN_SAFETY = "other_women_safety"
    
    OTHER = "other"


class Situation(BaseModel):
    """Structured understanding of the user's natural language situation."""

    case_summary: str = Field(
        ..., description="One-paragraph plain-English summary of the problem"
    )
    category: SituationCategory = Field(
        SituationCategory.OTHER, description="Broad category"
    )
    subcategory: Optional[str] = Field(
        None, description="Specific subcategory if discernible"
    )
    urgency: Urgency = Field(Urgency.MEDIUM, description="Assessed urgency")
    location: Optional[str] = Field(
        None, description="User's city/state/country if mentioned"
    )
    entities: List[str] = Field(
        default_factory=list, description="Named entities (people, products, etc.)"
    )
    organizations_involved: List[str] = Field(
        default_factory=list, description="Companies, seller platforms, government agencies"
    )
    user_goal: str = Field(
        ..., description="What the user wants to achieve (refund, replacement, report, etc.)"
    )

    # Fact / Claim / Unknown Distinction
    known_facts: List[str] = Field(
        default_factory=list,
        description="Explicitly stated objective facts (e.g., 'Purchased laptop on Sept 12').",
    )
    user_claims: List[str] = Field(
        default_factory=list,
        description="User assertions or legal/procedural claims (e.g., 'Seller broke the law').",
    )
    unknowns: List[str] = Field(
        default_factory=list,
        description="Critical missing context or unresolved questions (e.g., 'Whether return policy covers physical damage').",
    )

    missing_information: List[str] = Field(
        default_factory=list,
        description="Follow-up questions for the user (e.g., invoice date, payment method).",
    )
    relevant_time_constraints: Optional[str] = Field(
        None, description="Deadlines or time constraints if known"
    )
    evidence_already_available: List[str] = Field(
        default_factory=list,
        description="Photos, receipts, messages user currently possesses",
    )
    questions_to_ask: List[str] = Field(
        default_factory=list,
        description="Key questions that materially affect research",
    )
    recommended_research_types: List[str] = Field(
        default_factory=list,
        description="Suggested search verticals (e.g., web, news, maps, local)",
    )

    # Convenience properties for backward compatibility
    @property
    def summary(self) -> str:
        return self.case_summary

    @property
    def key_questions(self) -> List[str]:
        return self.questions_to_ask

    @property
    def missing_info(self) -> List[str]:
        return self.missing_information


# ---------------------------------------------------------------------------
# SerpApi & Search Models
# ---------------------------------------------------------------------------

class SearchVertical(str, Enum):
    WEB = "web"
    NEWS = "news"
    LOCAL = "local"
    MAPS = "maps"
    # Aliases for compatibility
    GOOGLE_SEARCH = "google_search"
    GOOGLE_NEWS = "google_news"
    GOOGLE_MAPS = "google_maps"


# Compatibility alias
SearchType = SearchVertical


class SearchRequest(BaseModel):
    """Search request model explaining WHY a search is being made."""
    query: str
    vertical: SearchVertical = SearchVertical.WEB
    reason: str = Field(..., description="Explanation of why this search is necessary")
    priority: str = Field("medium", description="high | medium | low")
    location: Optional[str] = None
    country: Optional[str] = "us"
    language: Optional[str] = "en"
    num_results: int = 10
    page: int = 1


SearchIntent = SearchRequest


class SearchResult(BaseModel):
    """Normalized internal SearchResult object representing live SerpApi data."""

    title: str
    url: Optional[str] = None
    source: Optional[str] = Field(None, description="Domain or publishing source name")
    domain: Optional[str] = Field(None, description="Extracted domain name")
    snippet: str = ""
    published_at: Optional[str] = Field(None, description="ISO date or relative string")
    position: Optional[int] = Field(None, description="SERP position ranking")
    result_type: str = Field("web", description="web | news | local | maps")

    # Local / Maps metadata
    thumbnail: Optional[str] = None
    address: Optional[str] = None
    rating: Optional[float] = None
    reviews: Optional[int] = None
    phone: Optional[str] = None
    coordinates: Optional[Dict[str, float]] = Field(
        None, description="e.g. {'latitude': 12.97, 'longitude': 77.59}"
    )

    raw_metadata: Optional[Dict[str, Any]] = Field(
        None, description="Raw metadata from SerpApi item (unexposed to UI)"
    )

    # Backward compatibility properties
    @property
    def search_type(self) -> SearchVertical:
        if self.result_type == "news":
            return SearchVertical.NEWS
        elif self.result_type in ("maps", "local"):
            return SearchVertical.MAPS
        return SearchVertical.WEB

    @property
    def raw_position(self) -> Optional[int]:
        return self.position

    @property
    def published_date(self) -> Optional[str]:
        return self.published_at


# ---------------------------------------------------------------------------
# Research Planner & Execution Models
# ---------------------------------------------------------------------------

class FreshnessPolicy(str, Enum):
    STATIC = "static"                    # General background / statutory definitions
    RECENT = "recent"                    # Policy changes / news / active developments
    CURRENT = "current"                  # Contact info, local resources, active services
    TIME_SENSITIVE = "time_sensitive"    # High urgency where stale info is dangerous


class ResearchMetrics(BaseModel):
    """Credit efficiency and execution metrics tracked per case."""
    search_count: int = 0
    cached_search_count: int = 0
    web_search_count: int = 0
    news_search_count: int = 0
    local_search_count: int = 0
    maps_search_count: int = 0
    unique_domains_count: int = 0
    official_domains_count: int = 0
    iterations_executed: int = 1
    contradictions_resolved: int = 0


class ResearchTask(BaseModel):
    """A single research task generated by the Research Planner."""
    task_id: str = Field(..., description="Unique task identifier, e.g. TASK_01")
    query: str
    vertical: SearchVertical = SearchVertical.WEB
    purpose: str = Field(..., description="Why this search is being executed")
    expected_information: str = Field(..., description="What evidence or info is expected")
    priority: str = Field("medium", description="high | medium | low")
    official_source_preference: str = Field("preferred", description="preferred | required | any")
    location: Optional[str] = None
    freshness_policy: FreshnessPolicy = Field(FreshnessPolicy.CURRENT, description="static | recent | current | time_sensitive")
    freshness_requirement: Optional[str] = None  # e.g., "recent", "past_year", "any"
    is_followup: bool = Field(False, description="True if generated by quality loop or contradiction resolution")
    target_entity: Optional[str] = None

    # Backward compatibility properties
    @property
    def rationale(self) -> str:
        return self.purpose

    @property
    def search_type(self) -> SearchVertical:
        return self.vertical

    @property
    def location_context(self) -> Optional[str]:
        return self.location


# PlannedSearch alias for backwards compatibility
PlannedSearch = ResearchTask


class ResearchPlan(BaseModel):
    """The research strategy produced by the Research Planning Agent."""
    case_id: str
    reasoning: str = Field("", description="Overview of search strategy")
    tasks: List[ResearchTask] = Field(default_factory=list)
    search_budget: int = Field(4, description="Max allowed search tasks for this plan")
    iteration: int = Field(1, description="Planning iteration number")
    created_at: datetime = Field(default_factory=datetime.utcnow)

    @property
    def searches(self) -> List[ResearchTask]:
        return self.tasks


class ResearchTraceEntry(BaseModel):
    """Per-case trace entry recorded during execution for transparency."""
    task_id: str
    why_searched: str
    query: str
    engine: str
    results_found: int
    sources_used: int = Field(0, description="Number of results selected and verified")
    selected_urls: List[str] = Field(default_factory=list, description="URLs of evidence extracted from this search")
    time_taken_ms: float
    is_cached: bool = Field(False, description="True if served from memory cache / deduplicated")
    is_followup: bool = Field(False, description="True if this was a follow-up retry or contradiction resolution")
    freshness_policy: str = Field("current", description="static | recent | current | time_sensitive")
    success: bool
    error: Optional[str] = None


class ResearchExecutionResult(BaseModel):
    """Execution output from ResearchAgent."""
    plan: ResearchPlan
    results: List[SearchResult] = Field(default_factory=list)
    trace: List[ResearchTraceEntry] = Field(default_factory=list)
    metrics: Optional[ResearchMetrics] = None


# ---------------------------------------------------------------------------
# Source Verification & Evidence Models
# ---------------------------------------------------------------------------

class SourceType(str, Enum):
    OFFICIAL_GOVERNMENT = "official_government"
    OFFICIAL_ORGANIZATION = "official_organization"
    NEWS = "news"
    ACADEMIC = "academic"
    COMPANY = "company"
    LOCAL_BUSINESS = "local_business"
    COMMUNITY = "community"
    BLOG = "blog"
    FORUM = "forum"
    UNKNOWN = "unknown"


class EvidenceStatus(str, Enum):
    VERIFIED_STRONGLY_SUPPORTED = "verified_strongly_supported"
    PARTIALLY_SUPPORTED = "partially_supported"
    CONFLICTING = "conflicting"
    UNVERIFIED = "unverified"


class Contradiction(BaseModel):
    """Captures disagreement between sources."""
    claim: str
    source_a: str
    source_b: str
    difference: str
    resolution_status: str = Field("unresolved", description="unresolved | resolved_by_official")


class EvidenceConfidence(str, Enum):
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"


class EvidenceItem(BaseModel):
    """A verified, scored piece of evidence extracted from search results."""

    id: str = Field(..., description="Unique evidence ID, e.g. EVIDENCE_01")
    source_title: str
    url: Optional[str] = None
    domain: Optional[str] = None
    source_type: SourceType = SourceType.UNKNOWN
    relevance: float = Field(0.0, ge=0.0, le=1.0)
    freshness: float = Field(0.0, ge=0.0, le=1.0)
    authority: float = Field(0.0, ge=0.0, le=1.0)
    supports_claim: bool = True
    claim_supported: str = Field(..., description="The exact factual claim extracted")
    extracted_facts: List[str] = Field(default_factory=list)
    contradictions: List[Contradiction] = Field(default_factory=list)
    confidence: EvidenceConfidence = EvidenceConfidence.MEDIUM
    confidence_score: float = Field(0.0, ge=0.0, le=1.0, description="Transparent computed score")
    status: EvidenceStatus = EvidenceStatus.UNVERIFIED
    why_this_source_matters: str = ""

    # Compatibility properties
    @property
    def claim(self) -> str:
        return self.claim_supported

    @property
    def source_url(self) -> Optional[str]:
        return self.url

    @property
    def relevance_note(self) -> str:
        return self.why_this_source_matters


# ---------------------------------------------------------------------------
# Local Resource Discovery Models
# ---------------------------------------------------------------------------

class LocalResource(BaseModel):
    """Normalized local physical resource found via Maps / Local search."""
    id: str = Field(default_factory=lambda: f"res_{datetime.utcnow().timestamp()}")
    name: str = Field(..., description="Name of institution, court, office, or center")
    type: str = Field(..., description="e.g. Consumer Court, Police Station, Cyber Support, Legal Aid")
    address: Optional[str] = None
    phone: Optional[str] = None
    rating: Optional[float] = None
    review_count: Optional[int] = None
    hours: Optional[str] = None
    coordinates: Optional[Dict[str, float]] = Field(None, description="{'latitude': float, 'longitude': float}")
    website: Optional[str] = None
    source_url: Optional[str] = None
    source_domain: Optional[str] = None
    retrieved_at: datetime = Field(default_factory=datetime.utcnow)
    is_verified_gov_or_ngo: bool = Field(False, description="True if official government, police, court, or verified NGO")
    relevance_reason: str = Field("", description="Why this local resource is relevant to the case")


# ---------------------------------------------------------------------------
# Final Research Report
# ---------------------------------------------------------------------------

class FinalResearchReport(BaseModel):
    """Complete research report handed to the Action Planner."""
    case_id: str
    situation: Situation
    research_plan: Optional[ResearchPlan] = None
    trace: List[ResearchTraceEntry] = Field(default_factory=list)
    evidence: List[EvidenceItem] = Field(default_factory=list)
    local_resources: List[LocalResource] = Field(default_factory=list)
    searches_executed: int = 0
    sources_verified: int = 0
    metrics: Optional[ResearchMetrics] = None
    unique_domains: List[str] = Field(default_factory=list)
    official_domains: List[str] = Field(default_factory=list)
    created_at: datetime = Field(default_factory=datetime.utcnow)


