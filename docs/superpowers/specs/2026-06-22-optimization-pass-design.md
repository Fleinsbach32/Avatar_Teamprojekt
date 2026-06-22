# Design: Optimierungs- und Weiterentwicklungs-Pass (22.06.2026)

**Status:** Freigegeben (Design), bereit für Implementierungsplan
**Branch:** `feature/tavus`

## Ziel

Ein zusammenhängender Polish-Durchlauf über KIRA in sieben geordneten Workstreams:
Latenz senken, Studiengang-Filter zuverlässig machen, Prompts empathischer und
konsistenter gestalten, UI (Dropdown + Sprachumschalter) verbessern, Code
reviewen/aufräumen, Doku aktualisieren.

Reihenfolge: **A → B → C → D → E → F → G → H** (Latenz/Filter zuerst, da akute
Probleme; H = abschließendes ganzheitliches Review nachdem alles steht).

## Getroffene Entscheidungen

| Thema | Entscheidung |
|-------|--------------|
| Latenz-Strategie | Reranker **behalten**, gezielt optimieren (nicht entfernen) |
| Empathie-Grad | **Moderat** wärmer; Voice & Text strukturell angleichen |
| Sprach-UI | **Zwei Flaggen-Buttons** nebeneinander (DE / EN), aktive markiert |
| DB-Pfad | Auf bestehendem **`chroma_db/`** (Root) standardisieren |
| Umfang | Eine Spec, ein Plan, geordnete Workstreams |

## Wichtigste Erkenntnis

"Studiengang-Filter wirkt nicht auf Antworten" (Text) und "Voice ignoriert
Auswahl" haben **dieselbe Wurzel**: Die RAG-Retrieval-Schicht priorisiert die
Handbuch-Chunks des gewählten Studiengangs zu schwach gegenüber den ~55.000
generischen Web-Chunks (`program == "all"`). Das Voice-Plumbing
(`active_voice_prefs`, `/tavus/settings`, Session-Start) ist korrekt — beide
Pfade teilen sich `build_rag_context`, ein Fix wirkt auf beide.

---

## Workstream A — Latenz-Optimierung (RAG)

**Problem:** Der heute integrierte `CrossEncoder`-Reranker
(`cross-encoder/mmarco-mMiniLMv2-L12-H384-v1`) läuft auf CPU und bewertet pro
Standard-Query 16–21 (Query, Doc)-Paare. Erste Anfrage zahlt zusätzlich den
Modell-Init. Chunk-Zahlen wurden heute erhöht (`prog_n` 4/8 → 10/15).

**Änderungen** (`app/rag.py`, `app/main.py`):
- **Reranker-Warmup** im Lifespan von `app/main.py` (analog zum ChromaDB-Warmup):
  ein Dummy-`reranker.predict([("warmup", "warmup")])`, damit die erste echte
  Anfrage den Init nicht zahlt.
- **Kandidatenpool reduzieren:** `prog_n` 10 → 8 (Pflicht 15 → 12), `all` 6 → 4.
  Reranker bewertet damit ~12 statt 16–21 Paare.
- **Spezialpfade unverändert:** Modul-ID, Name→Nummer, "Was ist Modul X" nutzen
  feste Distanz 0.1 und kein Reranking — bleibt so.

**Messung** (`scripts/bench_rag.py`, neu):
- Ruft `build_rag_context` für eine feste Liste repräsentativer Queries auf
  (Modul-ID, Name→Nummer, "Was ist X", allgemeine Frage, mit/ohne Studiengang).
- Gibt pro Query die Latenz aus (Mittel über N Läufe), getrennt nach
  Reranker an/aus (über ein Flag, das `rerank()` zum reinen Slicing degradiert).
- Kein Server nötig; nutzt `build_rag_context` direkt.

**Akzeptanz:** Standard-Query-Latenz im Bench messbar gesenkt; erste Anfrage
nach Start nicht mehr deutlich langsamer als folgende.

---

## Workstream B — Studiengang-Filter zuverlässig (Text + Voice)

**Problem:** Bei gewähltem Studiengang verdrängt der Reranker die
Handbuch-Chunks gegen generische Web-Chunks; Antworten unterscheiden sich nicht
zwischen Studiengängen.

**Änderungen** (`app/rag.py`, Standardsuche-Zweig mit Studiengang):
- **Handbuch-Priorität garantieren:** Wenn ein Studiengang gewählt ist, im
  finalen Kontext mindestens die Top-3 Handbuch-Chunks (`program == studiengang`)
  fix einplanen; die restlichen bis `top_k` aus dem reranked kombinierten Pool
  auffüllen. Dadurch kann der Reranker die studiengangsspezifischen Chunks nicht
  vollständig verdrängen.
