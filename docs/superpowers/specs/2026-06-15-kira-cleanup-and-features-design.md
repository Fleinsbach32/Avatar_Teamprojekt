# KIRA — Cleanup & Feature-Erweiterung: Design

**Datum:** 2026-06-15  
**Status:** Genehmigt  
**Scope:** Modulaufteilung, vereinheitlichter Start-Befehl, Sprachauswahl, Studiengang-Auswahl, getrennte Voice/Text-Prompts, Entfernung von HeyGen/Anam/LiveAvatar

---

## 1. Projektstruktur (Ziel)

```
Avatar_Teamprojekt/
├── run.ps1                  # einziges Start-Skript (idempotent, ersetzt setup.ps1 + start.ps1 + start.sh)
├── fill_db.py
├── requirements.txt
├── .env / .env.example
├── data/
├── chroma_db/
├── static/
│   └── index.html
└── app/
    ├── __init__.py
    ├── main.py              # FastAPI-App-Instanz, Middleware, Router-Einbindung (~40 Zeilen)
    ├── prompts.py           # KIRA_BASE_PROMPT, Text- und Voice-Erweiterungen (DE/EN)
    ├── rag.py               # ChromaDB-Client, build_rag_context(), STUDIENGANG_FILES
    ├── session.py           # sessions-Dict, touch_session(), opening-Tracking
    └── routes/
        ├── __init__.py
        ├── chat.py          # POST /chat
        ├── tavus.py         # POST /tavus/session, /tavus/end, /tavus/message, /tavus/llm
        └── avatar.py        # GET /avatar/config (Provider-Abstraktion, vorerst nur tavus)
```

**Bestehende Datei `main.py`** wird zu `app/main.py` umgezogen und auf App-Init reduziert.  
Der uvicorn-Aufruf in `run.ps1` referenziert dann `app.main:app`.

---

## 2. Idempotenter Start-Befehl (`run.ps1`)

`setup.ps1`, `start.ps1` und `start.sh` entfallen vollständig.

### Ablauf (sequenziell)

1. **`.env` prüfen** — falls fehlt: Anleitung ausgeben + Exit
2. **ngrok prüfen** — falls nicht im PATH und nicht unter `$HOME\ngrok\ngrok.exe`: herunterladen, entpacken, PATH setzen
3. **ngrok Authtoken prüfen** — falls `ngrok config check` fehlschlägt: Token einmalig abfragen und speichern
4. **pip-Abhängigkeiten prüfen** — falls `.pip-stamp` fehlt oder älter als `requirements.txt`: `pip install -r requirements.txt`, danach `.pip-stamp` aktualisieren
5. **ChromaDB prüfen** — falls `chroma_db/` fehlt: `python fill_db.py` ausführen
6. **ngrok im Hintergrund starten** — `Start-Job { ngrok http 8000 }`; nach 2 s ngrok-API (`localhost:4040/api/tunnels`) abfragen und öffentliche URL im Terminal ausgeben
7. **uvicorn starten** — `python -m uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload` (Vordergrund)

### Idempotenz-Mechanismus

- ngrok-Download: nur wenn Binary nicht vorhanden
- pip install: nur wenn `.pip-stamp` fehlt oder `requirements.txt` neuer ist (Datei-Timestamp-Vergleich)
- fill_db: nur wenn `chroma_db/` nicht existiert
- ngrok-Start: prüft vor dem Start ob Port 4040 (ngrok-API) bereits antwortet

---

## 3. Sprachauswahl (DE / EN)

### Frontend

- **Toggle-Button im Header** (rechts, neben Status): `DE | EN`
- Beim Umschalten: `lang`-Variable setzen + `applyLang()` aufrufen
- `applyLang()` setzt alle DOM-Texte über ein `I18N`-Dictionary:

```javascript
const I18N = {
  de: {
    placeholder: "Ihre Frage an KIRA...",
    greeting: "Hallo, ich bin KIRA ...",
    statusReady: "bereit",
    statusConnecting: "verbinde...",
    statusOffline: "server nicht erreichbar",
    idleFollowup: "Kann ich dir noch bei etwas helfen?",
    chips: ["Prüfungsanmeldung", "Bewerbungsfristen", "Beurlaubung", "Sprechzeiten"],
    chipQuestions: ["Wie melde ich mich für Prüfungen an?", ...],
    startBtn: "▶ Gespräch starten",
    hint: "Enter zum Senden · Shift+Enter für neue Zeile",
    chatTitle: "KIRA",
    emptyStateText: "Hallo, ich bin KIRA ...",
  },
  en: {
    placeholder: "Your question for KIRA...",
    greeting: "Hi, I'm KIRA ...",
    statusReady: "ready",
    statusConnecting: "connecting...",
    statusOffline: "server not reachable",
    idleFollowup: "Can I help you with anything else?",
    chips: ["Exam registration", "Application deadlines", "Leave of absence", "Office hours"],
    chipQuestions: ["How do I register for exams?", ...],
    startBtn: "▶ Start conversation",
    hint: "Enter to send · Shift+Enter for new line",
    chatTitle: "KIRA",
    emptyStateText: "Hi, I'm KIRA ...",
  }
};
```

- `lang` wird als Feld bei jeder API-Anfrage mitgesendet: `{ message, session_id, lang, studiengang }`
- Spracheinstieg der SpeechRecognition wird entsprechend gesetzt (`de-DE` / `en-US`)

### Backend

`ChatRequest` und `TavusLLMRequest` erhalten ein optionales Feld `lang: str = "de"`.  
`build_prompt(mode, lang)` in `app/prompts.py` wählt die passende Erweiterung.

---

## 4. Prompt-Architektur (`app/prompts.py`)

```python
KIRA_BASE_PROMPT = """
Du bist KIRA / You are KIRA, Studienberaterin am KIT ...
[sprachunabhängiger Kern: Rolle, Sicherheitsregeln, Themenabgrenzung]
"""

KIRA_TEXT_EXT = {
    "de": "Antworte auf Deutsch. [Textregeln: Listen erlaubt, strukturierter, bis 5 Sätze]",
    "en": "Answer in English. [Text rules: lists allowed, structured, up to 5 sentences]",
}

KIRA_VOICE_EXT = {
    "de": "Antworte auf Deutsch. [Voice-Regeln: keine Listen, kurze Sätze, gut hörbar, max 3 Sätze]",
    "en": "Answer in English. [Voice rules: no lists, short sentences, speakable, max 3 sentences]",
}

def build_prompt(mode: Literal["text", "voice"], lang: str = "de") -> str:
    ext = KIRA_TEXT_EXT if mode == "text" else KIRA_VOICE_EXT
    return f"{KIRA_BASE_PROMPT}\n\n{ext.get(lang, ext['de'])}"
```

`/chat` ruft `build_prompt("text", lang)` auf, `/tavus/llm` ruft `build_prompt("voice", lang)` auf.

---

## 5. Studiengang-Auswahl

### Frontend

Dropdown im Header (links vom DE/EN-Toggle):

| Anzeigename | Key |
|---|---|
| (kein Filter) | `null` |
| WiWi BSc | `wiwi_bsc` |
| WiWi MSc | `wiwi_msc` |
| TVWL BSc | `tvwl_bsc` |
| TVWL MSc | `tvwl_msc` |
| WiInf BSc | `wiinf_bsc` |
| WiInf MSc | `wiinf_msc` |
| WiIng BSc | `wiing_bsc` |
| WiIng MSc | `wiing_msc` |
| WiMa MSc | `wima_msc` |
| IEAM MSc | `ieam_msc` |

