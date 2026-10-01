"""
Unit tests for SerpApiService.

Covers live search normalization, caching, retries, vertical routing, and the
full failure matrix required by the reliability spec:
missing key, timeout, HTTP error, rate limit, auth failure, empty result,
malformed result, and upstream quota errors.

All tests use mocks, so they run without a real SERPAPI_API_KEY.

Note on the mocks: ``httpx.Response.raise_for_status`` and ``.json`` are
*synchronous* methods. They must be mocked with ``MagicMock``, not
``AsyncMock`` — mocking them as async made ``resp.json()`` return a coroutine,
which silently broke every normalization assertion.
"""

import httpx
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from backend.models.research import (
    SearchFailureReason,
    SearchRequest,
    SearchResult,
    SearchVertical,
)
from backend.services.serpapi_service import SerpApiCache, SerpApiService


def _mock_response(payload: dict, status_code: int = 200) -> MagicMock:
    """Build a stand-in for an httpx.Response with the real sync method shapes."""
    resp = MagicMock()
    resp.status_code = status_code
    resp.raise_for_status = MagicMock()
    resp.json = MagicMock(return_value=payload)
    return resp


def _http_status_error(status: int) -> httpx.HTTPStatusError:
    request = httpx.Request("GET", "https://serpapi.com/search.json")
    response = httpx.Response(status, request=request)
    return httpx.HTTPStatusError(f"HTTP {status}", request=request, response=response)


# ---------------------------------------------------------------------------
# Normalization
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_serpapi_web_search_normalization():
    service = SerpApiService(api_key="mock_key")

    payload = {
        "organic_results": [
            {
                "title": "National Consumer Helpline Official Portal",
                "link": "https://consumerhelpline.gov.in",
                "snippet": "File consumer complaints online or call 1915.",
                "displayed_link": "consumerhelpline.gov.in",
                "position": 1,
            }
        ]
    }

    with patch("httpx.AsyncClient.get", new=AsyncMock(return_value=_mock_response(payload))):
        results = await service.search_web("consumer complaint India official")

    assert len(results) == 1
    res = results[0]
    assert res.title == "National Consumer Helpline Official Portal"
    assert res.url == "https://consumerhelpline.gov.in"
    assert res.domain == "consumerhelpline.gov.in"
    assert res.position == 1
    assert res.result_type == "web"


@pytest.mark.asyncio
async def test_serpapi_news_search_normalization():
    service = SerpApiService(api_key="mock_key")

    payload = {
        "news_results": [
            {
                "title": "Revised One Stop Centre guidelines notified",
                "link": "https://www.thehindu.com/news/osc-guidelines",
                "snippet": "The ministry notified revised operational guidelines.",
                "source": {"name": "The Hindu"},
                "date": "2 hours ago",
                "position": 1,
            }
        ]
    }

    with patch("httpx.AsyncClient.get", new=AsyncMock(return_value=_mock_response(payload))):
        results = await service.search_news("one stop centre guidelines")

    assert len(results) == 1
    res = results[0]
    assert res.title == "Revised One Stop Centre guidelines notified"
    assert res.source == "The Hindu"
    assert res.result_type == "news"


@pytest.mark.asyncio
async def test_serpapi_maps_search_normalization():
    service = SerpApiService(api_key="mock_key")

    payload = {
        "local_results": [
            {
                "title": "District Consumer Disputes Redressal Commission",
                "website": "https://consumerforum.gov.in",
                "description": "Government Consumer Dispute Redressal Forum",
                "address": "MG Road, Bengaluru, Karnataka",
                "phone": "+91 80 1234 5678",
                "rating": 4.5,
                "reviews": 120,
                "gps_coordinates": {"latitude": 12.9716, "longitude": 77.5946},
            }
        ]
    }

    with patch("httpx.AsyncClient.get", new=AsyncMock(return_value=_mock_response(payload))):
        results = await service.search_maps("consumer court", location="Bengaluru")

    assert len(results) == 1
    res = results[0]
    assert res.title == "District Consumer Disputes Redressal Commission"
    assert res.address == "MG Road, Bengaluru, Karnataka"
    assert res.phone == "+91 80 1234 5678"
    assert res.rating == 4.5
    assert res.coordinates == {"latitude": 12.9716, "longitude": 77.5946}


