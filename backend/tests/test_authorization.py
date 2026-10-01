"""
Authorization tests.

The property under test: **one user's case is never reachable by another.**

Before server-side identity existed, every case endpoint accepted an optional
``user_id`` query parameter supplied by the browser, so omitting it granted
full access to any case. These tests pin that door shut.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from backend.main import app


@pytest.fixture
def client():
    return TestClient(app)


def _new_session() -> TestClient:
    """A client with its own cookie jar — i.e. a different anonymous user."""
    return TestClient(app)


def _create_case(c: TestClient, text: str = "I am being threatened by my partner at home.") -> str:
    resp = c.post(
        "/api/v2/cases",
        json={"situation_text": text, "category": "domestic_violence"},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    case_id = body.get("id") or body.get("_id")
    assert case_id
    return case_id


# ---------------------------------------------------------------------------
# Anonymous sessions are isolated from each other
# ---------------------------------------------------------------------------

def test_anonymous_sessions_get_distinct_identities():
    """Two browsers must not share a single 'anonymous' namespace."""
    a, b = _new_session(), _new_session()
    _create_case(a)
    _create_case(b)

    a_cases = a.get("/api/v2/cases").json()
    b_cases = b.get("/api/v2/cases").json()

    assert len(a_cases) == 1
    assert len(b_cases) == 1
    assert a_cases[0]["id"] != b_cases[0]["id"]
    assert a_cases[0]["user_id"] != b_cases[0]["user_id"]


def test_session_cookie_is_httponly():
    """The session id must not be reachable from JavaScript."""
    c = _new_session()
    resp = c.post(
        "/api/v2/cases",
        json={"situation_text": "A long enough situation description for validation."},
    )
    assert resp.status_code == 200
    set_cookie = resp.headers.get("set-cookie", "")
    assert "herway_sid" in set_cookie
    assert "HttpOnly" in set_cookie


# ---------------------------------------------------------------------------
# Cross-user access is denied on every endpoint
# ---------------------------------------------------------------------------

@pytest.mark.parametrize(
    "method,path_suffix,payload",
    [
        ("get", "", None),
        ("patch", "", {"status": "archived"}),
        ("delete", "", None),
        ("get", "/safety-plan", None),
        ("patch", "/actions/ACTION_NOW_01", {"status": "completed"}),
        ("post", "/safety-plan/adapt", {"updated_situation_text": "He found out."}),
        ("post", "/safety-plan/research-more", {"query": "shelter", "location": "Pune"}),
    ],
)
def test_other_user_cannot_touch_a_case(method, path_suffix, payload):
    owner = _new_session()
    attacker = _new_session()
    case_id = _create_case(owner)

    url = f"/api/v2/cases/{case_id}{path_suffix}"
    resp = getattr(attacker, method)(url, json=payload) if payload else getattr(attacker, method)(url)

    assert resp.status_code == 403, (
        f"{method.upper()} {url} returned {resp.status_code}, expected 403. "
        "Another user's case must never be reachable."
    )


def test_other_user_cannot_run_research_on_a_case():
    owner = _new_session()
    attacker = _new_session()
    case_id = _create_case(owner)

    resp = attacker.post(f"/api/v2/research/{case_id}/run")
    assert resp.status_code == 403


def test_other_user_cannot_read_research_outputs():
    owner = _new_session()
    attacker = _new_session()
    case_id = _create_case(owner)

    assert attacker.get(f"/api/v2/research/{case_id}/report").status_code == 403
    assert attacker.get(f"/api/v2/research/{case_id}/plan").status_code == 403


def test_other_user_cannot_chat_against_a_case():
    """Chat loads case context, so an unowned case id must be rejected."""
    owner = _new_session()
    attacker = _new_session()
    case_id = _create_case(owner)

    resp = attacker.post(
        "/api/v2/chat",
        json={"case_id": case_id, "message": "What is in this case?"},
    )
    assert resp.status_code == 403


def test_owner_can_access_their_own_case():
    owner = _new_session()
    case_id = _create_case(owner)

    resp = owner.get(f"/api/v2/cases/{case_id}")
    assert resp.status_code == 200
    assert (resp.json().get("id") or resp.json().get("_id")) == case_id


# ---------------------------------------------------------------------------
# The client cannot assert its own identity
# ---------------------------------------------------------------------------

def test_user_id_in_body_is_ignored_on_create():
    """A caller must not be able to create a case owned by someone else."""
    c = _new_session()
    resp = c.post(
        "/api/v2/cases",
        json={
            "situation_text": "A long enough situation description for validation.",
            "user_id": "user_someone_else",
        },
    )
    assert resp.status_code == 200
    assert resp.json()["user_id"] != "user_someone_else"


def test_user_id_query_param_does_not_grant_access():
    """The old ?user_id= backdoor must no longer work."""
    owner = _new_session()
    attacker = _new_session()
    case_id = _create_case(owner)

    owner_id = owner.get(f"/api/v2/cases/{case_id}").json()["user_id"]
    resp = attacker.get(f"/api/v2/cases/{case_id}?user_id={owner_id}")
    assert resp.status_code == 403


def test_listing_cannot_be_redirected_to_another_user():
    owner = _new_session()
    attacker = _new_session()
    _create_case(owner)

    owner_id = owner.get("/api/v2/cases").json()[0]["user_id"]
    listed = attacker.get(f"/api/v2/cases?user_id={owner_id}").json()
    assert listed == []


def test_invalid_bearer_token_is_rejected_not_downgraded():
    """A bad token must fail, not quietly fall back to an anonymous session."""
    c = _new_session()
    resp = c.get(
        "/api/v2/cases",
        headers={"Authorization": "Bearer not-a-real-token"},
    )
    assert resp.status_code == 401


# ---------------------------------------------------------------------------
# Input validation
# ---------------------------------------------------------------------------

def test_malformed_case_id_is_rejected_cleanly():
    c = _new_session()
    resp = c.get("/api/v2/cases/not-an-object-id")
    assert resp.status_code == 400
    assert "detail" in resp.json()


def test_unknown_case_id_is_a_clean_404():
    c = _new_session()
    resp = c.get("/api/v2/cases/660000000000000000009999")
    assert resp.status_code == 404
