# Latenz-Messung Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Reproduzierbares Benchmark-Skript, das pro Frage RAG-Zeit, Gemini-TTFT und Generierungszeit misst und Median/Ø über die 20 Gold-Fragen ausgibt — Datenbasis für die spätere Optimierung (Teilprojekt B).

**Architecture:** Standalone-Skript `scripts/bench_latency.py` nach dem Muster von `eval_rag.py`. Black-Box-Timing um `build_rag_context` und `stream_gemini` — keine Änderung an `app/`-Code. Reine `_aggregate`-Funktion ist unit-getestet; die I/O-lastigen Mess-Funktionen werden manuell ausgeführt.

**Tech Stack:** Python 3.11, asyncio, time.perf_counter, statistics, pytest. Keine neue Dependency.

---

## Dateiübersicht

| Datei | Aktion | Verantwortung |
|---|---|---|
| `scripts/bench_latency.py` | Create | Timing-Messung + Aggregation + CLI |
| `tests/test_bench_latency.py` | Create | Unit-Test für reine `_aggregate`-Logik |

Reihenfolge: reine Aggregations-Funktion zuerst (TDD), dann die Mess-/CLI-Hülle drum herum.

---

### Task 1: `_aggregate` — reine Aggregations-Logik (TDD)

**Files:**
- Create: `scripts/bench_latency.py`
- Create: `tests/test_bench_latency.py`

- [ ] **Step 1: Failing Test schreiben**

`tests/test_bench_latency.py` erstellen:
```python
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import bench_latency  # noqa: E402


def test_aggregate_median_and_mean():
    records = [
        {"rag_ms": 100.0, "ttft_ms": 200.0, "gen_ms": 400.0, "e2e_ms": 500.0},
        {"rag_ms": 200.0, "ttft_ms": 400.0, "gen_ms": 600.0, "e2e_ms": 800.0},
        {"rag_ms": 300.0, "ttft_ms": 600.0, "gen_ms": 800.0, "e2e_ms": 1100.0},
    ]
    agg = bench_latency._aggregate(records)
    assert agg["rag_ms"]["median"] == 200.0
    assert agg["rag_ms"]["mean"] == 200.0
    assert agg["gen_ms"]["median"] == 600.0
    assert agg["e2e_ms"]["mean"] == 800.0


def test_aggregate_empty_is_zero():
    agg = bench_latency._aggregate([])
    for phase in ("rag_ms", "ttft_ms", "gen_ms", "e2e_ms"):
        assert agg[phase]["median"] == 0.0
        assert agg[phase]["mean"] == 0.0


def test_aggregate_skips_none_values():
    # --no-llm: ttft_ms/gen_ms/e2e_ms sind None und dürfen nicht als 0 zählen
    records = [
        {"rag_ms": 100.0, "ttft_ms": None, "gen_ms": None, "e2e_ms": 100.0},
        {"rag_ms": 300.0, "ttft_ms": None, "gen_ms": None, "e2e_ms": 300.0},
    ]
    agg = bench_latency._aggregate(records)
    assert agg["rag_ms"]["median"] == 200.0
    # Keine echten ttft-Werte → 0.0 (nicht durch None-Division crashen)
    assert agg["ttft_ms"]["median"] == 0.0
    assert agg["ttft_ms"]["mean"] == 0.0
```

- [ ] **Step 2: Test schlägt fehl**

Run: `python -m pytest tests/test_bench_latency.py -v`
Expected: FAIL (`ModuleNotFoundError: No module named 'bench_latency'`).

- [ ] **Step 3: `bench_latency.py` mit `_aggregate` anlegen**

