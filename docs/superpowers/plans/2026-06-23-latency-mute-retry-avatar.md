# Latenz-Profiling, Mute-Button, Auto-Retry & Avatar-Pausen — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** RAG-Latenz messbar machen, den Spracheingabe-Button entfernen, einen Frontend-Auto-Retry bei "Service momentan nicht verfügbar" hinzufügen und die unnatürlichen Sprechpausen des Avatars beheben.

**Architecture:** Vier unabhängige Tasks. Task 1 fügt Phasen-Timing-Logging in `build_rag_context` ein (nur messen, keine Optimierung). Task 2 entfernt den `ttsBtn`-Mikrofon-Button samt JS/CSS aus dem Frontend. Task 3 refaktoriert `sendMessage` in `sendMessage` + `attemptSend(text, attempt)` mit stillem Retry. Task 4 puffert den `/tavus/llm`-Stream in ganze Sätze und macht URLs vorlesefreundlich.

**Tech Stack:** FastAPI, ChromaDB, sentence-transformers CrossEncoder, Google Gemini SDK, pytest, Vanilla-JS-Frontend (`static/index.html`), Tavus CVI (Daily).

---

## File Map

| Datei | Änderung |
|-------|----------|
| `app/rag.py` | `import time`; Phasen-Timing (query/rerank) + `[RAG-TIMING]`-Log im zwei- und einstufigen Pfad |
| `tests/test_rag_reranking.py` | 1 neuer Test: `[RAG-TIMING]`-Log wird emittiert |
| `static/index.html` | Task 2: `ttsBtn`-Button + Recognition-JS + `.tts-btn`-CSS entfernen. Task 3: `sendMessage`/`attemptSend`-Refactor mit Auto-Retry |
| `app/routes/tavus.py` | `import re`; `_tts_normalize` + `_flush_sentences` Helfer; `stream_answer()` puffert Sätze |
| `tests/test_tavus.py` | `test_tavus_llm_streams_chunks` aktualisieren; 3 neue Tests (Normalisierung, Satz-Puffern, idempotente Normalisierung) |

**Hinweis Frontend-Tests:** Für `static/index.html` existiert kein JS-Test-Framework. Task 2 und Task 3 werden manuell verifiziert (Schritte angegeben). Backend-Tasks 1 und 4 sind per pytest abgedeckt.

---

## Task 1: `app/rag.py` — RAG-Phasen-Timing loggen

**Files:**
- Modify: `app/rag.py:1-4` (Imports), `app/rag.py:274-304` (zwei-/einstufiger Pfad)
- Test: `tests/test_rag_reranking.py`

**Ziel:** Sichtbar machen, wie viel Zeit ChromaDB-Query vs. CrossEncoder-Reranking kostet. Keine Optimierung in diesem Task — nur Messung.

### Schritte

- [ ] **Step 1: Failing-Test schreiben**

Datei `tests/test_rag_reranking.py` — ans Ende anhängen:

```python
# ── RAG-Timing wird geloggt ──────────────────────────────────────────────────

def test_single_stage_logs_rag_timing(caplog):
    import logging
    from unittest.mock import patch
    from app.rag import build_rag_context

    with patch("app.rag.collection") as mock_coll:
        mock_coll.query.return_value = {
            "documents": [["KIT Info zur Bewerbung am Campus."]],
            "distances": [[0.3]],
        }
        with caplog.at_level(logging.INFO):
            build_rag_context("Wie bewerbe ich mich?")  # kein Studiengang → einstufig

    assert any("[RAG-TIMING]" in r.message for r in caplog.records)
```

- [ ] **Step 2: Test als failing bestätigen**

```bash
cd c:/Users/lucat/Downloads/Avatar_Teamprojekt-feature-tavus
python -m pytest tests/test_rag_reranking.py::test_single_stage_logs_rag_timing -v
```

Erwartete Ausgabe: FAILED (kein `[RAG-TIMING]` im Log).

- [ ] **Step 3: `import time` ergänzen**

Datei: `app/rag.py`, Zeilen 1-4. Ändere:

```python
import logging
import os
import re
from concurrent.futures import ThreadPoolExecutor
```

zu:

```python
import logging
import os
import re
import time
from concurrent.futures import ThreadPoolExecutor
```

- [ ] **Step 4: Timing im zweistufigen Pfad ergänzen**

Datei: `app/rag.py`. Ersetze den `if studiengang and studiengang in STUDIENGANG_FILES:`-Block (Zeilen 274-299) vollständig durch:

```python
    if studiengang and studiengang in STUDIENGANG_FILES:
        prog_n = 12 if is_pflicht else 8
        # Stufe 1 + 2 parallel: beide Queries sind unabhängig
        _t_query = time.perf_counter()
        with ThreadPoolExecutor(max_workers=2) as pool:
            fut_prog = pool.submit(_query_safe, {"program": studiengang}, prog_n, query_texts=[query])
            fut_all  = pool.submit(_query_safe, {"program": "all"}, 4, query_texts=[query])
            prog_r   = fut_prog.result()
            all_r    = fut_all.result()
        query_ms = (time.perf_counter() - _t_query) * 1000
        prog_docs  = prog_r["documents"][0]
        if not prog_docs:
            logging.warning(
                f"[RAG] Keine Handbuch-Chunks für studiengang={studiengang!r} gefunden "
                f"— Filter greift möglicherweise nicht."
            )
        prog_dists = prog_r["distances"][0]
        all_docs   = all_r["documents"][0]
        all_dists  = all_r["distances"][0]
        # Kombinieren mit garantierter Handbuch-Priorität (max. 6 Chunks)
        _t_rerank = time.perf_counter()
        docs = _merge_handbook_priority(prog_docs, all_docs, reranker, query, top_k=6, min_handbook=3)
        rerank_ms = (time.perf_counter() - _t_rerank) * 1000
        combined_dists = prog_dists + all_dists
        # beste_distanz aus allen Kandidaten-Distanzen (Proxy für DB-Relevanz)
        beste_distanz = min(combined_dists) if combined_dists else 1.0
        logging.info(
            f"[RAG] SG={studiengang}: prog={len(prog_docs)} handbuch, all={len(all_docs)} general"
            f" → final={len(docs)} chunks"
        )
        logging.info(
            f"[RAG-TIMING] sg={studiengang} query={query_ms:.0f}ms rerank={rerank_ms:.0f}ms "
            f"total={query_ms + rerank_ms:.0f}ms"
        )
```

- [ ] **Step 5: Timing im einstufigen Pfad ergänzen**

Datei: `app/rag.py`. Ersetze den `else:`-Block (Zeilen 300-304) vollständig durch:

```python
    else:
        _t_query = time.perf_counter()
        results = _query_safe(where, 8, query_texts=[query])
        query_ms = (time.perf_counter() - _t_query) * 1000
        _t_rerank = time.perf_counter()
        docs  = rerank(results["documents"][0], query, top_k=6)
        rerank_ms = (time.perf_counter() - _t_rerank) * 1000
        dists = results["distances"][0]
        beste_distanz = dists[0] if dists else 1.0
        logging.info(
            f"[RAG-TIMING] single query={query_ms:.0f}ms rerank={rerank_ms:.0f}ms "
            f"total={query_ms + rerank_ms:.0f}ms"
        )
```

- [ ] **Step 6: Test grün**

```bash
python -m pytest tests/test_rag_reranking.py::test_single_stage_logs_rag_timing -v
```

Erwartete Ausgabe: PASSED.

- [ ] **Step 7: Gesamte Test-Suite**

```bash
python -m pytest tests/ -q
```

Erwartete Ausgabe: alle Tests grün (≥ 104).

- [ ] **Step 8: Commit**

```bash
git add app/rag.py tests/test_rag_reranking.py
git commit -m "perf(rag): Phasen-Timing (query/rerank) als [RAG-TIMING] loggen"
```

---

## Task 2: `static/index.html` — Spracheingabe-Button entfernen

**Files:**
- Modify: `static/index.html` (CSS 414-432 + 567-568, HTML 672-676, JS 813, 913, 935-970, 1137)

