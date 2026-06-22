# Design: HeyGen Streaming Avatar Integration

**Datum:** 2026-05-21  
**Projekt:** KIRA — KIT Studienberatungs-Chatbot  
**Ziel:** Vollständige bidirektionale Integration von HeyGen Streaming Avatar und dem KIRA-Chatbot

---

## 1. Ziel

Der HeyGen Streaming Avatar (WebRTC) ersetzt den bisherigen `liveavatar.com`-iframe. Der Avatar spricht alle KIRA-Antworten mit Lippensynchronisation. Der Nutzer kann alternativ per Mikrofon (Web Speech API) mit KIRA sprechen, statt zu tippen.

**Vollständiger Datenfluss:**
```
Nutzer spricht/tippt → KIRA verarbeitet (Gemini + ChromaDB) → Avatar spricht Antwort
```

---

## 2. Architektur

### Komponenten

| Komponente | Verantwortung |
|------------|---------------|
| `main.py` — `/chat` | Unverändert: RAG + Gemini, gibt Textantwort zurück |
| `main.py` — `/streaming/*` | Neu: 5 Proxy-Endpoints zur HeyGen Streaming API |
| `index.html` — WebRTC-Client | Neu: Ersetzt iframe, baut WebRTC-Verbindung auf |
| `index.html` — Mikrofon-Button | Neu: Web Speech API Spracheingabe |

### Entfällt

- Endpoint `/liveavatar-embed` (liveavatar.com) wird entfernt
- Separater `/tts`-Aufruf beim Anzeigen von Bot-Antworten entfällt (Avatar übernimmt Audio)
- `<iframe id="avatarIframe">` wird durch `<video id="avatarVideo">` ersetzt

---

## 3. Backend-Änderungen (`main.py`)

### Neue Umgebungsvariablen (`.env`)

```
HEYGEN_API_KEY=...       # bereits vorhanden
HEYGEN_VOICE_ID=...      # bereits vorhanden
HEYGEN_AVATAR_ID=...     # neu: Streaming-Avatar-ID aus HeyGen Dashboard
```

### Neue Endpoints

#### `POST /streaming/new`
Erstellt eine neue HeyGen Streaming Session.

- Ruft `POST https://api.heygen.com/v1/streaming.new` auf
- Body an HeyGen: `{ "quality": "high", "avatar_name": HEYGEN_AVATAR_ID, "voice": { "voice_id": HEYGEN_VOICE_ID } }`
- Gibt zurück: `{ "session_id", "sdp": { "sdp", "type" }, "ice_servers", "access_token" }`
- Speichert `session_id` im Backend (in-memory, analog zu `sessions`)

#### `POST /streaming/start`
Übermittelt die SDP-Answer des Browsers nach dem WebRTC-Handshake.

- Empfängt: `{ "session_id", "sdp": { "sdp", "type": "answer" } }`
- Ruft `POST https://api.heygen.com/v1/streaming.start` auf
- Gibt zurück: `{ "status": "started" }`

#### `POST /streaming/ice`
Leitet ICE-Kandidaten des Browsers an HeyGen weiter (läuft automatisch während Verbindungsaufbau).

- Empfängt: `{ "session_id", "candidate": { ... } }`
- Ruft `POST https://api.heygen.com/v1/streaming.ice` auf
- Gibt zurück: `{ "status": "ok" }`

#### `POST /streaming/task`
Lässt den Avatar einen Text sprechen.

- Empfängt: `{ "session_id", "text" }`
- Ruft `POST https://api.heygen.com/v1/streaming.task` auf
- Body an HeyGen: `{ "session_id", "text", "task_type": "repeat" }`
- Gibt zurück: `{ "status": "ok" }`

#### `POST /streaming/stop`
Beendet die Streaming Session.

- Empfängt: `{ "session_id" }`
- Ruft `POST https://api.heygen.com/v1/streaming.stop` auf
- Entfernt session_id aus dem Backend-Speicher
- Gibt zurück: `{ "status": "stopped" }`

---

