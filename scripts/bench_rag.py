#!/usr/bin/env python3
"""
Latenz-Benchmark für build_rag_context — misst pro Query-Typ die Laufzeit
mit und ohne CrossEncoder-Reranker.

Aufruf (Server NICHT nötig, nutzt app.rag direkt):
    python scripts/bench_rag.py
    python scripts/bench_rag.py --runs 5
"""
import argparse
import sys
import time
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import app.rag as rag

# (Beschreibung, Query, Studiengang)
QUERIES = [
    ("Allgemein, kein Filter",      "Wie melde ich mich für Prüfungen an?", None),
    ("Allgemein, mit Filter",       "Welche Module gibt es?",               "winfo_bsc"),
    ("Pflichtmodule, mit Filter",   "Welche Pflichtmodule hat der Bachelor?", "wing_bsc"),
    ("Modul-ID",                    "Was ist M-WIWI-101430?",               "winfo_bsc"),
    ("Was ist Modul X",             "Was ist das Modul Controlling?",       "wing_bsc"),
]


def bench(runs: int) -> None:
    original = rag.reranker
    for label, with_reranker in (("MIT Reranker", True), ("OHNE Reranker", False)):
        rag.reranker = original if with_reranker else None
        print(f"\n=== {label} ===")
        for desc, query, sg in QUERIES:
            # Aufwärmen (Embedding-Cache)
            rag.build_rag_context(query, sg)
            t0 = time.perf_counter()
            for _ in range(runs):
                rag.build_rag_context(query, sg)
            ms = (time.perf_counter() - t0) / runs * 1000
            print(f"  {desc:<28} {ms:7.1f} ms/Query  [{sg or 'kein SG'}]")
    rag.reranker = original


def main() -> None:
    parser = argparse.ArgumentParser(description="RAG Latenz-Benchmark")
    parser.add_argument("--runs", type=int, default=3, help="Läufe pro Query (Default 3)")
    args = parser.parse_args()
    print(f"Reranker geladen: {rag.reranker is not None}")
    bench(args.runs)


if __name__ == "__main__":
    main()
