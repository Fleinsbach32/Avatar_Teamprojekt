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
