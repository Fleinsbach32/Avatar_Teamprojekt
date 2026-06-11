import os
os.environ.setdefault("GOOGLE_API_KEY", "test-key")

import main
from unittest.mock import patch


def test_prompt_shares_persona():
    assert main.KIRA_PROMPT.startswith(main.KIRA_PERSONA)


def test_persona_mentions_kit():
    assert "KIRA" in main.KIRA_PERSONA
    assert "Karlsruher Institut für Technologie" in main.KIRA_PERSONA


def test_prompt_has_voice_rules():
    assert "vorgelesen" in main.KIRA_PROMPT
    assert "Sätzen" in main.KIRA_PROMPT


def test_prompt_is_human():
    assert "warm" in main.KIRA_PROMPT
    assert "Variiere" in main.KIRA_PROMPT


@patch("main.collection")
def test_build_rag_context_knowledge_base(mock_collection):
    mock_collection.query.return_value = {
        "documents": [["Doku eins", "Doku zwei"]],
        "distances": [[0.2, 0.3]]
    }
    kontext, anweisung, distanz = main.build_rag_context("Testfrage")
    assert "Doku eins" in kontext
    assert "Doku zwei" in kontext
    assert distanz == 0.2
    assert "KIT-Wissensdatenbank" in anweisung


@patch("main.collection")
def test_build_rag_context_general_fallback(mock_collection):
    mock_collection.query.return_value = {
        "documents": [["Irrelevantes Dokument"]],
        "distances": [[0.9]]
    }
    _, anweisung, distanz = main.build_rag_context("Testfrage")
    assert distanz == 0.9
    assert "allgemeines Hochschulwissen" in anweisung


@patch("main.collection")
def test_build_rag_context_truncates_docs_at_400(mock_collection):
    mock_collection.query.return_value = {
        "documents": [["C" * 500]],
        "distances": [[0.2]]
    }
    kontext, _, _ = main.build_rag_context("Testfrage")
    assert "C" * 400 in kontext
    assert "C" * 401 not in kontext


def test_remember_and_instruct_opening():
    main.remember_opening("s_open_test", "Genau, das stimmt so.")
    instr = main.opening_instruction("s_open_test")
    assert '"Genau"' in instr


def test_no_instruction_without_history():
    assert main.opening_instruction("s_never_used") == ""
