"""
Chat router — case-aware conversational assistant backed by ChatAgent.

Endpoints:
  POST /api/v2/chat   — send a message, execute the tool loop, get a grounded reply

Two things this router is careful about:

* **Ownership.** A ``case_id`` is only honoured if the caller owns that case.
  Previously any case id in the body was loaded and its contents fed into the
  reply, which let anyone read another person's case through the chat.
* **Honest responses.** Every field the agent produces (community posts, an
  adapted safety plan, a generated report) is returned. The response model used
  to drop them, so the Community tab and plan-refresh in the UI silently never
  worked.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from bson import ObjectId
from bson.errors import InvalidId
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from backend.agents.chat_agent import ChatAgent
from backend.auth import Identity, assert_case_owner, get_identity, owner_filter
from backend.db import get_database
from backend.models.case import Case
from backend.services.llm_service import LLMService, LLMUnavailableError
from backend.services.serpapi_service import SerpApiService
from backend.trace import get_trace_id
from backend.utils.common import serialize_object_id

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v2/chat", tags=["chat"])

MAX_HISTORY_MESSAGES = 20


class ChatRequest(BaseModel):
    case_id: Optional[str] = Field(None, description="Current active case ID")
    message: str = Field(..., min_length=1, max_length=4000)
    history: List[Dict[str, str]] = Field(
        default_factory=list,
        description='Previous messages as [{"role": "user"|"assistant", "content": "..."}]',
    )
    mode: Optional[str] = Field(
        None,
        description=(
            "Optional mode context: 'therapy' (emotional support via Niva), "
            "'legal' (legal Q&A via LawBot), or None (general case chat)."
        ),
    )


class ChatResponse(BaseModel):
    reply: str
    sources: List[str] = Field(default_factory=list)
    searched_query: Optional[str] = None
    #: Which tool the agent ran, so the UI can react (e.g. refresh the plan).
    tool_used: Optional[str] = None
    #: True when the safety plan changed and the client should reload the case.
    plan_adapted: bool = False
    safety_plan: Optional[Dict[str, Any]] = None
    community_posts: List[Dict[str, Any]] = Field(default_factory=list)
    lawbot_docs: List[str] = Field(default_factory=list)
    formal_report: Optional[str] = None
    #: Set when part of the answer could not be produced (e.g. search was down).
    degraded_notice: Optional[str] = None
    #: Diagnostic identifier for this request, so a user can quote it when
    #: reporting a problem and it can be found in the logs. Additive and
    #: optional — existing clients that ignore it are unaffected. It is **not**
    #: an authorization token and grants access to nothing.
    trace_id: Optional[str] = None
    #: Phase 3 local intelligence. All optional and additive; a client that
    #: ignores them behaves exactly as before.
    #: Normalised listings from a local discovery search, with provenance and a
    #: retrieval timestamp. Never implies a place is open or safe.
    local_resources: Optional[Dict[str, Any]] = None
    #: Structured profile of one named place, including review themes.
    place_profile: Optional[Dict[str, Any]] = None
    #: Side-by-side comparison table. Carries no overall ranking by design.
    comparison: Optional[Dict[str, Any]] = None


@router.post("", response_model=ChatResponse)
async def chat(request: ChatRequest, identity: Identity = Depends(get_identity)):
    """Send a message and get a case-grounded reply from HerWay's assistant."""
    db = get_database()
    llm = LLMService()

    if not llm.is_configured:
        raise HTTPException(
            status_code=503,
            detail=(
                "HerWay's assistant is unavailable right now. If you are in immediate "
                "danger, call 112, or 181 for the women helpline."
            ),
        )

    serpapi = SerpApiService()
    chat_agent = ChatAgent(llm, serpapi)

    # Load case context only if the caller actually owns the case.
    case_obj: Optional[Case] = None
    if request.case_id:
        if db is None:
            raise HTTPException(status_code=503, detail="Database unavailable")
        try:
            obj_id = ObjectId(request.case_id)
        except (InvalidId, TypeError, ValueError):
            raise HTTPException(status_code=400, detail="Invalid case ID format")

        doc = db["cases"].find_one({"_id": obj_id})
        if not doc:
            raise HTTPException(status_code=404, detail="Case not found")
        assert_case_owner(doc, identity)
        try:
            case_obj = Case(**serialize_object_id(doc))
        except Exception as exc:
            logger.error("Chat: stored case %s failed validation: %s", request.case_id, exc)
            raise HTTPException(
                status_code=500,
                detail="This case could not be opened. Please contact support.",
            )

    if case_obj is None:
        # Standalone LawBot / Niva session — no stored case behind it.
        mode_context = ""
        title = "General enquiry"
        if request.mode == "therapy":
            mode_context = "[Emotional support session with Niva. The user may be in distress.] "
            title = "Emotional support session"
        elif request.mode == "legal":
            mode_context = "[Legal information session via LawBot. Indian law context.] "
            title = "Legal information session"

        case_obj = Case(
            user_id=identity.owner_id,
            situation_text=f"{mode_context}{request.message}",
            title=title,
        )

    history = request.history[-MAX_HISTORY_MESSAGES:]

    try:
        result = await chat_agent.converse(
            case=case_obj,
            user_message=request.message,
            history=history,
            db=db,
            mode=request.mode,
        )
    except LLMUnavailableError as exc:
        logger.error("Chat: LLM unavailable (%s): %s", exc.reason, exc)
        raise HTTPException(
            status_code=429 if exc.reason == "rate_limited" else 503,
            detail=exc.user_message,
        )
    except Exception as exc:
        logger.exception("Case-aware chat failed")
        raise HTTPException(
            status_code=500,
            detail="Something went wrong answering that. Please try rephrasing your question.",
        )

    reply = result.get("reply", "")
    if not reply:
        raise HTTPException(
            status_code=502,
            detail="HerWay did not produce an answer. Please try again.",
        )

    # Persist the exchange only on a real, owned case.
    if request.case_id and db is not None:
        try:
            db["cases"].update_one(
                {"_id": ObjectId(request.case_id), **owner_filter(identity)},
                {
                    "$push": {
                        "conversation": {
                            "$each": [
                                {"role": "user", "content": request.message},
                                {"role": "assistant", "content": reply},
                            ]
                        }
                    }
                },
            )
        except Exception as exc:
            # The user still gets their answer; we just could not save it.
            logger.error("Chat: could not persist conversation for %s: %s", request.case_id, exc)

    return ChatResponse(
        reply=reply,
        sources=result.get("sources", []) or [],
        searched_query=result.get("searched_query"),
        tool_used=result.get("tool_used"),
        plan_adapted=bool(result.get("plan_adapted")),
        safety_plan=result.get("safety_plan"),
        community_posts=result.get("community_posts", []) or [],
        lawbot_docs=result.get("lawbot_docs", []) or [],
        formal_report=result.get("formal_report"),
        degraded_notice=result.get("degraded_notice"),
        trace_id=result.get("trace_id") or get_trace_id(),
        local_resources=result.get("local_resources"),
        place_profile=result.get("place_profile"),
        comparison=result.get("comparison"),
    )
