"""
Local intelligence tests (Phase 3, Tasks 2–5 / Task 8.4–8.13).

Covers the resource resolver, place research, review summarisation, news
evidence handling and evidence-aware comparison.

**All mocked.** The SerpApi provider is a stand-in throughout; no billable call
is made here. Live verification is reported separately in the Phase 3 report.

The recurring assertion across this file is a negative one: that nothing in
this layer ever tells a user a place is safe.
"""

from __future__ import annotations

import time
from unittest.mock import AsyncMock, MagicMock

import pytest

from backend.models.research import (
    ResourceVerification,
    SearchFailureReason,
    SearchOutcome,
    SearchResult,
)
from backend.services.place_research import (
    AreaReportSummary,
    PlaceResearchService,
    classify_claim,
    compare_options,
    summarise_reviews,
)
from backend.services.resource_resolver import (
    ResolutionOutcome,
    ResourceCategory,
    ResourceResolver,
    infer_category,
    wants_local_discovery,
)
from backend.trace import get_trace_id, trace_context


def _serpapi(results=None, *, success=True, failure=SearchFailureReason.NONE):
    serp = MagicMock()
    serp.search_detailed = AsyncMock(
        return_value=SearchOutcome(
            vertical="maps",
            query="q",
            success=success,
            failure_reason=failure,
            results=results if results is not None else [],
        )
    )
    return serp


def _listing(title="Ruby Hall Clinic", **kw):
    base = dict(
        title=title,
        url="https://example.gov.in/x",
        snippet="A hospital",
        address="Sassoon Road, Pune",
        phone="020-00000000",
        rating=4.1,
        reviews=120,
    )
    base.update(kw)
    return SearchResult(**base)


# ===========================================================================
# Trigger conditions — do not search when the user is not asking for a place
# ===========================================================================

@pytest.mark.parametrize(
    "text",
    [
        "is there a pharmacy near me",
        "where is the nearest hospital",
        "find a chemist in Baner",
        "how do I get to the railway station",
        "closest police station",
        "women police station in Nagpur",
        "any clinic around here",
        "address of the One Stop Centre",
    ],
)
def test_local_intent_detected(text):
    assert wants_local_discovery(text)


@pytest.mark.parametrize(
    "text",
    [
        "",
        "help me write a complaint letter",
        "draft a message to my manager",
        "what does POSH Act mean",
        "explain my rights under PWDVA",
        "translate this into Hindi",
        "summarise what we discussed",
        "I feel really low today",
        "what is a One Stop Centre",
    ],
)
def test_no_local_search_for_unrelated_requests(text):
    """Each false positive here is a wasted paid call and a worse answer."""
    assert not wants_local_discovery(text)


@pytest.mark.parametrize(
    "text,expected",
    [
        ("nearest chemist", ResourceCategory.PHARMACY),
        ("emergency hospital near me", ResourceCategory.HOSPITAL),
        ("women police station nearby", ResourceCategory.WOMEN_POLICE),
        ("police station in Pune", ResourceCategory.POLICE),
        ("one stop centre sakhi", ResourceCategory.ONE_STOP_CENTRE),
        ("legal aid dlsa office", ResourceCategory.LEGAL_AID),
        ("working women hostel", ResourceCategory.ACCOMMODATION),
        ("nearest atm", ResourceCategory.ATM),
    ],
)
def test_category_inference(text, expected):
    assert infer_category(text) == expected


def test_more_specific_category_wins():
    """'women police station' must not degrade to the generic police category."""
    assert infer_category("women police station") == ResourceCategory.WOMEN_POLICE


# ===========================================================================
# Resolver
# ===========================================================================

@pytest.mark.asyncio
async def test_resolve_normalises_results():
    resolver = ResourceResolver(_serpapi([_listing()]))
    outcome = await resolver.resolve(ResourceCategory.HOSPITAL, "Pune")

    assert outcome.success
    assert len(outcome.resources) == 1
    resource = outcome.resources[0]
    assert resource.name == "Ruby Hall Clinic"
    assert resource.address == "Sassoon Road, Pune"
    assert resource.rating == 4.1
    assert resource.retrieved_at > 0


@pytest.mark.asyncio
async def test_missing_fields_are_absent_not_invented():
    """A listing with no phone must report no phone, not a plausible one."""
    bare = SearchResult(title="Unnamed Clinic", snippet="")
    outcome = await ResourceResolver(_serpapi([bare])).resolve(
        ResourceCategory.CLINIC, "Pune"
    )
    resource = outcome.resources[0]
    assert resource.phone is None
    assert resource.address is None
    assert resource.rating is None
    assert resource.review_count is None


