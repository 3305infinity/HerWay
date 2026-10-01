"""
LLMService — unified interface to Gemini (and optionally Groq/Gemma).

This service wraps all LLM calls so that:
1. API key management is centralised.
2. Agents never import ``google.generativeai`` directly.
3. Structured JSON output is parsed into Pydantic models automatically.
4. Retry / error handling lives in one place.

The existing ``text_llm.py`` utilities are preserved in ``backend/utils/``
and continue to work for legacy endpoints.  New pipeline code should use
this service instead.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import re
from typing import Type, TypeVar

import google.generativeai as genai
from dotenv import load_dotenv
from pydantic import BaseModel

load_dotenv()

logger = logging.getLogger(__name__)

T = TypeVar("T", bound=BaseModel)

# How long a single Gemini call may take before we give up and surface a
# user-facing failure.  Without this the whole request can hang indefinitely.
#: A structured-output call sends the full JSON schema and asks for a complete
#: plan back, so it is legitimately slower than a chat turn. 45s was cutting
#: off research planning before it had finished rather than because anything
#: was wrong.
_DEFAULT_TIMEOUT_SECONDS = float(os.getenv("GEMINI_TIMEOUT_SECONDS", "90"))

#: Default Gemini model. ``gemini-flash-latest`` is a moving alias that Google
#: repoints at the current flash model, so the app keeps working across model
#: retirements. This matters here: the previously hardcoded
#: ``gemini-1.5-flash`` was withdrawn and began returning 404, which took down
#: every agent in the pipeline at once. Pin a specific version with
#: GEMINI_MODEL if you need reproducible behaviour.
DEFAULT_MODEL = os.getenv("GEMINI_MODEL", "gemini-flash-latest")


class LLMUnavailableError(RuntimeError):
    """Raised when Gemini is not configured or cannot be reached.

    Callers should translate this into an honest user-facing message rather
    than substituting invented content.

    ``user_message`` is safe to show directly; ``reason`` is a machine-readable
    code for logging and metrics.
    """

    def __init__(self, message: str, *, reason: str = "unavailable", user_message: str | None = None):
        super().__init__(message)
        self.reason = reason
        self.user_message = user_message or (
            "HerWay's assistant is unavailable right now. Please try again shortly."
        )


def _classify_api_error(exc: Exception) -> LLMUnavailableError | None:
    """Map a provider error onto an honest, user-facing failure.

    Rate limits, quota exhaustion and retired models are operational problems,
    not bad model output. Treating them as parse failures sent them through the
    correction-retry path, wasting another call and ending in a generic
    "something went wrong" that told the user nothing useful.
    """
    text = str(exc).lower()

    if "429" in text or "quota" in text or "rate limit" in text or "resource_exhausted" in text:
        return LLMUnavailableError(
            str(exc),
            reason="rate_limited",
            user_message=(
                "HerWay has reached its limit for AI requests just now. Please try again "
                "in a few minutes. If you need help immediately, call 112, or 181 for the "
                "women helpline."
            ),
        )

    if "not found" in text and "model" in text:
        return LLMUnavailableError(
            str(exc),
            reason="model_unavailable",
            user_message=(
                "HerWay's assistant is misconfigured and cannot answer right now. "
                "Please try again later, or call 181 for the women helpline."
            ),
        )

    if "permission" in text or "api key" in text or "unauthenticated" in text or "401" in text:
        return LLMUnavailableError(
            str(exc),
            reason="auth_failed",
            user_message=(
                "HerWay's assistant is not configured correctly. Please try again later, "
                "or call 181 for the women helpline."
            ),
        )

    if "503" in text or "unavailable" in text or "500" in text or "internal" in text:
        return LLMUnavailableError(
            str(exc),
            reason="provider_outage",
            user_message=(
                "HerWay's assistant is temporarily unavailable. Please try again shortly."
            ),
        )

    return None


class LLMService:
    """Thin wrapper around Google Gemini with structured-output support."""

    def __init__(
        self,
        api_key: str | None = None,
        model_name: str | None = None,
        timeout_seconds: float = _DEFAULT_TIMEOUT_SECONDS,
    ) -> None:
        # An explicitly supplied key wins, including an empty string meaning
        # "no key". Only fall back to the environment when nothing was passed —
        # otherwise a test for the unconfigured path quietly makes a real,
        # billable API call.
        self._api_key = os.getenv("GEMINI_API_KEY", "") if api_key is None else api_key
        self._model_name = model_name or DEFAULT_MODEL
        self._timeout_seconds = timeout_seconds
        if self._api_key:
            genai.configure(api_key=self._api_key)
        else:
            logger.warning(
                "LLMService: GEMINI_API_KEY is not set. Agent features that "
                "depend on the LLM will report an outage instead of answering."
            )

    @property
    def is_configured(self) -> bool:
        """True when an API key is present. Routes use this to degrade gracefully."""
        return bool(self._api_key)

    # ------------------------------------------------------------------
    # Public interface
    # ------------------------------------------------------------------

    async def generate(
        self,
        *,
        system_prompt: str,
        user_prompt: str,
    ) -> str:
        """Plain text generation. Returns the raw LLM response string.

        ``google.generativeai`` is a blocking client, so the call is pushed to a
        worker thread.  Previously it ran inline on the event loop, which
        serialised every "concurrent" agent call and blocked all other requests
        for the duration.
        """
        if not self._api_key:
            raise LLMUnavailableError(
                "GEMINI_API_KEY is not configured.",
                reason="not_configured",
                user_message=(
                    "HerWay's assistant is not available on this deployment. "
                    "For urgent help call 112, or 181 for the women helpline."
                ),
            )

        def _call() -> str:
            model = genai.GenerativeModel(
                self._model_name,
                system_instruction=system_prompt,
            )
            response = model.generate_content(user_prompt)
            return response.text

        try:
            return await asyncio.wait_for(
                asyncio.to_thread(_call), timeout=self._timeout_seconds
            )
        except asyncio.TimeoutError as exc:
            raise LLMUnavailableError(
                f"Gemini did not respond within {self._timeout_seconds:.0f}s.",
                reason="timeout",
                user_message=(
                    "That took longer than expected and we stopped waiting. "
                    "Please try again — your information has been saved."
                ),
            ) from exc
        except Exception as exc:
            classified = _classify_api_error(exc)
            if classified is not None:
                raise classified from exc
            raise

    async def structured_generate(
        self,
        *,
        system_prompt: str,
        user_prompt: str,
        output_schema: Type[T],
    ) -> T:
        """Generate and parse the LLM response into a Pydantic model.

        The system prompt should instruct the LLM to respond with JSON
        matching ``output_schema``.  This method strips markdown fences,
        parses the JSON, and validates it against the schema.

        Raises
        ------
        ValueError
            If the response is not valid JSON or does not match the schema.
        """
        full_system = (
            f"{system_prompt}\n\n"
            f"Respond ONLY with valid JSON matching this schema:\n"
            f"{json.dumps(output_schema.model_json_schema(), indent=2)}"
        )

        # Attempt 1
        try:
            raw = await self.generate(system_prompt=full_system, user_prompt=user_prompt)
            cleaned = self._clean_json_str(raw)
            data = json.loads(cleaned)
            return output_schema.model_validate(data)
        except LLMUnavailableError:
            # An outage is not a schema problem — retrying with a correction
            # prompt would just fail again. Surface it immediately.
            raise
        except Exception as exc:
            # ``exc`` is unbound outside this block in Python 3, so capture it.
            first_error = exc
            logger.warning(
                "LLMService: Attempt 1 failed (%s). Retrying with correction prompt...",
                first_error,
            )

        # Attempt 2 — Correction prompt retry
        correction_prompt = (
            f"{user_prompt}\n\n"
            f"CRITICAL FIX: Your previous output failed JSON validation with error:\n{first_error}\n\n"
            f"Please regenerate strictly adhering to the schema without markdown syntax errors."
        )
        try:
            raw = await self.generate(system_prompt=full_system, user_prompt=correction_prompt)
            cleaned = self._clean_json_str(raw)
            data = json.loads(cleaned)
            return output_schema.model_validate(data)
        except LLMUnavailableError:
            raise
        except Exception as exc2:
            logger.error("LLMService: Retry attempt 2 failed schema validation: %s", exc2)
            raise ValueError(f"LLM output failed Pydantic validation after retry: {exc2}") from exc2

    def _clean_json_str(self, raw: str) -> str:
        cleaned = raw.strip()
        # Look for markdown code fence
        match = re.search(r"```(?:json)?\s*([\s\S]*?)\s*```", cleaned, re.IGNORECASE)
        if match:
            cleaned = match.group(1).strip()
        else:
            first_brace = cleaned.find("{")
            first_bracket = cleaned.find("[")
            start = -1
            if first_brace != -1 and first_bracket != -1:
                start = min(first_brace, first_bracket)
            elif first_brace != -1:
                start = first_brace
            elif first_bracket != -1:
                start = first_bracket

            last_brace = cleaned.rfind("}")
            last_bracket = cleaned.rfind("]")
            end = max(last_brace, last_bracket)

            if start != -1 and end != -1 and end > start:
                cleaned = cleaned[start : end + 1].strip()

        return cleaned

    async def chat(
        self,
        *,
        system_prompt: str,
        messages: list[dict[str, str]],
    ) -> str:
        """Multi-turn chat.  ``messages`` is a list of
        ``{"role": "user"|"model", "content": "..."}`` dicts.

        Returns the assistant's reply as a string.
        """
        if not self._api_key:
            raise LLMUnavailableError(
                "GEMINI_API_KEY is not configured.", reason="not_configured"
            )

        def _call() -> str:
            model = genai.GenerativeModel(
                self._model_name,
                system_instruction=system_prompt,
            )
            # Convert to Gemini's Content format
            history = []
            for msg in messages[:-1]:
                role = "user" if msg["role"] == "user" else "model"
                history.append({"role": role, "parts": [msg["content"]]})

            chat = model.start_chat(history=history)
            last_msg = messages[-1]["content"] if messages else ""
            response = chat.send_message(last_msg)
            return response.text

        try:
            return await asyncio.wait_for(
                asyncio.to_thread(_call), timeout=self._timeout_seconds
            )
        except asyncio.TimeoutError as exc:
            raise LLMUnavailableError(
                f"Gemini did not respond within {self._timeout_seconds:.0f}s.",
                reason="timeout",
                user_message=(
                    "That took longer than expected and we stopped waiting. "
                    "Please try again."
                ),
            ) from exc
        except Exception as exc:
            classified = _classify_api_error(exc)
            if classified is not None:
                raise classified from exc
            raise
