"""
Demonstration scenarios.

One read-only endpoint listing the written scenarios in
``backend.demo_scenarios``. There is deliberately **no** "run demo" endpoint:
running a scenario means posting its text to ``POST /api/v2/cases`` like any
other case, so the pipeline a reviewer watches is the real one rather than a
demonstration path that only resembles it.

Public and unauthenticated, because the scenarios are static prose with no user
content in them. Creating a case from one still requires a session, and that
case is owned and scoped exactly like any other.
"""

from __future__ import annotations

from typing import Any, Dict

from fastapi import APIRouter

from backend.demo_scenarios import list_scenarios

router = APIRouter(prefix="/api/v2/demo", tags=["demo"])


@router.get("/scenarios")
async def demo_scenarios() -> Dict[str, Any]:
    """The runnable demonstration scenarios."""
    scenarios = list_scenarios()
    return {
        "scenarios": scenarios,
        "count": len(scenarios),
        "how_it_works": (
            "Picking a scenario fills the ordinary situation box with its text "
            "and submits it like any other case. Everything after that is the "
            "real pipeline — the same situation analysis, research planning and "
            "live search a user gets."
        ),
        "notice": (
            "These are fictional situations written for demonstration. None "
            "describes a real person or a real incident. Cases created from "
            "them are labelled DEMO and can be deleted like any other case."
        ),
    }
