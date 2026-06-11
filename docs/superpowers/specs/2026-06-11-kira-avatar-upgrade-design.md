# KIRA Avatar-Upgrade — Design

**Datum:** 2026-06-11
**Branch:** feature/tavus
**Status:** Genehmigt

## Ziel

Latenz der KIRA-Studienberatung senken (Streaming), Avatar- und Chat-Antworten
getrennt formatieren aber inhaltlich synchron halten, Begrüßung und
Idle-Follow-up ergänzen, Avatar natürlicher wirken lassen, einheitlichen
Start-Befehl schaffen.

## Architektur-Kontext

Es gibt zwei getrennte Antwort-Pfade bei Tavus:

1. **Gesprochener Pfad:** Nutzer spricht → Tavus STT → Tavus ruft
   `POST /tavus/llm` (OpenAI-kompatibel, SSE) auf → Tavus TTS spricht die
   Antwort. Der Chat erhält den Text über `conversation.utterance`-Events.
2. **Getippter Pfad:** Frontend → `POST /chat` → Antwort im Chat →
   `conversation.echo` App-Message an Tavus → Avatar spricht den Text wortgleich.

**Entscheidungen:**
- Gesprochener Pfad zeigt die Voice-Antwort im Chat (kein WebSocket für eine
  separate Chat-Version — bewusst gegen die Komplexität entschieden).
- Begrüßung über natives Tavus `custom_greeting` (kein eigener Endpoint).
- Getippter Pfad: Voice-Version als **ein einzelnes Echo** (nicht satzweise),
  da Voice-Antworten max. 2 Sätze haben und mehrere Echos sich unterbrechen können.

## 1. Streaming & Latenz (Backend)

### `/chat` → SSE-Streaming

- Wechsel von `client.models.generate_content` (sync, blockiert den Event-Loop)
  zu `client.aio.models.generate_content_stream` (async + streaming).
- SSE-Events:
  - `{"type": "chunk", "text": "..."}` — Token-Chunks der Chat-Version
  - `{"type": "done", "voice_text": "...", "source": "Wissensbasis|LLM", "latency_ms": N, "session_id": "..."}`
- Zwei parallele Gemini-Calls via `asyncio.gather`:
  - Chat-Version: gestreamt ans Frontend
  - Voice-Version: gesammelt, im `done`-Event mitgeliefert
- ChromaDB-Query läuft **einmal** pro Anfrage; Ergebnis wird für beide Prompts geteilt.

### `/tavus/llm` → echtes Streaming

- Gemini-Stream wird chunk-weise als OpenAI-kompatible SSE-Events an Tavus
  durchgereicht (Tavus beginnt zu sprechen, sobald der erste Satz ankommt).
- Retry-Logik (3 Versuche) bleibt, mit `asyncio.sleep` statt `time.sleep`.

### Weitere Optimierungen

- ChromaDB-Warmup beim Startup (`@app.on_event("startup")` Dummy-Query).
- `GenerateContentConfig`: `max_output_tokens=300` (voice) / `500` (chat),
  Temperatur bleibt **0.2** (Faktentreue der Studienberatung).
- Embedding-Modell bleibt auf Modulebene (bereits korrekt).

## 2. Dual-Prompt-System

- `KIRA_CHAT_PROMPT`: vollständige Infos, Zahlen als Ziffern, Links erlaubt,
  bis zu 4 Sätze. Abgeleitet aus `KIRA_SYSTEM_PROMPT`.
- `KIRA_VOICE_PROMPT`: gesprochene Sprache, Zahlen ausgeschrieben, keine
  Abkürzungen, max. 2 Sätze (entspricht `KIRA_SYSTEM_PROMPT` + `KIRA_VOICE_EXTRA`).
- Beide Calls bekommen identischen RAG-Kontext und Gesprächsverlauf →
  inhaltlich synchron.
- Getippter Pfad: Chat zeigt Chat-Version (gestreamt), Avatar spricht
  Voice-Version (ein Echo nach dem `done`-Event). `pendingEchoReplies`-Dedup
  wird auf den Voice-Text umgestellt.
