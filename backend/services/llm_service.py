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


class LLMService:
    """Thin wrapper around Google Gemini with structured-output support."""

    def __init__(
        self,
        api_key: str | None = None,
        model_name: str = "gemini-1.5-flash",
    ) -> None:
        self._api_key = api_key or os.getenv("GEMINI_API_KEY", "")
        self._model_name = model_name
        genai.configure(api_key=self._api_key)

    # ------------------------------------------------------------------
    # Public interface
    # ------------------------------------------------------------------

    async def generate(
        self,
        *,
        system_prompt: str,
        user_prompt: str,
    ) -> str:
        """Plain text generation. Returns the raw LLM response string."""
        model = genai.GenerativeModel(
            self._model_name,
            system_instruction=system_prompt,
        )
        response = model.generate_content(user_prompt)
        return response.text

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
        except Exception as exc:
            logger.warning("LLMService: Attempt 1 failed (%s). Retrying with correction prompt...", exc)

        # Attempt 2 — Correction prompt retry
        correction_prompt = (
            f"{user_prompt}\n\n"
            f"CRITICAL FIX: Your previous output failed JSON validation with error:\n{exc}\n\n"
            f"Please regenerate strictly adhering to the schema without markdown syntax errors."
        )
        try:
            raw = await self.generate(system_prompt=full_system, user_prompt=correction_prompt)
            cleaned = self._clean_json_str(raw)
            data = json.loads(cleaned)
            return output_schema.model_validate(data)
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
