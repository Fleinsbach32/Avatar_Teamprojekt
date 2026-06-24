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


async def measure_one(question: str, studiengang, with_llm: bool, model=None) -> dict:
    """Misst RAG-Zeit und (optional) Gemini-TTFT/Generierungszeit für eine Frage.
    `model` (optional) erzwingt ein bestimmtes Gemini-Modell für den Vergleich."""
    from app.rag import build_rag_context

    t0 = time.perf_counter()
    kontext, anweisung, _ = build_rag_context(question, studiengang)
    rag_ms = (time.perf_counter() - t0) * 1000

    ttft_ms = gen_ms = None
    e2e_ms = rag_ms
    ok = True
    answer = None
    if with_llm:
        from app.gemini import stream_gemini, GeminiUnavailable, GeminiMidStreamError
        from app.prompts import build_prompt

        prompt = f"""{build_prompt("text", "de")}

{anweisung}

Kontext:
{kontext}

Frage: {question}"""
        t1 = time.perf_counter()
        first = None
        parts: list[str] = []
        try:
            async for chunk in stream_gemini(prompt, 400, 0, model=model):
                if first is None:
                    first = time.perf_counter()
                parts.append(chunk)
        except (GeminiUnavailable, GeminiMidStreamError):
            # Gemini-Ausfall (z.B. 503): Frage als fehlgeschlagen vermerken,
            # Benchmark läuft weiter statt zu crashen.
            ok = False
        if ok:
            last = time.perf_counter()
            if first is not None:
                ttft_ms = (first - t1) * 1000
            gen_ms = (last - t1) * 1000
            e2e_ms = rag_ms + gen_ms
            answer = "".join(parts).strip()

    return {
        "question": question,
        "studiengang": studiengang,
        "ok": ok,
        "rag_ms": round(rag_ms, 1),
        "ttft_ms": round(ttft_ms, 1) if ttft_ms is not None else None,
        "gen_ms": round(gen_ms, 1) if gen_ms is not None else None,
        "e2e_ms": round(e2e_ms, 1),
        "answer": answer,
    }


async def run(with_llm: bool, model=None) -> dict:
    from dotenv import load_dotenv
    load_dotenv(PROJECT_ROOT / ".env")

    eval_set = json.loads(EVAL_SET_PATH.read_text(encoding="utf-8"))
    records = []
    for item in eval_set:
        rec = await measure_one(item["question"], item.get("studiengang"), with_llm, model=model)
        records.append(rec)
    return {
        "with_llm": with_llm,
        "model": model or "default (flash + flash-lite-Fallback)",
        "questions": len(records),
        "failed": sum(1 for r in records if not r.get("ok", True)),
        "aggregate": _aggregate(records),
        "records": records,
    }


def _print(summary: dict) -> None:
    agg = summary["aggregate"]
    mode = "RAG + Gemini" if summary["with_llm"] else "nur RAG (--no-llm)"
    print(f"\n{'='*64}")
    print(f"  Latenz-Benchmark — {summary['questions']} Fragen — {mode}")
    print(f"  Modell: {summary.get('model', 'default')}")
    failed = summary.get("failed", 0)
    if failed:
        print(f"  ⚠ {failed} Frage(n) fehlgeschlagen (Gemini-Ausfall, z.B. 503) — nicht in Median/Ø")
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


def _print_answers(summary: dict) -> None:
    print(f"\n{'-'*64}")
    print("  GENERIERTE ANTWORTEN")
    print(f"{'-'*64}")
    for r in summary["records"]:
        ans = (r.get("answer") or "—").replace("\n", " ")
        if len(ans) > 200:
            ans = ans[:200] + "…"
        print(f"\n  • {r['question']}")
        print(f"    {ans}")
    print()


def main() -> None:
    parser = argparse.ArgumentParser(description="KIRA Latenz-Benchmark")
    parser.add_argument("--no-llm", action="store_true", help="Nur RAG messen (offline)")
    parser.add_argument("--model", help="Gemini-Modell erzwingen (z.B. gemini-2.5-flash-lite)")
    parser.add_argument("--show-answers", action="store_true", help="Generierte Antworten ausgeben")
    parser.add_argument("--save", help="Ergebnis als JSON speichern")
    args = parser.parse_args()

    summary = asyncio.run(run(with_llm=not args.no_llm, model=args.model))
    _print(summary)
    if args.show_answers and not args.no_llm:
        _print_answers(summary)

    if args.save:
        Path(args.save).write_text(
            json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        print(f"  Gespeichert: {args.save}\n")


if __name__ == "__main__":
    main()
