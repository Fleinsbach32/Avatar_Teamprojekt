# KIRA — KIT Studienberatung mit Avatar

## Quick Start

```bash
# Windows
.\start.ps1

# Linux / Mac
./start.sh
```

Das Skript prüft die `.env`, befüllt die ChromaDB beim ersten Start und startet den Server auf http://localhost:8000.

## Voraussetzungen

1. Python-Abhängigkeiten: `pip install -r requirements.txt` (oder `.\setup.ps1`)
2. `.env` aus `.env.example` kopieren und mindestens `GOOGLE_API_KEY` setzen.
3. Avatar-Provider in `.env` wählen: `AVATAR_PROVIDER=heygen | anam | tavus`
   - Bei `tavus`: zusätzlich `TAVUS_API_KEY`, `TAVUS_REPLICA_ID` setzen. Für den gesprochenen Pfad muss `BASE_URL` öffentlich erreichbar sein (lokal: `ngrok http 8000`, dann die ngrok-URL eintragen).

## Architektur

- **Backend:** FastAPI (`main.py`) — RAG über ChromaDB + Google Gemini.
  - `/chat`: SSE-Streaming, Dual-Prompt (Chat-Vollversion + natürliche Sprech-Version)
  - `/tavus/llm`: OpenAI-kompatibles Streaming für Tavus CVI
- **Frontend:** `static/index.html` — Chat-Panel + Avatar (Daily.co / LiveKit / Anam SDK)
- **Wissensbasis:** `fill_db.py` lädt `data/faq.json` + PDFs in ChromaDB.

## Tests

```powershell
$env:PYTHONIOENCODING="utf-8"; python -m pytest tests/ -v
```
