# KIRA — Technische Dokumentation

Detaillierte Erklärung des Codes und der Methodik hinter der KIRA-Studienberatung
(KIT) mit sprechendem Avatar.

**Stand:** Juni 2026 · **Branch:** feature/tavus

---

## 1. Überblick

KIRA ist eine Studienberatungs-Webanwendung mit zwei Eingabewegen:

1. **Text-Chat** — der Nutzer tippt eine Frage in das Chat-Panel.
2. **Gespräch mit dem Avatar** — der Nutzer spricht; ein fotorealistischer
   Video-Avatar (Tavus) hört zu und antwortet mit Stimme und Lippenbewegung.

Beide Wege nutzen dieselbe Wissensbasis (RAG über ChromaDB) und dasselbe
Sprachmodell (Google Gemini 2.5 Flash). **Text- und Sprachausgabe sind
identisch**: Was im Chat steht, ist exakt das, was der Avatar spricht.

```
┌──────────────┐   tippt    ┌──────────────────────────────┐
│   Browser    │ ─────────▶ │  POST /chat (SSE-Stream)      │
│ (index.html) │ ◀───────── │  FastAPI-Backend (main.py)    │
│              │   chunks   │   ├─ ChromaDB (RAG)           │
│  Daily.co ◀──┼── Video ──▶│   └─ Gemini 2.5 Flash         │
└──────────────┘            └──────────────▲───────────────┘
        │ spricht                          │
        ▼                                  │ POST /tavus/llm
┌──────────────┐    STT + TTS              │ (OpenAI-kompatibles SSE)
│  Tavus CVI   │ ──────────────────────────┘
│  (Cloud)     │   via ngrok-Tunnel
└──────────────┘
```

---

## 2. Komponenten

| Datei | Verantwortung |
|---|---|
| `main.py` | FastAPI-Backend: RAG, Gemini-Calls, alle Endpoints, Session-Verwaltung |
| `static/index.html` | Komplettes Frontend (HTML + CSS + Vanilla-JS): Chat-Panel, Avatar-Einbindung, SSE-Konsum |
| `fill_db.py` | Befüllt ChromaDB einmalig aus `data/faq.json` + PDF-Dokumenten |
| `start.ps1` / `start.sh` | Einheitlicher Start: .env-Validierung → DB-Befüllung (falls nötig) → uvicorn |
| `tests/` | 56 pytest-Tests; schwere Abhängigkeiten (ChromaDB, Gemini, Torch) sind in `conftest.py` gemockt |

---

## 3. Die zwei Antwort-Pfade im Detail

### 3.1 Getippter Pfad: `POST /chat`

Ablauf pro Anfrage (`main.py`, Endpoint `chat`):

1. **Session-Pflege:** `touch_session()` merkt den Zugriffszeitpunkt und räumt
   Sessions auf, die länger als 30 Minuten (`SESSION_TTL_SECONDS`) inaktiv
   waren — verhindert unbegrenztes Speicherwachstum.
2. **RAG-Abfrage:** `build_rag_context()` sucht die 3 ähnlichsten Dokumente in
   ChromaDB. Läuft über `asyncio.to_thread`, damit das synchrone
   Embedding-Modell den Event-Loop nicht blockiert.
3. **Prompt-Bau:** `KIRA_PROMPT` + Satzanfang-Anweisung + Kontext-Anweisung +
   gefundene Dokumente + die letzten 4 Gesprächszüge + Frage.
4. **Streaming:** Ein einziger Gemini-Call über
   `client.aio.models.generate_content_stream`. Jeder Text-Chunk wird sofort
   als Server-Sent Event an den Browser geschickt:
   ```
   data: {"type": "chunk", "text": "Die Frist "}
   data: {"type": "chunk", "text": "ist der fünfzehnte Juli."}
   data: {"type": "done", "voice_text": "...", "source": "Wissensbasis", "latency_ms": 604, "session_id": "..."}
   ```
