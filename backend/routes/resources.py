"""
India resources router.

Serves the attributable parts of the resource registry — nationally allocated
helplines, official portals, and the list of States and Union Territories — so
the frontend never has to hardcode a phone number of its own.

Live, location-specific lookups are deliberately *not* served from a static
list: they go through SerpApi so the user gets current information with a
visible provenance label.
"""

from __future__ import annotations

from typing import Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from backend.rate_limit import rate_limit_submission
from backend.services.resource_feedback import (
    OUTCOMES,
    ResourceFeedbackStore,
    resource_key,
)

from backend.india_resources import (
    ALL_INDIAN_REGIONS,
    INDIAN_STATES,
    INDIAN_UNION_TERRITORIES,
    NATIONAL_HELPLINES,
    OFFICIAL_PORTALS,
    NationalHelpline,
    OfficialPortal,
    helplines_for_category,
    portals_for_category,
)

router = APIRouter(prefix="/api/v2/resources", tags=["resources"])


class NationalResourcesResponse(BaseModel):
    helplines: List[NationalHelpline]
    portals: List[OfficialPortal]
    note: str


@router.get("/national", response_model=NationalResourcesResponse)
async def national_resources(
    category: Optional[str] = Query(
        None, description="Situation category to filter by, e.g. domestic_violence"
    )
):
    """National helplines and official portals, each with its official source URL."""
    if category:
        helplines = helplines_for_category(category)
        portals = portals_for_category(category)
    else:
        helplines = list(NATIONAL_HELPLINES)
        portals = list(OFFICIAL_PORTALS)

    return NationalResourcesResponse(
        helplines=helplines,
        portals=portals,
        note=(
            "These are nationally allocated numbers and official Government of India "
            "portals. Each entry links to the government page documenting it. "
            "For services near you, add your city or district to your case."
        ),
    )


class RegionsResponse(BaseModel):
    states: List[str]
    union_territories: List[str]
    all: List[str]


@router.get("/regions", response_model=RegionsResponse)
async def regions():
    """Indian States and Union Territories, for the location picker.

    Offered as a list so the product never has to assume a default city.
    """
    return RegionsResponse(
        states=list(INDIAN_STATES),
        union_territories=list(INDIAN_UNION_TERRITORIES),
        all=list(ALL_INDIAN_REGIONS),
    )


# ---------------------------------------------------------------------------
# Community feedback — "did this resource actually work?"
# ---------------------------------------------------------------------------
# See backend/services/resource_feedback.py for the privacy reasoning. The
# short version: these endpoints take no identity and store none. A record
# linking a person to a women's shelter is exactly what this product must not
# create, so feedback is an anonymous counter on a resource and nothing else.
#
# No `get_identity` dependency here. That is deliberate, not an oversight.


class FeedbackRequest(BaseModel):
    outcome: str = Field(..., description=f"One of: {', '.join(OUTCOMES)}")
    #: Whatever identifies the resource. Hashed server-side into a key; the
    #: raw values are never stored.
    phone: Optional[str] = Field(None, max_length=40)
    url: Optional[str] = Field(None, max_length=400)
    name: Optional[str] = Field(None, max_length=200)


class FeedbackResponse(BaseModel):
    reports: int
    counts: Dict[str, int]
    last_seen: Optional[str] = None
    is_community_reported: bool
    note: str


@router.get("/feedback-options")
async def feedback_options() -> Dict[str, object]:
    """The outcomes a user can report, for rendering the control.

    Reachability only — "was this any good" would become a rating, and a rating
    beside a shelter reads as a safety verdict, which HerWay does not make.
    """
    return {
        "outcomes": [{"value": k, "label": v} for k, v in OUTCOMES.items()],
        "note": (
            "Your report is anonymous. It is counted against the resource, not "
            "against you — HerWay does not record who reported what."
        ),
    }


@router.post(
    "/feedback",
    response_model=FeedbackResponse,
    dependencies=[Depends(rate_limit_submission)],
)
async def submit_feedback(payload: FeedbackRequest) -> FeedbackResponse:
    """Record that a resource worked, or did not.

    Rate limited because there is no identity to limit by — see the module
    docstring on why repeat votes are the accepted cost of anonymity.
    """
    if payload.outcome not in OUTCOMES:
        raise HTTPException(
            status_code=422,
            detail=f"Unknown outcome. Valid values: {', '.join(OUTCOMES)}",
        )

    key = resource_key(phone=payload.phone, url=payload.url, name=payload.name)
    if key is None:
        raise HTTPException(
            status_code=422,
            detail="A phone number, URL or name is needed to identify the resource.",
        )

    return FeedbackResponse(**ResourceFeedbackStore().record(key, payload.outcome))


@router.get("/feedback", response_model=FeedbackResponse)
async def read_feedback(
    phone: Optional[str] = Query(None, max_length=40),
    url: Optional[str] = Query(None, max_length=400),
    name: Optional[str] = Query(None, max_length=200),
) -> FeedbackResponse:
    """What others have reported about one resource."""
    key = resource_key(phone=phone, url=url, name=name)
    if key is None:
        raise HTTPException(
            status_code=422,
            detail="A phone number, URL or name is needed to identify the resource.",
        )
    return FeedbackResponse(**ResourceFeedbackStore().summary(key))
