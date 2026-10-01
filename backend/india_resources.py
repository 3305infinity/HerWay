"""
India resource registry and source hierarchy.

Design rule
-----------
This module holds ONLY facts that are stable and attributable:

* Nationally-allocated short-code helplines (112, 181, 1091, 1098, 1930, 14567)
  — these are assigned by the Government of India and each entry records the
  official page it comes from.
* The list of Indian States and Union Territories.
* The ranking used to decide which kind of source to trust.

It deliberately does **not** hardcode:

* State helpline numbers (they change and vary by state),
* Any street address,
* Any office phone number,
* Opening hours.

Those must be discovered live through SerpApi against official sources. If a
resource cannot be verified, it is reported as unverified rather than invented.
"""

from __future__ import annotations

from enum import IntEnum
from typing import Dict, List, Optional

from pydantic import BaseModel, Field


# ---------------------------------------------------------------------------
# Source hierarchy (Section 4 of the reliability spec)
# ---------------------------------------------------------------------------

class SourceTier(IntEnum):
    """Priority order for conflicting information. Lower number wins."""

    GOVERNMENT_OF_INDIA = 1      # ministry / national portal (.gov.in, .nic.in)
    STATE_GOVERNMENT = 2         # state portal
    POLICE_LEGAL_SERVICES = 3    # police, cybercrime, legal services authority
    ESTABLISHED_NGO = 4          # registered support organisation
    REPUTABLE_NEWS = 5           # mainstream news outlet
    GENERAL_WEB = 6              # everything else — supplementary only


#: Domains whose authority we recognise directly.
_NATIONAL_GOV_DOMAINS = {
    "india.gov.in",
    "wcd.nic.in",
    "wcd.gov.in",
    "socialjustice.gov.in",
    "telemanas.mohfw.gov.in",
    "mohfw.gov.in",
    "ncw.nic.in",
    "ncwapps.nic.in",
    "shebox.wcd.gov.in",
    "shebox.nic.in",
    "cybercrime.gov.in",
    "nalsa.gov.in",
    "mha.gov.in",
    "meity.gov.in",
    "doj.gov.in",
    "indiacode.nic.in",
    "egazette.gov.in",
    "consumerhelpline.gov.in",
    "edaakhil.nic.in",
    "ncdrc.nic.in",
    "digitalpolice.gov.in",
    "112.gov.in",
}

_POLICE_LEGAL_KEYWORDS = (
    "police",
    "cybercrime",
    "cyber-crime",
    "legalservices",
    "legal-services",
    "nalsa",
    "slsa",
    "dlsa",
    "lokadalat",
    "judiciary",
    "courts",
)

_NEWS_DOMAINS = (
    "thehindu.com",
    "indianexpress.com",
    "hindustantimes.com",
    "timesofindia.indiatimes.com",
    "ndtv.com",
    "livemint.com",
    "scroll.in",
    "thewire.in",
    "bbc.com",
    "bbc.co.uk",
    "reuters.com",
    "pib.gov.in",
)

_KNOWN_NGO_DOMAINS = (
    "snehi.org",
    "aasraa.org",
    "icallhelpline.org",
    "sneha.org",
    "jagori.org",
    "majlislaw.com",
    "breakthrough.tv",
)


def classify_source_tier(domain: Optional[str]) -> SourceTier:
    """Map a domain onto the India-first source hierarchy.

    ``.nic.in`` is treated as government — most Indian ministry and district
    portals live there, and omitting it caused official sources such as
    ``edaakhil.nic.in`` to be scored as ordinary commercial websites.
    """
    if not domain:
        return SourceTier.GENERAL_WEB

    d = domain.lower().strip().replace("www.", "")

    if d in _NATIONAL_GOV_DOMAINS:
        return SourceTier.GOVERNMENT_OF_INDIA

    if any(kw in d for kw in _POLICE_LEGAL_KEYWORDS) and (
        d.endswith(".gov.in") or d.endswith(".nic.in") or d.endswith(".gov")
    ):
        return SourceTier.POLICE_LEGAL_SERVICES

    if d.endswith(".gov.in") or d.endswith(".nic.in"):
        # State subdomains such as `wcd.rajasthan.gov.in` or `mahilaayog.up.nic.in`
        return SourceTier.STATE_GOVERNMENT

    if d.endswith(".gov") or d.endswith(".mil"):
        return SourceTier.GOVERNMENT_OF_INDIA

    if any(kw in d for kw in _POLICE_LEGAL_KEYWORDS):
        return SourceTier.POLICE_LEGAL_SERVICES

    if any(d == n or d.endswith("." + n) for n in _NEWS_DOMAINS):
        return SourceTier.REPUTABLE_NEWS

    if any(d == n or d.endswith("." + n) for n in _KNOWN_NGO_DOMAINS):
        return SourceTier.ESTABLISHED_NGO

    if d.endswith(".ac.in") or d.endswith(".edu") or d.endswith(".edu.in"):
        return SourceTier.ESTABLISHED_NGO

    return SourceTier.GENERAL_WEB


