# Geteiltes Session-Memory Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Text-Chat und Voice-Pfad teilen sich eine durchgehende Konversations-History, sodass der gesprochene Pfad den getippten Verlauf kennt (und umgekehrt).

**Architecture:** Gemeinsame Helfer `record_turn`/`recent_history` in `app/session.py` (Fenster 6, Cap 20, Rollen „Du"/„KIRA"). Beide Routen lesen/schreiben denselben `sessions[session_id]`-Store. Der Voice-Pfad bekommt die `session_id` über `active_voice_prefs` (vom Frontend gemeldet); ohne `session_id` Fallback auf das bisherige Verhalten.

**Tech Stack:** FastAPI, pytest, Vanilla-JS. Keine neue Dependency.

---

## Dateiübersicht

| Datei | Aktion | Verantwortung |
|---|---|---|
| `app/session.py` | Modify | `record_turn`, `recent_history`, Konstanten `HISTORY_WINDOW`/`MAX_HISTORY` |
| `app/routes/chat.py` | Modify | Verlauf aus `recent_history`, Schreiben via `record_turn` |
| `app/routes/tavus.py` | Modify | `session_id` in Prefs, Verlauf aus geteiltem Store + Fallback, `record_turn` + `touch_session` |
| `static/index.html` | Modify | `session_id` an Voice-Settings + Session-Start mitsenden |
| `tests/test_prompts.py` | Modify | Unit-Tests `record_turn`/`recent_history` |
| `tests/test_chat_stream.py` | Modify | `test_chat_history_stored`: Rolle „KIRA" |
| `tests/test_tavus.py` | Modify | Voice teilt Session-Memory; `_reset_voice_prefs` setzt `session_id` zurück |

---

### Task 1: `app/session.py` — `record_turn` + `recent_history` (TDD)

**Files:**
- Modify: `app/session.py`
- Test: `tests/test_prompts.py`

- [ ] **Step 1: Failing Tests schreiben**

Am Ende von `tests/test_prompts.py` anhängen:
```python
# ── Geteiltes Session-Memory: record_turn / recent_history ──
def test_record_turn_appends_du_and_kira():
    from app.session import sessions, record_turn
    sessions.pop("s_rt", None)
    record_turn("s_rt", "Frage?", "Antwort.")
    assert sessions["s_rt"] == [
        {"role": "Du", "content": "Frage?"},
        {"role": "KIRA", "content": "Antwort."},
    ]


def test_record_turn_caps_at_max_history():
    from app.session import sessions, record_turn, MAX_HISTORY
    sessions.pop("s_cap", None)
    for i in range(MAX_HISTORY):           # 2*MAX_HISTORY Nachrichten
        record_turn("s_cap", f"q{i}", f"a{i}")
    assert len(sessions["s_cap"]) == MAX_HISTORY
    assert sessions["s_cap"][-1] == {"role": "KIRA", "content": f"a{MAX_HISTORY - 1}"}


def test_recent_history_returns_window():
    from app.session import sessions, record_turn, recent_history, HISTORY_WINDOW
    sessions.pop("s_win", None)
    for i in range(5):                      # 10 Nachrichten
        record_turn("s_win", f"q{i}", f"a{i}")
    assert len(recent_history("s_win")) == HISTORY_WINDOW


def test_recent_history_unknown_session_empty():
    from app.session import recent_history
    assert recent_history("does_not_exist_xyz") == []
```

- [ ] **Step 2: Tests schlagen fehl**

Run: `python -m pytest tests/test_prompts.py -k "record_turn or recent_history" -v`
Expected: FAIL (`cannot import name 'record_turn'`).

- [ ] **Step 3: Implementierung**

