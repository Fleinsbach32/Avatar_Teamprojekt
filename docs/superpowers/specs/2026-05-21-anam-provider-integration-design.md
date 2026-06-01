# Design: Anam.io als alternativer Avatar-Provider

**Datum:** 2026-05-21  
**Projekt:** KIRA — KIT Studienberatungs-Chatbot  
**Ziel:** Anam.io als zweiten Avatar-Provider neben HeyGen integrieren, umschaltbar per `.env`-Variable

---

## 1. Ziel

Ein neuer `AVATAR_PROVIDER`-Schalter in `.env` bestimmt, welcher Avatar-Anbieter genutzt wird: `heygen` (bestehend) oder `anam` (neu). Kein Code-Änderung beim Wechsel — nur `.env` anpassen und Server neu starten.

---

## 2. Architektur

### Neue Backend-Endpoints

| Endpoint | Methode | Zweck |
|----------|---------|-------|
| `/avatar/config` | GET | Gibt `{"provider": "heygen" \| "anam"}` zurück |
| `/avatar/session` | POST | Anam: erstellt Session-Token via Anam API, gibt `{session_token, persona_id}` zurück |

Bestehende `/streaming/*`-Endpoints (HeyGen) bleiben vollständig unverändert.

### Neue Umgebungsvariablen (`.env`)

```
AVATAR_PROVIDER=anam        # Werte: "anam" oder "heygen" (Default: "heygen")
ANAM_API_KEY=...            # Anam API Key aus dem Anam Dashboard
ANAM_PERSONA_ID=...         # Persona ID aus dem Anam Dashboard
```

### Frontend-Logik

```
Seite lädt
  → GET /avatar/config → { provider: "anam" | "heygen" }
  → Wert in Variable `avatarProvider` speichern

startAvatar():
  if avatarProvider === "anam":
    → POST /avatar/session → { session_token, persona_id }
    → AnamSDK.createClient(session_token, { personaId, disableInputAudio: true })
    → client.streamToVideoAndAudioElements(avatarVideo, avatarAudio)
  if avatarProvider === "heygen":
    → bestehender WebRTC-Flow (unverändert)

avatarSpeak(text):
  if avatarProvider === "anam":
    → anamClient.talk(text)
  if avatarProvider === "heygen":
    → fetch("/streaming/task", { session_id, text })

stopAvatar() [neu, beim Seitenunload]:
  if avatarProvider === "anam":
    → anamClient.stopStreaming()
  if avatarProvider === "heygen":
    → fetch("/streaming/stop", { session_id })
```

---

## 3. Backend-Änderungen (`main.py`)

### `GET /avatar/config`

Liest `AVATAR_PROVIDER` aus der Umgebung. Gibt `heygen` zurück wenn die Variable fehlt oder leer ist.

```python
@app.get("/avatar/config")
def avatar_config():
    provider = os.getenv("AVATAR_PROVIDER", "heygen").lower()
    if provider not in ("heygen", "anam"):
        provider = "heygen"
    return {"provider": provider}
```

### `POST /avatar/session`

