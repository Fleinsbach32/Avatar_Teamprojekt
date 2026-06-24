#!/usr/bin/env python3
"""
Systematischer KIRA-Test — schickt Anfragen an /chat und gibt Antwort,
Quelle und Latenz aus.

Aufruf:
    python scripts/test_kira.py
    python scripts/test_kira.py --url http://localhost:8000

Umgebungsvariable (Alternative zum Flag):
    KIRA_URL
"""
import argparse
import asyncio
import json
import os
import sys

# Windows-Konsole auf UTF-8 umstellen (verhindert charmap-Fehler bei Sonderzeichen)
if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

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

    # Modul-spezifisch (Module die tatsächlich im WING BSc Handbuch stehen)
    ("Was ist das Modul Finanzierung und Rechnungswesen?", "de", "wing_bsc",   "Modul: Finanzierung und Rechnungswesen"),
    ("Erkläre mir Lean Management kurz.",                  "de", "wing_bsc",   "Modul: Lean Management"),

    # Modul-ID & Name→Nummer
    # M-WIWI-101430 = Angewandte Informatik in winfo_bsc (nicht wing_bsc!)
    ("M-WIWI-101430",                                      "de", "winfo_bsc",  "Modul-ID: Angewandte Informatik (winfo_bsc)"),
    ("Was ist die Modulnummer von Berufspraktikum?",       "de", "wing_bsc",   "Name → Nummer: Berufspraktikum"),

    # Englisch
    ("What compulsory modules does the WING Bachelor have?", "en", "wing_bsc", "EN: WING BSc Pflichtmodule"),
    ("How do I apply for a master's programme at KIT?",    "en", None,         "EN: Masterbewerbung"),

    # Grenzfälle / Persönlichkeit
    ("Ich habe Prüfungsangst — gibt es Unterstützung?",    "de", None,         "Edge: Prüfungsangst"),
    ("Ich komme aus Indien, kann ich mich auf einen Master bewerben?", "de", None, "Edge: Internationale Bewerbung"),
    ("Kannst du mir bei Mathe helfen?",                    "de", None,         "Edge: Off-Topic"),
    ("Wer bist du?",                                       "de", None,         "Edge: Identitätsfrage"),

    # ── Neu: Mehrschrittiges Reasoning & Administrative Abläufe ─────────────
    # Prüft ob KIRA konkrete Abläufe / Konsequenzen korrekt erklären kann
    ("Ich habe die Orientierungsprüfung nicht bestanden. Was passiert jetzt?",
                                                           "de", "wing_bsc",   "Reasoning: Orientierungsprüfung durchgefallen"),
    ("Wie oft darf ich eine Klausur wiederholen, wenn ich durchgefallen bin?",
                                                           "de", None,         "Reasoning: Prüfungswiederholungen"),
    ("Kann ich mein Berufspraktikum auch im Ausland machen?",
                                                           "de", "wing_bsc",   "Reasoning: Praktikum Ausland"),
    ("Ich bin im 5. Semester WING und möchte zu WINFO wechseln. Wie läuft das ab?",
                                                           "de", None,         "Reasoning: Studiengangwechsel"),

    # ── Neu: Bekannte Module aus der DB (testen RAG-Trefferqualität) ────────
    ("Was ist das Modul Controlling?",                     "de", "wing_bsc",   "Modul-DB: Controlling (wing_bsc)"),
    ("Was ist die Modulnummer von Strategie und Organisation?",
                                                           "de", "wing_bsc",   "Modul-DB: Name→Nummer Strategie und Organisation"),
    ("Was ist das Modul Essentials of Finance?",           "de", "wing_bsc",   "Modul-DB: Essentials of Finance (wing_bsc)"),
    ("Wie viele ECTS hat das Modul Mathematik 1?",         "de", "wing_bsc",   "Modul-DB: ECTS Mathematik 1"),

    # ── Neu: Vergleich & Studienberatung ────────────────────────────────────
    # Prüft ob KIRA sinnvoll zwischen Studiengängen differenzieren kann
    ("Was ist der Unterschied zwischen WING Bachelor und WINFO Bachelor?",
                                                           "de", None,         "Vergleich: WING vs WINFO BSc"),
    ("Ich interessiere mich für Wirtschaft und Informatik — welcher Studiengang passt: WINFO oder Digital Economics?",
                                                           "de", None,         "Vergleich: WINFO vs DigiEco"),

    # ── Neu: Persönlichkeit & Empathie ──────────────────────────────────────
    # Prüft Ton, Empathie und natürliche Gesprächsführung
    ("Die Klausurenphase macht mich wahnsinnig, ich steh total unter Druck und weiß nicht mehr weiter.",
                                                           "de", None,         "Empathie: Klausurenstress"),
    ("Hey, wie geht's dir?",                               "de", None,         "Smalltalk: Greeting"),
    ("Ich weiß nicht ob das Studium das Richtige für mich ist, ich überlege alles hinzuschmeißen.",
                                                           "de", None,         "Empathie: Studiumszweifel"),

    # ── Neu: Falsche Voraussetzungen (Fact-Checking) ────────────────────────
    # KIRA soll falsche Annahmen sanft korrigieren statt zu bestätigen
    ("Stimmt es, dass der WING Bachelor 240 ECTS hat?",    "de", "wing_bsc",   "Fact-Check: ECTS falsch (240 statt 180)"),
    ("Ich habe gehört man kann Prüfungen am KIT beliebig oft wiederholen — stimmt das?",
                                                           "de", None,         "Fact-Check: Prüfungswiederholung unbegrenzt?"),

    # ── Neu: Campus-Leben & Borderline ──────────────────────────────────────
    ("Gibt es eine Mensa am KIT — wo kann ich mittags essen?",
                                                           "de", None,         "Campus: Mensa"),
    ("Kannst du mir einen Lebenslauf schreiben?",          "de", None,         "Off-Topic: Lebenslauf"),

    # ── Neu: Englisch – Modul & Notfall ─────────────────────────────────────
    ("What is the module Controlling about?",              "en", "wing_bsc",   "EN: Modul Controlling"),
    ("I just failed my exam and I'm devastated. What are my options?",
                                                           "en", None,         "EN: Empathy + Prüfungswiederholung"),
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


async def main(url: str) -> None:
    print(f"\n{'='*72}")
    print(f"  KIRA Systemtest  —  {url}")
    print(f"{'='*72}\n")

    failed = 0
    async with httpx.AsyncClient(base_url=url) as client:
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
    parser.add_argument("--url", default=os.getenv("KIRA_URL", "http://localhost:8000"))
    args = parser.parse_args()
    asyncio.run(main(args.url))
