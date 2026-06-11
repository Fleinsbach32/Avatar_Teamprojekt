# Einheitliche Text/Sprach-Ausgabe + menschlicheres Prompt — Design

**Datum:** 2026-06-11
**Branch:** feature/tavus
**Status:** Genehmigt
**Ersetzt teilweise:** 2026-06-11-kira-avatar-upgrade-design.md (Abschnitt 2 Dual-Prompt, Abschnitt 5 Filler)

## Ziel

Chat-Text und gesprochene Avatar-Ausgabe sollen wieder identisch sein.
Das Prompt wird menschlicher. Programmatische Filler entfallen ersatzlos
(Entscheidung des Nutzers: weder Code- noch Prompt-Floskeln).

## 1. Ein Prompt statt zwei

`KIRA_CHAT_PROMPT` und `KIRA_VOICE_PROMPT` werden zu einem `KIRA_PROMPT`
zusammengeführt (Basis bleibt `KIRA_PERSONA`). Stil: gesprochene Sprache,
da der Text vorgelesen wird — und gleichzeitig der Chat-Inhalt ist.

Anforderungen an das Prompt:
- Warm und empathisch; geht kurz auf die Situation des Fragenden ein
- Natürlicher Gesprächsrhythmus, klingt wie gesprochen
- Zahlen und Daten ausgeschrieben, keine Abkürzungen, keine Klammern,
  keine Listen
- 2–3 Sätze
- Variation im Antwortaufbau (Satzanfang-Variation bleibt aktiv)
- Keine Floskeln-Anweisung — direkter, freundlicher Ton

## 2. Backend (main.py)

### `/chat`
- Nur noch EIN streamender Gemini-Call (`KIRA_PROMPT`).
- `voice_text` im `done`-Event = kompletter gestreamter Text
  (identisch mit der Chat-Anzeige).
- Entfernt werden: `generate_voice_answer`, `maybe_add_filler`, `FILLERS`,
  `FILLER_PROBABILITY`, `FILLER_MIN_WORDS`.
- `remember_opening` / `opening_instruction` / `voice_openings` bleiben
  (Satzanfang-Variation, prompt-seitig, bricht die Identität nicht).
- SSE-Format unverändert: `chunk`-Events, `done`-Event mit
  `voice_text`, `source`, `latency_ms`, `session_id`; `error`-Event.
- `VOICE_RETRY_DELAY` bleibt (wird von `/tavus/llm` genutzt).

### `/tavus/llm`
- Nutzt dasselbe `KIRA_PROMPT` (statt `KIRA_VOICE_PROMPT`). Sonst unverändert.

## 3. Frontend (static/index.html)

Keine Änderung. `voice_text` kommt weiter im done-Event und wird vom
Avatar gesprochen — jetzt identisch mit dem angezeigten Text. Echo-Dedup
(`pendingEchoReplies`) funktioniert unverändert.

## 4. Tests

- `tests/test_prompts.py`: Filler-Tests (`FakeRng`, `maybe_add_filler`-Tests)
  entfernt; Dual-Prompt-Tests ersetzt durch Single-Prompt-Tests
  (`KIRA_PROMPT` startet mit `KIRA_PERSONA`, enthält Sprechregeln);
  Opening-Tests bleiben.
- `tests/test_chat_stream.py`: `test_chat_dual_prompts_share_context` →
  Single-Call-Test (genau EIN Gemini-Call, `generate_content` wird NICHT
  aufgerufen); `test_chat_voice_fallback_on_error` entfällt;
  `done.voice_text` == zusammengesetzte Chunks;
  Opening-Variation-Test bleibt (asserts auf den Stream-Prompt statt
  auf den Voice-Call).
- `tests/test_liveavatar.py`: `/chat`-Persona-Test angepasst — Sprechregeln
  ("vorgelesen") sind jetzt im Prompt ERLAUBT/erwartet.
- `tests/test_tavus.py`: Persona-Test prüft `KIRA_PROMPT`-Inhalte
  (funktioniert unverändert, da Sprechregeln enthalten bleiben).

## Nicht im Scope

- Begrüßung, Idle-Follow-up, Start-Skripte, `/tavus/session`,
  HeyGen/Anam-Logik: unverändert.
