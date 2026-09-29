"""
SourceVerifier — Source Verification & Evidence Agent (Stage 3 of Haven pipeline).

Scoring Formula (Explicit & Transparent)
---------------------------------------
The evidence confidence score (0.0 to 1.0) is calculated using an explicit weighted formula:

    Score = (0.40 * Authority) + (0.25 * Agreement) + (0.20 * Directness) + (0.15 * Freshness)

Where:
- Authority (0.0 - 1.0):
  - `.gov` / `.gov.in` / `.edu` / official portals = 0.95
  - Major official organizations / NGOs / verified help portals = 0.85
  - Major news organizations = 0.75
  - Company official help sites = 0.65
  - Community forums / blogs / general web = 0.35
- Agreement (0.0 - 1.0):
  - Supported by multiple distinct sources = 1.0
  - Single source with no contradictions = 0.6
  - Contradiction detected between sources = 0.2
- Directness (0.0 - 1.0):
  - Direct procedural rule / explicit quote = 0.9
  - Contextually relevant inference = 0.6
- Freshness (0.0 - 1.0):
  - Current year / active policy = 1.0
  - Timeless official procedure = 0.85
  - Outdated news (> 3 years old) = 0.4

Categorization
--------------
- VERIFIED_STRONGLY_SUPPORTED (Score >= 0.75)
- PARTIALLY_SUPPORTED (Score 0.50 - 0.74)
- CONFLICTING (Contradiction present or disagreement)
- UNVERIFIED (Score < 0.50)
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, List, Optional
from urllib.parse import urlparse

from pydantic import BaseModel, Field

from backend.models.research import (
    Contradiction,
    EvidenceConfidence,
    EvidenceItem,
    EvidenceStatus,
    SearchResult,
    Situation,
    SourceType,
)

if TYPE_CHECKING:
    from backend.services.llm_service import LLMService

logger = logging.getLogger(__name__)

_VERIFIER_SYSTEM_PROMPT = """\
You are the Source Verification & Evidence Agent for Haven.

Input:
- A structured Situation object.
- A batch of search results (title, snippet, URL, domain).

Your Task:
1. Filter out irrelevant, clickbait, or spammy results.
2. For each valuable search result, extract concrete factual claims or official resources.
3. Classify the source type:
   [official_government, official_organization, news, academic, company, local_business, community, blog, forum, unknown]
4. Directness: Assess how directly the snippet supports the extracted claim (0.0 to 1.0).
5. Freshness: Assess how recent or applicable the snippet is (0.0 to 1.0).
6. Contradictions: If the snippet contradicts a known fact or another claim in the batch, describe the contradiction.

IMPORTANT:
- Do NOT fabricate authority or legal guarantees.
- Always preserve exact URLs.
- If a snippet is vague or unverified, set directness < 0.5.

