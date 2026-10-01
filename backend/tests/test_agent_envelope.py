"""
Tests for the agent execution envelope (``backend.models.agent_envelope``).

The envelope exists to answer three questions consistently: what ran, whether
it actually worked, and how long it took. The distinction the tests care about
most is **attempted vs completed** — a safety product must never tell a woman
an action was taken when it only tried.

All offline.
"""

from __future__ import annotations

import asyncio

import pytest

from backend.models.agent_envelope import AgentError, AgentExecution, AgentStatus
from backend.trace import trace_context


# ---------------------------------------------------------------------------
# Status semantics
# ---------------------------------------------------------------------------

def test_started_is_proposed_not_completed():
    execution = AgentExecution.started("search_web")
    assert execution.status is AgentStatus.PROPOSED
    assert not execution.ok
    assert not execution.did_complete


def test_completed_is_both_ok_and_done():
    execution = AgentExecution.started("search_web").succeed({"results": 3})
    assert execution.status is AgentStatus.COMPLETED
    assert execution.ok
    assert execution.did_complete


def test_partial_is_usable_but_not_a_completed_action():
    """Some evidence is better than none — but do not claim the job is done."""
    execution = AgentExecution.started("research").succeed({"results": 1}, partial=True)
    assert execution.status is AgentStatus.PARTIAL
    assert execution.ok, "a partial result is still usable"
    assert not execution.did_complete, "partial must not read as completed"


def test_attempted_is_neither_ok_nor_done():
    execution = AgentExecution.started("adapt_safety_plan").fail(
        "db_write_failed", "write rejected"
    )
    assert execution.status is AgentStatus.ATTEMPTED
    assert not execution.ok
    assert not execution.did_complete


def test_unavailable_is_distinct_from_attempted():
    """'No API key' and 'the call failed' need different user messages."""
    execution = AgentExecution.started("search_web").fail(
        "not_configured", "no SERPAPI_API_KEY", unavailable=True
    )
    assert execution.status is AgentStatus.UNAVAILABLE
    assert not execution.ok


def test_skipped_records_why():
    execution = AgentExecution.started("search_web").skip("no search needed")
    assert execution.status is AgentStatus.SKIPPED
    assert execution.metadata["skip_reason"] == "no search needed"
    assert not execution.did_complete


# ---------------------------------------------------------------------------
# run(): timing, trace, isolation
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_run_records_success_and_duration():
    async def work():
        await asyncio.sleep(0.01)
        return {"value": 42}

    execution = await AgentExecution.run("demo", work)

    assert execution.did_complete
    assert execution.result == {"value": 42}
    assert execution.duration_ms > 0
    assert execution.error is None


@pytest.mark.asyncio
async def test_run_captures_the_trace_id():
    async def work():
        return "done"

    with trace_context("envelope-trace-1"):
        execution = await AgentExecution.run("demo", work)

    assert execution.trace_id == "envelope-trace-1"


@pytest.mark.asyncio
async def test_run_does_not_reraise_so_one_tool_cannot_kill_the_turn():
    async def explode():
        raise RuntimeError("provider is down")

    execution = await AgentExecution.run("flaky_tool", explode)

    assert execution.status is AgentStatus.ATTEMPTED
    assert execution.error is not None
    assert execution.error.reason == "RuntimeError"
    assert "provider is down" in execution.error.message
    assert not execution.did_complete


@pytest.mark.asyncio
async def test_run_records_duration_even_when_it_fails():
    async def explode():
        await asyncio.sleep(0.01)
        raise ValueError("nope")

    execution = await AgentExecution.run("flaky_tool", explode)
    assert execution.duration_ms > 0


@pytest.mark.asyncio
async def test_classify_maps_an_exception_to_a_structured_error():
    """Existing failure vocabularies pass through rather than being re-encoded."""

    def classify(exc: Exception):
        if "429" in str(exc):
            return AgentError(
                reason="rate_limited",
                message="provider quota exhausted",
                user_message="Please try again in a few minutes.",
                retryable=True,
            )
        return None

    async def explode():
        raise RuntimeError("HTTP 429 quota exceeded")

    execution = await AgentExecution.run("llm_call", explode, classify=classify)

    assert execution.error.reason == "rate_limited"
    assert execution.error.retryable is True
    assert execution.error.user_message


@pytest.mark.asyncio
async def test_unclassified_exception_falls_back_to_generic_error():
    def classify(exc: Exception):
        return None

    async def explode():
        raise KeyError("missing")

    execution = await AgentExecution.run("x", explode, classify=classify)
    assert execution.error.reason == "KeyError"
    assert execution.error.retryable is False


@pytest.mark.asyncio
async def test_long_error_messages_are_truncated():
    async def explode():
        raise RuntimeError("x" * 5000)

    execution = await AgentExecution.run("x", explode)
    assert len(execution.error.message) <= 500


@pytest.mark.asyncio
async def test_metadata_is_carried_through():
    async def work():
        return None

    execution = await AgentExecution.run("demo", work, tool="search_web", mode="legal")
    assert execution.metadata["tool"] == "search_web"
    assert execution.metadata["mode"] == "legal"


@pytest.mark.asyncio
async def test_concurrent_executions_keep_their_own_trace_ids():
    async def work():
        await asyncio.sleep(0)
        return "ok"

    async def one(trace_id: str):
        with trace_context(trace_id):
            return await AgentExecution.run("demo", work)

    executions = await asyncio.gather(*(one(f"trace-id-{i:04d}") for i in range(8)))
    assert sorted(e.trace_id for e in executions) == [f"trace-id-{i:04d}" for i in range(8)]


# ---------------------------------------------------------------------------
# Privacy
# ---------------------------------------------------------------------------

def test_envelope_does_not_require_user_content():
    """Nothing in the envelope's required shape invites a user message in."""
    execution = AgentExecution.started("demo")
    dumped = execution.model_dump()
    assert set(dumped) == {
        "agent",
        "status",
        "trace_id",
        "result",
        "error",
        "duration_ms",
        "metadata",
    }
    assert dumped["metadata"] == {}
