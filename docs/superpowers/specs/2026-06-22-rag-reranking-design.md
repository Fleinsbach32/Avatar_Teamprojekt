# RAG Reranking Design

**Date:** 2026-06-22
**Scope:** `app/rag.py` — Standard-Such-Pfad

---

## Ziel

Die Standard-Suche (allgemeine Fragen ohne Modul-ID oder Modulnamen) liefert aktuell die Top-N Chunks nach Embedding-Similarity. Ein Cross-Encoder bewertet Kandidaten gezielt gegen die Nutzerfrage und verbessert so die Relevanz der an das LLM weitergegebenen Chunks.

## Was sich ändert

Nur der Standard-Such-Pfad in `build_rag_context()` wird angepasst. Alle spezialisierten Pfade (Modul-ID, Modulnummer-Frage, "Was ist Modul X?") bleiben unverändert.

## Architektur

### Modul-Initialisierung

Beim Import von `app/rag.py` wird das Cross-Encoder-Modell geladen — einmalig beim App-Start, konsistent mit dem bestehenden `embedding_fn`:

```python
from sentence_transformers import CrossEncoder

reranker = CrossEncoder("cross-encoder/mmarco-mMiniLMv2-L12-H384-v1")
```

**Modell:** `cross-encoder/mmarco-mMiniLMv2-L12-H384-v1`
- Multilingual, Deutsch-tauglich
- ~120MB
- Basiert auf mMiniLMv2, geeignet für Retrieval-Reranking

### `rerank()` Hilfsfunktion

```python
def rerank(docs: list[str], query: str, top_k: int = 6) -> list[str]:
    if not docs:
        return docs
    pairs = [(query, doc) for doc in docs]
    scores = reranker.predict(pairs)
    ranked = sorted(zip(scores, docs), key=lambda x: x[0], reverse=True)
    return [doc for _, doc in ranked[:top_k]]
```

- Nimmt Kandidaten-Chunks und die Nutzer-Query
- Bildet Query-Chunk-Paare und scored sie mit dem Cross-Encoder
- Gibt die `top_k` relevantesten Chunks zurück

### Standard-Such-Pfad (einstufig, kein Studiengang)

| | Vorher | Nachher |
|---|---|---|
| ChromaDB-Kandidaten | 6 | 15 |
| An LLM weitergegebene Chunks | 6 | 6 (nach Reranking) |

```python
results = _query_safe(where, 15, query_texts=[query])
docs = rerank(results["documents"][0], query, top_k=6)
dists = results["distances"][0]
beste_distanz = dists[0] if dists else 1.0
```

### Standard-Such-Pfad (zweistufig, Studiengang gewählt)

| | Vorher | Nachher |
|---|---|---|
| Handbuch-Chunks (Stufe 1) | 4 / 8 (Pflicht) | 10 / 15 (Pflicht) |
| Allgemeine Chunks (Stufe 2) | 3 | 6 |
| Gesamt nach Reranking | — | 6 |

```python
prog_r = _query_safe({"program": studiengang}, prog_n, query_texts=[query])
all_r  = _query_safe({"program": "all"}, 6, query_texts=[query])
all_docs_dists = list(zip(all_r["documents"][0], all_r["distances"][0]))
combined_docs = prog_r["documents"][0] + all_r["documents"][0]
combined_dists = prog_r["distances"][0] + all_r["distances"][0]
docs = rerank(combined_docs, query, top_k=6)
beste_distanz = min(combined_dists) if combined_dists else 1.0
```

## Was sich NICHT ändert

- Modul-ID-Pfad (`MODULE_ID_RE`)
- Modulnummer-Fragen (`_module_name_from_number_question`)
- "Was ist Modul X?"-Pfad (`_module_name_from_what_is_question`)
- `beste_distanz` stammt weiterhin aus ChromaDB-Distanzen (nicht vom Reranker-Score)
- Anweisungs-Texte (`anweisung`) bleiben unverändert
- Keine neuen Dependencies — `sentence-transformers` ist bereits in `requirements.txt`

## Fehlerbehandlung

Falls das Reranker-Modell nicht geladen werden kann (z.B. kein Internet beim ersten Start), fällt `rerank()` auf die ursprüngliche Reihenfolge zurück:

```python
try:
    reranker = CrossEncoder("cross-encoder/mmarco-mMiniLMv2-L12-H384-v1")
except Exception as e:
    logging.warning(f"Reranker konnte nicht geladen werden: {e}")
    reranker = None
```

In `rerank()`:
```python
if reranker is None:
    return docs[:top_k]
```

## Testbarkeit

- `rerank()` ist eine reine Funktion — testbar mit Mock-Chunks und einer Test-Query
- Existing Tests für `build_rag_context()` bleiben unverändert, da der Output-Typ gleich bleibt