5. **Abschluss:** `voice_text` im `done`-Event ist der komplette Text —
   identisch mit dem, was der Browser bereits angezeigt hat. Das Frontend
   reicht ihn an den Avatar weiter (siehe 3.3).
6. **Fehlerfall:** Bricht der Gemini-Stream ab, kommt ein
   `{"type": "error"}`-Event; es wird kein `done` gesendet und nichts in den
   Verlauf geschrieben.

### 3.2 Gesprochener Pfad: `POST /tavus/llm`

Tavus betreibt die komplette Sprachstrecke (Spracherkennung, Text-to-Speech,
Video-Rendering) und ruft unser Backend als **Custom LLM** auf — die Schnittstelle
ist OpenAI-Chat-Completions-kompatibel. Die URL dazu (ngrok-Tunnel + `/tavus/llm`)
ist im Tavus-Dashboard in der Persona hinterlegt.

1. Tavus schickt den bisherigen Gesprächsverlauf als `messages`-Liste.
2. Die letzte Nutzer-Nachricht wird extrahiert, die vorherigen Züge (max. 6)
   werden als Gesprächsverlauf in den Prompt übernommen — der Avatar kann sich
   also auf Vorheriges beziehen ("Und wo reiche ich das ein?").
3. Gleiche RAG-Abfrage, gleiches `KIRA_PROMPT` wie im Chat.
4. Die Gemini-Chunks werden **durchgereicht, während sie entstehen** —
   Tavus beginnt zu sprechen, sobald der erste Satz da ist. Das ist der größte
   Latenzgewinn des Projekts.
5. **Retry-Logik:** Bis zu 3 Versuche, aber nur solange noch kein Chunk
   gesendet wurde (`gesendet`-Flag). Ein Retry mitten im Stream würde Text
   doppelt sprechen lassen. Schlagen alle Versuche fehl, kommt
   "Service momentan nicht verfügbar." als Fallback.

### 3.3 Synchronisation Chat ↔ Avatar (getippter Pfad)

Wenn der Nutzer **tippt**, läuft die Antwort über `/chat` — der Avatar weiß
davon nichts. Das Frontend schickt deshalb nach dem `done`-Event den Text als
`conversation.echo`-App-Message an Tavus (`speakAnswer()` in index.html):
der Avatar spricht ihn wortgleich nach.

**Dedup-Mechanismus:** Wenn der Avatar spricht, meldet Tavus ein
`conversation.utterance`-Event zurück — der gesprochene Text würde also ein
zweites Mal im Chat landen. Das Set `pendingEchoReplies` merkt sich jeden per
Echo geschickten Text; kommt das Utterance-Event mit genau diesem Text, wird
es verworfen. Beim Verbindungsabbau wird das Set geleert.

---

## 4. Prompt-Methodik

Der Prompt besteht aus zwei Bausteinen in `main.py`:

- **`KIRA_PERSONA`** — wer KIRA ist: freundliche, kompetente Studienberaterin,
  duzt, antwortet wie eine erfahrene Kommilitonin. Enthält auch
  Sicherheitsregeln (Rollenwechsel-Versuche ignorieren, Themenfremdes höflich
  ablehnen).
- **`KIRA_PROMPT`** = Persona + Antwortregeln. Da jede Antwort **vorgelesen**
  wird, gelten Sprechregeln: 2–3 Sätze, Zahlen ausgeschrieben
  ("fünfzehnter Januar" statt "15.01."), keine Abkürzungen, Klammern oder
  Listen. Für Menschlichkeit: warm, geht mit einem halben Satz auf die
  Situation ein, variiert Satzbau von Antwort zu Antwort.

**Satzanfang-Variation:** `remember_opening()` speichert pro Session das erste
Wort der letzten Antwort; `opening_instruction()` ergänzt den nächsten Prompt
um "Beginne deine Antwort nicht mit dem Wort X". So klingen aufeinanderfolgende
Antworten nicht mechanisch gleich.