@pytest.mark.asyncio
async def test_malformed_provider_result_does_not_raise():
    """Provider shape varies by engine; a missing attribute must not 500.

    ``model_construct`` deliberately skips validation so the resolver receives
    an object with fields genuinely absent — which is what a real engine
    sometimes hands back.
    """
    partial = SearchOutcome.model_construct(
        vertical="maps",
        query="q",
        success=True,
        failure_reason=SearchFailureReason.NONE,
        results=[type("Weird", (), {"title": "Odd Listing"})()],
    )
    serp = MagicMock()
    serp.search_detailed = AsyncMock(return_value=partial)

    outcome = await ResourceResolver(serp).resolve(ResourceCategory.OTHER, "Pune")
    assert outcome.success
    assert outcome.resources[0].name == "Odd Listing"
    assert outcome.resources[0].phone is None


@pytest.mark.asyncio
async def test_provider_failure_is_not_reported_as_no_results():
    """The distinction this whole type exists for."""
    resolver = ResourceResolver(
        _serpapi([], success=False, failure=SearchFailureReason.RATE_LIMITED)
    )
    outcome = await resolver.resolve(ResourceCategory.HOSPITAL, "Pune")

    assert outcome.success is False
    assert outcome.found_nothing is False, (
        "a failed lookup must never read as 'there are no hospitals'"
    )
    assert outcome.failure_reason == "rate_limited"


@pytest.mark.asyncio
async def test_genuine_empty_result_is_distinguishable():
    outcome = await ResourceResolver(_serpapi([])).resolve(ResourceCategory.HOSPITAL, "Pune")
    assert outcome.success is True
    assert outcome.found_nothing is True


@pytest.mark.asyncio
async def test_provider_exception_is_caught():
    serp = MagicMock()
    serp.search_detailed = AsyncMock(side_effect=RuntimeError("network down"))
    outcome = await ResourceResolver(serp).resolve(ResourceCategory.HOSPITAL, "Pune")
    assert outcome.success is False
    assert outcome.found_nothing is False


@pytest.mark.asyncio
async def test_missing_location_is_refused_rather_than_guessed():
    outcome = await ResourceResolver(_serpapi([_listing()])).resolve(
        ResourceCategory.HOSPITAL, None
    )
    assert outcome.success is False
    assert outcome.failure_reason == "location_required"


@pytest.mark.asyncio
async def test_resolver_never_claims_a_place_is_open_or_safe():
    outcome = await ResourceResolver(_serpapi([_listing()])).resolve(
        ResourceCategory.HOSPITAL, "Pune"
    )
    payload = outcome.to_dict()
    assert payload["resources"][0]["open_now_known"] is False
    assert "do not confirm" in payload["disclaimer"].lower()
    assert "safe" not in str(payload["resources"][0]).lower().replace("safety", "")


@pytest.mark.asyncio
async def test_resolver_propagates_the_trace_id():
    with trace_context("local-trace-0001"):
        outcome = await ResourceResolver(_serpapi([_listing()])).resolve(
            ResourceCategory.HOSPITAL, "Pune"
        )
    assert outcome.trace_id == "local-trace-0001"


@pytest.mark.asyncio
async def test_resolve_from_text_skips_non_local_requests():
    serp = _serpapi([_listing()])
    result = await ResourceResolver(serp).resolve_from_text(
        "help me draft a complaint", "Pune"
    )
    assert result is None
    serp.search_detailed.assert_not_awaited(), "no provider call for a writing request"


@pytest.mark.asyncio
async def test_resolve_from_text_runs_for_a_local_request():
    outcome = await ResourceResolver(_serpapi([_listing()])).resolve_from_text(
        "nearest pharmacy", "Pune"
    )
    assert outcome is not None
    assert outcome.category == ResourceCategory.PHARMACY


@pytest.mark.asyncio
async def test_only_one_provider_call_per_resolution():
    """Do not invoke every engine for every request."""
    serp = _serpapi([_listing()])
    await ResourceResolver(serp).resolve(ResourceCategory.HOSPITAL, "Pune")
    assert serp.search_detailed.await_count == 1


# ===========================================================================
# Review summarisation
# ===========================================================================

def test_themes_are_grouped_with_evidence():
    summary = summarise_reviews(
        [
            "The staff were rude and the wait was long",
            "Very clean facility but expensive",
            "Staff helpful, quick service",
        ]
    )
    themes = {t.theme for t in summary.themes}
    assert "staff_conduct" in themes
    assert all(t.examples for t in summary.themes), "every theme needs its evidence"


