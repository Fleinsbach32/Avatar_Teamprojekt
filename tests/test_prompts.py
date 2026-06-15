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
