"""
MapsService — Location-aware local resource discovery & geocoding helper.

Capabilities
------------
1. Contextual Local Resource Discovery:
   - Generates India-specific queries for the physical offices that actually
     exist here (One Stop Centres, Mahila Thana, DLSA, cyber crime cells).
   - Normalizes SerpApi Maps results into structured ``LocalResource`` models.
   - Reports *why* discovery produced nothing, so the UI can tell "no centres
     found nearby" apart from "the search did not run".
2. Reverse Geocoding:
   - Converts lat/lng coordinates to a human-readable place via OpenCage.

Provenance rules
----------------
A Google Maps listing is a third-party listing, not a government record.  We
label it ``UNVERIFIED_LISTING`` unless the linked website sits on an official
Indian government domain.  A woman acting on a wrong address during a crisis is
a real harm, so we never over-claim.
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass, field
from datetime import datetime
from typing import List, Optional
from urllib.parse import urlparse

import httpx
from dotenv import load_dotenv

from backend.models.research import (
    LocalResource,
    ResourceVerification,
    SearchVertical,
)
from backend.services.serpapi_service import SerpApiService
from backend.trace import log_fields

load_dotenv()

logger = logging.getLogger(__name__)

#: Domain suffixes that identify an official Indian government service.
#: ``.nic.in`` matters especially — most Indian ministry and district portals
#: live there rather than on ``.gov.in``.
OFFICIAL_IN_SUFFIXES = (
    ".gov.in",
    ".nic.in",
    ".gov",
    ".edu.in",
    ".ac.in",
)

#: Words that indicate a government body in an Indian listing title.
_GOV_TITLE_KEYWORDS = (
    "police",
    "thana",
    "mahila",
    "one stop centre",
    "one stop center",
    "sakhi",
    "district court",
    "commission",
    "government",
    "legal services authority",
    "dlsa",
    "municipal",
    "collectorate",
    "cyber crime",
    "cybercrime",
)


@dataclass
class LocalDiscoveryResult:
    """Outcome of a local-resource lookup, including explicit failure state."""

    resources: List[LocalResource] = field(default_factory=list)
    success: bool = True
    failure_reason: str = "none"
    query_used: Optional[str] = None
    location_used: Optional[str] = None


class MapsService:
    """Location-aware search and geocoding helpers."""

    def __init__(self, serpapi: SerpApiService) -> None:
        self._serpapi = serpapi
        self._opencage_key = os.getenv("OPENCAGE_API_KEY", "")

    # ------------------------------------------------------------------
    # Query construction
    # ------------------------------------------------------------------

    @staticmethod
    def build_query(category: str, location: str) -> tuple[str, str]:
        """Return ``(query, resource_type_label)`` for an India-specific search."""
        clean_cat = (category or "").lower().strip()
        clean_loc = location.strip()

        if any(
            kw in clean_cat
            for kw in (
                "domestic_violence",
                "abuse",
                "threats",
                "unsafe_relationship",
                "coercive_control",
            )
        ):
            return (
                f"One Stop Centre Sakhi women shelter home {clean_loc}",
                "One Stop Centre & women's shelter",
            )
        if "stalking" in clean_cat:
            return (
                f"Mahila Thana women police station {clean_loc}",
                "Women police station",
            )
        if "online_harassment" in clean_cat or "cyber" in clean_cat:
            return (
                f"cyber crime police station cyber cell {clean_loc}",
                "Cyber crime cell",
            )
        if any(kw in clean_cat for kw in ("workplace_harassment", "sexual_harassment", "posh")):
            return (
                f"District Legal Services Authority women legal aid {clean_loc}",
                "Legal aid & women's rights office",
            )
        if clean_cat in ("safety", "other_women_safety"):
            return (
                f"One Stop Centre women helpline support centre {clean_loc}",
                "Women's support centre",
            )
        if "consumer" in clean_cat:
            return (
                f"District Consumer Disputes Redressal Commission {clean_loc}",
                "Consumer disputes commission",
            )
        if "housing" in clean_cat or "rental" in clean_cat:
            return (
                f"Rent Controller office District Legal Services Authority {clean_loc}",
                "Rent controller & legal aid",
            )
        if "education" in clean_cat:
            return (
                f"District Education Officer office {clean_loc}",
                "District education office",
            )
        if "travel" in clean_cat:
            return (
                f"railway station manager grievance office {clean_loc}",
                "Transport grievance office",
            )
        if "employment" in clean_cat or "workplace" in clean_cat:
            return (
                f"Labour Commissioner office {clean_loc}",
                "Labour commissioner office",
            )
        if "financial" in clean_cat:
            return (
                f"District Legal Services Authority consumer court {clean_loc}",
                "Legal aid & consumer redressal",
            )
        return (
            f"District Legal Services Authority legal aid clinic {clean_loc}",
            "Legal aid & public help centre",
        )

    # ------------------------------------------------------------------
    # Discovery
    # ------------------------------------------------------------------

    async def discover_local_resources_detailed(
        self,
        category: str,
        location: Optional[str] = None,
        case_summary: Optional[str] = None,
        num_results: int = 6,
    ) -> LocalDiscoveryResult:
        """Find nearby offices for a category, reporting success or failure explicitly."""
        if not location or not location.strip():
            logger.info("MapsService: No location provided. Skipping local resource discovery.")
            return LocalDiscoveryResult(
                resources=[],
                success=False,
                failure_reason="no_location_provided",
            )

        clean_loc = location.strip()
        query, res_type = self.build_query(category, clean_loc)

        # The query is built from the user's category and location, so logging
        # it verbatim would record that an identifiable session searched for,
        # say, a women's shelter in a named district. Log its shape instead.
        logger.info(
            "MapsService: discovering local resources %s",
            log_fields(
                resource_type=res_type,
                category=category,
                has_location=bool(clean_loc),
                query_chars=len(query),
            ),
        )

        outcome = await self._serpapi.search_detailed(
            query=query,
            vertical=SearchVertical.MAPS,
            location=clean_loc,
            num_results=num_results,
            reason=f"Find {res_type} near {clean_loc}",
        )

        if not outcome.success:
            logger.warning(
                "MapsService: discovery failed for '%s': %s",
                clean_loc,
                outcome.error_message,
            )
            return LocalDiscoveryResult(
                resources=[],
                success=False,
                failure_reason=outcome.failure_reason.value,
                query_used=query,
                location_used=clean_loc,
            )

        now = datetime.utcnow()
        local_resources: List[LocalResource] = []
        for r in outcome.results:
            if not r.title:
                continue

            domain = self._domain_of(r.url)
            verification, note = self._classify(r.title, domain)

            local_resources.append(
                LocalResource(
                    name=r.title,
                    type=res_type,
                    # Only record an address we were actually given. Falling back
                    # to the city name made every listing look located when it
                    # was not.
                    address=r.address,
                    phone=r.phone,
                    rating=r.rating,
                    review_count=r.reviews,
                    coordinates=r.coordinates,
                    website=r.url,
                    source_url=r.url,
                    source_domain=domain,
                    retrieved_at=now,
                    verification=verification,
                    verification_note=note,
                    relevance_reason=f"{res_type} listed near {clean_loc}.",
                )
            )

        logger.info("MapsService: Found %d local resources", len(local_resources))
        return LocalDiscoveryResult(
            resources=local_resources,
            success=True,
            failure_reason="none",
            query_used=query,
            location_used=clean_loc,
        )

    async def discover_local_resources(
        self,
        category: str,
        location: Optional[str] = None,
        case_summary: Optional[str] = None,
        num_results: int = 6,
    ) -> List[LocalResource]:
        """Backward-compatible wrapper returning only the resources."""
        result = await self.discover_local_resources_detailed(
            category=category,
            location=location,
            case_summary=case_summary,
            num_results=num_results,
        )
        return result.resources

    # ------------------------------------------------------------------
    # Provenance
    # ------------------------------------------------------------------

    @staticmethod
    def _classify(title: str, domain: Optional[str]) -> tuple[ResourceVerification, str]:
        """Decide how much we can honestly claim about a listing's provenance."""
        if domain and any(domain.endswith(sfx) for sfx in OFFICIAL_IN_SUFFIXES):
            return (
                ResourceVerification.OFFICIAL_SOURCE,
                f"Listed website is on the official government domain {domain}.",
            )

        title_lower = (title or "").lower()
        if any(kw in title_lower for kw in _GOV_TITLE_KEYWORDS):
            return (
                ResourceVerification.LIKELY_OFFICIAL,
                "Name matches a government service, but we could not confirm it "
                "against an official registry. Please call ahead before travelling.",
            )

        return (
            ResourceVerification.UNVERIFIED_LISTING,
            "This is a public map listing that HerWay has not been able to verify. "
            "Please confirm the address and phone number before relying on it.",
        )

    @staticmethod
    def _domain_of(url: Optional[str]) -> Optional[str]:
        if not url:
            return None
        try:
            parsed = urlparse(url)
            netloc = (parsed.netloc or parsed.path).lower()
            return netloc.replace("www.", "") or None
        except Exception:
            return None

    # ------------------------------------------------------------------
    # Geocoding
    # ------------------------------------------------------------------

    async def reverse_geocode(self, lat: float, lng: float) -> Optional[str]:
        """Convert coordinates to a human-readable location string via OpenCage."""
        if not self._opencage_key:
            logger.warning("MapsService: OPENCAGE_API_KEY not set")
            return None

        url = "https://api.opencagedata.com/geocode/v1/json"
        params = {"key": self._opencage_key, "q": f"{lat},{lng}", "countrycode": "in"}

        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                resp = await client.get(url, params=params)
                resp.raise_for_status()
                data = resp.json()
                results = data.get("results") or []
                if not results:
                    return None
                components = results[0].get("components", {})
                city = (
                    components.get("city")
                    or components.get("town")
                    or components.get("village")
                    or components.get("suburb")
                    or components.get("county")
                )
                state = components.get("state")
                if city and state:
                    return f"{city}, {state}"
                return city or state or components.get("country")
        except Exception as exc:
            logger.error("MapsService: reverse geocode failed: %s", exc)
            return None
