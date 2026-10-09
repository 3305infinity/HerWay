"""
Did this resource actually work?

HerWay can tell you a number came from an official page. It cannot tell you
whether anyone picks up, whether the office has moved, or whether the shelter
is still taking people. Only the women who tried can tell us that, and right
now that knowledge evaporates.

This records it — as **aggregate counts per resource**, nothing more.

The privacy constraint that shapes everything here
--------------------------------------------------
Feedback on "did this number work?" implies the person called it. A record
linking *this user* to *this women's shelter* is a disclosure of exactly the
kind this product exists to prevent, and it would be more sensitive than most
of what the app stores deliberately.

So no feedback record carries an owner. There is no ``user_id``, no session id,
no case id, no trace id, and no timestamp finer than a day. The stored document
is a counter attached to a resource, and it is not possible to work backwards
from it to a person — not by us, not by anyone who obtains the database.

The cost is that one person can vote repeatedly and we cannot tell. That is
accepted: light vote-stuffing on "is this number still live" is a far smaller
harm than a table linking survivors to the services they contacted. Rate
limiting on the route takes the edge off it.

What the counts are for
-----------------------
Surfacing "7 people said this number did not connect" next to a listing, and
eventually demoting dead resources. They are reports from the public, not
verification by us, and the API labels them that way.
"""

from __future__ import annotations

import hashlib
import logging
from datetime import datetime, timezone
from typing import Any, Dict, Optional

from backend.db import get_database
from backend.trace import log_fields

logger = logging.getLogger(__name__)

COLLECTION = "resource_feedback"

#: Outcomes a user can report. Deliberately about *reachability*, not quality —
#: "was this place good" invites a rating, and a rating next to a shelter would
#: become a safety verdict, which this product does not make.
OUTCOMES = {
    "worked": "Reached someone who could help",
    "no_answer": "Nobody answered",
    "wrong_number": "Number is wrong or disconnected",
    "moved": "Address or office has changed",
    "not_relevant": "Not the right kind of help",
}


def normalise_indian_phone(raw: str) -> str:
    """Reduce an Indian number to its 10 national digits.

    The same office is written `+91 98765 43210`, `098765-43210` and
    `9876543210` depending on who copied it from where. Stripping to digits is
    not enough — that leaves `919876543210`, `09876543210` and `9876543210` as
    three different strings, which would split one resource's reports across
    three counters and make the whole feature useless.

    Short codes (112, 181, 1091, 1930, 14416) are left alone: they are already
    canonical and are not 10 digits.

    Numbers that do not look Indian are returned as their digits, unmodified —
    a resource listed with an international number should not be mangled into
    something else.
    """
    digits = "".join(ch for ch in (raw or "") if ch.isdigit())
    if not digits:
        return ""

    # Short codes and anything under 10 digits is already canonical.
    if len(digits) <= 9:
        return digits

    # +91XXXXXXXXXX / 0091XXXXXXXXXX
    if len(digits) == 12 and digits.startswith("91"):
        return digits[2:]
    if len(digits) == 14 and digits.startswith("0091"):
        return digits[4:]
    # 0XXXXXXXXXX — domestic trunk prefix
    if len(digits) == 11 and digits.startswith("0"):
        return digits[1:]

    return digits


def resource_key(*, phone: Optional[str] = None, url: Optional[str] = None,
                 name: Optional[str] = None) -> Optional[str]:
    """A stable id for a resource, derived from what identifies it.

    Hashed so the stored key does not itself read as a directory of women's
    shelters with phone numbers. Prefers phone, then URL, then name — the first
    two are stable, a name is not.
    """
    basis = None
    if phone and phone.strip():
        normalised = normalise_indian_phone(phone)
        if normalised:
            basis = "tel:" + normalised
    if basis is None and url and url.strip():
        basis = "url:" + url.strip().lower().rstrip("/")
    if basis is None and name and name.strip():
        basis = "name:" + " ".join(name.lower().split())

    if not basis:
        return None
    return hashlib.sha256(basis.encode("utf-8")).hexdigest()[:32]


class ResourceFeedbackStore:
    """Aggregate counters per resource. No owner, by design."""

    def __init__(self, db: Any = None) -> None:
        self._db = db if db is not None else get_database()

    def record(self, key: str, outcome: str) -> Dict[str, Any]:
        """Increment one counter.

        ``$inc`` on a single document rather than inserting an event row: an
        event log would carry an arrival order, and arrival order plus
        timestamps is enough to correlate a report with a session. A counter
        cannot be de-anonymised that way.
        """
        if outcome not in OUTCOMES:
            raise ValueError(f"Unknown outcome: {outcome}")

        collection = self._db[COLLECTION]
        # Day granularity only — enough to age out stale reports, too coarse to
        # place someone at a time.
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")

        existing = collection.find_one({"_id": key})
        if existing is None:
            doc = {
                "_id": key,
                "counts": {o: 0 for o in OUTCOMES},
                "first_seen": today,
                "last_seen": today,
            }
            doc["counts"][outcome] = 1
            collection.insert_one(doc)
        else:
            counts = dict(existing.get("counts") or {})
            counts[outcome] = int(counts.get(outcome, 0)) + 1
            collection.update_one(
                {"_id": key},
                {"$set": {"counts": counts, "last_seen": today}},
            )

        # Outcome only. Never the key — it identifies the resource, and a log
        # line pairing a resource with a request is the correlation this module
        # exists to avoid.
        logger.info("Resource feedback recorded %s", log_fields(outcome=outcome))
        return self.summary(key)

    def summary(self, key: str) -> Dict[str, Any]:
        """Counts for one resource, with a plain-language reading."""
        doc = self._db[COLLECTION].find_one({"_id": key})
        counts = dict((doc or {}).get("counts") or {})
        total = sum(int(v) for v in counts.values())

        return {
            "reports": total,
            "counts": {o: int(counts.get(o, 0)) for o in OUTCOMES},
            "last_seen": (doc or {}).get("last_seen"),
            # Stated so no caller mistakes these for verification by HerWay.
            "is_community_reported": True,
            "note": (
                "Reported by people who tried this resource. HerWay has not "
                "re-checked it."
            ),
        }

    def summaries(self, keys: list[str]) -> Dict[str, Dict[str, Any]]:
        """Counts for several resources, for rendering a list in one call."""
        return {key: self.summary(key) for key in keys if key}
