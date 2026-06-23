import os
os.environ.setdefault("GOOGLE_API_KEY", "test-key")

import time as _time
from app.session import (
    sessions, session_last_seen, voice_openings,
    SESSION_TTL_SECONDS, touch_session,
    remember_opening, opening_instruction,
)
from app.prompts import KIRA_BASE_PROMPT, KIRA_TEXT_EXT, KIRA_VOICE_EXT, build_prompt


# ── Basis-Prompt ──────────────────────────────────────────
def test_base_prompt_mentions_kira_and_kit():
    assert "KIRA" in KIRA_BASE_PROMPT
    assert "Karlsruher Institut für Technologie" in KIRA_BASE_PROMPT

def test_base_prompt_has_security_rules():
    assert "Sicherheit" in KIRA_BASE_PROMPT or "Ignoriere" in KIRA_BASE_PROMPT

# ── build_prompt ──────────────────────────────────────────
def test_build_prompt_text_de_contains_base():
    p = build_prompt("text", "de")
    assert "KIRA" in p
    assert "Karlsruher Institut für Technologie" in p

def test_build_prompt_voice_de_has_voice_rules():
    p = build_prompt("voice", "de")
    assert "vorlesen" in p.lower() or "vorgelesen" in p.lower()

def test_build_prompt_voice_de_shorter_than_text_de():
    voice = build_prompt("voice", "de")
    text  = build_prompt("text",  "de")
    assert len(voice) < len(text), "Voice-Prompt sollte kürzer sein als Text-Prompt"

def test_build_prompt_en_text_says_english():
    p = build_prompt("text", "en")
    assert "English" in p or "english" in p.lower()

def test_build_prompt_en_voice_says_english():
    p = build_prompt("voice", "en")
    assert "English" in p or "english" in p.lower()

def test_build_prompt_unknown_lang_falls_back_to_de():
    p = build_prompt("text", "xx")
    assert "KIRA" in p

def test_build_prompt_voice_de_no_lists():
    p = build_prompt("voice", "de")
    assert "keine Listen" in p.lower() or "Keine Listen" in p

# ── Session-Tests ─────────────────────────────────────────
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

# ── RAG-Tests (app.rag) ───────────────────────────────────
from unittest.mock import patch

def test_build_rag_context_knowledge_base():
    with patch("app.rag.collection") as mock_collection:
        mock_collection.query.return_value = {
            "documents": [["Doku eins", "Doku zwei"]],
            "distances": [[0.2, 0.3]]
        }
        with patch("app.rag.rerank") as mock_rerank:
            mock_rerank.return_value = ["Doku eins", "Doku zwei"]
            from app.rag import build_rag_context
            kontext, anweisung, distanz = build_rag_context("Testfrage")
    assert "Doku eins" in kontext
    assert "Doku zwei" in kontext
    assert distanz == 0.2
    assert "KIT-Wissensdatenbank" in anweisung

def test_build_rag_context_general_fallback():
    with patch("app.rag.collection") as mock_collection:
        mock_collection.query.return_value = {
            "documents": [["Irrelevantes Dokument"]],
            "distances": [[0.9]]
        }
        with patch("app.rag.rerank") as mock_rerank:
            mock_rerank.return_value = ["Irrelevantes Dokument"]
            from app.rag import build_rag_context
            _, anweisung, distanz = build_rag_context("Testfrage")
    assert distanz == 0.9
    assert "allgemeines Hochschulwissen" in anweisung

def test_build_rag_context_truncates_docs_at_600():
    with patch("app.rag.collection") as mock_collection:
        mock_collection.query.return_value = {
            "documents": [["C" * 700]],
            "distances": [[0.2]]
        }
        with patch("app.rag.rerank") as mock_rerank:
            mock_rerank.return_value = ["C" * 700]
            from app.rag import build_rag_context
            kontext, _, _ = build_rag_context("Testfrage")
    assert "C" * 600 in kontext
    assert "C" * 601 not in kontext

def test_build_rag_context_studiengang_filter():
    with patch("app.rag.collection") as mock_collection:
        mock_collection.query.return_value = {
            "documents": [["WiInf Dokument"]],
            "distances": [[0.2]]
        }
        with patch("app.rag.rerank") as mock_rerank:
            mock_rerank.return_value = ["WiInf Dokument"]
            from app.rag import build_rag_context
            build_rag_context("Testfrage", studiengang="winfo_bsc")
    # Stufe 1: Studiengangs-spezifische Dokumente
    call1_kwargs = mock_collection.query.call_args_list[0].kwargs
    assert call1_kwargs["where"] == {"program": "winfo_bsc"}
    # Stufe 2: allgemeine Dokumente
    call2_kwargs = mock_collection.query.call_args_list[1].kwargs
    assert call2_kwargs["where"] == {"program": "all"}

