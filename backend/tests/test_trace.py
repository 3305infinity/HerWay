"""
Tests for request-scoped trace IDs (``backend.trace``).

All offline — no external service is involved. These cover the properties that
make a trace ID safe to use: isolation between concurrent requests, cleanup
after exceptions, and refusal to echo a hostile client-supplied value into the
logs.
"""

from __future__ import annotations

import asyncio
import logging

import pytest
from fastapi.testclient import TestClient

from backend.trace import (
    TRACE_HEADER,
    TraceIdFilter,
    coerce_trace_id,
    get_trace_id,
    is_valid_trace_id,
    log_fields,
    new_trace_id,
    reset_trace_id,
    set_trace_id,
    trace_context,
)


# ---------------------------------------------------------------------------
# Generation and validation
# ---------------------------------------------------------------------------

def test_new_trace_id_is_unique_and_well_formed():
    ids = {new_trace_id() for _ in range(500)}
    assert len(ids) == 500, "trace IDs must not collide"
    assert all(is_valid_trace_id(i) for i in ids)


@pytest.mark.parametrize(
    "value",
    [
        "abcd1234",                      # minimum length
        "a" * 64,                        # maximum length
        "trace-id_with-separators-01",
        new_trace_id(),
    ],
)
def test_valid_trace_ids_accepted(value):
    assert is_valid_trace_id(value)


@pytest.mark.parametrize(
    "value",
    [
        None,
        "",
        "short",                          # below 8 chars
        "a" * 65,                         # above 64 chars
        "has spaces here",
        "newline\ninjected",              # log injection
        "carriage\rreturn",
        "\x1b[31mansi-escape",            # terminal escape sequence
        "semi;colon",
        "sql'quote",
        "../../etc/passwd",
        "unicode-ਪੰਜਾਬੀ-id",
        12345678,                         # not a string
        ["list"],
        {"dict": 1},
    ],
)
def test_invalid_trace_ids_rejected(value):
    assert not is_valid_trace_id(value)


def test_coerce_replaces_invalid_with_fresh_id():
    """A hostile header must never reach the logs, but must not fail the request."""
    coerced = coerce_trace_id("newline\ninjected")
    assert coerced != "newline\ninjected"
    assert is_valid_trace_id(coerced)


def test_coerce_preserves_valid_id():
    """A well-formed inbound ID is kept, so callers can correlate across services."""
    supplied = "caller-supplied-0001"
    assert coerce_trace_id(supplied) == supplied


# ---------------------------------------------------------------------------
# Context management
# ---------------------------------------------------------------------------

def test_no_trace_id_outside_a_request():
    assert get_trace_id() is None


def test_trace_context_binds_and_restores():
    assert get_trace_id() is None
    with trace_context("outer-trace-id") as tid:
        assert tid == "outer-trace-id"
        assert get_trace_id() == "outer-trace-id"
    assert get_trace_id() is None, "context must be restored on exit"


def test_trace_context_restores_after_exception():
    """An exception must not leave a stale ID bound to a reused worker task."""
    with pytest.raises(ValueError):
        with trace_context("will-explode-01"):
            assert get_trace_id() == "will-explode-01"
            raise ValueError("boom")
    assert get_trace_id() is None


def test_nested_contexts_restore_the_outer_value():
    with trace_context("outer-trace-id"):
        with trace_context("inner-trace-id"):
            assert get_trace_id() == "inner-trace-id"
        assert get_trace_id() == "outer-trace-id"
    assert get_trace_id() is None


def test_set_and_reset_tokens():
    token = set_trace_id("manual-token-001")
    assert get_trace_id() == "manual-token-001"
    reset_trace_id(token)
    assert get_trace_id() is None


# ---------------------------------------------------------------------------
# Concurrency isolation — the property that matters most
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_concurrent_tasks_do_not_leak_trace_ids():
    """Each asyncio task gets a copy of the context, so IDs cannot cross over."""
    observed: dict[str, list[str | None]] = {}

    async def worker(name: str, trace_id: str) -> None:
        with trace_context(trace_id):
            seen = []
            for _ in range(20):
                seen.append(get_trace_id())
                await asyncio.sleep(0)  # force interleaving
            observed[name] = seen

    await asyncio.gather(
        *(worker(f"req{i}", f"trace-id-{i:04d}") for i in range(12))
    )

    for i in range(12):
        seen = observed[f"req{i}"]
        assert set(seen) == {f"trace-id-{i:04d}"}, (
            f"req{i} observed foreign trace IDs: {set(seen)}"
        )


