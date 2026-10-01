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
from backend.safety_triage import apply_triage_to_text
from backend.trace import log_fields

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
   [consumer, housing, employment, education, financial, travel, cyber, legal_information, government_service, safety, health_information, domestic_violence, sexual_harassment, stalking, online_harassment, threats, coercive_control, unsafe_relationship, workplace_harassment, other_women_safety, immediate_danger, street_harassment, unsafe_travel, campus_safety, emotional_distress, safety_planning, local_discovery, other]
   If confidence is low or ambiguous, select "other".
   Use "immediate_danger" ONLY when harm is happening now or within minutes.
   Use "emotional_distress" when the user wants to be heard and has asked no
   factual question. Use "safety_planning" when nothing is wrong right now but
   they want to prepare. Use "local_discovery" for "what is near me" with no
   incident disclosed.

5. INTENT:
   What the user wants from HerWay right now — one of:
   [get_to_safety, understand_options, take_formal_action, find_local_help,
    emotional_support, plan_ahead, preserve_evidence, other]
   This is NOT the same as user_goal. user_goal is their real-world outcome
   ("get a restraining order"); intent is what they need from this app in this
   moment ("understand_options").

6. CONSTRAINTS:
   Record limits the user actually stated, in their words — "cannot leave the
   children", "he checks my phone", "no money of my own", "do not tell my
   family". NEVER infer a constraint that was not stated. An empty list is
   correct and expected.

7. IMMEDIATE DANGER SIGNALS:
   If and only if the user's words indicate danger now, quote the exact
   fragments into immediate_danger_signals. Quote; do not paraphrase, and do
   not add a signal that is not literally present in their message.

8. URGENCY:
   Be conservative. If you are unsure between two levels, choose the higher
   one. Do not downgrade urgency because the user is writing calmly — people
   describe severe danger in flat language.

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
        logger.info(
            "SituationAgent: analysing input %s",
            log_fields(input_chars=len(user_text)),
        )

        situation = await self._llm.structured_generate(
            system_prompt=_SYSTEM_PROMPT,
            user_prompt=f"User Situation:\n\"\"\"\n{user_text}\n\"\"\"",
            output_schema=Situation,
        )

        # Deterministic triage over the user's own words, applied on top of the
        # model's judgement. It can only raise urgency, never lower it: a model
        # that under-reads "he is outside my door" must not decide this is a
        # routine case. It also sets the workflow, so routing keeps working
        # when the model is degraded. See backend/safety_triage.py.
        situation = apply_triage_to_text(situation, user_text)

        # Counts and classifications only. This previously logged the first 60
        # characters of `case_summary`, which is a paraphrase of what the user
        # just disclosed — a log line reading "husband hit me again last night"
        # is exactly the kind of record this product must not create.
        logger.info(
            "SituationAgent: analysed %s",
            log_fields(
                category=situation.category.value,
                urgency=situation.urgency.value,
                intent=situation.intent.value,
                workflow=(
                    situation.recommended_workflow.value
                    if situation.recommended_workflow
                    else None
                ),
                danger_signals=len(situation.immediate_danger_signals),
                facts=len(situation.known_facts),
                claims=len(situation.user_claims),
                unknowns=len(situation.unknowns),
                has_location=bool(situation.location),
            ),
        )

        return situation

