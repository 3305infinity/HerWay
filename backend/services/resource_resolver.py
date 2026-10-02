"""
Local resource resolution.

What this is for
----------------
Everyday local discovery: *"a pharmacy near me that's open late"*, *"hospitals
in Kothrud"*, *"how do I get from Shivajinagar to the airport"*. It is the
implementation behind ``SafetyWorkflow.LOCAL_RESOURCES``.

It is **not** a safety oracle. A business listing in Google Maps means a
business is listed — not that it is open, staffed, accessible, reputable or
safe. Every method here is written so that distinction survives into the
result, because the alternative is a product that tells a woman a place is fine
on the strength of a map pin.

What it reuses
--------------
Nothing here is a new search pipeline:

- ``MapsService``     — query construction, provenance classification
- ``SerpApiService``  — the single HTTP client, with the shared cache
- ``SerpApiCache``    — shared across processes (see ``search_cache``)
- ``backend.trace``   — request correlation

Location handling
-----------------
A place name the user typed is enough. Precise coordinates are never requested
for ordinary discovery — "find a chemist in Baner" does not need GPS, and
asking for it would be collecting a sensitive signal for no benefit. Where
coordinates already exist (the user granted them for something else), they are
used via the existing reverse-geocode path and never sent to the provider raw.
"""

from __future__ import annotations

import logging
import re
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional

from backend.models.research import (
    ResourceVerification,
    SearchFailureReason,
    SearchVertical,
)
from backend.trace import get_trace_id, log_fields

logger = logging.getLogger(__name__)


class ResourceCategory(str, Enum):
    """Categories this resolver knows how to search for.

    Deliberately a closed set: each value maps to a query template tuned for
    Indian listings, and an open-ended category would send unvalidated user
    text straight into a provider query.
    """

    HOSPITAL = "hospital"
    CLINIC = "clinic"
    PHARMACY = "pharmacy"
    POLICE = "police"
    WOMEN_POLICE = "women_police"
    ONE_STOP_CENTRE = "one_stop_centre"
    SHELTER = "shelter"
    LEGAL_AID = "legal_aid"
    TRANSPORT_HUB = "transport_hub"
    PUBLIC_TRANSPORT = "public_transport"
    ATM = "atm"
    PUBLIC_PLACE = "public_place"
    ACCOMMODATION = "accommodation"
    COUNSELLING = "counselling"
    OTHER = "other"


#: Query templates. ``{location}`` is substituted; nothing else from the user
#: reaches the provider verbatim.
_CATEGORY_QUERIES: Dict[ResourceCategory, str] = {
    ResourceCategory.HOSPITAL: "hospital emergency {location}",
    ResourceCategory.CLINIC: "clinic {location}",
    ResourceCategory.PHARMACY: "pharmacy chemist {location}",
    ResourceCategory.POLICE: "police station {location}",
    ResourceCategory.WOMEN_POLICE: "women police station mahila thana {location}",
    ResourceCategory.ONE_STOP_CENTRE: "One Stop Centre Sakhi {location}",
    ResourceCategory.SHELTER: "women shelter home Swadhar Greh {location}",
    ResourceCategory.LEGAL_AID: "District Legal Services Authority DLSA {location}",
    ResourceCategory.TRANSPORT_HUB: "railway station bus stand {location}",
    ResourceCategory.PUBLIC_TRANSPORT: "public transport metro bus {location}",
    ResourceCategory.ATM: "atm {location}",
    ResourceCategory.PUBLIC_PLACE: "open public place {location}",
    ResourceCategory.ACCOMMODATION: "working women hostel {location}",
    ResourceCategory.COUNSELLING: "counselling centre mental health {location}",
    ResourceCategory.OTHER: "{location}",
}


#: Words that indicate a request genuinely wants a *place*, used to avoid
#: running local discovery for questions that have nothing to do with one.
_LOCAL_INTENT_PATTERNS = [
    r"\bnear(by| me| here)?\b",
    r"\bclosest\b",
    r"\bnearest\b",
    r"\baround (me|here)\b",
    r"\bin my (area|city|locality|neighbourhood|neighborhood)\b",
    r"\bwhere (is|can i find|are)\b",
    r"\bhow (do|can) i (get|reach)\b",
    r"\bdirections?\b",
    r"\bopen (now|late|today)\b",
    r"\baddress of\b",
    r"\bwalking distance\b",
]
_LOCAL_INTENT_RE = re.compile("|".join(_LOCAL_INTENT_PATTERNS), re.IGNORECASE)

#: Requests that mention a place word but are not asking to find one.
_NON_LOCAL_PATTERNS = [
    r"\bwrite (me |a )?\b",
    r"\bdraft\b",
    r"\bexplain\b",
    r"\bwhat does .* mean\b",
    r"\bhow do i feel\b",
    r"\btranslate\b",
    r"\bsummari[sz]e\b",
]
_NON_LOCAL_RE = re.compile("|".join(_NON_LOCAL_PATTERNS), re.IGNORECASE)

