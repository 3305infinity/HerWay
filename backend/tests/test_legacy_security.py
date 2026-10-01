"""
Tests for the Phase 2 legacy-endpoint security policy.

The policy itself is documented at the top of ``backend/routes/legacy.py``.
These tests pin it down so a later change cannot quietly open an endpoint back
up, or quietly close a deliberately public one.

All offline. No Gemini, SerpApi, MongoDB or Twitter call is made: the endpoints
either reject the request before reaching a provider, or the provider is absent
and the handler degrades — which is exactly what these tests assert.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from backend.rate_limit import (
    LLM_BUDGET,
    READ_BUDGET,
    SUBMISSION_BUDGET,
    Budget,
    SlidingWindowLimiter,
    reset_limiter,
)


@pytest.fixture(autouse=True)
def _clean_limiter():
    """Each test starts with an empty budget."""
    reset_limiter()
    yield
    reset_limiter()


@pytest.fixture
def client():
    from backend.main import app

    return TestClient(app)


# ---------------------------------------------------------------------------
# The limiter itself
# ---------------------------------------------------------------------------

def test_limiter_allows_up_to_the_limit():
    limiter = SlidingWindowLimiter()
    budget = Budget(limit=3, window_seconds=60, name="t")
    assert limiter.check("k", budget) is None
    assert limiter.check("k", budget) is None
    assert limiter.check("k", budget) is None


def test_limiter_blocks_past_the_limit_and_reports_retry_after():
    limiter = SlidingWindowLimiter()
    budget = Budget(limit=2, window_seconds=60, name="t")
    limiter.check("k", budget)
    limiter.check("k", budget)
    retry_after = limiter.check("k", budget)
    assert isinstance(retry_after, int) and retry_after > 0


def test_limiter_keys_are_independent():
    """One caller exhausting their budget must not affect anyone else."""
    limiter = SlidingWindowLimiter()
    budget = Budget(limit=1, window_seconds=60, name="t")
    assert limiter.check("caller-a", budget) is None
    assert limiter.check("caller-b", budget) is None
    assert limiter.check("caller-a", budget) is not None


def test_budgets_are_ordered_sensibly():
    """Reads should be cheapest to make, paid model calls dearest."""
    assert READ_BUDGET.limit > SUBMISSION_BUDGET.limit
    assert READ_BUDGET.limit > LLM_BUDGET.limit


# ---------------------------------------------------------------------------
# Deliberately public endpoints must stay public
# ---------------------------------------------------------------------------

def test_community_feed_is_readable_without_an_account(client):
    """Anonymity is the product decision here, not an oversight."""
    response = client.get("/get-admin-posts")
    assert response.status_code == 200


def test_community_post_can_be_submitted_anonymously(client):
    response = client.post(
        "/save-extracted-data",
        json={"Location": "Pune", "Nature of domestic violence": "Verbal abuse"},
    )
    assert response.status_code == 200, (
        "anonymous submission must keep working — the create-post flow depends on it"
    )


def test_public_read_does_not_expose_contact_fields(client):
    """A public feed must never carry a survivor's contact details."""
    posts = client.get("/get-admin-posts").json()
    items = posts if isinstance(posts, list) else posts.get("posts", [])
    for post in items:
        for key in post:
            assert not any(
                marker in key.lower() for marker in ("contact", "email", "phone", "mobile")
            ), f"public post exposed field {key!r}"
        assert "user_id" not in post, "internal identifier leaked to a public feed"


# ---------------------------------------------------------------------------
# The one endpoint that now requires authentication
# ---------------------------------------------------------------------------

def test_twitter_publish_requires_authentication(client):
    """An open endpoint that posts in public is not defensible here."""
    response = client.post(
        "/send-message", params={"image_url": "https://example.com/a.png", "caption": "hi"}
    )
    assert response.status_code == 401, (
        f"expected 401 for unauthenticated Twitter publish, got {response.status_code}"
    )


def test_administrative_endpoints_still_require_authentication(client):
    for method, path in [
        ("post", "/close-issue/660000000000000000000001"),
        ("post", "/upload_embeddings/"),
    ]:
        response = getattr(client, method)(path)
        assert response.status_code == 401, f"{path} should require authentication"


# ---------------------------------------------------------------------------
# Input validation on paid endpoints — reject before spending a model call
# ---------------------------------------------------------------------------

@pytest.mark.parametrize(
    "path,payload",
    [
        ("/text-decomposition", {}),
        ("/text-decomposition", {"text": ""}),
        ("/text-decomposition", {"text": "   "}),
    ],
)
def test_decomposition_rejects_empty_input(client, path, payload):
    assert client.post(path, json=payload).status_code == 422


def test_decomposition_rejects_oversized_input(client):
    from backend.routes.legacy import MAX_TEXT_INPUT_CHARS

    response = client.post(
        "/text-decomposition", json={"text": "x" * (MAX_TEXT_INPUT_CHARS + 1)}
    )
    assert response.status_code == 422


def test_poem_rejects_empty_and_oversized_input(client):
    from backend.routes.legacy import MAX_TEXT_INPUT_CHARS

    assert client.get("/poem-generation", params={"text": "  "}).status_code == 422
    assert (
        client.get(
            "/poem-generation", params={"text": "x" * (MAX_TEXT_INPUT_CHARS + 1)}
        ).status_code
        == 422
    )


def test_find_match_rejects_unknown_collection(client):
    """The collection used to be taken verbatim, exposing `cases`."""
    response = client.get("/find-match", params={"info": "test", "collection": "cases"})
    assert response.status_code == 400


def test_find_match_rejects_empty_info(client):
    response = client.get("/find-match", params={"info": "   ", "collection": "admin"})
    assert response.status_code == 422


# ---------------------------------------------------------------------------
# Rate limiting actually fires on a paid endpoint
# ---------------------------------------------------------------------------

def test_llm_endpoint_is_rate_limited(client):
    """Past the budget the caller gets 429 with Retry-After, not a model call."""
    saw_429 = False
    for _ in range(LLM_BUDGET.limit + 5):
        response = client.get("/poem-generation", params={"text": "hello there"})
        if response.status_code == 429:
            saw_429 = True
            assert "Retry-After" in response.headers
            # The message must still point at real help.
            assert "181" in response.json()["detail"]
            break
    assert saw_429, (
        f"no 429 within {LLM_BUDGET.limit + 5} requests — the LLM budget is not enforced"
    )


def test_rate_limit_does_not_apply_to_emergency_resources(client):
    """A limiter must never be why someone cannot reach a helpline."""
    for _ in range(READ_BUDGET.limit + 20):
        response = client.get("/api/v2/resources/national")
        assert response.status_code == 200, (
            "national helplines must never be rate limited"
        )


def test_health_is_never_rate_limited(client):
    for _ in range(READ_BUDGET.limit + 10):
        assert client.get("/health").status_code == 200


# ---------------------------------------------------------------------------
# Error bodies must not leak internals
# ---------------------------------------------------------------------------

def test_errors_do_not_echo_provider_detail(client):
    """Handlers used to interpolate the raw exception into the response."""
    response = client.post("/text-decomposition", json={"text": "a real sentence here"})
    if response.status_code >= 500:
        body = response.text.lower()
        for leak in ("traceback", "api_key", "google.generativeai", "file \""):
            assert leak not in body, f"error body leaked {leak!r}"
