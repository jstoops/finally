"""Chat routes: POST /api/chat and GET /api/chat/history (PLAN §8)."""

from __future__ import annotations

from contextlib import closing

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

from app import db
from app.llm import LLMCallFailed, LLMNotConfigured, handle_chat

HISTORY_LIMIT = 50

router = APIRouter(tags=["chat"])


class ChatRequest(BaseModel):
    message: str


@router.post("/api/chat")
async def post_chat(body: ChatRequest, request: Request) -> dict:
    message = body.message.strip()
    if not message:
        raise HTTPException(status_code=400, detail="Message cannot be empty.")
    try:
        return await handle_chat(request.app.state.ctx, message)
    except LLMNotConfigured as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except LLMCallFailed as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@router.get("/api/chat/history")
def get_chat_history(request: Request) -> dict:
    with closing(request.app.state.ctx.connect()) as conn:
        return {"messages": db.list_chat_messages(conn, limit=HISTORY_LIMIT)}