In `app/session.py` nach `opening_instruction` (am Dateiende) anhängen:
```python
HISTORY_WINDOW = 6   # Nachrichten, die ins Prompt gehen (Chat + Voice gemeinsam)
MAX_HISTORY = 20     # gespeicherte Nachrichten pro Session (Cap gegen unbegrenztes Wachstum)


def record_turn(session_id: str, user_text: str, answer_text: str) -> None:
    """Hängt User- + KIRA-Turn an die Session-History und trimmt auf MAX_HISTORY."""
    hist = sessions.setdefault(session_id, [])
    hist.append({"role": "Du", "content": user_text})
    hist.append({"role": "KIRA", "content": answer_text})
    del hist[:-MAX_HISTORY]


def recent_history(session_id: str) -> list:
    """Die letzten HISTORY_WINDOW Nachrichten der Session (leer, wenn unbekannt)."""
    return sessions.get(session_id, [])[-HISTORY_WINDOW:]
```

- [ ] **Step 4: Tests grün**

Run: `python -m pytest tests/test_prompts.py -k "record_turn or recent_history" -v`
Expected: PASS (4 Tests).

- [ ] **Step 5: Commit**
```bash
git add app/session.py tests/test_prompts.py
git commit -m "feat(session): record_turn + recent_history (geteilter Store, Fenster 6, Cap 20)"
```

---

### Task 2: `app/routes/chat.py` — geteilten Store nutzen

**Files:**
- Modify: `app/routes/chat.py`
- Test: `tests/test_chat_stream.py`

- [ ] **Step 1: Test `test_chat_history_stored` auf Rolle „KIRA" umstellen**

In `tests/test_chat_stream.py` den Test ersetzen:
```python
@patch("app.rag.collection")
@patch("app.gemini.client")
def test_chat_history_stored(mock_client, mock_collection):
    mock_collection.query.return_value = {"documents": [["Doc"]], "distances": [[0.3]]}
    mock_client.aio.models.generate_content_stream = AsyncMock(
        return_value=make_async_stream(["Antwort A."])
    )

    test_client.post("/chat", json={"message": "Frage A", "session_id": "s_hist2"})

    history = sessions["s_hist2"]
    assert {"role": "Du", "content": "Frage A"} in history
    assert any(m["role"] == "KIRA" and "Antwort A." in m["content"] for m in history)
```

- [ ] **Step 2: Test als failing bestätigen**

