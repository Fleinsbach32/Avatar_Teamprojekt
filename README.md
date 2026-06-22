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

## Voraussetzungen

1. `.env` aus `.env.example` kopieren und `GOOGLE_API_KEY` setzen.
2. Für den Avatar (`AVATAR_PROVIDER=tavus`): zusätzlich `TAVUS_API_KEY` und `TAVUS_REPLICA_ID` setzen.
   Für den gesprochenen Pfad muss der Server öffentlich erreichbar sein — `run.ps1` startet dafür automatisch ngrok.
   Die ausgegebene ngrok-URL + `/tavus/llm` wird im **Tavus-Dashboard in der Persona** als Custom-LLM-URL hinterlegt — nicht in der `.env`.

## Sprache & Studiengang

- Die Sprache (Deutsch/Englisch) wird über zwei Flaggen-Buttons **DE | EN** oben rechts im UI gewählt; der aktive Button ist hervorgehoben. Die Auswahl steuert sowohl die UI-Texte als auch die Antwortsprache von KIRA.
- Über das Studiengang-Dropdown lässt sich die Wissensbasis auf das jeweilige Modulhandbuch filtern. Die Labels sind eindeutig: **WING (B.Sc.)** und **WING (M.Sc.)**. Die Auswahl gilt für die laufende Session.

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
  - `app/main.py`: App-Wiring, Middleware, `/health`, Static-Files; Reranker-Warmup im Lifespan
  - `app/routes/chat.py` → `/chat`: SSE-Streaming für den Text-Chat (Text-Prompt)
  - `app/routes/tavus.py` → `/tavus/llm`: OpenAI-kompatibles Streaming für Tavus CVI (Voice-Prompt)
  - `app/routes/avatar.py` → `/avatar/config`: Provider-Konfiguration
  - `app/prompts.py`: getrennte Text- und Voice-Prompts (DE/EN) via `build_prompt(mode, lang)`
  - `app/rag.py`: zweistufige ChromaDB-Suche mit CrossEncoder-Reranker, Studiengang-Filter, Modul-ID- und Modul-Namen-Lookup
  - `app/session.py`: In-Memory-Sessions
- **Frontend:** `static/index.html` — Chat-Panel + Tavus-Avatar (Daily.co) + Avatar-Toolbar.
- **Wissensbasis:** `scripts/fill_db.py` lädt `data/faq_de.json` + `data/faq_eng.json` + PDFs aus `data/pdfs/` modulweise in ChromaDB (67.112 Einträge, Stand 17.06.2026).
  - DB-Pfad: `chroma_db/` im Projekt-Root. ZIP-Backup: `data/chroma_db.zip` (1,15 GB).

### RAG-Strategie

Die Suche ist zweistufig wenn ein Studiengang gewählt ist:

1. **Stufe 1 — Studiengang-Handbuch** (`program == studiengang`, n=8): Modulhandbuch-Chunks des gewählten Studiengangs erhalten Vorrang (n=12 für Pflichtmodul-Anfragen).
2. **Stufe 2 — Allgemeines** (`program == "all"`, n=4): FAQ, Web-Crawl, studiengangsübergreifende Infos.

Der zusammengeführte Kandidatenpool (12 bzw. 16 Chunks) wird durch einen **CrossEncoder-Reranker** (`cross-encoder/mmarco-mMiniLMv2-L12-H384-v1`) neu bewertet; die top-6 Chunks gehen in den Kontext. `_merge_handbook_priority()` stellt sicher, dass mindestens 3 studiengangs-spezifische Handbuch-Chunks erhalten bleiben, auch wenn der Reranker generische Web-Chunks höher bewertet.

Ohne Studiengang-Filter: einstufige semantische Suche mit n=6 über die gesamte Wissensbasis (kein Reranker).

Spezielle Erkennungspfade in `app/rag.py`:
- **Modul-ID** (`M-WIWI-…`, `T-WIWI-…`): Metadaten-Lookup → Volltext-Fallback (`$contains`).
- **"Modulnummer von X?"**: Volltext-Suche auf Modulnamen, extrahiert via Regex.
- **"Was ist [das Modul] X?"**: Volltext-Suche auf Modulnamen (`_WHAT_IS_MODULE_RE`, "Modul"-Keyword optional); wenn nicht gefunden → explizite "nicht in DB"-Anweisung (verhindert Halluzination von Alternativ-Modulen).

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
python scripts/test_kira.py
```

Die Testfälle decken ab: FAQ, Studiengangs-Anfragen mit/ohne Filter, Modul-IDs,
Name-zu-Nummer-Abfragen, Vergleiche, Empathie, Fact-Checking, Off-Topic,
englische Anfragen.

### DB-Übersicht

```powershell
$env:PYTHONIOENCODING="utf-8"; python scripts/check_db.py
```

Zeigt Eintragsanzahl, Typ-Verteilung, Studiengänge und Sanity Checks der ChromaDB. Schneller Einstieg zur Diagnose von DB-Problemen.

### DB-Inspektion (detailliert)

```powershell
$env:PYTHONIOENCODING="utf-8"; python scripts/inspect_db.py
```

Zeigt Modul-IDs je Studiengang, prüft spezifische Modul-Suchen und gibt
Stichproben der ChromaDB-Einträge aus. Nützlich zur Diagnose von RAG-Fehlern.

### Latenz-Benchmark

```powershell
$env:PYTHONIOENCODING="utf-8"; python scripts/bench_rag.py
```

Misst die RAG-Latenz mit und ohne Reranker je Query-Typ (mit/ohne Studiengang-Filter, Modul-ID-Lookup). Nützlich zum Vergleich von Konfigurationsänderungen.
