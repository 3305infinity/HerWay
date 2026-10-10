"""
SerpApiService — Live SerpApi search service for Haven's research layer.

Key Capabilities
----------------
1. Structured Search Methods:
   - search_web()
   - search_news()
   - search_local()
   - search_maps()
   - execute_search()
2. Normalization: Converts raw JSON from Google Search, Google News, and
   Google Maps engines into clean, typed ``SearchResult`` Pydantic objects.
3. Resilience & Performance:
   - Retries with exponential backoff for transient HTTP errors / timeouts.
   - Configurable timeouts.
   - In-memory search cache to eliminate duplicate queries and save credits.
4. Structured Logging:
   - Logs case_id, search_id, vertical, query, result_count, latency_ms, success.
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
import logging
import os
import time
import uuid
from enum import Enum
from typing import Any, Dict, List, Optional
from urllib.parse import urlparse

import httpx
from dotenv import load_dotenv

from backend.models.research import (
    DEFAULT_COUNTRY,
    DEFAULT_LANGUAGE,
    SearchFailureReason,
    SearchOutcome,
    SearchRequest,
    SearchResult,
    SearchVertical,
)
from backend.services.search_cache import SerpApiCache  # noqa: F401  (re-export)
from backend.trace import log_fields

load_dotenv()

logger = logging.getLogger(__name__)

# Official SerpApi search endpoint
_SERPAPI_URL = "https://serpapi.com/search.json"


# ---------------------------------------------------------------------------
# Defensive field coercion
#
# SerpApi's shapes vary by engine and by result. The same key can arrive as a
# string, a list, a number or be absent entirely — Google Maps returns `type`
# as either "Government office" or ["Government office"]. One unexpected shape
# used to raise a ValidationError that discarded every result in the batch, so
# a single odd listing silently wiped out the whole local search for a case.
# ---------------------------------------------------------------------------

#: Terms that already pin a query to India, so we do not append "India" twice.
_INDIA_TERMS = (
    "india", "indian", "bharat",
    "gov.in", "nic.in",
    "andhra", "arunachal", "assam", "bihar", "chhattisgarh", "goa", "gujarat",
    "haryana", "himachal", "jharkhand", "karnataka", "kerala", "madhya pradesh",
    "maharashtra", "manipur", "meghalaya", "mizoram", "nagaland", "odisha",
    "punjab", "rajasthan", "sikkim", "tamil nadu", "telangana", "tripura",
    "uttar pradesh", "uttarakhand", "west bengal", "delhi", "puducherry",
    "chandigarh", "ladakh", "kashmir", "andaman", "lakshadweep",
    "posh act", "pwdva", "ipc", "bns", "sakhi", "mahila", "nalsa", "ncw",
)


#: HerWay's internal vertical names mapped to SerpApi's own engine ids.
#: Defined once so the request builder and the cache path cannot drift apart
#: and report different engines for the same search.
_PROVIDER_ENGINES = {
    "news": "google_news",
    "google_news": "google_news",
    "maps": "google_maps",
    "local": "google_maps",
    "google_maps": "google_maps",
}


def _provider_engine_for(vertical: str) -> str:
    """The SerpApi engine id for a vertical. Defaults to plain Google Search."""
    return _PROVIDER_ENGINES.get((vertical or "web").strip().lower(), "google")


def _mentions_india(query: str) -> bool:
    """True when a query is already scoped to India."""
    lowered = (query or "").lower()
    return any(term in lowered for term in _INDIA_TERMS)


def _as_text(value: Any) -> str:
    """Coerce a SerpApi field to a plain string, flattening lists."""
    if value is None:
        return ""
    if isinstance(value, str):
        return value.strip()
    if isinstance(value, (list, tuple)):
        return ", ".join(_as_text(v) for v in value if v is not None).strip()
    if isinstance(value, dict):
        for key in ("name", "title", "text", "value"):
            if key in value:
                return _as_text(value[key])
        return ""
    return str(value).strip()


def _as_float(value: Any) -> Optional[float]:
    try:
        return float(value) if value is not None else None
    except (TypeError, ValueError):
        return None


def _as_int(value: Any) -> Optional[int]:
    try:
        return int(value) if value is not None else None
    except (TypeError, ValueError):
        return None


# ``SerpApiCache`` now lives in ``backend.services.search_cache`` so it can be
# shared across worker processes. It is re-exported here unchanged: this module
# was its original home and existing imports and tests refer to it by this path.
#
# The ``get``/``set`` signatures are identical to the in-memory version this
# replaced; only the storage behind them changed. See search_cache.py for the
# backend choices and their operational requirements.


class SerpApiService:
    """Production SerpApi HTTP service with retry, caching, and normalization."""

    def __init__(
        self,
        api_key: Optional[str] = None,
        cache_ttl_seconds: int = 3600,
        max_retries: int = 3,
        # 15s was marginal on slower connections: the Google Search engine
        # regularly took longer, so every attempt timed out and a perfectly
        # healthy search was reported as a failure.
        default_timeout: float = float(os.getenv("SERPAPI_TIMEOUT_SECONDS", "30")),
    ) -> None:
        # An explicitly supplied key (including an empty string, meaning "no
        # key") always wins; only fall back to the environment when the caller
        # passed nothing at all. Previously ``api_key=""`` silently fell through
        # to the environment, so a test for the unconfigured path made a real
        # billable API call.
        if api_key is None:
            # Check SERPAPI_API_KEY first, fallback to SERPAPI_KEY
            self._api_key = os.getenv("SERPAPI_API_KEY") or os.getenv("SERPAPI_KEY") or ""
        else:
            self._api_key = api_key
        if not self._api_key:
            logger.warning(
                "SerpApiService: Neither SERPAPI_API_KEY nor SERPAPI_KEY is set. "
                "Live API calls will fail or rely on mocks in tests."
            )
        self._cache = SerpApiCache(ttl_seconds=cache_ttl_seconds)
        self._max_retries = max_retries
        self._default_timeout = default_timeout

    # ------------------------------------------------------------------
    # High-level Structured Search Methods
    # ------------------------------------------------------------------

    async def search_web(
        self,
        query: str,
        location: Optional[str] = None,
        country: str = DEFAULT_COUNTRY,
        language: str = DEFAULT_LANGUAGE,
        num_results: int = 10,
        page: int = 1,
        case_id: Optional[str] = None,
        search_id: Optional[str] = None,
    ) -> List[SearchResult]:
        """Search Google Web Search engine."""
        request = SearchRequest(
            query=query,
            vertical=SearchVertical.WEB,
            reason="Web Search",
            location=location,
            country=country,
            language=language,
            num_results=num_results,
            page=page,
        )
        return await self.execute_search(request, case_id=case_id, search_id=search_id)

    async def search_news(
        self,
        query: str,
        location: Optional[str] = None,
        country: str = DEFAULT_COUNTRY,
        language: str = DEFAULT_LANGUAGE,
        num_results: int = 10,
        page: int = 1,
        case_id: Optional[str] = None,
        search_id: Optional[str] = None,
    ) -> List[SearchResult]:
        """Search Google News engine."""
        request = SearchRequest(
            query=query,
            vertical=SearchVertical.NEWS,
            reason="News Search",
            location=location,
            country=country,
            language=language,
            num_results=num_results,
            page=page,
        )
        return await self.execute_search(request, case_id=case_id, search_id=search_id)

    async def search_local(
        self,
        query: str,
        location: Optional[str] = None,
        country: str = DEFAULT_COUNTRY,
        language: str = DEFAULT_LANGUAGE,
        num_results: int = 10,
        page: int = 1,
        case_id: Optional[str] = None,
        search_id: Optional[str] = None,
    ) -> List[SearchResult]:
        """Search Google Local results."""
        request = SearchRequest(
            query=query,
            vertical=SearchVertical.LOCAL,
            reason="Local Service Search",
            location=location,
            country=country,
            language=language,
            num_results=num_results,
            page=page,
        )
        return await self.execute_search(request, case_id=case_id, search_id=search_id)

    async def search_maps(
        self,
        query: str,
        location: Optional[str] = None,
        country: str = DEFAULT_COUNTRY,
        language: str = DEFAULT_LANGUAGE,
        num_results: int = 10,
        page: int = 1,
        case_id: Optional[str] = None,
        search_id: Optional[str] = None,
    ) -> List[SearchResult]:
        """Search Google Maps engine."""
        request = SearchRequest(
            query=query,
            vertical=SearchVertical.MAPS,
            reason="Maps Search",
            location=location,
            country=country,
            language=language,
            num_results=num_results,
            page=page,
        )
        return await self.execute_search(request, case_id=case_id, search_id=search_id)

    async def search_detailed(
        self,
        query: str,
        vertical: SearchVertical = SearchVertical.WEB,
        location: Optional[str] = None,
        country: str = DEFAULT_COUNTRY,
        language: str = DEFAULT_LANGUAGE,
        num_results: int = 10,
        case_id: Optional[str] = None,
        search_id: Optional[str] = None,
        reason: str = "Targeted search",
    ) -> SearchOutcome:
        """Run a search on any vertical and return the full outcome.

        This is the entry point the research pipeline uses, because it needs to
        distinguish "no results" from "this vertical was unavailable".
        """
        request = SearchRequest(
            query=query,
            vertical=vertical,
            reason=reason,
            location=location,
            country=country,
            language=language,
            num_results=num_results,
        )
        return await self.execute_search_detailed(
            request, case_id=case_id, search_id=search_id
        )

    # Backward compatibility signature: search(query, search_type, location, num_results)
    async def search(
        self,
        query: str,
        search_type: Any = SearchVertical.WEB,
        location: Optional[str] = None,
        num_results: int = 10,
    ) -> List[SearchResult]:
        v_str = getattr(search_type, "value", str(search_type))
        if "news" in v_str:
            vertical = SearchVertical.NEWS
        elif "map" in v_str or "local" in v_str:
            vertical = SearchVertical.MAPS
        else:
            vertical = SearchVertical.WEB

        req = SearchRequest(
            query=query,
            vertical=vertical,
            reason="Generic Search",
            location=location,
            num_results=num_results,
        )
        return await self.execute_search(req)

    # ------------------------------------------------------------------
    # Core Executor with Caching, Retries & Logging
    # ------------------------------------------------------------------

    async def execute_search(
        self,
        request: SearchRequest,
        case_id: Optional[str] = None,
        search_id: Optional[str] = None,
    ) -> List[SearchResult]:
        """Execute a SearchRequest and return just the results.

        Prefer :meth:`execute_search_detailed` in new code — it also reports
        *why* a search returned nothing, which the UI needs so that an outage
        is never displayed as "we searched and found nothing".
        """
        outcome = await self.execute_search_detailed(
            request, case_id=case_id, search_id=search_id
        )
        return outcome.results

    async def execute_search_detailed(
        self,
        request: SearchRequest,
        case_id: Optional[str] = None,
        search_id: Optional[str] = None,
    ) -> SearchOutcome:
        """Execute a SearchRequest with caching, retries, and an explicit outcome."""
        s_id = search_id or f"srch_{uuid.uuid4().hex[:8]}"
        c_id = case_id or "general"
        v_name = request.vertical.value if isinstance(request.vertical, Enum) else str(request.vertical)

        def _fail(reason: SearchFailureReason, message: str, latency: float = 0.0) -> SearchOutcome:
            self._log_execution(
                case_id=c_id,
                search_id=s_id,
                vertical=v_name,
                query=request.query,
                result_count=0,
                latency_ms=latency,
                success=False,
                cached=False,
                error=f"{reason.value}: {message}",
            )
            return SearchOutcome(
                vertical=v_name,
                query=request.query,
                success=False,
                results=[],
                failure_reason=reason,
                error_message=message,
                latency_ms=latency,
            )

        # 0. Configuration guard — fail loudly rather than returning an empty
        #    list that looks identical to "no matches found".
        if not self._api_key:
            return _fail(
                SearchFailureReason.NOT_CONFIGURED,
                "SERPAPI_API_KEY is not configured, so live research could not run.",
            )

        # 1. Check Cache
        cached = self._cache.get(
            query=request.query,
            vertical=v_name,
            location=request.location,
            country=request.country,
            language=request.language,
            page=request.page,
        )
        if cached is not None:
            self._log_execution(
                case_id=c_id,
                search_id=s_id,
                vertical=v_name,
                query=request.query,
                result_count=len(cached),
                latency_ms=0.0,
                success=True,
                cached=True,
            )
            return SearchOutcome(
                vertical=v_name,
                query=request.query,
                success=True,
                results=cached,
                from_cache=True,
                provider_engine=_provider_engine_for(v_name),
                # Deliberately NOT `now`: this is the time of the original
                # fetch. Stamping a cache hit with the current time would
                # present hour-old data as fresh.
                #
                # `v_name` — the same vertical the cache lookup above used, so
                # the key matches. (`v_str` is the live path's local and is not
                # in scope here.)
                retrieved_at=self._cache.cached_at(
                    request.query, v_name, request.location,
                    request.country, request.language, request.page,
                ),
            )

        # 2. Build HTTP parameters
        params = self._build_http_params(request)

        # 3. Execute HTTP Call with Retries & Exponential Backoff
        start_time = time.time()
        data: Optional[Dict[str, Any]] = None
        last_reason = SearchFailureReason.NETWORK_ERROR
        last_message = "Unknown error"

        for attempt in range(1, self._max_retries + 1):
            try:
                async with httpx.AsyncClient(timeout=self._default_timeout) as client:
                    resp = await client.get(_SERPAPI_URL, params=params)
                    resp.raise_for_status()
                    data = resp.json()
                    break
            except httpx.HTTPStatusError as exc:
                status = exc.response.status_code
                last_message = f"SerpApi returned HTTP {status}."
                if status == 429:
                    last_reason = SearchFailureReason.RATE_LIMITED
                elif status in (401, 403):
                    # Credentials will not become valid on retry.
                    logger.error("SerpApiService: credentials rejected (HTTP %s)", status)
                    return _fail(
                        SearchFailureReason.AUTH_FAILED,
                        last_message,
                        round((time.time() - start_time) * 1000, 2),
                    )
                else:
                    last_reason = SearchFailureReason.HTTP_ERROR
            except httpx.TimeoutException:
                last_reason = SearchFailureReason.TIMEOUT
                last_message = f"SerpApi did not respond within {self._default_timeout:.0f}s."
            except httpx.RequestError as exc:
                last_reason = SearchFailureReason.NETWORK_ERROR
                last_message = f"Could not reach SerpApi: {exc.__class__.__name__}."
            except ValueError:
                # resp.json() on a non-JSON body — retrying will not help.
                return _fail(
                    SearchFailureReason.MALFORMED_RESPONSE,
                    "SerpApi returned a response that could not be parsed as JSON.",
                    round((time.time() - start_time) * 1000, 2),
                )
            except Exception as exc:  # noqa: BLE001 - never let one search kill a case
                last_reason = SearchFailureReason.NETWORK_ERROR
                last_message = f"Unexpected error calling SerpApi: {exc.__class__.__name__}."

            logger.warning(
                "SerpApiService attempt %d/%d failed for vertical='%s': %s",
                attempt,
                self._max_retries,
                v_name,
                last_message,
            )
            if attempt < self._max_retries:
                await asyncio.sleep(0.5 * (2 ** (attempt - 1)))  # 0.5s, 1.0s, 2.0s...

        latency_ms = round((time.time() - start_time) * 1000, 2)

        if data is None:
            return _fail(last_reason, last_message, latency_ms)

        if not isinstance(data, dict):
            return _fail(
                SearchFailureReason.MALFORMED_RESPONSE,
                "SerpApi returned an unexpected payload shape.",
                latency_ms,
            )

        # SerpApi signals quota and parameter problems inside a 200 response body.
        upstream_error = data.get("error")
        if upstream_error:
            text = str(upstream_error).lower()
            reason = (
                SearchFailureReason.RATE_LIMITED
                if ("run out" in text or "limit" in text or "quota" in text)
                else SearchFailureReason.UPSTREAM_ERROR
            )
            return _fail(reason, str(upstream_error), latency_ms)

        # 4. Parse & Normalize Results
        try:
            results = self._normalize_response(data, v_name)
        except Exception as exc:
            logger.exception("SerpApiService: normalization failed for vertical='%s'", v_name)
            return _fail(
                SearchFailureReason.MALFORMED_RESPONSE,
                f"Search results could not be read ({exc.__class__.__name__}).",
                latency_ms,
            )

        # 5. Populate Cache
        self._cache.set(
            query=request.query,
            vertical=v_name,
            location=request.location,
            country=request.country,
            language=request.language,
            page=request.page,
            results=results,
        )

        # 6. Structured Logging
        self._log_execution(
            case_id=c_id,
            search_id=s_id,
            vertical=v_name,
            query=request.query,
            result_count=len(results),
            latency_ms=latency_ms,
            success=True,
            cached=False,
        )

        return SearchOutcome(
            vertical=v_name,
            query=request.query,
            success=True,
            results=results,
            latency_ms=latency_ms,
            # Provenance: the provider's own engine id, and when this was
            # actually fetched. Both travel with the results into the research
            # trail so a reader can see which SerpApi engine produced what, and
            # how old it is.
            provider_engine=params.get("engine"),
            retrieved_at=datetime.now(timezone.utc),
        )

    # ------------------------------------------------------------------
    # Internal Helpers
    # ------------------------------------------------------------------

    def _build_http_params(self, request: SearchRequest) -> Dict[str, Any]:
        query = request.query
        v_str = request.vertical.value if isinstance(request.vertical, Enum) else str(request.vertical)

        params: Dict[str, Any] = {
            "api_key": self._api_key,
            "num": request.num_results,
            "gl": request.country or DEFAULT_COUNTRY,
            "hl": request.language or DEFAULT_LANGUAGE,
        }

        if v_str in ("news", "google_news"):
            params["engine"] = "google_news"
        elif v_str in ("maps", "local", "google_maps"):
            params["engine"] = "google_maps"
            params["type"] = "search"
            # The Maps engine keys off the query text, not the `location`
            # parameter (which only biases the Google Search engine). Without
            # folding the place name into `q`, a search for "One Stop Centre"
            # in Bhopal silently returns results from anywhere in the world.
            if request.location and request.location.lower() not in query.lower():
                query = f"{query} {request.location}".strip()
        else:
            params["engine"] = "google"
            if request.location:
                params["location"] = request.location
            # `gl=in` only biases ranking, it does not restrict results: a
            # search for "women helpline 181" returned a UK helpline first.
            # Naming the jurisdiction in the query keeps answers applicable.
            if (request.country or DEFAULT_COUNTRY) == "in" and not _mentions_india(query):
                query = f"{query} India"

        params["q"] = query

        if request.page > 1:
            if params["engine"] == "google":
                params["start"] = (request.page - 1) * request.num_results
            else:
                params["start"] = request.page

        return params

    def _normalize_response(
        self, data: Dict[str, Any], vertical: str
    ) -> List[SearchResult]:
        """Normalize raw SerpApi response JSON into structured SearchResult objects."""
        results: List[SearchResult] = []

        if vertical in ("news", "google_news"):
            news_items = data.get("news_results") or []
            if not isinstance(news_items, list):
                news_items = []

            for item in news_items:
                if not isinstance(item, dict):
                    continue
                title = _as_text(item.get("title"))
                if not title:
                    continue

                link = _as_text(item.get("link")) or None
                domain = self._extract_domain(link)
                source_name = _as_text(item.get("source"))

                results.append(
                    SearchResult(
                        title=title,
                        url=link,
                        source=source_name or domain,
                        domain=domain,
                        snippet=_as_text(item.get("snippet")),
                        published_at=_as_text(item.get("date")) or None,
                        position=_as_int(item.get("position")),
                        result_type="news",
                        thumbnail=_as_text(item.get("thumbnail")) or None,
                        raw_metadata={"news_item": item},
                    )
                )

        elif vertical in ("maps", "local", "google_maps"):
            # Check local_results or place_results
            items = data.get("local_results", []) or data.get("place_results", [])
            if isinstance(items, dict):
                items = [items]
            if not isinstance(items, list):
                items = []

            for idx, item in enumerate(items):
                if not isinstance(item, dict):
                    continue

                title = _as_text(item.get("title"))
                if not title:
                    # A listing with no name is not usable.
                    continue

                link = _as_text(item.get("website")) or _as_text(item.get("link")) or None
                # Google Maps returns `type` as either a string or a list of
                # category labels (e.g. ['Government office']). Passing the list
                # straight through failed validation and threw away every maps
                # result for the whole case.
                snippet = _as_text(item.get("description")) or _as_text(item.get("type"))
                address = _as_text(item.get("address")) or None
                phone = _as_text(item.get("phone")) or None
                thumbnail = _as_text(item.get("thumbnail")) or None

                gps = item.get("gps_coordinates")
                coords = None
                if isinstance(gps, dict):
                    lat, lng = _as_float(gps.get("latitude")), _as_float(gps.get("longitude"))
                    if lat is not None and lng is not None:
                        coords = {"latitude": lat, "longitude": lng}

                results.append(
                    SearchResult(
                        title=title,
                        url=link,
                        source="Google Maps",
                        domain=self._extract_domain(link),
                        snippet=snippet,
                        position=idx + 1,
                        result_type="maps",
                        thumbnail=thumbnail,
                        address=address,
                        rating=_as_float(item.get("rating")),
                        reviews=_as_int(item.get("reviews")),
                        phone=phone,
                        coordinates=coords,
                        raw_metadata={"maps_item": item},
                    )
                )

        else:
            # Default Google Organic Search
            organic = data.get("organic_results") or []
            if not isinstance(organic, list):
                organic = []

            for item in organic:
                if not isinstance(item, dict):
                    continue
                title = _as_text(item.get("title"))
                if not title:
                    continue

                link = _as_text(item.get("link")) or None
                domain = self._extract_domain(link)
                # Only `date` is an actual publication date.
                # `snippet_highlighted_words` is a list of matched terms and was
                # being stringified into this field, so results displayed
                # things like "['helpline', '181']" as their publication date.
                published = _as_text(item.get("date")) or None

                results.append(
                    SearchResult(
                        title=title,
                        url=link,
                        source=_as_text(item.get("displayed_link")) or domain,
                        domain=domain,
                        snippet=_as_text(item.get("snippet")),
                        published_at=published,
                        position=_as_int(item.get("position")),
                        result_type="web",
                        raw_metadata={"organic_item": item},
                    )
                )

        return results

    def _extract_domain(self, url: Optional[str]) -> Optional[str]:
        if not url:
            return None
        try:
            parsed = urlparse(url)
            netloc = parsed.netloc or parsed.path
            return netloc.lower().replace("www.", "")
        except Exception:
            return None

    def _log_execution(
        self,
        case_id: str,
        search_id: str,
        vertical: str,
        query: str,
        result_count: int,
        latency_ms: float,
        success: bool,
        cached: bool = False,
        error: Optional[str] = None,
    ) -> None:
        """Structured logger — omits any sensitive user parameters."""
        log_data = {
            "event": "serpapi_search_executed",
            "case_id": case_id,
            "search_id": search_id,
            "vertical": vertical,
            "query_length": len(query),
            "result_count": result_count,
            "latency_ms": latency_ms,
            "success": success,
            "cached": cached,
            "error": error,
        }
        logger.info("SerpApiLog: %s", log_data)