**Bestätigt:** Gemeint ist `ttsBtn` (Mikrofon-Symbol "Spracheingabe") im Chat-Eingabebereich. `micMuted`, `toggleMic`, `SVG_MIC*` gehören zur **Toolbar** (Avatar-Mute) und bleiben unangetastet.

### Schritte

- [ ] **Step 1: CSS `.tts-btn`-Regeln entfernen (Light-Theme)**

Datei: `static/index.html`. Entferne den Block (Zeilen 414-432):

```css
.tts-btn {
  width: 40px; height: 40px;
  border-radius: 50%;
  border: 1px solid var(--border);
  background: var(--surface);
  cursor: pointer;
  display: flex;
  align-items: center;
  justify-content: center;
  flex-shrink: 0;
  color: var(--text-muted);
  transition: all 0.2s;
}

.tts-btn.active {
  background: #fef2f2;
  border-color: #ef4444;
  color: #ef4444;
}
```

- [ ] **Step 2: CSS `.tts-btn`-Overrides entfernen (Dark-Theme)**

Datei: `static/index.html`. Entferne die zwei Zeilen (567-568):

```css
.tts-btn { border-color: rgba(255,255,255,0.15); background: rgba(0,0,0,0.40); color: rgba(255,255,255,0.70); }
.tts-btn.active { background: rgba(239,68,68,0.30); border-color: rgba(239,68,68,0.60); }
```

- [ ] **Step 3: Button-Markup entfernen**

Datei: `static/index.html`. Entferne den Button (Zeilen 672-676):

```html
      <button class="tts-btn" id="ttsBtn" title="Spracheingabe (Chrome/Edge)">
        <svg viewBox="0 0 24 24" fill="currentColor" width="16" height="16">
          <path d="M12 1a3 3 0 0 0-3 3v8a3 3 0 0 0 6 0V4a3 3 0 0 0-3-3zM19 10v2a7 7 0 0 1-14 0v-2H3v2a9 9 0 0 0 8 8.94V22h-3v2h8v-2h-3v-1.06A9 9 0 0 0 21 12v-2h-2z"/>
        </svg>
      </button>
```

- [ ] **Step 4: `ttsBtn`-Konstante entfernen**

Datei: `static/index.html`, Zeile 913. Entferne:

```javascript
  const ttsBtn      = document.getElementById("ttsBtn");
```

- [ ] **Step 5: Recognition-Setup-Block entfernen**

Datei: `static/index.html`. Entferne den gesamten Block (Zeilen 935-970):

```javascript
  let recognition = null;

  if (!('SpeechRecognition' in window) && !('webkitSpeechRecognition' in window)) {
    ttsBtn.disabled = true;
    ttsBtn.title = "Spracheingabe nur in Chrome/Edge verfügbar";
  } else {
    const SpeechRecognition = window.SpeechRecognition || window.webkitSpeechRecognition;
    recognition = new SpeechRecognition();
    recognition.lang = "de-DE";
    recognition.interimResults = false;
    recognition.maxAlternatives = 1;

    recognition.onresult = (event) => {
      const transcript = event.results[0][0].transcript;
      document.getElementById("userInput").value = transcript;
      sendMessage();
    };

    recognition.onerror = (event) => {
      console.warn("Spracherkennung:", event.error);
      ttsBtn.classList.remove("active");
    };

    recognition.onend = () => {
      ttsBtn.classList.remove("active");
    };

    ttsBtn.addEventListener("click", () => {
      if (ttsBtn.classList.contains("active")) {
        recognition.stop();
      } else {
        recognition.start();
        ttsBtn.classList.add("active");
      }
    });
  }
```

- [ ] **Step 6: `recognition.lang`-Zeile in `setLang` entfernen**

Datei: `static/index.html`, Zeile 813. Entferne:

```javascript
    if (recognition) recognition.lang = lang === "en" ? "en-US" : "de-DE";
```

- [ ] **Step 7: `recognition.stop()`-Zeile in `avatarSpeak` entfernen**

Datei: `static/index.html`, Zeile 1137. Entferne:

