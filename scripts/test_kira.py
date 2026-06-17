#!/usr/bin/env python3
"""
Systematischer KIRA-Test — schickt Anfragen an /chat und gibt Antwort,
Quelle und Latenz aus.

Aufruf:
    python scripts/test_kira.py
    python scripts/test_kira.py --url http://localhost:8000 --user admin --pass geheim

Umgebungsvariablen (Alternative zu Flags):
    KIRA_URL, APP_USERNAME, APP_PASSWORD
"""
import argparse
import asyncio
import json
import os
import sys

try:
    import httpx
except ImportError:
    print("httpx fehlt — bitte 'pip install httpx' ausführen.")
    sys.exit(1)

# ---------------------------------------------------------------------------
# Testfälle: (Frage, lang, studiengang, Beschreibung)
# ---------------------------------------------------------------------------
TESTS = [
    # Allgemeine FAQ
    ("Wie melde ich mich für Prüfungen an?",              "de", None,         "FAQ: Prüfungsanmeldung"),
    ("Wann ist die Bewerbungsfrist für das Wintersemester?", "de", None,       "FAQ: Bewerbungsfrist"),
    ("Was ist ein NC und wie wird er berechnet?",          "de", None,         "FAQ: NC-Erklärung"),
    ("Wie beantrage ich ein Urlaubssemester?",             "de", None,         "FAQ: Urlaubssemester"),

    # Studiengangs-Anfragen MIT Filter — Handbuch soll priorisiert werden
    ("Welche Pflichtmodule hat der WING Bachelor?",        "de", "wing_bsc",   "WING BSc Pflichtmodule (mit Filter)"),
    ("Welche Pflichtmodule hat der WING Bachelor?",        "de", None,         "WING BSc Pflichtmodule (ohne Filter)"),
    ("Welche Module gibt es im WINFO Master?",             "de", "winfo_msc",  "WINFO MSc Module (mit Filter)"),
    ("Wie viele ECTS hat der Digital Economics Bachelor?", "de", "digieco_bsc","DigiEco BSc ECTS (mit Filter)"),

    # Modul-spezifisch
    ("Was ist das Modul Buchführung und Abschluss?",       "de", "wing_bsc",   "Modul: Buchführung (mit Filter)"),
    ("Erkläre mir Lean Management kurz.",                  "de", "wing_bsc",   "Modul: Lean Management"),

    # Modul-ID & Name→Nummer
    ("M-WIWI-101430",                                      "de", "wing_bsc",   "Modul-ID direkt"),
    ("Was ist die Modulnummer von Buchführung und Abschluss?", "de", "wing_bsc", "Name → Nummer"),

    # Englisch
    ("What compulsory modules does the WING Bachelor have?", "en", "wing_bsc", "EN: WING BSc Pflichtmodule"),
    ("How do I apply for a master's programme at KIT?",    "en", None,         "EN: Masterbewerbung"),

    # Grenzfälle / Persönlichkeit
    ("Ich habe Prüfungsangst — gibt es Unterstützung?",    "de", None,         "Edge: Prüfungsangst"),
    ("Ich komme aus Indien, kann ich mich auf einen Master bewerben?", "de", None, "Edge: Internationale Bewerbung"),
    ("Kannst du mir bei Mathe helfen?",                    "de", None,         "Edge: Off-Topic"),
    ("Wer bist du?",                                       "de", None,         "Edge: Identitätsfrage"),
]

# ---------------------------------------------------------------------------

async def ask(client: "httpx.AsyncClient", frage: str, lang: str,
              studiengang, session_id: str) -> tuple[str, int | None, str]:
    body = {
        "message": frage,
        "session_id": session_id,
        "lang": lang,
        "studiengang": studiengang,
    }
    full_text = ""
    latency   = None
    source    = "?"
    async with client.stream("POST", "/chat", json=body, timeout=40) as resp:
        resp.raise_for_status()
        async for line in resp.aiter_lines():
            if not line.startswith("data:"):
                continue
            try:
                ev = json.loads(line[5:])
            except Exception:
                continue
            if ev.get("type") == "chunk":
                full_text += ev["text"]
            elif ev.get("type") == "done":
                latency = ev.get("latency_ms")
                source  = ev.get("source", "?")
            elif ev.get("type") == "error":
                full_text = f"[FEHLER] {ev.get('message', '?')}"
    return full_text, latency, source


async def main(url: str, username: str, password: str) -> None:
    auth = (username, password)
    print(f"\n{'='*72}")
    print(f"  KIRA Systemtest  —  {url}")
    print(f"{'='*72}\n")

    failed = 0
    async with httpx.AsyncClient(base_url=url, auth=auth) as client:
        for i, (frage, lang, sg, desc) in enumerate(TESTS, 1):
            sid = f"test_{i:03d}"
            sg_tag = sg or "kein Studiengang"
            print(f"[{i:02d}/{len(TESTS)}] {desc}  [{sg_tag}]")
            print(f"  F: {frage}")
            try:
                antwort, latenz, quelle = await ask(client, frage, lang, sg, sid)
                lat_str = f"{latenz} ms" if latenz is not None else "?"
                print(f"  A: {antwort}")
                print(f"     → {quelle} | {lat_str}\n")
            except Exception as exc:
                print(f"  [FEHLER] {exc}\n")
                failed += 1

    print(f"{'='*72}")
    print(f"  Fertig. {len(TESTS) - failed}/{len(TESTS)} Tests erfolgreich.")
    print(f"{'='*72}\n")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="KIRA Systemtest")
    parser.add_argument("--url",  default=os.getenv("KIRA_URL",      "http://localhost:8000"))
    parser.add_argument("--user", default=os.getenv("APP_USERNAME",  "admin"))
    parser.add_argument("--pass", dest="pw",
                        default=os.getenv("APP_PASSWORD", "geheim"))
    args = parser.parse_args()
    asyncio.run(main(args.url, args.user, args.pw))
