"""
Tests for LLMService error handling.

The behaviour that matters: when the model provider is unavailable, rate
limited, or misconfigured, HerWay must say so. It must never quietly fall
through to answering from memory, and it must not report an operational
problem as a generic crash — "try again in a few minutes" is actionable,
"something went wrong" is not.
"""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from pydantic import BaseModel

from backend.services.llm_service import (
    LLMService,
    LLMUnavailableError,
    _classify_api_error,
)


class _Schema(BaseModel):
    answer: str


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

def test_missing_api_key_is_reported_not_configured():
    service = LLMService(api_key="")
    assert service.is_configured is False


@pytest.mark.asyncio
async def test_generate_without_key_raises_unavailable():
    service = LLMService(api_key="")
    with pytest.raises(LLMUnavailableError) as exc_info:
        await service.generate(system_prompt="s", user_prompt="u")
    assert exc_info.value.reason == "not_configured"
    # The message must give the user somewhere to go.
    assert "112" in exc_info.value.user_message or "181" in exc_info.value.user_message


# ---------------------------------------------------------------------------
# Provider error classification
# ---------------------------------------------------------------------------

@pytest.mark.parametrize(
    "message,expected_reason",
    [
        ("429 You exceeded your current quota, please check your plan", "rate_limited"),
        ("RESOURCE_EXHAUSTED: quota exceeded", "rate_limited"),
        ("Rate limit reached for this model", "rate_limited"),
        ("404 models/gemini-1.5-flash is not found for API version v1beta", "model_unavailable"),
        ("403 PERMISSION_DENIED: API key not valid", "auth_failed"),
        ("503 The service is currently unavailable", "provider_outage"),
    ],
)
def test_provider_errors_are_classified(message, expected_reason):
    classified = _classify_api_error(RuntimeError(message))
    assert classified is not None, f"Should classify: {message}"
    assert classified.reason == expected_reason
    assert classified.user_message


def test_rate_limit_message_tells_the_user_to_wait():
    classified = _classify_api_error(RuntimeError("429 quota exceeded"))
    assert classified is not None
    text = classified.user_message.lower()
    assert "try again" in text
    # A woman who cannot get an answer now still needs a number she can call.
    assert "112" in classified.user_message or "181" in classified.user_message


def test_unrecognised_errors_are_not_misclassified():
    """A genuine bug must not be dressed up as a rate limit."""
    assert _classify_api_error(KeyError("some_field")) is None


@pytest.mark.asyncio
async def test_quota_error_surfaces_as_rate_limited():
    service = LLMService(api_key="test_key")

    def _boom(*args, **kwargs):
        raise RuntimeError("429 You exceeded your current quota")

    with patch("backend.services.llm_service.genai.GenerativeModel") as model_cls:
        model_cls.return_value.generate_content.side_effect = _boom
        with pytest.raises(LLMUnavailableError) as exc_info:
            await service.generate(system_prompt="s", user_prompt="u")

    assert exc_info.value.reason == "rate_limited"


@pytest.mark.asyncio
async def test_timeout_surfaces_as_unavailable_not_a_hang():
    """A slow provider must fail cleanly rather than holding the request open."""
    service = LLMService(api_key="test_key", timeout_seconds=0.05)

    def _slow(*args, **kwargs):
        import time

        time.sleep(2)
        return MagicMock(text="too late")

    with patch("backend.services.llm_service.genai.GenerativeModel") as model_cls:
        model_cls.return_value.generate_content.side_effect = _slow
        with pytest.raises(LLMUnavailableError) as exc_info:
            await service.generate(system_prompt="s", user_prompt="u")

    assert exc_info.value.reason == "timeout"


# ---------------------------------------------------------------------------
# Structured output
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_outage_is_not_retried_as_a_schema_problem():
    """An outage is not bad JSON — retrying with a correction prompt just
    burns another call and ends in a misleading error."""
    service = LLMService(api_key="test_key")

    with patch.object(
        service,
        "generate",
        new=AsyncMock(side_effect=LLMUnavailableError("down", reason="provider_outage")),
    ) as gen:
        with pytest.raises(LLMUnavailableError):
            await service.structured_generate(
                system_prompt="s", user_prompt="u", output_schema=_Schema
            )

    assert gen.await_count == 1, "An outage must not trigger the correction retry"


@pytest.mark.asyncio
async def test_invalid_json_is_retried_once_then_reported():
    service = LLMService(api_key="test_key")

    with patch.object(service, "generate", new=AsyncMock(return_value="not json at all")) as gen:
        with pytest.raises(ValueError) as exc_info:
            await service.structured_generate(
                system_prompt="s", user_prompt="u", output_schema=_Schema
            )

    assert gen.await_count == 2, "Bad output gets exactly one correction retry"
    assert "validation" in str(exc_info.value).lower()


@pytest.mark.asyncio
async def test_markdown_fenced_json_is_parsed():
    service = LLMService(api_key="test_key")
    fenced = '```json\n{"answer": "181 is the women helpline"}\n```'

    with patch.object(service, "generate", new=AsyncMock(return_value=fenced)):
        result = await service.structured_generate(
            system_prompt="s", user_prompt="u", output_schema=_Schema
        )

    assert result.answer == "181 is the women helpline"


@pytest.mark.asyncio
async def test_second_attempt_can_succeed():
    service = LLMService(api_key="test_key")
    responses = ["broken {", '{"answer": "recovered"}']

    with patch.object(service, "generate", new=AsyncMock(side_effect=responses)):
        result = await service.structured_generate(
            system_prompt="s", user_prompt="u", output_schema=_Schema
        )

    assert result.answer == "recovered"


@pytest.mark.asyncio
async def test_blocking_client_does_not_hold_the_event_loop():
    """The provider SDK is synchronous; calls must run off the event loop so
    concurrent agent work is actually concurrent."""
    service = LLMService(api_key="test_key", timeout_seconds=10)

    def _slow(*args, **kwargs):
        import time

        time.sleep(0.3)
        return MagicMock(text="done")

    with patch("backend.services.llm_service.genai.GenerativeModel") as model_cls:
        model_cls.return_value.generate_content.side_effect = _slow

        loop = asyncio.get_running_loop()
        start = loop.time()
        await asyncio.gather(
            *(service.generate(system_prompt="s", user_prompt=f"u{i}") for i in range(4))
        )
        elapsed = loop.time() - start

    # Four 0.3s calls run in parallel finish well before 1.2s.
    assert elapsed < 1.0, f"Calls appear serialised on the event loop ({elapsed:.2f}s)"
