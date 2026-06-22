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


def test_standard_search_fetches_15_candidates_and_reranks(monkeypatch):
    """Einstufige Suche (kein Studiengang) holt 15 Kandidaten und rerankt auf 6."""
    mock_reranker = MagicMock()
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
    assert chunk_count == 6


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
            n = kwargs["n_results"]
            return {"documents": [prog_docs[:n]], "distances": [prog_dists[:n]]}
        n = kwargs["n_results"]
        return {"documents": [all_docs[:n]], "distances": [all_dists[:n]]}

    mock_collection = MagicMock()
    mock_collection.query.side_effect = lambda **kw: fake_query(**kw)
    monkeypatch.setattr(rag_module, "collection", mock_collection)

    kontext, anweisung, distanz = rag_module.build_rag_context(
        "Welche Module gibt es?", studiengang="winfo_bsc"
    )

    # Reranker wurde aufgerufen
    assert mock_reranker.predict.called

    # Kontext enthält maximal 6 Chunks
    chunk_count = kontext.count("\n\n") + 1 if kontext else 0
    assert chunk_count <= 6

    # beste_distanz ist das Minimum der kombinierten Distanzen
    assert distanz == pytest.approx(min(prog_dists[0], all_dists[0]), abs=0.01)


def test_zweistufig_fetches_8_prog_and_4_all(monkeypatch):
    """Zweistufige Suche holt 8 Handbuch- + 4 allgemeine Kandidaten (Latenz)."""
    mock_reranker = MagicMock()
    mock_reranker.predict.side_effect = lambda pairs: [1.0 - i * 0.01 for i in range(len(pairs))]
    monkeypatch.setattr(rag_module, "reranker", mock_reranker)

    requested_n = {}

    def fake_query(**kwargs):
        where = kwargs.get("where", {})
        n = kwargs["n_results"]
        key = where.get("program")
        requested_n[key] = n
        docs = [f"{key}_{i}" for i in range(n)]
        dists = [0.2 + i * 0.01 for i in range(n)]
        return {"documents": [docs], "distances": [dists]}

    mock_collection = MagicMock()
    mock_collection.query.side_effect = lambda **kw: fake_query(**kw)
    monkeypatch.setattr(rag_module, "collection", mock_collection)

    rag_module.build_rag_context("Welche Module gibt es?", studiengang="winfo_bsc")

    assert requested_n["winfo_bsc"] == 8
    assert requested_n["all"] == 4


def test_zweistufig_pflicht_fetches_12_prog(monkeypatch):
    """Pflichtmodul-Frage holt 12 Handbuch-Kandidaten."""
    mock_reranker = MagicMock()
    mock_reranker.predict.side_effect = lambda pairs: [1.0 - i * 0.01 for i in range(len(pairs))]
    monkeypatch.setattr(rag_module, "reranker", mock_reranker)

    requested_n = {}

    def fake_query(**kwargs):
        where = kwargs.get("where", {})
        n = kwargs["n_results"]
        requested_n[where.get("program")] = n
        docs = [f"d_{i}" for i in range(n)]
        dists = [0.2 + i * 0.01 for i in range(n)]
        return {"documents": [docs], "distances": [dists]}

    mock_collection = MagicMock()
    mock_collection.query.side_effect = lambda **kw: fake_query(**kw)
    monkeypatch.setattr(rag_module, "collection", mock_collection)

    rag_module.build_rag_context("Welche Pflichtmodule gibt es?", studiengang="wing_bsc")

    assert requested_n["wing_bsc"] == 12
