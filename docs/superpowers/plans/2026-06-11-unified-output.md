# Unified Output (identische Text/Sprach-Ausgabe) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Chat-Text und gesprochene Avatar-Ausgabe wieder identisch machen (ein Gemini-Call statt zwei), Filler-Code entfernen, Prompt menschlicher gestalten.

**Architecture:** FastAPI-Backend (`main.py`); `/chat` streamt EINEN Gemini-Call als SSE und liefert denselben Text als `voice_text` im done-Event. `KIRA_CHAT_PROMPT`/`KIRA_VOICE_PROMPT` werden zu einem `KIRA_PROMPT` zusammengeführt. Frontend bleibt unverändert.

**Tech Stack:** Python 3.14, FastAPI, google-genai 2.0 (async `client.aio`), pytest (gemockte Module via `tests/conftest.py`).

**Spec:** `docs/superpowers/specs/2026-06-11-unified-output-design.md`

---

## Hinweise für den Ausführenden

1. **Tests (Windows, UTF-8):** `$env:PYTHONIOENCODING="utf-8"; python -m pytest tests/ -v`
2. **Baseline:** 53 Tests, alle grün.
3. `main.client` ist in Tests ein MagicMock; Async-Streaming-Mock-Muster (`make_async_stream`) existiert bereits in `tests/test_chat_stream.py`, `tests/test_liveavatar.py`, `tests/test_tavus.py`.
4. `sessions` und `voice_openings` sind prozess-global — neue Tests brauchen frische `session_id`s.

---

### Task 1: `KIRA_PROMPT` einführen, `/tavus/llm` umstellen

**Files:**
- Modify: `main.py` (Prompt-Konstanten, `/tavus/llm`)
- Modify: `tests/test_prompts.py` (Prompt-Tests ersetzen)

- [ ] **Step 1: Prompt-Tests ersetzen (failing)**

In `tests/test_prompts.py` die vier Tests `test_prompts_share_persona`, `test_persona_mentions_kit`, `test_chat_prompt_has_no_voice_rules`, `test_voice_prompt_has_voice_rules` ersetzen durch:

```python
def test_prompt_shares_persona():
    assert main.KIRA_PROMPT.startswith(main.KIRA_PERSONA)


def test_persona_mentions_kit():
    assert "KIRA" in main.KIRA_PERSONA
    assert "Karlsruher Institut für Technologie" in main.KIRA_PERSONA


def test_prompt_has_voice_rules():
    assert "vorgelesen" in main.KIRA_PROMPT
    assert "Sätzen" in main.KIRA_PROMPT


def test_prompt_is_human():
    assert "warm" in main.KIRA_PROMPT
    assert "Variiere" in main.KIRA_PROMPT
```

Alle anderen Tests in der Datei (build_rag_context, FakeRng/Filler, Opening) bleiben in diesem Task unangetastet.

- [ ] **Step 2: Laufen lassen — muss fehlschlagen**

Run: `$env:PYTHONIOENCODING="utf-8"; python -m pytest tests/test_prompts.py -v`
Expected: FAIL mit `AttributeError: module 'main' has no attribute 'KIRA_PROMPT'`

- [ ] **Step 3: `KIRA_PROMPT` in main.py einführen**

In `main.py` direkt nach `KIRA_VOICE_PROMPT` (vor `KIRA_GREETING`) einfügen:

```python
KIRA_PROMPT = KIRA_PERSONA + """

Antwortregeln (Text wird angezeigt und vorgelesen):
Antworte in zwei bis drei Sätzen, warm und natürlich, wie in einem echten Gespräch unter Studierenden. Geh mit einem halben Satz auf die Situation der Person ein, bevor du die Information gibst — echtes Verständnis statt Floskeln. Schreibe Zahlen und Daten aus (fünfzehnter Januar statt 15.01., zweiundzwanzig Prozent statt 22%). Keine Abkürzungen (schreibe "das heißt" statt "d.h.", "zum Beispiel" statt "z.B."), keine Klammern, keine Listen. Variiere Satzbau und Antwortaufbau von Antwort zu Antwort, damit du nie mechanisch klingst. Natürlicher Gesprächsrhythmus, klingt wie gesprochen."""
```

