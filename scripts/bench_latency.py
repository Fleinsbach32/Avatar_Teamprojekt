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
