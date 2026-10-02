"""
Place research and evidence-aware comparison.

Scope and the one line it will not cross
----------------------------------------
This module helps a user *understand options*: what a place is, what people say
about it, what has been reported about an area, and how a few candidates differ
on the facts a provider actually supplied.

It will not tell anyone a place is safe. Search results cannot establish that.
A venue with four stars and two hundred reviews can be dangerous for a woman
alone at night; a venue with no reviews can be perfectly fine. Concretely, this
module:

- never computes a safety score, and has no field that could be mistaken for one,
- never ranks options "safest first",
- never converts review sentiment into a safety verdict,
- never reads an absence of negative news as evidence of safety,
- keeps service quality ("slow staff") separate from personal safety.

What it reuses
--------------
``SerpApiService`` (shared cache, retries, failure taxonomy) and
``ResourceResolver``. It adds no new search pipeline and no second orchestrator.
"""

from __future__ import annotations

import logging
import re
import time
from collections import Counter
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Sequence

from backend.models.research import SearchFailureReason, SearchResult, SearchVertical
from backend.trace import get_trace_id, log_fields

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Review themes
# ---------------------------------------------------------------------------
# Deterministic keyword grouping, not sentiment analysis. The point is to show
# the user *what people keep mentioning* with the evidence attached, so they can
# judge it — not to produce a verdict for them.
#
# `security_mentions` is deliberately named for what it is: that a review
# mentioned the topic. It is never evidence that a place is or is not safe.

_THEME_KEYWORDS: Dict[str, List[str]] = {
    "cleanliness": ["clean", "dirty", "hygiene", "filthy", "tidy", "unclean"],
    "staff_conduct": ["staff", "rude", "polite", "helpful", "behaviour", "behavior", "service"],
    "waiting_time": ["wait", "queue", "slow", "quick", "delay", "prompt"],
    "cost": ["expensive", "cheap", "affordable", "price", "overcharge", "costly"],
    "accessibility": ["wheelchair", "ramp", "accessible", "lift", "elevator", "stairs"],
    "crowding": ["crowded", "busy", "packed", "empty", "rush"],
    "lighting": ["lighting", "lit", "dark", "bright"],
    "security_mentions": ["security", "guard", "cctv", "unsafe", "safe", "harass"],
    "facilities": ["parking", "washroom", "toilet", "restroom", "wifi", "ac "],
}


@dataclass
class ReviewTheme:
    """A topic reviewers kept raising, with the evidence that supports it."""

    theme: str
    mention_count: int
    #: Verbatim fragments. Quoting rather than paraphrasing keeps the user able
    #: to judge the source for themselves.
    examples: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "theme": self.theme,
            "mention_count": self.mention_count,
            "examples": self.examples[:3],
        }


@dataclass
class ReviewSummary:
    """What the available review text supports — and what it does not."""

    themes: List[ReviewTheme] = field(default_factory=list)
    total_reviews_seen: int = 0
    #: Provider-reported aggregate count, which is usually far larger than the
    #: number of reviews we actually read.
    provider_review_count: Optional[int] = None
    average_rating: Optional[float] = None
    limitations: List[str] = field(default_factory=list)
    #: True when several results carry near-identical text, which usually means
    #: one source syndicated — not independent corroboration.
    possible_duplicate_content: bool = False

    def to_dict(self) -> Dict[str, Any]:
        return {
            "themes": [t.to_dict() for t in self.themes],
            "total_reviews_seen": self.total_reviews_seen,
            "provider_review_count": self.provider_review_count,
            "average_rating": self.average_rating,
            "limitations": self.limitations,
            "possible_duplicate_content": self.possible_duplicate_content,
            "is_not_a_safety_assessment": True,
        }


def _normalise_for_dup(text: str) -> str:
    return " ".join(re.sub(r"[^\w\s]", " ", (text or "").lower()).split())


