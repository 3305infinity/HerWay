"""
Unit tests for Situation Understanding Agent (Task 2).

Includes example input/output test cases for:
1. Consumer complaint
2. Scam
3. Housing issue
4. Education issue
5. Cyber issue
"""

import pytest
from unittest.mock import AsyncMock

from backend.agents.situation_agent import SituationAgent
from backend.models.research import Situation, SituationCategory, Urgency


@pytest.fixture
def mock_llm():
    return AsyncMock()


@pytest.mark.asyncio
async def test_situation_consumer_complaint(mock_llm):
    # 1. Consumer Complaint Scenario
    user_input = (
        "I bought a laptop online on Sept 15 for $1,200 and it arrived with a cracked screen. "
        "The seller is refusing a replacement or refund and customer support stopped responding."
    )

    expected_situation = Situation(
        case_summary="User purchased a laptop for $1,200 which arrived damaged with a cracked screen; seller refuses refund/replacement.",
        category=SituationCategory.CONSUMER,
        subcategory="damaged_product_refund",
        urgency=Urgency.HIGH,
        location=None,
        entities=["laptop"],
        organizations_involved=["online seller"],
        user_goal="Obtain full refund or replacement for damaged laptop",
        known_facts=[
            "User purchased a laptop on Sept 15 for $1,200",
            "Laptop arrived with a cracked screen",
            "Seller refused replacement and stopped responding",
        ],
        user_claims=[
            "Seller is unlawfully withholding refund",
        ],
        unknowns=[
            "Platform return policy terms",
            "Whether payment was made via credit card or UPI",
        ],
        missing_information=[
            "Seller / e-commerce platform name",
            "Order ID",
            "Payment method used",
        ],
        questions_to_ask=[
            "What e-commerce platform was used?",
            "Did you pay via credit card (allowing chargeback)?",
        ],
        recommended_research_types=["web", "news"],
    )

    mock_llm.structured_generate.return_value = expected_situation

    agent = SituationAgent(mock_llm)
    result = await agent.analyse(user_input)

    assert result.category == SituationCategory.CONSUMER
    assert len(result.known_facts) == 3
    assert len(result.user_claims) == 1
    assert "laptop" in result.entities


@pytest.mark.asyncio
async def test_situation_scam(mock_llm):
    # 2. Scam / Fraud Scenario
    user_input = (
        "I received an urgent SMS claiming my bank account was suspended. I clicked the link and entered my OTP. "
        "Now $500 has been unauthorizedly transferred from my account."
    )

    expected_situation = Situation(
        case_summary="User was victimized by a bank phishing SMS scam and unauthorized $500 transfer occurred after sharing OTP.",
        category=SituationCategory.CYBER,  # or FINANCIAL / CYBER
        subcategory="phishing_bank_fraud",
        urgency=Urgency.CRITICAL,
        location=None,
        entities=["SMS link"],
        organizations_involved=["Bank"],
        user_goal="Block bank account, report fraud, and attempt funds recovery",
        known_facts=[
            "User received phishing SMS claiming bank account suspension",
            "User entered OTP on link",
            "Unauthorized transfer of $500 occurred",
        ],
        user_claims=[
            "Scammers stole funds illegally",
        ],
        unknowns=[
            "Whether bank hotline has been notified yet",
            "Transaction reference number",
        ],
        missing_information=[
            "Name of bank",
            "Time elapsed since transaction",
        ],
        questions_to_ask=[
            "Have you frozen your bank cards and reported to cyber crime portal?",
        ],
        recommended_research_types=["web", "maps", "local"],
    )

    mock_llm.structured_generate.return_value = expected_situation

    agent = SituationAgent(mock_llm)
    result = await agent.analyse(user_input)

    assert result.urgency == Urgency.CRITICAL
    assert "Bank" in result.organizations_involved


