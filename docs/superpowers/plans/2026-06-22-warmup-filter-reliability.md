# Warmup + Studiengang-Filter Reliability — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Behebe Cold-Start-Latenz nach Server-Neustart und stelle sicher dass der Studiengang-Filter zuverlässig studiengangspezifische RAG-Chunks zurückgibt.

**Architecture:** Workstream 1 erweitert den FastAPI-Lifespan um einen Gemini-Async-Warmup-Call. Workstream 2 verbessert `app/rag.py` um robusteres `$contains`-Matching, defensive Warnings und ein neues CLI-Debug-Skript für laufende Diagnose.

**Tech Stack:** FastAPI Lifespan, google-genai SDK, ChromaDB, pytest, logging

---

## File Map

| Datei | Änderung |
|-------|----------|
| `app/main.py` | Gemini-Warmup-Call im Lifespan |
| `app/rag.py` | `_contains_variants` erweitert, `logging.info` nach zwei-stufiger Suche + `what_is`-Pfad, `logging.warning` bei leerem `prog_docs` |
| `scripts/debug_rag.py` | Neu — CLI-Debug-Tool |
| `tests/test_rag_reranking.py` | 3 neue Tests |

---

## Task 1: Gemini Warmup im Lifespan

**Files:**
- Modify: `app/main.py:1-12` (Imports), `app/main.py:15-27` (lifespan)

Kein formaler Test nötig: der Warmup läuft im Lifespan, den der TestClient ohne `with`-Block nicht ausführt. Stattdessen Import-Check.

- [ ] **Step 1: Import ergänzen**

Datei: `app/main.py`, bestehende Import-Zeile `from app.rag import collection, reranker` ergänzen:

```python
import logging
from contextlib import asynccontextmanager

from dotenv import load_dotenv
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse

load_dotenv()

from app.gemini import client, gemini_config
from app.rag import collection, reranker
from app.routes import avatar, chat, tavus
```

- [ ] **Step 2: Gemini-Warmup-Call im Lifespan hinzufügen**

Datei: `app/main.py`, `lifespan`-Funktion. Neuen Block **nach** dem Reranker-Warmup, **vor** `yield` einfügen:

```python
@asynccontextmanager
async def lifespan(app: FastAPI):
    try:
        collection.query(query_texts=["Warmup"], n_results=1)
    except Exception as e:
        logging.warning(f"ChromaDB Warmup fehlgeschlagen: {e}")
    if reranker is not None:
        try:
            reranker.predict([("Warmup", "Warmup")])
        except Exception as e:
            logging.warning(f"Reranker Warmup fehlgeschlagen: {e}")
    try:
        await client.aio.models.generate_content(
            model="gemini-2.5-flash",
            contents="Warmup",
            config=gemini_config(1),
        )
    except Exception as e:
        logging.warning(f"Gemini Warmup fehlgeschlagen: {e}")
    yield
    await tavus._http.aclose()
```

- [ ] **Step 3: Import-Check ausführen**

```bash
cd c:/Users/lucat/Downloads/Avatar_Teamprojekt-feature-tavus
python -c "import app.main; print('IMPORT OK')"
```

Erwartete Ausgabe: `IMPORT OK`

- [ ] **Step 4: Tests laufen lassen**

```bash
python -m pytest tests/ -q
```

Erwartete Ausgabe: alle Tests grün (Anzahl unverändert gegenüber aktuell).

- [ ] **Step 5: Commit**

```bash
git add app/main.py
git commit -m "feat(startup): Gemini HTTP-Client Warmup im Lifespan"
```

---

## Task 2: RAG-Verbesserungen (`app/rag.py`)

**Files:**
- Modify: `app/rag.py:94-102` (`_contains_variants`), `app/rag.py:267-281` (Zwei-Stufen-Suche), `app/rag.py:232-238` (`what_is`-Pfad)
- Test: `tests/test_rag_reranking.py`

### Schritt-für-Schritt

- [ ] **Step 1: Failing-Tests schreiben**

Datei: `tests/test_rag_reranking.py` — folgende drei Tests ans Ende der Datei anhängen:

