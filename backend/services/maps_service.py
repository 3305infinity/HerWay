"""
MapsService — Location-aware local resource discovery & geocoding helper.

Capabilities
------------
1. Contextual Local Resource Discovery:
   - Generates category-specific queries for physical assistance offices.
   - Normalizes SerpApi Maps results into structured ``LocalResource`` Pydantic models.
   - Graceful fallback when location is unavailable or Maps search fails.
2. Reverse Geocoding:
   - Converts lat/lng coordinates to human-readable city/region string via OpenCage.
"""

from __future__ import annotations

import logging
import os
from typing import List, Optional

from datetime import datetime
from urllib.parse import urlparse

import httpx
from dotenv import load_dotenv

from backend.models.research import LocalResource, SearchVertical
from backend.services.serpapi_service import SerpApiService

load_dotenv()

logger = logging.getLogger(__name__)


class MapsService:
    """Location-aware search and geocoding helpers."""

    def __init__(self, serpapi: SerpApiService) -> None:
        self._serpapi = serpapi
        self._opencage_key = os.getenv("OPENCAGE_API_KEY", "")

    async def discover_local_resources(
        self,
        category: str,
        location: Optional[str] = None,
        case_summary: Optional[str] = None,
        num_results: int = 5,
    ) -> List[LocalResource]:
        """Generate a contextual query based on category and location, returning normalized LocalResource objects."""
        if not location or not location.strip():
            logger.info("MapsService: No location provided. Skipping local resource discovery.")
            return []

        clean_loc = location.strip()
        clean_cat = (category or "").lower().strip()

        # Contextual query mapping based on category
        if any(kw in clean_cat for kw in ("domestic_violence", "abuse", "threats", "unsafe_relationship", "coercive_control")):
            query = f"women shelter crisis center domestic violence One Stop Centre {clean_loc}"
            res_type = "Women's Shelter & Crisis Support Center"
        elif "stalking" in clean_cat:
            query = f"women police station protection cell stalking support {clean_loc}"
            res_type = "Women Police Station & Protection Cell"
        elif "online_harassment" in clean_cat:
            query = f"cyber crime police station women cyber cell {clean_loc}"
            res_type = "Cyber Crime Unit & Digital Safety Cell"
        elif any(kw in clean_cat for kw in ("workplace_harassment", "posh")):
            query = f"women legal aid labor commissioner office {clean_loc}"
            res_type = "Workplace Rights & Legal Aid Cell"
        elif clean_cat in ("safety", "other_women_safety"):
            query = f"women helpline emergency shelter crisis center {clean_loc}"
            res_type = "Emergency Women's Center & Shelter"
        elif "consumer" in clean_cat:
            query = f"District Consumer Disputes Redressal Commission Consumer Court {clean_loc}"
            res_type = "Consumer Court & Dispute Forum"
        elif "cyber" in clean_cat or "scam" in clean_cat or "fraud" in clean_cat:
            query = f"Cyber Crime Police Station Cyber Cell {clean_loc}"
            res_type = "Cyber Crime Unit / Police Station"
        elif "housing" in clean_cat or "rental" in clean_cat:
            query = f"Tenant Support Rent Control Board Legal Aid {clean_loc}"
            res_type = "Tenant Support & Legal Aid Office"
        elif "education" in clean_cat:
            query = f"District Education Office Student Support Ombudsman {clean_loc}"
            res_type = "Education Office & Student Ombudsman"
        elif "travel" in clean_cat:
            query = f"Railway Grievance Passenger Assistance Office {clean_loc}"
            res_type = "Travel Assistance & Transit Grievance Office"
        elif "employment" in clean_cat or "workplace" in clean_cat:
            query = f"Labor Commissioner Office Employment Court {clean_loc}"
            res_type = "Labor Commissioner & Workplace Ombudsman"
        else:
            query = f"Legal Aid Center Government Assistance Office {clean_loc}"
            res_type = "Legal Aid & Public Help Center"

        logger.info("MapsService: Discovering local resources with query='%s'", query)

        try:
            raw_results = await self._serpapi.search_maps(
                query=query,
                location=clean_loc,
                num_results=num_results,
            )

            local_resources: List[LocalResource] = []
            now = datetime.utcnow()
            for r in raw_results:
                if not r.title:
                    continue
                domain = None
                is_gov = False
                if r.url:
                    try:
                        parsed = urlparse(r.url)
                        domain = parsed.netloc.lower().replace("www.", "")
                        if any(domain.endswith(sfx) for sfx in (".gov", ".gov.in", ".nic.in", ".mil", ".edu", ".org")):
                            is_gov = True
                    except Exception:
                        pass

                # If police station, court, or government office in title
                title_lower = r.title.lower()
                if any(k in title_lower for k in ("police", "court", "commission", "government", "district", "one stop centre", "sakhi")):
                    is_gov = True

                local_resources.append(
                    LocalResource(
                        name=r.title,
                        type=res_type,
                        address=r.address or clean_loc,
                        phone=r.phone,
                        rating=r.rating,
                        review_count=r.reviews,
                        coordinates=r.coordinates,
                        website=r.url,
                        source_url=r.url or f"https://www.google.com/maps/search/?api=1&query={r.title}",
                        source_domain=domain,
                        retrieved_at=now,
                        is_verified_gov_or_ngo=is_gov,
                        relevance_reason=f"Nearby {res_type} in {clean_loc} matching your case.",
                    )
                )

            logger.info("MapsService: Found %d local resources", len(local_resources))
            return local_resources

        except Exception as exc:
            logger.error("MapsService: Resource discovery failed for location '%s': %s", clean_loc, exc)
            return []

    async def reverse_geocode(self, lat: float, lng: float) -> Optional[str]:
        """Convert coordinates to a human-readable location string via OpenCage."""
        if not self._opencage_key:
            logger.warning("MapsService: OPENCAGE_API_KEY not set")
            return None

        url = "https://api.opencagedata.com/geocode/v1/json"
        params = {"key": self._opencage_key, "q": f"{lat},{lng}"}

        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                resp = await client.get(url, params=params)
                resp.raise_for_status()
                data = resp.json()
                components = data["results"][0]["components"]
                return (
                    components.get("city")
                    or components.get("town")
                    or components.get("state")
                    or components.get("country")
                    or None
                )
        except Exception as exc:
            logger.error("MapsService: reverse geocode failed: %s", exc)
            return None