@pytest.mark.asyncio
async def test_situation_housing_issue(mock_llm):
    # 3. Rental Housing Issue Scenario
    user_input = (
        "I moved out of my apartment 45 days ago after fulfilling my lease. "
        "The landlord is refusing to return my $2,000 security deposit claiming fake painting charges."
    )

    expected_situation = Situation(
        case_summary="Landlord refusing to return $2,000 security deposit 45 days after move-out citing disputed painting costs.",
        category=SituationCategory.HOUSING,
        subcategory="security_deposit_dispute",
        urgency=Urgency.MEDIUM,
        location=None,
        entities=["apartment lease"],
        organizations_involved=["Landlord"],
        user_goal="Recover full $2,000 security deposit",
        known_facts=[
            "User vacated apartment 45 days ago",
            "Lease was fulfilled",
            "Landlord withheld $2,000 deposit citing painting fees",
        ],
        user_claims=[
            "Painting charges are fabricated and deposit is unlawfully withheld",
        ],
        unknowns=[
            "State statutory deposit return deadline (e.g. 14, 21, or 30 days)",
        ],
        missing_information=[
            "City / State of property",
            "Whether move-out photos exist",
        ],
        questions_to_ask=[
            "Do you have a written lease agreement and move-out inspection photos?",
        ],
        recommended_research_types=["web", "legal_information"],
    )

    mock_llm.structured_generate.return_value = expected_situation

    agent = SituationAgent(mock_llm)
    result = await agent.analyse(user_input)

    assert result.category == SituationCategory.HOUSING
    assert result.known_facts[0].startswith("User vacated")


@pytest.mark.asyncio
async def test_situation_education_issue(mock_llm):
    # 4. Education Issue Scenario
    user_input = (
        "My university is withholding my official degree transcript due to an alleged $150 library late fee dispute "
        "from 2 years ago that I already paid."
    )

    expected_situation = Situation(
        case_summary="University withholding official transcript over disputed $150 library fee that student claims was paid.",
        category=SituationCategory.EDUCATION,
        subcategory="transcript_withholding_dispute",
        urgency=Urgency.MEDIUM,
        location=None,
        entities=["transcript"],
        organizations_involved=["University"],
        user_goal="Obtain transcript release",
        known_facts=[
            "University is withholding official transcript",
            "Reason given is $150 library late fee",
        ],
        user_claims=[
            "The library fee was paid 2 years ago",
        ],
        unknowns=[
            "University ombudsman or academic appeal process",
        ],
        missing_information=[
            "University name",
            "Proof of payment receipt",
        ],
        questions_to_ask=[
            "Do you have a bank statement or receipt showing payment?",
        ],
        recommended_research_types=["web"],
    )

    mock_llm.structured_generate.return_value = expected_situation

    agent = SituationAgent(mock_llm)
    result = await agent.analyse(user_input)

    assert result.category == SituationCategory.EDUCATION


@pytest.mark.asyncio
async def test_situation_cyber_issue(mock_llm):
    # 5. Cyber Issue Scenario
    user_input = (
        "Someone created an impersonation account using my photos and full name on Instagram "
        "and is sending abusive messages to my colleagues."
    )

    expected_situation = Situation(
        case_summary="Unauthorized Instagram impersonation account sending abusive messages to user's colleagues.",
        category=SituationCategory.CYBER,
        subcategory="impersonation_harassment",
        urgency=Urgency.HIGH,
        location=None,
        entities=["Instagram account"],
        organizations_involved=["Instagram / Meta"],
        user_goal="Take down fake profile and stop cyber harassment",
        known_facts=[
            "Impersonation profile created using user's photo and full name",
            "Abusive messages sent to colleagues",
        ],
        user_claims=[
            "Impersonator is violating privacy and committing identity harassment",
        ],
        unknowns=[
            "Identity of impersonator",
        ],
        missing_information=[
            "Account handle URL",
            "Whether report was filed with Meta support",
        ],
        questions_to_ask=[
            "Have you reported the profile directly via Instagram's impersonation form?",
        ],
        recommended_research_types=["web", "local"],
    )

    mock_llm.structured_generate.return_value = expected_situation

    agent = SituationAgent(mock_llm)
    result = await agent.analyse(user_input)

    assert result.category == SituationCategory.CYBER
    assert result.urgency == Urgency.HIGH