- Gesprochener Pfad: nur Voice-Version (via `/tavus/llm`).
- HeyGen/Anam: `avatarSpeak(voice_text)` nach Stream-Ende —
  Provider-Switching (`AVATAR_PROVIDER`) bleibt vollständig intakt.

## 3. Begrüßung

- `custom_greeting` im `/tavus/session`-Request-Body:
  > "Hallo, ich bin KIRA, deine Studienberaterin am KIT. Womit kann ich dir helfen?"
- Avatar spricht sie beim Verbinden; Chat zeigt sie automatisch über das
  vorhandene `conversation.utterance`-Event.
- Chat-only-Fall (Avatar nicht gestartet): Frontend zeigt dieselbe Begrüßung
  als statische Bot-Nachricht beim Laden — nur wenn der Verlauf leer ist.
- Kein Gemini-Call, keine zusätzliche Latenz.

## 4. Idle-Follow-up

- Client-seitiger Timer (30 s), startet nach jeder abgeschlossenen Bot-Antwort.
- Bei Ablauf: "Kann ich dir noch bei etwas helfen?" als Chat-Bubble + Echo an
  Tavus (falls verbunden).
- Reset bei Tastatureingabe oder Senden.
- Feuert **maximal einmal** pro Stille-Fenster; nach dem Follow-up startet
  kein neuer Timer.

## 5. Natürlichkeit

- Filler-Pool: `["Gute Frage.", "Lass mich kurz nachdenken.", "Also,"]`
  — mit ~30 % Wahrscheinlichkeit der Voice-Version vorangestellt
  (nie der Chat-Version).
- Keine Filler bei kurzen Antworten (< 15 Wörter).
- Filler gelten **nur für den getippten Pfad** (`/chat`), wo die Voice-Version
  vollständig vorliegt. `/tavus/llm` bleibt reines Streaming — die
  <15-Wörter-Regel wäre dort nur mit Pufferung (= Latenzverlust) prüfbar.
- Session-State merkt sich das erste Wort der letzten Voice-Antwort; der
  Voice-Prompt erhält die Anweisung, nicht mit demselben Wort zu beginnen.

## 6. Einheitlicher Start-Befehl

- `start.ps1` (Windows) und `start.sh` (Linux/Mac) im Projekt-Root:
  1. `.env` laden; Fehler mit klarer Meldung, wenn `GOOGLE_API_KEY` fehlt
     (und `TAVUS_API_KEY`, falls `AVATAR_PROVIDER=tavus`).
  2. `fill_db.py` nur ausführen, wenn `chroma_db/` nicht existiert.
  3. uvicorn auf Port 8000 mit `--reload` starten;
     `PYTHONIOENCODING=utf-8` setzen (behebt Windows-cp1252-Crash).
- Neues `README.md` mit Quick-Start-Sektion (`./start.sh` / `.\start.ps1`).

## Fehlerbehandlung

- Gemini-Fehler in `/chat`: SSE-Event `{"type": "error", "message": "..."}`;
  Frontend zeigt die bestehende Error-Bubble.
- Schlägt nur der Voice-Call fehl, wird die Chat-Antwort trotzdem geliefert
  (`voice_text` fällt auf den Chat-Text zurück).
- `/tavus/llm`: bei Gemini-Fehler nach 3 Versuchen Fallback-Text
  "Service momentan nicht verfügbar." als SSE-Stream.

## Tests

- Bestehende Tests (gemockte Module via `tests/conftest.py`) laufen weiter.
- Neu:
  - SSE-Format von `/chat` (chunk- und done-Events, Fehlerfall)
  - Dual-Prompt-Aufbau (gleicher Kontext in beiden Prompts)
  - Filler-Logik (deterministisch via gemocktem `random`; Kurz-Antwort-Ausnahme)
  - `custom_greeting` im Tavus-Session-Body
  - Start-Skripte existieren und enthalten die Pflicht-Checks

## Nicht im Scope

- Daily.co-Setup und Tavus-CVI-Eventhandling (unverändert)
- HeyGen/Anam-Sessionlogik (unverändert)
- `fill_db.py` (unverändert)
- Neue Dependencies (keine nötig)
