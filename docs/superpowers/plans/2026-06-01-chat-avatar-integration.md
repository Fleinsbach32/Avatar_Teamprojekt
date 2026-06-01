# Chat-Avatar-Integration (Tavus Texteingabe) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Text-Eingabe im Chat-Panel soll bei aktivem Tavus-Avatar denselben Flow auslösen wie Spracheingabe — der Avatar spricht die Antwort und die Transkription erscheint im Chat.

**Architecture:** Wenn der User Text tippt und ein aktiver Tavus-Conversation-ID vorhanden ist, wird der Text via `POST /tavus/message` (neuer Backend-Endpoint) direkt in die Tavus-CVI-Pipeline injiziert. Tavus ruft daraufhin `/tavus/llm` auf, der Avatar spricht, und die `transcription-message`-Events zeigen User- und Bot-Nachricht im Chat. Ohne aktive Session fällt `sendMessage()` auf `/chat` zurück (unverändertes Verhalten für HeyGen/Anam und Chat ohne Avatar).

**Tech Stack:** FastAPI (Python), httpx, Vanilla JavaScript, Tavus REST API v2, Daily.co SDK

---

## Betroffene Dateien

| Datei | Aktion | Verantwortung |
|---|---|---|
| `main.py` | Modify | Neues Pydantic-Modell + `POST /tavus/message` Endpoint |
| `static/index.html` | Modify | Dedup-Variablen, `transcription-message` Handler, `sendMessage()` |
| `tests/test_tavus.py` | Modify | Tests für neuen Endpoint |

---

## Task 1: Backend — `POST /tavus/message` Endpoint

**Files:**
- Modify: `main.py` (nach dem `TavusEndRequest` Modell, vor `@app.post("/tavus/session")`)
- Test: `tests/test_tavus.py`

> **Vor der Implementierung:** Verifiziere die aktuelle Tavus API Dokumentation für `POST /v2/conversations/{conversation_id}/message`. Der erwartete Request-Body ist `{"message": "text"}`. Falls das Format abweicht, passe Schritt 3 entsprechend an.

- [ ] **Schritt 1: Failing Test schreiben**

Füge am Ende von `tests/test_tavus.py` hinzu:

```python
# ── /tavus/message ────────────────────────────────────────
@patch("main.httpx.AsyncClient")
def test_tavus_message_success(mock_httpx_class):
    mock_http = AsyncMock()
    mock_http.post.return_value = make_mock_response(200, {})
    mock_httpx_class.return_value.__aenter__ = AsyncMock(return_value=mock_http)
    mock_httpx_class.return_value.__aexit__ = AsyncMock(return_value=False)

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
    assert call_args.kwargs["headers"]["x-api-key"] == "real-key"


def test_tavus_message_missing_api_key():
    with patch.dict(os.environ, {"TAVUS_API_KEY": ""}):
        response = test_client.post("/tavus/message", json={
            "conversation_id": "conv_abc123",
            "message": "Hallo"
        })
    assert response.status_code == 500


@patch("main.httpx.AsyncClient")
def test_tavus_message_api_error(mock_httpx_class):
    mock_http = AsyncMock()
    mock_http.post.return_value = make_mock_response(404, {"error": "conversation not found"})
    mock_httpx_class.return_value.__aenter__ = AsyncMock(return_value=mock_http)
    mock_httpx_class.return_value.__aexit__ = AsyncMock(return_value=False)

    with patch.dict(os.environ, {"TAVUS_API_KEY": "real-key"}):
        response = test_client.post("/tavus/message", json={
            "conversation_id": "nonexistent",
            "message": "Hallo"
        })

    assert response.status_code == 404


@patch("main.httpx.AsyncClient")
def test_tavus_message_timeout(mock_httpx_class):
    import httpx as real_httpx
    mock_http = AsyncMock()
    mock_http.post.side_effect = real_httpx.TimeoutException("timeout")
    mock_httpx_class.return_value.__aenter__ = AsyncMock(return_value=mock_http)
    mock_httpx_class.return_value.__aexit__ = AsyncMock(return_value=False)

    response = test_client.post("/tavus/message", json={
        "conversation_id": "conv_abc123",
        "message": "Hallo"
    })
    assert response.status_code == 504
```

- [ ] **Schritt 2: Tests laufen lassen — müssen FAIL sein**

```
cd Avatar_Teamprojekt-feature-tavus
python -m pytest tests/test_tavus.py::test_tavus_message_success -v
```

