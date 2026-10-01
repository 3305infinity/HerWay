"""
Abuse controls for public endpoints.

The Phase 1 audit found twelve unauthenticated legacy endpoints, five of which
invoke a paid LLM. With no limit in place, one visitor could exhaust the Gemini
quota for every real user — in a product where the people who need it most may
be trying to reach help in a hurry, that is a safety problem, not just a billing
one.

Authentication is deliberately *not* the answer for most of these. The community
pages are anonymous on purpose: a woman reading other women's experiences, or
posting her own, must not have to create an account first. So the control here
is a per-caller request budget rather than a login wall.

What this is not
----------------
This is an in-process, in-memory limiter. It is honest about its limits:

- **Per worker.** With N uvicorn workers a caller gets roughly N times the
  budget. Documented in docs/KNOWN_ISSUES.md as A-05 alongside the SerpApi
  cache, which has the same shape of problem and wants the same shared backend.
- **Resets on restart.**
- **Not a defence against a distributed attacker.** It stops casual abuse and
  runaway clients. A real edge/WAF limit is still needed in production.

Emergency access
----------------
Nothing that carries emergency information is rate limited. ``/health`` and
``/api/v2/resources/*`` — which serve the national helplines — are deliberately
left alone. A limiter must never be the reason someone cannot reach 112.
"""

from __future__ import annotations

import logging
import os
import threading
import time
from collections import defaultdict, deque
from dataclasses import dataclass
from typing import Deque, Dict, Optional

from fastapi import HTTPException, Request

from backend.trace import log_fields

logger = logging.getLogger(__name__)

#: Set ``HERWAY_RATE_LIMIT_ENABLED=false`` to disable (useful in tests that
#: deliberately hammer an endpoint).
def _enabled() -> bool:
    return os.getenv("HERWAY_RATE_LIMIT_ENABLED", "true").strip().lower() != "false"


@dataclass(frozen=True)
class Budget:
    """A request allowance: ``limit`` requests per ``window_seconds``."""

    limit: int
    window_seconds: int
    name: str


# Tiers, chosen to be invisible to a real person and obstructive to a script.
#
# A woman using the app heavily might submit a handful of community posts or ask
# for several rewrites in an hour. A scraper or a runaway retry loop does
# hundreds. The gap between those is where these numbers sit.

#: Paid-provider calls (Gemini, Bedrock). The expensive ones.
LLM_BUDGET = Budget(limit=20, window_seconds=300, name="llm")

#: Writes to the database, e.g. submitting a community post.
SUBMISSION_BUDGET = Budget(limit=10, window_seconds=300, name="submission")

#: Public reads. Generous — these back ordinary page loads.
READ_BUDGET = Budget(limit=120, window_seconds=60, name="read")

#: Stateless CPU work, e.g. steganography encode/decode.
UTILITY_BUDGET = Budget(limit=30, window_seconds=300, name="utility")


class SlidingWindowLimiter:
    """Fixed-capacity sliding window, keyed by caller.

    Keeps one deque of timestamps per key and discards entries older than the
    window on each check, so the memory held is bounded by the limit itself.
    """

    def __init__(self) -> None:
        self._hits: Dict[str, Deque[float]] = defaultdict(deque)
        self._lock = threading.Lock()

    def check(self, key: str, budget: Budget) -> Optional[int]:
        """Record a hit. Returns ``None`` if allowed, else seconds to wait."""
        now = time.monotonic()
        cutoff = now - budget.window_seconds

        with self._lock:
            hits = self._hits[key]
            while hits and hits[0] < cutoff:
                hits.popleft()

            if len(hits) >= budget.limit:
                # Oldest hit decides when a slot frees up.
                retry_after = int(hits[0] + budget.window_seconds - now) + 1
                return max(retry_after, 1)

            hits.append(now)
            return None

    def reset(self) -> None:
        """Drop all state. For tests."""
        with self._lock:
            self._hits.clear()


_limiter = SlidingWindowLimiter()


def reset_limiter() -> None:
    """Clear all recorded hits. Intended for tests."""
    _limiter.reset()


def _caller_key(request: Request, budget: Budget) -> str:
    """Identify the caller, preferring a real identity over an IP.

    Order:

    1. The anonymous session cookie or Clerk subject, when present. This is
       stable per browser and survives a changing IP.
    2. The peer IP.

    ``X-Forwarded-For`` is **not** trusted: it is attacker-controlled unless a
    known proxy is in front, and trusting it here would let anyone bypass the
    limit by varying a header. Deployments behind a real proxy should enforce
    limits at that proxy as well.
    """
    cookie = request.cookies.get("herway_sid")
    if cookie:
        return f"{budget.name}:sid:{cookie[:32]}"

    auth = request.headers.get("authorization", "")
    if auth.lower().startswith("bearer ") and len(auth) > 16:
        # A fingerprint of the token, never the token itself.
        return f"{budget.name}:tok:{hash(auth) & 0xFFFFFFFF:08x}"

    client_host = request.client.host if request.client else "unknown"
    return f"{budget.name}:ip:{client_host}"


def enforce(request: Request, budget: Budget) -> None:
    """Raise ``429`` when ``request``'s caller is over ``budget``."""
    if not _enabled():
        return

    retry_after = _limiter.check(_caller_key(request, budget), budget)
    if retry_after is None:
        return

    logger.warning(
        "Rate limit exceeded %s",
        log_fields(
            budget=budget.name,
            path=request.url.path,
            retry_after_s=retry_after,
        ),
    )
    raise HTTPException(
        status_code=429,
        detail=(
            "You have made a lot of requests in a short time, so this one was "
            "not processed. Please wait a moment and try again. "
            "If you need help right now, call 112, or 181 for the women helpline."
        ),
        headers={"Retry-After": str(retry_after)},
    )


# ---------------------------------------------------------------------------
# FastAPI dependencies
# ---------------------------------------------------------------------------
# Used as `Depends(rate_limit_llm)` so the limit is visible in the route
# signature and in the OpenAPI schema, rather than hidden in a decorator.


def rate_limit_llm(request: Request) -> None:
    """Guard an endpoint that calls a paid model provider."""
    enforce(request, LLM_BUDGET)


def rate_limit_submission(request: Request) -> None:
    """Guard an endpoint that writes to the database."""
    enforce(request, SUBMISSION_BUDGET)


def rate_limit_read(request: Request) -> None:
    """Guard a public read endpoint."""
    enforce(request, READ_BUDGET)


def rate_limit_utility(request: Request) -> None:
    """Guard a stateless compute endpoint."""
    enforce(request, UTILITY_BUDGET)