def test_build_rag_context_no_studiengang_no_filter():
    with patch("app.rag.collection") as mock_collection:
        mock_collection.query.return_value = {
            "documents": [["Dok"]],
            "distances": [[0.2]]
        }
        from app.rag import build_rag_context
        build_rag_context("Testfrage", studiengang=None)
    call_kwargs = mock_collection.query.call_args.kwargs
    assert call_kwargs.get("where") is None

def test_rag_fallback_no_disclaiming():
    with patch("app.rag.collection") as mock_collection:
        mock_collection.query.return_value = {
            "documents": [["Irrelevant"]],
            "distances": [[0.9]]
        }
        from app.rag import build_rag_context
        _, anweisung, _ = build_rag_context("Testfrage")
    assert "ergänze am Ende" not in anweisung
    assert "nicht in jeder Antwort" in anweisung


# ── TP2: Modul-ID + Studiengang $or-Filter ────────────────
def test_module_id_regex_matches_m_and_t():
    from app.rag import MODULE_ID_RE
    assert MODULE_ID_RE.search("Info zu M-WIWI-101430 bitte").group() == "M-WIWI-101430"
    assert MODULE_ID_RE.search("und T-MATH-109944 dazu").group() == "T-MATH-109944"


def test_build_rag_context_studiengang_or_filter():
    with patch("app.rag.collection") as mock_collection:
        mock_collection.query.return_value = {"documents": [["Doc"]], "distances": [[0.2]]}
        with patch("app.rag.rerank") as mock_rerank:
            mock_rerank.return_value = ["Doc"]
            from app.rag import build_rag_context
            build_rag_context("Testfrage", studiengang="winfo_bsc")
    # Stufe 1: Studiengangs-spezifische Dokumente
    assert mock_collection.query.call_args_list[0].kwargs.get("where") == {"program": "winfo_bsc"}
    # Stufe 2: allgemeine Dokumente
    assert mock_collection.query.call_args_list[1].kwargs.get("where") == {"program": "all"}


def test_build_rag_context_module_id_exact_lookup():
    with patch("app.rag.collection") as mock_collection:
        mock_collection.query.return_value = {
            "documents": [["Modul: Angewandte Informatik [M-WIWI-101430] ..."]],
            "distances": [[0.2]],
        }
        from app.rag import build_rag_context
        _, _, distanz = build_rag_context("Was ist M-WIWI-101430?")
    first_where = mock_collection.query.call_args_list[0].kwargs.get("where")
    assert first_where == {"module_id": "M-WIWI-101430"}
    assert distanz == 0.1


def test_build_rag_context_module_id_with_studiengang_combines():
    with patch("app.rag.collection") as mock_collection:
        mock_collection.query.return_value = {
            "documents": [["Modul: X [M-WIWI-101430]"]],
            "distances": [[0.2]],
        }
        from app.rag import build_rag_context
        build_rag_context("Infos zu M-WIWI-101430?", studiengang="winfo_bsc")
    first_where = mock_collection.query.call_args_list[0].kwargs.get("where")
    assert first_where == {"$and": [
        {"$or": [{"program": "winfo_bsc"}, {"program": "all"}]},
        {"module_id": "M-WIWI-101430"},
    ]}


def test_module_name_extracted_from_number_question():
    from app.rag import _module_name_from_number_question as extract
    assert extract("Wie lautet die Modulnummer von Angewandte Informatik?") == "Angewandte Informatik"
    assert extract("Nummer für das Modul Statistik") == "Statistik"
    assert extract("Worum geht es im Modul Angewandte Informatik?") is None


def test_build_rag_context_number_question_uses_index():
    import app.rag as rag
    rag._module_index = [
        {"program": "winfo_bsc", "module_id": "M-WIWI-101430",
         "module_name": "Angewandte Informatik", "module_name_lower": "angewandte informatik",
         "document": "Modul: Angewandte Informatik [M-WIWI-101430] ..."},
    ]
    try:
        with patch("app.rag.collection") as mock_collection:
            _, anweisung, _ = rag.build_rag_context(
                "Wie lautet die Modulnummer von Angewandte Informatik?", studiengang="winfo_bsc")
        # Lookup lief über den In-Memory-Index — keine ChromaDB-Abfrage nötig
        mock_collection.query.assert_not_called()
        mock_collection.get.assert_not_called()
        assert "Modulnummer" in anweisung
    finally:
        rag._module_index = None


