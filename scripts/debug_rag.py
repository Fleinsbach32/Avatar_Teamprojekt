#!/usr/bin/env python3
"""Debug-Tool: Zeigt den von build_rag_context erzeugten RAG-Kontext für eine Query.

Ruft direkt die echte RAG-Pipeline auf (kein Logik-Duplikat → bleibt immer aktuell).

Verwendung:
    python scripts/debug_rag.py "Was ist Introduction to Digital Economics?" --studiengang digieco_bsc
    python scripts/debug_rag.py "Welche Pflichtmodule hat WING?" --studiengang wing_bsc
    python scripts/debug_rag.py "Wie bewerbe ich mich?"
"""
import argparse
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from dotenv import load_dotenv
load_dotenv(PROJECT_ROOT / ".env")

from app.rag import build_rag_context, STUDIENGANG_FILES


def debug(query: str, studiengang: str | None = None) -> None:
    print(f"\nQuery      : {query!r}")
    print(f"Studiengang: {studiengang or '(kein)'}")
    print("-" * 64)

    kontext, anweisung, distanz = build_rag_context(query, studiengang)

    chunks = kontext.split("\n\n") if kontext else []
    quelle = "Wissensbasis" if distanz < 0.45 else "LLM"
    print(f"Beste Distanz: {distanz:.3f}   ->   Quelle: {quelle}")
    print(f"Kontext-Chunks: {len(chunks)}")
    print(f"\nAnweisung an das LLM:\n  {anweisung}\n")
    print(f"Kontext ({len(chunks)} Chunks):")
    if not chunks:
        print("  (leer)")
    for i, c in enumerate(chunks):
        print(f"  [{i}] {c[:200]!r}")


def main() -> None:
    parser = argparse.ArgumentParser(description="KIRA RAG Debug Tool")
    parser.add_argument("query", help="Die Testfrage")
    parser.add_argument(
        "--studiengang",
        default=None,
        help=f"Studiengang-Key (z.B. wing_bsc). Gültig: {', '.join(STUDIENGANG_FILES)}",
    )
    args = parser.parse_args()

    if args.studiengang and args.studiengang not in STUDIENGANG_FILES:
        print(f"Fehler: Unbekannter Studiengang {args.studiengang!r}")
        print(f"Gültige Keys: {', '.join(STUDIENGANG_FILES)}")
        sys.exit(1)

    debug(args.query, args.studiengang)


if __name__ == "__main__":
    main()
