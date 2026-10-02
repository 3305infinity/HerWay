"""
Persistence for Safety Center records.

Goes through ``backend.db.get_database()`` — the same abstraction every other
collection uses — rather than opening its own client. That matters for an
honest reason as much as a tidy one: ``get_database`` falls back to an
**in-memory store** when MongoDB is unreachable, and routing through it means
the Safety Center inherits exactly the same persistence guarantees as cases,
including the loud warning and the production refusal.

**Persistence is unverified.** No MongoDB was reachable in the environment where
this was written, so every test below ran against the in-memory fallback. A
plan created there is lost on restart. The code is written against the real
PyMongo API and the production guard in ``db.py`` refuses the fallback when
``HERWAY_ENV=production``, but "the tests pass" is not evidence that data
survives a restart in production. See docs/PHASE4_IMPLEMENTATION_REPORT.md.

Ownership
---------
Every method takes an ``owner_id`` and filters on it. There is deliberately no
"get by id" that omits the owner — a function that can return another person's
safety plan is one call site away from leaking it.
"""

from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from backend.db import get_database
from backend.models.safety_center import (
    CheckIn,
    CheckInStatus,
    PlanStatus,
    SafetyCenterPlan,
    TrustedContact,
)
from backend.trace import log_fields

logger = logging.getLogger(__name__)

PLANS = "safety_plans"
CONTACTS = "trusted_contacts"
CHECKINS = "check_ins"


def _new_id() -> str:
    return uuid.uuid4().hex


def _now() -> datetime:
    return datetime.now(timezone.utc)


