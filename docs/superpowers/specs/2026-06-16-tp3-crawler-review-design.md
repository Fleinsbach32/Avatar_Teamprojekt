# Teil-Projekt 3 — Crawler-Review & Verbesserung: Design

**Datum:** 2026-06-16
**Status:** Autonom umgesetzt (ohne manuelles Review, auf Wunsch des Nutzers)
**Branch:** feature/tavus

## Ziel

Den Web-Crawler (`scripts/crawler.py`) überprüfen, an das in TP2 eingeführte
Metadaten-Schema angleichen und gefundene Fehler beheben.

## Befunde & Änderungen

### 1. Metadaten-Angleichung an TP2 (kritisch)
Gecrawlte Chunks hatten kein `program`-Feld. Der Studiengang-Filter in
`app/rag.py` nutzt `where={"$or": [{"program": key}, {"program": "all"}]}` und
matcht nur Dokumente, die das Feld besitzen → gecrawlte Inhalte wären im
Studiengang-Filter unsichtbar gewesen.
**Fix:** `program: "all"` zu allen Ingestion-Pfaden ergänzt
(`crawl()`-meta_base, `fill_db_from_crawled()`-meta_base,
`inject_module_ratings()`-meta). Webinhalte sind nicht studiengangsspezifisch und
erscheinen damit bei jeder Studiengang-Auswahl (zusätzlich zum gewählten Handbuch).

### 2. Bugfix `is_internal` (Domain-Erkennung)
`urlparse(url).netloc.lstrip("www.")` entfernt eine **Zeichenmenge**, kein
Präfix: `"www.wiwi.kit.edu".lstrip("www.")` → `"iwi.kit.edu"` (auch das 'w' von
"wiwi" wird gefressen). Dadurch wurden interne Links falsch klassifiziert.
**Fix:** Helfer `_strip_www()` (echtes Präfix-Entfernen), `is_internal` nutzt ihn.

### 3. `ALLOWED_DOMAINS` erweitert
Bisher nur `wiwi.kit.edu`, obwohl die Seeds auch fachschaft.org, hoc/zak/sle.kit.edu
enthalten → deren Links wurden nie verfolgt. **Fix:** Studienrelevante Domains
ergänzt (`fachschaft.org`, `hoc.kit.edu`, `studium.hoc.kit.edu`, `zak.kit.edu`,
`sle.kit.edu`). Die breite `www.kit.edu` bleibt **bewusst** seed-only, um eine
Crawl-Explosion zu vermeiden.

### 4. Distanzmetrik konsistent
Crawler erzeugte die Collection mit `metadata={"hnsw:space": "cosine"}`, während
`fill_db.py`/`app.rag` die Default-Metrik nutzen → je nach Erzeuger-Reihenfolge
unterschiedlicher Distanzraum (der 0.45-Schwellwert in `rag.py` ist auf den
Default getunt). **Fix:** cosine-Override im Crawler entfernt → einheitlich.

## Tests (`tests/test_crawler.py`, 7 neu)
- `_strip_www` / `is_internal` inkl. Regression auf den lstrip-Bug
- `ALLOWED_DOMAINS`: neue Domains intern, externe + breite kit.edu extern
- `store_chunks` propagiert `program` + `chunk_index` in den Upsert
- `classify_content`, `chunk_text` (Crawler-Satz-Chunker)

## Verifikation
- `python -m pytest tests/ -q` → 80 passed.
- Crawler-Import unter conftest-Mocks erfolgreich (chromadb/sentence_transformers
  gemockt; requests/bs4/PyMuPDF/langdetect installiert).

## Nicht geändert (bewusst)
- Crawl-Strategie (BFS, robots.txt, Retry/Backoff, Skip-Listen) ist solide.
- Satz-/Token-Chunking des Crawlers bleibt (für Webseiten passend; das
  modulweise Chunking aus TP2 gilt nur für die Handbuch-PDFs).

## Hinweis
Damit gecrawlte Inhalte tatsächlich in der DB landen, muss der Crawl-Workflow
ausgeführt werden (`scripts/crawl.ps1`), gefolgt von einem `fill-db`. Das ist ein
separater, optionaler Schritt; `run.ps1` baut nur die PDF/FAQ-Basis auf.