Run: `python -m pytest tests/test_chat_stream.py::test_chat_history_stored -v`
Expected: FAIL (History enthält noch Rolle „Bot").

- [ ] **Step 3: `chat.py` umstellen**

In `app/routes/chat.py` die Import-Zeile
```python
from app.session import sessions, touch_session, remember_opening, opening_instruction
```
ersetzen durch:
```python
from app.session import touch_session, remember_opening, opening_instruction, recent_history, record_turn
```

Den Block (Session-Init + Verlauf)
```python
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
```
ersetzen durch:
```python
    touch_session(request.session_id)

    try:
        kontext, kontext_anweisung, beste_distanz = await asyncio.to_thread(
            build_rag_context, request.message, request.studiengang
        )
    except Exception:
        logging.error("/chat RAG Fehler", exc_info=True)

        async def rag_error_stream():
            yield f'data: {json.dumps({"type": "error", "message": "Wissensdatenbank momentan nicht verfügbar."})}\n\n'

        return StreamingResponse(rag_error_stream(), media_type="text/event-stream", headers=SSE_HEADERS)
    verlauf = "\n".join(f"{m['role']}: {m['content']}" for m in recent_history(request.session_id))
```

Den Schreib-Block
```python
        answer = "".join(chat_parts).strip()
        remember_opening(request.session_id, answer)

        sessions[request.session_id].append({"role": "Du", "content": request.message})
        sessions[request.session_id].append({"role": "Bot", "content": answer})
```
ersetzen durch:
```python
        answer = "".join(chat_parts).strip()
        remember_opening(request.session_id, answer)
        record_turn(request.session_id, request.message, answer)
```

- [ ] **Step 4: Test grün + Regression**

Run: `python -m pytest tests/test_chat_stream.py -v`
Expected: alle PASS (inkl. `test_chat_second_request_varies_opening`, das `remember_opening` nutzt).

- [ ] **Step 5: Commit**
```bash
git add app/routes/chat.py tests/test_chat_stream.py
git commit -m "feat(chat): geteilter Session-Store via recent_history/record_turn"
```

---

### Task 3: `app/routes/tavus.py` — session_id + geteilter Store

**Files:**
- Modify: `app/routes/tavus.py`
- Test: `tests/test_tavus.py`

- [ ] **Step 1: Failing Test (Voice teilt Memory) + `_reset_voice_prefs` erweitern**

In `tests/test_tavus.py` die Helferfunktion ersetzen:
```python
def _reset_voice_prefs():
    test_client.post("/tavus/settings", json={"lang": "de", "studiengang": None, "session_id": None})
```

Und am Ende von `tests/test_tavus.py` anhängen:
```python
@patch("app.rag.collection")
@patch("app.gemini.client")
def test_tavus_llm_shares_session_memory(mock_client, mock_collection):
    from app.session import sessions, record_turn
    mock_collection.query.return_value = {"documents": [["Doc"]], "distances": [[0.3]]}
    mock_client.aio.models.generate_content_stream = AsyncMock(
        return_value=make_async_stream(["Gesprochene Antwort."])
    )
    # Getippter Turn liegt schon in der Session
    sessions.pop("s_shared", None)
    record_turn("s_shared", "Getippte Frage zum Praktikum", "Getippte Antwort dazu")
    # Frontend meldet die session_id an den Voice-Pfad
    test_client.post("/tavus/settings", json={"lang": "de", "studiengang": None, "session_id": "s_shared"})
    test_client.post("/tavus/llm", json={
        "messages": [{"role": "user", "content": "Und wie melde ich mich an?"}],
        "stream": True,
    })
    # 1) Getippter Verlauf erscheint im Voice-Prompt
    prompt = mock_client.aio.models.generate_content_stream.call_args.kwargs["contents"]
    assert "Getippte Frage zum Praktikum" in prompt
    # 2) Gesprochener Turn wurde in dieselbe Session geschrieben
    assert {"role": "Du", "content": "Und wie melde ich mich an?"} in sessions["s_shared"]
    assert any(m["role"] == "KIRA" and "Gesprochene Antwort." in m["content"] for m in sessions["s_shared"])
    _reset_voice_prefs()
```

- [ ] **Step 2: Test schlägt fehl**

Run: `python -m pytest tests/test_tavus.py::test_tavus_llm_shares_session_memory -v`
Expected: FAIL (getippter Verlauf nicht im Prompt; gesprochener Turn nicht in `sessions`).

- [ ] **Step 3: Imports + Prefs + Model**

In `app/routes/tavus.py` die Import-Zeile
```python
from app.rag import build_rag_context
```
ergänzen (darunter):
```python
from app.session import recent_history, record_turn, touch_session
```

`active_voice_prefs` erweitern:
```python
active_voice_prefs: dict = {"lang": "de", "studiengang": None}
```
→
```python
active_voice_prefs: dict = {"lang": "de", "studiengang": None, "session_id": None}
```

`TavusPrefsRequest` erweitern:
```python
class TavusPrefsRequest(BaseModel):
    lang: str = "de"
    studiengang: str | None = None
```
→
```python
class TavusPrefsRequest(BaseModel):
    lang: str = "de"
    studiengang: str | None = None
    session_id: str | None = None
```

In `tavus_settings` den Block
```python
    active_voice_prefs["lang"] = prefs.lang
    active_voice_prefs["studiengang"] = prefs.studiengang
    return {"status": "ok", **active_voice_prefs}
```
→
```python
    active_voice_prefs["lang"] = prefs.lang
    active_voice_prefs["studiengang"] = prefs.studiengang
    active_voice_prefs["session_id"] = prefs.session_id
    return {"status": "ok", **active_voice_prefs}
```

In `tavus_session` den Block
```python
    prefs = prefs or TavusPrefsRequest()
    active_voice_prefs["lang"] = prefs.lang
    active_voice_prefs["studiengang"] = prefs.studiengang
```
→
```python
    prefs = prefs or TavusPrefsRequest()
    active_voice_prefs["lang"] = prefs.lang
    active_voice_prefs["studiengang"] = prefs.studiengang
    active_voice_prefs["session_id"] = prefs.session_id
```

- [ ] **Step 4: Verlauf aus geteiltem Store (mit Fallback)**

In `tavus_llm` den Block
```python
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
```
ersetzen durch:
```python
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
```

- [ ] **Step 5: Gesprochenen Turn in den Store schreiben**

In `tavus_llm` die `stream_answer`-Funktion ersetzen:
```python
    async def stream_answer():
        gesendet = False
        buffer = ""
        try:
            async for text in stream_gemini(prompt, 300, VOICE_RETRY_DELAY):
                gesendet = True
                buffer += text
                deltas, buffer = _flush_sentences(buffer)
                for d in deltas:
                    yield f'data: {json.dumps({"choices": [{"delta": {"content": d}, "finish_reason": None}]})}\n\n'
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
        yield f'data: {json.dumps({"choices": [{"delta": {}, "finish_reason": "stop"}]})}\n\n'
        yield 'data: [DONE]\n\n'
```
durch:
```python
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
```

- [ ] **Step 6: Test grün + Regression**

Run: `python -m pytest tests/test_tavus.py -v`
Expected: alle PASS. Insbesondere `test_tavus_llm_includes_conversation_history` (kein `session_id` gesetzt → Fallback auf `request.messages`) und `test_tavus_llm_shares_session_memory` (neuer Test).

- [ ] **Step 7: Commit**
```bash
git add app/routes/tavus.py tests/test_tavus.py
git commit -m "feat(tavus): Voice teilt Session-Memory mit Chat (session_id + record_turn, Fallback)"
```

---

### Task 4: Frontend — `session_id` mitsenden

**Files:**
- Modify: `static/index.html`

- [ ] **Step 1: `pushVoicePrefs` erweitern**

In `static/index.html` (in `pushVoicePrefs`):
```javascript
      body: JSON.stringify({ lang: lang, studiengang: currentStudiengang })
    }).catch(() => {});
```
ersetzen durch:
```javascript
      body: JSON.stringify({ lang: lang, studiengang: currentStudiengang, session_id: sessionId })
    }).catch(() => {});
```

- [ ] **Step 2: Session-Start erweitern**

In `static/index.html` (im `/tavus/session`-Aufruf):
```javascript
        body: JSON.stringify({ lang: lang, studiengang: currentStudiengang })
      });
```
ersetzen durch:
```javascript
        body: JSON.stringify({ lang: lang, studiengang: currentStudiengang, session_id: sessionId })
      });
```

- [ ] **Step 3: Syntax-Check (kein Tooling — visuelle Prüfung)**

`sessionId` ist als `const` definiert (oberhalb des Live-Aufrufzeitpunkts) und steht zur Laufzeit beider Aufrufe bereit. Keine weitere Änderung nötig.

- [ ] **Step 4: Commit**
```bash
git add static/index.html
git commit -m "feat(ui): session_id an Voice-Settings + Session-Start mitsenden"
```

---

### Task 5: Volle Suite + Abschluss

**Files:** keine Änderung — Verifikation.

- [ ] **Step 1: Gesamte Test-Suite**

Run: `python -m pytest tests/ -q`
Expected: alle PASS (bestehende + neue Memory-Tests).

- [ ] **Step 2 (manuell, optional):** Im laufenden Server eine Frage tippen, dann den Avatar starten und sprechend darauf Bezug nehmen — der Avatar sollte den getippten Verlauf kennen.

---

## Self-Review-Notiz

Abgedeckt: `record_turn`/`recent_history` + Konstanten (T1), Chat auf geteilten Store (T2), Voice mit `session_id`/Fallback/Schreiben (T3), Frontend (T4), Verifikation (T5). Namen konsistent: `record_turn`, `recent_history`, `HISTORY_WINDOW`, `MAX_HISTORY`, `active_voice_prefs["session_id"]`. Fallback erhält `test_tavus_llm_includes_conversation_history`. Mid-Stream-Fehler → kein `record_turn` (via `complete`-Flag). Keine Platzhalter.
