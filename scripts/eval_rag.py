#!/usr/bin/env python3
"""Offline-Retrieval-Eval: prüft, ob erwartete Fakten im von build_rag_context
abgerufenen Kontext stehen. Kein Server/LLM nötig — misst Retrieval-Grounding.

Aufruf:
    python scripts/eval_rag.py
    python scripts/eval_rag.py --save baseline.json
    python scripts/eval_rag.py --compare baseline.json
"""
import argparse
import json
import re
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

EVAL_SET_PATH = PROJECT_ROOT / "data" / "eval_set.json"


def _norm(text: str) -> str:
    """Klein + Whitespace kollabiert — für robustes Substring-Matching."""
    return re.sub(r"\s+", " ", text.lower()).strip()


def _facts_present(facts: list[str], kontext: str) -> tuple[int, int]:
    """Gibt (gefundene_Fakten, gesamt) zurück (normalisierter Substring-Match)."""
    nk = _norm(kontext)
    hits = sum(1 for f in facts if _norm(f) in nk)
    return hits, len(facts)


def run() -> dict:
    from dotenv import load_dotenv
    load_dotenv(PROJECT_ROOT / ".env")
    from app.rag import build_rag_context

    eval_set = json.loads(EVAL_SET_PATH.read_text(encoding="utf-8"))
    results = []
    fact_hits = fact_total = passed = 0
    for item in eval_set:
        kontext, _, distanz = build_rag_context(item["question"], item.get("studiengang"))
        hits, total = _facts_present(item["expected_facts"], kontext)
        ok = hits == total
        fact_hits += hits
        fact_total += total
        passed += int(ok)
        results.append({
            "question": item["question"],
            "studiengang": item.get("studiengang"),
            "hits": hits, "total": total, "passed": ok,
            "distanz": round(distanz, 3),
        })
    summary = {
        "questions": len(eval_set),
        "passed": passed,
        "fact_recall": round(fact_hits / fact_total, 3) if fact_total else 0.0,
        "results": results,
    }
    return summary


def _print(summary: dict) -> None:
    print(f"\n{'='*64}")
    print(f"  RAG-Eval — {summary['passed']}/{summary['questions']} Fragen bestanden, "
          f"Fakt-Recall {summary['fact_recall']:.1%}")
    print(f"{'='*64}")
    for r in summary["results"]:
        mark = "OK " if r["passed"] else "XX "
        sg = r["studiengang"] or "-"
        print(f"  [{mark}] {r['hits']}/{r['total']}  d={r['distanz']:.2f}  [{sg}]  {r['question']}")
    print()


def main() -> None:
    parser = argparse.ArgumentParser(description="KIRA RAG-Eval (offline)")
    parser.add_argument("--save", help="Ergebnis als JSON-Baseline speichern")
    parser.add_argument("--compare", help="Mit gespeicherter Baseline vergleichen")
    args = parser.parse_args()

    summary = run()
    _print(summary)

    if args.compare:
        base = json.loads(Path(args.compare).read_text(encoding="utf-8"))
        d_pass = summary["passed"] - base["passed"]
        d_recall = summary["fact_recall"] - base["fact_recall"]
        print(f"  Δ bestanden: {d_pass:+d}   Δ Fakt-Recall: {d_recall:+.1%}\n")
    if args.save:
        Path(args.save).write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"  Baseline gespeichert: {args.save}\n")


if __name__ == "__main__":
    main()