```javascript
    if (recognition) recognition.stop();
```

- [ ] **Step 8: Auf verwaiste Referenzen prüfen**

```bash
cd c:/Users/lucat/Downloads/Avatar_Teamprojekt-feature-tavus
grep -n "ttsBtn\|recognition\|tts-btn\|SpeechRecognition" static/index.html
```

Erwartete Ausgabe: **keine Treffer**. Falls doch, die jeweilige Referenz entfernen.

- [ ] **Step 9: Manuelle Verifikation**

`run.ps1` starten, `http://localhost:8000` öffnen, Chat öffnen. Prüfen:
- Kein Mikrofon-Button mehr links neben dem Eingabefeld.
- DevTools-Konsole zeigt keine Fehler (`ttsBtn is null` o.ä.).
- Frage tippen + Enter → Antwort kommt normal.
- Sprache auf EN umstellen → kein Konsolen-Fehler.

- [ ] **Step 10: Commit**

```bash
git add static/index.html
git commit -m "feat(ui): Spracheingabe-Button (ttsBtn) aus dem Chat entfernen"
```

---

## Task 3: `static/index.html` — Auto-Retry bei "Service momentan nicht verfügbar"

**Files:**
- Modify: `static/index.html:1170-1246` (`sendMessage`)

**Ziel:** Bei einem transienten Fehler (SSE-`error`-Event oder Netzwerkfehler) versucht das UI **bis zu 2×** still erneut, bevor `showError()` die dauerhafte Meldung zeigt. Retry nur, wenn noch **keine** Antwort gestreamt wurde (analog zum Backend-Verhalten).

### Schritte

- [ ] **Step 1: `sendMessage` durch `sendMessage` + `attemptSend` ersetzen**

Datei: `static/index.html`. Ersetze die gesamte `async function sendMessage() { ... }` (Zeilen 1170-1246) durch:

```javascript
  const MAX_SEND_RETRIES = 2;
  const SEND_RETRY_DELAY = 1500;

  async function sendMessage() {
    const input = document.getElementById("userInput");
    const text  = input.value.trim();
    if (!text) return;
    resetIdleTimer();

    input.value = "";
    input.style.height = "auto";

    const emptyState = document.getElementById("emptyState");
    if (emptyState) emptyState.remove();
    if (chipsRow) chipsRow.style.display = "none";

    addMessage("user", text);
    attemptSend(text, 0);
  }

  async function attemptSend(text, attempt) {
    document.getElementById("sendBtn").disabled = true;
    document.getElementById("statusText").textContent =
      attempt > 0 ? "Verbindung wird erneut versucht…" : "denkt nach...";

    const typingId = showTyping();
    let streamEl = null;
    let gotContent = false;
    let failed = false;
    let errMessage = "Service momentan nicht verfügbar.";

    try {
      const res = await fetch(API_URL, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ message: text, session_id: sessionId, lang: lang, studiengang: currentStudiengang })
      });
      if (!res.ok) {
        const errBody = await res.json().catch(() => ({}));
        throw new Error(errBody.detail || `HTTP ${res.status}`);
      }

      const reader = res.body.getReader();
      const decoder = new TextDecoder();
      let buffer = "";

      while (true) {
        const { done, value } = await reader.read();
        if (done) break;
        buffer += decoder.decode(value, { stream: true });
        const blocks = buffer.split("\n\n");
        buffer = blocks.pop();
        for (const block of blocks) {
          const line = block.trim();
          if (!line.startsWith("data:")) continue;
          let evt;
          try { evt = JSON.parse(line.slice(5)); } catch (_) { continue; }

          if (evt.type === "chunk") {
            gotContent = true;
            if (!streamEl) { removeTyping(typingId); streamEl = addStreamingMessage(); }
            streamEl.content.textContent += evt.text;
            const messages = document.getElementById("messages");
            messages.scrollTop = messages.scrollHeight;
          } else if (evt.type === "done") {
            if (!streamEl) { removeTyping(typingId); streamEl = addStreamingMessage(); }
            const m = document.createElement("div");
            m.className = "meta";
            const cls = evt.source === "Wissensbasis" ? "wb" : "llm";
            const ico = evt.source === "Wissensbasis" ? "📚" : "🧠";
            m.innerHTML = `<span class="${cls}">${ico} ${evt.source}</span><span>${evt.latency_ms}ms</span>`;
            streamEl.bubble.appendChild(m);
            speakAnswer(evt.voice_text);
            markUnread();
            startIdleTimer();
          } else if (evt.type === "error") {
            failed = true;
            errMessage = evt.message || errMessage;
          }
        }
      }
    } catch (err) {
      failed = true;
      errMessage = err.message || errMessage;
    } finally {
      removeTyping(typingId);
      document.getElementById("sendBtn").disabled = false;
      document.getElementById("statusText").textContent = "bereit";
    }

    // Auto-Retry nur wenn ein Fehler auftrat und noch keine Antwort gestreamt wurde
    if (failed && !gotContent && attempt < MAX_SEND_RETRIES) {
      await new Promise(r => setTimeout(r, SEND_RETRY_DELAY));
      return attemptSend(text, attempt + 1);
    }
    if (failed && !gotContent) {
      showError(errMessage);
    }
  }
```

