import os
os.environ.setdefault("GOOGLE_API_KEY", "test-key")

import main
from unittest.mock import patch


def test_prompts_share_persona():
    assert main.KIRA_CHAT_PROMPT.startswith(main.KIRA_PERSONA)
    assert main.KIRA_VOICE_PROMPT.startswith(main.KIRA_PERSONA)


def test_persona_mentions_kit():
    assert "KIRA" in main.KIRA_PERSONA
    assert "Karlsruher Institut für Technologie" in main.KIRA_PERSONA


def test_chat_prompt_has_no_voice_rules():
    assert "vorgelesen" not in main.KIRA_CHAT_PROMPT
    assert "Sprachausgabe" not in main.KIRA_CHAT_PROMPT
    assert "4 Sätzen" in main.KIRA_CHAT_PROMPT


def test_voice_prompt_has_voice_rules():
    assert "vorgelesen" in main.KIRA_VOICE_PROMPT
    assert "2 Sätzen" in main.KIRA_VOICE_PROMPT


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


class FakeRng:
    def __init__(self, random_value, choice_index=0):
        self.random_value = random_value
        self.choice_index = choice_index

    def random(self):
        return self.random_value

    def choice(self, seq):
        return seq[self.choice_index]


LONG_TEXT = ("Dies ist eine sehr lange Antwort mit deutlich mehr als "
             "fünfzehn einzelnen Wörtern damit die Filler Logik hier greift.")


def test_filler_added_for_long_answers():
    result = main.maybe_add_filler(LONG_TEXT, rng=FakeRng(0.1, choice_index=0))
    assert result == f"{main.FILLERS[0]} {LONG_TEXT}"


def test_no_filler_when_random_above_threshold():
    assert main.maybe_add_filler(LONG_TEXT, rng=FakeRng(0.9)) == LONG_TEXT


def test_no_filler_for_short_answers():
    short = "Kurze Antwort ohne Filler."
    assert main.maybe_add_filler(short, rng=FakeRng(0.1)) == short


def test_remember_and_instruct_opening():
    main.remember_opening("s_open_test", "Genau, das stimmt so.")
    instr = main.opening_instruction("s_open_test")
    assert '"Genau"' in instr


def test_no_instruction_without_history():
    assert main.opening_instruction("s_never_used") == ""