**Kontext-Anweisung (RAG-Vertrauen):** siehe Abschnitt 5 — je nach
Treffer-Qualität bekommt das Modell eine andere Anweisung.

---

## 5. RAG-Methodik (Retrieval-Augmented Generation)

**Befüllung (`fill_db.py`):**
- FAQ-Einträge aus `data/faq.json` werden als "Frage: … / Antwort: …"-Texte
  gespeichert.
- PDFs (z.B. Modulhandbuch) werden seitenweise extrahiert und in Chunks von
  400 Zeichen mit 50 Zeichen Überlappung zerlegt (Überlappung verhindert, dass
  Information an Chunk-Grenzen verloren geht).
- Embedding-Modell: `paraphrase-multilingual-MiniLM-L12-v2`
  (mehrsprachig, gut für Deutsch, klein genug für CPU).

**Abfrage (`build_rag_context()` in `main.py`):**
- Die Nutzerfrage wird embedded und gegen die Collection verglichen;
  die 3 ähnlichsten Dokumente bilden den Kontext (je auf 400 Zeichen gekürzt).
- **Distanz-Schwelle 0.45:** Ist das beste Dokument näher als 0.45, gilt die
  Wissensbasis als zuständig → Anweisung "antworte ausschließlich auf Basis
  des Kontexts". Ist die Distanz größer, fällt das System auf allgemeines
  Hochschulwissen zurück; nur bei verbindlichen Fristen/Regelungen empfiehlt
  KIRA beiläufig eine Bestätigung beim Prüfungsamt (bewusst **nicht** als
  Pflicht-Anhang an jede Antwort).
- Das `done`-Event meldet die Quelle ("Wissensbasis" oder "LLM") ans Frontend,
  das sie unter der Antwort anzeigt.

**Warmup:** Beim Serverstart (Lifespan-Handler) läuft eine Dummy-Query, damit
die erste echte Anfrage nicht den Kaltstart der Embedding-Pipeline bezahlt.

---

## 6. Latenz-Optimierungen

| Maßnahme | Wirkung |
|---|---|
| Echtes Token-Streaming (beide Pfade) | Erster sichtbarer/hörbarer Text nach ~0.5 s statt nach der kompletten Generierung |
| `thinking_budget=0` (`gemini_config()`) | Gemini 2.5 Flash "denkt" sonst intern; das zählte gegen `max_output_tokens` (abgeschnittene Antworten!) und kostete ~2.5 s pro Antwort |
| `max_output_tokens` 300/400 | Es wird nicht mehr generiert als gebraucht |
| Async-API (`client.aio`) statt sync | Die früheren synchronen Calls blockierten den ganzen Server |
| `asyncio.to_thread` um die ChromaDB-Query | Embedding-Berechnung blockiert den Event-Loop nicht mehr |
| ChromaDB-Warmup beim Start | Erste Anfrage ist nicht kalt |
| SSE-Header `Cache-Control: no-cache`, `X-Accel-Buffering: no` | Verhindert, dass Proxies (ngrok/nginx) den Stream puffern und das Streaming damit aushebeln |

Gemessene `/chat`-Latenz (lokal, Wissensbasis-Treffer): **~600 ms** bis zur
fertigen Antwort, erster Chunk deutlich früher.

---

## 7. Frontend-Verhalten (static/index.html)

- **SSE-Konsum:** `sendMessage()` liest den Response-Body über
  `ReadableStream.getReader()`, puffert bis zur Event-Grenze `\n\n`, parst
  jede `data:`-Zeile als JSON und rendert `chunk`-Events fortlaufend in die
  Bot-Bubble (`addStreamingMessage()`).
- **Begrüßung:** 3 Sekunden nachdem das Avatar-Video steht (`track-started`),
  schickt das Frontend die Begrüßung als Chat-Nachricht + Echo an den Avatar.
  Die Tavus-eigene Sofort-Begrüßung ist serverseitig unterdrückt
  (`custom_greeting: ""`), damit der Avatar nicht spricht, bevor er sichtbar
  ist. Ohne Avatar zeigt der Empty-State dieselbe Begrüßung statisch.