`scripts/bench_latency.py` erstellen:
```python
#!/usr/bin/env python3
"""Latenz-Benchmark: misst RAG-Zeit, Gemini-TTFT und Generierungszeit über die
Gold-Fragen (data/eval_set.json). Datenbasis für die Latenz-Optimierung.

Aufruf:
    python scripts/bench_latency.py             # RAG + Gemini (braucht API-Key)
    python scripts/bench_latency.py --no-llm    # nur RAG (offline)
    python scripts/bench_latency.py --save bench_baseline.json
"""
import argparse
import asyncio
import json
import statistics
import sys
import time
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

EVAL_SET_PATH = PROJECT_ROOT / "data" / "eval_set.json"
PHASES = ("rag_ms", "ttft_ms", "gen_ms", "e2e_ms")


def _aggregate(records: list[dict]) -> dict:
    """Median + Ø je Phase. None-Werte (z.B. ttft bei --no-llm) werden
    ausgelassen; fehlen alle Werte einer Phase → 0.0."""
    agg: dict = {}
    for phase in PHASES:
        vals = [r[phase] for r in records if r.get(phase) is not None]
        if vals:
            agg[phase] = {
                "median": round(statistics.median(vals), 1),
                "mean": round(statistics.mean(vals), 1),
            }
        else:
            agg[phase] = {"median": 0.0, "mean": 0.0}
    return agg
```

- [ ] **Step 4: Test grün**

Run: `python -m pytest tests/test_bench_latency.py -v`
Expected: PASS (3 Tests).

- [ ] **Step 5: Commit**
```bash
git add scripts/bench_latency.py tests/test_bench_latency.py
git commit -m "feat(bench): _aggregate — Median/Ø-Aggregation für Latenz-Phasen"
```

---

### Task 2: Mess-Funktionen `measure_one` + `run`

**Files:**
- Modify: `scripts/bench_latency.py`

- [ ] **Step 1: `measure_one` + `run` ergänzen**

In `scripts/bench_latency.py` nach `_aggregate` einfügen:
```python
async def measure_one(question: str, studiengang, with_llm: bool) -> dict:
    """Misst RAG-Zeit und (optional) Gemini-TTFT/Generierungszeit für eine Frage."""
    from app.rag import build_rag_context

    t0 = time.perf_counter()
    kontext, anweisung, _ = build_rag_context(question, studiengang)
    rag_ms = (time.perf_counter() - t0) * 1000

    ttft_ms = gen_ms = None
    e2e_ms = rag_ms
    if with_llm:
        from app.gemini import stream_gemini
        from app.prompts import build_prompt

        prompt = f"""{build_prompt("text", "de")}

{anweisung}

Kontext:
{kontext}

Frage: {question}"""
        t1 = time.perf_counter()
        first = None
        async for chunk in stream_gemini(prompt, 400, 0):
            if first is None:
                first = time.perf_counter()
            _ = chunk
        last = time.perf_counter()
        if first is not None:
            ttft_ms = (first - t1) * 1000
        gen_ms = (last - t1) * 1000
        e2e_ms = rag_ms + gen_ms

    return {
        "question": question,
        "studiengang": studiengang,
        "rag_ms": round(rag_ms, 1),
        "ttft_ms": round(ttft_ms, 1) if ttft_ms is not None else None,
        "gen_ms": round(gen_ms, 1) if gen_ms is not None else None,
        "e2e_ms": round(e2e_ms, 1),
    }


async def run(with_llm: bool) -> dict:
    from dotenv import load_dotenv
    load_dotenv(PROJECT_ROOT / ".env")

    eval_set = json.loads(EVAL_SET_PATH.read_text(encoding="utf-8"))
    records = []
    for item in eval_set:
        rec = await measure_one(item["question"], item.get("studiengang"), with_llm)
        records.append(rec)
    return {
        "with_llm": with_llm,
        "questions": len(records),
        "aggregate": _aggregate(records),
        "records": records,
    }
```

- [ ] **Step 2: Import-Check (Syntax + Modul lädt)**

Run: `python -c "import sys; sys.path.insert(0, 'scripts'); import bench_latency; print('ok')"`
Expected: `ok`.

- [ ] **Step 3: Aggregations-Tests weiterhin grün**

Run: `python -m pytest tests/test_bench_latency.py -v`
Expected: PASS (Funktionssignatur von `_aggregate` unverändert).

- [ ] **Step 4: Commit**
```bash
git add scripts/bench_latency.py
git commit -m "feat(bench): measure_one + run — RAG-/Gemini-Timing pro Frage"
```

---

### Task 3: Ausgabe + CLI

