"""
Haven Backend — FastAPI application entry point.

Architecture (post-refactor):
- Legacy endpoints are served via ``backend.routes.legacy`` at the root path.
  These are the original Haven endpoints used by the current frontend.
  They remain FULLY FUNCTIONAL and unchanged.

- New v2 endpoints are served via:
  - ``backend.routes.cases``    → /api/v2/cases/...
  - ``backend.routes.research`` → /api/v2/research/...
  - ``backend.routes.chat``     → /api/v2/chat/...

The old inline endpoint definitions have been moved to ``routes/legacy.py``
but their behaviour is identical.
"""

import logging
import sys
from pathlib import Path

# Ensure Haven-main and backend directories are in sys.path
_current_file = Path(__file__).resolve()
_backend_dir = _current_file.parent
_root_dir = _backend_dir.parent
for p in [str(_root_dir), str(_backend_dir)]:
    if p not in sys.path:
        sys.path.insert(0, p)

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from backend.db import get_database
from backend.logger import CustomFormatter

# Import routers
from backend.routes.legacy import router as legacy_router
from backend.routes.cases import router as cases_router
from backend.routes.research import router as research_router
from backend.routes.chat import router as chat_router

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------
logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)
handler = logging.StreamHandler()
handler.setFormatter(CustomFormatter())
logger.addHandler(handler)

# ---------------------------------------------------------------------------
# Application
# ---------------------------------------------------------------------------
app = FastAPI(
    title="Haven",
    description="Information and action-planning assistant for real-world problems",
    version="2.0.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ---------------------------------------------------------------------------
# Startup — database connection (same as original)
# ---------------------------------------------------------------------------
db = None


def initialize_database():
    global db
    if db is None:
        db = get_database()


@app.on_event("startup")
async def startup_event():
    initialize_database()


# ---------------------------------------------------------------------------
# Mount routers
# ---------------------------------------------------------------------------

# Legacy endpoints — these keep the existing frontend working
app.include_router(legacy_router)

# New v2 endpoints — the research-resolution pipeline
app.include_router(cases_router)
app.include_router(research_router)
app.include_router(chat_router)


# ---------------------------------------------------------------------------
# Health check
# ---------------------------------------------------------------------------
@app.get("/health")
async def health():
    return {"status": "ok", "version": "2.0.0"}