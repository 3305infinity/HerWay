"""
Resource feedback tests.

The behavioural tests matter, but the ones that matter *most* are the privacy
assertions: that no stored record can be traced to a person, and that nothing
identifying reaches the logs. Those are the properties the whole design exists
to protect, so they are pinned here rather than left to review.

All offline — storage runs on the in-memory fallback.
"""

from __future__ import annotations

import logging

import pytest
from fastapi.testclient import TestClient

from backend.rate_limit import reset_limiter
from backend.services.resource_feedback import (
    OUTCOMES,
    ResourceFeedbackStore,
    resource_key,
)


@pytest.fixture(autouse=True)
def _clean_limiter():
    reset_limiter()
    yield
    reset_limiter()


@pytest.fixture
def client():
    from backend.main import app

    return TestClient(app)


# ---------------------------------------------------------------------------
# Keys
# ---------------------------------------------------------------------------

def test_phone_formatting_does_not_change_the_key():
    """The same number written three ways is one resource."""
    a = resource_key(phone="+91 98765 43210")
    b = resource_key(phone="09876543210")
    c = resource_key(phone="+91-98765-43210")
    assert a == b == c


def test_different_resources_get_different_keys():
    assert resource_key(phone="+919876543210") != resource_key(phone="+919876543211")
    assert resource_key(url="https://a.gov.in") != resource_key(url="https://b.gov.in")


def test_url_trailing_slash_and_case_are_normalised():
    assert resource_key(url="https://WCD.NIC.IN/osc/") == resource_key(url="https://wcd.nic.in/osc")


def test_key_does_not_contain_the_resource_details():
    """A stored key must not read as a directory of shelters and numbers."""
    key = resource_key(phone="+919876543210", name="Sakhi One Stop Centre Nagpur")
    assert "9876543210" not in key
    assert "sakhi" not in key.lower()
    assert "nagpur" not in key.lower()


def test_key_is_none_without_any_identifier():
    assert resource_key() is None
    assert resource_key(phone="", url="", name="") is None


def test_phone_is_preferred_over_name():
    """Names drift; numbers do not. Same number, different name, one key."""
    assert resource_key(phone="+919876543210", name="Old Name") == resource_key(
        phone="+919876543210", name="New Name"
    )


# ---------------------------------------------------------------------------
# Counting
# ---------------------------------------------------------------------------

def test_first_report_creates_a_counter():
    store = ResourceFeedbackStore()
    key = resource_key(phone="+911111111111")
    summary = store.record(key, "worked")

    assert summary["reports"] == 1
    assert summary["counts"]["worked"] == 1
    assert summary["counts"]["no_answer"] == 0


def test_reports_accumulate():
    store = ResourceFeedbackStore()
    key = resource_key(phone="+912222222222")
    for _ in range(3):
        store.record(key, "no_answer")
    store.record(key, "worked")

    summary = store.summary(key)
    assert summary["reports"] == 4
    assert summary["counts"]["no_answer"] == 3
    assert summary["counts"]["worked"] == 1


def test_unknown_resource_reads_as_zero_not_an_error():
    summary = ResourceFeedbackStore().summary(resource_key(phone="+919999999999"))
    assert summary["reports"] == 0
    assert all(v == 0 for v in summary["counts"].values())


def test_invalid_outcome_is_rejected():
    store = ResourceFeedbackStore()
    with pytest.raises(ValueError):
        store.record(resource_key(phone="+913333333333"), "five_stars")


def test_outcomes_are_about_reachability_not_quality():
    """A rating beside a shelter would read as a safety verdict."""
    joined = " ".join(OUTCOMES).lower()
    for rating_word in ("good", "bad", "rating", "star", "safe", "recommend"):
        assert rating_word not in joined


# ---------------------------------------------------------------------------
# Privacy — the properties the design exists for
# ---------------------------------------------------------------------------

def test_stored_record_has_no_owner_field():
    """Nothing in the document can tie a report to a person."""
    from backend.db import get_database

    store = ResourceFeedbackStore()
    key = resource_key(phone="+914444444444")
    store.record(key, "worked")

    doc = get_database()["resource_feedback"].find_one({"_id": key})
    assert doc is not None
    for forbidden in ("user_id", "owner_id", "session", "herway_sid", "trace_id", "case_id", "ip"):
        assert forbidden not in doc, f"feedback record leaked {forbidden}"


def test_stored_record_has_no_fine_grained_timestamp():
    """Day granularity only — a precise time could place someone."""
    from backend.db import get_database

    store = ResourceFeedbackStore()
    key = resource_key(phone="+915555555555")
    store.record(key, "worked")

    doc = get_database()["resource_feedback"].find_one({"_id": key})
    assert len(doc["last_seen"]) == len("2026-01-01"), "timestamp is finer than a day"
    assert ":" not in doc["last_seen"]


