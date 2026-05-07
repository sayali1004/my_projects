import uuid
import json
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from typing import Optional
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from db.database import get_db, Chat, Message
from agents.chat_agent import generate_response, generate_response_stream

router = APIRouter()


class ChatRequest(BaseModel):
    message: str
    chat_id: Optional[str] = None
    project_id: Optional[str] = None


class NewChatRequest(BaseModel):
    title: str = "New chat"
    project_id: Optional[str] = None


@router.post("/new")
async def create_chat(req: NewChatRequest, db: AsyncSession = Depends(get_db)):
    """Create a new chat session."""
    chat = Chat(
        id=str(uuid.uuid4()),
        title=req.title,
        project_id=req.project_id
    )
    db.add(chat)
    await db.commit()
    return {"id": chat.id, "title": chat.title, "project_id": chat.project_id}


@router.post("/message")
async def send_message(req: ChatRequest, db: AsyncSession = Depends(get_db)):
    """
    Send a message. Triggers the full RAG pipeline:
    retrieve from vault → augment prompt → Ollama response
    """
    # Get or create chat
    if req.chat_id:
        result = await db.execute(select(Chat).where(Chat.id == req.chat_id))
        chat   = result.scalar_one_or_none()
        if not chat:
            raise HTTPException(404, "Chat not found")
    else:
        chat = Chat(
            id=str(uuid.uuid4()),
            title=req.message[:50],     # use first 50 chars as title
            project_id=req.project_id
        )
        db.add(chat)
        await db.commit()

    # Fetch chat history for context
    history_result = await db.execute(
        select(Message)
        .where(Message.chat_id == chat.id)
        .order_by(Message.created_at)
    )
    history = [
        {"role": m.role, "content": m.content}
        for m in history_result.scalars().all()
    ]

    # Save user message
    user_msg = Message(
        id=str(uuid.uuid4()),
        chat_id=chat.id,
        role="user",
        content=req.message
    )
    db.add(user_msg)
    await db.commit()

    # Generate RAG response
    result = await generate_response(
        question=req.message,
        project_id=req.project_id or chat.project_id,
        chat_history=history
    )

    # Save assistant message with sources
    assistant_msg = Message(
        id=str(uuid.uuid4()),
        chat_id=chat.id,
        role="assistant",
        content=result["answer"],
        sources=json.dumps(result["sources"])
    )
    db.add(assistant_msg)
    await db.commit()

    return {
        "chat_id":     chat.id,
        "answer":      result["answer"],
        "sources":     result["sources"],
        "chunks_used": result["chunks_used"]
    }


@router.post("/message/stream")
async def send_message_stream(req: ChatRequest, db: AsyncSession = Depends(get_db)):
    """
    Streaming version of send_message.
    Returns text/event-stream with events:
      data: {"type": "start",  "chat_id": "...", "sources": [...], "chunks_used": N}
      data: {"type": "token",  "content": "..."}
      data: {"type": "done"}
    """
    # ── get or create chat (same logic as /message) ──────────────────────
    if req.chat_id:
        result = await db.execute(select(Chat).where(Chat.id == req.chat_id))
        chat   = result.scalar_one_or_none()
        if not chat:
            raise HTTPException(404, "Chat not found")
    else:
        chat = Chat(
            id=str(uuid.uuid4()),
            title=req.message[:50],
            project_id=req.project_id
        )
        db.add(chat)
        await db.commit()

    # fetch history for RAG context
    history_result = await db.execute(
        select(Message).where(Message.chat_id == chat.id).order_by(Message.created_at)
    )
    history = [{"role": m.role, "content": m.content} for m in history_result.scalars().all()]

    # save user message now so history is complete before streaming starts
    user_msg = Message(id=str(uuid.uuid4()), chat_id=chat.id, role="user", content=req.message)
    db.add(user_msg)
    await db.commit()

    chat_id    = chat.id
    project_id = req.project_id or chat.project_id

    async def event_stream():
        full_response = ""
        sources       = []
        chunks_used   = 0

        async for event in generate_response_stream(
            question=req.message,
            project_id=project_id,
            chat_history=history
        ):
            if event["type"] == "start":
                sources     = event["sources"]
                chunks_used = event["chunks_used"]
                yield f"data: {json.dumps({'type': 'start', 'chat_id': chat_id, 'sources': sources, 'chunks_used': chunks_used})}\n\n"
            elif event["type"] == "token":
                full_response += event["content"]
                yield f"data: {json.dumps({'type': 'token', 'content': event['content']})}\n\n"

        # persist assistant reply after the stream is fully consumed
        assistant_msg = Message(
            id=str(uuid.uuid4()),
            chat_id=chat_id,
            role="assistant",
            content=full_response,
            sources=json.dumps(sources)
        )
        db.add(assistant_msg)
        await db.commit()

        yield f"data: {json.dumps({'type': 'done'})}\n\n"

    return StreamingResponse(event_stream(), media_type="text/event-stream")


@router.get("/{chat_id}/messages")
async def get_messages(chat_id: str, db: AsyncSession = Depends(get_db)):
    """Get all messages for a chat session."""
    result = await db.execute(
        select(Message)
        .where(Message.chat_id == chat_id)
        .order_by(Message.created_at)
    )
    messages = result.scalars().all()

    return [
        {
            "id":         m.id,
            "role":       m.role,
            "content":    m.content,
            "sources":    json.loads(m.sources) if m.sources else [],
            "created_at": m.created_at.isoformat()
        }
        for m in messages
    ]


@router.get("/list")
async def list_chats(project_id: str = None, db: AsyncSession = Depends(get_db)):
    """List all chats, optionally filtered by project."""
    query = select(Chat).order_by(Chat.updated_at.desc())
    if project_id:
        query = query.where(Chat.project_id == project_id)

    result = await db.execute(query)
    chats  = result.scalars().all()

    return [
        {
            "id":         c.id,
            "title":      c.title,
            "project_id": c.project_id,
            "created_at": c.created_at.isoformat()
        }
        for c in chats
    ]