- **Idle-Follow-up:** Nach jeder Bot-Antwort startet ein 30-Sekunden-Timer
  (`startIdleTimer()`). Läuft er ab, fragt KIRA einmalig "Kann ich dir noch
  bei etwas helfen?" (Chat + Sprache). Jede Nutzeraktivität (Tippen, Senden,
  Sprechen) setzt den Timer zurück; nach dem Follow-up selbst startet kein
  neuer Timer (`idleFired`-Flag).
- **Doppel-Send-Schutz:** Enter ist gesperrt, solange ein Stream läuft
  (Send-Button disabled).
- **Provider-Switching:** `AVATAR_PROVIDER` in der .env steuert, ob Tavus,
  HeyGen/LiveAvatar oder Anam geladen wird; `speakAnswer()` routet die Sprache
  entsprechend (Tavus: Echo-App-Message, sonst `avatarSpeak()`).

---

## 8. Test-Methodik

- **TDD:** Jede Funktionalität wurde test-first entwickelt (Test schreiben →
  fehlschlagen sehen → implementieren → grün).
- **Mock-Strategie:** `tests/conftest.py` ersetzt ChromaDB, google-genai,
  sentence-transformers und torch durch MagicMocks, **bevor** `main` importiert
  wird — die Tests laufen dadurch in <0.5 s ohne Modelle oder API-Keys.
- **Async-Streaming-Mocks:** Gemini-Streams werden als Async-Generatoren
  gemockt (`make_async_stream`), Fehler mitten im Stream über
  `make_failing_stream`. Damit sind auch die heiklen Pfade getestet:
  Retry nur vor dem ersten Chunk, Fallback-Text nach 3 Fehlversuchen,
  kein `done`-Event und kein Verlaufs-Eintrag bei Stream-Abbruch.
- **Wichtige Invarianten, die Tests absichern:**
  - `voice_text` == angezeigter Text (Identität von Text und Sprache)
  - genau **ein** Gemini-Call pro Chat-Anfrage, genau **eine** ChromaDB-Query
  - Satzanfang-Variation landet im Folge-Prompt
  - Session-TTL räumt `sessions` + `voice_openings` auf
  - SSE-Anti-Buffering-Header sind gesetzt

Ausführen:
```powershell
$env:PYTHONIOENCODING="utf-8"; python -m pytest tests/ -v
```

---

## 9. Betrieb

```powershell
.\start.ps1     # Windows       (Linux/Mac: ./start.sh)
```
Das Skript validiert die `.env` (GOOGLE_API_KEY immer, TAVUS_API_KEY bei
`AVATAR_PROVIDER=tavus`), befüllt `chroma_db/` beim ersten Start über
`fill_db.py` und startet uvicorn auf Port 8000 mit `--reload`.

Für den **gesprochenen** Tavus-Pfad muss der Server öffentlich erreichbar sein:
`ngrok http 8000` starten und die ngrok-URL + `/tavus/llm` im Tavus-Dashboard
in der Persona als Custom-LLM-URL eintragen.

---

## 10. Bekannte Grenzen

- **Ein Prozess:** Session-State (`sessions`, `voice_openings`) liegt im
  Speicher — `uvicorn --workers N` oder mehrere Instanzen bräuchten einen
  externen Store (z.B. Redis).
- **CORS ist offen** (`allow_origins=["*"]`) — für Produktion einschränken.
- **Gesprochener Pfad ohne Satzanfang-Variation:** `/tavus/llm` hat keine
  Session-ID, daher greift die Variation dort nicht.
- **Keine Authentifizierung / kein Rate-Limiting** — für den Demo-Betrieb
  ausgelegt.
- Der frühere Google-API-Key liegt in der Git-Historie (Commits vor dieser
  Umbauphase) und sollte rotiert werden.
