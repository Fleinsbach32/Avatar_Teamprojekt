# Design: Geteiltes Session-Memory (Chat + Voice)

**Datum:** 2026-06-24
**Status:** Approved

## Problem

Text-Chat (`/chat`) und Voice (`/tavus/llm`) haben **getrennte Erinnerung**:

- Chat schreibt und liest `sessions[session_id]` (Server-Memory in [app/session.py](app/session.py)).
- Voice baut seinen Verlauf nur aus den von Tavus mitgeschickten Nachrichten (`request.messages`)
  und nutzt `sessions` gar nicht.

Folge: Tippt der Nutzer etwas im Chat und spricht dann weiter, weiß der Avatar nichts vom
getippten Teil (und umgekehrt). Der fehlende Link: das Frontend sendet die `session_id` an
`/chat`, aber **nicht** an den Voice-Pfad (`pushVoicePrefs()` schickt nur `lang`/`studiengang`).

## Entscheidungen (aus dem Brainstorming)

- **Voll bidirektional:** beide Pfade lesen UND schreiben denselben Konversations-Store.
- **Verlaufsfenster: 6 Nachrichten** (3 Runden) — gemeinsam für Chat + Voice.
- **Speicher-Cap: 20 Nachrichten** pro Session (behebt unbegrenztes Wachstum nebenbei).
- **Rollen-Labels vereinheitlicht:** „Du" (Nutzer) / „KIRA" (Assistent).
- **Fallback:** ohne `session_id` läuft Voice wie bisher (Tavus-Nachrichten) — kein Crash.

## Architektur

Ein geteilter Store `sessions[session_id]`; der Voice-Pfad bekommt über `active_voice_prefs`
Zugriff auf die `session_id`, die das Frontend beim Voice-Start/Settings mitsendet.

### `app/session.py`

Neue Konstanten und Helfer (von beiden Pfaden genutzt, DRY):

```python
HISTORY_WINDOW = 6   # Nachrichten, die ins Prompt gehen
MAX_HISTORY = 20     # gespeicherte Nachrichten pro Session (Cap)

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

### `app/routes/chat.py`

- `verlauf` aus `recent_history(request.session_id)` statt `chat_history[-4:]`.
- Nach erfolgreicher Antwort `record_turn(request.session_id, request.message, answer)`
  statt der zwei manuellen Appends. `remember_opening` bleibt.

### `app/routes/tavus.py`

- `TavusPrefsRequest` bekommt `session_id: str | None = None`.
- `/tavus/settings` und `/tavus/session` speichern `session_id` in `active_voice_prefs`.
- `active_voice_prefs` initial: `{"lang": "de", "studiengang": None, "session_id": None}`.
- `/tavus/llm`:
  - `sid = active_voice_prefs["session_id"]`
  - `verlauf` aus `recent_history(sid)` wenn `sid` gesetzt, sonst Fallback auf den bisherigen
    Aufbau aus `request.messages`.
  - `touch_session(sid)` aufrufen (wenn `sid` gesetzt), damit die geteilte Session am Leben bleibt.
  - Nach erfolgreichem Stream den vollen Antworttext sammeln und `record_turn(sid, user_message, answer)`
    schreiben (nur bei `sid` gesetzt und vollständiger Antwort — kein Schreiben bei Mid-Stream-Fehler).

### `static/index.html`

- `pushVoicePrefs()` und der `/tavus/session`-Start-Body senden zusätzlich `session_id: sessionId`.

## Datenfluss

```
Tippen:  /chat → record_turn(sid, frage, antwort) → sessions[sid]
Sprechen: Frontend meldet sid an /tavus/settings → active_voice_prefs["session_id"]
          /tavus/llm: verlauf = recent_history(sid)  (enthält getippte UND gesprochene Turns)
                      nach Antwort → record_turn(sid, frage, antwort)
```

## Tests

- `record_turn`: hängt zwei Turns an, Rollen „Du"/„KIRA", trimmt auf `MAX_HISTORY` (z.B. 25 Turns → 20 bleiben).
- `recent_history`: gibt höchstens `HISTORY_WINDOW` (6) zurück; leere Liste bei unbekannter Session.
- `test_chat_history_stored` anpassen: Rolle „KIRA" statt „Bot".
- Voice-Integration: bei gesetzter `session_id` landet ein gesprochener Turn in `sessions[sid]`,
  und ein zuvor per `record_turn` eingefügter getippter Turn erscheint im Voice-Prompt (`contents`).
- Voice-Fallback: ohne `session_id` nutzt `/tavus/llm` weiterhin `request.messages` (kein Crash).

## Erfolgskriterien

- Getippte und gesprochene Turns teilen sich eine durchgehende History (max. 6 im Prompt, max. 20 gespeichert).
- Bestehende Tests grün (mit angepasstem `test_chat_history_stored`).
- Ohne `session_id` bleibt der Voice-Pfad funktionsfähig (Fallback).

## Außerhalb des Scope

- Persistenz über Neustart hinweg, Multi-Worker/Redis (bleibt dokumentierte Einzel-Session-Annahme).
- Opening-Variation für den Voice-Pfad (bleibt Chat-only).
- Rolling-Summary langer Konversationen (YAGNI).
