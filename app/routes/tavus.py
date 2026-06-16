import os
import asyncio
import json as json_lib
import logging
from urllib.parse import quote

import httpx
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, field_validator

from app.auth import check_auth
from app.gemini import client, gemini_config, SSE_HEADERS
from app.prompts import build_prompt
from app.rag import build_rag_context

router = APIRouter()

VOICE_RETRY_DELAY = 2

# Aktive Voice-Einstellungen. Tavus ruft /tavus/llm serverseitig ohne UI-Kontext
# auf, daher merken wir uns hier die zuletzt im Frontend gewählte Sprache und den
# Studiengang. Bei lokalem Einzel-Session-Betrieb (ein Avatar gleichzeitig) genügt
# ein globaler Zustand; das Frontend aktualisiert ihn bei Session-Start und bei
# jeder Änderung von Sprache oder Studiengang.
active_voice_prefs: dict = {"lang": "de", "studiengang": None}

# Sprachabhängiger Gesprächskontext für die Tavus-Persona.
_VOICE_CONTEXT = {
    "de": (
        "Du bist KIRA, Studienberaterin am KIT (Karlsruher Institut für Technologie) "
        "für Fragen rund um das Studium der Wirtschaftswissenschaften. "
        "Antworte auf Deutsch, freundlich, kurz und präzise wie eine erfahrene Kommilitonin. "
        "Sprich Studierende mit 'du' an. Keine Listen oder Aufzählungen. "
        "Bei offiziellen Daten verweise auf campus.kit.edu."
    ),
    "en": (
        "You are KIRA, an academic advisor at KIT (Karlsruhe Institute of Technology). "
        "Answer in English, friendly and precise. "
        "For official data, refer to campus.kit.edu."
    ),
}


class TavusPrefsRequest(BaseModel):
    lang: str = "de"
    studiengang: str | None = None


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


@router.post("/tavus/settings", dependencies=[Depends(check_auth)])
async def tavus_settings(prefs: TavusPrefsRequest):
    """Aktualisiert Sprache/Studiengang für den laufenden Voice-Pfad."""
    active_voice_prefs["lang"] = prefs.lang
    active_voice_prefs["studiengang"] = prefs.studiengang
    return {"status": "ok", **active_voice_prefs}


@router.post("/tavus/session", dependencies=[Depends(check_auth)])
async def tavus_session(prefs: TavusPrefsRequest | None = None):
    api_key = os.getenv("TAVUS_API_KEY")
    if not api_key:
        raise HTTPException(status_code=500, detail="TAVUS_API_KEY nicht gesetzt")

    prefs = prefs or TavusPrefsRequest()
    active_voice_prefs["lang"] = prefs.lang
    active_voice_prefs["studiengang"] = prefs.studiengang

    replica_id = os.getenv("TAVUS_REPLICA_ID", "")
    persona_id = os.getenv("TAVUS_PERSONA_ID", "")

    body: dict = {
        "replica_id": replica_id,
        "conversational_context": _VOICE_CONTEXT.get(prefs.lang, _VOICE_CONTEXT["de"]),
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


@router.post("/tavus/end", dependencies=[Depends(check_auth)])
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


@router.post("/tavus/message", dependencies=[Depends(check_auth)])
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


# Tavus' OpenAI-kompatibler Client hängt "/chat/completions" an die im Dashboard
# konfigurierte Custom-LLM-URL an. Wir registrieren mehrere Aliase, damit sowohl
# eine Basis-URL mit "/tavus/llm" als auch die ngrok-Root funktioniert.
@router.post("/tavus/llm")
@router.post("/tavus/llm/chat/completions")
@router.post("/chat/completions")
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

    # Tavus sendet keine UI-Felder mit, daher kommen Sprache/Studiengang aus den
    # zuletzt im Frontend gesetzten Voice-Einstellungen.
    lang = active_voice_prefs["lang"]
    studiengang = active_voice_prefs["studiengang"]

    kontext, kontext_anweisung, _ = await asyncio.to_thread(
        build_rag_context, user_message, studiengang
    )

    verlauf = "\n".join(
        f"{'Du' if m.get('role') == 'user' else 'KIRA'}: {m.get('content', '')}"
        for m in request.messages[:-1][-6:]
        if m.get("role") in ("user", "assistant") and m.get("content")
    )

    prompt = f"""{build_prompt("voice", lang)}

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
