"""
Demonstration scenarios.

What these are
--------------
Four written situations a judge, reviewer or new user can run through the
**real** pipeline in one click. They are not a mock dashboard: picking one
fills the ordinary intake box with its text and submits it through
``POST /api/v2/cases`` like any other case, so what follows is genuine
situation analysis, genuine research planning and — when SerpApi is
configured — genuine live search.

What they are **not**
---------------------
- **Not real incidents.** Every scenario is fictional and written for
  demonstration. None describes a real person or a real event, and the UI says
  so. Inventing a plausible-sounding real incident on a domestic-violence
  product would be indefensible.
- **Not seeded into storage.** Nothing here is written to the database at
  import time or on startup. A scenario becomes a case only when a user
  deliberately runs it, under their own session, and deleting that case removes
  it completely.
- **Not a separate code path.** There is no demo renderer and no demo API. The
  scenario supplies text; everything after that is the product.

Honesty about results
---------------------
``expected_engines`` describes which SerpApi engines the planner is *likely* to
choose for this situation, so a reviewer knows what to watch for. It is a
prediction, not a promise — the planner decides at run time, and the research
trail shows what actually ran.

If SerpApi is unavailable the run still completes and reports the outage; it
does not fall back to pretending. Snapshots, where present, are labelled as
illustrative and carry the date they were captured.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


@dataclass(frozen=True)
class DemoScenario:
    """One runnable demonstration situation."""

    id: str
    title: str
    #: One line explaining what this scenario demonstrates.
    summary: str
    #: The text that goes into the intake box. Written as a person would write
    #: it — plain, uneven, no legal vocabulary — because that is what the
    #: situation agent has to cope with in reality.
    situation_text: str
    category: str
    #: Free-text location, only where the scenario genuinely needs one. Local
    #: search is skipped without it, which is correct behaviour to show.
    location: Optional[str] = None
    #: What a reviewer should look for in the research trail.
    demonstrates: List[str] = field(default_factory=list)
    #: Engines the planner is *likely* to pick. A prediction, not a guarantee.
    expected_engines: List[str] = field(default_factory=list)
    #: Roughly how urgent this reads. Used only to order the list; the real
    #: urgency comes from safety_triage at run time.
    urgency_hint: str = "medium"
    #: Pre-written searches, used **only** when the LLM planner is unavailable.
    #:
    #: Research planning is an LLM call, so an exhausted Gemini quota meant a
    #: scenario could not get past planning and the walkthrough died at the
    #: first step. These let it continue: the *plan* is pre-written, but the
    #: searches that follow are the ordinary live SerpApi calls, returning real
    #: results with real links and real timestamps.
    #:
    #: Nothing here is a saved result. Only the question is scripted; the
    #: answer is still retrieved. The plan is labelled `scripted` so the UI can
    #: say so rather than implying an agent chose these.
    #:
    #: Each entry: (query, vertical, purpose, expected_information)
    fallback_searches: List[tuple] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "title": self.title,
            "summary": self.summary,
            "situation_text": self.situation_text,
            "category": self.category,
            "location": self.location,
            "demonstrates": self.demonstrates,
            "expected_engines": self.expected_engines,
            "urgency_hint": self.urgency_hint,
            # Repeated on every scenario so no consumer can render one without
            # the label travelling with it.
            "is_demo": True,
            "disclaimer": (
                "A fictional scenario written for demonstration. It does not "
                "describe a real person or a real incident."
            ),
        }


SCENARIOS: List[DemoScenario] = [
    DemoScenario(
        id="late_night_travel",
        title="Travelling home late, alone",
        summary=(
            "Location-aware research: public places that stay open, transport "
            "options, and precautions for a route — without ever claiming a "
            "route is safe."
        ),
        situation_text=(
            "I finish work around 11pm and have to get from Hinjewadi to Kothrud "
            "in Pune. It is about 40 minutes and part of the road is quiet with "
            "not many shops open. I usually book a cab but last week the driver "
            "took a different turn than the map showed and I did not know what "
            "to do. I would like to know what is open along the way, what my "
            "options are if something feels wrong, and what I should set up "
            "before I leave."
        ),
        category="unsafe_travel",
        location="Pune, Maharashtra",
        demonstrates=[
            "Google Maps search for places that are actually open late",
            "Transport options near the route",
            "A safety plan built around a specific journey",
            "Explicit refusal to call the route itself safe or unsafe",
        ],
        expected_engines=["google_maps", "google"],
        urgency_hint="medium",
        fallback_searches=[
            ("women police station Pune", "maps",
             "Find the nearest women's police help in the area",
             "Addresses and phone numbers for women's police desks"),
            ("24 hour pharmacy Kothrud Pune", "maps",
             "Identify places that are actually open late along the route",
             "Somewhere lit and staffed to stop at if needed"),
            ("women safety helpline Maharashtra official", "web",
             "Confirm the current state helpline from an official page",
             "A helpline number traceable to a government source"),
        ],
    ),
    DemoScenario(
        id="workplace_harassment",
        title="A manager who will not stop",
        summary=(
            "Legal-information research under the POSH Act 2013: what an "
            "Internal Committee is, what a complaint involves, and what to "
            "document — sourced, not recalled."
        ),
        situation_text=(
            "My reporting manager keeps making comments about how I look and "
            "messages me on WhatsApp late at night about things that are not "
            "work. It has been going on for about three months. Last week he "
            "said my appraisal depends on whether I am friendly with him. I "
            "have screenshots of some messages. I do not want to leave this "
            "job and I do not know if going to HR will make it worse. I want "
            "to understand what my options actually are."
        ),
        category="workplace_harassment",
        location="Bengaluru, Karnataka",
        demonstrates=[
            "Targeted search of the POSH Act 2013 and Internal Committee process",
            "Preference for .gov.in and .nic.in sources, scored by authority",
            "Documentation steps that carry an 'only if it is safe' caveat",
            "Legal information clearly separated from legal advice",
        ],
        expected_engines=["google"],
        urgency_hint="medium",
        fallback_searches=[
            ("POSH Act 2013 internal committee complaint procedure", "web",
             "Establish the statutory complaint route",
             "How a complaint is filed and who receives it"),
            ("SHe-Box online complaint sexual harassment workplace", "web",
             "Find the government portal for workplace complaints",
             "The official online reporting route"),
            ("POSH Act 2013 timeline complaint 90 days", "web",
             "Check the statutory time limits",
             "How long a complainant has, and what the committee must do"),
        ],
    ),
    DemoScenario(
        id="online_blackmail",
        title="Threatening messages and blackmail",
        summary=(
            "Urgency classification, evidence-preservation guidance, and the "
            "live cyber-crime reporting route — without asking anyone to "
            "upload real evidence."
        ),
        situation_text=(
            "Someone I met online has photos of me and is saying he will send "
            "them to my family if I do not keep talking to him. He has started "
            "messaging from new numbers when I block him. I am scared and I do "
            "not know whether telling anyone will make it worse. I want to know "
            "what I should save, who I can report this to, and whether there is "
            "anything I can do tonight."
        ),
        category="online_harassment",
        demonstrates=[
            "Conservative urgency handling — escalation signals are caught",
            "Evidence preservation guidance before anything is deleted",
            "Current cyber-crime reporting routes, retrieved not remembered",
            "No request to upload real evidence to run the demo",
        ],
        expected_engines=["google"],
        urgency_hint="high",
        fallback_searches=[
            ("cybercrime.gov.in report online harassment blackmail", "web",
             "Find the national cyber crime reporting route",
             "The official portal and what reporting involves"),
            ("1930 cyber crime helpline India official", "web",
             "Confirm the current cyber crime helpline",
             "A number traceable to an official page"),
            ("preserve evidence screenshots cyber crime complaint India", "web",
             "Find guidance on what to keep before anything is deleted",
             "What form of evidence is accepted and how to keep it"),
        ],
    ),
    DemoScenario(
        id="unfamiliar_area",
        title="An area I do not know",
        summary=(
            "News and local research about a place, with contradiction "
            "handling and an explicit refusal to infer a crime rate from a "
            "handful of search results."
        ),
        situation_text=(
            "I have been offered a paying guest accommodation in an area of "
            "Delhi I have never been to, and I need to decide this week. I do "
            "not know anyone who lives there. I would like to know what has "
            "been reported about the area recently, what is nearby in terms of "
            "transport and a hospital, and what I should check before I agree."
        ),
        category="local_discovery",
        location="Delhi",
        demonstrates=[
            "Google News for recent public reporting, with dates where available",
            "Google Maps for transport and facilities nearby",
            "Claims labelled allegation / reported incident / official statement",
            "Explicit statement that absence of bad news is not evidence of safety",
        ],
        expected_engines=["google_news", "google_maps", "google"],
        urgency_hint="low",
        fallback_searches=[
            ("Delhi neighbourhood safety news", "news",
             "See what has recently been reported about the area",
             "Recent coverage, with dates where available"),
            ("hospital Delhi", "maps",
             "Check what medical help is nearby",
             "Hospitals and clinics within reach"),
            ("metro station Delhi", "maps",
             "Check transport options from the area",
             "Nearest stations and connections"),
        ],
    ),
]

SCENARIOS_BY_ID: Dict[str, DemoScenario] = {s.id: s for s in SCENARIOS}


def list_scenarios() -> List[Dict[str, Any]]:
    return [s.to_dict() for s in SCENARIOS]


def get_scenario(scenario_id: str) -> Optional[DemoScenario]:
    return SCENARIOS_BY_ID.get(scenario_id)


#: Marks an example case's title so it stays identifiable in the database and
#: in any export, not only in the UI that created it.
#:
#: Deliberately "Example" rather than "[DEMO]": the distinction that matters is
#: *this is not something you wrote*, which "Example" says just as clearly
#: without making a working product read as demo-ware. The machine-readable
#: `is_demo` flag is what code should branch on; this is for humans reading a
#: title out of context.
DEMO_TITLE_PREFIX = "Example:"


def demo_title(scenario: DemoScenario) -> str:
    return f"{DEMO_TITLE_PREFIX} {scenario.title}"


def is_demo_case(case: Dict[str, Any]) -> bool:
    """Whether a stored case came from a demo scenario.

    Checks the persisted flag first and falls back to the title prefix, so a
    case created before the flag existed is still identifiable.
    """
    if case.get("is_demo") is True:
        return True
    return str(case.get("title") or "").startswith(DEMO_TITLE_PREFIX)


def scripted_research_plan(scenario: DemoScenario, case_id: str):
    """A research plan from a scenario's pre-written searches.

    Used only when the LLM planner is unavailable and the case is an example.
    The returned plan is an ordinary ``ResearchPlan`` and is executed by the
    ordinary orchestrator, so every search is a real, live SerpApi call —
    nothing here is a saved result.

    ``plan_origin="scripted"`` marks it so the research trail can say the
    questions were written in advance rather than chosen by an agent.
    """
    from backend.models.research import ResearchPlan, ResearchTask, SearchVertical

    vertical_map = {
        "web": SearchVertical.WEB,
        "news": SearchVertical.NEWS,
        "maps": SearchVertical.MAPS,
    }

    tasks = [
        ResearchTask(
            task_id=f"TASK_{index + 1:02d}",
            query=query,
            vertical=vertical_map.get(vertical, SearchVertical.WEB),
            purpose=purpose,
            expected_information=expected,
            location=scenario.location,
        )
        for index, (query, vertical, purpose, expected) in enumerate(
            scenario.fallback_searches
        )
    ]

    return ResearchPlan(
        case_id=case_id,
        reasoning=(
            "Planned from a written example because the research planner was "
            "unavailable. The searches below ran live."
        ),
        tasks=tasks,
        search_budget=max(len(tasks), 1),
        plan_origin="scripted",
    )


def situation_from_scenario(scenario: DemoScenario, situation_text: str):
    """A ``Situation`` for an example case when the model is unavailable.

    Built only from what is already known — the scenario's own declared
    category and location, the user-visible text, and deterministic triage from
    ``safety_triage``. **No facts are invented.** ``known_facts`` is left empty
    rather than filled with plausible-looking extractions, because asserting
    that someone stated something they did not is exactly the failure this
    product is built to avoid.

    ``case_summary`` is the scenario's own one-line description, not a
    generated paraphrase, so nothing here claims to be model output.
    """
    from backend.models.research import Situation, SituationCategory
    from backend.safety_triage import apply_triage_to_text

    try:
        category = SituationCategory(scenario.category)
    except ValueError:
        category = SituationCategory.OTHER

    situation = Situation(
        case_summary=scenario.summary,
        category=category,
        user_goal="Understand the options and what to do next",
        location=scenario.location,
        # Deliberately empty. A stand-in must not put words in anyone's mouth.
        known_facts=[],
        user_claims=[],
        unknowns=[
            "Detailed analysis was unavailable, so this is based on the "
            "example's own description rather than a reading of the text."
        ],
        recommended_research_types=scenario.expected_engines,
    )

    # Real triage — regex over the actual text, no model. Urgency can only be
    # raised here, never lowered.
    return apply_triage_to_text(situation, situation_text)