def test_both_positive_and_negative_evidence_survive():
    summary = summarise_reviews(
        ["staff were rude", "staff were helpful and polite"]
    )
    staff = next(t for t in summary.themes if t.theme == "staff_conduct")
    joined = " ".join(staff.examples).lower()
    assert "rude" in joined and "helpful" in joined


def test_no_reviews_is_stated_not_hidden():
    summary = summarise_reviews([])
    assert summary.themes == []
    assert any("no review text" in lim.lower() for lim in summary.limitations)


def test_duplicate_content_is_flagged_not_counted_as_corroboration():
    """Repeated copied text is one source, not several agreeing."""
    summary = summarise_reviews(["Great place to visit"] * 4)
    assert summary.possible_duplicate_content is True
    assert any("republished" in lim or "near-identical" in lim for lim in summary.limitations)


def test_distinct_reviews_are_not_flagged_as_duplicates():
    summary = summarise_reviews(
        ["clean and tidy", "staff were rude", "quite expensive here"]
    )
    assert summary.possible_duplicate_content is False


def test_review_coverage_limitation_is_explicit():
    summary = summarise_reviews(["clean"], provider_review_count=5000)
    assert any("5000" in lim for lim in summary.limitations)


def test_security_mentions_are_not_a_safety_verdict():
    """The sharpest line in this module."""
    summary = summarise_reviews(
        ["security guard present at night", "felt unsafe in the parking area"]
    )
    payload = summary.to_dict()
    assert payload["is_not_a_safety_assessment"] is True
    assert any("does not establish" in lim for lim in summary.limitations)
    # No field anywhere that could be read as a verdict.
    assert "safety_score" not in payload
    assert "is_safe" not in payload


def test_summary_has_no_overall_score_field():
    payload = summarise_reviews(["clean", "rude staff"]).to_dict()
    for forbidden in ("score", "verdict", "rank", "safe_rating"):
        assert forbidden not in payload


# ===========================================================================
# News evidence
# ===========================================================================

@pytest.mark.parametrize(
    "text,expected",
    [
        ("Man allegedly assaulted woman near station", "allegation"),
        ("Police said the investigation is ongoing", "official_statement"),
        ("Three arrested after incident in market", "reported_incident"),
        ("New flyover opens next month", "unclear"),
    ],
)
def test_claim_classification(text, expected):
    assert classify_claim(text) == expected


def test_allegation_wins_over_incident_wording():
    """Presenting an allegation as established fact is the costlier error."""
    assert classify_claim("Man allegedly arrested after alleged assault") == "allegation"


@pytest.mark.asyncio
async def test_area_reports_preserve_source_metadata():
    article = SearchResult(
        title="Report about the area",
        url="https://news.example.com/a",
        source="Example News",
        published_at="2026-09-01",
        snippet="Police said an investigation is ongoing",
    )
    serp = MagicMock()
    serp.search_detailed = AsyncMock(
        return_value=SearchOutcome(vertical="news", query="q", success=True, results=[article])
    )

    summary = await PlaceResearchService(serp).area_reports("Kothrud, Pune")
    got = summary.articles[0]
    assert got.url == "https://news.example.com/a"
    assert got.source == "Example News"
    assert got.published_at == "2026-09-01"
    assert got.claim_type == "official_statement"


@pytest.mark.asyncio
async def test_undated_articles_are_flagged():
    undated = SearchResult(title="No date here", url="https://x.com/a", snippet="s")
    serp = MagicMock()
    serp.search_detailed = AsyncMock(
        return_value=SearchOutcome(vertical="news", query="q", success=True, results=[undated])
    )
    summary = await PlaceResearchService(serp).area_reports("Pune")
    assert any("no publication date" in lim for lim in summary.limitations)


@pytest.mark.asyncio
async def test_area_reports_refuse_to_imply_a_crime_rate():
    serp = MagicMock()
    serp.search_detailed = AsyncMock(
        return_value=SearchOutcome(vertical="news", query="q", success=True, results=[])
    )
    payload = (await PlaceResearchService(serp).area_reports("Pune")).to_dict()
    assert payload["cannot_infer_crime_rate"] is True
    assert payload["absence_of_results_is_not_safety"] is True


@pytest.mark.asyncio
async def test_news_failure_is_reported_as_failure():
    serp = MagicMock()
    serp.search_detailed = AsyncMock(
        return_value=SearchOutcome(
            vertical="news", query="q", success=False,
            failure_reason=SearchFailureReason.TIMEOUT, results=[],
        )
    )
    summary = await PlaceResearchService(serp).area_reports("Pune")
    assert summary.success is False
    assert summary.failure_reason == "timeout"


