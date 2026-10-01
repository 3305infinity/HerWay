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

from typing import List, Optional

from fastapi import APIRouter, Query
from pydantic import BaseModel

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
