import os
import asyncio
import json
import logging
import re
from urllib.parse import quote

import httpx
from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field, field_validator

from app.gemini import SSE_HEADERS, stream_gemini, GeminiUnavailable, GeminiMidStreamError
from app.prompts import build_prompt, VOICE_CONTEXT
from app.rag import build_rag_context
from app.session import recent_history, record_turn, touch_session

router = APIRouter()
_http = httpx.AsyncClient()

VOICE_RETRY_DELAY = 2

# Aktive Voice-Einstellungen. Tavus ruft /tavus/llm serverseitig ohne UI-Kontext
# auf, daher merken wir uns hier die zuletzt im Frontend gewählte Sprache und den
# Studiengang. Bei lokalem Einzel-Session-Betrieb (ein Avatar gleichzeitig) genügt
# ein globaler Zustand; das Frontend aktualisiert ihn bei Session-Start und bei
# jeder Änderung von Sprache oder Studiengang.
active_voice_prefs: dict = {"lang": "de", "studiengang": None, "session_id": None}

# URLs/Domains (z.B. campus.kit.edu) werden vorgelesen mit "punkt" statt Punkt,
# sonst stockt die TTS an jedem Punkt. TLD muss aus Buchstaben bestehen, damit
# Dezimalzahlen (2.5) nicht fälschlich getroffen werden.
_DOMAIN_RE = re.compile(r"\b[a-z0-9-]+(?:\.[a-z0-9-]+)*\.[a-z]{2,}\b", re.IGNORECASE)
# Vollständiger Satz: bis zum ersten Satzzeichen, gefolgt von Whitespace.
_SENTENCE_END_RE = re.compile(r"(.+?[.!?]+[\)\]\"']*)\s+", re.DOTALL)


def _tts_normalize(text: str) -> str:
    """Macht TTS-feindliche Tokens vorlesefreundlich (Domains → 'punkt')."""
    return _DOMAIN_RE.sub(lambda m: m.group(0).replace(".", " punkt "), text)


def _flush_sentences(buf: str, final: bool = False) -> tuple[list[str], str]:
    """Zerlegt den Puffer in vollständige Sätze. Gibt (fertige_sätze, rest) zurück.
    URLs werden vor der Satztrennung normalisiert, damit ihre Punkte keine
    falschen Satzgrenzen erzeugen. Bei final=True wird der Rest mit ausgegeben."""
    buf = _tts_normalize(buf)
    out: list[str] = []
    while True:
        m = _SENTENCE_END_RE.match(buf)
        if not m:
            break
        sentence = m.group(1).strip()
        if sentence:
            out.append(sentence + " ")
        buf = buf[m.end():]
    if final and buf.strip():
        out.append(buf.strip())
        buf = ""
    return out, buf


class TavusPrefsRequest(BaseModel):
    lang: str = "de"
    studiengang: str | None = None
    session_id: str | None = None


class TavusEndRequest(BaseModel):
    conversation_id: str


class TavusMessageRequest(BaseModel):
    conversation_id: str
    message: str = Field(..., max_length=2000)

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


@router.post("/tavus/settings")
async def tavus_settings(prefs: TavusPrefsRequest):
    """Aktualisiert Sprache/Studiengang für den laufenden Voice-Pfad."""
    active_voice_prefs["lang"] = prefs.lang
    active_voice_prefs["studiengang"] = prefs.studiengang
    active_voice_prefs["session_id"] = prefs.session_id
    return {"status": "ok", **active_voice_prefs}


@router.post("/tavus/session")
async def tavus_session(prefs: TavusPrefsRequest | None = None):
    api_key = os.getenv("TAVUS_API_KEY")
    if not api_key:
        raise HTTPException(status_code=500, detail="TAVUS_API_KEY nicht gesetzt")

    prefs = prefs or TavusPrefsRequest()
    active_voice_prefs["lang"] = prefs.lang
    active_voice_prefs["studiengang"] = prefs.studiengang
    active_voice_prefs["session_id"] = prefs.session_id

    replica_id = os.getenv("TAVUS_REPLICA_ID", "")
    persona_id = os.getenv("TAVUS_PERSONA_ID", "")

    body: dict = {
        "replica_id": replica_id,
        "conversational_context": VOICE_CONTEXT.get(prefs.lang, VOICE_CONTEXT["de"]),
        "custom_greeting": "",
    }
    if persona_id:
        body["persona_id"] = persona_id

    try:
        res = await _http.post(
            "https://tavusapi.com/v2/conversations",
            headers={"x-api-key": api_key, "Content-Type": "application/json"},
            json=body,
            timeout=15.0,
        )
        data = res.json()
        if res.status_code in (200, 201):
            logging.info(f"Tavus API status: {res.status_code}")
        else:
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
    try:
        await _http.delete(
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

    try:
        res = await _http.post(
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
            yield f'data: {json.dumps({"choices":[{"delta":{},"finish_reason":"stop"}]})}\n\n'
            yield 'data: [DONE]\n\n'
        return StreamingResponse(empty_stream(), media_type="text/event-stream", headers=SSE_HEADERS)

    # Tavus sendet keine UI-Felder mit, daher kommen Sprache/Studiengang aus den
    # zuletzt im Frontend gesetzten Voice-Einstellungen.
    lang = active_voice_prefs["lang"]
    studiengang = active_voice_prefs["studiengang"]
    sid = active_voice_prefs["session_id"]

    kontext, kontext_anweisung, _ = await asyncio.to_thread(
        build_rag_context, user_message, studiengang
    )

    if sid:
        # Geteilter Store: enthält getippte UND gesprochene Turns
        touch_session(sid)
        verlauf = "\n".join(f"{m['role']}: {m['content']}" for m in recent_history(sid))
    else:
        # Fallback ohne session_id: Verlauf aus den von Tavus gesendeten Nachrichten
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
        complete = False
        buffer = ""
        full_answer = ""
        try:
            async for text in stream_gemini(prompt, 300, VOICE_RETRY_DELAY):
                gesendet = True
                full_answer += text
                buffer += text
                deltas, buffer = _flush_sentences(buffer)
                for d in deltas:
                    yield f'data: {json.dumps({"choices": [{"delta": {"content": d}, "finish_reason": None}]})}\n\n'
            complete = True
        except GeminiMidStreamError:
            pass  # bereits gesendete Sätze stehen; Rest wird unten geflusht
        except GeminiUnavailable:
            gesendet = False
        if gesendet:
            # Restpuffer (letzter Satz ohne abschließendes Whitespace) ausgeben
            deltas, _ = _flush_sentences(buffer, final=True)
            for d in deltas:
                yield f'data: {json.dumps({"choices": [{"delta": {"content": d}, "finish_reason": None}]})}\n\n'
        else:
            yield f'data: {json.dumps({"choices": [{"delta": {"content": "Service momentan nicht verfügbar."}, "finish_reason": None}]})}\n\n'
        # Nur vollständige Antworten in den geteilten Store schreiben (keine halben)
        if complete and sid and full_answer.strip():
            record_turn(sid, user_message, full_answer.strip())
        yield f'data: {json.dumps({"choices": [{"delta": {}, "finish_reason": "stop"}]})}\n\n'
        yield 'data: [DONE]\n\n'

    return StreamingResponse(stream_answer(), media_type="text/event-stream", headers=SSE_HEADERS)
