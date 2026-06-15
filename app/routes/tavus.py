import os
import asyncio
import json as json_lib
import logging
from urllib.parse import quote

import httpx
from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, field_validator

from app.gemini import client, gemini_config, SSE_HEADERS
from app.prompts import build_prompt
from app.rag import build_rag_context

router = APIRouter()

VOICE_RETRY_DELAY = 2


class TavusEndRequest(BaseModel):
    conversation_id: str


class TavusMessageRequest(BaseModel):
    conversation_id: str
    message: str

    @field_validator("message")
    @classmethod
    def message_not_empty(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("message must not be empty")
        return v


class TavusLLMRequest(BaseModel):
    messages: list
    stream: bool = True
    lang: str = "de"
    studiengang: str | None = None


@router.post("/tavus/session")
async def tavus_session():
    api_key = os.getenv("TAVUS_API_KEY")
    if not api_key:
        raise HTTPException(status_code=500, detail="TAVUS_API_KEY nicht gesetzt")

    replica_id = os.getenv("TAVUS_REPLICA_ID", "")
    persona_id = os.getenv("TAVUS_PERSONA_ID", "")

    body: dict = {
        "replica_id": replica_id,
        "conversational_context": (
            "Du bist KIRA, Studienberaterin am KIT (Karlsruher Institut für Technologie). "
            "Antworte auf Deutsch, freundlich und präzise. "
            "Bei offiziellen Daten verweise auf campus.kit.edu."
        ),
        "custom_greeting": "",
    }
    if persona_id:
        body["persona_id"] = persona_id

    async with httpx.AsyncClient() as http:
        try:
            res = await http.post(
                "https://tavusapi.com/v2/conversations",
                headers={"x-api-key": api_key, "Content-Type": "application/json"},
                json=body,
                timeout=15.0,
            )
            data = res.json()
            logging.warning(f"Tavus API status: {res.status_code}, body: {data}")
            if res.status_code not in (200, 201):
                raise HTTPException(status_code=res.status_code, detail=str(data))
            return {
                "conversation_id": data["conversation_id"],
                "conversation_url": data["conversation_url"],
            }
        except httpx.TimeoutException:
            raise HTTPException(status_code=504, detail="Tavus API Timeout")


@router.post("/tavus/end")
async def tavus_end(request: TavusEndRequest):
    api_key = os.getenv("TAVUS_API_KEY", "")
    async with httpx.AsyncClient() as http:
        try:
            await http.delete(
                f"https://tavusapi.com/v2/conversations/{request.conversation_id}",
                headers={"x-api-key": api_key},
                timeout=10.0,
            )
        except httpx.TimeoutException:
            pass
    return {"status": "ended"}


@router.post("/tavus/message")
async def tavus_message(request: TavusMessageRequest):
    api_key = os.getenv("TAVUS_API_KEY")
    if not api_key:
        raise HTTPException(status_code=500, detail="TAVUS_API_KEY nicht gesetzt")

    async with httpx.AsyncClient() as http:
        try:
            res = await http.post(
                f"https://tavusapi.com/v2/conversations/{quote(request.conversation_id, safe='')}/message",
                headers={"x-api-key": api_key, "Content-Type": "application/json"},
                json={"message": request.message},
                timeout=15.0,
            )
            if res.status_code not in (200, 201):
                try:
                    detail = str(res.json())
                except Exception:
                    detail = res.text or f"HTTP {res.status_code}"
                raise HTTPException(status_code=res.status_code, detail=detail)
            return {"status": "sent"}
        except httpx.TimeoutException:
            raise HTTPException(status_code=504, detail="Tavus API Timeout")


@router.post("/tavus/llm")
@router.post("/tavus/llm/chat/completions")
async def tavus_llm(request: TavusLLMRequest):
    user_message = next(
        (m.get("content", "") for m in reversed(request.messages) if m.get("role") == "user"),
        "",
    )

    if not user_message:
        async def empty_stream():
            yield f'data: {json_lib.dumps({"choices":[{"delta":{},"finish_reason":"stop"}]})}\n\n'
            yield 'data: [DONE]\n\n'
        return StreamingResponse(empty_stream(), media_type="text/event-stream", headers=SSE_HEADERS)

    kontext, kontext_anweisung, _ = await asyncio.to_thread(
        build_rag_context, user_message, request.studiengang
    )

    verlauf = "\n".join(
        f"{'Du' if m.get('role') == 'user' else 'KIRA'}: {m.get('content', '')}"
        for m in request.messages[:-1][-6:]
        if m.get("role") in ("user", "assistant") and m.get("content")
    )

    prompt = f"""{build_prompt("voice", request.lang)}

{kontext_anweisung}

Kontext:
{kontext}

Gesprächsverlauf:
{verlauf}

Frage: {user_message}"""

    async def stream_answer():
        gesendet = False
        for versuch in range(3):
            try:
                stream = await client.aio.models.generate_content_stream(
                    model="gemini-2.5-flash",
                    contents=prompt,
                    config=gemini_config(300),
                )
                async for chunk in stream:
                    if chunk.text:
                        gesendet = True
                        yield f'data: {json_lib.dumps({"choices": [{"delta": {"content": chunk.text}, "finish_reason": None}]})}\n\n'
                break
            except Exception as e:
                logging.warning(f"tavus/llm Gemini Fehler (Versuch {versuch + 1}): {e}")
                if gesendet:
                    break
                if versuch < 2:
                    await asyncio.sleep(VOICE_RETRY_DELAY)
        if not gesendet:
            yield f'data: {json_lib.dumps({"choices": [{"delta": {"content": "Service momentan nicht verfügbar."}, "finish_reason": None}]})}\n\n'
        yield f'data: {json_lib.dumps({"choices": [{"delta": {}, "finish_reason": "stop"}]})}\n\n'
        yield 'data: [DONE]\n\n'

    return StreamingResponse(stream_answer(), media_type="text/event-stream", headers=SSE_HEADERS)
