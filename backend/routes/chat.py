"""
Chat router — Case-aware conversational assistant backed by ChatAgent and SerpApiService.

Endpoints:
  POST /api/v2/chat   — send a message, execute tool loop, get grounded reply
"""

from __future__ import annotations

import logging
from typing import List, Optional

from bson import ObjectId
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from backend.agents.chat_agent import ChatAgent
from backend.db import get_database
from backend.models.case import Case
from backend.services.llm_service import LLMService
from backend.services.serpapi_service import SerpApiService
from backend.utils.common import serialize_object_id

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v2/chat", tags=["chat"])


class ChatRequest(BaseModel):
    case_id: Optional[str] = Field(None, description="Current active case ID")
    message: str = Field(..., min_length=1)
    history: List[dict[str, str]] = Field(
        default_factory=list,
        description='Previous messages as [{"role": "user"|"assistant", "content": "..."}]',
    )


class ChatResponse(BaseModel):
    reply: str
    sources: List[str] = Field(default_factory=list)
    searched_query: Optional[str] = None


@router.post("", response_model=ChatResponse)
async def chat(request: ChatRequest):
    """Send a message and get a case-grounded reply from HerWay's tool-calling assistant."""
    db = get_database()
    llm = LLMService()
    serpapi = SerpApiService()

    chat_agent = ChatAgent(llm, serpapi)

    # Load case context if case_id provided
    case_obj: Optional[Case] = None
    if request.case_id and db is not None:
        try:
            doc = db["cases"].find_one({"_id": ObjectId(request.case_id)})
            if doc:
                case_obj = Case(**serialize_object_id(doc))
        except Exception:
            pass

    if not case_obj:
        # Fallback dummy case context for general inquiries
        case_obj = Case(
            user_id="anonymous",
            situation_text=request.message,
            title="General Inquiry",
        )

    try:
        result = await chat_agent.converse(
            case=case_obj,
            user_message=request.message,
            history=request.history,
            db=db,
        )

        # Update conversation in MongoDB if case exists
        if request.case_id and db is not None:
            db["cases"].update_one(
                {"_id": ObjectId(request.case_id)},
                {
                    "$push": {
                        "conversation": {
                            "$each": [
                                {"role": "user", "content": request.message},
                                {"role": "assistant", "content": result.get("reply", "")},
                            ]
                        }
                    }
                },
            )

        return ChatResponse(
            reply=result.get("reply", ""),
            sources=result.get("sources", []),
            searched_query=result.get("searched_query"),
        )

    except Exception as exc:
        logger.exception("Case-aware chat failed")
        raise HTTPException(status_code=500, detail=f"Chat error: {exc}")

