import asyncio
import json
import logging
import time

from fastapi import APIRouter
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from app.gemini import SSE_HEADERS, stream_gemini, GeminiUnavailable, GeminiMidStreamError
from app.prompts import build_prompt
from app.rag import build_rag_context
from app.session import sessions, touch_session, remember_opening, opening_instruction

router = APIRouter()

CHAT_RETRY_DELAY = 2


class ChatRequest(BaseModel):
    message: str = Field(..., max_length=2000)
    session_id: str = "default"
    lang: str = "de"
    studiengang: str | None = None


@router.post("/chat")
async def chat(request: ChatRequest):
    touch_session(request.session_id)
    if request.session_id not in sessions:
        sessions[request.session_id] = []
    chat_history = sessions[request.session_id]

    try:
        kontext, kontext_anweisung, beste_distanz = await asyncio.to_thread(
            build_rag_context, request.message, request.studiengang
        )
    except Exception:
        logging.error("/chat RAG Fehler", exc_info=True)

        async def rag_error_stream():
            yield f'data: {json.dumps({"type": "error", "message": "Wissensdatenbank momentan nicht verfügbar."})}\n\n'

        return StreamingResponse(rag_error_stream(), media_type="text/event-stream", headers=SSE_HEADERS)
    verlauf = "\n".join(f"{m['role']}: {m['content']}" for m in chat_history[-4:])

    prompt = f"""{build_prompt("text", request.lang)}{opening_instruction(request.session_id)}

{kontext_anweisung}

Kontext:
{kontext}

Gesprächsverlauf:
{verlauf}

Frage: {request.message}"""

    async def event_stream():
        t1 = time.time()
        chat_parts = []
        try:
            async for text in stream_gemini(prompt, 400, CHAT_RETRY_DELAY):
                chat_parts.append(text)
                yield f'data: {json.dumps({"type": "chunk", "text": text})}\n\n'
        except (GeminiUnavailable, GeminiMidStreamError):
            yield f'data: {json.dumps({"type": "error", "message": "Service momentan nicht verfügbar."})}\n\n'
            return

        answer = "".join(chat_parts).strip()
        remember_opening(request.session_id, answer)

        sessions[request.session_id].append({"role": "Du", "content": request.message})
        sessions[request.session_id].append({"role": "Bot", "content": answer})

        done_event = {
            "type": "done",
            "voice_text": answer,
            "source": "Wissensbasis" if beste_distanz < 0.45 else "LLM",
            "latency_ms": round((time.time() - t1) * 1000),
            "session_id": request.session_id,
        }
        yield f'data: {json.dumps(done_event)}\n\n'

    return StreamingResponse(event_stream(), media_type="text/event-stream", headers=SSE_HEADERS)