(`KIRA_CHAT_PROMPT` und `KIRA_VOICE_PROMPT` bleiben in diesem Task bestehen — `/chat` nutzt sie noch bis Task 2.)

In `/tavus/llm` die Prompt-Zeile umstellen:
`prompt = f"""{KIRA_VOICE_PROMPT}` → `prompt = f"""{KIRA_PROMPT}`

- [ ] **Step 4: Alle Tests laufen lassen**

Run: `$env:PYTHONIOENCODING="utf-8"; python -m pytest tests/ -v`
Expected: ALLE PASS (53). `test_tavus_llm_uses_kira_persona` muss weiter grün sein (KIRA_PROMPT enthält "vorgelesen").

- [ ] **Step 5: Commit**

```bash
git add main.py tests/test_prompts.py
git commit -m "feat: unified human KIRA_PROMPT, /tavus/llm switched"
```

---

### Task 2: `/chat` auf Single-Call umbauen, Filler-Code entfernen

**Files:**
- Modify: `main.py` (`/chat` ersetzen; `generate_voice_answer`, Filler-Code, alte Prompt-Konstanten, `import contextlib` entfernen)
- Modify: `tests/test_chat_stream.py`
- Modify: `tests/test_prompts.py` (Filler-Tests entfernen)
- Modify: `tests/test_liveavatar.py` (Persona-Test anpassen)

- [ ] **Step 1: Tests anpassen (failing gegen alten Code)**

1a. In `tests/test_chat_stream.py`:

`test_chat_streams_chunks_then_done` ersetzen durch:

```python
@patch("main.collection")
@patch("main.client")
def test_chat_streams_chunks_then_done(mock_client, mock_collection):
    mock_collection.query.return_value = {
        "documents": [["KIT Bewerbungsfrist 15. Juli."]],
        "distances": [[0.3]]
    }
    mock_client.aio.models.generate_content_stream = AsyncMock(
        return_value=make_async_stream(["Die Frist ", "ist der fünfzehnte Juli."])
    )
    mock_client.aio.models.generate_content = AsyncMock()

    response = test_client.post("/chat", json={"message": "Frist?", "session_id": "s_uni1"})

    assert response.status_code == 200
    assert "text/event-stream" in response.headers["content-type"]
    events = sse_events(response.text)
    chunks = [e for e in events if e["type"] == "chunk"]
    dones = [e for e in events if e["type"] == "done"]
    assert [c["text"] for c in chunks] == ["Die Frist ", "ist der fünfzehnte Juli."]
    assert len(dones) == 1
    # Text und Sprache identisch: voice_text == zusammengesetzte Chunks
    assert dones[0]["voice_text"] == "Die Frist ist der fünfzehnte Juli."
    assert dones[0]["source"] == "Wissensbasis"
    assert isinstance(dones[0]["latency_ms"], int)
    # Nur EIN Gemini-Call — kein zweiter Voice-Call
    assert mock_client.aio.models.generate_content.call_count == 0
```

`test_chat_dual_prompts_share_context` ersetzen durch:

```python
@patch("main.collection")
@patch("main.client")
def test_chat_single_call_with_context(mock_client, mock_collection):
    mock_collection.query.return_value = {
        "documents": [["EINDEUTIGER_KONTEXT_42"]],
        "distances": [[0.3]]
    }
    mock_client.aio.models.generate_content_stream = AsyncMock(
        return_value=make_async_stream(["Antwort."])
    )
    mock_client.aio.models.generate_content = AsyncMock()

    test_client.post("/chat", json={"message": "Test", "session_id": "s_single"})

    prompt = mock_client.aio.models.generate_content_stream.call_args.kwargs["contents"]
    assert "EINDEUTIGER_KONTEXT_42" in prompt
    assert "vorgelesen" in prompt
    assert mock_client.aio.models.generate_content.call_count == 0
    assert mock_collection.query.call_count == 1
```

`test_chat_voice_fallback_on_error` KOMPLETT LÖSCHEN (es gibt keinen zweiten Call mehr).

`test_chat_error_event_on_stream_failure` ersetzen durch (nur die generate_content-Mock-Zeile entfällt):