@pytest.mark.asyncio
async def test_maps_result_with_list_type_field_is_handled():
    """Google Maps returns `type` as a string OR a list.

    Regression test: the list form raised a ValidationError that discarded
    *every* result in the batch, so one oddly-shaped listing silently wiped out
    the entire nearby-services search for a case.
    """
    service = SerpApiService(api_key="mock_key")
    payload = {
        "local_results": [
            {
                "title": "District Legal Services Authority",
                "type": ["Government office", "Legal services"],
                "address": "Civil Lines, Nagpur, Maharashtra",
                "rating": "4.3",
                "reviews": "87",
            },
            {
                "title": "Mahila Thana",
                "type": "Police station",
                "gps_coordinates": {"latitude": "21.1458", "longitude": "79.0882"},
            },
        ]
    }

    with patch("httpx.AsyncClient.get", new=AsyncMock(return_value=_mock_response(payload))):
        outcome = await service.search_detailed(
            "legal aid", vertical=SearchVertical.MAPS, location="Nagpur"
        )

    assert outcome.success is True
    assert len(outcome.results) == 2, "A list-valued field must not drop results"
    assert outcome.results[0].snippet == "Government office, Legal services"
    # Numeric fields arriving as strings must still parse.
    assert outcome.results[0].rating == 4.3
    assert outcome.results[0].reviews == 87
    assert outcome.results[1].coordinates == {"latitude": 21.1458, "longitude": 79.0882}


@pytest.mark.asyncio
async def test_malformed_items_are_skipped_not_fatal():
    """One unusable listing must not discard the usable ones beside it."""
    service = SerpApiService(api_key="mock_key")
    payload = {
        "local_results": [
            "not-a-dict",
            {"address": "No title here"},
            {"title": "One Stop Centre, Nagpur", "address": "Civil Lines"},
        ]
    }

    with patch("httpx.AsyncClient.get", new=AsyncMock(return_value=_mock_response(payload))):
        outcome = await service.search_detailed("one stop centre", vertical=SearchVertical.MAPS)

    assert outcome.success is True
    assert len(outcome.results) == 1
    assert outcome.results[0].title == "One Stop Centre, Nagpur"


@pytest.mark.asyncio
async def test_highlighted_words_are_not_shown_as_a_publication_date():
    """`snippet_highlighted_words` is a list of matched terms, not a date."""
    service = SerpApiService(api_key="mock_key")
    payload = {
        "organic_results": [
            {
                "title": "Women Helpline",
                "link": "https://wcd.gov.in/x",
                "snippet": "181 operates 24x7.",
                "snippet_highlighted_words": ["helpline", "181"],
            }
        ]
    }

    with patch("httpx.AsyncClient.get", new=AsyncMock(return_value=_mock_response(payload))):
        outcome = await service.search_detailed("women helpline")

    assert outcome.results[0].published_at is None


# ---------------------------------------------------------------------------
# India-first locale defaults
# ---------------------------------------------------------------------------

def test_default_locale_is_india():
    """HerWay serves Indian users, so searches must not default to the US locale."""
    service = SerpApiService(api_key="mock_key")
    params = service._build_http_params(
        SearchRequest(query="women helpline", reason="test")
    )
    assert params["gl"] == "in"
    assert params["hl"] == "en"