# ===========================================================================
# Place research
# ===========================================================================

@pytest.mark.asyncio
async def test_place_profile_is_built_from_the_listing():
    serp = MagicMock()
    serp.search_detailed = AsyncMock(
        return_value=SearchOutcome(
            vertical="maps", query="q", success=True,
            results=[_listing(), _listing(title="Other", snippet="clean and tidy")],
        )
    )
    profile = await PlaceResearchService(serp).research_place("Ruby Hall Clinic", "Pune")

    assert profile.success
    assert profile.listing["name"] == "Ruby Hall Clinic"
    assert profile.listing["open_now_known"] is False
    assert profile.reviews is not None
    assert profile.sources


@pytest.mark.asyncio
async def test_place_not_found_is_not_a_failure():
    serp = MagicMock()
    serp.search_detailed = AsyncMock(
        return_value=SearchOutcome(vertical="maps", query="q", success=True, results=[])
    )
    profile = await PlaceResearchService(serp).research_place("Nonexistent Place", "Pune")
    assert profile.success is True
    assert profile.listing is None


@pytest.mark.asyncio
async def test_place_lookup_failure_is_reported():
    serp = MagicMock()
    serp.search_detailed = AsyncMock(
        return_value=SearchOutcome(
            vertical="maps", query="q", success=False,
            failure_reason=SearchFailureReason.NETWORK_ERROR, results=[],
        )
    )
    profile = await PlaceResearchService(serp).research_place("Somewhere", "Pune")
    assert profile.success is False
    assert profile.listing is None


@pytest.mark.asyncio
async def test_empty_place_name_is_refused_without_a_provider_call():
    serp = _serpapi([_listing()])
    profile = await PlaceResearchService(serp).research_place("   ", "Pune")
    assert profile.success is False
    serp.search_detailed.assert_not_awaited()


# ===========================================================================
# Comparison
# ===========================================================================

def _option(name, **kw):
    base = dict(name=name, rating=None, review_count=None, address=None,
                phone=None, hours_text=None, verification=None, source_domain=None)
    base.update(kw)
    return base


def test_comparison_only_includes_available_fields():
    result = compare_options(
        [_option("A", rating=4.0), _option("B", rating=3.5)]
    )
    assert "rating" in result.fields_compared
    assert "hours_text" not in result.fields_compared, "an all-empty row is noise"


def test_comparison_labels_missing_data_explicitly():
    result = compare_options([_option("A", rating=4.0), _option("B")])
    cell = result.table["rating"]["B"]
    assert cell.available is False
    assert cell.value is None
    assert "not published" in cell.note.lower()


def test_comparison_is_useful_with_incomplete_data():
    """An option with nothing published still appears, with its gaps named."""
    result = compare_options([_option("A", rating=4.0, phone="123"), _option("Sparse")])
    assert "Sparse" in result.option_names
    assert any("Sparse" in note for note in result.notes)


def test_comparison_has_no_overall_ranking():
    payload = compare_options([_option("A", rating=4.9), _option("B", rating=2.0)]).to_dict()
    assert payload["has_overall_ranking"] is False
    for forbidden in ("best", "recommended", "winner", "safest", "safety_score"):
        assert forbidden not in payload


def test_comparison_does_not_reorder_by_rating():
    """Higher rated must not silently become 'first choice'."""
    result = compare_options([_option("Low", rating=2.0), _option("High", rating=4.9)])
    assert result.option_names == ["Low", "High"], "input order must be preserved"


def test_user_priorities_reorder_fields_but_do_not_score():
    result = compare_options(
        [_option("A", rating=4.0, phone="1"), _option("B", rating=3.0, phone="2")],
        priorities=["phone"],
    )
    assert result.fields_compared[0] == "phone"
    assert result.user_priorities == ["phone"]
    assert result.to_dict()["has_overall_ranking"] is False


def test_rating_is_labelled_as_not_safety():
    result = compare_options([_option("A", rating=4.0)])
    assert any("not a measure of personal safety" in n for n in result.notes)


def test_empty_option_list_is_handled():
    result = compare_options([])
    assert result.option_names == []
    assert any("no options" in n.lower() for n in result.notes)


def test_comparison_explains_its_basis():
    payload = compare_options([_option("A", rating=4.0)]).to_dict()
    assert "only on fields the sources actually provided" in payload["basis"]


def test_comparison_is_deterministic():
    options = [_option("A", rating=4.0), _option("B", phone="123")]
    assert compare_options(options).to_dict()["table"] == compare_options(options).to_dict()["table"]
