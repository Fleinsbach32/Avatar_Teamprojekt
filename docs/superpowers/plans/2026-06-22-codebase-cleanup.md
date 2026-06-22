# Codebase Cleanup & Optimization Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Auth/Passwort entfernen, httpx Connection-Pooling einführen und toten Code löschen.

**Architecture:** Drei unabhängige Änderungen: (1) HTTP Basic Auth komplett herauslösen aus main.py, tavus.py und conftest, (2) geteilter httpx.AsyncClient als Modul-Variable statt per-Request-Erstellung, (3) funktionsloser Code in avatar.py, chat.py und tavus.py entfernen.

**Tech Stack:** FastAPI, httpx, pytest, unittest.mock

---

## File Map

| File | Aktion | Grund |
|------|--------|-------|
| `app/auth.py` | Delete | Auth wird entfernt |
| `app/main.py` | Modify | Auth-Import + Deps entfernen, httpx-Cleanup in lifespan |
| `app/routes/tavus.py` | Modify | Auth-Import + Deps entfernen, `_http` Singleton, `json` Import fixen |
| `app/routes/avatar.py` | Modify | `_VALID_PROVIDERS` entfernen |
| `app/routes/chat.py` | Modify | `json` Import fixen, Zwischenvariablen entfernen |
| `tests/conftest.py` | Modify | `_bypass_basic_auth` Fixture entfernen |
| `tests/test_auth.py` | Delete | Testet nur noch gelöschte Auth-Logik |
| `tests/test_tavus.py` | Modify | httpx-Mocks von AsyncClient-Pattern auf `_http`-Patch umstellen |

---

## Task 1: Auth entfernen

**Files:**
- Delete: `app/auth.py`
- Delete: `tests/test_auth.py`
- Modify: `tests/conftest.py`
- Modify: `app/main.py`
- Modify: `app/routes/tavus.py`

- [ ] **Step 1.1: `tests/test_auth.py` löschen**

```bash
rm "tests/test_auth.py"
```

- [ ] **Step 1.2: `_bypass_basic_auth` aus `tests/conftest.py` entfernen**

Ersetze den gesamten Inhalt von `tests/conftest.py`:

```python
import sys
from unittest.mock import MagicMock

sys.modules.update({
    'chromadb': MagicMock(),
    'chromadb.utils': MagicMock(),
    'chromadb.utils.embedding_functions': MagicMock(),
    'google': MagicMock(),
    'google.genai': MagicMock(),
    'google.genai.types': MagicMock(),
    'sentence_transformers': MagicMock(),
    'torch': MagicMock(),
})
```

- [ ] **Step 1.3: Tests ausführen — müssen FEHLSCHLAGEN (Auth noch aktiv)**

```
python -m pytest tests/ -q --ignore=tests/test_auth.py
```

Erwartetes Ergebnis: Mehrere Failures mit `401` oder `ImportError` weil Auth noch aktiv aber Bypass entfernt.

- [ ] **Step 1.4: `app/auth.py` löschen**

```bash
rm "app/auth.py"
```

- [ ] **Step 1.5: `app/main.py` komplett ersetzen**

```python
import logging
from contextlib import asynccontextmanager

from dotenv import load_dotenv
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse

load_dotenv()

from app.rag import collection
from app.routes import avatar, chat, tavus


@asynccontextmanager
async def lifespan(app: FastAPI):
    try:
        collection.query(query_texts=["Warmup"], n_results=1)
    except Exception as e:
        logging.warning(f"ChromaDB Warmup fehlgeschlagen: {e}")
    yield
    await tavus._http.aclose()


app = FastAPI(lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(avatar.router)
app.include_router(chat.router)
app.include_router(tavus.router)


@app.get("/health")
def health():
    return {"status": "ok"}


@app.get("/")
async def serve_index():
    return FileResponse("static/index.html")
```

- [ ] **Step 1.6: Auth-Imports und `dependencies=[Depends(check_auth)]` aus `app/routes/tavus.py` entfernen**

Ersetze die Import-Zeilen am Anfang der Datei (Zeilen 1-16):

```python
import os
import asyncio
import json
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
```

Entferne `dependencies=[Depends(check_auth)]` aus den vier Route-Dekoratoren:

```python
# Zeile 73 — vorher:
@router.post("/tavus/settings", dependencies=[Depends(check_auth)])
# nachher:
@router.post("/tavus/settings")

# Zeile 81 — vorher:
@router.post("/tavus/session", dependencies=[Depends(check_auth)])
# nachher:
@router.post("/tavus/session")

# Zeile 122 — vorher:
@router.post("/tavus/end", dependencies=[Depends(check_auth)])
# nachher:
@router.post("/tavus/end")

# Zeile 137 — vorher:
@router.post("/tavus/message", dependencies=[Depends(check_auth)])
# nachher:
@router.post("/tavus/message")
```