## 4. Frontend-Änderungen (`index.html`)

### HTML-Änderungen

```html
<!-- Vorher -->
<iframe id="avatarIframe" allow="microphone; camera" ...></iframe>

<!-- Nachher -->
<video id="avatarVideo" autoplay playsinline></video>
```

Der Avatar-Container (`div.avatar-container`) und der Placeholder bleiben erhalten. Der "Avatar starten"-Button löst jetzt den WebRTC-Handshake aus.

### JavaScript: WebRTC-Ablauf

```
startAvatar()
  → POST /streaming/new
  → RTCPeerConnection({ iceServers })
  → pc.setRemoteDescription(sdp_offer)
  → pc.onicecandidate → POST /streaming/ice
  → pc.ontrack → video.srcObject = event.streams[0]
  → pc.createAnswer()
  → pc.setLocalDescription(answer)
  → POST /streaming/start { sdp_answer }
  → Avatar erscheint im <video>
```

### JavaScript: Antwort sprechen

Nach jedem erfolgreichen `/chat`-Aufruf (egal ob Text oder Sprache):

```javascript
await fetch("/streaming/task", {
  method: "POST",
  body: JSON.stringify({ session_id: currentSessionId, text: data.answer })
})
```

Entfällt: der bisherige `speak(data.answer)`-Aufruf (HeyGen TTS + Browser-Fallback).

### JavaScript: Mikrofon-Button

Der bisherige TTS-Toggle-Button (`ttsBtn`) wird zum Mikrofon-Button:

- **Klick:** `SpeechRecognition.start()` — Button wird rot
- **`onresult`:** Transkript → `sendMessage(transcript)`
- **`onerror` / kein Support:** Button deaktiviert, Tooltip "Nur in Chrome/Edge verfügbar"
- Während Avatar spricht (`SPEAKING`-Zustand): Mikrofon pausiert, um Echo zu vermeiden

### Avatar-Zustandsmaschine (Frontend)

| Zustand | Avatar-Anzeige | Header-Status | Mikrofon |
|---------|---------------|--------------|---------|
| `IDLE` | Placeholder + "Avatar starten" | `verbinde...` | — |
| `CONNECTING` | Spinner | `verbinde...` | — |
| `READY` | Video sichtbar | `bereit` | aktiv |
| `SPEAKING` | Video sichtbar | `spricht...` | pausiert |
| `ERROR` | Placeholder + "Erneut versuchen" | `Fehler` | — |

---

## 5. Fehlerbehandlung

| Fehler | Verhalten |
|--------|-----------|
| HeyGen API nicht erreichbar | `ERROR`-Zustand, "Erneut versuchen"-Button |
| WebRTC-Verbindung schlägt fehl | `ERROR`-Zustand mit Meldung im Placeholder |
| `/streaming/task` schlägt fehl | Antwort erscheint trotzdem im Text-Chat; kein Absturz |
| Web Speech API nicht verfügbar | Mikrofon-Button deaktiviert (`disabled`), kein Fehler |
| Avatar-Session läuft ab | Beim nächsten `/streaming/task` Fehler → `ERROR`-Zustand |

---

## 6. Was sich nicht ändert

- `/chat`-Endpoint und KIRA-Logik (Gemini + ChromaDB RAG) bleiben vollständig unverändert
- Session-Memory im Backend (`sessions`-Dict) bleibt unverändert
- Layout, Farben, Chips, Nachrichtenblasen — visuell identisch
- Text-Chat funktioniert weiterhin parallel zur Spracheingabe
- `/health`-Endpoint bleibt

---

## 7. Abhängigkeiten & Voraussetzungen

- `HEYGEN_AVATAR_ID` muss in `.env` eingetragen werden (Streaming-Avatar aus HeyGen Dashboard)
- HeyGen-Account muss Zugriff auf die Streaming Avatar API haben
- Browser: Chrome oder Edge (Web Speech API); Firefox zeigt Avatar, aber kein Mikrofon
- Keine neuen Python-Pakete erforderlich (httpx bereits vorhanden)