def test_stored_record_does_not_contain_the_raw_phone_or_name():
    from backend.db import get_database

    store = ResourceFeedbackStore()
    key = resource_key(phone="+916666666666", name="Sakhi Centre Pune")
    store.record(key, "worked")

    blob = str(get_database()["resource_feedback"].find_one({"_id": key})).lower()
    assert "6666666666" not in blob
    assert "sakhi" not in blob
    assert "pune" not in blob


def test_logging_does_not_record_which_resource(caplog):
    """A log line pairing a resource with a request is the correlation to avoid."""
    store = ResourceFeedbackStore()
    key = resource_key(phone="+917777777777", name="Women Shelter Delhi")

    with caplog.at_level(logging.INFO):
        store.record(key, "no_answer")

    text = caplog.text.lower()
    assert "no_answer" in text, "the outcome should be logged"
    assert key not in caplog.text, "the resource key must not be logged"
    assert "7777777777" not in text
    assert "shelter" not in text


def test_response_labels_counts_as_community_reported():
    """Counts must never read as verification by HerWay."""
    summary = ResourceFeedbackStore().summary(resource_key(phone="+918888888888"))
    assert summary["is_community_reported"] is True
    assert "not re-checked" in summary["note"].lower()


# ---------------------------------------------------------------------------
# API
# ---------------------------------------------------------------------------

def test_feedback_options_lists_outcomes(client):
    body = client.get("/api/v2/resources/feedback-options").json()
    values = {o["value"] for o in body["outcomes"]}
    assert values == set(OUTCOMES)
    assert "anonymous" in body["note"].lower()


def test_submit_and_read_back(client):
    payload = {"outcome": "worked", "phone": "+91 90000 00001"}
    posted = client.post("/api/v2/resources/feedback", json=payload)
    assert posted.status_code == 200
    assert posted.json()["counts"]["worked"] >= 1

    read = client.get("/api/v2/resources/feedback", params={"phone": "+919000000001"})
    assert read.json()["counts"]["worked"] >= 1


def test_submitting_requires_no_account(client):
    """Anonymity is the point — a login wall would defeat it."""
    from backend.main import app

    anonymous = TestClient(app)
    response = anonymous.post(
        "/api/v2/resources/feedback", json={"outcome": "no_answer", "phone": "+919000000002"}
    )
    assert response.status_code == 200


def test_unknown_outcome_rejected_by_api(client):
    response = client.post(
        "/api/v2/resources/feedback", json={"outcome": "five_stars", "phone": "+919000000003"}
    )
    assert response.status_code == 422


def test_missing_identifier_rejected(client):
    response = client.post("/api/v2/resources/feedback", json={"outcome": "worked"})
    assert response.status_code == 422


def test_feedback_is_rate_limited(client):
    """With no identity to limit by, the route is the only control available."""
    from backend.rate_limit import SUBMISSION_BUDGET

    saw_429 = False
    for i in range(SUBMISSION_BUDGET.limit + 3):
        response = client.post(
            "/api/v2/resources/feedback",
            json={"outcome": "worked", "phone": f"+9190000{i:05d}"},
        )
        if response.status_code == 429:
            saw_429 = True
            break
    assert saw_429, "anonymous feedback must be rate limited"


def test_reading_feedback_is_not_rate_limited_into_uselessness(client):
    """Reading counts is cheap and happens once per rendered listing."""
    for _ in range(25):
        assert (
            client.get(
                "/api/v2/resources/feedback", params={"phone": "+919000000004"}
            ).status_code
            == 200
        )


# ---------------------------------------------------------------------------
# Indian phone normalisation
# ---------------------------------------------------------------------------
# Added after the first run caught `+91 98765 43210` and `09876543210` keying
# differently — which would have split one office's reports across two
# counters and quietly made the whole feature useless.

@pytest.mark.parametrize(
    "written",
    [
        "+91 98765 43210",
        "+919876543210",
        "0091 98765 43210",
        "09876543210",
        "098765-43210",
        "9876543210",
        "98765 43210",
        "(+91) 98765-43210",
    ],
)
def test_every_way_of_writing_one_number_gives_one_key(written):
    assert resource_key(phone=written) == resource_key(phone="9876543210")


@pytest.mark.parametrize("short_code", ["112", "181", "1091", "1930", "1098", "14416"])
def test_short_codes_are_left_alone(short_code):
    """Already canonical, and not 10 digits — must not be rewritten."""
    from backend.services.resource_feedback import normalise_indian_phone

    assert normalise_indian_phone(short_code) == short_code


def test_short_codes_stay_distinct_from_each_other():
    keys = {resource_key(phone=c) for c in ("112", "181", "1091", "1930")}
    assert len(keys) == 4


def test_landline_with_std_code_is_handled():
    """020-12345678 (Pune) — 10 digits, already canonical."""
    assert resource_key(phone="020-12345678") == resource_key(phone="02012345678")


def test_international_numbers_are_not_mangled():
    """A resource listed with a non-Indian number must not collide."""
    uk = resource_key(phone="+44 20 7946 0958")
    india = resource_key(phone="+91 98765 43210")
    assert uk != india