Ersetze außerdem alle `json_lib.dumps` durch `json.dumps` in tavus.py (alle Vorkommen in `tavus_llm` und `empty_stream`).

- [ ] **Step 1.7: Tests ausführen — müssen BESTEHEN**

```
python -m pytest tests/ -q
```

Erwartetes Ergebnis: Gleiche Anzahl Passes wie vor dem Task (pre-existing failures bleiben, keine neuen).

- [ ] **Step 1.8: Commit**

```bash
git add app/main.py app/routes/tavus.py tests/conftest.py
git rm app/auth.py tests/test_auth.py
git commit -m "feat: remove HTTP Basic Auth"
```

---

## Task 2: httpx Shared Client

**Files:**
- Modify: `app/routes/tavus.py` (Modul-Variable + 3 Aufrufe umstellen)
- Modify: `tests/test_tavus.py` (6 Mocks aktualisieren)

- [ ] **Step 2.1: Test-Mocks für httpx in `tests/test_tavus.py` aktualisieren**

Ersetze alle 6 Tests die `@patch("app.routes.tavus.httpx.AsyncClient")` verwenden:

**`test_tavus_session_success`** (derzeit ~Zeile 39):
```python
@patch("app.routes.tavus._http")
def test_tavus_session_success(mock_http):
    mock_http.post = AsyncMock(return_value=make_mock_response(200, {
        "conversation_id": "conv_abc123",
        "conversation_url": "https://tavus.daily.co/abc123"
    }))
    with patch.dict(os.environ, {
        "TAVUS_API_KEY": "real-key",
        "TAVUS_REPLICA_ID": "replica_xyz",
        "TAVUS_PERSONA_ID": ""
    }):
        response = test_client.post("/tavus/session")
    assert response.status_code == 200
    data = response.json()
    assert data["conversation_id"] == "conv_abc123"
    assert data["conversation_url"] == "https://tavus.daily.co/abc123"
    call_kwargs = mock_http.post.call_args.kwargs
    assert call_kwargs["headers"]["x-api-key"] == "real-key"
    assert call_kwargs["json"]["replica_id"] == "replica_xyz"
    assert call_kwargs["json"]["custom_greeting"] == ""
```

**`test_tavus_session_api_error`** (derzeit ~Zeile 72):
```python
@patch("app.routes.tavus._http")
def test_tavus_session_api_error(mock_http):
    mock_http.post = AsyncMock(return_value=make_mock_response(401, {"error": "unauthorized"}))
    with patch.dict(os.environ, {"TAVUS_API_KEY": "bad-key"}):
        response = test_client.post("/tavus/session")
    assert response.status_code == 401
```

**`test_tavus_session_timeout`** (derzeit ~Zeile 83):
```python
@patch("app.routes.tavus._http")
def test_tavus_session_timeout(mock_http):
    import httpx as real_httpx
    mock_http.post = AsyncMock(side_effect=real_httpx.TimeoutException("timeout"))
    response = test_client.post("/tavus/session")
    assert response.status_code == 504
```

**`test_tavus_end_success`** (derzeit ~Zeile 94):
```python
@patch("app.routes.tavus._http")
def test_tavus_end_success(mock_http):
    mock_http.delete = AsyncMock(return_value=make_mock_response(200, {}))
    response = test_client.post("/tavus/end", json={"conversation_id": "conv_abc123"})
    assert response.status_code == 200
    assert response.json() == {"status": "ended"}
    call_url = mock_http.delete.call_args.args[0]
    assert "conv_abc123" in call_url
```

**`test_tavus_message_success`** (derzeit ~Zeile 192):
```python
@patch("app.routes.tavus._http")
def test_tavus_message_success(mock_http):
    mock_http.post = AsyncMock(return_value=make_mock_response(200, {}))
    with patch.dict(os.environ, {"TAVUS_API_KEY": "real-key"}):
        response = test_client.post("/tavus/message", json={
            "conversation_id": "conv_abc123",
            "message": "Wie melde ich mich für Prüfungen an?"
        })
    assert response.status_code == 200
    assert response.json() == {"status": "sent"}
    call_args = mock_http.post.call_args
    assert "conv_abc123" in call_args.args[0]
    assert call_args.kwargs["json"]["message"] == "Wie melde ich mich für Prüfungen an?"
```

**`test_tavus_message_timeout`** (derzeit ~Zeile 227):
```python
@patch("app.routes.tavus._http")
def test_tavus_message_timeout(mock_http):
    import httpx as real_httpx
    mock_http.post = AsyncMock(side_effect=real_httpx.TimeoutException("timeout"))
    response = test_client.post("/tavus/message", json={
        "conversation_id": "conv_abc123",
        "message": "Hallo"
    })
    assert response.status_code == 504
```

- [ ] **Step 2.2: Tests ausführen — müssen FEHLSCHLAGEN**

```
python -m pytest tests/test_tavus.py -q
```

Erwartetes Ergebnis: Die 6 geänderten Tests schlagen fehl (`AttributeError: module has no attribute '_http'`).

