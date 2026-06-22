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
    """Einstufige Suche (kein Studiengang) holt 8 Kandidaten und rerankt auf 6."""
    mock_reranker = MagicMock()
    mock_reranker.predict.return_value = list(range(7, -1, -1))  # 7..0
    monkeypatch.setattr(rag_module, "reranker", mock_reranker)

    fake_docs = [f"doc_{i}" for i in range(8)]
    fake_dists = [0.3 + i * 0.01 for i in range(8)]
    mock_collection = MagicMock()
    mock_collection.query.return_value = {
        "documents": [fake_docs],
        "distances": [fake_dists],
    }
    monkeypatch.setattr(rag_module, "collection", mock_collection)

    kontext, anweisung, distanz = rag_module.build_rag_context("Wie bewerbe ich mich?")

    # ChromaDB wurde mit n_results=8 aufgerufen
    call_kwargs = mock_collection.query.call_args_list[0][1]
    assert call_kwargs["n_results"] == 8

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


def test_merge_handbook_priority_forces_min_handbook():
    """Auch wenn der Reranker alle 'all'-Chunks oben platziert, bleiben
    mindestens 3 Handbuch-Chunks im finalen Kontext."""
    prog_docs = [f"prog_{i}" for i in range(8)]
    all_docs = [f"all_{i}" for i in range(4)]

    class FakeReranker:
        # platziert absichtlich alle all_* vor prog_* (niedrigster Score für prog_*)
        def predict(self, pairs):
            scores = []
            for _q, doc in pairs:
                scores.append(0.1 if doc.startswith("prog_") else 0.9)
            return scores

    result = rag_module._merge_handbook_priority(
        prog_docs, all_docs, FakeReranker(), "frage", top_k=6, min_handbook=3
    )

    assert len(result) == 6
    handbook = [d for d in result if d.startswith("prog_")]
    assert len(handbook) >= 3


def test_merge_handbook_priority_no_reranker_keeps_order():
    """Ohne Reranker: Handbuch zuerst, dann allgemein, auf top_k geschnitten."""
    prog_docs = ["prog_0", "prog_1", "prog_2", "prog_3"]
    all_docs = ["all_0", "all_1"]

    result = rag_module._merge_handbook_priority(
        prog_docs, all_docs, None, "frage", top_k=6, min_handbook=3
    )

    assert result[:4] == prog_docs
    assert "all_0" in result and "all_1" in result


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

    def side_effect(*args, **kwargs):
        where = kwargs.get("where") or {}
        if where.get("program") == "all":
            return general_result
        return empty_result

    with patch("app.rag.collection") as mock_coll:
        mock_coll.query.side_effect = side_effect
        with caplog.at_level(logging.WARNING):
            build_rag_context("Welche Pflichtmodule gibt es?", studiengang="wing_bsc")

    assert any("Keine Handbuch-Chunks" in r.message for r in caplog.records)


# ── Einstufige Suche: n_results 8 statt 15 ───────────────────────────────────

def test_single_stage_uses_8_results_not_15():
    from unittest.mock import patch
    from app.rag import build_rag_context

    with patch("app.rag.collection") as mock_coll:
        mock_coll.query.return_value = {"documents": [[]], "distances": [[]]}
        build_rag_context("Wie bewerbe ich mich?")   # kein Studiengang → einstufig

    assert mock_coll.query.call_count == 1
    assert mock_coll.query.call_args.kwargs["n_results"] == 8


# ── _contains_variants: kurzes erstes Wort nicht als Fallback ────────────────

def test_contains_variants_skips_short_first_word_as_fallback():
    from app.rag import _contains_variants

    # "Risk" hat 4 Zeichen (< 8) — soll NICHT als Standalone-Fallback hinzugefügt werden.
    # "Analysis" hat 8 Zeichen (>= 8) — wird stattdessen als erstes langes Wort gewählt.
    variants = _contains_variants("Risk Analysis")
    assert "risk" not in variants          # "Risk" (4 Zeichen) nicht standalone
    assert "analysis" in variants          # "Analysis" (8 Zeichen) ist der Fallback