Erwartet: `FAILED` mit `404 Not Found` (Endpoint existiert noch nicht)

- [ ] **Schritt 3: Modell + Endpoint in `main.py` einfügen**

Füge nach dem Block `class TavusEndRequest(BaseModel):` (Zeile ~164) ein:

```python
class TavusMessageRequest(BaseModel):
    conversation_id: str
    message: str
```

Füge nach `@app.post("/tavus/end")` (nach Zeile ~229) ein:

```python
@app.post("/tavus/message")
async def tavus_message(request: TavusMessageRequest):
    api_key = os.getenv("TAVUS_API_KEY")
    if not api_key:
        raise HTTPException(status_code=500, detail="TAVUS_API_KEY nicht gesetzt")

    async with httpx.AsyncClient() as http:
        try:
            res = await http.post(
                f"https://tavusapi.com/v2/conversations/{request.conversation_id}/message",
                headers={"x-api-key": api_key, "Content-Type": "application/json"},
                json={"message": request.message},
                timeout=15.0
            )
            if res.status_code not in (200, 201):
                raise HTTPException(status_code=res.status_code, detail=str(res.json()))
            return {"status": "sent"}
        except httpx.TimeoutException:
            raise HTTPException(status_code=504, detail="Tavus API Timeout")
```

- [ ] **Schritt 4: Alle neuen Tests laufen lassen — müssen PASS sein**

```
python -m pytest tests/test_tavus.py -v -k "message"
```

Erwartet:
```
PASSED tests/test_tavus.py::test_tavus_message_success
PASSED tests/test_tavus.py::test_tavus_message_missing_api_key
PASSED tests/test_tavus.py::test_tavus_message_api_error
PASSED tests/test_tavus.py::test_tavus_message_timeout
```

- [ ] **Schritt 5: Gesamte Test-Suite laufen lassen**

```
python -m pytest tests/ -v
```

Alle vorherigen Tests müssen weiter PASS sein.

- [ ] **Schritt 6: Commit**

```
git add main.py tests/test_tavus.py
git commit -m "feat: add POST /tavus/message endpoint for text injection into CVI"
```

---

## Task 2: Frontend — Dedup-Variablen + `transcription-message` Handler

**Files:**
- Modify: `static/index.html`

- [ ] **Schritt 1: Dedup-Variablen nach den bestehenden Avatar-Variablen einfügen**

Suche den Block (ca. Zeile 647–653):
```javascript
let liveKitRoom = null;
let liveAvatarSessionId = null;
let tavusCall = null;
let tavusConversationId = null;
let avatarProvider = "heygen";
let anamClient = null;
const avatarAudio = document.getElementById("avatarAudio");
```

Ersetze ihn durch:
```javascript
let liveKitRoom = null;
let liveAvatarSessionId = null;
let tavusCall = null;
let tavusConversationId = null;
let avatarProvider = "heygen";
let anamClient = null;
const avatarAudio = document.getElementById("avatarAudio");
const pendingTypedMessages = new Set();
let tavusTypingId = null;
```

- [ ] **Schritt 2: `transcription-message` Handler ersetzen**

Suche den bestehenden Handler (ca. Zeile 786–791):
```javascript
      tavusCall.on("transcription-message", (e) => {
        if (!e.is_final) return;
        openChat();
        if (e.role === "user") addMessage("user", e.text);
        if (e.role === "assistant") addMessage("bot", e.text);
      });
```

Ersetze ihn durch:
```javascript
      tavusCall.on("transcription-message", (e) => {
        if (!e.is_final) return;
        openChat();
        if (e.role === "user") {
          const key = e.text.toLowerCase().trim();
          if (pendingTypedMessages.has(key)) {
            pendingTypedMessages.delete(key);
            return;
          }
          addMessage("user", e.text);
        }
        if (e.role === "assistant") {
          if (tavusTypingId) { removeTyping(tavusTypingId); tavusTypingId = null; }
          document.getElementById("statusText").textContent = "bereit";
          addMessage("bot", e.text);
        }
      });
```

- [ ] **Schritt 3: Manuell prüfen — Spracheingabe unbeschädigt**

Backend starten: `python -m uvicorn main:app --reload`

Öffne die App, starte den Tavus-Avatar, spreche in das Mikrofon.

Erwartet:
- Deine gesprochene Frage erscheint als User-Nachricht im Chat
- Avatar antwortet und die Antwort erscheint als Bot-Nachricht
- Kein Doppeleintrag

