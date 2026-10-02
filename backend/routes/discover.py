"""
Local discovery endpoints (Phase 3).

Everyday "what is near me" research, served from the same canonical search
infrastructure the agents use: ``SerpApiService`` with the shared cache,
``ResourceResolver`` and ``PlaceResearchService``. No new pipeline.

These are paid searches, so every route carries the LLM-tier rate-limit budget.
They need an identity (so the limit is per-browser rather than per-IP) but not
a Clerk account — local discovery is ordinary, low-sensitivity use and
requiring sign-in would be a barrier for no safety benefit.

Nothing here returns a safety judgement. See ``place_research`` for why.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from backend.auth import Identity, get_identity
from backend.rate_limit import rate_limit_llm
from backend.services.place_research import PlaceResearchService, compare_options
from backend.services.resource_resolver import ResourceCategory, ResourceResolver
from backend.services.serpapi_service import SerpApiService
from backend.trace import get_trace_id, log_fields

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v2/discover", tags=["discover"])

#: Upper bound on a user-supplied place or location string. Long enough for
#: "Shop 4, Mahatma Gandhi Road, Camp, Pune", short enough that a pasted
#: document cannot become a search query.
MAX_PLACE_CHARS = 160


class ResourceQuery(BaseModel):
    category: str = Field(..., description="A ResourceCategory value")
    location: str = Field(..., min_length=2, max_length=MAX_PLACE_CHARS)
    max_results: int = Field(6, ge=1, le=12)


class PlaceQuery(BaseModel):
    place_name: str = Field(..., min_length=2, max_length=MAX_PLACE_CHARS)
    location: Optional[str] = Field(None, max_length=MAX_PLACE_CHARS)


class CompareQuery(BaseModel):
    category: str
    location: str = Field(..., min_length=2, max_length=MAX_PLACE_CHARS)
    #: What the user said matters to them. Never inferred on their behalf.
    priorities: List[str] = Field(default_factory=list, max_length=6)
    max_results: int = Field(5, ge=2, le=8)


class AreaQuery(BaseModel):
    area: str = Field(..., min_length=2, max_length=MAX_PLACE_CHARS)


def _resolve_category(value: str) -> ResourceCategory:
    try:
        return ResourceCategory(value.strip().lower())
    except ValueError:
        raise HTTPException(
            status_code=422,
            detail=f"Unknown category. Valid values: "
            f"{', '.join(c.value for c in ResourceCategory)}",
        )


@router.get("/categories")
async def list_categories() -> Dict[str, Any]:
    """The categories the resolver can search for. Public, no search cost."""
    return {
        "categories": [
            {"value": c.value, "label": c.value.replace("_", " ").title()}
            for c in ResourceCategory
            if c is not ResourceCategory.OTHER
        ]
    }


@router.post("/resources", dependencies=[Depends(rate_limit_llm)])
async def discover_resources(
    payload: ResourceQuery,
    identity: Identity = Depends(get_identity),
) -> Dict[str, Any]:
    """Find local resources of one category near a place the user named."""
    category = _resolve_category(payload.category)
    resolver = ResourceResolver(SerpApiService())

    outcome = await resolver.resolve(
        category, payload.location, max_results=payload.max_results
    )
    logger.info(
        "Discover: resources %s",
        log_fields(
            category=category.value,
            found=len(outcome.resources),
            success=outcome.success,
            from_cache=outcome.from_cache,
        ),
    )
    return outcome.to_dict()


@router.post("/place", dependencies=[Depends(rate_limit_llm)])
async def research_place(
    payload: PlaceQuery,
    identity: Identity = Depends(get_identity),
) -> Dict[str, Any]:
    """Look up one named place and summarise what is published about it."""
    profile = await PlaceResearchService(SerpApiService()).research_place(
        payload.place_name, payload.location
    )
    logger.info(
        "Discover: place %s",
        log_fields(success=profile.success, has_listing=bool(profile.listing)),
    )
    return profile.to_dict()


@router.post("/compare", dependencies=[Depends(rate_limit_llm)])
async def compare_resources(
    payload: CompareQuery,
    identity: Identity = Depends(get_identity),
) -> Dict[str, Any]:
    """Compare several options of one category, on the fields sources supplied.

    Returns the comparison **and** the underlying resources, so the UI can show
    the evidence behind every cell rather than a table the user must trust.
    """
    category = _resolve_category(payload.category)
    outcome = await ResourceResolver(SerpApiService()).resolve(
        category, payload.location, max_results=payload.max_results
    )

    comparison = compare_options(
        [r.to_dict() for r in outcome.resources], priorities=payload.priorities
    )
    return {
        "resources": outcome.to_dict(),
        "comparison": comparison.to_dict(),
        "trace_id": get_trace_id(),
    }


@router.post("/area-reports", dependencies=[Depends(rate_limit_llm)])
async def area_reports(
    payload: AreaQuery,
    identity: Identity = Depends(get_identity),
) -> Dict[str, Any]:
    """Recent public reporting about an area.

    The response carries its own limitations, including that an absence of
    results says nothing about whether an area is safe.
    """
    summary = await PlaceResearchService(SerpApiService()).area_reports(payload.area)
    return summary.to_dict()
