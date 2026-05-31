# Tavus AI Integration Design Spec

**Goal:** Tavus als dritten Avatar-Provider in KIRA integrieren. Tavus übernimmt Spracheingabe und Avatar-Video via Daily.co WebRTC; KIRA's Gemini + ChromaDB RAG bleibt das KI-Backend über einen OpenAI-kompatiblen Custom-LLM Endpoint.

**Architecture:** Neuer Provider-Zweig im bestehenden Plugin-System (`AVATAR_PROVIDER=tavus`). Backend: 3 neue FastAPI-Endpoints in `main.py`. Frontend: Daily.co JS SDK ersetzt LiveKit für Video/Audio-Streaming, Transkriptions-Events befüllen die Chat-Sidebar. Kein neues Framework.

**Tech Stack:** FastAPI (bestehend), httpx (bestehend), Daily.co JS SDK (CDN), Tavus REST API v2.

---

## 1. Datenfluss

```
Nutzer spricht → Daily.co Mic → Tavus CVI (STT)
    → POST /tavus/llm (OpenAI-Format)
        → ChromaDB RAG + Gemini 2.5 Flash
        → Streaming SSE (OpenAI-Format)
    → Tavus Avatar spricht (Daily.co Video)
    → transcription-message Events → Chat-Sidebar Bubbles
```

---

## 2. Backend — Neue Endpoints

### `POST /tavus/session`
Erstellt eine Tavus CVI-Konversation.

**Request:** kein Body

**Intern:**
```python
POST https://tavusapi.com/v2/conversations
Headers: { "x-api-key": TAVUS_API_KEY }
Body: {
  "replica_id": TAVUS_REPLICA_ID,
  "persona_id": TAVUS_PERSONA_ID,          # nur wenn gesetzt
  "conversational_context": "Du bist KIRA, Studienberaterin am KIT...",
  "custom_llm_extra_body": {
    "llm_websocket_url": "{BASE_URL}/tavus/llm"
  }
}
```

**Response:**
```json
{ "conversation_id": "...", "conversation_url": "https://tavus.daily.co/..." }
```

---

### `POST /tavus/llm`
OpenAI-kompatibler Custom-LLM Endpoint — wird von Tavus aufgerufen wenn der Nutzer spricht.

**Request (von Tavus):**
```json
{
  "messages": [{"role": "user", "content": "..."}, ...],
  "stream": true
}
```

**Intern:**
1. Letzten `role: "user"` Message aus `messages[]` extrahieren
2. `session_id` aus `X-Tavus-Conversation-Id` Header (Fallback: `"tavus_default"`)
3. ChromaDB-Query + Gemini (identische Logik wie `/chat`)
4. Antwort als OpenAI SSE streamen

**Response:** `text/event-stream`
```
data: {"choices":[{"delta":{"content":"Hallo"},"finish_reason":null}]}
data: {"choices":[{"delta":{"content":"!"},"finish_reason":null}]}
data: {"choices":[{"delta":{},"finish_reason":"stop"}]}
data: [DONE]
```

---

### `POST /tavus/end`
Beendet eine Tavus-Konversation.

**Request:** `{ "conversation_id": "..." }`

**Intern:**
```python
DELETE https://tavusapi.com/v2/conversations/{conversation_id}
Headers: { "x-api-key": TAVUS_API_KEY }
```

**Response:** `{ "status": "ended" }`

---

## 3. Environment Variables

```env
TAVUS_API_KEY=...
TAVUS_REPLICA_ID=...
TAVUS_PERSONA_ID=...      # leer lassen wenn kein Persona
AVATAR_PROVIDER=tavus
```

---

## 4. Frontend

### Neue CDN-Abhängigkeit (`<head>`)
```html
<script src="https://unpkg.com/@daily-co/daily-js"></script>
```

### `_startAvatarTavus()` Funktion
```javascript
async function _startAvatarTavus() {
  // 1. Session erstellen
  const res = await fetch("/tavus/session", { method: "POST" });
  const { conversation_id, conversation_url } = await res.json();
  tavusConversationId = conversation_id;

  // 2. Daily.co Call erstellen und beitreten
  tavusCall = Daily.createCallObject();
  await tavusCall.join({ url: conversation_url, startVideoOff: false, startAudioOff: false });

  // 3. Video/Audio in bestehende Elemente routen
  tavusCall.on("track-started", (e) => {
    if (e.participant.local) return;
    if (e.track.kind === "video") avatarVideo.srcObject = new MediaStream([e.track]);
    if (e.track.kind === "audio") avatarAudio.srcObject = new MediaStream([e.track]);
  });

  // 4. Transkription → Chat-Sidebar
  tavusCall.on("transcription-message", (e) => {
    if (!e.is_final) return;
    if (e.role === "user") addMessage("user", e.text);
    if (e.role === "assistant") addMessage("bot", e.text);
  });

  // 5. Status-Updates
  tavusCall.on("joined-meeting", () => setStatus("bereit", "connected"));
  tavusCall.on("left-meeting", () => setStatus("offline", "offline"));
}
```

### Globale Variablen (neu)
```javascript
let tavusCall = null;
let tavusConversationId = null;
```

### `startAvatar()` — neuer Zweig
```javascript
case "tavus": await _startAvatarTavus(); break;
```

### `beforeunload` — Cleanup
```javascript
if (tavusConversationId) {
  navigator.sendBeacon("/tavus/end",
    JSON.stringify({ conversation_id: tavusConversationId }));
  tavusCall?.destroy();
}
```

---

## 5. Tests (`tests/test_tavus.py`)

6 Tests mit `@patch("main.httpx.AsyncClient")`:
1. `test_tavus_session_success` — Erfolgreiche Session-Erstellung
2. `test_tavus_session_missing_api_key` — 500 wenn `TAVUS_API_KEY` fehlt
3. `test_tavus_session_api_error` — Tavus API gibt Fehler zurück
4. `test_tavus_session_timeout` — 504 bei Timeout
5. `test_tavus_llm_success` — Streaming-Response mit gültigem Message-Array
6. `test_tavus_end_success` — Session erfolgreich beendet

---

## 6. Was sich nicht ändert

- Alle bestehenden Element-IDs
- `/chat`, `/liveavatar/*`, `/avatar/config`, `/tts` Endpoints
- Tests für andere Provider
- `AVATAR_PROVIDER=heygen` oder `=anam` funktionieren weiterhin unverändert