```python
@patch("main.collection")
@patch("main.client")
def test_chat_error_event_on_stream_failure(mock_client, mock_collection):
    mock_collection.query.return_value = {"documents": [["Doc"]], "distances": [[0.3]]}
    mock_client.aio.models.generate_content_stream = AsyncMock(side_effect=RuntimeError("boom"))

    response = test_client.post("/chat", json={"message": "Test", "session_id": "s_err2"})

    events = sse_events(response.text)
    assert any(e["type"] == "error" for e in events)
    assert not any(e["type"] == "done" for e in events)
```

`test_chat_history_stored` ersetzen durch:

```python
@patch("main.collection")
@patch("main.client")
def test_chat_history_stored(mock_client, mock_collection):
    mock_collection.query.return_value = {"documents": [["Doc"]], "distances": [[0.3]]}
    mock_client.aio.models.generate_content_stream = AsyncMock(
        return_value=make_async_stream(["Antwort A."])
    )

    test_client.post("/chat", json={"message": "Frage A", "session_id": "s_hist2"})

    history = main.sessions["s_hist2"]
    assert {"role": "Du", "content": "Frage A"} in history
    assert any(m["role"] == "Bot" and "Antwort A." in m["content"] for m in history)
```

`test_chat_second_request_varies_opening` ersetzen durch (Opening kommt jetzt aus dem gestreamten Text; Assertion auf den Stream-Prompt):

```python
@patch("main.collection")
@patch("main.client")
def test_chat_second_request_varies_opening(mock_client, mock_collection):
    mock_collection.query.return_value = {"documents": [["Doc"]], "distances": [[0.3]]}
    mock_client.aio.models.generate_content_stream = AsyncMock(
        side_effect=lambda **kwargs: make_async_stream(["Genau, das ist richtig."])
    )

    test_client.post("/chat", json={"message": "Frage eins", "session_id": "s_vary2"})
    test_client.post("/chat", json={"message": "Frage zwei", "session_id": "s_vary2"})

    prompt_2 = mock_client.aio.models.generate_content_stream.call_args.kwargs["contents"]
    assert 'Beginne deine Antwort nicht mit dem Wort "Genau"' in prompt_2
```

1b. In `tests/test_prompts.py`: die Klasse `FakeRng`, die Konstante `LONG_TEXT` und die drei Tests `test_filler_added_for_long_answers`, `test_no_filler_when_random_above_threshold`, `test_no_filler_for_short_answers` KOMPLETT LÖSCHEN. Die Opening-Tests (`test_remember_and_instruct_opening`, `test_no_instruction_without_history`) bleiben.

1c. In `tests/test_liveavatar.py` `test_chat_uses_kira_persona` ersetzen durch (Sprechregeln jetzt erwartet, kein Voice-Mock mehr):

```python
@patch("main.collection")
@patch("main.client")
def test_chat_uses_kira_persona(mock_client, mock_collection):
    mock_collection.query.return_value = {
        "documents": [["KIT Bewerbungsfrist 15. Juli."]],
        "distances": [[0.3]]
    }
    mock_client.aio.models.generate_content_stream = AsyncMock(
        return_value=make_async_stream(["Die Bewerbungsfrist ist am fünfzehnten Juli."])
    )

    test_client.post("/chat", json={"message": "Wann ist die Bewerbungsfrist?", "session_id": "test_persona2"})

    prompt = mock_client.aio.models.generate_content_stream.call_args.kwargs["contents"]
    assert isinstance(prompt, str) and len(prompt) > 0
    assert "KIRA" in prompt
    assert "Karlsruher Institut für Technologie" in prompt
    # Einheitlicher Prompt: Sprechregeln sind jetzt Teil des /chat-Prompts
    assert "vorgelesen" in prompt
```

In `test_chat_context_limit_400` nur die Zeile `mock_client.aio.models.generate_content = AsyncMock(return_value=MagicMock(text="Antwort."))` LÖSCHEN (Rest unverändert).

- [ ] **Step 2: Laufen lassen — geänderte Tests müssen fehlschlagen**

Run: `$env:PYTHONIOENCODING="utf-8"; python -m pytest tests/test_chat_stream.py tests/test_liveavatar.py -v`
Expected: u.a. `test_chat_streams_chunks_then_done` FAIL (voice_text ist noch die Voice-Version), `test_chat_single_call_with_context` FAIL (generate_content wird noch aufgerufen).

