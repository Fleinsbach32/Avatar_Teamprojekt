# KIRA — Technische Dokumentation

Detaillierte Erklärung des Codes und der Methodik hinter der KIRA-Studienberatung
(KIT) mit sprechendem Avatar.

**Stand:** 16.06.2026 · **Branch:** feature/tavus

---

## 1. Überblick

KIRA ist eine Studienberatungs-Webanwendung mit zwei Eingabewegen:

1. **Text-Chat** — der Nutzer tippt eine Frage in das Chat-Panel.
2. **Gespräch mit dem Avatar** — der Nutzer spricht; ein fotorealistischer
   Video-Avatar (Tavus) hört zu und antwortet mit Stimme und Lippenbewegung.

Beide Wege nutzen dieselbe Wissensbasis (RAG über ChromaDB) und dasselbe
Sprachmodell (Google Gemini 2.5 Flash). Der Text-Pfad nutzt einen Text-Prompt,
der Voice-Pfad einen kürzeren, sprechoptimierten Voice-Prompt — beide in Deutsch
oder Englisch (Sprachauswahl im UI). Optional lässt sich die Wissensbasis auf
einen Studiengang (Modulhandbuch) einschränken.

```
┌──────────────┐   tippt    ┌──────────────────────────────┐
│   Browser    │ ─────────▶ │  POST /chat (SSE-Stream)      │
│ (index.html) │ ◀───────── │  FastAPI-Backend (app/)       │
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

Das Backend ist in ein `app/`-Paket aufgeteilt (statt einer einzelnen
`main.py`), damit jede Datei eine klar abgegrenzte Aufgabe hat:

| Datei | Verantwortung |
|---|---|
| `app/main.py` | FastAPI-App-Wiring: Middleware, Router-Einbindung, Lifespan-Warmup, `/health`, `/` |
| `app/auth.py` | HTTP Basic Auth (`check_auth`) für Browser-Endpoints; Tavus-LLM-Endpoints ausgenommen |
| `app/routes/chat.py` | `POST /chat` — getippter Pfad (SSE-Stream, Text-Prompt) |
| `app/routes/tavus.py` | `POST /tavus/session`, `/tavus/end`, `/tavus/message`, `/tavus/settings`, `/tavus/llm` (+ Aliase) — Voice-Pfad |
| `app/routes/avatar.py` | `GET /avatar/config` — Provider-Konfiguration (derzeit nur Tavus) |
| `app/prompts.py` | `KIRA_BASE_PROMPT` + getrennte Text-/Voice-Erweiterungen (DE/EN), `build_prompt(mode, lang)` |
| `app/rag.py` | ChromaDB-Client, `build_rag_context()`, `STUDIENGANG_FILES` (Studiengang-Filter) |
| `app/gemini.py` | Gemini-Client, `gemini_config()`, SSE-Header |
| `app/session.py` | In-Memory-Sessions, TTL-Aufräumung, Satzanfang-Variation |
| `static/index.html` | Komplettes Frontend (HTML + CSS + Vanilla-JS): Chat-Panel, Avatar-Einbindung, SSE-Konsum, Sprach-/Studiengang-Auswahl |
| `scripts/fill_db.py` | Befüllt ChromaDB einmalig aus `data/faq.json` + PDFs aus `data/pdfs/` (Upsert in 5000er-Batches) |
| `crawler.py` | BFS-Web-Crawler für wiwi.kit.edu: crawlt, chunked und befüllt ChromaDB direkt; unterstützt PDF-Extraktion, robots.txt, Shibboleth-Erkennung und Modul-Bewertungen |
| `run.ps1` | Idempotenter Einzel-Start: .env-Validierung → ngrok + pip + DB-Befüllung (falls nötig) → ngrok-Tunnel → uvicorn |
| `crawl.ps1` | Einzel-Befehl für den Crawler: pip → Crawl → ChromaDB-Einbettung; Modi: Standard, `-FillDbOnly`, `-InjectRatings` |
| `tests/` | pytest-Tests; schwere Abhängigkeiten (ChromaDB, Gemini, Torch) sind in `conftest.py` gemockt |

---

## 3. Die zwei Antwort-Pfade im Detail

### 3.1 Getippter Pfad: `POST /chat`

Ablauf pro Anfrage (`app/routes/chat.py`, Endpoint `chat`):

1. **Session-Pflege:** `touch_session()` (in `app/session.py`) merkt den
   Zugriffszeitpunkt und räumt Sessions auf, die länger als 30 Minuten
   (`SESSION_TTL_SECONDS`) inaktiv waren — verhindert unbegrenztes
   Speicherwachstum.
2. **RAG-Abfrage:** `build_rag_context(frage, studiengang)` sucht die 3
   ähnlichsten Dokumente in ChromaDB, optional gefiltert auf das Modulhandbuch
   des gewählten Studiengangs. Läuft über `asyncio.to_thread`, damit das
   synchrone Embedding-Modell den Event-Loop nicht blockiert.
3. **Prompt-Bau:** `build_prompt("text", lang)` (Basis + Text-Regeln in der
   gewählten Sprache) + Satzanfang-Anweisung + Kontext-Anweisung + gefundene
   Dokumente + die letzten 4 Gesprächszüge + Frage. Die Sprache (`lang`) und der
   Studiengang kommen als Felder im Request-Body vom Frontend.
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
ist OpenAI-Chat-Completions-kompatibel. Die URL dazu (ngrok-Tunnel) ist im
Tavus-Dashboard in der Persona hinterlegt. Der Endpoint ist unter drei Aliasen
erreichbar (`/tavus/llm`, `/tavus/llm/chat/completions`, `/chat/completions`),
weil Tavus' OpenAI-Client `/chat/completions` an die Basis-URL anhängt — so
funktionieren sowohl eine Basis-URL mit `/tavus/llm` als auch die ngrok-Root.

1. Tavus schickt den bisherigen Gesprächsverlauf als `messages`-Liste.
2. Die letzte Nutzer-Nachricht wird extrahiert, die vorherigen Züge (max. 6)
   werden als Gesprächsverlauf in den Prompt übernommen — der Avatar kann sich
   also auf Vorheriges beziehen ("Und wo reiche ich das ein?").
3. Gleiche RAG-Abfrage wie im Chat, aber `build_prompt("voice", lang)` (kürzerer,
   sprechoptimierter Voice-Prompt).
4. **Sprache & Studiengang:** Tavus sendet keine UI-Felder mit. Daher merkt sich
   das Backend die zuletzt im Frontend gewählten Voice-Einstellungen
   (`active_voice_prefs`), gesetzt bei `POST /tavus/session` und aktualisiert über
   `POST /tavus/settings`. `/tavus/llm` liest Sprache und Studiengang aus diesem
   Zustand. Er ist global — ausgelegt für den lokalen Einzel-Session-Betrieb.
5. Die Gemini-Chunks werden **durchgereicht, während sie entstehen** —
   Tavus beginnt zu sprechen, sobald der erste Satz da ist. Das ist der größte
   Latenzgewinn des Projekts.
6. **Retry-Logik:** Bis zu 3 Versuche, aber nur solange noch kein Chunk
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

Der Prompt wird in `app/prompts.py` aus einer Basis plus einer modus- und
sprachabhängigen Erweiterung zusammengesetzt (`build_prompt(mode, lang)`):

- **`KIRA_BASE_PROMPT`** — sprach- und modusunabhängiger Kern: wer KIRA ist
  (freundliche, kompetente Studienberaterin), Aufgabe, Sicherheitsregeln
  (Rollenwechsel-Versuche ignorieren), das Nachfrage-Verhalten und ein expliziter
  „Wissensgrenzen"-Block: „nicht zuständig" ist nur bei echten Off-Topic-Fragen
  erlaubt; bei Wissenslücken zu Studium/KIT gibt KIRA das ehrlich zu und verweist
  auf campus.kit.edu.
- **`KIRA_TEXT_EXT[lang]`** — Text-Regeln (DE/EN): fließende Sätze, keine Listen,
  Länge an die Frage angepasst (1–2 Sätze bei einfachen, 3–5 bei komplexen
  Fragen), duzt, lehnt Themenfremdes höflich ab. Verboten: Floskeln wie „Ich
  verstehe, dass…", „Das ist eine gute Frage", Markdown-Formatierung.
- **`KIRA_VOICE_EXT[lang]`** — Voice-Regeln (DE/EN): bewusst kürzer als der
  Text-Prompt, maximal 2–3 gut vorlesbare Sätze, keine Klammern/Abkürzungen,
  variierte Satzanfänge, kein Markdown.
- **Modul-ID-Regel:** Wird eine Modul-ID (z.B. `M-WIWI-101267`) genannt, sucht
  KIRA sie zuerst in der Wissensbasis und antwortet mit dem Klarnamen — ohne die
  ID zu nennen. Ist sie nicht gefunden, fragt KIRA nach dem Modulnamen.

`/chat` ruft `build_prompt("text", lang)`, `/tavus/llm` ruft
`build_prompt("voice", lang)`. So können sich gesprochene und getippte Antworten
in Stil und Länge unterscheiden, obwohl sie dieselbe Wissensbasis nutzen.

**Satzanfang-Variation:** `remember_opening()` speichert pro Session das erste
Wort der letzten Antwort; `opening_instruction()` ergänzt den nächsten Prompt
um "Beginne deine Antwort nicht mit dem Wort X". So klingen aufeinanderfolgende
Antworten nicht mechanisch gleich.

**Kontext-Anweisung (RAG-Vertrauen):** siehe Abschnitt 5 — je nach
Treffer-Qualität bekommt das Modell eine andere Anweisung.

---

## 5. RAG-Methodik (Retrieval-Augmented Generation)

**Befüllung (`scripts/fill_db.py`):**
- FAQ-Einträge aus `data/faq.json` werden als "Frage: … / Antwort: …"-Texte
  gespeichert.
- PDFs aus `data/pdfs/` (z.B. Modulhandbücher) werden seitenweise extrahiert und in Chunks von
  400 Zeichen mit 50 Zeichen Überlappung zerlegt (Überlappung verhindert, dass
  Information an Chunk-Grenzen verloren geht).
- Embedding-Modell: `paraphrase-multilingual-MiniLM-L12-v2`
  (mehrsprachig, gut für Deutsch, klein genug für CPU).

**Abfrage (`build_rag_context()` in `app/rag.py`):**
- **Modul-ID-Direktsuche:** Enthält die Frage eine ID der Form `M-[A-Z]+-\d+`,
  läuft zuerst eine `where_document={"$contains": module_id}`-Query (Volltext-
  Match ohne Embedding). Liefert sie Ergebnisse, werden diese direkt mit einer
  eigenen Anweisung ans Modell übergeben.
- Die Nutzerfrage wird embedded und gegen die Collection verglichen;
  die 3 ähnlichsten Dokumente bilden den Kontext (je auf 600 Zeichen gekürzt).
- **Studiengang-Filter:** Wird ein Studiengang gewählt, schränkt ein
  `where`-Filter die Suche über `STUDIENGANG_FILES` auf das zugehörige
  Modulhandbuch-PDF ein (Mapping Studiengang-Schlüssel → Dateiname). Ohne
  Auswahl wird die gesamte Wissensbasis durchsucht.
- **Distanz-Schwelle 0.45:** Ist das beste Dokument näher als 0.45, gilt die
  Wissensbasis als zuständig → Anweisung „Nutze den Kontext wenn er zur Frage
  passt; sonst ignoriere ihn und nutze allgemeines Hochschulwissen." (Vorher:
  „ausschließlich auf Basis des Kontexts" — führte dazu, dass KIRA bei falsch
  retrievten Chunks irrelevante Inhalte wiedergab.) Ist die Distanz größer,
  fällt das System auf allgemeines Hochschulwissen zurück.
- **`_query_safe()`-Fallback:** Wirft ChromaDB bei `n_results=3` einen Fehler
  (z.B. wenn der Filter nur 1 Dokument trifft), wird automatisch mit
  `n_results=1` wiederholt; schlägt auch das fehl, kommt ein leeres Ergebnis
  zurück statt eines Server-Fehlers.
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
- **Sprach-Umschalter:** Der Button oben rechts (mit Flagge) schaltet zwischen
  Deutsch und Englisch. `applyLang()` aktualisiert alle UI-Texte aus dem
  `I18N`-Dictionary und setzt die Erkennungssprache der Spracheingabe; `lang`
  wird bei jeder `/chat`-Anfrage mitgeschickt.
- **Studiengang-Dropdown:** Ebenfalls oben rechts, gruppiert in Bachelor/Master.
  Die Auswahl (`currentStudiengang`) gilt für die Session und wird bei jeder
  `/chat`-Anfrage mitgeschickt.
- **Voice-Pfad-Synchronisation:** Da Tavus `/tavus/llm` ohne UI-Kontext aufruft,
  meldet `pushVoicePrefs()` Sprache und Studiengang an `POST /tavus/settings` —
  beim Avatar-Start und bei jeder Änderung während eines laufenden Gesprächs.
- **Avatar-Provider:** Es wird ausschließlich Tavus geladen; `speakAnswer()`
  schickt den getippten Antworttext als Echo-App-Message an den Avatar.

---

## 8. Test-Methodik

- **TDD:** Jede Funktionalität wurde test-first entwickelt (Test schreiben →
  fehlschlagen sehen → implementieren → grün).
- **Mock-Strategie:** `tests/conftest.py` ersetzt ChromaDB, google-genai,
  sentence-transformers und torch durch MagicMocks, **bevor** das `app`-Paket
  importiert wird — die Tests laufen dadurch in <0.5 s ohne Modelle oder
  API-Keys.
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

### Server starten

```powershell
.\run.ps1
```
`run.ps1` ist idempotent und übernimmt alles in einem Befehl: `.env`-Validierung
(GOOGLE_API_KEY), Installation von ngrok und pip-Paketen beim ersten Aufruf,
Befüllung von `chroma_db/` über `scripts/fill_db.py` (falls nötig), Start des
ngrok-Tunnels (gibt die öffentliche URL aus) und uvicorn auf Port 8000 mit
`--reload` (Modulpfad `app.main:app`). Folgeaufrufe überspringen erledigte
Schritte (pip via `.pip-stamp`, ngrok via Tunnel-Probe auf Port 4040).

### HTTP Basic Auth

Der Server verlangt HTTP-Basic-Authentifizierung auf allen Routen außer
`/health`. Credentials werden über `.env` gesetzt:

```
APP_USERNAME=admin
APP_PASSWORD=geheim
```

Der Browser zeigt automatisch ein Login-Fenster. Für den **gesprochenen**
Tavus-Pfad müssen die Credentials direkt in der Custom-LLM-URL kodiert werden,
da Tavus-Server keine Browser-Auth-Dialoge nutzen können:

```
https://user:passwort@meine-ngrok-url.ngrok.app/tavus/llm
```

### Wissensbasis neu crawlen

```powershell
.\crawl.ps1                   # Standard: pip installieren + crawlen + ChromaDB befuellen
.\crawl.ps1 -MaxPages 200     # Schneller Testlauf
.\crawl.ps1 -FillDbOnly       # Nur vorhandene JSON-Dateien in ChromaDB einbetten
.\crawl.ps1 -InjectRatings    # Nur Modulbewertungen aus module_ratings.json einpflegen
```

`crawl.ps1` installiert fehlende pip-Pakete (einmalig via `.pip-stamp`), startet
den BFS-Crawler für wiwi.kit.edu und befüllt anschließend ChromaDB. Gecrawlte
JSON-Dateien landen in `crawled_data/` (in `.gitignore`).

### Web-Authentifizierung

Die Browser-Endpoints (`/`, `/chat`, `/avatar/config`,
`/tavus/session|end|message|settings`) sind per HTTP Basic Auth geschützt
(`app/auth.py`, Zugangsdaten aus `APP_USERNAME`/`APP_PASSWORD` in der `.env`,
Default `admin`/`geheim`). Der Browser fragt die Zugangsdaten einmal ab und sendet
sie danach automatisch mit. **Ausgenommen** sind die von Tavus serverseitig
aufgerufenen LLM-Endpoints (`/tavus/llm`, `/tavus/llm/chat/completions`,
`/chat/completions`) und `/health` — Tavus kann keine Credentials senden, eine
Auth darauf würde den gesprochenen Avatar-Pfad mit 401 abbrechen.

---

## 10. Bekannte Grenzen

- **Ein Prozess / eine Voice-Session:** Session-State (`sessions`,
  `voice_openings`) und die Voice-Einstellungen (`active_voice_prefs`) liegen im
  Speicher und sind global. `uvicorn --workers N`, mehrere Instanzen oder mehrere
  gleichzeitige Avatar-Gespräche bräuchten einen externen Store bzw. eine
  Schlüsselung pro `conversation_id` (z.B. Redis).
- **CORS ist offen** (`allow_origins=["*"]`) — für Produktion einschränken.
- **Gesprochener Pfad ohne Satzanfang-Variation:** `/tavus/llm` hat keine
  Session-ID, daher greift die Variation dort nicht.
- **Auth nur als HTTP Basic, kein Rate-Limiting** — einfacher Passwortschutz für
  die UI (siehe Abschnitt 9); für Produktion ggf. stärkeres Auth-Verfahren und
  Rate-Limiting ergänzen.
- Der frühere Google-API-Key liegt in der Git-Historie (Commits vor dieser
  Umbauphase) und sollte rotiert werden.