def summarise_reviews(
    snippets: Sequence[str],
    *,
    provider_review_count: Optional[int] = None,
    average_rating: Optional[float] = None,
) -> ReviewSummary:
    """Group review text into recurring themes, with limitations stated.

    Deterministic: the same input always produces the same output, which makes
    it testable and keeps it working when the LLM is unavailable.
    """
    texts = [s for s in snippets if s and s.strip()]
    summary = ReviewSummary(
        total_reviews_seen=len(texts),
        provider_review_count=provider_review_count,
        average_rating=average_rating,
    )

    if not texts:
        summary.limitations.append(
            "No review text was available, so nothing here is based on what "
            "visitors actually said."
        )
        return summary

    # Near-duplicate detection. Repeated copies of one description are a single
    # source, and treating them as several would manufacture confidence.
    normalised = [_normalise_for_dup(t) for t in texts]
    counts = Counter(normalised)
    summary.possible_duplicate_content = any(c > 1 for c in counts.values())

    for theme, keywords in _THEME_KEYWORDS.items():
        examples: List[str] = []
        for text in texts:
            lowered = text.lower()
            if any(keyword in lowered for keyword in keywords):
                examples.append(text.strip()[:200])
        if examples:
            summary.themes.append(
                ReviewTheme(theme=theme, mention_count=len(examples), examples=examples)
            )

    summary.themes.sort(key=lambda t: t.mention_count, reverse=True)

    # Limitations are part of the result, not a footnote.
    summary.limitations.append(
        f"Based on {len(texts)} snippet(s) visible in search results"
        + (
            f", out of {provider_review_count} reviews the provider reports."
            if provider_review_count
            else "."
        )
    )
    summary.limitations.append(
        "Reviews are opinions, not verified facts, and the people who post them "
        "are not a representative sample."
    )
    if summary.possible_duplicate_content:
        summary.limitations.append(
            "Some entries repeat near-identical wording, which usually means one "
            "source was republished rather than several people agreeing."
        )
    if any(t.theme == "security_mentions" for t in summary.themes):
        summary.limitations.append(
            "Some reviews mention security or safety. That records what a "
            "reviewer wrote; it does not establish whether this place is safe "
            "for you. Only you can weigh that, with current local knowledge."
        )
    return summary


# ---------------------------------------------------------------------------
# News and public reports
# ---------------------------------------------------------------------------

@dataclass
class NewsEvidence:
    """One article, with its claim status kept explicit."""

    title: str
    url: Optional[str]
    source: Optional[str]
    published_at: Optional[str]
    snippet: str
    #: allegation | reported_incident | official_statement | unclear
    claim_type: str = "unclear"

    def to_dict(self) -> Dict[str, Any]:
        return {
            "title": self.title,
            "url": self.url,
            "source": self.source,
            "published_at": self.published_at,
            "snippet": self.snippet,
            "claim_type": self.claim_type,
        }


_ALLEGATION_RE = re.compile(
    r"\balleged|allegation|accus(ed|ation)|claim(s|ed)?\b", re.IGNORECASE
)
_OFFICIAL_RE = re.compile(
    r"\b(police (said|say|stated)|official|ministry|government|court (said|ruled)|"
    r"fir (registered|filed)|commission)\b",
    re.IGNORECASE,
)
_INCIDENT_RE = re.compile(
    r"\b(arrest(ed)?|incident|attack(ed)?|assault(ed)?|robbery|theft|accident|"
    r"complaint (filed|registered))\b",
    re.IGNORECASE,
)


def classify_claim(text: str) -> str:
    """Label a headline/snippet as allegation, incident, official or unclear.

    Ordered most-cautious first: wording that marks something as *alleged* wins
    over wording that would otherwise read as an established event, because
    presenting an allegation as a fact is the more damaging error.
    """
    blob = text or ""
    if _ALLEGATION_RE.search(blob):
        return "allegation"
    if _OFFICIAL_RE.search(blob):
        return "official_statement"
    if _INCIDENT_RE.search(blob):
        return "reported_incident"
    return "unclear"


@dataclass
class AreaReportSummary:
    """News about an area, with the inference limits made loud."""

    articles: List[NewsEvidence] = field(default_factory=list)
    success: bool = True
    failure_reason: str = SearchFailureReason.NONE.value
    limitations: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "articles": [a.to_dict() for a in self.articles],
            "success": self.success,
            "failure_reason": self.failure_reason,
            "limitations": self.limitations,
            "cannot_infer_crime_rate": True,
            "absence_of_results_is_not_safety": True,
        }


# ---------------------------------------------------------------------------
# Comparison
# ---------------------------------------------------------------------------

#: Fields a user may compare on. No "safety" field exists here by design.
COMPARABLE_FIELDS = (
    "rating",
    "review_count",
    "address",
    "phone",
    "hours_text",
    "verification",
    "source_domain",
    "distance_text",
    "price_level",
)


