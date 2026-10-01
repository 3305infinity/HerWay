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
  - ``backend.routes.resources``→ /api/v2/resources/...
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

# Import routers
from backend.routes.cases import router as cases_router
from backend.routes.chat import router as chat_router
from backend.routes.discreet import router as discreet_router
from backend.routes.legacy import router as legacy_router
from backend.routes.research import router as research_router
from backend.routes.resources import router as resources_router

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------
logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)
handler = logging.StreamHandler()
handler.setFormatter(CustomFormatter())
logger.addHandler(handler)


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
        "mongodb": bool(os.getenv("MONGO_ENDPOINT") or os.getenv("MONGODB_URI")),
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
                )
            },
        )


# ---------------------------------------------------------------------------
# Mount routers
# ---------------------------------------------------------------------------
app.include_router(legacy_router)
app.include_router(cases_router)
app.include_router(research_router)
app.include_router(chat_router)
app.include_router(discreet_router)
app.include_router(resources_router)


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
