"""
SituationAgent — Situation Understanding Agent (Stage 1 of Haven pipeline).

Responsibility
--------------
Accept raw natural-language user text describing a real-world situation and
convert it into a structured ``Situation`` Pydantic model.

Strict Principles
-----------------
1. Distinguishes KNOWN FACT vs USER CLAIM vs UNKNOWN:
   - KNOWN FACT: Explicitly stated objective events (e.g., 'Bought laptop on Sept 15 for $1,200').
   - USER CLAIM: User assertions or legal/procedural conclusions (e.g., 'Seller violated consumer law').
   - UNKNOWN: Items requiring research or missing context (e.g., 'Whether return window is 14 or 30 days').
   - NEVER convert user claims into facts.
2. Categories:
   - Extensible options: consumer, housing, employment, education, financial, travel,
     cyber, legal_information, government_service, safety, health_information, other.
   - Does NOT force a category when confidence is low (defaults to 'other').
3. Targeted Follow-ups:
   - Identifies missing information (e.g. purchase date, seller name, warranty, payment method).
   - Only asks follow-up questions that materially affect research.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from backend.models.research import Situation, SituationCategory

if TYPE_CHECKING:
    from backend.services.llm_service import LLMService

logger = logging.getLogger(__name__)

_SYSTEM_PROMPT = """\
You are the Situation Understanding Agent for HerWay, an AI assistant for real-world problem resolution.

Your task is to analyze a user's natural language situation description and convert it into a structured JSON Situation object.

CRITICAL RULES:
1. DISTINGUISH FACTS, CLAIMS, AND UNKNOWNS:
   - known_facts: ONLY objective, explicitly stated events (e.g., "User bought a laptop on Amazon on Sept 10", "Package arrived damaged").
   - user_claims: Assertions, allegations, or legal conclusions made by the user (e.g., "The seller scammed me", "Seller violated consumer protection laws").
   - unknowns: Unverified questions or legal/procedural uncertainties (e.g., "Whether Amazon's return window applies to opened items", "Which court has jurisdiction").
   NEVER convert user claims into facts.

2. CATEGORY SELECTION:
   Assign the single best category from:
   [consumer, housing, employment, education, financial, travel, cyber, legal_information, government_service, safety, health_information, domestic_violence, sexual_harassment, stalking, online_harassment, threats, coercive_control, unsafe_relationship, workplace_harassment, other_women_safety, other]
   If confidence is low or ambiguous, select "other".

3. MISSING INFORMATION & QUESTIONS:
   - Identify missing details that materially affect research (e.g., purchase date, platform/seller name, user's country/state, payment method, warranty status, complaint number).
   - Only ask questions that materially alter research directions. Do not ask redundant questions.

4. USER GOAL & SUMMARY:
   - case_summary: A concise 1-paragraph summary of the situation.
   - user_goal: Clear statement of desired outcome (e.g., "Obtain full refund for damaged laptop").

Respond ONLY with valid JSON matching the Situation schema.
"""


class SituationAgent:
    """Converts natural language situation descriptions into structured ``Situation`` models."""

    def __init__(self, llm: LLMService) -> None:
        self._llm = llm

    async def analyse(self, user_text: str) -> Situation:
        """Analyze raw text description into a typed Situation model."""
        logger.info("SituationAgent: analyzing %d characters of user input", len(user_text))

        situation = await self._llm.structured_generate(
            system_prompt=_SYSTEM_PROMPT,
            user_prompt=f"User Situation:\n\"\"\"\n{user_text}\n\"\"\"",
            output_schema=Situation,
        )

        logger.info(
            "SituationAgent: summary='%s...', category=%s, urgency=%s, %d facts, %d claims, %d unknowns",
            situation.case_summary[:60],
            situation.category,
            situation.urgency,
            len(situation.known_facts),
            len(situation.user_claims),
            len(situation.unknowns),
        )

        return situation

