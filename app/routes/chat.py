import asyncio
import json as json_lib
import logging
import time

from fastapi import APIRouter
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from app.gemini import client, gemini_config, SSE_HEADERS
from app.prompts import build_prompt
from app.rag import build_rag_context
from app.session import sessions, touch_session, remember_opening, opening_instruction

router = APIRouter()


class ChatRequest(BaseModel):
    message: str
    session_id: str = "default"
    lang: str = "de"
    studiengang: str | None = None


@router.post("/chat")
async def chat(request: ChatRequest):
    session_id  = request.session_id
    user_input  = request.message

    touch_session(session_id)
    if session_id not in sessions:
        sessions[session_id] = []
    chat_history = sessions[session_id]

    kontext, kontext_anweisung, beste_distanz = await asyncio.to_thread(
        build_rag_context, user_input, request.studiengang
    )
    verlauf = "\n".join(f"{m['role']}: {m['content']}" for m in chat_history[-4:])

    prompt = f"""{build_prompt("text", request.lang)}{opening_instruction(session_id)}

{kontext_anweisung}

Kontext:
{kontext}

Gesprächsverlauf:
{verlauf}

Frage: {user_input}"""

    quelle = "Wissensbasis" if beste_distanz < 0.45 else "LLM"

    async def event_stream():
        t1 = time.time()
        chat_parts = []
        try:
            stream = await client.aio.models.generate_content_stream(
                model="gemini-2.5-flash",
                contents=prompt,
                config=gemini_config(400),
            )
            async for chunk in stream:
                if chunk.text:
                    chat_parts.append(chunk.text)
                    yield f'data: {json_lib.dumps({"type": "chunk", "text": chunk.text})}\n\n'
        except Exception as e:
            logging.warning(f"/chat Gemini Fehler: {e}")
            yield f'data: {json_lib.dumps({"type": "error", "message": "Service momentan nicht verfügbar."})}\n\n'
            return

        answer = "".join(chat_parts).strip()
        remember_opening(session_id, answer)

        sessions[session_id].append({"role": "Du", "content": user_input})
        sessions[session_id].append({"role": "Bot", "content": answer})

        done_event = {
            "type": "done",
            "voice_text": answer,
            "source": quelle,
            "latency_ms": round((time.time() - t1) * 1000),
            "session_id": session_id,
        }
        yield f'data: {json_lib.dumps(done_event)}\n\n'

    return StreamingResponse(event_stream(), media_type="text/event-stream", headers=SSE_HEADERS)