- [ ] **Step 2.3: `_http` Singleton in `app/routes/tavus.py` hinzufügen**

Füge nach `router = APIRouter()` (aktuell Zeile 17) folgendes ein:

```python
_http = httpx.AsyncClient()
```

- [ ] **Step 2.4: `tavus_session` — `async with`-Block durch direkte `_http`-Aufrufe ersetzen**

Ersetze (Zeilen 102-119 in der originalen Datei, nach Schritt 1 verschoben):

```python
# vorher:
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

# nachher:
    try:
        res = await _http.post(
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
```

- [ ] **Step 2.5: `tavus_end` — `async with`-Block ersetzen**

```python
# vorher:
    async with httpx.AsyncClient() as http:
        try:
            await http.delete(
                f"https://tavusapi.com/v2/conversations/{request.conversation_id}",
                headers={"x-api-key": api_key},
                timeout=10.0,
            )
        except httpx.TimeoutException:
            pass

# nachher:
    try:
        await _http.delete(
            f"https://tavusapi.com/v2/conversations/{request.conversation_id}",
            headers={"x-api-key": api_key},
            timeout=10.0,
        )
    except httpx.TimeoutException:
        pass
```

- [ ] **Step 2.6: `tavus_message` — `async with`-Block ersetzen**

```python
# vorher:
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

# nachher:
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
```

- [ ] **Step 2.7: Tests ausführen — müssen BESTEHEN**

```
python -m pytest tests/test_tavus.py -q
```

Erwartetes Ergebnis: Alle Tavus-Tests PASSED (außer pre-existing failures).

- [ ] **Step 2.8: Alle Tests ausführen**

```
python -m pytest tests/ -q
```

Erwartetes Ergebnis: Gleiche Ergebnisse wie nach Task 1.

- [ ] **Step 2.9: Commit**

```bash
git add app/routes/tavus.py tests/test_tavus.py
git commit -m "perf: shared httpx.AsyncClient für Tavus API Connection-Pooling"
```

---

## Task 3: Dead Code entfernen

**Files:**
- Modify: `app/routes/avatar.py`
- Modify: `app/routes/chat.py`

- [ ] **Step 3.1: Test für `avatar_config` schreiben**

Füge in `tests/test_tavus.py` am Ende an:

```python
def test_avatar_config_returns_tavus():
    response = test_client.get("/avatar/config")
    assert response.status_code == 200
    assert response.json() == {"provider": "tavus"}
```

- [ ] **Step 3.2: Test ausführen — muss BESTEHEN (Verhalten ändert sich nicht)**

```
python -m pytest tests/test_tavus.py::test_avatar_config_returns_tavus -v
```

Erwartetes Ergebnis: PASSED (Verhaltenstest, der vor und nach dem Refactoring gleich bleibt).

- [ ] **Step 3.3: `app/routes/avatar.py` vereinfachen**

Ersetze den gesamten Inhalt:

```python
import os
from fastapi import APIRouter

router = APIRouter()


@router.get("/avatar/config")
def avatar_config():
    return {"provider": os.getenv("AVATAR_PROVIDER", "tavus").lower()}
```

- [ ] **Step 3.4: Test nach Refactoring ausführen — muss BESTEHEN**

```
python -m pytest tests/test_tavus.py::test_avatar_config_returns_tavus -v
```

Erwartetes Ergebnis: PASSED.

- [ ] **Step 3.5: `app/routes/chat.py` bereinigen**

Ersetze den gesamten Inhalt:

```python
import asyncio
import json
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
    touch_session(request.session_id)
    if request.session_id not in sessions:
        sessions[request.session_id] = []
    chat_history = sessions[request.session_id]

    kontext, kontext_anweisung, beste_distanz = await asyncio.to_thread(
        build_rag_context, request.message, request.studiengang
    )
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
            stream = await client.aio.models.generate_content_stream(
                model="gemini-2.5-flash",
                contents=prompt,
                config=gemini_config(400),
            )
            async for chunk in stream:
                if chunk.text:
                    chat_parts.append(chunk.text)
                    yield f'data: {json.dumps({"type": "chunk", "text": chunk.text})}\n\n'
        except Exception as e:
            logging.warning(f"/chat Gemini Fehler: {e}")
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
```

- [ ] **Step 3.6: Alle Tests ausführen**

```
python -m pytest tests/ -q
```

Erwartetes Ergebnis: Gleiche Ergebnisse wie nach Task 2.

- [ ] **Step 3.7: Commit**

```bash
git add app/routes/avatar.py app/routes/chat.py tests/test_tavus.py
git commit -m "refactor: remove dead code (_VALID_PROVIDERS, json alias, unused vars)"
```

---

## Fertig

Nach Task 3 ist die Codebase bereinigt. Verifikation:

```
python -m pytest tests/ -q
```

Alle Tests müssen grün sein (pre-existing failures ausgenommen).