#: Authority weight per tier, used by the SourceVerifier scoring formula.
TIER_AUTHORITY: Dict[SourceTier, float] = {
    SourceTier.GOVERNMENT_OF_INDIA: 0.95,
    SourceTier.STATE_GOVERNMENT: 0.90,
    SourceTier.POLICE_LEGAL_SERVICES: 0.88,
    SourceTier.ESTABLISHED_NGO: 0.72,
    SourceTier.REPUTABLE_NEWS: 0.62,
    SourceTier.GENERAL_WEB: 0.30,
}


# ---------------------------------------------------------------------------
# National helplines
# ---------------------------------------------------------------------------

class NationalHelpline(BaseModel):
    """A nationally-allocated helpline short code.

    Every entry carries ``official_source_url`` — the page a user (or we) can
    check it against. Nothing in this list is included without one.
    """

    id: str
    name: str
    number: str
    purpose: str
    official_source_url: str = Field(
        ..., description="Government page documenting this number"
    )
    operating_hours: str = "24x7"
    categories: List[str] = Field(default_factory=list)
    #: How a safety plan should group this resource in the UI.
    resource_category: str = "helpline"
    notes: Optional[str] = None


#: Short codes allocated nationally by the Government of India.  These are the
#: only contact details HerWay states without running a live search, because
#: they are statutory allocations rather than per-office details.
NATIONAL_HELPLINES: List[NationalHelpline] = [
    NationalHelpline(
        id="IN_ERSS_112",
        name="Emergency Response Support System (ERSS)",
        number="112",
        purpose="Single emergency number for police, fire and ambulance anywhere in India.",
        official_source_url="https://112.gov.in/",
        categories=[
            "domestic_violence",
            "safety",
            "threats",
            "stalking",
            "unsafe_relationship",
            "coercive_control",
            "other_women_safety",
        ],
        notes="Works from any phone. The ERSS mobile app also supports a panic button.",
    ),
    NationalHelpline(
        id="IN_WOMEN_181",
        name="Women Helpline (Universalisation of Women Helpline scheme)",
        number="181",
        purpose="24x7 support for women affected by violence, including referral to One Stop Centres.",
        official_source_url="https://wcd.gov.in/schemes/women-helpline-scheme",
        categories=[
            "domestic_violence",
            "sexual_harassment",
            "workplace_harassment",
            "safety",
            "unsafe_relationship",
            "coercive_control",
            "other_women_safety",
        ],
        notes="Run under the Ministry of Women and Child Development. Connects to local support.",
    ),
    NationalHelpline(
        id="IN_WOMEN_POLICE_1091",
        name="Women's Helpline (police)",
        number="1091",
        purpose="Police women's helpline for women in distress.",
        official_source_url="https://www.india.gov.in/spotlight/national-emergency-number-112",
        categories=["domestic_violence", "stalking", "threats", "safety", "other_women_safety"],
        notes="Availability can vary by state; 112 reaches police everywhere.",
    ),
    NationalHelpline(
        id="IN_CYBER_1930",
        name="National Cyber Crime Helpline",
        number="1930",
        purpose="Report cyber crime, including online harassment and financial fraud.",
        official_source_url="https://cybercrime.gov.in/",
        categories=["online_harassment", "cyber", "stalking", "financial", "threats"],
        resource_category="cyber_cell",
        notes="Complaints can also be filed online at cybercrime.gov.in.",
    ),
    NationalHelpline(
        id="IN_CHILD_1098",
        name="CHILDLINE",
        number="1098",
        purpose="Emergency help for children in need of care and protection.",
        official_source_url="https://wcd.gov.in/schemes/child-helpline-service",
        categories=["domestic_violence", "safety"],
        notes="Relevant when children are present in an unsafe home.",
    ),
    NationalHelpline(
        id="IN_SENIOR_14567",
        name="Elderline (National Helpline for Senior Citizens)",
        number="14567",
        purpose="Support for senior citizens facing abuse or neglect.",
        official_source_url="https://socialjustice.gov.in/",
        categories=["domestic_violence", "safety"],
    ),
    NationalHelpline(
        id="IN_TELEMANAS_14416",
        name="Tele-MANAS",
        number="14416",
        purpose="Free 24x7 mental health support in multiple Indian languages.",
        resource_category="counselling",
        official_source_url="https://telemanas.mohfw.gov.in/",
        categories=["health_information", "safety", "domestic_violence", "other_women_safety"],
        notes="Government mental-health counselling service, available in many languages.",
    ),
]


class OfficialPortal(BaseModel):
    """An official Government of India portal for a specific kind of action."""

    id: str
    name: str
    url: str
    purpose: str
    categories: List[str] = Field(default_factory=list)
    #: How a safety plan should group this resource in the UI.
    resource_category: str = "portal"


