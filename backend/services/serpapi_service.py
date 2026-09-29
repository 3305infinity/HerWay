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
import logging
import os
import time
import uuid
from typing import Any, Dict, List, Optional
from urllib.parse import urlparse

import httpx
from dotenv import load_dotenv

from backend.models.research import SearchRequest, SearchResult, SearchVertical

load_dotenv()

logger = logging.getLogger(__name__)

# Official SerpApi search endpoint
_SERPAPI_URL = "https://serpapi.com/search.json"


class SerpApiCache:
    """In-memory cache for identical search requests to prevent credit wastage."""

    def __init__(self, ttl_seconds: int = 3600) -> None:
        self._cache: Dict[str, tuple[float, List[SearchResult]]] = {}
        self._ttl_seconds = ttl_seconds

    def _make_key(
        self,
        query: str,
        vertical: str,
        location: Optional[str],
        country: Optional[str],
        language: Optional[str],
        page: int,
    ) -> str:
        clean_q = (query or "").strip().lower()
        clean_v = (vertical or "web").strip().lower()
        clean_loc = (location or "").strip().lower()
        clean_gl = (country or "us").strip().lower()
        clean_hl = (language or "en").strip().lower()
        return f"{clean_v}:{clean_q}:{clean_loc}:{clean_gl}:{clean_hl}:{page}"

    def get(
        self,
        query: str,
        vertical: str,
        location: Optional[str],
        country: Optional[str],
        language: Optional[str],
        page: int = 1,
    ) -> Optional[List[SearchResult]]:
        key = self._make_key(query, vertical, location, country, language, page)
        if key in self._cache:
            timestamp, results = self._cache[key]
            if time.time() - timestamp < self._ttl_seconds:
                logger.info("SerpApiCache: HIT for key='%s'", key)
                return results
            else:
                del self._cache[key]
        return None

    def set(
        self,
        query: str,
        vertical: str,
        location: Optional[str],
        country: Optional[str],
        language: Optional[str],
        page: int,
        results: List[SearchResult],
    ) -> None:
        key = self._make_key(query, vertical, location, country, language, page)
        self._cache[key] = (time.time(), results)


