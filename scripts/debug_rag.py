#!/usr/bin/env python3
"""Debug-Tool: Zeigt welche RAG-Chunks für eine Query abgerufen werden.

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

from dotenv import load_dotenv
load_dotenv(PROJECT_ROOT / ".env")

from app.rag import (
    _query_safe,
    _contains_variants,
    _module_name_from_what_is_question,
    _module_name_from_number_question,
    _merge_handbook_priority,
    _studiengang_where,
    STUDIENGANG_FILES,
    MODULE_ID_RE,
    reranker,
)


def _label(docs: list) -> str:
    return f"{len(docs)} Chunk(s)" if docs else "0 Chunks (LEER)"


def debug(query: str, studiengang: str | None = None) -> None:
    print(f"\nQuery      : {query!r}")
    print(f"Studiengang: {studiengang or '(kein)'}")
    print("-" * 64)

    where = _studiengang_where(studiengang)

    # Pfad 1: Modul-ID erkannt
    module_match = MODULE_ID_RE.search(query)
    if module_match:
        mid = module_match.group()
        print(f"Pfad: MODUL_ID  (id={mid!r})")
        r = _query_safe({"module_id": mid}, 3, query_texts=[query])
        docs = r["documents"][0]
        print(f"  Treffer: {_label(docs)}")
        for i, d in enumerate(docs):
            print(f"  [{i}] {d[:120]!r}")
        return

    # Pfad 2: "Modulnummer von X?"
    name_query = _module_name_from_number_question(query)
    if name_query:
        print(f"Pfad: MODULNUMMER_FRAGE  (name={name_query!r})")
        for variant in _contains_variants(name_query):
            r = _query_safe(where, 3, query_texts=[name_query],
                            where_document={"$contains": variant})
            n = len(r["documents"][0])
            print(f"  Variante {variant!r:40s} -> {n} Treffer")
            if n:
                print(f"    {r['documents'][0][0][:100]!r}")
        return

    # Pfad 3: "Was ist X?"
    what_is_name = _module_name_from_what_is_question(query)
    if what_is_name:
        print(f"Pfad: WAS_IST_MODULE  (name={what_is_name!r})")
        print(f"  where-Filter: {where}")
        found_variant = None
        for variant in _contains_variants(what_is_name):
            r = _query_safe(where, 3, query_texts=[what_is_name],
                            where_document={"$contains": variant})
            n = len(r["documents"][0])
            print(f"  Variante {variant!r:40s} -> {n} Treffer")
            if n and found_variant is None:
                found_variant = variant
                for d in r["documents"][0]:
                    print(f"    {d[:120]!r}")
        if found_variant is None:
            print("  -> Kein $contains-Treffer gefunden.")
            if studiengang and studiengang in STUDIENGANG_FILES:
                print("    Fallback: 'nicht in diesem Studiengang'-Antwort")
            else:
                print("    Fallback: Standard-Semantiksuche (kein Studiengang)")
        return

    # Pfad 4: Standard-Semantiksuche
    is_pflicht = any(
        kw in query.lower()
        for kw in ("pflichtmodul", "pflicht", "orientierungsprüfung", "orientierungspruefung")
    )
    print(f"Pfad: SEMANTIK  (is_pflicht={is_pflicht})")

    if studiengang and studiengang in STUDIENGANG_FILES:
        prog_n = 12 if is_pflicht else 8
        print(f"\n  [Stufe 1] program={studiengang!r}, n_results={prog_n}")
        prog_r = _query_safe({"program": studiengang}, prog_n, query_texts=[query])
        prog_docs = prog_r["documents"][0]
        prog_dists = prog_r["distances"][0]
        print(f"  -> {_label(prog_docs)}")
        if not prog_docs:
            print("  WARNING: LEER -- Filter greift nicht oder Metadaten prüfen!")

        print(f"\n  [Stufe 2] program='all', n_results=4")
        all_r = _query_safe({"program": "all"}, 4, query_texts=[query])
        all_docs = all_r["documents"][0]
        all_dists = all_r["distances"][0]
        print(f"  -> {_label(all_docs)}")

        print(f"\n  [_merge_handbook_priority] top_k=6, min_handbook=3 ...")
        docs = _merge_handbook_priority(prog_docs, all_docs, reranker, query, top_k=6, min_handbook=3)
        combined_dists = prog_dists + all_dists
        beste_distanz = min(combined_dists) if combined_dists else 1.0
        print(f"  -> Finaler Kontext: {_label(docs)}")
        print(f"  Beste Distanz: {beste_distanz:.3f}  ->  Quelle: "
              f"{'Wissensbasis' if beste_distanz < 0.45 else 'LLM'}")
    else:
        print(f"  [Einstufig] n_results=15")
        r = _query_safe(where, 15, query_texts=[query])
        docs = r["documents"][0]
        dists = r["distances"][0]
        beste_distanz = dists[0] if dists else 1.0
        print(f"  -> {_label(docs)}, Beste Distanz: {beste_distanz:.3f}")

    print(f"\n  Finaler Kontext ({len(docs)} Chunks):")
    for i, d in enumerate(docs):
        print(f"  [{i}] {d[:160]!r}")


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
