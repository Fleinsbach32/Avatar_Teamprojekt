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

## Avatar-Toolbar

Während ein Gespräch läuft, erscheint eine Steuerleiste am unteren Bildschirmrand:

| Button | Funktion |
|--------|----------|
| Mikrofon | Selbst-Mute (`tavusCall.setLocalAudio()`) |
| Lautsprecher | Avatar-Audio stummschalten |
| Lautstärke | Slider 0–100 % für `avatarAudio.volume` |
| Vollbild | Fullscreen-API auf dem Avatar-Container |
| Chat | Chat-Panel ein-/ausblenden |
| Beenden | Gespräch beenden (rot) |

Die Toolbar erscheint wenn das Avatar-Video startet und verschwindet bei Gesprächsende.

## Architektur

- **Backend:** FastAPI im `app/`-Paket — RAG über ChromaDB + Google Gemini 2.5 Flash.
  - `app/main.py`: App-Wiring, Middleware, `/health`, Static-Files
  - `app/auth.py`: HTTP Basic Auth (`check_auth`) für Browser-Endpoints
  - `app/routes/chat.py` → `/chat`: SSE-Streaming für den Text-Chat (Text-Prompt)
  - `app/routes/tavus.py` → `/tavus/llm`: OpenAI-kompatibles Streaming für Tavus CVI (Voice-Prompt)
  - `app/routes/avatar.py` → `/avatar/config`: Provider-Konfiguration
  - `app/prompts.py`: getrennte Text- und Voice-Prompts (DE/EN) via `build_prompt(mode, lang)`
  - `app/rag.py`: zweistufige ChromaDB-Suche mit Studiengang-Filter, Modul-ID- und Modul-Namen-Lookup
  - `app/session.py`: In-Memory-Sessions
- **Frontend:** `static/index.html` — Chat-Panel + Tavus-Avatar (Daily.co) + Avatar-Toolbar.
- **Wissensbasis:** `scripts/fill_db.py` lädt `data/faq_de.json` + `data/faq_eng.json` + PDFs aus `data/pdfs/` modulweise in ChromaDB (67.112 Einträge, Stand 17.06.2026).

### RAG-Strategie

Die Suche ist zweistufig wenn ein Studiengang gewählt ist:

1. **Stufe 1 — Studiengang-Handbuch** (`program == studiengang`, n=4): Modulhandbuch-Chunks des gewählten Studiengangs erhalten Vorrang.
2. **Stufe 2 — Allgemeines** (`program == "all"`, n=3): FAQ, Web-Crawl, studiengangsübergreifende Infos.

Zusammengeführt werden maximal 6 Chunks (Handbuch zuerst). Ohne Studiengang-Filter: einstufige Suche mit n=6 über die gesamte Wissensbasis.

Spezielle Erkennungspfade in `app/rag.py`:
- **Modul-ID** (`M-WIWI-…`, `T-WIWI-…`): Metadaten-Lookup → Volltext-Fallback (`$contains`).
- **"Modulnummer von X?"**: Volltext-Suche auf Modulnamen, extrahiert via Regex.
- **"Was ist das Modul X?"**: Volltext-Suche auf Modulnamen; wenn nicht gefunden → explizite "nicht in DB"-Anweisung (verhindert Halluzination von Alternativ-Modulen).

## Tests

### Unit- und Integrationstests

```powershell
$env:PYTHONIOENCODING="utf-8"; python -m pytest tests/ -v
```

### Systematisches Ende-zu-Ende-Testing

Das Skript `scripts/test_kira.py` schickt 37 reale Anfragen an den laufenden Server
und gibt Antwort, Quelle (Wissensbasis / LLM) und Latenz aus:

```powershell
# Server muss laufen (.\run.ps1)
$env:PYTHONIOENCODING="utf-8"
python scripts/test_kira.py --user DEIN_USERNAME --pass DEIN_PASSWORD
```

Die Testfälle decken ab: FAQ, Studiengangs-Anfragen mit/ohne Filter, Modul-IDs,
Name-zu-Nummer-Abfragen, Vergleiche, Empathie, Fact-Checking, Off-Topic,
englische Anfragen.

### DB-Inspektion

```powershell
$env:PYTHONIOENCODING="utf-8"; python scripts/inspect_db.py
```

Zeigt Modul-IDs je Studiengang, prüft spezifische Modul-Suchen und gibt
Stichproben der ChromaDB-Einträge aus. Nützlich zur Diagnose von RAG-Fehlern.