#: Primary complaint/filing portals. URLs only — no phone numbers or addresses,
#: which must be discovered live.
OFFICIAL_PORTALS: List[OfficialPortal] = [
    OfficialPortal(
        id="IN_PORTAL_CYBERCRIME",
        name="National Cyber Crime Reporting Portal",
        url="https://cybercrime.gov.in/",
        purpose="File a cyber crime complaint, including a dedicated flow for women and children.",
        categories=["online_harassment", "cyber", "stalking", "threats", "financial"],
        resource_category="cyber_cell",
    ),
    OfficialPortal(
        id="IN_PORTAL_SHEBOX",
        name="SHe-Box (Sexual Harassment electronic Box)",
        url="https://shebox.wcd.gov.in/",
        purpose="Central government portal for workplace sexual harassment complaints under the POSH Act.",
        categories=["workplace_harassment", "sexual_harassment"],
        resource_category="posh_icc",
    ),
    OfficialPortal(
        id="IN_PORTAL_NCW",
        name="National Commission for Women — complaint registration",
        url="https://ncw.nic.in/",
        purpose="Register a complaint with the statutory national commission for women.",
        categories=[
            "domestic_violence",
            "sexual_harassment",
            "workplace_harassment",
            "stalking",
            "other_women_safety",
        ],
    ),
    OfficialPortal(
        id="IN_PORTAL_NALSA",
        name="National Legal Services Authority (NALSA)",
        url="https://nalsa.gov.in/",
        purpose="Free legal aid. Women are entitled to free legal services under Section 12 of the Legal Services Authorities Act, 1987.",
        categories=[
            "domestic_violence",
            "sexual_harassment",
            "workplace_harassment",
            "legal_information",
            "housing",
            "financial",
        ],
        resource_category="legal_aid",
    ),
    OfficialPortal(
        id="IN_PORTAL_OSC",
        name="One Stop Centre (Sakhi) scheme",
        url="https://wcd.gov.in/schemes/one-stop-centre-scheme-1",
        purpose="Integrated support — medical, police, legal, psychosocial and temporary shelter — under one roof at district level.",
        categories=[
            "domestic_violence",
            "sexual_harassment",
            "safety",
            "unsafe_relationship",
            "other_women_safety",
        ],
        resource_category="one_stop_centre",
    ),
    OfficialPortal(
        id="IN_PORTAL_CONSUMER",
        name="National Consumer Helpline / E-Daakhil",
        url="https://consumerhelpline.gov.in/",
        purpose="Register a consumer complaint; E-Daakhil allows online filing with consumer commissions.",
        categories=["consumer", "financial", "travel"],
    ),
    OfficialPortal(
        id="IN_PORTAL_INDIACODE",
        name="India Code — central repository of Indian legislation",
        url="https://www.indiacode.nic.in/",
        purpose="Read the authoritative text of Indian Acts, including PWDVA 2005 and the POSH Act 2013.",
        categories=["legal_information"],
    ),
]


def helplines_for_category(category: str) -> List[NationalHelpline]:
    """Return the national helplines relevant to a situation category."""
    cat = (category or "").lower().strip()
    matched = [h for h in NATIONAL_HELPLINES if cat in h.categories]
    if not matched:
        # 112 is always correct for an emergency, whatever the category.
        matched = [h for h in NATIONAL_HELPLINES if h.id == "IN_ERSS_112"]
    return matched


def portals_for_category(category: str) -> List[OfficialPortal]:
    """Return the official portals relevant to a situation category."""
    cat = (category or "").lower().strip()
    return [p for p in OFFICIAL_PORTALS if cat in p.categories]


# ---------------------------------------------------------------------------
# States and Union Territories
# ---------------------------------------------------------------------------

#: Used for the location picker so users are never asked to free-type a state,
#: and so HerWay never assumes a default city.
INDIAN_STATES: List[str] = [
    "Andhra Pradesh",
    "Arunachal Pradesh",
    "Assam",
    "Bihar",
    "Chhattisgarh",
    "Goa",
    "Gujarat",
    "Haryana",
    "Himachal Pradesh",
    "Jharkhand",
    "Karnataka",
    "Kerala",
    "Madhya Pradesh",
    "Maharashtra",
    "Manipur",
    "Meghalaya",
    "Mizoram",
    "Nagaland",
    "Odisha",
    "Punjab",
    "Rajasthan",
    "Sikkim",
    "Tamil Nadu",
    "Telangana",
    "Tripura",
    "Uttar Pradesh",
    "Uttarakhand",
    "West Bengal",
]

INDIAN_UNION_TERRITORIES: List[str] = [
    "Andaman and Nicobar Islands",
    "Chandigarh",
    "Dadra and Nagar Haveli and Daman and Diu",
    "Delhi",
    "Jammu and Kashmir",
    "Ladakh",
    "Lakshadweep",
    "Puducherry",
]

ALL_INDIAN_REGIONS: List[str] = sorted(INDIAN_STATES + INDIAN_UNION_TERRITORIES)


def is_valid_indian_region(value: str) -> bool:
    """True if ``value`` names an Indian State or Union Territory."""
    return (value or "").strip().lower() in {r.lower() for r in ALL_INDIAN_REGIONS}


def normalise_pin_code(value: str) -> Optional[str]:
    """Return a 6-digit Indian PIN code if ``value`` contains one, else None."""
    digits = "".join(ch for ch in (value or "") if ch.isdigit())
    if len(digits) == 6 and digits[0] not in "0":
        return digits
    return None