```python
# ── _contains_variants: Erweiterung ──────────────────────────────────────────

def test_contains_variants_includes_full_lowercase():
    from app.rag import _contains_variants
    variants = _contains_variants("Introduction to Digital Economics")
    assert "introduction to digital economics" in variants


def test_contains_variants_first_word_lowercase_fallback():
    from app.rag import _contains_variants
    variants = _contains_variants("Introduction to Digital Economics")
    assert "introduction" in variants


# ── RAG: Warning bei leerem prog_docs ────────────────────────────────────────

def test_rag_warns_when_no_handbook_chunks_for_studiengang(caplog):
    import logging
    from unittest.mock import patch
    from app.rag import build_rag_context

    empty_result   = {"documents": [[]], "distances": [[]]}
    general_result = {"documents": [["General KIT Info"]], "distances": [[0.3]]}

    with patch("app.rag.collection") as mock_coll:
        # Erste Query = prog_docs (leer), zweite = all_docs (ein Treffer)
        mock_coll.query.side_effect = [empty_result, general_result]
        with caplog.at_level(logging.WARNING):
            build_rag_context("Welche Pflichtmodule gibt es?", studiengang="wing_bsc")

    assert any("Keine Handbuch-Chunks" in r.message for r in caplog.records)
```

- [ ] **Step 2: Tests als failing verifizieren**

```bash
python -m pytest tests/test_rag_reranking.py::test_contains_variants_includes_full_lowercase tests/test_rag_reranking.py::test_contains_variants_first_word_lowercase_fallback tests/test_rag_reranking.py::test_rag_warns_when_no_handbook_chunks_for_studiengang -v
```

Erwartete Ausgabe: FAILED für alle drei (AssertionError oder AttributeError).

- [ ] **Step 3: `_contains_variants` erweitern**

Datei: `app/rag.py`, Funktion `_contains_variants` (ca. Zeile 94). **Ersetze die gesamte Funktion:**

```python
def _contains_variants(name: str) -> list[str]:
    """Erzeugt Schreibvarianten für where_document $contains (Case-Varianten
    + erster Bestandteil als Fallback bei mehrteiligen Namen)."""
    variants = [name, name.title(), name.capitalize(), name.lower()]
    words = name.split()
    if len(words) > 1:
        for w in words:
            if len(w) >= 4:
                variants.extend([w, w.title(), w.lower()])
                break
    return list(dict.fromkeys(v for v in variants if v))
```

- [ ] **Step 4: Warning bei leerem `prog_docs` hinzufügen**

Datei: `app/rag.py`, Funktion `build_rag_context`, Zwei-Stufen-Zweig. Suche die Zeile:

```python
        prog_docs  = prog_r["documents"][0]
```

Und füge direkt darunter ein:

```python
        if not prog_docs:
            logging.warning(
                f"[RAG] Keine Handbuch-Chunks für studiengang={studiengang!r} gefunden "
                f"— Filter greift möglicherweise nicht."
            )
```

- [ ] **Step 5: `logging.info` nach Zwei-Stufen-Ergebnis hinzufügen**

Datei: `app/rag.py`, nach der Zeile:

```python
        beste_distanz = min(combined_dists) if combined_dists else 1.0
```

Füge direkt danach ein:

```python
        logging.info(
            f"[RAG] SG={studiengang}: prog={len(prog_docs)} handbuch, all={len(all_docs)} general"
            f" → final={len(docs)} chunks"
        )
```

- [ ] **Step 6: `logging.info` im `what_is`-Pfad hinzufügen**

Datei: `app/rag.py`, Funktion `build_rag_context`, `what_is_name`-Zweig. Suche den Block:

```python
        for variant in _contains_variants(what_is_name):
            what_results = _query_safe(where, 3, query_texts=[what_is_name],
                                       where_document={"$contains": variant})
            if what_results["documents"][0]:
                break
        if what_results["documents"][0]:
```

Füge **zwischen** `break` und `if what_results` eine neue Zeile ein (nach dem for-Loop, vor dem `if`):

```python
        for variant in _contains_variants(what_is_name):
            what_results = _query_safe(where, 3, query_texts=[what_is_name],
                                       where_document={"$contains": variant})
            if what_results["documents"][0]:
                break
        logging.info(
            f"[RAG] was_ist='{what_is_name}': contains-Treffer="
            f"{len(what_results['documents'][0])} (where={where})"
        )
        if what_results["documents"][0]:
```

- [ ] **Step 7: Tests grün verifizieren**

```bash
python -m pytest tests/test_rag_reranking.py::test_contains_variants_includes_full_lowercase tests/test_rag_reranking.py::test_contains_variants_first_word_lowercase_fallback tests/test_rag_reranking.py::test_rag_warns_when_no_handbook_chunks_for_studiengang -v
```

Erwartete Ausgabe: PASSED für alle drei.

- [ ] **Step 8: Alle Tests laufen lassen**

