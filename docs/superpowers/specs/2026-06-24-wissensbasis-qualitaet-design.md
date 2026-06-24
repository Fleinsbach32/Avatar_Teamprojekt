# Design: Wissensbasis-Qualität (Block 1 von 3)

**Datum:** 2026-06-24
**Status:** Approved
**Kontext:** Erster von drei Blöcken zur Antwortverbesserung. Folgeblöcke: (2) Prompt-Optimierung, (3) Latenz-Minimierung — jeweils eigener Spec→Plan→Umsetzung-Zyklus.

## Problem

Die ChromaDB besteht zu 82 % aus Webcrawl-Chunks (54.971 von 67.112), die gravierende Qualitätsmängel haben:

1. **Encoding-Korruption (verlustbehaftet):** ~25 % der Sonderzeichen in der Stichprobe sind U+FFFD-Ersetzungszeichen. Ursache: [crawler.py:595](scripts/crawler.py#L595) nutzt `BeautifulSoup(resp.text, …)`; `resp.text` rät die Kodierung falsch (fehlender charset-Header → ISO-8859-1-Default bzw. fehlerhafte Dekodierung). Die Korruption ist in den 3.644 `crawled_data/`-JSONs persistiert und nicht rückrechenbar.
2. **Boilerplate-Rauschen:** Viele Chunks bestehen aus Navigationsmenüs statt Inhalt. `extract_text_html` entfernt nur semantische Tags (`nav/footer/header/aside`), nicht div-basierte Menüs.
3. **Quasi-Duplikate:** Wiederholte Navi-Header über Chunks derselben Seite; Dedup erfolgt nur pro URL, nicht pro Chunk-Inhalt.
4. **Web verdrängt Struktur:** 55k „all"-Web-Chunks vs. ~11,7k saubere Handbuch-Chunks im Suchpool.

Die Handbuch-Daten (17,6 %) sind sauber strukturiert und bleiben die gute Basis.

## Entscheidungen (aus dem Brainstorming)

- **Voller kuratierter Re-Crawl** mit Encoding-Fix (in-place-Reparatur unmöglich, da verlustbehaftet).
- **Qualitätsfilter bei breitem Crawl** (keine Whitelist, keine harten Chunk-Caps, kein RAG-Retrieval-Rebalance). Der Web-Anteil sinkt organisch durch Dedup + Filter.
- **Messung: beides** — DB-Hygiene-Metriken UND Gold-Eval-Set für Retrieval-Grounding.
- **Ansatz A** (verbesserter Crawler in-place, keine schwere Dependency; trafilatura später nachrüstbar, falls Boilerplate-Heuristik nicht reicht).

## Architektur & Komponenten

Keine neue Dependency. Gemeinsame Helfer werden von beiden Ingestion-Pfaden genutzt (Live-Crawl `store_chunks` und offline `fill_db_from_crawled`), damit keine Logik driftet.

### `scripts/crawler.py`
- **`_decode_response(resp)`** — dekodiert den Response-Body korrekt: `BeautifulSoup(resp.content, "html.parser")` (bs4/UnicodeDammit liest Meta-charset/BOM); Fallback auf `resp.apparent_encoding`. Ersetzt `BeautifulSoup(resp.text, …)` an [crawler.py:595](scripts/crawler.py#L595).
- **`_normalize_text(text)`** — Unicode-NFC; Soft-Hyphen (`­`) entfernen; NBSP (` `)→Space; Steuerzeichen entfernen; Whitespace kollabieren. Wird vor dem Chunking angewandt.
- **`extract_text_html(soup)`** (erweitert) — zusätzlich Elemente entfernen, deren `class`/`id` auf `nav|menu|header|footer|cookie|breadcrumb|sidebar` matcht; falls vorhanden, bevorzugt aus `main`/`article`/`#content` extrahieren, sonst Fallback auf `body`.
- **`_content_hash(text)`** — stabiler Hash des normalisierten Chunk-Texts; globales Seen-Set über den Lauf → identische/Quasi-duplizierte Chunks werden übersprungen.
- **`_is_low_quality_chunk(text)`** — verwirft Chunks mit < N Wörtern, mit zu niedrigem Buchstaben-Anteil (Navigations-/Symbol-Müll) oder verbleibenden U+FFFD.

Dedup-State und Filter greifen in beiden Pfaden (`store_chunks`-Aufrufer im Live-Crawl und `fill_db_from_crawled`).

### `scripts/check_db.py`
Neue Sektion **„HYGIENE"**: U+FFFD-Quote (Anteil Chunks mit Ersetzungszeichen), Duplikatrate (per `_content_hash`), Ø/Median-Chunk-Länge, Anteil zu kurzer Chunks.

### `data/eval_set.json` (neu)
~25 Gold-Fragen, Format pro Eintrag:
```json
{"question": "Wie viele ECTS hat das Modul Mathematik 1?",
 "lang": "de", "studiengang": "wing_bsc",
 "expected_facts": ["Mathematik 1", "ECTS"]}
```
Deckt FAQ-, Handbuch-, Modul-ID-, ECTS- und Web-Themen ab.

### `scripts/eval_rag.py` (neu)
Offline (kein Server/LLM): ruft für jeden Eintrag `build_rag_context(question, studiengang)` und prüft, ob jeder `expected_fact` (normalisiert, case-insensitiv) im abgerufenen Kontext vorkommt. Ausgabe: Fakt-Trefferquote gesamt, bestandene Fragen (alle Fakten vorhanden) und Pro-Frage-Detail. Optional `--save baseline.json` und `--compare baseline.json` für Vorher/Nachher.

## Datenfluss

**Re-Crawl:** fetch → `_decode_response` → `extract_text_html` (boilerplate-frei) → `_normalize_text` → `chunk_text` → Dedup (`_content_hash`) + `_is_low_quality_chunk` → `store_chunks` (DB) + `save_json`.

**Messung:** `check_db.py` (Daten-Hygiene) und `eval_rag.py` (Retrieval-Grounding), je vor und nach dem Rebuild.

## Erfolgskriterien (messbar)
- U+FFFD-Quote in der DB → **~0 %** (vorher ~25 % der Sonderzeichen in Stichprobe).
- Duplikatrate deutlich gesenkt; Web-Chunk-Zahl sinkt spürbar.
- `eval_rag.py`-Fakt-Trefferquote **steigt** gegenüber der vor dem Rebuild gespeicherten Baseline.

## Tests (TDD)
Unit-Tests für jeden reinen Helfer:
- `_normalize_text`: Soft-Hyphen/NBSP entfernt, NFC, Whitespace kollabiert.
- `_decode_response`: UTF-8-Bytes ohne charset-Header werden korrekt zu Umlauten (kein Mojibake/U+FFFD).
- `extract_text_html`: div-basierte Navigation wird entfernt, Hauptinhalt bleibt.
- `_content_hash` + Dedup: identische Chunks werden nur einmal aufgenommen.
- `_is_low_quality_chunk`: kurze/wort-arme/U+FFFD-Chunks werden verworfen.
- `eval_rag.py`-Fakt-Matching: vorhandene vs. fehlende Fakten korrekt erkannt (normalisiert).

Integrationstest = `check_db.py`/`eval_rag.py` nach dem Rebuild (vom Nutzer ausgeführt).

## Manuelle Schritte (Nutzer, mit Netzwerk)
Nach der Implementierung: Baseline messen (`eval_rag.py --save`), dann `python scripts/crawler.py` (Re-Crawl regeneriert `crawled_data/` sauber), DB-Rebuild, dann `check_db.py` + `eval_rag.py --compare` zum Nachweis der Verbesserung.

## Außerhalb des Scope
Whitelist, harte Chunk-Caps, RAG-Retrieval-Rebalance (per Nutzerwahl), trafilatura, sowie Prompt-Optimierung (Block 2) und Latenz (Block 3).
