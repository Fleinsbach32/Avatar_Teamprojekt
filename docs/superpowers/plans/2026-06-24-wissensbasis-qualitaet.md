# Wissensbasis-Qualität Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Crawler-Pipeline säubern (Encoding, Boilerplate, Dedup, Qualitätsfilter) plus Hygiene-Metriken und ein Offline-Gold-Eval, sodass ein Re-Crawl faktisch saubere Wissensbasis-Chunks liefert.

**Architecture:** Reine Helfer in `scripts/crawler.py`, von beiden Ingestion-Pfaden (Live-Crawl und `fill_db_from_crawled`) über eine gemeinsame `clean_chunks`-Funktion genutzt. `check_db.py` bekommt eine Hygiene-Sektion; neu sind `data/eval_set.json` und `scripts/eval_rag.py` (offline Retrieval-Grounding-Eval). Keine neue Dependency.

**Tech Stack:** Python 3.11, BeautifulSoup4, ChromaDB, pytest. `scripts/` ist kein Paket — Tests ergänzen den Pfad (s. `tests/test_crawler.py`). `chromadb`/`sentence_transformers` sind in `tests/conftest.py` gemockt; `bs4`/`requests` sind installiert.

---

## Dateiübersicht

| Datei | Aktion | Verantwortung |
|---|---|---|
| `scripts/crawler.py` | Modify | Encoding-Fix, Boilerplate-Extraktion, Normalisierung, Dedup, Qualitätsfilter, `clean_chunks` in beiden Pfaden |
| `tests/test_crawler.py` | Modify | Unit-Tests für alle neuen Helfer |
| `scripts/check_db.py` | Modify | Hygiene-Sektion (U+FFFD, Duplikate, Längen) |
| `data/eval_set.json` | Create | ~20 Gold-Fragen mit erwarteten Fakten |
| `scripts/eval_rag.py` | Create | Offline-Retrieval-Eval (Fakt-im-Kontext) |
| `tests/test_eval_rag.py` | Create | Test für reine Fakt-Matching-Logik |

Reihenfolge: reine Helfer zuerst (TDD), dann Verdrahtung, dann Metriken/Eval.

---

### Task 1: `_normalize_text` — Unicode-Normalisierung

**Files:**
- Modify: `scripts/crawler.py` (neuer Helfer + `import unicodedata`)
- Test: `tests/test_crawler.py`

- [ ] **Step 1: Failing Test**

Am Ende von `tests/test_crawler.py` anhängen:
```python
# ── _normalize_text ───────────────────────────────────────
def test_normalize_text_removes_soft_hyphen_and_nbsp():
    raw = "Fakult\xadät\xa0der\xa0Wirtschaft"
    assert crawler._normalize_text(raw) == "Fakultät der Wirtschaft"


def test_normalize_text_collapses_whitespace():
    assert crawler._normalize_text("a   b\n\nc\t d") == "a b c d"


def test_normalize_text_strips_control_chars():
    assert crawler._normalize_text("Text\x00mit\x07Steuerzeichen") == "Textmit Steuerzeichen" or \
           crawler._normalize_text("Text\x00mit\x07Steuerzeichen") == "Text mit Steuerzeichen"
```
Hinweis: Steuerzeichen werden entfernt (nicht durch Space ersetzt) → erwartetes Ergebnis `"Textmit Steuerzeichen"`. Die `or`-Variante deckt nur ab, falls eine Implementierung sie durch Space ersetzt; Zielverhalten ist Entfernung.

- [ ] **Step 2: Test schlägt fehl**

Run: `python -m pytest tests/test_crawler.py -k normalize_text -v`
Expected: FAIL (`_normalize_text` existiert nicht).

- [ ] **Step 3: Implementierung**

In `scripts/crawler.py` `import unicodedata` zu den stdlib-Imports (nach `import time`, Zeile ~16) hinzufügen. Direkt vor `def _split_sentences` (Zeile ~296) einfügen:
```python
def _normalize_text(text: str) -> str:
    """Unicode-Normalisierung für sauberes Embedding/Anzeige:
    NFC, Soft-Hyphen (U+00AD) entfernen, NBSP→Space, Steuerzeichen entfernen,
    Whitespace kollabieren."""
    text = unicodedata.normalize("NFC", text)
    text = text.replace("\xad", "").replace("\xa0", " ")
    # Steuerzeichen (Kategorie C*) entfernen, außer normalem Whitespace
    text = "".join(
        ch for ch in text
        if ch in "\t\n\r " or unicodedata.category(ch)[0] != "C"
    )
    return re.sub(r"\s+", " ", text).strip()
```