def test_web_queries_are_scoped_to_india():
    """`gl=in` only biases ranking. A live search for "women helpline 181"
    returned a UK helpline first, so the jurisdiction goes in the query."""
    service = SerpApiService(api_key="mock_key")
    params = service._build_http_params(
        SearchRequest(query="women helpline 181 official site", reason="test")
    )
    assert params["q"].endswith(" India")


@pytest.mark.parametrize(
    "query",
    [
        "POSH Act complaint procedure",
        "One Stop Centre Nagpur Maharashtra",
        "cybercrime.gov.in reporting",
        "PWDVA protection order",
        "women helpline in India",
    ],
)
def test_already_indian_queries_are_not_padded(query):
    """Do not append "India" to a query that is already scoped to it."""
    service = SerpApiService(api_key="mock_key")
    params = service._build_http_params(SearchRequest(query=query, reason="test"))
    assert params["q"] == query


def test_non_india_locale_is_left_alone():
    service = SerpApiService(api_key="mock_key")
    params = service._build_http_params(
        SearchRequest(query="women helpline", reason="test", country="gb")
    )
    assert params["q"] == "women helpline"


def test_maps_query_includes_location():
    """The Maps engine keys off `q`, so the place name must be folded into it."""
    service = SerpApiService(api_key="mock_key")
    params = service._build_http_params(
        SearchRequest(
            query="One Stop Centre",
            vertical=SearchVertical.MAPS,
            reason="test",
            location="Bhopal, Madhya Pradesh",
        )
    )
    assert params["engine"] == "google_maps"
    assert "Bhopal" in params["q"]


# ---------------------------------------------------------------------------
# Caching & deduplication
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_serpapi_caching():
    service = SerpApiService(api_key="mock_key")
    payload = {
        "organic_results": [
            {"title": "Cached Result Test", "link": "https://test.gov.in", "snippet": "Snippet"}
        ]
    }

    mock_get = AsyncMock(return_value=_mock_response(payload))
    with patch("httpx.AsyncClient.get", new=mock_get):
        res1 = await service.search_web("identical query")
        assert len(res1) == 1
        assert mock_get.await_count == 1

        # Second identical call must be served from cache.
        res2 = await service.search_web("identical query")
        assert res2[0].title == "Cached Result Test"
        assert mock_get.await_count == 1


@pytest.mark.asyncio
async def test_cache_key_ignores_whitespace_and_case():
    """Whitespace variants must share a cache entry rather than burn a credit."""
    cache = SerpApiCache()
    a = cache._make_key("official women   helpline", "web", None, "in", "en", 1)
    b = cache._make_key("  OFFICIAL Women helpline  ", "web", None, "in", "en", 1)
    assert a == b


# ---------------------------------------------------------------------------
# Failure matrix
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_missing_api_key_reports_not_configured():
    """A missing key must be distinguishable from a genuinely empty result."""
    service = SerpApiService(api_key="")
    outcome = await service.search_detailed("women helpline")

    assert outcome.success is False
    assert outcome.results == []
    assert outcome.failure_reason == SearchFailureReason.NOT_CONFIGURED
    assert outcome.is_empty_but_successful is False


@pytest.mark.asyncio
async def test_serpapi_retry_then_report_network_failure():
    service = SerpApiService(api_key="mock_key", max_retries=2)
    mock_get = AsyncMock(side_effect=httpx.ConnectError("connection refused"))

    with patch("httpx.AsyncClient.get", new=mock_get):
        outcome = await service.search_detailed("failing query")

    assert outcome.success is False
    assert outcome.failure_reason == SearchFailureReason.NETWORK_ERROR
    assert mock_get.await_count == 2


@pytest.mark.asyncio
async def test_serpapi_timeout_is_reported_as_timeout():
    service = SerpApiService(api_key="mock_key", max_retries=2)
    mock_get = AsyncMock(side_effect=httpx.ReadTimeout("too slow"))

    with patch("httpx.AsyncClient.get", new=mock_get):
        outcome = await service.search_detailed("slow query")

    assert outcome.failure_reason == SearchFailureReason.TIMEOUT
    assert mock_get.await_count == 2