@dataclass
class ComparisonCell:
    """One field for one option: the value, or an explicit absence."""

    value: Any = None
    available: bool = False
    note: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {"value": self.value, "available": self.available, "note": self.note}


@dataclass
class ComparisonResult:
    """A side-by-side table with no overall winner.

    There is deliberately no ``best`` or ``recommended`` field. The user states
    what matters to them; this presents the evidence against those fields and
    stops. Picking for them would require a judgement the data cannot support.
    """

    option_names: List[str] = field(default_factory=list)
    fields_compared: List[str] = field(default_factory=list)
    table: Dict[str, Dict[str, ComparisonCell]] = field(default_factory=dict)
    user_priorities: List[str] = field(default_factory=list)
    notes: List[str] = field(default_factory=list)
    retrieved_at: float = field(default_factory=time.time)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "option_names": self.option_names,
            "fields_compared": self.fields_compared,
            "table": {
                fname: {opt: cell.to_dict() for opt, cell in row.items()}
                for fname, row in self.table.items()
            },
            "user_priorities": self.user_priorities,
            "notes": self.notes,
            "retrieved_at": self.retrieved_at,
            "has_overall_ranking": False,
            "basis": (
                "Compared only on fields the sources actually provided. Blank "
                "cells mean the information was not available, not that the "
                "option lacks it."
            ),
        }


def compare_options(
    options: Sequence[Dict[str, Any]],
    *,
    priorities: Optional[Sequence[str]] = None,
    fields: Optional[Sequence[str]] = None,
) -> ComparisonResult:
    """Build a deterministic comparison table.

    ``options`` are dicts (typically ``ResolvedResource.to_dict()``).
    ``priorities`` is what the *user* said matters; it reorders the table and is
    echoed back, but it never collapses into a single score.

    Works with incomplete data: an option missing every comparable field still
    appears, with its gaps labelled, because knowing a listing has no published
    phone number is itself useful.
    """
    result = ComparisonResult(
        user_priorities=list(priorities or []),
    )
    if not options:
        result.notes.append("No options were supplied to compare.")
        return result

    result.option_names = [
        str(opt.get("name") or f"Option {i + 1}") for i, opt in enumerate(options)
    ]

    candidate_fields = list(fields or COMPARABLE_FIELDS)
    # A field is worth a row only if at least one option has it — an entirely
    # empty row is noise.
    present_fields = [
        f for f in candidate_fields if any(opt.get(f) not in (None, "", []) for opt in options)
    ]

    # User priorities float to the top; everything else keeps its declared order.
    if priorities:
        ordered = [f for f in priorities if f in present_fields]
        ordered += [f for f in present_fields if f not in ordered]
        present_fields = ordered

    result.fields_compared = present_fields

    for fname in present_fields:
        row: Dict[str, ComparisonCell] = {}
        for name, opt in zip(result.option_names, options):
            raw = opt.get(fname)
            if raw in (None, "", []):
                row[name] = ComparisonCell(
                    value=None, available=False, note="Not published by the source"
                )
            else:
                row[name] = ComparisonCell(value=raw, available=True)
        result.table[fname] = row

    missing_everything = [
        name
        for name, opt in zip(result.option_names, options)
        if all(opt.get(f) in (None, "", []) for f in present_fields)
    ]
    if missing_everything:
        result.notes.append(
            "No comparable details were published for: " + ", ".join(missing_everything)
        )

    if any("rating" == f for f in present_fields):
        result.notes.append(
            "Ratings reflect general customer experience. They are not a measure "
            "of personal safety."
        )

    result.notes.append(
        "This comparison does not rank the options. Which one suits you depends "
        "on what matters to you and on local knowledge the sources do not have."
    )
    return result


# ---------------------------------------------------------------------------
# Service
# ---------------------------------------------------------------------------

@dataclass
class PlaceProfile:
    """Everything gathered about one named place."""

    name: str
    listing: Optional[Dict[str, Any]] = None
    reviews: Optional[ReviewSummary] = None
    success: bool = True
    failure_reason: str = SearchFailureReason.NONE.value
    sources: List[str] = field(default_factory=list)
    trace_id: Optional[str] = None
    retrieved_at: float = field(default_factory=time.time)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "listing": self.listing,
            "reviews": self.reviews.to_dict() if self.reviews else None,
            "success": self.success,
            "failure_reason": self.failure_reason,
            "sources": self.sources,
            "trace_id": self.trace_id,
            "retrieved_at": self.retrieved_at,
        }


