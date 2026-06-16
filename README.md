# KIRA — KIT Studienberatung mit Avatar

## Quick Start

```powershell
.\run.ps1
```

`run.ps1` ist idempotent und übernimmt alles in einem Befehl:
- prüft die `.env`
- installiert beim ersten Aufruf ngrok und die Python-Abhängigkeiten
- befüllt die ChromaDB beim ersten Start (`scripts/fill_db.py`)
- startet ngrok im Hintergrund und gibt die öffentliche URL aus
- startet den Server auf http://localhost:8000

Folgeaufrufe überspringen bereits erledigte Schritte automatisch.

## Web-Authentifizierung

Die UI ist per HTTP Basic Auth geschützt. Benutzer/Passwort werden in `.env`
gesetzt (`APP_USERNAME`/`APP_PASSWORD`, Default `admin`/`geheim`). Geschützt sind
alle Browser-Endpoints (`/`, `/chat`, `/avatar/config`, `/tavus/session|end|message|settings`).

**Bewusst NICHT geschützt** sind die von Tavus CVI serverseitig aufgerufenen
LLM-Endpoints (`/tavus/llm`, `/tavus/llm/chat/completions`, `/chat/completions`)
sowie `/health` — Tavus kann keine Basic-Auth-Credentials mitsenden; eine Auth
darauf würde den gesprochenen Avatar-Pfad mit 401 abbrechen.

## Voraussetzungen

1. `.env` aus `.env.example` kopieren und `GOOGLE_API_KEY` sowie
   `APP_USERNAME`/`APP_PASSWORD` setzen.
2. Für den Avatar (`AVATAR_PROVIDER=tavus`): zusätzlich `TAVUS_API_KEY` und `TAVUS_REPLICA_ID` setzen.
   Für den gesprochenen Pfad muss der Server öffentlich erreichbar sein — `run.ps1` startet dafür automatisch ngrok.
   Die ausgegebene ngrok-URL + `/tavus/llm` wird im **Tavus-Dashboard in der Persona** als Custom-LLM-URL hinterlegt — nicht in der `.env`.

## Sprache & Studiengang

- Die Sprache (Deutsch/Englisch) wird über den Umschalter oben rechts im UI gewählt; sie steuert sowohl die UI-Texte als auch die Antwortsprache von KIRA.
- Über das Studiengang-Dropdown lässt sich die Wissensbasis auf das jeweilige Modulhandbuch filtern. Die Auswahl gilt für die laufende Session.

## Voice-Pfad: Sprache & Studiengang

Tavus CVI ruft den Custom-LLM-Endpoint serverseitig auf und sendet dabei keine UI-Felder mit. Damit der gesprochene Pfad trotzdem die im UI gewählte Sprache und den Studiengang berücksichtigt, merkt sich das Backend die zuletzt gewählten Voice-Einstellungen (`active_voice_prefs` in [app/routes/tavus.py](app/routes/tavus.py)):

- Beim Avatar-Start (`POST /tavus/session`) und bei jeder Änderung von Sprache oder Studiengang sendet das Frontend die aktuelle Auswahl an `POST /tavus/settings`.
- `POST /tavus/llm` (bzw. die Aliase `/tavus/llm/chat/completions` und `/chat/completions`) liest Sprache und Studiengang aus diesen Einstellungen.

**Einschränkung:** Der Zustand ist global, also für den lokalen Einzel-Session-Betrieb (ein Avatar gleichzeitig) ausgelegt. Bei mehreren parallelen Gesprächen würden sich die Einstellungen überschreiben.

### Tavus-Dashboard

Als Custom-LLM-URL kann entweder die ngrok-Root (`https://<id>.ngrok-free.dev`) oder die URL mit `/tavus/llm` hinterlegt werden — beide Varianten funktionieren, da `/chat/completions` zusätzlich auf der Root registriert ist.

## Architektur

- **Backend:** FastAPI im `app/`-Paket — RAG über ChromaDB + Google Gemini.
  - `app/main.py`: App-Wiring, Middleware, `/health`, Static-Files
  - `app/routes/chat.py` → `/chat`: SSE-Streaming für den Text-Chat (Text-Prompt)
  - `app/routes/tavus.py` → `/tavus/llm`: OpenAI-kompatibles Streaming für Tavus CVI (Voice-Prompt)
  - `app/routes/avatar.py` → `/avatar/config`: Provider-Konfiguration
  - `app/prompts.py`: getrennte Text- und Voice-Prompts (DE/EN) via `build_prompt(mode, lang)`
  - `app/rag.py`: ChromaDB-Abfrage mit optionalem Studiengang-Filter
  - `app/session.py`: In-Memory-Sessions
- **Frontend:** `static/index.html` — Chat-Panel + Tavus-Avatar (Daily.co).
- **Wissensbasis:** `scripts/fill_db.py` lädt `data/faq.json` + PDFs in ChromaDB.

## Tests

```powershell
$env:PYTHONIOENCODING="utf-8"; python -m pytest tests/ -v
```