**Files:**
- Modify: `scripts/bench_latency.py`

- [ ] **Step 1: `_print` + `main` ergänzen**

In `scripts/bench_latency.py` ans Ende anfügen:
```python
def _print(summary: dict) -> None:
    agg = summary["aggregate"]
    mode = "RAG + Gemini" if summary["with_llm"] else "nur RAG (--no-llm)"
    print(f"\n{'='*64}")
    print(f"  Latenz-Benchmark — {summary['questions']} Fragen — {mode}")
    print(f"{'='*64}")
    print(f"  {'Phase':<10}  {'Median':>10}  {'Ø':>10}")
    for phase in PHASES:
        print(f"  {phase:<10}  {agg[phase]['median']:>9.1f}ms  {agg[phase]['mean']:>9.1f}ms")
    if summary["with_llm"]:
        rag = agg["rag_ms"]["median"]
        gen = agg["gen_ms"]["median"]
        dominant = "RAG" if rag > gen else "Gemini-Generierung"
        print(f"\n  Dominanter Anteil (Median): {dominant}  "
              f"(RAG {rag:.0f}ms vs Generierung {gen:.0f}ms)")
    print()


def main() -> None:
    parser = argparse.ArgumentParser(description="KIRA Latenz-Benchmark")
    parser.add_argument("--no-llm", action="store_true", help="Nur RAG messen (offline)")
    parser.add_argument("--save", help="Ergebnis als JSON speichern")
    args = parser.parse_args()

    summary = asyncio.run(run(with_llm=not args.no_llm))
    _print(summary)

    if args.save:
        Path(args.save).write_text(
            json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        print(f"  Gespeichert: {args.save}\n")


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: Import-Check**

Run: `python -c "import sys; sys.path.insert(0, 'scripts'); import bench_latency; print('ok')"`
Expected: `ok`.

- [ ] **Step 3: Offline-Smoke-Run (nur RAG, kein API-Key nötig)**

Run: `python scripts/bench_latency.py --no-llm`
Expected: Tabelle mit `rag_ms` Median/Ø über 20 Fragen; `ttft_ms`/`gen_ms`/`e2e_ms` zeigen für `ttft`/`gen` 0.0 (None ausgelassen), `e2e_ms` = `rag_ms`. Kein Crash.

- [ ] **Step 4: Volle Test-Suite**

Run: `python -m pytest tests/ -q`
Expected: alle PASS (bestehende + 3 neue bench-Tests).

- [ ] **Step 5: Commit**
```bash
git add scripts/bench_latency.py
git commit -m "feat(bench): _print + CLI (--no-llm, --save)"
```

---

### Task 4: Baseline messen + Abschluss

**Files:** keine Änderung — Ausführung/Verifikation.

- [ ] **Step 1: Offline-RAG-Baseline**

Run: `python scripts/bench_latency.py --no-llm --save bench_rag_baseline.json`
Erwartet: `rag_ms`-Verteilung über die 20 Fragen. (`bench_rag_baseline.json` liegt im Root, bewusst NICHT committen — nur lokal.)

- [ ] **Step 2 (mit API-Key): Voll-Baseline**

Run: `python scripts/bench_latency.py --save bench_baseline.json`
Erwartet: `rag_ms`, `ttft_ms`, `gen_ms`, `e2e_ms` + dominanter Anteil. Das ist die Datenbasis für Teilprojekt B (Optimierung).

- [ ] **Step 3: Ergebnis festhalten**

Den dominanten Anteil notieren (RAG vs Gemini-Generierung) — er bestimmt, welche Optimierung in Teilprojekt B priorisiert wird.

---

## Self-Review-Notiz

Abgedeckt: `_aggregate` (T1, mit None-Handling + Leerliste), `measure_one`/`run` (T2), `_print`/CLI inkl. `--no-llm`/`--save` (T3), Baseline-Messung (T4). Phasennamen konsistent (`rag_ms`, `ttft_ms`, `gen_ms`, `e2e_ms`) in Spec, Tests und Code. Prompt-Aufbau spiegelt `chat.py`. Keine App-Änderung, keine Platzhalter.