- **`_module_name_from_what_is_question`-Regex** (heute gefixt: "Modul" optional,
  Fallback auf Semantiksuche ohne Studiengang) bleibt erhalten.

**Voice:** Keine Code-Änderung — Plumbing korrekt, profitiert automatisch.

**Akzeptanz:** Gleiche Frage in zwei Studiengängen liefert nachweislich
unterschiedliche, handbuchgestützte Antworten (Test: "Was ist Introduction to
Digital Economics?" in DigiEco vs. WING).

---

## Workstream C — Dropdown-Redesign

**Problem:** Master "WING"/"WINFO" tragen identische Labels wie die
Bachelor-Optionen → visuell mehrdeutig.

**Änderungen** (`static/index.html`):
- Optionen-Labels eindeutig machen: z.B. "WING (B.Sc.)" / "WING (M.Sc.)",
  analog WINFO, DigiEco. Optgroups "Bachelor"/"Master" bleiben.
- Keine funktionale Änderung am `onStudiengangChange`-Handler nötig (Fix kommt
  aus Workstream B).

**Akzeptanz:** Jede Option ist eindeutig einem Abschluss zuordenbar.

---

## Workstream D — Voice/Text-Prompt: Empathie & Konsistenz

**Problem:** Voice- und Text-Extension unterscheiden sich strukturell; Ton soll
moderat wärmer/nahbarer werden, ohne Länge oder Präzision zu opfern.

**Änderungen** (`app/prompts.py`):
- **Strukturelle Angleichung:** `KIRA_TEXT_EXT` und `KIRA_VOICE_EXT` erhalten
  dieselben Abschnitte (Sprache, Ton & Stil, Antwortregeln, Längenlimits) in
  paralleler Reihenfolge, DE und EN identisch aufgebaut.
- **Moderat empathischer Ton:** Gefühle kurz aufgreifen, ermutigend formulieren,
  nahbar bleiben — aber weiter direkt zum Punkt und in den bestehenden
  Längengrenzen (max. 2/3/4 Sätze Text; 2–4 Sätze Voice).
- Bestehende Verbote (keine Listen, keine Begrüßungsfloskeln, Abkürzungen
  ausschreiben, Modulnummern nur auf Nachfrage) bleiben.

**Akzeptanz:** Beide Modi haben dieselbe Abschnittsstruktur; Empathie-Formulierung
in beiden vorhanden; `test_kira.py`-Empathie-Fälle wirken wärmer, bleiben kurz.

---

## Workstream E — Sprach-UI: zwei Flaggen-Buttons

**Problem:** Aktueller Umschalter ist ein einzelner Button, der die *Zielsprache*
zeigt — verwirrend, welche Sprache gerade aktiv ist.

**Änderungen** (`static/index.html`):
- `#langToggle`-Button ersetzen durch zwei nebeneinanderliegende Flaggen-Buttons
  (DE, EN) in einem Container. Aktive Sprache visuell hervorgehoben (z.B. Rahmen,
  volle Deckkraft); inaktive gedimmt.
- Klick auf die inaktive Flagge wechselt die Sprache; Klick auf die aktive ist
  No-Op. Nutzt bestehende `applyLang()` und `pushVoicePrefs()`.
- `setLangButton()` wird zu `setLangButtons()` (markiert aktive Flagge), bestehende
  `FLAG_SVG` wiederverwenden.

**Akzeptanz:** Beide Flaggen sichtbar; aktive klar erkennbar; Umschalten
funktioniert für UI-Texte und (bei laufendem Avatar) Voice-Prefs.

---

## Workstream F — Code-Review & Hygiene

**Unabhängiges Review** von `app/rag.py`, `app/prompts.py`, `app/routes/chat.py`,
`app/routes/tavus.py` auf Effizienz, Latenz-Hotspots, Edge Cases, Bugs.

**Konkret umzusetzen:**
- **DB-Pfad vereinheitlichen:** `scripts/fill_db.py` schreibt aktuell nach
  `data/chroma_db/`, der Rest liest `chroma_db/` (Root). `fill_db.py` auf
  `chroma_db/` umstellen (`CHROMA_PATH`). ZIP-Backup bleibt unter
  `data/chroma_db.zip`.
- **`chat.py` Retry:** analog `tavus.py` einen einfachen Retry (z.B. 2 Versuche)
  bei Gemini-Stream-Fehlern ergänzen, bevor abgebrochen wird.
- **Message-Längenlimit:** `ChatRequest.message` und `TavusMessageRequest.message`
  via `Field(max_length=...)` begrenzen (z.B. 2000 Zeichen).
- **`voice_openings`-Cleanup:** in `touch_session()` abgelaufene Einträge auch aus
  `voice_openings` entfernen (aktuell nur `sessions`/`session_last_seen`).
- **Logging-Level:** `tavus.py` Tavus-API-Statuslog von `warning` auf `info`
  (loggt aktuell auch Erfolg als Warnung).

**TODO/FIXME-Scan:** Im Code keine gefunden (verifiziert). Offene Punkte aus dem
Chatverlauf in diese Spec aufgenommen.

**Bekannt, nicht in diesem Pass** (dokumentieren, nicht umsetzen):
- Webcrawl-`source`-Metadatum zeigt nur 1 unique URL / leere Domain — Datenqualität
  beim Crawl/`fill_db.py`, separater Task.
- `is_pflicht`-Metadatum für vollständige Pflichtmodul-Listen — strukturell, separater Task.

**Akzeptanz:** Alle Tests grün (`pytest tests/`); genannte Fixes umgesetzt;
DB-Pfad konsistent.

---

## Workstream G — Dokumentation

**Änderungen:**
- **`README.md`:** Reranker (Cross-Encoder, zweistufige Suche + Rerank), DB-Pfad
  `chroma_db/`, neue Skripte `scripts/check_db.py` und `scripts/bench_rag.py`,
  Sprach-UI (zwei Flaggen), Dropdown-Labels. Auth-Abschnitt entfernen (HTTP Basic
  Auth wurde im Pull entfernt).
- **Dev-Log `docs/dev-log/2026-06-22-session-2.md`:** heutige Änderungen
  (DB-ZIP/Pfad-Reparatur, `check_db.py`, RAG-Filter-Fix, Latenz-Optimierung,
  Prompts, UI, Review-Fixes).

**Akzeptanz:** README spiegelt Endzustand; Dev-Log dokumentiert die Session.

---

## Workstream H — Abschließendes ganzheitliches Code-Review & Optimierung

**Ziel:** Nachdem A–G stehen, ein unabhängiges Review über die **gesamte**
Codebasis (nicht nur die geänderten Dateien) mit Fokus auf Effizienz,
Latenz-Hotspots, Edge Cases, Bugs und Konsistenz. Findings, die klein und
risikoarm sind, werden direkt umgesetzt; größere werden dokumentiert.

**Vorgehen:**
- Durchsicht aller Module unter `app/` (`main.py`, `rag.py`, `gemini.py`,
  `session.py`, `prompts.py`, `routes/*`) und `scripts/` auf:
  - **Effizienz/Latenz:** redundante DB-Queries, unnötige Modell-Aufrufe,
    synchrone Blocker im Async-Pfad, zu große Kontextfenster (`doc[:600]` × N).
  - **Edge Cases:** leere/sehr lange Eingaben, fehlende Env-Variablen, leere
    ChromaDB, Sprach-Fallbacks, gleichzeitige Sessions (globaler
    `active_voice_prefs`).
  - **Bugs/Konsistenz:** Fehlerbehandlung in SSE-Streams, Exception-Swallowing
    (`_query_safe`), uneinheitliche Distanz-/Quelle-Logik.
- **Lauffähigkeit prüfen:** `pytest tests/` grün, `python scripts/check_db.py`
  ok, App startet ohne Fehler (Import-Check `python -c "import app.main"`).
- Kleine, sichere Optimierungen sofort anwenden; alles andere als nummerierte
  Liste im Dev-Log (Workstream G) festhalten.

**Akzeptanz:** Review-Liste erstellt; risikoarme Findings umgesetzt; alle Tests
grün; verbleibende Punkte dokumentiert.

---

## Betroffene Dateien (Überblick)

| Datei | Workstreams |
|-------|-------------|
| `app/rag.py` | A, B |
| `app/main.py` | A (Reranker-Warmup) |
| `app/prompts.py` | D |
| `app/routes/chat.py` | F (Retry, Längenlimit) |
| `app/routes/tavus.py` | F (Logging, Längenlimit) |
| `app/session.py` | F (`voice_openings`-Cleanup) |
| `scripts/fill_db.py` | F (DB-Pfad) |
| `scripts/bench_rag.py` | A (neu) |
| `static/index.html` | C, E |
| `README.md` | G |
| `docs/dev-log/2026-06-22-session-2.md` | G (neu) |
| `tests/` | F (anpassen/ergänzen) |

## Nicht im Scope

- Reranker entfernen oder austauschen.
- Zweisprachige Gleichzeitig-Anzeige der Antworten.
- Crawl-Datenqualität / `is_pflicht`-Metadatum (separate Tasks, dokumentiert).
- Wiedereinführung von Auth.
