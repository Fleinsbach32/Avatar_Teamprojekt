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
