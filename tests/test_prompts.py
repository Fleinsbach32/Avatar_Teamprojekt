import os
os.environ.setdefault("GOOGLE_API_KEY", "test-key")

import main


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
