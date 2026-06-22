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