- [ ] **Schritt 4: Commit**

```
git add static/index.html
git commit -m "feat: add transcription dedup and tavusTypingId for text-driven chat"
```

---

## Task 3: Frontend — `sendMessage()` aufteilen

**Files:**
- Modify: `static/index.html`

- [ ] **Schritt 1: `sendMessage()` ersetzen**

Suche die gesamte `sendMessage()` Funktion (ca. Zeile 960–1004) und ersetze sie durch:

```javascript
  async function sendMessage() {
    const input = document.getElementById("userInput");
    const text  = input.value.trim();
    if (!text) return;

    input.value = "";
    input.style.height = "auto";

    const emptyState = document.getElementById("emptyState");
    if (emptyState) emptyState.remove();
    if (chipsRow) chipsRow.style.display = "none";

    addMessage("user", text);
    document.getElementById("sendBtn").disabled = true;
    document.getElementById("statusText").textContent = "denkt nach...";

    if (avatarProvider === "tavus" && tavusConversationId) {
      pendingTypedMessages.add(text.toLowerCase().trim());
      tavusTypingId = showTyping();
      try {
        const res = await fetch("/tavus/message", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ conversation_id: tavusConversationId, message: text })
        });
        if (!res.ok) {
          const err = await res.json();
          throw new Error(err.detail || `HTTP ${res.status}`);
        }
        // Bot-Antwort kommt via transcription-message Event
      } catch (err) {
        if (tavusTypingId) { removeTyping(tavusTypingId); tavusTypingId = null; }
        pendingTypedMessages.delete(text.toLowerCase().trim());
        showError(err.message);
        document.getElementById("statusText").textContent = "bereit";
      } finally {
        document.getElementById("sendBtn").disabled = false;
      }
    } else {
      const typingId = showTyping();
      try {
        const res = await fetch(API_URL, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ message: text, session_id: sessionId })
        });
        removeTyping(typingId);
        if (!res.ok) {
          const err = await res.json();
          throw new Error(err.detail || `HTTP ${res.status}`);
        }
        const data = await res.json();
        addMessage("bot", data.answer, { source: data.source, latency_ms: data.latency_ms });
        await avatarSpeak(data.answer);
      } catch (err) {
        removeTyping(typingId);
        showError(err.message);
      } finally {
        document.getElementById("sendBtn").disabled = false;
        document.getElementById("statusText").textContent = "bereit";
      }
    }
  }
```

- [ ] **Schritt 2: Manuell prüfen — Texteingabe mit aktivem Tavus-Avatar**

Backend starten, App öffnen, Avatar starten.

Tippe eine Frage z.B. `Wie melde ich mich für Prüfungen an?` und sende ab.

Erwartet:
- Deine Nachricht erscheint sofort im Chat
- Typing-Indicator erscheint
- Der Avatar beginnt zu sprechen (CVI-Pipeline)
- Die Bot-Antwort erscheint im Chat via Transkription
- Typing-Indicator verschwindet
- Status wechselt zurück auf "bereit"

- [ ] **Schritt 3: Manuell prüfen — Texteingabe OHNE aktiven Avatar (Fallback)**

Avatar NICHT starten, Chat-Panel öffnen über FAB-Button.

Tippe eine Frage und sende ab.

Erwartet:
- User-Nachricht erscheint sofort
- Typing-Indicator erscheint
- Bot-Antwort erscheint aus `/chat` (mit `📚 Wissensbasis` oder `🧠 LLM` + Latenz-Anzeige)
- Avatar bleibt im Placeholder-Zustand (kein Fehler)

- [ ] **Schritt 4: Manuell prüfen — Quick-Chips funktionieren noch**

Klicke einen der Chips (z.B. "Prüfungsanmeldung") ohne aktiven Avatar.

Erwartet: Chat öffnet sich, Chip-Text wird gesendet, Bot antwortet.

- [ ] **Schritt 5: Commit**

```
git add static/index.html
git commit -m "feat: route chat text input through Tavus CVI when avatar is active"
```

---

## Abschluss-Check

- [ ] `python -m pytest tests/ -v` — alle Tests grün
- [ ] Vollständiger End-to-End-Test: Avatar starten → Text tippen → Avatar spricht → Chat zeigt Antwort
- [ ] Vollständiger End-to-End-Test: Mikrofon sprechen → transkribiert → Avatar antwortet → Chat zeigt beide Nachrichten ohne Duplikat
