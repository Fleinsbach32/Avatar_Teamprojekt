# Code-Review-Audit — KIRA

**Datum:** 2026-06-24
**Umfang:** app/ (Runtime), scripts/, tests/, docs/ & Config
**Dimensionen:** Korrektheit, Dead Code/Cleanup, Performance · **Kein** Struktur-Refactoring

---

## Zusammenfassung

| Schwere | Anzahl |
|---|---|
| 🔴 Kritisch | 0 |
| 🟡 Wichtig | 4 |
| ⚪ Klein | 8 |

Die Codebasis ist insgesamt sauber und gut getestet (121 Tests, durchweg echte
Verhaltensprüfung statt reiner Mock-Assertions). Keine Crash- oder Datenverlust-Bugs.
Die wichtigsten Punkte: ein Concurrency-Problem im Voice-Pfad (globaler State), eine
Sicherheits-/Doku-Diskrepanz (Auth wurde entfernt, `.env.example` behauptet weiter Schutz),
eine vermeidbare Embedding-Berechnung im Modul-ID-Pfad und ein veraltetes Debug-Skript.
Vieles im „Klein"-Bereich ist stale Konfiguration/Doku nach dem Auth-Rückbau.

---

## 🟡 Wichtig

### [C1] Globaler Voice-State kollidiert bei gleichzeitigen Nutzern  `[Bug]`
- **Datei:** [app/routes/tavus.py:27](app/routes/tavus.py#L27), [app/routes/tavus.py:216-217](app/routes/tavus.py#L216-L217)
- **Problem:** `active_voice_prefs` ist ein modulglobales Dict. `/tavus/llm` wird von Tavus serverseitig ohne UI-Kontext aufgerufen und liest Sprache/Studiengang daraus. Bei zwei gleichzeitigen Voice-Sessions überschreibt die letzte `/tavus/settings`-Anfrage die Einstellung der anderen → Antworten im falschen Studiengang/falscher Sprache.
- **Warum:** Auf der öffentlichen Railway-Instanz ist „nur ein Avatar gleichzeitig" nicht mehr garantiert. Der Kommentar dokumentiert die Annahme, aber die Realität des Deployments widerspricht ihr.
- **Fix:** State pro `conversation_id` halten (Dict `conversation_id → prefs`), `/tavus/settings` und `/tavus/session` schreiben unter der ID, `/tavus/llm` liest darüber. Die `conversation_id` ist in der Tavus-LLM-Anfrage allerdings nicht garantiert vorhanden — falls nicht, bleibt der globale Fallback. Alternativ klar als bekannte Single-Session-Limitierung im README akzeptieren.
- **Aufwand:** M · **Risiko:** mittel

### [S1] Keine Authentifizierung trotz gegenteiliger Doku  `[Bug/Security]`
- **Datei:** [.env.example:4-8](.env.example#L4-L8), [app/main.py:46-51](app/main.py#L46-L51)
- **Problem:** HTTP Basic Auth wurde bewusst entfernt (Commit `1dfccde6`, weil sie den Tavus-Voice-Pfad blockierte). Aber `.env.example` dokumentiert `APP_USERNAME`/`APP_PASSWORD` weiterhin als „Schuetzt die UI (/, /chat, …)". Im Code (`app/`) existiert kein einziger Auth-Check. CORS steht zudem auf `allow_origins=["*"]`.
- **Warum:** Wer nach der Doku deployt, glaubt die Instanz sei geschützt — ist sie nicht. `/chat` ist offen → beliebige Dritte können die Gemini-API-Quota/Kosten verbrauchen.
- **Fix:** Entscheidung nötig (siehe Frage unten):
  (a) Doku ehrlich machen — Auth-Block aus `.env.example` entfernen, Offenheit dokumentieren; oder
  (b) leichten Schutz wieder einführen, der den Tavus-Pfad ausnimmt (z.B. Token-Header auf `/chat` + UI, `/tavus/llm` frei) plus simples Rate-Limit.
- **Aufwand:** S (nur Doku) / M (echter Schutz) · **Risiko:** niedrig (Doku) / mittel (Auth kann Voice erneut brechen)

### [P1] Modul-ID-Pfad berechnet unnötig ein Embedding  `[Perf]`
- **Datei:** [app/rag.py:295](app/rag.py#L295)
- **Problem:** Bei erkannter Modul-ID läuft `_query_safe(_combine(where, {"module_id": …}), 3, query_texts=[query])`. `query_texts` zwingt das SentenceTransformer-Modell, die Query zu embedden — obwohl es um einen **exakten Metadaten-Match** geht, bei dem die semantische Distanz egal ist.
- **Warum:** Das Embedding kostet pro Anfrage spürbar Zeit (zweistelliger ms-Bereich), ohne das Ergebnis zu beeinflussen. Der Fallback (`_get_by_contains`) macht es bereits richtig (kein Embedding).
- **Fix:** Statt `query()` ein `collection.get(where=_combine(where, {"module_id": module_id}), limit=3, include=["documents"])` verwenden (analog `_get_by_contains`). Distanz bleibt der feste Wert `0.1`.
- **Aufwand:** S · **Risiko:** niedrig (durch Test abdeckbar)

### [D1] debug_rag.py ist veraltet und führt in die Irre  `[Dead]`
- **Datei:** [scripts/debug_rag.py:99](scripts/debug_rag.py#L99), [scripts/debug_rag.py:108-123](scripts/debug_rag.py#L108-L123)
- **Problem:** Das Debug-Tool dupliziert die RAG-Routing-Logik mit **alten** Werten: `prog_n = 12/8`, einstufig `n_results=15`, und es nutzt direkt `_query_safe(..., where_document={"$contains": …})` statt des aktuellen In-Memory-Modulindex (`_lookup_module_by_name`). Der neue ECTS-Pfad (`_module_name_from_ects_question`) fehlt komplett.
- **Warum:** Wer mit `debug_rag.py` debuggt, sieht ein anderes Verhalten als der echte Server in `rag.py` (9/6/3, Skip-Rerank, Modulindex) — das Tool lügt.
- **Fix:** Entweder an `rag.py` angleichen, oder radikal vereinfachen: nur noch `build_rag_context(query, sg)` aufrufen und Kontext/Anweisung/Distanz ausgeben (kein Logik-Duplikat mehr → driftet nie wieder).
- **Aufwand:** M · **Risiko:** niedrig

---

## ⚪ Klein

### [D2] Stale Auth-Konfiguration in .env.example  `[Dead]`
- **Datei:** [.env.example:4-8](.env.example#L4-L8)
- **Problem/Fix:** `APP_USERNAME`/`APP_PASSWORD` werden im App-Code nirgends gelesen. Block entfernen (oder im Zuge von S1 mitbehandeln). · **Aufwand:** S

### [D3] test_kira.py sendet ignorierte Auth-Credentials  `[Dead]`
- **Datei:** [scripts/test_kira.py:148](scripts/test_kira.py#L148), [scripts/test_kira.py:176-179](scripts/test_kira.py#L176-L179)
- **Problem/Fix:** `auth=(admin, geheim)` und die `--user/--pass`-Flags + Docstring-Zeilen sind wirkungslos (Server prüft nichts). Entfernen für Klarheit. · **Aufwand:** S

### [D4] inspect_db.py ist ein veraltetes Einmal-Skript  `[Dead]`
- **Datei:** [scripts/inspect_db.py](scripts/inspect_db.py)
- **Problem/Fix:** Hartkodierte „Buchführung"-Debug-Queries, ohne CLI. Funktional abgelöst durch `check_db.py` (Statistik) + `debug_rag.py` (Query-Debug). Kandidat zum Löschen. · **Aufwand:** S

### [D5] Root-Archiv nicht in .gitignore  `[Cleanup]`
- **Datei:** [.gitignore](.gitignore)
- **Problem/Fix:** `data/chroma_db.zip` ist ignoriert, aber das im Deployment erzeugte `chroma_db.zip` / `chroma_db.tar.gz` im Root nicht — Risiko, versehentlich ~6,8 GB zu committen. `chroma_db.zip` und `*.tar.gz` ergänzen. · **Aufwand:** S

### [D6] Drei fast identische Modulnamen-Extraktoren  `[Dead/DRY]`
- **Datei:** [app/rag.py:93-120](app/rag.py#L93-L120)
- **Problem/Fix:** `_module_name_from_number_question`, `_..._what_is_question`, `_..._ects_question` haben denselben Aufbau (Regex `.search` → group(1) strippen → Mindestlänge). In einen Helper `_extract(regex, query, min_len)` zusammenführen. · **Aufwand:** S · **Risiko:** niedrig

### [D7] Persona-Text doppelt gepflegt  `[Dead/DRY]`
- **Datei:** [app/routes/tavus.py:30-43](app/routes/tavus.py#L30-L43)
- **Problem/Fix:** `_VOICE_CONTEXT` wiederholt KIRA-Persona/Regeln, die auch in `app/prompts.py` stehen. Zwei Quellen driften auseinander. Erwägen, `_VOICE_CONTEXT` aus den Prompt-Bausteinen abzuleiten. · **Aufwand:** S · **Risiko:** niedrig

### [P2] _flush_sentences normalisiert den Rest-Puffer mehrfach  `[Perf]`
- **Datei:** [app/routes/tavus.py:63](app/routes/tavus.py#L63)
- **Problem/Fix:** `_tts_normalize` läuft bei jedem Chunk über den gesamten Puffer inkl. des bereits geprüften Rests. Idempotent (keine Punkte mehr nach Normalisierung), daher kein Bug — aber unnötige Regex-Arbeit. Optional nur neuen Text normalisieren. Sehr geringer Nutzen. · **Aufwand:** S

### [C2] Gemini-Streaming-Retry doppelt implementiert  `[Cleanup]`
- **Datei:** [app/routes/chat.py:59-88](app/routes/chat.py#L59-L88), [app/routes/tavus.py:241-273](app/routes/tavus.py#L241-L273)
- **Problem/Fix:** Beide Routen haben eine eigene 3-Versuch-Retry-Schleife um `generate_content_stream` mit „kein Retry nach erstem Chunk". Leicht unterschiedlich (SSE-Format), aber das Kernmuster ist dupliziert. Ein gemeinsamer Async-Generator-Helper würde Drift vermeiden. Grenzfall (zwei SSE-Formate) — nur wenn ohne Verrenkung sauber. · **Aufwand:** M · **Risiko:** mittel

---

## Projektverbesserungen (zukunftsgerichtet, keine konkreten Befunde)

Rein zum Lesen — nichts davon ist Teil der Befund-Umsetzung.

1. **Linting & CI:** `ruff` (Lint + Format) ins Repo, plus eine GitHub-Action, die bei jedem Push `pytest` und `ruff check` ausführt. Fängt tote Imports/Stale-Code automatisch, bevor er sich ansammelt — genau die Klasse von Befunden, die hier manuell gefunden wurde.

2. **Coverage messen:** `pytest-cov` aktivieren, um Testlücken sichtbar zu machen (z.B. die ECTS-„kein-Treffer"-Pfade, `_get_by_contains`-Exception-Fallback).

3. **Auth-/Missbrauchsschutz fürs öffentliche Deployment:** Selbst ohne volle Auth wäre ein simples Rate-Limit (z.B. pro IP über `slowapi`) auf `/chat` sinnvoll, um Gemini-Kostenmissbrauch zu begrenzen. CORS von `*` auf die tatsächliche Frontend-Domain eingrenzen.

4. **Health-Check aussagekräftiger machen:** `/health` könnte `collection.count() > 0` prüfen, damit Railway eine leere/fehlgeschlagene Bootstrap-DB als „unhealthy" erkennt statt „ok" zu melden.

5. **Strukturierte Latenz-Metriken:** Die `[RAG-TIMING]`-Logs sind bereits da — als JSON-Logs ausgeben und optional in ein einfaches Dashboard (oder Railway-Metrics) leiten, statt sie nur in Textlogs zu vergraben.

6. **Dependency-Hygiene:** Crawler-Deps (`beautifulsoup4`, `PyMuPDF`, `langdetect`) nutzen `>=`, der Rest ist gepinnt. Einheitlich pinnen für reproduzierbare Builds.

7. **Bootstrap-Verifikation:** Nach dem Drive-Download in `ensure_chroma_db` optional `collection.count()` loggen, damit ein korrupter/leerer Download früh auffällt.