def test_what_is_module_uses_index_no_scan():
    import app.rag as rag
    rag._module_index = [
        {"program": "wing_bsc", "module_id": "M-WIWI-1", "module_name": "Controlling",
         "module_name_lower": "controlling", "document": "Modul Controlling: Grundlagen ..."},
        {"program": "wing_bsc", "module_id": "M-WIWI-2", "module_name": "Marketing",
         "module_name_lower": "marketing", "document": "Modul Marketing: ..."},
    ]
    try:
        with patch("app.rag.collection") as mock_collection:
            kontext, _, distanz = rag.build_rag_context("Was ist das Modul Controlling?", studiengang="wing_bsc")
        assert "Controlling" in kontext
        assert "Marketing" not in kontext        # nur der passende Modulname
        assert distanz == 0.1
        mock_collection.query.assert_not_called()  # Index statt Scan
        mock_collection.get.assert_not_called()
    finally:
        rag._module_index = None


def test_ects_question_extracts_module_name():
    from app.rag import _module_name_from_ects_question as ex
    assert ex("Wie viele ECTS hat das Modul Mathematik 1?") == "Mathematik 1"
    assert ex("Wie viele Leistungspunkte hat Controlling?") == "Controlling"
    assert ex("Wie viele LP bekomme ich für das Modul Statistik?") == "Statistik"
    assert ex("Wie heißt der Dekan?") is None


def test_ects_module_question_uses_index():
    import app.rag as rag
    rag._module_index = [
        {"program": "wing_bsc", "module_id": "M-MATH-1", "module_name": "Mathematik 1",
         "module_name_lower": "mathematik 1", "document": "Modul Mathematik 1: 7,5 ECTS, Pflicht ..."},
        {"program": "wing_bsc", "module_id": "M-MATH-2", "module_name": "Mathematik 2",
         "module_name_lower": "mathematik 2", "document": "Modul Mathematik 2: ..."},
    ]
    try:
        with patch("app.rag.collection") as mock_collection:
            kontext, anweisung, distanz = rag.build_rag_context(
                "Wie viele ECTS hat das Modul Mathematik 1?", studiengang="wing_bsc")
        assert "Mathematik 1" in kontext
        assert "Mathematik 2" not in kontext
        assert distanz == 0.1                       # Treffer aus der Wissensbasis
        assert "ECTS" in anweisung
        mock_collection.query.assert_not_called()   # Index statt unzuverlässiger Semantiksuche
    finally:
        rag._module_index = None


def test_base_prompt_lists_studiengaenge():
    from app.prompts import build_prompt
    for mode in ("text", "voice"):
        p = build_prompt(mode, "de")
        assert "Digital Economics" in p
        assert "Wirtschaftsinformatik" in p
        assert "180 ECTS" in p


def test_get_by_contains_uses_collection_get_not_query():
    from app.rag import _get_by_contains
    with patch("app.rag.collection") as mock_collection:
        mock_collection.get.return_value = {"documents": ["Treffer-Chunk"]}
        docs = _get_by_contains({"program": "wing_bsc"}, "Controlling", 3)
    assert docs == ["Treffer-Chunk"]
    kwargs = mock_collection.get.call_args.kwargs
    assert kwargs["where_document"] == {"$contains": "Controlling"}
    assert kwargs["where"] == {"program": "wing_bsc"}
    assert kwargs["limit"] == 3
    mock_collection.query.assert_not_called()


def test_name_lookup_falls_back_to_contains_when_index_empty():
    import app.rag as rag
    rag._module_index = []   # leerer Index → Fallback auf $contains-Scan
    try:
        with patch("app.rag.collection") as mock_collection:
            mock_collection.get.return_value = {"documents": ["Modul Controlling: ..."]}
            kontext, _, distanz = rag.build_rag_context("Was ist das Modul Controlling?", studiengang="wing_bsc")
        assert "Controlling" in kontext
        assert distanz == 0.1
        # Fallback nutzt collection.get ($contains), kein Embedding-Query
        assert mock_collection.query.call_count == 0
        assert mock_collection.get.called
    finally:
        rag._module_index = None


def test_prompt_module_number_only_on_request():
    from app.prompts import build_prompt
    for mode in ("text", "voice"):
        p = build_prompt(mode, "de")
        assert "wenn ausdrücklich danach gefragt" in p
        assert "komplett weg" not in p


def test_prompts_have_empathy_marker_de():
    for mode in ("text", "voice"):
        p = build_prompt(mode, "de").lower()
        assert "ermutig" in p, f"DE {mode}-Prompt sollte ermutigenden Ton enthalten"


def test_prompts_have_empathy_marker_en():
    for mode in ("text", "voice"):
        p = build_prompt(mode, "en").lower()
        assert "encourag" in p, f"EN {mode}-Prompt sollte ermutigenden Ton enthalten"
