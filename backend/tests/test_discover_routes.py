"""
Discovery endpoint tests (Phase 3, Task 8).

**All mocked.** ``SerpApiService`` is patched at the point the routes construct
it, so no billable call is made. Live verification is reported separately.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from backend.models.research import SearchFailureReason, SearchOutcome, SearchResult
from backend.rate_limit import reset_limiter


@pytest.fixture(autouse=True)
def _clean_limiter():
    reset_limiter()
    yield
    reset_limiter()


@pytest.fixture
def client():
    from backend.main import app

    return TestClient(app)


def _patched_serpapi(results=None, *, success=True, failure=SearchFailureReason.NONE):
    """Patch the SerpApiService the discover routes instantiate."""
    service = MagicMock()
    service.search_detailed = AsyncMock(
        return_value=SearchOutcome(
            vertical="maps",
            query="q",
            success=success,
            failure_reason=failure,
            results=results if results is not None else [],
        )
    )
    return patch("backend.routes.discover.SerpApiService", return_value=service)


def _listing(title="City Hospital", **kw):
    base = dict(
        title=title,
        url="https://example.gov.in/h",
        snippet="A hospital",
        address="MG Road, Pune",
        phone="020-11111111",
        rating=4.2,
        reviews=88,
    )
    base.update(kw)
    return SearchResult(**base)


# ---------------------------------------------------------------------------
# Categories
# ---------------------------------------------------------------------------

def test_categories_are_listed(client):
    response = client.get("/api/v2/discover/categories")
    assert response.status_code == 200
    values = {c["value"] for c in response.json()["categories"]}
    for expected in ("hospital", "pharmacy", "one_stop_centre", "legal_aid"):
        assert expected in values


def test_categories_exclude_the_catch_all(client):
    values = {c["value"] for c in client.get("/api/v2/discover/categories").json()["categories"]}
    assert "other" not in values, "'other' is an internal fallback, not a user choice"


# ---------------------------------------------------------------------------
# Resource discovery
# ---------------------------------------------------------------------------

def test_discover_resources_returns_normalised_listings(client):
    with _patched_serpapi([_listing()]):
        response = client.post(
            "/api/v2/discover/resources",
            json={"category": "hospital", "location": "Pune"},
        )
    assert response.status_code == 200
    body = response.json()
    assert body["success"] is True
    assert body["resources"][0]["name"] == "City Hospital"
    assert body["resources"][0]["open_now_known"] is False
    assert "do not confirm" in body["disclaimer"].lower()


def test_unknown_category_is_rejected_with_422(client):
    response = client.post(
        "/api/v2/discover/resources",
        json={"category": "nightclub_safety_rating", "location": "Pune"},
    )
    assert response.status_code == 422
    assert "Valid values" in response.json()["detail"]


def test_location_is_required(client):
    response = client.post("/api/v2/discover/resources", json={"category": "hospital"})
    assert response.status_code == 422


def test_oversized_location_is_rejected_before_a_search(client):
    with _patched_serpapi([_listing()]) as patched:
        response = client.post(
            "/api/v2/discover/resources",
            json={"category": "hospital", "location": "x" * 500},
        )
    assert response.status_code == 422
    patched.assert_not_called()


def test_provider_failure_is_surfaced_as_failure_not_emptiness(client):
    with _patched_serpapi([], success=False, failure=SearchFailureReason.RATE_LIMITED):
        body = client.post(
            "/api/v2/discover/resources",
            json={"category": "hospital", "location": "Pune"},
        ).json()

    assert body["success"] is False
    assert body["found_nothing"] is False
    assert body["failure_reason"] == "rate_limited"


def test_genuine_empty_result_is_marked_found_nothing(client):
    with _patched_serpapi([]):
        body = client.post(
            "/api/v2/discover/resources",
            json={"category": "hospital", "location": "Pune"},
        ).json()

    assert body["success"] is True
    assert body["found_nothing"] is True


def test_missing_fields_are_null_not_fabricated(client):
    bare = SearchResult(title="Sparse Listing", snippet="")
    with _patched_serpapi([bare]):
        body = client.post(
            "/api/v2/discover/resources",
            json={"category": "clinic", "location": "Pune"},
        ).json()

    resource = body["resources"][0]
    assert resource["phone"] is None
    assert resource["address"] is None
    assert resource["rating"] is None


# ---------------------------------------------------------------------------
# Place research
# ---------------------------------------------------------------------------

def test_place_research_returns_a_profile(client):
    with _patched_serpapi([_listing(title="Ruby Hall Clinic", snippet="very clean")]):
        body = client.post(
            "/api/v2/discover/place",
            json={"place_name": "Ruby Hall Clinic", "location": "Pune"},
        ).json()

    assert body["success"] is True
    assert body["listing"]["name"] == "Ruby Hall Clinic"
    assert body["reviews"]["is_not_a_safety_assessment"] is True


def test_place_response_has_no_safety_verdict_field(client):
    with _patched_serpapi([_listing(rating=5.0, reviews=2000)]):
        body = client.post(
            "/api/v2/discover/place", json={"place_name": "Somewhere"}
        ).json()

    blob = str(body).lower()
    for forbidden in ("safety_score", "is_safe", "safety_rating", "safest"):
        assert forbidden not in blob


# ---------------------------------------------------------------------------
# Comparison
# ---------------------------------------------------------------------------

def test_compare_returns_table_and_underlying_resources(client):
    with _patched_serpapi([_listing("A"), _listing("B", rating=None, phone=None)]):
        body = client.post(
            "/api/v2/discover/compare",
            json={"category": "hospital", "location": "Pune", "priorities": []},
        ).json()

    assert body["comparison"]["has_overall_ranking"] is False
    assert len(body["comparison"]["option_names"]) == 2
    assert body["resources"]["resources"], "evidence must accompany the table"


def test_compare_labels_missing_values(client):
    with _patched_serpapi([_listing("A"), _listing("B", rating=None)]):
        body = client.post(
            "/api/v2/discover/compare",
            json={"category": "hospital", "location": "Pune"},
        ).json()

    cell = body["comparison"]["table"]["rating"]["B"]
    assert cell["available"] is False
    assert cell["value"] is None


def test_compare_echoes_user_priorities_without_scoring(client):
    with _patched_serpapi([_listing("A"), _listing("B")]):
        body = client.post(
            "/api/v2/discover/compare",
            json={"category": "hospital", "location": "Pune", "priorities": ["phone"]},
        ).json()

    assert body["comparison"]["fields_compared"][0] == "phone"
    assert body["comparison"]["has_overall_ranking"] is False


# ---------------------------------------------------------------------------
# Area reports
# ---------------------------------------------------------------------------

def test_area_reports_carry_their_limitations(client):
    article = SearchResult(
        title="Police said an inquiry is underway",
        url="https://news.example.com/1",
        source="Example News",
        published_at="2026-08-01",
        snippet="official statement",
    )
    with _patched_serpapi([article]):
        body = client.post("/api/v2/discover/area-reports", json={"area": "Pune"}).json()

    assert body["cannot_infer_crime_rate"] is True
    assert body["absence_of_results_is_not_safety"] is True
    assert body["articles"][0]["claim_type"] == "official_statement"
    assert body["articles"][0]["published_at"] == "2026-08-01"


# ---------------------------------------------------------------------------
# Abuse controls
# ---------------------------------------------------------------------------

def test_discovery_is_rate_limited(client):
    from backend.rate_limit import LLM_BUDGET

    saw_429 = False
    with _patched_serpapi([_listing()]):
        for _ in range(LLM_BUDGET.limit + 3):
            response = client.post(
                "/api/v2/discover/resources",
                json={"category": "hospital", "location": "Pune"},
            )
            if response.status_code == 429:
                saw_429 = True
                assert "Retry-After" in response.headers
                break
    assert saw_429, "paid discovery endpoints must be rate limited"


def test_categories_endpoint_costs_nothing_and_is_not_limited(client):
    """It performs no search, so it must not consume the paid budget."""
    for _ in range(40):
        assert client.get("/api/v2/discover/categories").status_code == 200


# ---------------------------------------------------------------------------
# Tracing
# ---------------------------------------------------------------------------

def test_responses_carry_a_trace_id_header(client):
    from backend.trace import TRACE_HEADER, is_valid_trace_id

    with _patched_serpapi([_listing()]):
        response = client.post(
            "/api/v2/discover/resources",
            json={"category": "hospital", "location": "Pune"},
        )
    assert is_valid_trace_id(response.headers.get(TRACE_HEADER))


def test_compare_response_includes_the_trace_id(client):
    with _patched_serpapi([_listing("A"), _listing("B")]):
        body = client.post(
            "/api/v2/discover/compare",
            json={"category": "hospital", "location": "Pune"},
        ).json()
    assert body["trace_id"]
