#!/usr/bin/env python3
"""DB inspection — Encoding-Check und Modul-Suche."""
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

import chromadb
from chromadb.utils import embedding_functions

ef = embedding_functions.SentenceTransformerEmbeddingFunction(
    model_name="paraphrase-multilingual-MiniLM-L12-v2"
)
client = chromadb.PersistentClient(path=str(PROJECT_ROOT / "data" / "chroma_db"))
col = client.get_collection("uni_beratung", embedding_function=ef)

print(f"Gesamt: {col.count()} Eintraege\n")

# 1. Alle wing_bsc module_names (unique) - zeige was wirklich gespeichert ist
r_all = col.get(where={"program": "wing_bsc"}, limit=500, include=["metadatas"])
names = {}
for meta in r_all["metadatas"]:
    mid = meta.get("module_id")
    name = meta.get("module_name", "?")
    if mid and mid not in names:
        names[mid] = name
print(f"=== WING BSc: {len(names)} eindeutige Module ===")
for mid, name in sorted(names.items(), key=lambda x: x[1]):
    # Zeige name als repr um encoding-issues sichtbar zu machen
    if any(ord(c) > 127 for c in name):
        print(f"  {mid}  {name!r}  ← Sonderzeichen")
    else:
        print(f"  {mid}  {name}")
print()

# 2. Suche "Buchf" (erster Teil, unabhaengig von Umlaut-Encoding)
print("=== Suche nach Modulen mit 'buchf' im Namen (case-insensitive) ===")
for mid, name in names.items():
    if "buchf" in name.lower() or "buchf" in name.encode("ascii", "replace").decode().lower():
        print(f"  {mid}  {name!r}")
print()

# 3. Semantic search fuer Buchfuehrung - OHNE program filter
try:
    r_nf = col.query(
        query_texts=["Buchführung und Abschluss Rechnungswesen"],
        n_results=5,
        include=["documents", "metadatas", "distances"],
    )
    print("=== Global semantic: 'Buchführung' (kein Filter) ===")
    for doc, meta, dist in zip(r_nf["documents"][0], r_nf["metadatas"][0], r_nf["distances"][0]):
        print(f"  dist={dist:.3f}  program={meta.get('program')}  name={meta.get('module_name')!r}")
        print(f"  {doc[:180]!r}")
        print()
except Exception as e:
    print(f"  FEHLER: {e}")
print()

# 4. Semantic search mit wing_bsc filter
try:
    r_wing = col.query(
        query_texts=["Buchführung und Abschluss"],
        where={"program": "wing_bsc"},
        n_results=4,
        include=["documents", "metadatas", "distances"],
    )
    docs = r_wing["documents"][0]
    print(f"=== WING BSc semantic 'Buchführung' → {len(docs)} Ergebnisse ===")
    for doc, meta, dist in zip(docs, r_wing["metadatas"][0], r_wing["distances"][0]):
        print(f"  dist={dist:.3f}  name={meta.get('module_name')!r}")
        print(f"  {doc[:180]!r}")
        print()
except Exception as e:
    print(f"  FEHLER: {e}")
print()

# 5. Pflichtmodule - zeige mehr Chunks
try:
    r_pf = col.query(
        query_texts=["Pflichtmodule Liste Bachelorstudium Wirtschaftsingenieurwesen Orientierungspruefung"],
        where={"program": "wing_bsc"},
        n_results=8,
        include=["documents", "metadatas", "distances"],
    )
    print(f"=== WING BSc Pflichtmodule (n=8) ===")
    for doc, meta, dist in zip(r_pf["documents"][0], r_pf["metadatas"][0], r_pf["distances"][0]):
        print(f"  dist={dist:.3f}  name={meta.get('module_name')}")
        print(f"  {doc[:120]!r}")
        print()
except Exception as e:
    print(f"  FEHLER: {e}")