@pytest.mark.asyncio
async def test_gather_fanout_inherits_the_parent_trace_id():
    """Research fans out with asyncio.gather; children must share the ID."""
    async def child() -> str | None:
        await asyncio.sleep(0)
        return get_trace_id()

    with trace_context("parent-trace-01"):
        results = await asyncio.gather(*(child() for _ in range(8)))

    assert set(results) == {"parent-trace-01"}


@pytest.mark.asyncio
async def test_child_task_cannot_overwrite_parent_trace_id():
    async def child_sets_its_own() -> None:
        with trace_context("child-trace-0001"):
            await asyncio.sleep(0)

    with trace_context("parent-trace-0001"):
        await asyncio.gather(child_sets_its_own(), child_sets_its_own())
        assert get_trace_id() == "parent-trace-0001"


# ---------------------------------------------------------------------------
# Logging integration
# ---------------------------------------------------------------------------

def test_log_filter_attaches_trace_id():
    record = logging.LogRecord("t", logging.INFO, __file__, 1, "msg", None, None)
    with trace_context("log-trace-000001"):
        assert TraceIdFilter().filter(record) is True
        assert record.trace_id == "log-trace-000001"


def test_log_filter_outside_request_uses_placeholder():
    record = logging.LogRecord("t", logging.INFO, __file__, 1, "msg", None, None)
    TraceIdFilter().filter(record)
    assert record.trace_id == "-"


def test_custom_formatter_tolerates_missing_trace_attribute():
    """Third-party records have no trace_id; formatting must not raise."""
    from backend.logger import CustomFormatter

    record = logging.LogRecord("ext", logging.INFO, __file__, 1, "hello", None, None)
    assert "hello" in CustomFormatter().format(record)


def test_log_fields_includes_trace_id():
    with trace_context("fields-trace-01"):
        payload = log_fields(tool="search_web", outcome="ok", duration_ms=12)
    assert payload == {
        "trace_id": "fields-trace-01",
        "tool": "search_web",
        "outcome": "ok",
        "duration_ms": 12,
    }


# ---------------------------------------------------------------------------
# HTTP middleware integration
# ---------------------------------------------------------------------------

@pytest.fixture
def client():
    from backend.main import app

    return TestClient(app)


def test_response_carries_a_trace_header(client):
    response = client.get("/health")
    assert response.status_code == 200
    assert is_valid_trace_id(response.headers.get(TRACE_HEADER))


def test_valid_inbound_trace_id_is_echoed(client):
    response = client.get("/health", headers={TRACE_HEADER: "client-supplied-01"})
    assert response.headers[TRACE_HEADER] == "client-supplied-01"


def test_hostile_inbound_trace_id_is_replaced(client):
    """A log-injection attempt must not be reflected back or recorded."""
    response = client.get("/health", headers={TRACE_HEADER: "bad\nid INJECTED"})
    returned = response.headers[TRACE_HEADER]
    assert returned != "bad\nid INJECTED"
    assert "\n" not in returned
    assert is_valid_trace_id(returned)


def test_each_request_gets_a_distinct_trace_id(client):
    ids = {client.get("/health").headers[TRACE_HEADER] for _ in range(10)}
    assert len(ids) == 10


def test_trace_id_is_not_an_authorization_mechanism(client):
    """Supplying someone else's trace ID must not grant access to anything."""
    create = client.post(
        "/api/v2/cases",
        json={"situation_text": "Audit probe situation text for trace testing."},
    )
    assert create.status_code == 200
    owner_trace = create.headers[TRACE_HEADER]
    case_id = create.json()["id"]

    # A different client (no shared session cookie) presenting the owner's trace ID.
    from backend.main import app

    other = TestClient(app)
    response = other.get(
        f"/api/v2/cases/{case_id}", headers={TRACE_HEADER: owner_trace}
    )
    assert response.status_code == 403, "trace ID must never confer access"