Respond ONLY with valid JSON matching the _ExtractedEvidenceBatch schema.
"""


class _RawExtractedItem(BaseModel):
    source_title: str
    url: Optional[str] = None
    domain: Optional[str] = None
    source_type: SourceType = SourceType.UNKNOWN
    claim_supported: str
    extracted_facts: List[str] = Field(default_factory=list)
    directness_score: float = Field(0.7, ge=0.0, le=1.0)
    freshness_score: float = Field(0.8, ge=0.0, le=1.0)
    why_this_source_matters: str = ""
    contradiction_found: Optional[dict] = None


class _ExtractedEvidenceBatch(BaseModel):
    items: List[_RawExtractedItem] = Field(default_factory=list)


class SourceVerifier:
    """Verifies search results, computes transparent confidence scores, and detects contradictions."""

    def __init__(self, llm: LLMService) -> None:
        self._llm = llm

    async def verify(
        self,
        situation: Situation,
        results: List[SearchResult],
        *,
        batch_size: int = 10,
    ) -> List[EvidenceItem]:
        """Verify search results and output scored EvidenceItem models."""
        if not results:
            logger.warning("SourceVerifier: No search results to verify.")
            return []

        raw_items: List[_RawExtractedItem] = []

        # Process search results in batches
        for i in range(0, len(results), batch_size):
            batch = results[i : i + batch_size]
            batch_text = "\n\n".join(
                f"[{j+1}] Title: {r.title}\nURL: {r.url or 'N/A'}\nDomain: {r.domain or 'N/A'}\nSnippet: {r.snippet}"
                for j, r in enumerate(batch)
            )

            prompt = (
                f"Situation: {situation.case_summary}\n"
                f"User Goal: {situation.user_goal}\n"
                f"Known Facts: {situation.known_facts}\n\n"
                f"Search Results:\n{batch_text}"
            )

            try:
                parsed_batch = await self._llm.structured_generate(
                    system_prompt=_VERIFIER_SYSTEM_PROMPT,
                    user_prompt=prompt,
                    output_schema=_ExtractedEvidenceBatch,
                )
                raw_items.extend(parsed_batch.items)
            except Exception as exc:
                logger.error("SourceVerifier: Failed to process batch %d: %s", i, exc)

        # Post-process raw items: Compute observable authority, score, agreement, & status
        evidence_list: List[EvidenceItem] = []

        # Map to detect agreement / contradictions across extracted items
        claim_map: dict[str, list[str]] = {}
        for item in raw_items:
            key = item.claim_supported.lower().strip()[:40]
            claim_map.setdefault(key, []).append(item.source_title)

        for idx, raw in enumerate(raw_items):
            evidence_id = f"EVIDENCE_{idx + 1:02d}"
            domain = raw.domain or self._extract_domain(raw.url)

            # 1. Observable Domain Authority Score
            authority_score, source_type = self._evaluate_authority(domain, raw.source_type)

            # 2. Agreement Score
            key = raw.claim_supported.lower().strip()[:40]
            agreeing_sources = claim_map.get(key, [])
            if len(agreeing_sources) > 1:
                agreement_score = 1.0
            elif raw.contradiction_found:
                agreement_score = 0.2
            else:
                agreement_score = 0.6

            # 3. Transparent Weighted Score Calculation:
            # Score = (0.40 * Authority) + (0.25 * Agreement) + (0.20 * Directness) + (0.15 * Freshness)
            final_score = round(
                (0.40 * authority_score)
                + (0.25 * agreement_score)
                + (0.20 * raw.directness_score)
                + (0.15 * raw.freshness_score),
                2,
            )

            # Determine Confidence Enum & Status
            if raw.contradiction_found or agreement_score <= 0.2:
                status = EvidenceStatus.CONFLICTING
                conf = EvidenceConfidence.LOW
            elif final_score >= 0.75:
                status = EvidenceStatus.VERIFIED_STRONGLY_SUPPORTED
                conf = EvidenceConfidence.HIGH
            elif final_score >= 0.50:
                status = EvidenceStatus.PARTIALLY_SUPPORTED
                conf = EvidenceConfidence.MEDIUM
            else:
                status = EvidenceStatus.UNVERIFIED
                conf = EvidenceConfidence.LOW

            contradiction_objs = []
            if raw.contradiction_found:
                contradiction_objs.append(
                    Contradiction(
                        claim=raw.claim_supported,
                        source_a=raw.source_title,
                        source_b=raw.contradiction_found.get("source_b", "Other Source"),
                        difference=raw.contradiction_found.get("difference", "Disagreement on claim details"),
                        resolution_status="unresolved",
                    )
                )

            evidence_item = EvidenceItem(
                id=evidence_id,
                source_title=raw.source_title,
                url=raw.url,
                domain=domain,
                source_type=source_type,
                relevance=raw.directness_score,
                freshness=raw.freshness_score,
                authority=authority_score,
                supports_claim=True,
                claim_supported=raw.claim_supported,
                extracted_facts=raw.extracted_facts or [raw.claim_supported],
                contradictions=contradiction_objs,
                confidence=conf,
                confidence_score=final_score,
                status=status,
                why_this_source_matters=raw.why_this_source_matters,
            )

            evidence_list.append(evidence_item)

        logger.info(
            "SourceVerifier: Verified %d evidence items from %d raw search results",
            len(evidence_list),
            len(results),
        )
        return evidence_list

    def _evaluate_authority(self, domain: Optional[str], fallback_type: SourceType) -> tuple[float, SourceType]:
        """Compute observable domain authority score and refine source_type."""
        if not domain:
            return 0.35, fallback_type

        d = domain.lower()
        if d.endswith(".gov") or d.endswith(".gov.in") or d.endswith(".gov.uk") or d.endswith(".edu") or d.endswith(".ac.in"):
            return 0.95, SourceType.OFFICIAL_GOVERNMENT
        if "org" in d or "consumerhelpline" in d or "ncdrc" in d or "cybercrime" in d:
            return 0.85, SourceType.OFFICIAL_ORGANIZATION
        if any(news_kw in d for news_kw in ["news", "times", "reuters", "bbc", "hindu", "tribune", "express", "post"]):
            return 0.75, SourceType.NEWS
        if any(forum_kw in d for forum_kw in ["reddit", "quora", "forum", "medium", "wordpress", "blogspot"]):
            return 0.35, SourceType.FORUM

        return 0.65, fallback_type if fallback_type != SourceType.UNKNOWN else SourceType.COMPANY

    def _extract_domain(self, url: Optional[str]) -> Optional[str]:
        if not url:
            return None
        try:
            parsed = urlparse(url)
            return (parsed.netloc or parsed.path).lower().replace("www.", "")
        except Exception:
            return None

