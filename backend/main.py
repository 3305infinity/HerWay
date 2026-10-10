"""
HerWay Backend — FastAPI application entry point.

Routing
-------
- Legacy endpoints (``backend.routes.legacy``) are served at the root path.
  These are the original Haven endpoints and remain functional.
- v2 endpoints:
  - ``backend.routes.cases``    → /api/v2/cases/...
  - ``backend.routes.research`` → /api/v2/research/...
  - ``backend.routes.chat``     → /api/v2/chat/...
  - ``backend.routes.discreet`` → /api/v2/discreet/...
  - ``backend.routes.discover`` → /api/v2/discover/...
  - ``backend.routes.resources``→ /api/v2/resources/...
  - ``backend.routes.safety_center`` → /api/v2/safety-center/...
"""

import logging
import os
import sys
from contextlib import asynccontextmanager
from pathlib import Path

# Ensure Haven-main and backend directories are in sys.path
_current_file = Path(__file__).resolve()
_backend_dir = _current_file.parent
_root_dir = _backend_dir.parent
for p in [str(_root_dir), str(_backend_dir)]:
    if p not in sys.path:
        sys.path.insert(0, p)

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from backend.auth import clerk_is_configured, startup_auth_check
from backend.db import get_database, database_mode
from backend.logger import CustomFormatter
from backend.trace import (
    TRACE_HEADER,
    coerce_trace_id,
    get_trace_id,
    install_log_filter,
    reset_trace_id,
    set_trace_id,
)

# Import routers
from backend.routes.cases import router as cases_router
from backend.routes.chat import router as chat_router
from backend.routes.discreet import router as discreet_router
from backend.routes.demo import router as demo_router
from backend.routes.discover import router as discover_router
from backend.routes.legacy import router as legacy_router
from backend.routes.research import router as research_router
from backend.routes.resources import router as resources_router
from backend.routes.safety_center import router as safety_center_router

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------
logger = logging.getLogger(__name__)

# Configure the `backend` package logger rather than just `backend.main`.
# Every module uses `logging.getLogger(__name__)`, so `backend.routes.cases`,
# `backend.agents.chat_agent` and the rest are its children. Attaching the
# handler here means all of them are formatted by CustomFormatter — and so all
# of them carry the request's trace ID. Previously only `backend.main` had a
# handler and everything else propagated to uvicorn's root handler, which knows
# nothing about traces.
_package_logger = logging.getLogger("backend")
_package_logger.setLevel(logging.INFO)
if not any(isinstance(h, logging.StreamHandler) for h in _package_logger.handlers):
    _handler = logging.StreamHandler()
    _handler.setFormatter(CustomFormatter())
    _package_logger.addHandler(_handler)
    # Already rendered here; letting it propagate would print every line twice.
    _package_logger.propagate = False

install_log_filter(_package_logger)


# ---------------------------------------------------------------------------
# Lifespan
# ---------------------------------------------------------------------------
db = None


def initialize_database():
    global db
    if db is None:
        db = get_database()
    return db


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Refuse to boot with an unsafe production auth configuration rather than
    # silently serving every case to every visitor.
    startup_auth_check()
    initialize_database()

    for name, present in _integration_status().items():
        if not present:
            logger.warning(
                "Integration '%s' is not configured. Features that need it will "
                "report an outage instead of inventing a result.",
                name,
            )
    yield


def _integration_status() -> dict[str, bool]:
    """Which optional integrations are configured.

    The app always starts; each feature degrades on its own.
    """
    return {
        "gemini": bool(os.getenv("GEMINI_API_KEY")),
        "serpapi": bool(os.getenv("SERPAPI_API_KEY") or os.getenv("SERPAPI_KEY")),
        # Whether the connection actually succeeded, not merely whether a URI
        # was configured. Reporting `true` for a set-but-unreachable URI told an
        # operator that cases were being persisted while they were in fact being
        # held in a volatile in-memory store.
        "mongodb": database_mode() == "mongodb",
        "clerk": clerk_is_configured(),
        "groq": bool(os.getenv("GROQ_API_TOKEN")),
        "opencage": bool(os.getenv("OPENCAGE_API_KEY")),
        "aws_bedrock": bool(os.getenv("AWS_ACCESS_KEY_ID") and os.getenv("AWS_REGION")),
    }


# ---------------------------------------------------------------------------
# Application
# ---------------------------------------------------------------------------
app = FastAPI(
    title="HerWay",
    description="Information and action-planning assistant for real-world problems in India",
    version="2.1.0",
    lifespan=lifespan,
)


def _allowed_origins() -> list[str]:
    """CORS origins. Credentials are sent, so a wildcard is not permitted."""
    raw = os.getenv("HERWAY_ALLOWED_ORIGINS", "")
    if raw.strip():
        return [o.strip() for o in raw.split(",") if o.strip()]
    return ["http://localhost:3000", "http://127.0.0.1:3000"]


app.add_middleware(
    CORSMiddleware,
    allow_origins=_allowed_origins(),
    allow_credentials=True,  # the anonymous session cookie must be sent
    allow_methods=["GET", "POST", "PATCH", "DELETE", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type", "X-Dev-User-Id"],
)


@app.middleware("http")
async def catch_unhandled_errors(request: Request, call_next):
    """Return a plain, non-leaking error instead of an HTML stack trace.

    A traceback in a response body could expose case contents or file paths.
    The trace ID is included so a user can quote it when reporting a problem;
    it identifies the request in the logs and grants no access to anything.
    """
    try:
        return await call_next(request)
    except Exception:
        logger.exception("Unhandled error on %s %s", request.method, request.url.path)
        return JSONResponse(
            status_code=500,
            content={
                "detail": (
                    "Something went wrong on our side. Your information is safe. "
                    "Please try again."
                ),
                "trace_id": get_trace_id(),
            },
        )


# Registered after `catch_unhandled_errors`, which makes it the OUTER
# middleware (Starlette inserts each new middleware at the front of the stack).
# The trace ID is therefore already bound when the error handler above runs.
@app.middleware("http")
async def assign_trace_id(request: Request, call_next):
    """Bind a trace ID for the lifetime of this request.

    An inbound ``X-Trace-Id`` is accepted only if it matches a strict short-token
    pattern; anything else is replaced with a fresh server-generated ID, because
    this value is written to log files. It is a diagnostic label and is never
    consulted for authorization.
    """
    token = set_trace_id(coerce_trace_id(request.headers.get(TRACE_HEADER)))
    try:
        response = await call_next(request)
        response.headers[TRACE_HEADER] = get_trace_id() or ""
        return response
    finally:
        # Reset even when the handler raised, so a reused worker task cannot
        # carry this request's ID into the next one.
        reset_trace_id(token)


# ---------------------------------------------------------------------------
# Mount routers
# ---------------------------------------------------------------------------
app.include_router(legacy_router)
app.include_router(cases_router)
app.include_router(research_router)
app.include_router(chat_router)
app.include_router(discreet_router)
app.include_router(discover_router)
app.include_router(demo_router)
app.include_router(resources_router)
app.include_router(safety_center_router)


# ---------------------------------------------------------------------------
# Health
# ---------------------------------------------------------------------------
@app.get("/health")
async def health():
    """Liveness plus a truthful report of which integrations are available."""
    integrations = _integration_status()
    return {
        "status": "ok",
        "version": "2.1.0",
        "database": database_mode(),
        "integrations": integrations,
        "degraded": [name for name, ok in integrations.items() if not ok],
    }