class SerpApiService:
    """Production SerpApi HTTP service with retry, caching, and normalization."""

    def __init__(
        self,
        api_key: Optional[str] = None,
        cache_ttl_seconds: int = 3600,
        max_retries: int = 3,
        default_timeout: float = 15.0,
    ) -> None:
        # Check SERPAPI_API_KEY first, fallback to SERPAPI_KEY
        self._api_key = (
            api_key
            or os.getenv("SERPAPI_API_KEY")
            or os.getenv("SERPAPI_KEY")
            or ""
        )
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
        country: str = "us",
        language: str = "en",
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
        country: str = "us",
        language: str = "en",
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
        country: str = "us",
        language: str = "en",
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
        country: str = "us",
        language: str = "en",
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
        """Execute a SearchRequest with caching, retries, and normalized output."""
        s_id = search_id or f"srch_{uuid.uuid4().hex[:8]}"
        c_id = case_id or "general"
        v_name = request.vertical.value if isinstance(request.vertical, Enum) else str(request.vertical)

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
            return cached

        # 2. Build HTTP parameters
        params = self._build_http_params(request)

        # 3. Execute HTTP Call with Retries & Exponential Backoff
        start_time = time.time()
        data: Optional[Dict[str, Any]] = None
        last_exception: Optional[Exception] = None

        for attempt in range(1, self._max_retries + 1):
            try:
                async with httpx.AsyncClient(timeout=self._default_timeout) as client:
                    resp = await client.get(_SERPAPI_URL, params=params)
                    resp.raise_for_status()
                    data = resp.json()
                    break
            except (httpx.HTTPStatusError, httpx.RequestError, httpx.TimeoutException) as exc:
                last_exception = exc
                logger.warning(
                    "SerpApiService attempt %d/%d failed for query='%s': %s",
                    attempt,
                    self._max_retries,
                    request.query,
                    exc,
                )
                if attempt < self._max_retries:
                    await asyncio.sleep(0.5 * (2 ** (attempt - 1)))  # 0.5s, 1.0s, 2.0s...

        latency_ms = round((time.time() - start_time) * 1000, 2)

        if data is None:
            logger.error(
                "SerpApiService: All retries failed for case_id=%s, search_id=%s, query='%s': %s",
                c_id,
                s_id,
                request.query,
                last_exception,
            )
            self._log_execution(
                case_id=c_id,
                search_id=s_id,
                vertical=v_name,
                query=request.query,
                result_count=0,
                latency_ms=latency_ms,
                success=False,
                cached=False,
                error=str(last_exception),
            )
            return []

        # 4. Parse & Normalize Results
        results = self._normalize_response(data, v_name)

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

        return results

    # ------------------------------------------------------------------
    # Internal Helpers
    # ------------------------------------------------------------------

    def _build_http_params(self, request: SearchRequest) -> Dict[str, Any]:
        params: Dict[str, Any] = {
            "api_key": self._api_key,
            "q": request.query,
            "num": request.num_results,
            "gl": request.country or "us",
            "hl": request.language or "en",
        }

        v_str = request.vertical.value if isinstance(request.vertical, Enum) else str(request.vertical)

        if v_str == "news" or v_str == "google_news":
            params["engine"] = "google_news"
        elif v_str in ("maps", "local", "google_maps"):
            params["engine"] = "google_maps"
            params["type"] = "search"
        else:
            params["engine"] = "google"

        if request.location:
            params["location"] = request.location

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
            for item in data.get("news_results", []):
                title = item.get("title", "")
                link = item.get("link")
                snippet = item.get("snippet", "")
                source_name = item.get("source", {}).get("name") if isinstance(item.get("source"), dict) else item.get("source")
                pub_date = item.get("date")
                thumbnail = item.get("thumbnail")

                domain = self._extract_domain(link)

                results.append(
                    SearchResult(
                        title=title,
                        url=link,
                        source=source_name or domain,
                        domain=domain,
                        snippet=snippet,
                        published_at=pub_date,
                        position=item.get("position"),
                        result_type="news",
                        thumbnail=thumbnail,
                        raw_metadata={"news_item": item},
                    )
                )

        elif vertical in ("maps", "local", "google_maps"):
            # Check local_results or place_results
            items = data.get("local_results", []) or data.get("place_results", [])
            if isinstance(items, dict):
                items = [items]

            for idx, item in enumerate(items):
                title = item.get("title", "")
                link = item.get("website") or item.get("link")
                snippet = item.get("description", "") or item.get("type", "")
                address = item.get("address")
                phone = item.get("phone")
                rating = item.get("rating")
                reviews = item.get("reviews")
                thumbnail = item.get("thumbnail")
                gps = item.get("gps_coordinates")

                coords = None
                if isinstance(gps, dict) and "latitude" in gps and "longitude" in gps:
                    coords = {
                        "latitude": float(gps["latitude"]),
                        "longitude": float(gps["longitude"]),
                    }

                domain = self._extract_domain(link)

                results.append(
                    SearchResult(
                        title=title,
                        url=link,
                        source="Google Maps",
                        domain=domain,
                        snippet=snippet,
                        position=idx + 1,
                        result_type="maps",
                        thumbnail=thumbnail,
                        address=address,
                        rating=float(rating) if rating is not None else None,
                        reviews=int(reviews) if reviews is not None else None,
                        phone=phone,
                        coordinates=coords,
                        raw_metadata={"maps_item": item},
                    )
                )

        else:
            # Default Google Organic Search
            for item in data.get("organic_results", []):
                title = item.get("title", "")
                link = item.get("link")
                snippet = item.get("snippet", "")
                source_display = item.get("displayed_link")
                domain = self._extract_domain(link)
                pub_date = item.get("snippet_highlighted_words") or item.get("date")

                results.append(
                    SearchResult(
                        title=title,
                        url=link,
                        source=source_display or domain,
                        domain=domain,
                        snippet=snippet,
                        published_at=str(pub_date) if pub_date else None,
                        position=item.get("position"),
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

