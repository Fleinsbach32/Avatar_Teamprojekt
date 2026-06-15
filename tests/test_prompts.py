import os
os.environ.setdefault("GOOGLE_API_KEY", "test-key")

import time
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


def test_fallback_instruction_not_always_disclaiming():
    """Der Prüfungsamt-Hinweis darf nicht als Pflicht-Anhang formuliert sein."""
    with patch("main.collection") as mock_collection:
        mock_collection.query.return_value = {
            "documents": [["Irrelevant"]],
            "distances": [[0.9]]
        }
        _, anweisung, _ = main.build_rag_context("Testfrage")
    assert "ergänze am Ende" not in anweisung
    assert "nicht in jeder Antwort" in anweisung


def test_session_ttl_eviction():
    main.sessions["s_alt"] = [{"role": "Du", "content": "x"}]
    main.voice_openings["s_alt"] = "Hallo"
    main.session_last_seen["s_alt"] = time.time() - main.SESSION_TTL_SECONDS - 1

    main.touch_session("s_neu")

    assert "s_alt" not in main.sessions
    assert "s_alt" not in main.voice_openings
    assert "s_alt" not in main.session_last_seen
    assert "s_neu" in main.session_last_seen


# ── Session-Tests (app.session) ───────────────────────────
import time as _time
from app.session import (
    sessions, session_last_seen, voice_openings,
    SESSION_TTL_SECONDS, touch_session,
    remember_opening, opening_instruction,
)

def test_session_ttl_eviction_new():
    sessions["s_alt2"] = [{"role": "Du", "content": "x"}]
    voice_openings["s_alt2"] = "Hallo"
    session_last_seen["s_alt2"] = _time.time() - SESSION_TTL_SECONDS - 1
    touch_session("s_neu2")
    assert "s_alt2" not in sessions
    assert "s_alt2" not in voice_openings
    assert "s_neu2" in session_last_seen

def test_remember_and_instruct_opening_new():
    remember_opening("s_op2", "Genau, das stimmt so.")
    instr = opening_instruction("s_op2")
    assert '"Genau"' in instr

def test_no_instruction_without_history_new():
    assert opening_instruction("s_never2") == ""