Auswahl wird als `studiengang: string | null` bei jeder Anfrage mitgesendet.  
Dropdown-Labels werden ebenfalls per `I18N` übersetzt (DE: "Studiengang", EN: "Programme").

### Backend (`app/rag.py`)

```python
STUDIENGANG_FILES: dict[str, list[str]] = {
    "wiwi_bsc":  ["mhb_de_BSc_de_aktuell.pdf"],
    "wiwi_msc":  ["mhb_de_MSc_en_aktuell.pdf"],
    "tvwl_bsc":  ["mhb_tvwl_BSc_de_aktuell.pdf"],
    "tvwl_msc":  ["mhb_tvwl_MSc_de_aktuell.pdf"],
    "wiinf_bsc": ["mhb_wiinf_BSc_de_aktuell.pdf"],
    "wiinf_msc": ["mhb_wiinf_MSc_de_aktuell.pdf"],
    "wiing_bsc": ["mhb_wiing_BSc_de_aktuell.pdf"],
    "wiing_msc": ["mhb_wiing_MSc_de_aktuell.pdf"],
    "wima_msc":  ["mhb_wima_MSc_de_aktuell.pdf"],
    "ieam_msc":  ["mhb_ieam_MSc_en_aktuell.pdf"],
}

def build_rag_context(query: str, studiengang: str | None = None) -> tuple[str, str, float]:
    where = {"source": {"$in": STUDIENGANG_FILES[studiengang]}} if studiengang else None
    results = collection.query(query_texts=[query], n_results=3, where=where, include=["documents", "distances"])
    ...
```

`ChatRequest` und `TavusLLMRequest` erhalten `studiengang: str | None = None`.

---

## 6. Code-Aufräumen: HeyGen / Anam / LiveAvatar entfernen

### Was entfällt

**Backend (`main.py` → `app/`):**
- `/avatar/session` (Anam)
- `/liveavatar/session`, `/liveavatar/stop`
- `/tts` (HeyGen TTS)
- `LiveAvatarStopRequest`-Model
- Alle `ANAM_*`, `LIVEAVATAR_*`, `HEYGEN_*` env-var-Zugriffe

**Frontend (`static/index.html`):**
- CDN-Imports: Anam SDK, LiveKit Client
- Funktionen: `_startAvatarAnam()`, `_startAvatarLiveAvatar()`
- Variablen: `liveKitRoom`, `liveAvatarSessionId`, `anamClient`

**Skripte:**
- `setup.ps1`, `start.ps1`, `start.sh` (ersetzt durch `run.ps1`)

**`.env.example`:**
```
GOOGLE_API_KEY=
TAVUS_API_KEY=
TAVUS_REPLICA_ID=
TAVUS_PERSONA_ID=    # optional
```

### Was bleibt (Provider-Abstraktion)

`app/routes/avatar.py` liefert weiterhin `GET /avatar/config → {"provider": "tavus"}`.  
`AVATAR_PROVIDER` bleibt als env-var erhalten (Default: `"tavus"`), damit künftige Provider ohne Frontend-Änderungen ergänzt werden können.  
Das Frontend liest den Provider beim Start und ruft den passenden `_startAvatar*`-Branch auf — aktuell existiert nur `_startAvatarTavus()`.

---

## 7. Nicht im Scope

- Neue Avatar-Provider
- Persistente Nutzerkonten oder Datenbankanbindung
- Admin-Interface für Prompt-Verwaltung
- Mobile App

---

## 8. Offene Punkte (zu klären bei Implementierung)

- ChromaDB-`where`-Filter: testen ob `$in` mit Einzelelement-Listen korrekt funktioniert; Fallback auf `$eq` falls nötig
- Englische Prompt-Inhalte für `KIRA_BASE_PROMPT`: inhaltlich identisch zur deutschen Version, nur übersetzt — kein anderes Verhalten
- ngrok-Job in `run.ps1`: PowerShell `Start-Job` vs. `Start-Process` — je nach Windows-Version testen
