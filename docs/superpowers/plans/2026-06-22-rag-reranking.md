# RAG Reranking Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Cross-Encoder Reranking für den Standard-Such-Pfad in `app/rag.py` hinzufügen, um relevantere Chunks an das LLM weiterzugeben.

**Architecture:** Beim App-Start wird `CrossEncoder("cross-encoder/mmarco-mMiniLMv2-L12-H384-v1")` als Modul-Variable geladen (mit Fallback auf `None`). Eine neue `rerank(docs, query, top_k)` Funktion scored Kandidaten gegen die Query. Die Standard-Suche holt mehr ChromaDB-Kandidaten (15 statt 6) und filtert via Reranking auf 6 herunter. Alle anderen Such-Pfade (Modul-ID, Modulnummer, "Was ist Modul X?") bleiben unverändert.

**Tech Stack:** `sentence-transformers` (CrossEncoder, bereits in requirements.txt), `chromadb`, `pytest`, `monkeypatch`

---

## File Map

| File | Aktion | Zweck |
|------|--------|-------|
| `app/rag.py` | Modify | CrossEncoder-Import, `reranker`-Variable, `rerank()`-Funktion, Standard-Such-Pfad anpassen |
| `tests/test_rag_reranking.py` | Create | Tests für `rerank()` und den modifizierten Standard-Such-Pfad |

---

## Task 1: `rerank()` Funktion — Test schreiben und implementieren

**Files:**
- Create: `tests/test_rag_reranking.py`
- Modify: `app/rag.py` (Zeilen 1-17: Imports + Modul-Init)

- [ ] **Step 1.1: Testdatei anlegen**

Erstelle `tests/test_rag_reranking.py` mit folgendem Inhalt:

```python
import pytest
from unittest.mock import MagicMock
import app.rag as rag_module


def test_rerank_sorts_by_score(monkeypatch):
    mock_reranker = MagicMock()
    mock_reranker.predict.return_value = [0.9, 0.1, 0.5]
    monkeypatch.setattr(rag_module, "reranker", mock_reranker)

    docs = ["most relevant", "least relevant", "middle"]
    result = rag_module.rerank(docs, "test query", top_k=2)

    assert result == ["most relevant", "middle"]


def test_rerank_returns_top_k(monkeypatch):
    mock_reranker = MagicMock()
    mock_reranker.predict.return_value = [0.8, 0.6, 0.4, 0.2]
    monkeypatch.setattr(rag_module, "reranker", mock_reranker)

    docs = ["a", "b", "c", "d"]
    result = rag_module.rerank(docs, "query", top_k=2)

    assert len(result) == 2
    assert result[0] == "a"
    assert result[1] == "b"


def test_rerank_fallback_when_reranker_none(monkeypatch):
    monkeypatch.setattr(rag_module, "reranker", None)

    docs = ["a", "b", "c", "d"]
    result = rag_module.rerank(docs, "query", top_k=2)

    assert result == ["a", "b"]


def test_rerank_empty_docs(monkeypatch):
    monkeypatch.setattr(rag_module, "reranker", None)

    result = rag_module.rerank([], "query", top_k=6)

    assert result == []


def test_rerank_fewer_docs_than_top_k(monkeypatch):
    mock_reranker = MagicMock()
    mock_reranker.predict.return_value = [0.7, 0.3]
    monkeypatch.setattr(rag_module, "reranker", mock_reranker)

    docs = ["x", "y"]
    result = rag_module.rerank(docs, "query", top_k=10)

    assert result == ["x", "y"]
```

- [ ] **Step 1.2: Tests ausführen — müssen FEHLSCHLAGEN**

```
pytest tests/test_rag_reranking.py -v
```

Erwartetes Ergebnis: `AttributeError: module 'app.rag' has no attribute 'rerank'`

- [ ] **Step 1.3: CrossEncoder-Import und `reranker`-Variable in `app/rag.py` hinzufügen**

Ersetze die ersten 17 Zeilen von `app/rag.py`:

```python
import logging
import os
import re
import chromadb
from chromadb.utils import embedding_functions
from sentence_transformers import CrossEncoder

os.environ.setdefault("TOKENIZERS_PARALLELISM", "false")

MODULE_ID_RE = re.compile(r'\b[MT]-[A-Z]+-\d+\b')

embedding_fn = embedding_functions.SentenceTransformerEmbeddingFunction(
    model_name="paraphrase-multilingual-MiniLM-L12-v2"
)
chroma_client = chromadb.PersistentClient(path="data/chroma_db")
collection = chroma_client.get_or_create_collection(
    name="uni_beratung",
    embedding_function=embedding_fn,
)

try:
    reranker = CrossEncoder("cross-encoder/mmarco-mMiniLMv2-L12-H384-v1")
except Exception as e:
    logging.warning(f"Reranker konnte nicht geladen werden: {e}")
    reranker = None
```

- [ ] **Step 1.4: `rerank()` Funktion nach `_query_safe()` einfügen (nach Zeile 109)**

Füge nach der `_query_safe()`-Funktion folgendes ein:

