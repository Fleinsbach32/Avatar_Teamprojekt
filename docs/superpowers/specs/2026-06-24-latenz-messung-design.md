# Design: Latenz-Messung (Block 3, Teilprojekt A)

**Datum:** 2026-06-24
**Status:** Approved
**Kontext:** Dritter Block (Latenz-Minimierung). Bewusst zweigeteilt: **(A) Messung** — dieses Spec — und **(B) Optimierung** auf Datenbasis (eigenes Spec, sobald Messdaten vorliegen). „Erst messen, dann gezielt optimieren."

## Problem

Beide Antwortpfade (`/chat` und `/tavus/llm`) fühlen sich träge an — generelle Time-to-First-Token. Der gemeinsame Kern ist `build_rag_context` (Embedding + ChromaDB + ggf. Reranker) gefolgt von `stream_gemini` (Gemini-TTFT). Es gibt bereits `[RAG-TIMING]`-Logs für die RAG-Sub-Phasen, aber **die Gemini-TTFT wird nirgends gemessen** und es gibt keinen reproduzierbaren Gesamt-Überblick. Ohne Messung wäre jede Optimierung blind.

## Entscheidungen (aus dem Brainstorming)

- **Ansatz A:** Standalone-Benchmark-Skript, Black-Box-Timing. Keine Änderung an `app/`-Code (rein additiv).
- **Reuse** von `data/eval_set.json` (20 repräsentative Fragen, decken Modul- + allgemeine Themen ab).
- **Phasen:** `rag_ms`, `ttft_ms`, `gen_ms`, `e2e_ms`.
- **Gemini optional** per `--no-llm` (RAG-Timing dann offline, ohne API-Key).
- RAG-Sub-Phasen (Embedding vs Reranker) bleiben in den bestehenden `[RAG-TIMING]`-Logs — nur falls Teilprojekt B zeigt, dass RAG dominiert.

## Architektur & Komponenten

### `scripts/bench_latency.py` (neu)

Aufbau nach dem Muster von `scripts/eval_rag.py` (gleiche `sys.path`-Ergänzung, `load_dotenv`, Win32-`stdout.reconfigure`).

- **`_aggregate(records: list[dict]) -> dict`** — reine Funktion. Nimmt Pro-Frage-Timing-Dicts, berechnet Median + Ø je Phase (`rag_ms`, `ttft_ms`, `gen_ms`, `e2e_ms`). Keine I/O. Leere Liste → alle Werte 0.0. Unit-testbar.

- **`measure_one(question, studiengang, with_llm) -> dict`** (async):
  - `t0 = perf_counter()` → `build_rag_context(question, studiengang)` → `rag_ms`
  - wenn `with_llm`: Prompt wie in `chat.py` bauen (`build_prompt("text", "de")` + Anweisung + Kontext + Frage), dann `async for chunk in stream_gemini(prompt, 400, 0)`: erster Chunk → `ttft_ms`, letzter → `gen_ms`. `e2e_ms = rag_ms + gen_ms`.
  - ohne `with_llm`: `ttft_ms`/`gen_ms`/`e2e_ms` bleiben `None` bzw. `e2e_ms = rag_ms`.
  - gibt Timing-Dict zurück: `{"question", "studiengang", "rag_ms", "ttft_ms", "gen_ms", "e2e_ms"}`.

- **`run(with_llm) -> dict`** (async): lädt `eval_set.json`, iteriert, sammelt Records, ruft `_aggregate`, gibt `{"with_llm", "questions", "aggregate", "records"}` zurück.

- **`_print(summary)`**: Tabelle Median/Ø je Phase; bei `with_llm` zusätzlich Hinweis, welcher Anteil dominiert (Median `rag_ms` vs Median `gen_ms`).

- **`main()`**: argparse `--no-llm`, `--save <pfad>`. `asyncio.run(run(...))`.

### `tests/test_bench_latency.py` (neu)

Tests für `_aggregate`:
- Korrekte Median- und Ø-Berechnung mit festen Records.
- Leere Record-Liste → alle Phasen 0.0 (kein Crash).
- `None`-Phasen (z.B. `ttft_ms` bei `--no-llm`) werden bei der Aggregation ausgelassen, nicht als 0 gezählt.

## Datenfluss

```
eval_set.json → für jede Frage: measure_one(...) → record
records → _aggregate → summary → _print
optional: --save → summary als JSON (Baseline für Teilprojekt B)
```

## Erfolgskriterien

- `python scripts/bench_latency.py --no-llm` läuft offline, gibt `rag_ms` Median/Ø über 20 Fragen aus.
- `python scripts/bench_latency.py` (mit API-Key) gibt zusätzlich `ttft_ms`, `gen_ms`, `e2e_ms` und den dominierenden Anteil aus.
- `_aggregate` Unit-Tests PASS; bestehende Suite weiterhin PASS.
- Ergebnis liefert die Datenbasis, um in Teilprojekt B die größte Latenzquelle gezielt anzugehen.

## Außerhalb des Scope

- Die eigentliche Optimierung (Teilprojekt B) — eigener Spec→Plan-Zyklus auf Basis der hier gemessenen Daten.
- Änderungen an `app/rag.py`, `app/gemini.py`, `app/routes/*` (Messung ist rein additiv).
- RAG-Sub-Phasen-Instrumentierung (bereits in `[RAG-TIMING]`-Logs vorhanden).
- Neue Dependencies.
