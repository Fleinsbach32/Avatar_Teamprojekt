# Design: Chat-Avatar-Integration (Tavus Texteingabe)

**Datum:** 2026-06-01  
**Status:** Genehmigt

## Problem

Chat-Panel und Tavus-Avatar sind aktuell getrennt. Wenn der User Text tippt, erscheint die Antwort nur im Chat — der Avatar spricht nicht. Nur Spracheingabe (Mikrofon) geht durch das Tavus-CVI-Pipeline und lässt den Avatar sprechen. HeyGen/Anam sind bereits verbunden (via `avatarSpeak()`).

## Ziel

Text-Eingabe im Chat soll denselben Pipeline-Flow wie Spracheingabe auslösen: Avatar spricht, Transkription erscheint im Chat. Ein einheitlicher Gesprächsfluss für alle Eingabearten.

## Gewählter Ansatz: Text durch Tavus CVI routen

```
User tippt Text
     ↓
addMessage("user", text)            ← sofort sichtbar im Chat
     ↓
POST /tavus/message (neuer Endpoint)
     ↓
Tavus API: POST /v2/conversations/{id}/message
     ↓
Tavus ruft /tavus/llm auf           ← bereits vorhanden
     ↓
Avatar spricht                      ← CVI-Pipeline
     ↓
transcription-message Event         ← bereits vorhanden
     ↓
addMessage("bot", text)             ← Antwort im Chat
```

**Fallback:** Kein aktiver Tavus-Avatar (`tavusConversationId` null) → `POST /chat` wie bisher.

## Backend-Änderungen (`main.py`)

### Neues Pydantic-Modell

```python
class TavusMessageRequest(BaseModel):
    conversation_id: str
    message: str
```

### Neuer Endpoint `POST /tavus/message`

Ruft `POST https://tavusapi.com/v2/conversations/{conversation_id}/message` auf.

- Request-Body an Tavus: `{"message": request.message}`
- Erfolg (HTTP 200/201): gibt `{"status": "sent"}` zurück
- Fehler: `HTTPException` mit Tavus-Statuscode + Detail
- Timeout (15s): `HTTPException 504`

## Frontend-Änderungen (`static/index.html`)

### Neue Variablen

```javascript
const pendingTypedMessages = new Set(); // dedup: getippte Nachrichten
let tavusTypingId = null;               // Typing-Indicator für Tavus-Flow
```

### Aktualisierter `transcription-message` Handler

```javascript
tavusCall.on("transcription-message", (e) => {
    if (!e.is_final) return;
    openChat();
    if (e.role === "user") {
        const key = e.text.toLowerCase().trim();
        if (pendingTypedMessages.has(key)) {
            pendingTypedMessages.delete(key);
            return; // bereits als getippte Nachricht gezeigt
        }
        addMessage("user", e.text); // Spracheingabe → normal
    }
    if (e.role === "assistant") {
        if (tavusTypingId) { removeTyping(tavusTypingId); tavusTypingId = null; }
        document.getElementById("statusText").textContent = "bereit";
        addMessage("bot", e.text);
    }
});
```

### Aktualisierte `sendMessage()` Funktion

Split nach Provider + Session-Status:

**Zweig A — Tavus mit aktiver Session:**
1. `addMessage("user", text)` — sofort sichtbar
2. `pendingTypedMessages.add(text.toLowerCase().trim())` — dedup vorbereiten
3. `tavusTypingId = showTyping()` — Typing-Indicator
4. `POST /tavus/message` mit `{conversation_id, message}`
5. Bei Fehler: Typing entfernen, dedup-Set bereinigen, `showError()`
6. `sendBtn` re-aktivieren nach HTTP-Antwort (nicht erst nach Bot-Antwort)
7. Bot-Antwort + Typing-Removal erfolgt via `transcription-message` Event

**Zweig B — HeyGen, Anam, oder Tavus ohne aktive Session:**
- Identisch zum aktuellen `/chat`-Flow (unverändert)

## Was sich nicht ändert

- `/chat` Endpoint unberührt
- `avatarSpeak()` für HeyGen/Anam unberührt
- Spracheingabe via Mikrofon unverändert
- Alle anderen Tavus-Events (track-started, left-meeting, etc.) unverändert

## Fehlerbehandlung

| Szenario | Verhalten |
|---|---|
| Tavus API nicht erreichbar | `showError()` im Chat, dedup-Set bereinigt, Typing entfernt |
| Kein aktiver Avatar (kein `conversation_id`) | Fallback auf `/chat` |
| Transkription kommt nie (Timeout) | Typing-Indicator bleibt — kein Auto-Remove (seltener Edge-Case) |

## Teststrategie

- Neuer Unittest `test_tavus_message` in `tests/test_tavus.py`
- Manuell: Text tippen mit laufendem Tavus-Avatar → Avatar spricht, Chat zeigt Antwort
- Manuell: Text tippen ohne Avatar → Fallback auf /chat-Text-Antwort
- Manuell: Mikrofon-Eingabe → unverändert wie bisher