```python
def rerank(docs: list[str], query: str, top_k: int = 6) -> list[str]:
    if not docs:
        return docs
    if reranker is None:
        return docs[:top_k]
    pairs = [(query, doc) for doc in docs]
    scores = reranker.predict(pairs)
    ranked = sorted(zip(scores, docs), key=lambda x: x[0], reverse=True)
    return [doc for _, doc in ranked[:top_k]]
```

- [ ] **Step 1.5: Tests ausführen — müssen BESTEHEN**

```
pytest tests/test_rag_reranking.py -v
```

Erwartetes Ergebnis:
```
PASSED tests/test_rag_reranking.py::test_rerank_sorts_by_score
PASSED tests/test_rag_reranking.py::test_rerank_returns_top_k
PASSED tests/test_rag_reranking.py::test_rerank_fallback_when_reranker_none
PASSED tests/test_rag_reranking.py::test_rerank_empty_docs
PASSED tests/test_rag_reranking.py::test_rerank_fewer_docs_than_top_k
```

- [ ] **Step 1.6: Commit**

```bash
git add tests/test_rag_reranking.py app/rag.py
git commit -m "feat: add rerank() function with CrossEncoder fallback"
```

---

## Task 2: Einstufige Standard-Suche anpassen (kein Studiengang)

**Files:**
- Modify: `app/rag.py` (else-Zweig der Standard-Suche, aktuell Zeilen ~213-217)
- Modify: `tests/test_rag_reranking.py` (neuer Test)

- [ ] **Step 2.1: Test für einstufige Suche schreiben**

Füge diesen Test an `tests/test_rag_reranking.py` an:

```python
def test_standard_search_fetches_15_candidates_and_reranks(monkeypatch):
    """Einstufige Suche (kein Studiengang) holt 15 Kandidaten und rerankt auf 6."""
    mock_reranker = MagicMock()
    # Scores: letzter Chunk bekommt höchsten Score → soll nach vorne kommen
    mock_reranker.predict.return_value = list(range(14, -1, -1))  # 14..0
    monkeypatch.setattr(rag_module, "reranker", mock_reranker)

    fake_docs = [f"doc_{i}" for i in range(15)]
    fake_dists = [0.3 + i * 0.01 for i in range(15)]
    mock_collection = MagicMock()
    mock_collection.query.return_value = {
        "documents": [fake_docs],
        "distances": [fake_dists],
    }
    monkeypatch.setattr(rag_module, "collection", mock_collection)

    kontext, anweisung, distanz = rag_module.build_rag_context("Wie bewerbe ich mich?")

    # ChromaDB wurde mit n_results=15 aufgerufen
    call_kwargs = mock_collection.query.call_args_list[0][1]
    assert call_kwargs["n_results"] == 15

    # Reranker wurde aufgerufen
    assert mock_reranker.predict.called

    # Kontext enthält maximal 6 Chunks
    chunk_count = kontext.count("\n\n") + 1 if kontext else 0
    assert chunk_count <= 6
```

- [ ] **Step 2.2: Test ausführen — muss FEHLSCHLAGEN**

```
pytest tests/test_rag_reranking.py::test_standard_search_fetches_15_candidates_and_reranks -v
```

Erwartetes Ergebnis: FAIL (`n_results` ist noch 6, nicht 15)

- [ ] **Step 2.3: else-Zweig der Standard-Suche in `app/rag.py` anpassen**

Suche den else-Zweig (nach `if studiengang and studiengang in STUDIENGANG_FILES:`). Er sieht aktuell so aus:

```python
    else:
        results = _query_safe(where, 6, query_texts=[query])
        docs  = results["documents"][0]
        dists = results["distances"][0]
        beste_distanz = dists[0] if dists else 1.0
```

Ersetze ihn durch:

```python
    else:
        results = _query_safe(where, 15, query_texts=[query])
        docs  = rerank(results["documents"][0], query, top_k=6)
        dists = results["distances"][0]
        beste_distanz = dists[0] if dists else 1.0
```

- [ ] **Step 2.4: Test ausführen — muss BESTEHEN**

```
pytest tests/test_rag_reranking.py::test_standard_search_fetches_15_candidates_and_reranks -v
```

Erwartetes Ergebnis: PASSED

- [ ] **Step 2.5: Alle bisherigen Tests noch grün?**

```
pytest tests/ -v
```

Erwartetes Ergebnis: Alle Tests PASSED

- [ ] **Step 2.6: Commit**

```bash
git add app/rag.py tests/test_rag_reranking.py
git commit -m "feat: einstufige Standard-Suche holt 15 Kandidaten und rerankt auf 6"
```

---

## Task 3: Zweistufige Standard-Suche anpassen (Studiengang gewählt)

**Files:**
- Modify: `app/rag.py` (if-Zweig mit `studiengang`, aktuell Zeilen ~198-211)
- Modify: `tests/test_rag_reranking.py` (neuer Test)

- [ ] **Step 3.1: Test für zweistufige Suche schreiben**

Füge diesen Test an `tests/test_rag_reranking.py` an:

```python
def test_zweistufige_suche_kombiniert_und_rerankt(monkeypatch):
    """Zweistufige Suche (Studiengang gewählt) kombiniert Handbuch- und
    allgemeine Chunks, rerankt auf 6."""
    mock_reranker = MagicMock()
    mock_reranker.predict.return_value = [float(i) for i in range(16, 0, -1)]
    monkeypatch.setattr(rag_module, "reranker", mock_reranker)

    prog_docs = [f"prog_{i}" for i in range(10)]
    prog_dists = [0.2 + i * 0.01 for i in range(10)]
    all_docs = [f"all_{i}" for i in range(6)]
    all_dists = [0.35 + i * 0.01 for i in range(6)]

    call_count = 0

    def fake_query(**kwargs):
        nonlocal call_count
        call_count += 1
        where = kwargs.get("where", {})
        if where.get("program") == "winfo_bsc":
            return {"documents": [prog_docs[:kwargs["n_results"]]], "distances": [prog_dists[:kwargs["n_results"]]]}
        return {"documents": [all_docs[:kwargs["n_results"]]], "distances": [all_dists[:kwargs["n_results"]]]}

    mock_collection = MagicMock()
    mock_collection.query.side_effect = lambda **kw: fake_query(**kw)
    monkeypatch.setattr(rag_module, "collection", mock_collection)

    kontext, anweisung, distanz = rag_module.build_rag_context(
        "Welche Pflichtmodule gibt es?", studiengang="winfo_bsc"
    )

    # Reranker wurde aufgerufen
    assert mock_reranker.predict.called

    # Kontext enthält maximal 6 Chunks
    chunk_count = kontext.count("\n\n") + 1 if kontext else 0
    assert chunk_count <= 6

    # beste_distanz ist das Minimum der kombinierten Distanzen
    assert distanz == pytest.approx(min(prog_dists[0], all_dists[0]), abs=0.01)
```

- [ ] **Step 3.2: Test ausführen — muss FEHLSCHLAGEN**

```
pytest tests/test_rag_reranking.py::test_zweistufige_suche_kombiniert_und_rerankt -v
```

Erwartetes Ergebnis: FAIL (Reranker wird noch nicht aufgerufen im Studiengang-Pfad)

- [ ] **Step 3.3: if-Zweig der Standard-Suche in `app/rag.py` anpassen**

Suche den if-Zweig (beginnt mit `if studiengang and studiengang in STUDIENGANG_FILES:`). Er sieht aktuell so aus:

```python
    if studiengang and studiengang in STUDIENGANG_FILES:
        prog_n = 8 if is_pflicht else 4
        # Stufe 1: Handbuch des gewählten Studiengangs (Priorität)
        prog_r = _query_safe({"program": studiengang}, prog_n, query_texts=[query])
        prog_docs  = prog_r["documents"][0]
        prog_dists = prog_r["distances"][0]
        # Stufe 2: allgemeiner Inhalt (FAQ, Info, Web)
        all_r  = _query_safe({"program": "all"}, 3, query_texts=[query])
        all_docs  = all_r["documents"][0]
        all_dists = all_r["distances"][0]
        # Handbuch-Chunks zuerst, dann allgemeine (max. 8 bei Pflicht, sonst 6)
        limit = prog_n + 2
        docs  = (prog_docs + all_docs)[:limit]
        dists = (prog_dists + all_dists)[:limit]
        beste_distanz = min(dists) if dists else 1.0
```

Ersetze ihn durch:

```python
    if studiengang and studiengang in STUDIENGANG_FILES:
        prog_n = 15 if is_pflicht else 10
        # Stufe 1: Handbuch des gewählten Studiengangs (Priorität)
        prog_r = _query_safe({"program": studiengang}, prog_n, query_texts=[query])
        prog_docs  = prog_r["documents"][0]
        prog_dists = prog_r["distances"][0]
        # Stufe 2: allgemeiner Inhalt (FAQ, Info, Web)
        all_r  = _query_safe({"program": "all"}, 6, query_texts=[query])
        all_docs  = all_r["documents"][0]
        all_dists = all_r["distances"][0]
        # Kombinieren und via Cross-Encoder auf 6 reranken
        combined_docs  = prog_docs + all_docs
        combined_dists = prog_dists + all_dists
        docs  = rerank(combined_docs, query, top_k=6)
        dists = combined_dists
        beste_distanz = min(dists) if dists else 1.0
```

- [ ] **Step 3.4: Test ausführen — muss BESTEHEN**

```
pytest tests/test_rag_reranking.py::test_zweistufige_suche_kombiniert_und_rerankt -v
```

Erwartetes Ergebnis: PASSED

- [ ] **Step 3.5: Alle Tests ausführen**

```
pytest tests/ -v
```

Erwartetes Ergebnis: Alle Tests PASSED

- [ ] **Step 3.6: Commit**

```bash
git add app/rag.py tests/test_rag_reranking.py
git commit -m "feat: zweistufige Standard-Suche rerankt kombinierte Chunks auf 6"
```

---

## Fertig

Nach Task 3 ist das Reranking vollständig implementiert. Die App muss neu gestartet werden, damit das Modell beim nächsten App-Start geladen wird.

**Verifikation:**
```
pytest tests/ -v
```
Alle Tests müssen grün sein.