_CATEGORY_KEYWORDS: List[tuple[ResourceCategory, List[str]]] = [
    (ResourceCategory.PHARMACY, ["pharmacy", "chemist", "medical store", "medicine"]),
    (ResourceCategory.HOSPITAL, ["hospital", "emergency room", "casualty", "trauma"]),
    (ResourceCategory.CLINIC, ["clinic", "doctor", "dispensary"]),
    (ResourceCategory.WOMEN_POLICE, ["women police", "mahila thana", "women's cell"]),
    (ResourceCategory.POLICE, ["police", "thana", "cyber cell", "fir"]),
    (ResourceCategory.ONE_STOP_CENTRE, ["one stop", "sakhi"]),
    (ResourceCategory.SHELTER, ["shelter", "swadhar", "ujjwala", "refuge"]),
    (ResourceCategory.LEGAL_AID, ["legal aid", "dlsa", "nalsa", "lawyer", "advocate"]),
    (ResourceCategory.COUNSELLING, ["counsel", "therapist", "psychiatrist", "mental health"]),
    (ResourceCategory.ACCOMMODATION, ["hostel", "pg ", "paying guest", "accommodation"]),
    (ResourceCategory.TRANSPORT_HUB, ["railway station", "bus stand", "airport", "metro station"]),
    (ResourceCategory.PUBLIC_TRANSPORT, ["bus", "metro", "train", "transport", "auto stand"]),
    (ResourceCategory.ATM, ["atm", "cash machine"]),
    (ResourceCategory.PUBLIC_PLACE, ["public place", "open place", "mall", "cafe"]),
]


def wants_local_discovery(text: str) -> bool:
    """Whether ``text`` is actually asking to find a place.

    Deliberately conservative in the *negative* direction: running a maps
    search for "help me write a complaint" wastes a paid call and returns
    nothing useful. Phrasing that only names a category without asking to
    locate one (e.g. "what is a One Stop Centre") is not local intent.
    """
    if not text or not text.strip():
        return False
    if _NON_LOCAL_RE.search(text):
        return False
    if _LOCAL_INTENT_RE.search(text):
        return True
    # A bare category mention plus a preposition of place is enough:
    # "pharmacy in Baner".
    lowered = text.lower()
    has_category = any(
        kw in lowered for _cat, kws in _CATEGORY_KEYWORDS for kw in kws
    )
    return bool(has_category and re.search(r"\b(in|at|near|around)\s+\w", lowered))


def infer_category(text: str) -> ResourceCategory:
    """Best-guess category from the user's wording.

    First match wins and the list is ordered most-specific first, so "women
    police station" resolves to ``WOMEN_POLICE`` rather than ``POLICE``.
    """
    lowered = (text or "").lower()
    for category, keywords in _CATEGORY_KEYWORDS:
        if any(keyword in lowered for keyword in keywords):
            return category
    return ResourceCategory.OTHER


# ---------------------------------------------------------------------------
# Normalised result
# ---------------------------------------------------------------------------

@dataclass
class ResolvedResource:
    """One local resource, carrying only what the provider actually returned.

    Every optional field is ``None`` when absent rather than guessed. A missing
    phone number is shown as missing; it is never filled from a similar listing
    or from the model's own knowledge.
    """

    name: str
    category: ResourceCategory
    address: Optional[str] = None
    phone: Optional[str] = None
    url: Optional[str] = None
    source_domain: Optional[str] = None
    rating: Optional[float] = None
    review_count: Optional[int] = None
    #: Provenance, not a safety judgement. See ``ResourceVerification``.
    verification: ResourceVerification = ResourceVerification.UNVERIFIED_LISTING
    verification_note: str = ""
    #: Raw provider text about hours, if any. Never interpreted as "open now".
    hours_text: Optional[str] = None
    #: Unix time the data was retrieved, so the UI can show its age.
    retrieved_at: float = field(default_factory=time.time)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "category": self.category.value,
            "address": self.address,
            "phone": self.phone,
            "url": self.url,
            "source_domain": self.source_domain,
            "rating": self.rating,
            "review_count": self.review_count,
            "verification": self.verification.value,
            "verification_note": self.verification_note,
            "hours_text": self.hours_text,
            "retrieved_at": self.retrieved_at,
            # Stated explicitly so no consumer has to infer it.
            "open_now_known": False,
        }


