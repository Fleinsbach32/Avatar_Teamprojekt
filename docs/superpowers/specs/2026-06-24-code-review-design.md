# Design: Umfassendes Code-Review (Audit)

**Datum:** 2026-06-24
**Status:** Approved

## Ziel

Ein konsolidierter Audit-Report über die gesamte Codebasis (~4.800 Zeilen) mit
priorisierten, umsetzbaren Befunden. Der Nutzer wählt per ID aus, was umgesetzt wird;
die Umsetzung folgt danach über einen separaten Implementierungsplan.

## Umfang

- `app/` (Runtime: rag.py, tavus.py, chat.py, main.py, prompts.py, session.py, bootstrap.py, gemini.py, avatar.py)
- `scripts/` (crawler.py, fill_db.py, check_db.py, inspect_db.py, debug_rag.py, bench_rag.py, test_kira.py)
- `tests/` (11 Dateien)
- `docs/` & Config (README, requirements.txt, .env.example)

## Befund-Dimensionen

1. **Korrektheits-Bugs** — echte Fehler, Race Conditions, falsche Edge Cases, Sicherheit
2. **Dead Code & Cleanup** — ungenutzte Funktionen/Imports/Variablen, Dopplungen (DRY)
3. **Performance/Effizienz** — Hotpath-Optimierungen, redundante DB-Calls/Berechnungen

**Ausdrücklich nicht im Scope:** Struktur-Refactoring (große Dateien aufteilen).

## Durchführung

Ansatz A: Ein zusammenhängender Review durch den Hauptagenten, Bereich für Bereich,
mit vollem Kontext — damit bereichsübergreifende Befunde (z.B. Dead Code, der nur von
einem entfernten Skript genutzt wurde) erkannt werden.

## Deliverable-Format

Markdown-Report unter `docs/superpowers/specs/2026-06-24-code-review-audit.md`:

1. **Zusammenfassung** — Befundzahl pro Schweregrad + Gesamteindruck
2. **Befunde nach Schweregrad:**
   - 🔴 Kritisch — Bugs, Sicherheit, Datenverlust
   - 🟡 Wichtig — Hotpath-Performance, fehlerhafte Edge Cases, riskanter Dead Code
   - ⚪ Klein — ungenutzte Imports, Dopplungen, Mikro-Optimierungen
3. Jeder Befund mit fester Struktur:
   ```
   #### [ID] Kurztitel  [Bug|Dead|Perf]
   - Datei: pfad.py:Zeile
   - Problem / Warum / Fix
   - Aufwand: S/M/L · Risiko: niedrig/mittel/hoch
   ```
   IDs nach Dimension: `C*` (Korrektheit), `D*` (Dead Code), `P*` (Performance).
4. **Projektverbesserungen** — separate, rein lesende Sektion: Tooling (Linting/CI),
   Monitoring, Testlücken-Strategie, Architektur-Ideen.

## Nach dem Audit

Nutzer wählt Befunde per ID → Implementierungsplan (writing-plans) → Umsetzung mit Tests.
Nicht gewählte Befunde bleiben als Dokumentation im Report.