- [ ] **Step 2: Manuelle Verifikation — Erfolgsfall**

`run.ps1` starten, Chat öffnen, eine Frage senden. Erwartung: Antwort streamt normal, kein "Verbindung wird erneut versucht…".

- [ ] **Step 3: Manuelle Verifikation — Retry-Fall**

Fehler simulieren: in `attemptSend` temporär die `fetch`-URL auf einen ungültigen Pfad (`"/chat-broken"`) setzen ODER den Backend-Server während des Sendens stoppen. Erwartung:
- Status zeigt kurz "Verbindung wird erneut versucht…".
- Nach 2 zusätzlichen Versuchen (~3s) erscheint die Fehlermeldung "⚠ Fehler: …" genau **einmal**.
- DevTools-Network zeigt 3 `/chat`-Requests.

Danach die temporäre Änderung zurücksetzen.

- [ ] **Step 4: Commit**

```bash
git add static/index.html
git commit -m "feat(ui): stiller Auto-Retry (2x) bei Service-Fehler im Chat"
```

---

## Task 4: `app/routes/tavus.py` — Avatar-Pausen durch Satz-Puffern + URL-Normalisierung beheben

**Files:**
- Modify: `app/routes/tavus.py:1-10` (Imports), neue Helfer nach `_VOICE_CONTEXT`, `stream_answer()` in `tavus_llm` (Zeilen 207-230)
- Test: `tests/test_tavus.py`

**Ziel:** Tavus erhält im Voice-Pfad (`/tavus/llm`) ganze Sätze statt Token-Fragmente, und URLs wie `campus.kit.edu` werden vorlesefreundlich (`campus punkt kit punkt edu`). Das beseitigt Pausen mitten im Satz und das Stocken an URLs.

### Schritte

- [ ] **Step 1: Bestehenden Test an Satz-Puffern anpassen**

Datei: `tests/test_tavus.py`. Ersetze die Funktion `test_tavus_llm_streams_chunks` (Zeilen 95-121) vollständig durch:

```python
@patch("app.rag.collection")
@patch("app.routes.tavus.client")
def test_tavus_llm_streams_chunks(mock_client, mock_collection):
    mock_collection.query.return_value = {
        "documents": [["KIT Prüfungsanmeldung erfolgt über das Campus-Portal."]],
        "distances": [[0.3]]
    }
    mock_client.aio.models.generate_content_stream = AsyncMock(
        return_value=make_async_stream(["Prüfungen meldest du ", "über campus.kit.edu an."])
    )
    response = test_client.post("/tavus/llm", json={
        "messages": [{"role": "user", "content": "Wie melde ich mich für Prüfungen an?"}],
        "stream": True
    })
    assert response.status_code == 200
    assert "text/event-stream" in response.headers.get("content-type", "")
    body = response.text
    assert "[DONE]" in body
    # URL wird vorlesefreundlich normalisiert
    assert "campus punkt kit punkt edu" in body
    assert "campus.kit.edu" not in body
    import json as j
    deltas = [
        j.loads(line[5:])["choices"][0]["delta"].get("content")
        for line in body.split("\n\n")
        if line.strip().startswith("data:") and "[DONE]" not in line
        and j.loads(line[5:])["choices"][0]["delta"].get("content")
    ]
    # Token-Fragmente werden zu einem vollständigen Satz gepuffert
    full = "".join(deltas)
    assert "Prüfungen meldest du über campus punkt kit punkt edu an." in full
    assert response.headers["cache-control"] == "no-cache"
    assert response.headers["x-accel-buffering"] == "no"
    _reset_voice_prefs()
```