@dataclass
class ResolutionOutcome:
    """Result of one resolution, with failure made explicit.

    ``success=False`` and ``resources=[]`` means the lookup broke.
    ``success=True`` and ``resources=[]`` means nothing matched. Collapsing
    those two into "no results" is the error this type exists to prevent.
    """

    resources: List[ResolvedResource] = field(default_factory=list)
    success: bool = True
    failure_reason: str = SearchFailureReason.NONE.value
    category: ResourceCategory = ResourceCategory.OTHER
    location_used: Optional[str] = None
    query_used: Optional[str] = None
    from_cache: bool = False
    trace_id: Optional[str] = None
    retrieved_at: float = field(default_factory=time.time)

    @property
    def found_nothing(self) -> bool:
        """Searched successfully and genuinely matched nothing."""
        return self.success and not self.resources

    def to_dict(self) -> Dict[str, Any]:
        return {
            "resources": [r.to_dict() for r in self.resources],
            "success": self.success,
            "failure_reason": self.failure_reason,
            "category": self.category.value,
            "location_used": self.location_used,
            "query_used": self.query_used,
            "from_cache": self.from_cache,
            "trace_id": self.trace_id,
            "retrieved_at": self.retrieved_at,
            "found_nothing": self.found_nothing,
            "disclaimer": (
                "These are public listings. They do not confirm that a place is "
                "open, operating or suitable. Please call before travelling."
            ),
        }


class ResourceResolver:
    """Resolves a category and a place name into normalised local resources."""

    def __init__(self, serpapi, maps_service=None) -> None:
        from backend.services.maps_service import MapsService

        self._serpapi = serpapi
        self._maps = maps_service or MapsService(serpapi)

    async def resolve(
        self,
        category: ResourceCategory,
        location: Optional[str],
        *,
        max_results: int = 6,
        case_id: Optional[str] = None,
    ) -> ResolutionOutcome:
        """Find resources of ``category`` near ``location``.

        Returns an outcome with ``success=False`` when the provider failed, so
        the caller can say "the lookup did not work" instead of implying the
        area has no hospitals.
        """
        trace_id = get_trace_id()

        if not location or not location.strip():
            # Never guess a location, and never ask for GPS to answer this.
            return ResolutionOutcome(
                success=False,
                failure_reason="location_required",
                category=category,
                trace_id=trace_id,
            )

        clean_location = " ".join(location.split())[:120]
        query = _CATEGORY_QUERIES.get(category, "{location}").format(
            location=clean_location
        )

        logger.info(
            "ResourceResolver: resolving %s",
            log_fields(category=category.value, has_location=True, max_results=max_results),
        )

        try:
            outcome = await self._serpapi.search_detailed(
                query=query,
                vertical=SearchVertical.MAPS,
                location=clean_location,
                case_id=case_id,
                reason=f"Local {category.value} lookup",
            )
        except Exception as exc:
            logger.warning(
                "ResourceResolver: provider call failed %s",
                log_fields(category=category.value, reason=type(exc).__name__),
            )
            return ResolutionOutcome(
                success=False,
                failure_reason=SearchFailureReason.UPSTREAM_ERROR.value,
                category=category,
                location_used=clean_location,
                query_used=query,
                trace_id=trace_id,
            )

        if not outcome.success:
            return ResolutionOutcome(
                success=False,
                failure_reason=outcome.failure_reason.value,
                category=category,
                location_used=clean_location,
                query_used=query,
                trace_id=trace_id,
            )

        resources = [
            self._normalise(result, category)
            for result in outcome.results[:max_results]
            if getattr(result, "title", None)
        ]

        return ResolutionOutcome(
            resources=resources,
            success=True,
            category=category,
            location_used=clean_location,
            query_used=query,
            from_cache=bool(getattr(outcome, "from_cache", False)),
            trace_id=trace_id,
        )

    def _normalise(self, result: Any, category: ResourceCategory) -> ResolvedResource:
        """Map a provider result onto ``ResolvedResource``.

        Absent fields stay absent. ``getattr`` with a default is used
        throughout because the provider's shape varies between engines and a
        missing attribute must not raise mid-render.
        """
        from backend.services.maps_service import MapsService

        url = getattr(result, "url", None)
        domain = MapsService._domain_of(url) if url else None
        verification, note = MapsService._classify(
            getattr(result, "title", "") or "", domain
        )

        return ResolvedResource(
            name=getattr(result, "title", "") or "Unnamed listing",
            category=category,
            address=getattr(result, "address", None),
            phone=getattr(result, "phone", None),
            url=url,
            source_domain=domain,
            rating=getattr(result, "rating", None),
            review_count=getattr(result, "reviews", None),
            verification=verification,
            verification_note=note,
            hours_text=getattr(result, "hours", None),
        )

    async def resolve_from_text(
        self,
        text: str,
        location: Optional[str],
        *,
        max_results: int = 6,
        case_id: Optional[str] = None,
    ) -> Optional[ResolutionOutcome]:
        """Resolve directly from a user's phrasing.

        Returns ``None`` when the text is not asking to find a place, so the
        caller can skip the search entirely rather than spending a credit on
        "help me draft a complaint".
        """
        if not wants_local_discovery(text):
            return None
        return await self.resolve(
            infer_category(text), location, max_results=max_results, case_id=case_id
        )