@pytest.mark.asyncio
async def test_serpapi_rate_limit_is_reported():
    service = SerpApiService(api_key="mock_key", max_retries=1)
    mock_get = AsyncMock(side_effect=_http_status_error(429))

    with patch("httpx.AsyncClient.get", new=mock_get):
        outcome = await service.search_detailed("rate limited query")

    assert outcome.failure_reason == SearchFailureReason.RATE_LIMITED


@pytest.mark.asyncio
async def test_serpapi_auth_failure_does_not_retry():
    """Bad credentials will not fix themselves — retrying just wastes time."""
    service = SerpApiService(api_key="bad_key", max_retries=3)
    mock_get = AsyncMock(side_effect=_http_status_error(401))

    with patch("httpx.AsyncClient.get", new=mock_get):
        outcome = await service.search_detailed("unauthorised query")

    assert outcome.failure_reason == SearchFailureReason.AUTH_FAILED
    assert mock_get.await_count == 1


@pytest.mark.asyncio
async def test_serpapi_http_500_is_reported_as_http_error():
    service = SerpApiService(api_key="mock_key", max_retries=2)
    mock_get = AsyncMock(side_effect=_http_status_error(500))

    with patch("httpx.AsyncClient.get", new=mock_get):
        outcome = await service.search_detailed("server error query")

    assert outcome.failure_reason == SearchFailureReason.HTTP_ERROR


@pytest.mark.asyncio
async def test_serpapi_empty_result_is_a_success():
    """Zero matches is a real answer, not a failure."""
    service = SerpApiService(api_key="mock_key")

    with patch("httpx.AsyncClient.get", new=AsyncMock(return_value=_mock_response({"organic_results": []}))):
        outcome = await service.search_detailed("query with no matches")

    assert outcome.success is True
    assert outcome.results == []
    assert outcome.is_empty_but_successful is True
    assert outcome.failure_reason == SearchFailureReason.NONE


@pytest.mark.asyncio
async def test_serpapi_malformed_json_is_reported():
    service = SerpApiService(api_key="mock_key", max_retries=2)
    resp = MagicMock()
    resp.raise_for_status = MagicMock()
    resp.json = MagicMock(side_effect=ValueError("not json"))

    with patch("httpx.AsyncClient.get", new=AsyncMock(return_value=resp)):
        outcome = await service.search_detailed("malformed query")

    assert outcome.failure_reason == SearchFailureReason.MALFORMED_RESPONSE


@pytest.mark.asyncio
async def test_serpapi_payload_not_a_dict_is_reported():
    service = SerpApiService(api_key="mock_key")

    with patch("httpx.AsyncClient.get", new=AsyncMock(return_value=_mock_response(["unexpected"]))):
        outcome = await service.search_detailed("odd payload query")

    assert outcome.failure_reason == SearchFailureReason.MALFORMED_RESPONSE


@pytest.mark.asyncio
async def test_serpapi_upstream_quota_error_in_200_body():
    """SerpApi reports an exhausted plan inside a 200 response."""
    service = SerpApiService(api_key="mock_key")
    payload = {"error": "Your account has run out of searches."}

    with patch("httpx.AsyncClient.get", new=AsyncMock(return_value=_mock_response(payload))):
        outcome = await service.search_detailed("quota query")

    assert outcome.success is False
    assert outcome.failure_reason == SearchFailureReason.RATE_LIMITED


@pytest.mark.asyncio
async def test_unexpected_exception_does_not_escape():
    """One bad search must never take down the whole case."""
    service = SerpApiService(api_key="mock_key", max_retries=1)

    with patch("httpx.AsyncClient.get", new=AsyncMock(side_effect=RuntimeError("boom"))):
        outcome = await service.search_detailed("exploding query")

    assert outcome.success is False
    assert outcome.results == []