- [ ] **Step 2: Neue Tests anhängen**

Datei `tests/test_tavus.py` — ans Ende anhängen:

```python
# ── Avatar-Pausen: Satz-Puffern + TTS-Normalisierung ─────────────────────────

def test_tts_normalize_urls():
    from app.routes.tavus import _tts_normalize
    assert _tts_normalize("Schau auf campus.kit.edu nach.") == "Schau auf campus punkt kit punkt edu nach."
    # Reiner Text ohne Domain bleibt unverändert
    assert _tts_normalize("Das ist ein ganz normaler Satz.") == "Das ist ein ganz normaler Satz."
    # Dezimalzahl ist keine Domain (TLD muss aus Buchstaben bestehen)
    assert _tts_normalize("Die Note ist 2.5 wert.") == "Die Note ist 2.5 wert."


@patch("app.rag.collection")
@patch("app.routes.tavus.client")
def test_tavus_llm_buffers_into_sentences(mock_client, mock_collection):
    mock_collection.query.return_value = {"documents": [["Doc"]], "distances": [[0.3]]}
    # Tokenweises Streaming, das Satzgrenzen kreuzt
    mock_client.aio.models.generate_content_stream = AsyncMock(
        return_value=make_async_stream(["Erster ", "Satz. Zwei", "ter Satz."])
    )
    response = test_client.post("/tavus/llm", json={
        "messages": [{"role": "user", "content": "Test"}],
        "stream": True
    })
    import json as j
    deltas = [
        j.loads(line[5:])["choices"][0]["delta"].get("content")
        for line in response.text.split("\n\n")
        if line.strip().startswith("data:") and "[DONE]" not in line
        and j.loads(line[5:])["choices"][0]["delta"].get("content")
    ]
    # Jeder Satz ist ein eigenes, vollständiges Delta — keine Fragmente wie "Erster "
    assert any(d.strip() == "Erster Satz." for d in deltas)
    assert any(d.strip() == "Zweiter Satz." for d in deltas)
    _reset_voice_prefs()
```

- [ ] **Step 3: Tests als failing bestätigen**

```bash
python -m pytest tests/test_tavus.py::test_tts_normalize_urls tests/test_tavus.py::test_tavus_llm_buffers_into_sentences tests/test_tavus.py::test_tavus_llm_streams_chunks -v
```

Erwartete Ausgabe: alle drei FAILED (`_tts_normalize` existiert nicht / keine Satz-Pufferung).

- [ ] **Step 4: `import re` ergänzen**

Datei: `app/routes/tavus.py`, Zeilen 1-5. Ändere:

```python
import os
import asyncio
import json
import logging
from urllib.parse import quote
```

zu:

```python
import os
import asyncio
import json
import logging
import re
from urllib.parse import quote
```

- [ ] **Step 5: Helfer `_tts_normalize` und `_flush_sentences` hinzufügen**

Datei: `app/routes/tavus.py`. Direkt **nach** dem `_VOICE_CONTEXT`-Dict (nach Zeile 42, vor `class TavusPrefsRequest`) einfügen:

```python
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
```

- [ ] **Step 6: `stream_answer()` auf Satz-Puffern umstellen**

Datei: `app/routes/tavus.py`. Ersetze die innere Funktion `stream_answer()` (Zeilen 207-230) vollständig durch:

