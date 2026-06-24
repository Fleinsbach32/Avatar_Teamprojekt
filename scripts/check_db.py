#!/usr/bin/env python3
"""
DB-Status-Check — zeigt wie viele Einträge in der ChromaDB liegen und von welchem Typ.

Aufruf:
    python scripts/check_db.py

Kein Server nötig. Schnell: lädt KEIN Embedding-Modell.
"""
import argparse
import statistics
import sys
from collections import Counter, defaultdict
from pathlib import Path
from urllib.parse import urlparse

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

import chromadb

DEFAULT_CHROMA_PATH = str(PROJECT_ROOT / "chroma_db")

PROGRAM_LABELS = {
    "wing_bsc":    "WI+NG BSc  (Wirtschaftsingenieurwesen)",
    "winfo_bsc":   "WInf BSc   (Wirtschaftsinformatik)",
    "digieco_bsc": "DigiEco BSc(Digital Economics)",
    "wing_msc":    "WI+NG MSc",
    "ieam_msc":    "IEAM MSc   (Industrial Eng.)",
    "winfo_msc":   "WInf MSc   (Wirtschaftsinformatik)",
    "wima_msc":    "WiMa MSc   (Wirtschaftsmathematik)",
    "digieco_msc": "DigiEco MSc",
    "tvwl_bsc":    "TVWL BSc",
    "tvwl_msc":    "TVWL MSc",
    "all":         "Allgemein  (FAQ / Web / Info)",
}

DOC_TYPE_LABELS = {
    "faq":      "FAQ-Eintraege",
    "handbook": "Modulhandbuch-Chunks",
    "info":     "Info-PDF-Chunks",
    "webpage":  "Webcrawl-Chunks",
}

EXPECTED_PROGRAMS = ["wing_bsc", "winfo_bsc", "digieco_bsc", "wing_msc", "winfo_msc"]


def line(char="-", width=64):
    print(char * width)


def load_all_metadatas(col) -> list[dict]:
    """Lädt alle Metadaten in Batches (ohne Embedding-Modell, nur Metadaten)."""
    result = []
    batch_size = 5000
    offset = 0
    while True:
        batch = col.get(limit=batch_size, offset=offset, include=["metadatas"])
        fetched = batch.get("metadatas") or []
        if not fetched:
            break
        result.extend(fetched)
        offset += len(fetched)
        if len(fetched) < batch_size:
            break
    return result


def hygiene_report(col) -> None:
    """Streamt alle Dokumente und meldet Datenhygiene: U+FFFD-Quote,
    Duplikatrate (per Inhalts-Hash), Chunk-Längen."""
    import hashlib
    batch_size = 5000
    offset = 0
    total = 0
    fffd_chunks = 0
    short_chunks = 0
    lengths: list[int] = []
    seen: dict[str, int] = {}
    while True:
        batch = col.get(limit=batch_size, offset=offset, include=["documents"])
        docs = batch.get("documents") or []
        if not docs:
            break
        for doc in docs:
            doc = doc or ""
            total += 1
            if "�" in doc:
                fffd_chunks += 1
            n_words = len(doc.split())
            lengths.append(n_words)
            if n_words < 8:
                short_chunks += 1
            h = hashlib.md5(doc.strip().lower().encode("utf-8")).hexdigest()
            seen[h] = seen.get(h, 0) + 1
        offset += len(docs)
        if len(docs) < batch_size:
            break

    if total == 0:
        return
    duplicates = sum(c - 1 for c in seen.values() if c > 1)
    line()
    print("  HYGIENE")
    line()
    print(f"  Chunks mit U+FFFD:   {fffd_chunks:>7,}  ({fffd_chunks / total:.1%})")
    print(f"  Duplikat-Chunks:     {duplicates:>7,}  ({duplicates / total:.1%})")
    print(f"  Sehr kurze (<8 W.):  {short_chunks:>7,}  ({short_chunks / total:.1%})")
    print(f"  Chunk-Länge Wörter:  Ø {statistics.mean(lengths):.0f}  |  Median {statistics.median(lengths):.0f}")
    print()


