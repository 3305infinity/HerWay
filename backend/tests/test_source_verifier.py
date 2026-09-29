"""
Unit tests for Source Verification / Evidence Agent (Task 4).

Tests:
1. Multiple agreeing sources (high agreement score & verified status)
2. Conflicting sources (creates Contradiction object and flags CONFLICTING status)
3. Outdated source + recent official source (weights freshness & domain authority)
4. Irrelevant search result (filtered out or assigned UNVERIFIED)
"""

import pytest
from unittest.mock import AsyncMock

from backend.agents.source_verifier import SourceVerifier, _ExtractedEvidenceBatch, _RawExtractedItem
from backend.models.research import (
    EvidenceConfidence,
    EvidenceStatus,
    SearchResult,
    Situation,
    SituationCategory,
    SourceType,
)


@pytest.fixture
def sample_situation():
    return Situation(
        case_summary="User seeks refund for damaged laptop delivered by online seller.",
        category=SituationCategory.CONSUMER,
        user_goal="Obtain full refund",
        known_facts=["Purchased laptop", "Arrived damaged"],
    )


@pytest.mark.asyncio
async def test_source_verifier_agreeing_sources(sample_situation):
    # 1. Multiple Agreeing Sources
    mock_llm = AsyncMock()

    batch_output = _ExtractedEvidenceBatch(
        items=[
            _RawExtractedItem(
                source_title="National Consumer Helpline Guidelines",
                url="https://consumerhelpline.gov.in/rules",
                domain="consumerhelpline.gov.in",
                source_type=SourceType.OFFICIAL_GOVERNMENT,
                claim_supported="Consumers can file a complaint within 7 days for damaged goods delivered online.",
                extracted_facts=["File within 7 days for damaged goods online"],
                directness_score=0.9,
                freshness_score=0.95,
                why_this_source_matters="Official government consumer helpline procedure.",
            ),
            _RawExtractedItem(
                source_title="India Consumer Protection Act 2019 Summary",
                url="https://ncdrc.nic.in/cpa2019",
                domain="ncdrc.nic.in",
                source_type=SourceType.OFFICIAL_GOVERNMENT,
                claim_supported="Consumers can file a complaint within 7 days for damaged goods delivered online.",
                extracted_facts=["7-day complaint window for damaged goods"],
                directness_score=0.95,
                freshness_score=0.9,
                why_this_source_matters="Official dispute redressal commission rules.",
            ),
        ]
    )

    mock_llm.structured_generate.return_value = batch_output
    verifier = SourceVerifier(mock_llm)

    results = [
        SearchResult(title="Helpline", url="https://consumerhelpline.gov.in/rules", snippet="File complaint in 7 days"),
        SearchResult(title="NCDRC", url="https://ncdrc.nic.in/cpa2019", snippet="7-day window"),
    ]

    evidence = await verifier.verify(sample_situation, results)

    assert len(evidence) == 2
    assert evidence[0].status == EvidenceStatus.VERIFIED_STRONGLY_SUPPORTED
    assert evidence[0].confidence == EvidenceConfidence.HIGH
    assert evidence[0].authority >= 0.85
    assert evidence[0].confidence_score >= 0.75


@pytest.mark.asyncio
async def test_source_verifier_conflicting_sources(sample_situation):
    # 2. Conflicting Sources
    mock_llm = AsyncMock()

    batch_output = _ExtractedEvidenceBatch(
        items=[
            _RawExtractedItem(
                source_title="Official E-Commerce Policy",
                url="https://platform.com/policy",
                domain="platform.com",
                source_type=SourceType.COMPANY,
                claim_supported="Return window for damaged electronics is strictly 10 days.",
                extracted_facts=["10 day return window"],
                directness_score=0.8,
                freshness_score=0.9,
                contradiction_found={
                    "source_b": "Forum User Post",
                    "difference": "Forum claims return window was reduced to 3 days.",
                },
            ),
        ]
    )

    mock_llm.structured_generate.return_value = batch_output
    verifier = SourceVerifier(mock_llm)

    results = [SearchResult(title="Policy", url="https://platform.com/policy", snippet="10 days return")]

    evidence = await verifier.verify(sample_situation, results)

    assert len(evidence) == 1
    assert evidence[0].status == EvidenceStatus.CONFLICTING
    assert len(evidence[0].contradictions) == 1
    assert evidence[0].contradictions[0].resolution_status == "unresolved"


@pytest.mark.asyncio
async def test_source_verifier_outdated_vs_recent_official(sample_situation):
    # 3. Outdated Source + Recent Official Source
    mock_llm = AsyncMock()

    batch_output = _ExtractedEvidenceBatch(
        items=[
            _RawExtractedItem(
                source_title="Old Blog Post (2018)",
                url="https://randomblog.com/rules-2018",
                domain="randomblog.com",
                source_type=SourceType.BLOG,
                claim_supported="Written complaints must be sent by physical registered mail.",
                extracted_facts=["Physical mail required"],
                directness_score=0.5,
                freshness_score=0.3,  # Low freshness
                why_this_source_matters="Outdated blog guidance",
            ),
            _RawExtractedItem(
                source_title="E-Daakhil Portal Official 2026",
                url="https://edaakhil.nic.in",
                domain="edaakhil.nic.in",
                source_type=SourceType.OFFICIAL_GOVERNMENT,
                claim_supported="Consumer complaints can be filed 100% online via E-Daakhil portal.",
                extracted_facts=["Online filing via E-Daakhil portal"],
                directness_score=0.95,
                freshness_score=1.0,  # Recent / active
                why_this_source_matters="Official online filing system",
            ),
        ]
    )

    mock_llm.structured_generate.return_value = batch_output
    verifier = SourceVerifier(mock_llm)

    results = [
        SearchResult(title="Blog", url="https://randomblog.com/rules-2018", snippet="Send mail"),
        SearchResult(title="Portal", url="https://edaakhil.nic.in", snippet="Online filing"),
    ]

    evidence = await verifier.verify(sample_situation, results)

    assert len(evidence) == 2

    # Blog item has lower authority & freshness score
    assert evidence[0].authority <= 0.35
    assert evidence[0].confidence_score < 0.60

    # Official portal has highest authority & score
    assert evidence[1].authority >= 0.90
    assert evidence[1].status == EvidenceStatus.VERIFIED_STRONGLY_SUPPORTED


@pytest.mark.asyncio
async def test_source_verifier_irrelevant_result(sample_situation):
    # 4. Irrelevant Search Result
    mock_llm = AsyncMock()

    # LLM filters out irrelevant items and returns empty batch or low directness
    batch_output = _ExtractedEvidenceBatch(
        items=[
            _RawExtractedItem(
                source_title="Laptop Unboxing Video",
                url="https://youtube.com/watch?v=123",
                domain="youtube.com",
                source_type=SourceType.COMMUNITY,
                claim_supported="This laptop features an Intel i7 processor and 16GB RAM.",
                extracted_facts=["Hardware specs"],
                directness_score=0.1,  # Irrelevant to refund dispute
                freshness_score=0.5,
                why_this_source_matters="Irrelevant product review video.",
            )
        ]
    )

    mock_llm.structured_generate.return_value = batch_output
    verifier = SourceVerifier(mock_llm)

    results = [SearchResult(title="Video", url="https://youtube.com/watch?v=123", snippet="Unboxing video")]

    evidence = await verifier.verify(sample_situation, results)

    assert len(evidence) == 1
    assert evidence[0].status == EvidenceStatus.UNVERIFIED
    assert evidence[0].confidence_score < 0.50