```python
    async def stream_answer():
        gesendet = False
        buffer = ""
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
                        buffer += chunk.text
                        deltas, buffer = _flush_sentences(buffer)
                        for d in deltas:
                            yield f'data: {json.dumps({"choices": [{"delta": {"content": d}, "finish_reason": None}]})}\n\n'
                break
            except Exception as e:
                logging.warning(f"tavus/llm Gemini Fehler (Versuch {versuch + 1}): {e}")
                if gesendet:
                    break
                if versuch < 2:
                    await asyncio.sleep(VOICE_RETRY_DELAY)
        if gesendet:
            # Restpuffer (letzter Satz ohne abschließendes Whitespace) ausgeben
            deltas, buffer = _flush_sentences(buffer, final=True)
            for d in deltas:
                yield f'data: {json.dumps({"choices": [{"delta": {"content": d}, "finish_reason": None}]})}\n\n'
        else:
            yield f'data: {json.dumps({"choices": [{"delta": {"content": "Service momentan nicht verfügbar."}, "finish_reason": None}]})}\n\n'
        yield f'data: {json.dumps({"choices": [{"delta": {}, "finish_reason": "stop"}]})}\n\n'
        yield 'data: [DONE]\n\n'
```

- [ ] **Step 7: Neue/aktualisierte Tests grün**

```bash
python -m pytest tests/test_tavus.py::test_tts_normalize_urls tests/test_tavus.py::test_tavus_llm_buffers_into_sentences tests/test_tavus.py::test_tavus_llm_streams_chunks -v
```

Erwartete Ausgabe: alle drei PASSED.

- [ ] **Step 8: Gesamte Tavus-Test-Suite (Regression)**

```bash
python -m pytest tests/test_tavus.py -q
```

Erwartete Ausgabe: alle grün — insbesondere `test_tavus_llm_fallback_after_failures` (Fallback-Meldung) und `test_tavus_llm_no_retry_after_first_chunk` ("Teil eins" genau einmal) müssen weiter bestehen.

- [ ] **Step 9: Gesamte Test-Suite**

```bash
python -m pytest tests/ -q
```

Erwartete Ausgabe: alle Tests grün (≥ 106).

- [ ] **Step 10: Manuelle Verifikation (optional, mit echtem Tavus)**

Falls `TAVUS_API_KEY` gesetzt: Avatar starten, eine Frage mit URL-Antwort stellen (z.B. "Wo bewerbe ich mich?"). Erwartung: Avatar spricht flüssig, liest URL als "campus punkt kit punkt edu", keine Pausen mitten im Satz. Sichtbarer Chat-Text ist davon unberührt (Path A bleibt unverändert).

- [ ] **Step 11: Commit**

```bash
git add app/routes/tavus.py tests/test_tavus.py
git commit -m "fix(tavus): Stream in Sätze puffern + URLs vorlesefreundlich gegen Avatar-Pausen"
```

---

## Akzeptanzkriterien (Gesamt)

1. `python -m pytest tests/ -q` → alle Tests grün (≥ 106).
2. Nach einer Chat-Anfrage steht eine `[RAG-TIMING]`-Zeile mit getrennten `query=`/`rerank=`-Zeiten im Log (Task 1).
3. Kein Mikrofon-/Spracheingabe-Button mehr im Chat; `grep` findet keine `ttsBtn`/`recognition`/`tts-btn`-Referenzen; keine Konsolenfehler (Task 2).
4. Bei transientem Fehler versucht das UI automatisch bis zu 2× neu, dann erscheint die Fehlermeldung genau einmal; erfolgreicher Retry zeigt die Antwort normal (Task 3).
5. `/tavus/llm` liefert ganze Sätze als Deltas und normalisiert URLs zu "… punkt …"; Fallback- und No-Retry-Verhalten unverändert (Task 4).

## Nicht im Scope

- Konkrete RAG-Optimierung — sie wird nach Auswertung der `[RAG-TIMING]`-Messungen separat entschieden.
- GPU-Beschleunigung, Reranker-Modellwechsel.
- Änderung der Prompt-Inhalte (außer der TTS-URL-Normalisierung im Stream).