def main():
    parser = argparse.ArgumentParser(description="ChromaDB Status-Check")
    parser.add_argument(
        "--path",
        default=DEFAULT_CHROMA_PATH,
        help=f"Pfad zur ChromaDB (Standard: {DEFAULT_CHROMA_PATH})",
    )
    args = parser.parse_args()
    chroma_path = args.path

    # --- Verbindung ---
    try:
        client = chromadb.PersistentClient(path=chroma_path)
        col = client.get_collection("uni_beratung")
    except Exception as e:
        print(f"\n[FEHLER] ChromaDB nicht gefunden oder Collection fehlt: {e}")
        print(f"  Pfad:   {chroma_path}")
        print("  Lösung: python scripts/fill_db.py ausfuehren.\n")
        sys.exit(1)

    total = col.count()

    line("=")
    print("  ChromaDB — Datenbankstatus")
    print(f"  Pfad: {chroma_path}")
    line("=")
    print(f"\n  Eintraege gesamt: {total:>8,}\n")

    if total == 0:
        print("  [!] Datenbank ist leer — bitte fill_db.py ausfuehren.\n")
        return

    # --- Metadaten laden ---
    print("  Lade Metadaten ...", end="", flush=True)
    all_meta = load_all_metadatas(col)
    print(f" {len(all_meta):,} geladen\n")

    # --- Gruppieren ---
    by_type: dict[str, list] = defaultdict(list)
    by_program: dict[str, list] = defaultdict(list)
    for m in all_meta:
        by_type[m.get("doc_type", "?")].append(m)
        by_program[m.get("program", "?")].append(m)

    # ── Typ-Übersicht ────────────────────────────────────────────
    line()
    print("  NACH TYP")
    line()
    bar_max = 35
    for dtype, metas in sorted(by_type.items(), key=lambda x: -len(x[1])):
        label = DOC_TYPE_LABELS.get(dtype, dtype)
        pct   = len(metas) / total
        bar   = "#" * round(pct * bar_max)
        print(f"  {label:<25}  {len(metas):>8,}  {pct:>5.1%}  {bar}")
    print()

    # ── Studiengang-Übersicht ────────────────────────────────────
    line()
    print("  NACH STUDIENGANG  (Handbuch-Programme + Allgemein)")
    line()
    known_order = list(PROGRAM_LABELS.keys())
    extra       = [p for p in by_program if p not in PROGRAM_LABELS]
    for prog in known_order + extra:
        metas = by_program.get(prog)
        if not metas:
            continue
        label   = PROGRAM_LABELS.get(prog, prog)
        hb_meta = [m for m in metas if m.get("doc_type") == "handbook"]
        n_mods  = len({m.get("module_id") for m in hb_meta if m.get("module_id")})
        mod_str = f"  [{n_mods} eindeutige Module]" if n_mods else ""
        print(f"  {label:<36}  {len(metas):>7,}{mod_str}")
    print()

    # ── FAQ: Sprachen ────────────────────────────────────────────
    faq_meta = by_type.get("faq", [])
    if faq_meta:
        line()
        print("  FAQ — SPRACHAUFTEILUNG")
        line()
        for lang, cnt in sorted(Counter(m.get("language", "?") for m in faq_meta).items()):
            label = {"de": "Deutsch", "en": "Englisch"}.get(lang, lang)
            print(f"  {label:<12}  {cnt:>6,}")
        print()

    # ── Webcrawl: Domains ────────────────────────────────────────
    web_meta = by_type.get("webpage", [])
    if web_meta:
        line()
        print("  WEBCRAWL — QUELLEN")
        line()
        unique_urls = {m.get("source", "") for m in web_meta}
        domains: Counter = Counter()
        for url in unique_urls:
            try:
                domains[urlparse(url).netloc] += 1
            except Exception:
                domains["?"] += 1
        print(f"  Unique URLs:     {len(unique_urls):>7,}")
        print(f"  Chunks gesamt:   {len(web_meta):>7,}")
        print(f"  Domains ({len(domains)}):")
        for domain, cnt in domains.most_common():
            print(f"    {domain:<40}  {cnt:>5,} Seiten")
        print()

    # ── Sanity Checks ────────────────────────────────────────────
    line()
    print("  SANITY CHECKS")
    line()
    all_ok = True
    for prog in EXPECTED_PROGRAMS:
        cnt    = len(by_program.get(prog, []))
        status = "OK    " if cnt > 0 else "FEHLT!"
        if cnt == 0:
            all_ok = False
        print(f"  [{status}]  {prog:<15}  {cnt:>7,} Chunks")

    faq_cnt = len(faq_meta)
    faq_ok  = faq_cnt > 0
    if not faq_ok:
        all_ok = False
    print(f"  [{'OK    ' if faq_ok else 'FEHLT!'}]  {'FAQ':<15}  {faq_cnt:>7,} Eintraege")

    print()
    if all_ok:
        print("  Alle Checks bestanden.")
    else:
        print("  WARNUNG: Daten fehlen — fill_db.py erneut ausfuehren.")

    hygiene_report(col)
    line("=")
    typen_str = " + ".join(
        f"{len(v):,} {DOC_TYPE_LABELS.get(k, k)}"
        for k, v in sorted(by_type.items(), key=lambda x: -len(x[1]))
    )
    print(f"  Gesamt: {total:,}  |  {len(by_type)} Typen  |  {len(by_program)} Programme")
    print(f"  {typen_str}")
    line("=")
    print()


if __name__ == "__main__":
    main()