class PlaceResearchService:
    """Research a named place, or public reports about an area.

    Thin on purpose: it composes ``SerpApiService`` calls and the deterministic
    helpers above. It owns no pipeline of its own.
    """

    def __init__(self, serpapi) -> None:
        self._serpapi = serpapi

    async def research_place(
        self, name: str, location: Optional[str] = None, *, case_id: Optional[str] = None
    ) -> PlaceProfile:
        """Look up one named place and summarise what is published about it."""
        trace_id = get_trace_id()
        if not name or not name.strip():
            return PlaceProfile(
                name=name or "",
                success=False,
                failure_reason="name_required",
                trace_id=trace_id,
            )

        query = " ".join(f"{name} {location or ''}".split())[:160]
        logger.info(
            "PlaceResearch: looking up a place %s",
            log_fields(has_location=bool(location), query_chars=len(query)),
        )

        try:
            outcome = await self._serpapi.search_detailed(
                query=query,
                vertical=SearchVertical.MAPS,
                location=location,
                case_id=case_id,
                reason="Place lookup",
            )
        except Exception as exc:
            return PlaceProfile(
                name=name,
                success=False,
                failure_reason=SearchFailureReason.UPSTREAM_ERROR.value,
                trace_id=trace_id,
            )

        if not outcome.success:
            return PlaceProfile(
                name=name,
                success=False,
                failure_reason=outcome.failure_reason.value,
                trace_id=trace_id,
            )

        results: List[SearchResult] = list(outcome.results or [])
        if not results:
            return PlaceProfile(name=name, success=True, trace_id=trace_id)

        top = results[0]
        listing = {
            "name": top.title,
            "address": top.address,
            "phone": top.phone,
            "url": top.url,
            "rating": top.rating,
            "review_count": top.reviews,
            "source_domain": top.domain or top.source,
            # Stated, not inferred: the provider does not tell us this.
            "open_now_known": False,
        }

        reviews = summarise_reviews(
            [r.snippet for r in results],
            provider_review_count=top.reviews,
            average_rating=top.rating,
        )

        return PlaceProfile(
            name=name,
            listing=listing,
            reviews=reviews,
            success=True,
            sources=[r.url for r in results[:5] if r.url],
            trace_id=trace_id,
        )

    async def area_reports(
        self, area: str, *, case_id: Optional[str] = None, max_articles: int = 5
    ) -> AreaReportSummary:
        """Recent public reporting about an area.

        The limitations attached to the result are not decoration: a handful of
        news hits cannot establish a crime rate, and no hits cannot establish
        safety. Both statements travel with the data.
        """
        summary = AreaReportSummary()
        if not area or not area.strip():
            summary.success = False
            summary.failure_reason = "area_required"
            return summary

        try:
            outcome = await self._serpapi.search_detailed(
                query=f"{area} news reports",
                vertical=SearchVertical.NEWS,
                case_id=case_id,
                reason="Public reports about an area",
            )
        except Exception:
            summary.success = False
            summary.failure_reason = SearchFailureReason.UPSTREAM_ERROR.value
            return summary

        if not outcome.success:
            summary.success = False
            summary.failure_reason = outcome.failure_reason.value
            summary.limitations.append(
                "The news lookup did not complete, so nothing below is a "
                "complete picture of what has been reported."
            )
            return summary

        for result in (outcome.results or [])[:max_articles]:
            summary.articles.append(
                NewsEvidence(
                    title=result.title,
                    url=result.url,
                    source=result.source or result.domain,
                    # Only a real date field is used. A relative string like
                    # "2 days ago" is kept verbatim rather than converted into
                    # a date we would be guessing at.
                    published_at=result.published_at,
                    snippet=result.snippet or "",
                    claim_type=classify_claim(f"{result.title} {result.snippet}"),
                )
            )

        undated = sum(1 for a in summary.articles if not a.published_at)
        summary.limitations.append(
            f"{len(summary.articles)} article(s) found in a single search. This is "
            "not a survey of everything published about this area."
        )
        if undated:
            summary.limitations.append(
                f"{undated} of these carry no publication date, so their recency "
                "is unknown."
            )
        summary.limitations.append(
            "News coverage reflects what was reported, not how common something "
            "is. It cannot be used to work out a crime rate, and finding nothing "
            "does not mean an area is safe."
        )
        return summary
