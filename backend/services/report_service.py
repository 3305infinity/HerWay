"""
ReportService — thin wrapper around existing Haven text-expansion utilities.

Reuses:
  - backend.utils.text_llm.expand_user_text_using_gemini
  - backend.utils.text_llm.expand_user_text_using_gemma
  - backend.utils.text_llm.create_poem

DO NOT rebuild these — call the existing functions directly.
This service is invoked by ChatAgent's ``generate_formal_report``
and ``generate_poem`` tools.
"""

from __future__ import annotations

import logging
from typing import Optional

from backend.utils.text_llm import (
    create_poem,
    expand_user_text_using_gemini,
    expand_user_text_using_gemma,
)

logger = logging.getLogger(__name__)


class ReportService:
    """Wraps existing Haven text-generation utilities for reuse by agents."""

    # ------------------------------------------------------------------ #
    # Formal authority report generation (existing LLM pipeline)
    # ------------------------------------------------------------------ #

    async def generate_formal_report(
        self,
        situation_text: str,
        name: Optional[str] = None,
        location: Optional[str] = None,
        phone: Optional[str] = None,
        duration_of_abuse: Optional[str] = None,
        frequency: Optional[str] = None,
        contact_method: Optional[str] = "Not specified",
        culprit_description: Optional[str] = "Not specified",
        extra_context: Optional[str] = None,
    ) -> dict:
        """
        Generate a formal, urgent authority report using the existing
        ``expand_user_text_using_gemini`` + ``expand_user_text_using_gemma``
        pipeline (both models, dual-output for resilience).

        Returns dict with keys: ``gemini_response``, ``gemma_response``.
        """
        concatenated = (
            f"Name: {name or 'Anonymous'}\n"
            f"Phone: {phone or 'Not specified'}\n"
            f"Location: {location or 'Not specified'}\n"
            f"Duration of Abuse: {duration_of_abuse or 'Not specified'}\n"
            f"Frequency of Incidents: {frequency or 'Not specified'}\n"
            f"Preferred Contact Method: {contact_method}\n"
            f"Current Situation: {situation_text}\n"
            f"Culprit Description: {culprit_description}\n"
        )
        if extra_context:
            concatenated += f"\nAdditional Context: {extra_context}\n"

        logger.info("ReportService: generating formal report (%d chars)", len(concatenated))

        gemini_text = ""
        gemma_text = ""

        try:
            gemini_text = await expand_user_text_using_gemini(concatenated)
        except Exception as exc:
            logger.warning("ReportService: Gemini expansion failed: %s", exc)

        try:
            gemma_text = await expand_user_text_using_gemma(concatenated)
        except Exception as exc:
            logger.warning("ReportService: Gemma expansion failed: %s", exc)

        return {
            "gemini_response": gemini_text,
            "gemma_response": gemma_text,
        }

    # ------------------------------------------------------------------ #
    # Inspirational poem generation (existing pipeline)
    # ------------------------------------------------------------------ #

    def generate_poem(self, situation_text: str) -> str:
        """
        Generate an empowering poem using the existing ``create_poem()``
        pipeline (Gemini 1.5 Flash 8B with INSPIRATION_POEM_PROMPT).
        """
        logger.info("ReportService: generating inspirational poem")
        try:
            return create_poem(situation_text)
        except Exception as exc:
            logger.error("ReportService.generate_poem failed: %s", exc)
            return (
                "You are braver than you know,\n"
                "Stronger than the fear that shadows you.\n"
                "Through Haven, help is on its way —\n"
                "You are not alone, not today."
            )
