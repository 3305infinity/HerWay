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
        expected_engines=["google", "google_maps"],
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
            ("Karnataka State Commission for Women office Bengaluru", "maps",
             "Locate the body that takes a complaint outside the employer",
             "An address and phone number that can be confirmed by calling"),
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
    DemoScenario(
        id="domestic_violence_exit",
        title="Planning to leave safely",
        summary=(
            "Where a One Stop Centre actually is, what a protection order under "
            "PWDVA 2005 involves, and what to arrange before leaving."
        ),
        situation_text=(
            "Things at home have been getting worse for about a year. My husband "
            "shouts and has pushed me twice, and last month he took my phone away "
            "for a week. I have a four year old. I do not have my own income and "
            "my parents are not in this city. I have started thinking about "
            "leaving but I do not know where I would go, what papers I should "
            "take, or whether anyone would help me."
        ),
        category="domestic_violence",
        location="Lucknow, Uttar Pradesh",
        demonstrates=[
            "One Stop Centre located by district, not a national average",
            "PWDVA 2005 protection orders explained from the statute",
            "Shelter options surfaced with their provenance",
            "No step suggests confronting him",
        ],
        expected_engines=["google_maps", "google"],
        urgency_hint="high",
        fallback_searches=[
            ("One Stop Centre Sakhi Lucknow", "maps",
             "Find the nearest integrated support centre",
             "Address and contact for a Sakhi centre in the district"),
            ("PWDVA 2005 protection order procedure", "web",
             "Understand what a protection order is and how it is obtained",
             "The statutory route and who grants the order"),
            ("181 women helpline official India", "web",
             "Confirm the current helpline from an official page",
             "A number traceable to a government source"),
            ("women shelter home Lucknow", "maps",
             "Identify somewhere to go if leaving becomes urgent",
             "Shelter homes and their published contact details"),
        ],
    ),
    DemoScenario(
        id="stalking_ex",
        title="An ex-partner who will not stop",
        summary=(
            "What stalking is under the Bharatiya Nyaya Sanhita, where the "
            "women's police desk is, and how to report impersonation accounts."
        ),
        situation_text=(
            "My ex keeps turning up where I am. He waits outside my office some "
            "evenings and he has made two fake accounts to message me after I "
            "blocked him. He has not hurt me but I have started changing my route "
            "home and I do not sleep properly. People tell me it is not serious "
            "enough to report. I want to know if it actually is, and what I can do."
        ),
        category="stalking",
        location="Hyderabad, Telangana",
        demonstrates=[
            "Statutory definition retrieved, not recalled",
            "Women's police desk located in the city",
            "Reporting route for impersonation accounts",
            "Recent reporting on local enforcement, with dates",
        ],
        expected_engines=["google", "google_maps", "google_news"],
        urgency_hint="high",
        fallback_searches=[
            ("stalking section Bharatiya Nyaya Sanhita punishment", "web",
             "Establish how stalking is defined and treated in law",
             "The section, what it covers and the penalty"),
            ("women police station Hyderabad", "maps",
             "Find the women's police desk in the city",
             "Addresses and contact numbers"),
            ("cybercrime.gov.in fake account harassment", "web",
             "Find the route for reporting impersonation accounts",
             "The official portal and what reporting involves"),
            ("Hyderabad SHE Teams stalking news", "news",
             "See how this is being handled locally",
             "Recent coverage of enforcement, with dates where available"),
        ],
    ),
    DemoScenario(
        id="fir_refused",
        title="The police would not register my complaint",
        summary=(
            "Zero FIR, what to do when a station refuses, and where free legal "
            "aid is available in the district."
        ),
        situation_text=(
            "I went to the police station to file a complaint and they told me to "
            "go to a different station because it did not happen in their area. I "
            "went back the next day and they said they would look into it but did "
            "not write anything down. I do not have money for a lawyer. I want to "
            "know whether they are allowed to refuse and what I can do next."
        ),
        category="legal_information",
        location="Jaipur, Rajasthan",
        demonstrates=[
            "Zero FIR explained from a source, with the link",
            "Escalation route when a station refuses",
            "Free legal aid eligibility under NALSA",
            "District Legal Services Authority located",
        ],
        expected_engines=["google", "google_maps"],
        urgency_hint="medium",
        fallback_searches=[
            ("Zero FIR police refuse to register complaint", "web",
             "Establish whether a station may refuse and what Zero FIR means",
             "The rule and where it comes from"),
            ("district legal services authority Jaipur", "maps",
             "Find where free legal aid is available locally",
             "DLSA office address and contact"),
            ("NALSA free legal aid women eligibility", "web",
             "Check who qualifies for free legal aid",
             "Eligibility criteria from an official page"),
            ("SP complaint procedure refusal FIR", "web",
             "Find the escalation route above the station",
             "How to complain to a senior officer"),
        ],
    ),
    DemoScenario(
        id="campus_harassment",
        title="Harassment at college",
        summary=(
            "UGC regulations on sexual harassment in higher education, the "
            "internal committee route, and where a complaint goes."
        ),
        situation_text=(
            "A faculty member in my department keeps asking me to stay back after "
            "class and comments on how I dress. He is on the panel for my project "
            "evaluation. Other girls have said similar things about him but nobody "
            "wants to be the one to complain. I do not know who I would even go to, "
            "or whether it would affect my marks."
        ),
        category="campus_safety",
        location="Chennai, Tamil Nadu",
        demonstrates=[
            "UGC regulations retrieved from source",
            "The internal committee route in a college",
            "SHe-Box as an online reporting option",
            "State helpline confirmed from an official page",
        ],
        expected_engines=["google", "google_maps"],
        urgency_hint="medium",
        fallback_searches=[
            ("UGC regulations prevention of sexual harassment higher education", "web",
             "Establish what a college is required to have in place",
             "The regulations and the committee they mandate"),
            ("SHe-Box complaint", "web",
             "Find the online complaint route",
             "The portal and what a complaint involves"),
            ("women helpline Tamil Nadu official", "web",
             "Confirm the state helpline from an official page",
             "A number traceable to a government source"),
            ("women police station Chennai Tamil Nadu", "maps",
             "Locate the nearest women's police desk",
             "An address and phone number that can be confirmed by calling"),
        ],
    ),
    DemoScenario(
        id="dowry_pressure",
        title="Demands from my in-laws",
        summary=(
            "The Dowry Prohibition Act, family counselling options nearby, and "
            "free legal aid in the district."
        ),
        situation_text=(
            "My in-laws keep bringing up what my family did not give at the "
            "wedding. It started as comments and now my mother-in-law says I "
            "should ask my father for money for a car. My husband does not stop "
            "her. My parents cannot afford it and I do not want to ask them. I "
            "want to understand whether this is something I can act on."
        ),
        category="domestic_violence",
        location="Patna, Bihar",
        demonstrates=[
            "The Dowry Prohibition Act 1961 retrieved from source",
            "Family counselling centres located in the district",
            "Free legal aid through the local DLSA",
            "Recent reporting for context, clearly dated",
        ],
        expected_engines=["google", "google_maps", "google_news"],
        urgency_hint="medium",
        fallback_searches=[
            ("Dowry Prohibition Act 1961", "web",
             "Establish what the law says about dowry demands",
             "The Act and what it prohibits"),
            ("family counselling centre Patna women", "maps",
             "Find counselling support locally",
             "Centres and their published contact details"),
            ("district legal services authority Patna", "maps",
             "Find where free legal aid is available",
             "DLSA office address and contact"),
            ("dowry harassment cases Bihar news", "news",
             "See how such cases are being reported locally",
             "Recent coverage, with dates where available"),
        ],
    ),
    DemoScenario(
        id="new_city_housing",
        title="Moving to a new city alone",
        summary=(
            "Working women's hostels, what has been reported about the city, and "
            "the local police helpline — before committing to anything."
        ),
        situation_text=(
            "I have a job offer in a city where I do not know anyone and I have to "
            "decide in two weeks. I will be living alone for the first time. I want "
            "to know what accommodation options exist for women, what the area is "
            "like, and what I should set up before I move so that I am not working "
            "it all out afterwards."
        ),
        category="safety_planning",
        location="Bengaluru, Karnataka",
        demonstrates=[
            "Accommodation options surfaced with provenance",
            "Recent local reporting, clearly dated",
            "Police helpline confirmed from an official page",
            "Planning support with nothing wrong yet",
        ],
        expected_engines=["google_maps", "google_news", "google"],
        urgency_hint="low",
        fallback_searches=[
            ("working women hostel Bengaluru", "maps",
             "Find accommodation intended for women living alone",
             "Hostels and their published contact details"),
            ("Bengaluru women safety news", "news",
             "See what has recently been reported about the city",
             "Recent coverage, with dates where available"),
            ("Bengaluru police women helpline Suraksha", "web",
             "Confirm the local police helpline from an official page",
             "A number traceable to an official source"),
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