```bash
python -m pytest tests/ -q
```

Erwartete Ausgabe: alle Tests grün.

- [ ] **Step 9: Commit**

```bash
git add app/rag.py tests/test_rag_reranking.py
git commit -m "fix(rag): robusteres contains-Matching, defensive Logging, Warning bei leerem prog_docs"
```

---

## Task 3: CLI-Debug-Skript `scripts/debug_rag.py`

**Files:**
- Create: `scripts/debug_rag.py`

Kein pytest-Test — Verifikation durch direkten Aufruf.

- [ ] **Step 1: Skript erstellen**

Datei neu anlegen: `scripts/debug_rag.py`

```python
#!/usr/bin/env python3
"""Debug-Tool: Zeigt welche RAG-Chunks für eine Query abgerufen werden.

Verwendung:
    python scripts/debug_rag.py "Was ist Introduction to Digital Economics?" --studiengang digieco_bsc
    python scripts/debug_rag.py "Welche Pflichtmodule hat WING?" --studiengang wing_bsc
    python scripts/debug_rag.py "Wie bewerbe ich mich?"
"""
import argparse
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from dotenv import load_dotenv
load_dotenv(PROJECT_ROOT / ".env")

from app.rag import (
    _query_safe,
    _contains_variants,
    _module_name_from_what_is_question,
    _module_name_from_number_question,
    _merge_handbook_priority,
    _studiengang_where,
    STUDIENGANG_FILES,
    MODULE_ID_RE,
    reranker,
)


def _label(docs: list) -> str:
    return f"{len(docs)} Chunk(s)" if docs else "0 Chunks (LEER)"


def debug(query: str, studiengang: str | None = None) -> None:
    print(f"\nQuery      : {query!r}")
    print(f"Studiengang: {studiengang or '(kein)'}")
    print("-" * 64)

    where = _studiengang_where(studiengang)

    # Pfad 1: Modul-ID erkannt
    module_match = MODULE_ID_RE.search(query)
    if module_match:
        mid = module_match.group()
        print(f"Pfad: MODUL_ID  (id={mid!r})")
        r = _query_safe({"module_id": mid}, 3, query_texts=[query])
        docs = r["documents"][0]
        print(f"  Treffer: {_label(docs)}")
        for i, d in enumerate(docs):
            print(f"  [{i}] {d[:120]!r}")
        return

    # Pfad 2: "Modulnummer von X?"
    name_query = _module_name_from_number_question(query)
    if name_query:
        print(f"Pfad: MODULNUMMER_FRAGE  (name={name_query!r})")
        for variant in _contains_variants(name_query):
            r = _query_safe(where, 3, query_texts=[name_query],
                            where_document={"$contains": variant})
            n = len(r["documents"][0])
            print(f"  Variante {variant!r:40s} → {n} Treffer")
            if n:
                print(f"    {r['documents'][0][0][:100]!r}")
        return

    # Pfad 3: "Was ist X?"
    what_is_name = _module_name_from_what_is_question(query)
    if what_is_name:
        print(f"Pfad: WAS_IST_MODULE  (name={what_is_name!r})")
        print(f"  where-Filter: {where}")
        found_variant = None
        for variant in _contains_variants(what_is_name):
            r = _query_safe(where, 3, query_texts=[what_is_name],
                            where_document={"$contains": variant})
            n = len(r["documents"][0])
            print(f"  Variante {variant!r:40s} → {n} Treffer")
            if n and found_variant is None:
                found_variant = variant
                for d in r["documents"][0]:
                    print(f"    {d[:120]!r}")
        if found_variant is None:
            print("  → Kein $contains-Treffer gefunden.")
            if studiengang and studiengang in STUDIENGANG_FILES:
                print("    Fallback: 'nicht in diesem Studiengang'-Antwort")
            else:
                print("    Fallback: Standard-Semantiksuche (kein Studiengang)")
        return

    # Pfad 4: Standard-Semantiksuche
    is_pflicht = any(
        kw in query.lower()
        for kw in ("pflichtmodul", "pflicht", "orientierungsprüfung", "orientierungspruefung")
    )
    print(f"Pfad: SEMANTIK  (is_pflicht={is_pflicht})")

    if studiengang and studiengang in STUDIENGANG_FILES:
        prog_n = 12 if is_pflicht else 8
        print(f"\n  [Stufe 1] program={studiengang!r}, n_results={prog_n}")
        prog_r = _query_safe({"program": studiengang}, prog_n, query_texts=[query])
        prog_docs = prog_r["documents"][0]
        prog_dists = prog_r["distances"][0]
        print(f"  → {_label(prog_docs)}")
        if not prog_docs:
            print("  ⚠️  LEER — Filter greift nicht oder Metadaten prüfen!")

        print(f"\n  [Stufe 2] program='all', n_results=4")
        all_r = _query_safe({"program": "all"}, 4, query_texts=[query])
        all_docs = all_r["documents"][0]
        all_dists = all_r["distances"][0]
        print(f"  → {_label(all_docs)}")

        print(f"\n  [_merge_handbook_priority] top_k=6, min_handbook=3 ...")
        docs = _merge_handbook_priority(prog_docs, all_docs, reranker, query, top_k=6, min_handbook=3)
        combined_dists = prog_dists + all_dists
        beste_distanz = min(combined_dists) if combined_dists else 1.0
        print(f"  → Finaler Kontext: {_label(docs)}")
        print(f"  Beste Distanz: {beste_distanz:.3f}  →  Quelle: "
              f"{'Wissensbasis' if beste_distanz < 0.45 else 'LLM'}")
    else:
        print(f"  [Einstufig] n_results=15")
        r = _query_safe(where, 15, query_texts=[query])
        docs = r["documents"][0]
        dists = r["distances"][0]
        beste_distanz = dists[0] if dists else 1.0
        print(f"  → {_label(docs)}, Beste Distanz: {beste_distanz:.3f}")

    print(f"\n  Finaler Kontext ({len(docs)} Chunks):")
    for i, d in enumerate(docs):
        print(f"  [{i}] {d[:160]!r}")


def main() -> None:
    parser = argparse.ArgumentParser(description="KIRA RAG Debug Tool")
    parser.add_argument("query", help="Die Testfrage")
    parser.add_argument(
        "--studiengang",
        default=None,
        help=f"Studiengang-Key (z.B. wing_bsc). Gültig: {', '.join(STUDIENGANG_FILES)}",
    )
    args = parser.parse_args()

    if args.studiengang and args.studiengang not in STUDIENGANG_FILES:
        print(f"Fehler: Unbekannter Studiengang {args.studiengang!r}")
        print(f"Gültige Keys: {', '.join(STUDIENGANG_FILES)}")
        sys.exit(1)

    debug(args.query, args.studiengang)


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: Skript testen — allgemeine Query**

```bash
cd c:/Users/lucat/Downloads/Avatar_Teamprojekt-feature-tavus
python scripts/debug_rag.py "Wie bewerbe ich mich am KIT?"
```

Erwartete Ausgabe: `Pfad: SEMANTIK`, gefolgt von Chunk-Liste mit Distanzwert.

- [ ] **Step 3: Skript testen — mit Studiengang**

```bash
python scripts/debug_rag.py "Welche Pflichtmodule hat WING?" --studiengang wing_bsc
```

Erwartete Ausgabe: `Pfad: SEMANTIK (is_pflicht=True)`, Stufe-1 zeigt `> 0 Chunks` für `wing_bsc`. Falls `0 Chunks (LEER)` erscheint, ist das ein Hinweis auf Metadaten-Mismatch in ChromaDB.

- [ ] **Step 4: Skript testen — `what_is`-Pfad**

```bash
python scripts/debug_rag.py "Was ist Introduction to Digital Economics?" --studiengang digieco_bsc
```

Erwartete Ausgabe: `Pfad: WAS_IST_MODULE`, Varianten-Treffer für mindestens eine Schreibvariante.

- [ ] **Step 5: Abschließende Test-Suite**

```bash
python -m pytest tests/ -q
```

Erwartete Ausgabe: alle Tests grün.

- [ ] **Step 6: Commit**

```bash
git add scripts/debug_rag.py
git commit -m "feat(scripts): debug_rag.py — CLI-Diagnose für RAG-Filter"
```

---

## Akzeptanzkriterien (Gesamt)

1. `python -c "import app.main"` → kein Fehler
2. `python -m pytest tests/ -q` → alle Tests grün
3. `python scripts/debug_rag.py "Was ist Introduction to Digital Economics?" --studiengang digieco_bsc` → zeigt Treffer für mindestens eine Variante (oder klar "LEER" mit Hinweis)
4. Im Server-Log (`uvicorn --log-level info`) ist pro Anfrage ein `[RAG]`-Eintrag sichtbar
5. Erste Nutzeranfrage nach Server-Start fühlt sich nicht langsamer an als folgende
