"""
Unit tests for SerpApiService (Task 1).

Tests live search normalization, caching, retries, and vertical routing
using mocks so unit tests execute cleanly without needing a real SERPAPI_API_KEY.
"""

import pytest
from unittest.mock import AsyncMock, patch

from backend.models.research import SearchRequest, SearchResult, SearchVertical
from backend.services.serpapi_service import SerpApiCache, SerpApiService


@pytest.mark.asyncio
async def test_serpapi_web_search_normalization():
    service = SerpApiService(api_key="mock_key")

    mock_response_json = {
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

    with patch("httpx.AsyncClient.get") as mock_get:
        mock_resp = AsyncMock()
        mock_resp.raise_for_status = AsyncMock()
        mock_resp.json = AsyncMock(return_value=mock_response_json)
        mock_get.return_value = mock_resp

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

    mock_news_json = {
        "news_results": [
            {
                "title": "New E-Commerce Refund Rules Introduced in 2026",
                "link": "https://news.example.com/consumer-rules",
                "snippet": "New guidelines mandate 14-day replacement window.",
                "source": {"name": "Tech Times"},
                "date": "2 hours ago",
                "position": 1,
            }
        ]
    }

    with patch("httpx.AsyncClient.get") as mock_get:
        mock_resp = AsyncMock()
        mock_resp.raise_for_status = AsyncMock()
        mock_resp.json = AsyncMock(return_value=mock_news_json)
        mock_get.return_value = mock_resp

        results = await service.search_news("damaged product refund rules")

        assert len(results) == 1
        res = results[0]
        assert res.title == "New E-Commerce Refund Rules Introduced in 2026"
        assert res.source == "Tech Times"
        assert res.result_type == "news"


@pytest.mark.asyncio
async def test_serpapi_maps_search_normalization():
    service = SerpApiService(api_key="mock_key")

    mock_maps_json = {
        "local_results": [
            {
                "title": "District Consumer Forum",
                "website": "https://consumerforum.gov.in",
                "description": "Government Consumer Dispute Redressal Forum",
                "address": "MG Road, Bengaluru",
                "phone": "+91 80 1234 5678",
                "rating": 4.5,
                "reviews": 120,
                "gps_coordinates": {"latitude": 12.9716, "longitude": 77.5946},
            }
        ]
    }

    with patch("httpx.AsyncClient.get") as mock_get:
        mock_resp = AsyncMock()
        mock_resp.raise_for_status = AsyncMock()
        mock_resp.json = AsyncMock(return_value=mock_maps_json)
        mock_get.return_value = mock_resp

        results = await service.search_maps("consumer court near Bengaluru")

        assert len(results) == 1
        res = results[0]
        assert res.title == "District Consumer Forum"
        assert res.address == "MG Road, Bengaluru"
        assert res.phone == "+91 80 1234 5678"
        assert res.rating == 4.5
        assert res.coordinates == {"latitude": 12.9716, "longitude": 77.5946}


@pytest.mark.asyncio
async def test_serpapi_caching():
    service = SerpApiService(api_key="mock_key")

    mock_response_json = {
        "organic_results": [{"title": "Cached Result Test", "link": "https://test.com", "snippet": "Snippet"}]
    }

    with patch("httpx.AsyncClient.get") as mock_get:
        mock_resp = AsyncMock()
        mock_resp.raise_for_status = AsyncMock()
        mock_resp.json = AsyncMock(return_value=mock_response_json)
        mock_get.return_value = mock_resp

        # First Call — hits API
        res1 = await service.search_web("identical query")
        assert len(res1) == 1
        assert mock_get.call_count == 1

        # Second Call — hits cache (mock_get call_count remains 1)
        res2 = await service.search_web("identical query")
        assert len(res2) == 1
        assert res2[0].title == "Cached Result Test"
        assert mock_get.call_count == 1


@pytest.mark.asyncio
async def test_serpapi_retry_on_failure():
    service = SerpApiService(api_key="mock_key", max_retries=2)

    with patch("httpx.AsyncClient.get") as mock_get:
        mock_get.side_effect = Exception("HTTP 500 Internal Server Error")

        results = await service.search_web("failing query")
        assert results == []
        assert mock_get.call_count == 2