- [ ] **Step 3: main.py umbauen**

3a. LÖSCHEN: `import contextlib` UND `import random` (beide werden nach dem Umbau nirgends mehr genutzt — random wurde nur von `maybe_add_filler` verwendet).

3b. LÖSCHEN: die Konstanten `KIRA_CHAT_PROMPT` und `KIRA_VOICE_PROMPT` (komplett, inkl. Strings).

3c. LÖSCHEN: den Block `# ── Natürlichkeit: Filler & Satzanfang-Variation ──────────` nur teilweise — `FILLERS`, `FILLER_PROBABILITY`, `FILLER_MIN_WORDS` und die Funktion `maybe_add_filler` entfernen. `voice_openings`, `remember_opening`, `opening_instruction` BLEIBEN.

3d. LÖSCHEN: die Funktion `generate_voice_answer` (komplett). `VOICE_RETRY_DELAY` BLEIBT (wird von `/tavus/llm` genutzt) — ggf. mit dem Kommentar `# Retry-Delay für /tavus/llm` versehen.

3e. Den kompletten `/chat`-Endpoint ersetzen durch:

```python
# ── Chat Endpoint (SSE-Streaming, einheitliche Ausgabe) ───
@app.post("/chat")
async def chat(request: ChatRequest):
    session_id = request.session_id
    user_input = request.message

    if session_id not in sessions:
        sessions[session_id] = []
    chat_history = sessions[session_id]

    kontext, kontext_anweisung, beste_distanz = build_rag_context(user_input)
    verlauf = "\n".join(f"{m['role']}: {m['content']}" for m in chat_history[-4:])

    prompt = f"""{KIRA_PROMPT}{opening_instruction(session_id)}

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

    return StreamingResponse(event_stream(), media_type="text/event-stream")
```

- [ ] **Step 4: Alle Tests laufen lassen**

Run: `$env:PYTHONIOENCODING="utf-8"; python -m pytest tests/ -v`
Expected: ALLE PASS. Erwartete Testanzahl: 49 (53 minus 3 Filler-Tests minus 1 Voice-Fallback-Test, plus 0 neue — `test_prompt_is_human` kam in Task 1 dazu, der ersetzte Block in Task 1 war 4→4).

- [ ] **Step 5: Grep-Kontrolle**

`maybe_add_filler|FILLERS|generate_voice_answer|KIRA_CHAT_PROMPT|KIRA_VOICE_PROMPT|contextlib|import random` darf in `main.py` und `tests/` KEINE Treffer mehr haben.

- [ ] **Step 6: Commit**

```bash
git add main.py tests/test_chat_stream.py tests/test_prompts.py tests/test_liveavatar.py
git commit -m "feat: single-call /chat, identical text and voice output, fillers removed"
```

---

### Task 3: Gesamtverifikation + Smoke-Test

- [ ] **Step 1: Kompletter Testlauf**

Run: `$env:PYTHONIOENCODING="utf-8"; python -m pytest tests/ -v`
Expected: 49 passed, 0 failed.

- [ ] **Step 2: Live-Smoke-Test**

1. Server starten: `.\start.ps1` (Hintergrund, Logs umleiten)
2. SSE prüfen (JSON-Body über Temp-Datei wegen PowerShell-Quoting):
   ```powershell
   Set-Content -Path "$env:TEMP\smoke.json" -Value '{"message":"Wie beantrage ich Beurlaubung?","session_id":"smoke_uni"}' -Encoding utf8
   curl.exe -s -N -X POST http://localhost:8000/chat -H "Content-Type: application/json" --data "@$env:TEMP\smoke.json" --max-time 40
   ```
3. Erwartung: mehrere `chunk`-Events; `done.voice_text` == exakt die zusammengesetzten Chunk-Texte (identisch); Antwort klingt natürlich/gesprochen (Zahlen ausgeschrieben); 2–3 Sätze; Latenz unter ~1500ms.
4. Server stoppen, Logs löschen.

- [ ] **Step 3: Abschluss-Commit (falls offene Änderungen)**

```bash
git status
git add -A
git commit -m "chore: verification pass for unified output"
```
