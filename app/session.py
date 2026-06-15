import time

SESSION_TTL_SECONDS = 1800

sessions: dict = {}
session_last_seen: dict = {}
voice_openings: dict = {}


def touch_session(session_id: str) -> None:
    now = time.time()
    session_last_seen[session_id] = now
    abgelaufen = [sid for sid, t in session_last_seen.items() if now - t > SESSION_TTL_SECONDS]
    for sid in abgelaufen:
        session_last_seen.pop(sid, None)
        sessions.pop(sid, None)
        voice_openings.pop(sid, None)


def remember_opening(session_id: str, voice_text: str) -> None:
    words = voice_text.split()
    if words:
        voice_openings[session_id] = words[0].strip(".,!?")


def opening_instruction(session_id: str) -> str:
    last = voice_openings.get(session_id)
    if not last:
        return ""
    return f'\n\nBeginne deine Antwort nicht mit dem Wort "{last}".'