Ruft `POST https://api.anam.ai/v1/auth/session` auf, gibt Session-Token und Persona-ID zurück. (Endpoint-URL vor Implementierung in der aktuellen [Anam API-Doku](https://docs.anam.ai) verifizieren.)

- Header an Anam: `Authorization: Bearer {ANAM_API_KEY}`
- Body an Anam: `{ "persona_id": ANAM_PERSONA_ID }`
- Antwort an Frontend: `{ "session_token": "...", "persona_id": "..." }`
- Fehler: 500 wenn `ANAM_API_KEY` fehlt, 504 bei Timeout

---

## 4. Frontend-Änderungen (`static/index.html`)

### Neues `<audio>`-Element

Anam trennt Video- und Audio-Stream — ein zusätzliches `<audio>`-Element ist nötig:

```html
<audio id="avatarAudio" autoplay></audio>
```

(Unsichtbar, kein CSS-Eintrag nötig)

### Anam SDK via CDN

```html
<script src="https://cdn.jsdelivr.net/npm/@anam-ai/js-sdk/dist/index.umd.js"></script>
```

Wird immer geladen — Overhead minimal, vereinfacht den Code.

### Neue globale Variablen

```javascript
let avatarProvider = "heygen";   // wird durch /avatar/config gesetzt
let anamClient = null;           // Anam SDK Instanz (null wenn HeyGen aktiv)
```

### Initialisierung beim Seitenstart

```javascript
fetch("/avatar/config")
  .then(r => r.json())
  .then(data => { avatarProvider = data.provider; });
```

### `startAvatar()` — bedingter Code

```javascript
async function startAvatar() {
  // ... (Spinner, Button deaktivieren — identisch für beide Provider)

  if (avatarProvider === "anam") {
    // Anam-Pfad
    const res = await fetch("/avatar/session", { method: "POST" });
    const { session_token, persona_id } = await res.json();
    anamClient = AnamSDK.createClient(session_token, {
      personaId: persona_id,
      disableInputAudio: true
    });
    await anamClient.streamToVideoAndAudioElements(avatarVideo, avatarAudio);
    // onConnectionStateChange für Fehlerbehandlung
  } else {
    // HeyGen-Pfad (unverändert)
    // ... bestehender WebRTC-Code
  }
}
```

### `avatarSpeak(text)` — bedingter Code

```javascript
async function avatarSpeak(text) {
  if (recognition) recognition.stop();
  if (avatarProvider === "anam" && anamClient) {
    await anamClient.talk(text);
  } else if (avatarProvider === "heygen" && streamingSessionId) {
    await fetch("/streaming/task", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ session_id: streamingSessionId, text })
    });
  }
}
```

### `stopAvatar()` — neu, bei Seitenunload

```javascript
window.addEventListener("beforeunload", () => {
  if (avatarProvider === "anam" && anamClient) {
    anamClient.stopStreaming();
  } else if (avatarProvider === "heygen" && streamingSessionId) {
    navigator.sendBeacon("/streaming/stop",
      JSON.stringify({ session_id: streamingSessionId }));
  }
});
```

---

## 5. Fehlerbehandlung

| Fehler | Verhalten |
|--------|-----------|
| `AVATAR_PROVIDER` fehlt oder ungültig | Default: `heygen` |
| `ANAM_API_KEY` nicht gesetzt | `/avatar/session` gibt 500 → Placeholder + "Erneut versuchen" |
| Anam SDK lädt nicht (CDN-Fehler) | `startAvatar()` fängt `ReferenceError`, zeigt Fehlermeldung |
| `anamClient.talk()` schlägt fehl | Antwort erscheint trotzdem im Text-Chat |
| Anam-Stream bricht ab | SDK-Event → Placeholder + "Erneut verbinden" + `anamClient = null` |

---

## 6. Neue Tests (`tests/test_avatar_config.py`)

- `GET /avatar/config` mit `AVATAR_PROVIDER=heygen` → `{"provider": "heygen"}`
- `GET /avatar/config` mit `AVATAR_PROVIDER=anam` → `{"provider": "anam"}`
- `GET /avatar/config` ohne Variable → `{"provider": "heygen"}` (Default)
- `POST /avatar/session` mit gültigem API-Key → proxied korrekt
- `POST /avatar/session` ohne `ANAM_API_KEY` → 500

---

## 7. Was sich nicht ändert

- `/chat`, Gemini, ChromaDB — vollständig unverändert
- Alle bestehenden HeyGen-Tests (`tests/test_streaming.py`) — laufen weiter
- Mikrofon-Button, Web Speech API — für beide Provider identisch
- Layout, Farben, Chips, Nachrichtenblasen — visuell identisch
- `AVATAR_PROVIDER=heygen` verhält sich exakt wie der aktuelle Stand

---

## 8. Abhängigkeiten & Voraussetzungen

- Anam-Account mit API-Key und Persona-ID (aus dashboard.anam.ai)
- CDN-Zugriff auf `cdn.jsdelivr.net` im Browser
- Keine neuen Python-Pakete (httpx bereits vorhanden)