- [ ] **Step 4: Test grün**

Run: `python -m pytest tests/test_crawler.py -k normalize_text -v`
Expected: PASS.

- [ ] **Step 5: Commit**
```bash
git add scripts/crawler.py tests/test_crawler.py
git commit -m "feat(kb): _normalize_text — Unicode/Soft-Hyphen/Whitespace-Normalisierung"
```

---

### Task 2: `_decode_response` — Encoding-Fix

**Files:**
- Modify: `scripts/crawler.py` (neuer Helfer + Nutzung in `crawl`)
- Test: `tests/test_crawler.py`

Hintergrund: [crawler.py:595](scripts/crawler.py#L595) nutzt `BeautifulSoup(resp.text, …)` — `resp.text` rät die Kodierung falsch. Fix: Bytes (`resp.content`) an bs4 geben mit `apparent_encoding` als Hinweis.

- [ ] **Step 1: Failing Test**

Anhängen an `tests/test_crawler.py`:
```python
# ── _decode_response (Encoding-Fix) ───────────────────────
class _FakeResp:
    def __init__(self, content: bytes, apparent_encoding: str = "utf-8"):
        self.content = content
        self.apparent_encoding = apparent_encoding


def test_decode_response_utf8_without_charset_header():
    # UTF-8-Bytes ohne charset-Header → korrekte Umlaute, kein Mojibake/U+FFFD
    html = "<html><body><p>Prüfungsamt Fakultät Wirtschaft</p></body></html>"
    resp = _FakeResp(html.encode("utf-8"))
    soup = crawler._decode_response(resp)
    text = soup.get_text()
    assert "Prüfungsamt" in text
    assert "Fakultät" in text
    assert "�" not in text
```

- [ ] **Step 2: Test schlägt fehl**

Run: `python -m pytest tests/test_crawler.py -k decode_response -v`
Expected: FAIL (`_decode_response` existiert nicht).

- [ ] **Step 3: Implementierung**

In `scripts/crawler.py` direkt vor `def extract_text_html` (Zeile ~273) einfügen:
```python
def _decode_response(resp) -> BeautifulSoup:
    """Dekodiert den HTML-Body korrekt: Bytes an BeautifulSoup geben, das
    Meta-charset/BOM auswertet; apparent_encoding (chardet) als Fallback-Hinweis.
    Behebt Mojibake/U+FFFD aus dem alten BeautifulSoup(resp.text, …)."""
    return BeautifulSoup(resp.content, "html.parser", from_encoding=resp.apparent_encoding)
```
Dann in `crawl()` Zeile 595 ersetzen:
```python
                soup = BeautifulSoup(resp.text, "html.parser")
```
durch:
```python
                soup = _decode_response(resp)
```

- [ ] **Step 4: Test grün**

Run: `python -m pytest tests/test_crawler.py -k decode_response -v`
Expected: PASS.

- [ ] **Step 5: Commit**
```bash
git add scripts/crawler.py tests/test_crawler.py
git commit -m "fix(kb): _decode_response — korrektes HTML-Encoding statt resp.text"
```

---

### Task 3: `extract_text_html` — Boilerplate-Entfernung

**Files:**
- Modify: `scripts/crawler.py:273-277`
- Test: `tests/test_crawler.py`

- [ ] **Step 1: Failing Test**

Anhängen an `tests/test_crawler.py`:
```python
# ── extract_text_html: Boilerplate ────────────────────────
def test_extract_text_html_drops_div_navigation():
    from bs4 import BeautifulSoup
    html = """
    <html><body>
      <div class="main-navigation">Startseite Über uns Kontakt</div>
      <div id="cookie-banner">Wir nutzen Cookies</div>
      <main><p>Die Bewerbungsfrist endet am 15. Juli.</p></main>
      <footer class="site-footer">Impressum Datenschutz</footer>
    </body></html>
    """
    soup = BeautifulSoup(html, "html.parser")
    text = crawler.extract_text_html(soup)
    assert "Bewerbungsfrist endet am 15. Juli" in text
    assert "Über uns" not in text
    assert "Cookies" not in text
    assert "Impressum" not in text
```

- [ ] **Step 2: Test schlägt fehl**

Run: `python -m pytest tests/test_crawler.py -k drops_div_navigation -v`
Expected: FAIL (div-Navigation bleibt aktuell erhalten).

- [ ] **Step 3: Implementierung**

In `scripts/crawler.py` die Funktion `extract_text_html` (Zeilen 273–277) ersetzen durch:
```python
_BOILERPLATE_RE = re.compile(
    r"nav|menu|header|footer|cookie|breadcrumb|sidebar|skip-link|social",
    re.IGNORECASE,
)


def extract_text_html(soup: BeautifulSoup) -> str:
    # Semantische Boilerplate-Tags entfernen
    for tag in soup(["script", "style", "nav", "footer", "header", "aside", "form", "noscript"]):
        tag.decompose()
    # div/section/ul mit boilerplate-typischer class/id entfernen
    for attr in ("class", "id"):
        for tag in soup.find_all(attrs={attr: _BOILERPLATE_RE}):
            tag.decompose()
    # Bevorzugt Hauptinhalt; sonst body; sonst gesamtes Dokument
    main = (soup.find("main") or soup.find("article")
            or soup.find(id="content") or soup.body or soup)
    text = main.get_text(separator=" ", strip=True)
    return re.sub(r"\s{2,}", " ", text).strip()
```

- [ ] **Step 4: Test grün (und Regression der vorhandenen Crawler-Tests)**

Run: `python -m pytest tests/test_crawler.py -v`
Expected: alle PASS.

- [ ] **Step 5: Commit**
```bash
git add scripts/crawler.py tests/test_crawler.py
git commit -m "feat(kb): extract_text_html entfernt div-Boilerplate, bevorzugt Hauptinhalt"
```

---

### Task 4: `_content_hash`, `_is_low_quality_chunk`, `clean_chunks`

**Files:**
- Modify: `scripts/crawler.py` (drei Helfer + Konstante)
- Test: `tests/test_crawler.py`

- [ ] **Step 1: Failing Tests**

Anhängen an `tests/test_crawler.py`:
```python
# ── Qualitätsfilter + Dedup ───────────────────────────────
def test_is_low_quality_chunk_rejects_short_and_fffd():
    assert crawler._is_low_quality_chunk("Zu kurz hier.")            # < 8 Wörter
    assert crawler._is_low_quality_chunk("Text mit � Loch drin hier weiter mehr")  # U+FFFD
    assert not crawler._is_low_quality_chunk(
        "Die Bewerbungsfrist für das Wintersemester endet jedes Jahr am fünfzehnten Juli."
    )


def test_is_low_quality_chunk_rejects_symbol_soup():
    # Überwiegend Nicht-Wort-Tokens (Navigation/Symbole)
    assert crawler._is_low_quality_chunk("» | › • — / \\ > < — » Home | Kontakt | Impressum | A")


def test_clean_chunks_dedups_identical_content():
    seen = set()
    text = "Die Bewerbungsfrist endet am fünfzehnten Juli jedes Jahr im Sommer regelmäßig. " * 10
    first = crawler.clean_chunks(text, seen)
    second = crawler.clean_chunks(text, seen)   # gleiche Inhalte → bereits gesehen
    assert first              # erster Lauf liefert Chunks
    assert second == []       # zweiter Lauf komplett dedupliziert
```

- [ ] **Step 2: Tests schlagen fehl**

Run: `python -m pytest tests/test_crawler.py -k "low_quality or clean_chunks" -v`
Expected: FAIL (Funktionen existieren nicht).

- [ ] **Step 3: Implementierung**

In `scripts/crawler.py` direkt nach `chunk_text` (nach Zeile 340) einfügen:
```python
MIN_CHUNK_WORDS = 8


def _content_hash(text: str) -> str:
    """Stabiler Hash des normalisierten, kleingeschriebenen Texts (für Dedup)."""
    return hashlib.md5(_normalize_text(text).lower().encode("utf-8")).hexdigest()


def _is_low_quality_chunk(text: str) -> bool:
    """True, wenn der Chunk verworfen werden soll: U+FFFD-Reste, zu kurz oder
    überwiegend Nicht-Wort-Tokens (Navigation/Symbolmüll)."""
    if "�" in text:
        return True
    words = text.split()
    if len(words) < MIN_CHUNK_WORDS:
        return True
    alpha_words = [w for w in words if sum(c.isalpha() for c in w) >= 2]
    return len(alpha_words) / len(words) < 0.6


def clean_chunks(text: str, seen_hashes: set) -> list[str]:
    """Normalisiert Text, chunkt ihn, verwirft Low-Quality-Chunks und dedupliziert
    gegen `seen_hashes` (über den gesamten Lauf). Mutiert `seen_hashes`."""
    out: list[str] = []
    for chunk in chunk_text(_normalize_text(text)):
        if _is_low_quality_chunk(chunk):
            continue
        h = _content_hash(chunk)
        if h in seen_hashes:
            continue
        seen_hashes.add(h)
        out.append(chunk)
    return out
```

- [ ] **Step 4: Tests grün**

Run: `python -m pytest tests/test_crawler.py -k "low_quality or clean_chunks" -v`
Expected: PASS.

- [ ] **Step 5: Commit**
```bash
git add scripts/crawler.py tests/test_crawler.py
git commit -m "feat(kb): Chunk-Dedup (_content_hash) + Qualitätsfilter + clean_chunks"
```

---

### Task 5: `clean_chunks` in beide Ingestion-Pfade verdrahten

**Files:**
- Modify: `scripts/crawler.py` — `crawl()` (Zeilen ~641-685) und `fill_db_from_crawled()` (Zeilen ~870-901)
- Test: `tests/test_crawler.py`

- [ ] **Step 1: Failing Test (Pfad-Dedup über mehrere Seiten)**

Anhängen an `tests/test_crawler.py`:
```python
def test_clean_chunks_shared_seen_set_across_pages():
    # Zwei "Seiten" mit identischem Inhalt → zweite trägt nichts mehr bei
    seen = set()
    page = "Das Studienbüro hilft bei Fragen zu Anmeldung Prüfung und Fristen jederzeit gern. " * 8
    a = crawler.clean_chunks(page, seen)
    b = crawler.clean_chunks(page, seen)
    assert a and not b
```
(Verifiziert das gemeinsame `seen`-Set-Verhalten, das beide Pfade nutzen.)

- [ ] **Step 2: Test grün ausführen (clean_chunks existiert bereits aus Task 4)**

Run: `python -m pytest tests/test_crawler.py -k shared_seen_set -v`
Expected: PASS (dient als Verdrahtungs-Sicherung; eigentliche Änderung sind die Pfade).

- [ ] **Step 3: `crawl()` verdrahten**

In `scripts/crawler.py`: Direkt vor der Hauptschleife von `crawl()` ein Seen-Set anlegen. Suche die Zeile, in der `stats` initialisiert wird (vor `while queue:`), und ergänze danach:
```python
    seen_chunk_hashes: set = set()
```
Dann in `crawl()` die Zeile 642 (Normalisierung des extrahierten Texts vor dem Record):
```python
        language = detect_language(extracted_text)
```
ersetzen durch:
```python
        extracted_text = _normalize_text(extracted_text)
        language = detect_language(extracted_text)
```
Und die Ingestion (Zeile 667):
```python
                chunks = chunk_text(extracted_text)
```
ersetzen durch:
```python
                chunks = clean_chunks(extracted_text, seen_chunk_hashes)
```

- [ ] **Step 4: `fill_db_from_crawled()` verdrahten**

In `fill_db_from_crawled()` vor der Schleife `for path in json_files:` (nach Zeile 870 `total_inserted = 0`) ergänzen:
```python
    seen_chunk_hashes: set = set()
```
Und Zeile 899:
```python
        chunks = chunk_text(text)
```
ersetzen durch:
```python
        chunks = clean_chunks(text, seen_chunk_hashes)
```

- [ ] **Step 5: Volle Crawler-Tests**

Run: `python -m pytest tests/test_crawler.py -v`
Expected: alle PASS (inkl. bestehender `store_chunks`/`chunk_text`-Tests).

- [ ] **Step 6: Syntax-Check des gesamten Skripts**

Run: `python -c "import ast; ast.parse(open('scripts/crawler.py', encoding='utf-8').read()); print('ok')"`
Expected: `ok`.

- [ ] **Step 7: Commit**
```bash
git add scripts/crawler.py tests/test_crawler.py
git commit -m "feat(kb): clean_chunks + Normalisierung in Live-Crawl und fill_db_from_crawled"
```

---

### Task 6: Hygiene-Metriken in check_db.py

**Files:**
- Modify: `scripts/check_db.py` (neue Funktion + Aufruf in `main`, `import statistics`)

- [ ] **Step 1: Hygiene-Funktion hinzufügen**

In `scripts/check_db.py` `import statistics` zu den Imports (nach `from collections import Counter, defaultdict`, Zeile ~12) hinzufügen. Vor `def main()` (Zeile ~72) einfügen:
```python
def hygiene_report(col) -> None:
    """Streamt alle Dokumente und meldet Datenhygiene: U+FFFD-Quote,
    Duplikatrate (per Inhalts-Hash), Chunk-Längen."""
    import hashlib
    batch_size = 5000
    offset = 0
    total = 0
    fffd_chunks = 0
    short_chunks = 0
    lengths: list[int] = []
    seen: dict[str, int] = {}
    while True:
        batch = col.get(limit=batch_size, offset=offset, include=["documents"])
        docs = batch.get("documents") or []
        if not docs:
            break
        for doc in docs:
            doc = doc or ""
            total += 1
            if "�" in doc:
                fffd_chunks += 1
            n_words = len(doc.split())
            lengths.append(n_words)
            if n_words < 8:
                short_chunks += 1
            h = hashlib.md5(doc.strip().lower().encode("utf-8")).hexdigest()
            seen[h] = seen.get(h, 0) + 1
        offset += len(docs)
        if len(docs) < batch_size:
            break

    if total == 0:
        return
    duplicates = sum(c - 1 for c in seen.values() if c > 1)
    line()
    print("  HYGIENE")
    line()
    print(f"  Chunks mit U+FFFD:   {fffd_chunks:>7,}  ({fffd_chunks / total:.1%})")
    print(f"  Duplikat-Chunks:     {duplicates:>7,}  ({duplicates / total:.1%})")
    print(f"  Sehr kurze (<8 W.):  {short_chunks:>7,}  ({short_chunks / total:.1%})")
    print(f"  Chunk-Länge Wörter:  Ø {statistics.mean(lengths):.0f}  |  Median {statistics.median(lengths):.0f}")
    print()
```

- [ ] **Step 2: In `main()` aufrufen**

In `scripts/check_db.py` in `main()` direkt vor dem abschließenden `line("=")`-Block (vor `typen_str = …`, Zeile ~201) einfügen:
```python
    hygiene_report(col)
```

- [ ] **Step 3: Syntax-Check**

Run: `python -c "import ast; ast.parse(open('scripts/check_db.py', encoding='utf-8').read()); print('ok')"`
Expected: `ok`.

- [ ] **Step 4: Smoke-Run (DB vorhanden)**

Run: `python scripts/check_db.py`
Expected: zusätzliche „HYGIENE"-Sektion mit U+FFFD-/Duplikat-/Längen-Kennzahlen (zeigt aktuell hohe U+FFFD-/Duplikatwerte → Baseline).

- [ ] **Step 5: Commit**
```bash
git add scripts/check_db.py
git commit -m "feat(kb): check_db.py Hygiene-Sektion (U+FFFD, Duplikate, Längen)"
```

---

### Task 7: Gold-Eval-Set + eval_rag.py

**Files:**
- Create: `data/eval_set.json`
- Create: `scripts/eval_rag.py`
- Test: `tests/test_eval_rag.py`

- [ ] **Step 1: Eval-Set anlegen**

`data/eval_set.json` mit folgendem Inhalt erstellen:
```json
[
  {"question": "Wie viele ECTS hat das Modul Mathematik 1?", "lang": "de", "studiengang": "wing_bsc", "expected_facts": ["Mathematik 1"]},
  {"question": "Was ist das Modul Controlling?", "lang": "de", "studiengang": "wing_bsc", "expected_facts": ["Controlling"]},
  {"question": "Was ist das Modul Finanzierung und Rechnungswesen?", "lang": "de", "studiengang": "wing_bsc", "expected_facts": ["Finanzierung"]},
  {"question": "Was ist die Modulnummer von Berufspraktikum?", "lang": "de", "studiengang": "wing_bsc", "expected_facts": ["Berufspraktikum"]},
  {"question": "M-WIWI-101430", "lang": "de", "studiengang": "winfo_bsc", "expected_facts": ["Angewandte Informatik"]},
  {"question": "Was ist das Modul Strategie und Organisation?", "lang": "de", "studiengang": "wing_bsc", "expected_facts": ["Strategie"]},
  {"question": "Was ist das Modul Essentials of Finance?", "lang": "de", "studiengang": "wing_bsc", "expected_facts": ["Finance"]},
  {"question": "Welche Pflichtmodule hat der WING Bachelor?", "lang": "de", "studiengang": "wing_bsc", "expected_facts": ["Modul"]},
  {"question": "Wie melde ich mich für Prüfungen an?", "lang": "de", "studiengang": null, "expected_facts": ["Prüfung"]},
  {"question": "Wann ist die Bewerbungsfrist für das Wintersemester?", "lang": "de", "studiengang": null, "expected_facts": ["Bewerbung"]},
  {"question": "Wie beantrage ich ein Urlaubssemester?", "lang": "de", "studiengang": null, "expected_facts": ["Urlaubssemester"]},
  {"question": "Was ist ein NC und wie wird er berechnet?", "lang": "de", "studiengang": null, "expected_facts": ["NC"]},
  {"question": "Gibt es eine Mensa am KIT?", "lang": "de", "studiengang": null, "expected_facts": ["Mensa"]},
  {"question": "Wie funktioniert ein Auslandssemester über Erasmus?", "lang": "de", "studiengang": null, "expected_facts": ["Erasmus"]},
  {"question": "Was macht die Fachschaft WiWi?", "lang": "de", "studiengang": null, "expected_facts": ["Fachschaft"]},
  {"question": "Wo finde ich Studienberatung am KIT?", "lang": "de", "studiengang": null, "expected_facts": ["Beratung"]},
  {"question": "Wie oft darf ich eine Klausur wiederholen?", "lang": "de", "studiengang": null, "expected_facts": ["Wiederholung"]},
  {"question": "Was ist die Orientierungsprüfung?", "lang": "de", "studiengang": "wing_bsc", "expected_facts": ["Orientierung"]},
  {"question": "Welche Module gibt es im WINFO Master?", "lang": "de", "studiengang": "winfo_msc", "expected_facts": ["Modul"]},
  {"question": "Was ist das Modul Introduction to Digital Economics?", "lang": "de", "studiengang": "digieco_bsc", "expected_facts": ["Digital Economics"]}
]
```

- [ ] **Step 2: Failing Test für die Fakt-Matching-Logik**

`tests/test_eval_rag.py` erstellen:
```python
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import eval_rag  # noqa: E402


def test_facts_present_all_found():
    kontext = "Das Modul Mathematik 1 umfasst 7,5 ECTS und ist Pflicht."
    hits, total = eval_rag._facts_present(["Mathematik 1", "ECTS"], kontext)
    assert (hits, total) == (2, 2)


def test_facts_present_case_and_whitespace_insensitive():
    kontext = "Die   BEWERBUNG  läuft über das Portal."
    hits, total = eval_rag._facts_present(["bewerbung"], kontext)
    assert (hits, total) == (1, 1)


def test_facts_present_missing_fact():
    kontext = "Nur allgemeiner Text ohne den gesuchten Begriff."
    hits, total = eval_rag._facts_present(["Erasmus"], kontext)
    assert (hits, total) == (0, 1)
```

- [ ] **Step 3: Test schlägt fehl**

Run: `python -m pytest tests/test_eval_rag.py -v`
Expected: FAIL (`eval_rag` existiert nicht).

- [ ] **Step 4: eval_rag.py implementieren**

`scripts/eval_rag.py` erstellen:
```python
#!/usr/bin/env python3
"""Offline-Retrieval-Eval: prüft, ob erwartete Fakten im von build_rag_context
abgerufenen Kontext stehen. Kein Server/LLM nötig — misst Retrieval-Grounding.

Aufruf:
    python scripts/eval_rag.py
    python scripts/eval_rag.py --save baseline.json
    python scripts/eval_rag.py --compare baseline.json
"""
import argparse
import json
import re
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

EVAL_SET_PATH = PROJECT_ROOT / "data" / "eval_set.json"


def _norm(text: str) -> str:
    """Klein + Whitespace kollabiert — für robustes Substring-Matching."""
    return re.sub(r"\s+", " ", text.lower()).strip()


def _facts_present(facts: list[str], kontext: str) -> tuple[int, int]:
    """Gibt (gefundene_Fakten, gesamt) zurück (normalisierter Substring-Match)."""
    nk = _norm(kontext)
    hits = sum(1 for f in facts if _norm(f) in nk)
    return hits, len(facts)


def run() -> dict:
    from dotenv import load_dotenv
    load_dotenv(PROJECT_ROOT / ".env")
    from app.rag import build_rag_context

    eval_set = json.loads(EVAL_SET_PATH.read_text(encoding="utf-8"))
    results = []
    fact_hits = fact_total = passed = 0
    for item in eval_set:
        kontext, _, distanz = build_rag_context(item["question"], item.get("studiengang"))
        hits, total = _facts_present(item["expected_facts"], kontext)
        ok = hits == total
        fact_hits += hits
        fact_total += total
        passed += int(ok)
        results.append({
            "question": item["question"],
            "studiengang": item.get("studiengang"),
            "hits": hits, "total": total, "passed": ok,
            "distanz": round(distanz, 3),
        })
    summary = {
        "questions": len(eval_set),
        "passed": passed,
        "fact_recall": round(fact_hits / fact_total, 3) if fact_total else 0.0,
        "results": results,
    }
    return summary


def _print(summary: dict) -> None:
    print(f"\n{'='*64}")
    print(f"  RAG-Eval — {summary['passed']}/{summary['questions']} Fragen bestanden, "
          f"Fakt-Recall {summary['fact_recall']:.1%}")
    print(f"{'='*64}")
    for r in summary["results"]:
        mark = "OK " if r["passed"] else "XX "
        sg = r["studiengang"] or "-"
        print(f"  [{mark}] {r['hits']}/{r['total']}  d={r['distanz']:.2f}  [{sg}]  {r['question']}")
    print()


def main() -> None:
    parser = argparse.ArgumentParser(description="KIRA RAG-Eval (offline)")
    parser.add_argument("--save", help="Ergebnis als JSON-Baseline speichern")
    parser.add_argument("--compare", help="Mit gespeicherter Baseline vergleichen")
    args = parser.parse_args()

    summary = run()
    _print(summary)

    if args.compare:
        base = json.loads(Path(args.compare).read_text(encoding="utf-8"))
        d_pass = summary["passed"] - base["passed"]
        d_recall = summary["fact_recall"] - base["fact_recall"]
        print(f"  Δ bestanden: {d_pass:+d}   Δ Fakt-Recall: {d_recall:+.1%}\n")
    if args.save:
        Path(args.save).write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"  Baseline gespeichert: {args.save}\n")


if __name__ == "__main__":
    main()
```

- [ ] **Step 5: Test grün**

Run: `python -m pytest tests/test_eval_rag.py -v`
Expected: PASS.

- [ ] **Step 6: Commit**
```bash
git add data/eval_set.json scripts/eval_rag.py tests/test_eval_rag.py
git commit -m "feat(kb): Gold-Eval-Set + offline eval_rag.py (Retrieval-Grounding)"
```

---

### Task 8: Volle Suite + Abschluss

**Files:** keine Änderung — Verifikation.

- [ ] **Step 1: Gesamte Test-Suite**

Run: `python -m pytest tests/ -q`
Expected: alle PASS (bestehende 121 + neue Crawler-/Eval-Tests).

- [ ] **Step 2: Baseline messen (vor Re-Crawl)**

Run: `python scripts/eval_rag.py --save eval_baseline.json` und `python scripts/check_db.py`
(Hält den Ist-Zustand fest — `eval_baseline.json` ist via `*.json`? Nein: liegt im Root und ist nicht ignoriert. Bewusst NICHT committen; nur lokal zum Vergleich.)

- [ ] **Step 3 (manuell, mit Netz — Nutzer):** Re-Crawl + Rebuild

Run:
```bash
python scripts/crawler.py            # Re-Crawl, regeneriert crawled_data/ sauber
python scripts/check_db.py           # U+FFFD-Quote sollte ~0 % sein
python scripts/eval_rag.py --compare eval_baseline.json
```
Erwartet: U+FFFD ~0 %, Duplikatrate niedriger, Fakt-Recall ≥ Baseline.

---

## Self-Review-Notiz

Abgedeckt: Encoding (T2), Boilerplate (T3), Normalisierung (T1), Dedup+Qualitätsfilter (T4), Verdrahtung beider Pfade (T5), Hygiene-Metriken (T6), Gold-Eval (T7), Verifikation (T8). Helfernamen konsistent: `_normalize_text`, `_decode_response`, `extract_text_html`, `_content_hash`, `_is_low_quality_chunk`, `clean_chunks`, `_facts_present`. Keine Platzhalter.