class SafetyCenterRepository:
    """CRUD for plans, contacts and check-ins, always scoped to one owner."""

    def __init__(self, db: Any = None) -> None:
        self._db = db if db is not None else get_database()

    # -- plans -------------------------------------------------------------

    def create_plan(self, owner_id: str, plan: SafetyCenterPlan) -> SafetyCenterPlan:
        doc = plan.model_dump(mode="json")
        doc["_id"] = plan.id
        doc["owner_id"] = owner_id
        self._db[PLANS].insert_one(doc)
        # Counts only — never the title, purpose, steps or locations.
        logger.info(
            "SafetyCenter: plan created %s",
            log_fields(steps=len(plan.steps), has_case_link=bool(plan.case_id)),
        )
        return plan

    def get_plan(self, owner_id: str, plan_id: str) -> Optional[SafetyCenterPlan]:
        doc = self._db[PLANS].find_one({"_id": plan_id, "owner_id": owner_id})
        return SafetyCenterPlan.model_validate(_clean(doc)) if doc else None

    def list_plans(
        self, owner_id: str, include_archived: bool = False
    ) -> List[SafetyCenterPlan]:
        query: Dict[str, Any] = {"owner_id": owner_id}
        docs = list(self._db[PLANS].find(query))
        plans = [SafetyCenterPlan.model_validate(_clean(d)) for d in docs]
        if not include_archived:
            plans = [p for p in plans if p.status is not PlanStatus.ARCHIVED]
        return sorted(plans, key=lambda p: p.updated_at, reverse=True)

    def save_plan(self, owner_id: str, plan: SafetyCenterPlan) -> SafetyCenterPlan:
        plan.updated_at = _now()
        doc = plan.model_dump(mode="json")
        doc["owner_id"] = owner_id
        self._db[PLANS].update_one({"_id": plan.id, "owner_id": owner_id}, {"$set": doc})
        return plan

    def delete_plan(self, owner_id: str, plan_id: str) -> bool:
        """Hard delete. A user deleting a safety plan means delete it."""
        result = self._db[PLANS].delete_one({"_id": plan_id, "owner_id": owner_id})
        return getattr(result, "deleted_count", 0) > 0

    # -- contacts ----------------------------------------------------------

    def create_contact(self, owner_id: str, contact: TrustedContact) -> TrustedContact:
        doc = contact.model_dump(mode="json")
        doc["_id"] = contact.id
        doc["owner_id"] = owner_id
        self._db[CONTACTS].insert_one(doc)
        # Never the name, number or relationship.
        logger.info("SafetyCenter: contact created %s", log_fields(method=contact.method.value))
        return contact

    def get_contact(self, owner_id: str, contact_id: str) -> Optional[TrustedContact]:
        doc = self._db[CONTACTS].find_one({"_id": contact_id, "owner_id": owner_id})
        return TrustedContact.model_validate(_clean(doc)) if doc else None

    def list_contacts(self, owner_id: str) -> List[TrustedContact]:
        docs = list(self._db[CONTACTS].find({"owner_id": owner_id}))
        return [TrustedContact.model_validate(_clean(d)) for d in docs]

    def save_contact(self, owner_id: str, contact: TrustedContact) -> TrustedContact:
        contact.updated_at = _now()
        doc = contact.model_dump(mode="json")
        doc["owner_id"] = owner_id
        self._db[CONTACTS].update_one(
            {"_id": contact.id, "owner_id": owner_id}, {"$set": doc}
        )
        return contact

    def delete_contact(self, owner_id: str, contact_id: str) -> bool:
        """Delete a contact and detach it from every plan that referenced it.

        Leaving a dangling id behind would mean a deleted contact still appeared
        in a plan's contact list, which is both confusing and a retention
        failure.
        """
        result = self._db[CONTACTS].delete_one({"_id": contact_id, "owner_id": owner_id})
        deleted = getattr(result, "deleted_count", 0) > 0
        if deleted:
            for plan in self.list_plans(owner_id, include_archived=True):
                if contact_id in plan.contact_ids:
                    plan.contact_ids = [c for c in plan.contact_ids if c != contact_id]
                    self.save_plan(owner_id, plan)
        return deleted

    # -- check-ins ---------------------------------------------------------

    def create_check_in(self, owner_id: str, check_in: CheckIn) -> CheckIn:
        doc = check_in.model_dump(mode="json")
        doc["_id"] = check_in.id
        doc["owner_id"] = owner_id
        self._db[CHECKINS].insert_one(doc)
        logger.info(
            "SafetyCenter: check-in started %s",
            log_fields(
                has_expected_time=bool(check_in.expected_back_at),
                has_contact=bool(check_in.contact_id),
            ),
        )
        return check_in

    def get_check_in(self, owner_id: str, check_in_id: str) -> Optional[CheckIn]:
        doc = self._db[CHECKINS].find_one({"_id": check_in_id, "owner_id": owner_id})
        return CheckIn.model_validate(_clean(doc)) if doc else None

    def list_check_ins(self, owner_id: str, limit: int = 50) -> List[CheckIn]:
        docs = list(self._db[CHECKINS].find({"owner_id": owner_id}))
        check_ins = [CheckIn.model_validate(_clean(d)) for d in docs]
        return sorted(check_ins, key=lambda c: c.started_at, reverse=True)[:limit]

    def active_check_in(self, owner_id: str) -> Optional[CheckIn]:
        for check_in in self.list_check_ins(owner_id):
            if check_in.status is CheckInStatus.ACTIVE:
                return check_in
        return None

    def save_check_in(self, owner_id: str, check_in: CheckIn) -> CheckIn:
        doc = check_in.model_dump(mode="json")
        doc["owner_id"] = owner_id
        self._db[CHECKINS].update_one(
            {"_id": check_in.id, "owner_id": owner_id}, {"$set": doc}
        )
        return check_in

    def delete_check_in(self, owner_id: str, check_in_id: str) -> bool:
        result = self._db[CHECKINS].delete_one({"_id": check_in_id, "owner_id": owner_id})
        return getattr(result, "deleted_count", 0) > 0

    def delete_all_for_owner(self, owner_id: str) -> Dict[str, int]:
        """Remove everything this owner stored. Used by "delete my data".

        Returns per-collection counts so the UI can tell the user exactly what
        was removed rather than claiming a vague success.
        """
        counts = {}
        for name in (PLANS, CONTACTS, CHECKINS):
            docs = list(self._db[name].find({"owner_id": owner_id}))
            for doc in docs:
                self._db[name].delete_one({"_id": doc["_id"], "owner_id": owner_id})
            counts[name] = len(docs)
        return counts


def _clean(doc: Dict[str, Any]) -> Dict[str, Any]:
    """Map a stored document onto model fields.

    ``_id`` is the record id; the model calls it ``id``.
    """
    data = dict(doc)
    if "_id" in data:
        data.setdefault("id", str(data.pop("_id")))
    return data


def new_id() -> str:
    return _new_id()
