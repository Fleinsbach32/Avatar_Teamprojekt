import os
import re
import json
from pathlib import Path

import chromadb
from pypdf import PdfReader
from chromadb.utils import embedding_functions

# Projekt-Root (eine Ebene über scripts/) — alle Pfade beziehen sich darauf,
# damit das Skript unabhängig vom Arbeitsverzeichnis läuft.
PROJECT_ROOT = Path(__file__).resolve().parent.parent

CHROMA_PATH = str(PROJECT_ROOT / "data" / "chroma_db")
CRAWLED_DATA_FOLDER = PROJECT_ROOT / "crawled_data"
FAQ_FILES = [
    (PROJECT_ROOT / "data" / "faq_de.json",  "de"),
    (PROJECT_ROOT / "data" / "faq_eng.json", "en"),
]
PDF_FOLDER = PROJECT_ROOT / "data" / "pdfs"

# Modulhandbuch-Dateiname -> Studiengang-Schlüssel (program-Metadatum).
# Deckt auch TVWL ab (nicht im UI) -> erscheint nur bei ungefilterter Suche.
HANDBOOK_PROGRAM = {
    "mhb_wiing_BSc_de_aktuell.pdf": "wing_bsc",
    "mhb_wiinf_BSc_de_aktuell.pdf": "winfo_bsc",
    "mhb_de_BSc_de_aktuell.pdf":    "digieco_bsc",
    "mhb_wiing_MSc_de_aktuell.pdf": "wing_msc",
    "mhb_ieam_MSc_en_aktuell.pdf":  "ieam_msc",
    "mhb_wiinf_MSc_de_aktuell.pdf": "winfo_msc",
    "mhb_wima_MSc_de_aktuell.pdf":  "wima_msc",
    "mhb_de_MSc_en_aktuell.pdf":    "digieco_msc",
    "mhb_tvwl_BSc_de_aktuell.pdf":  "tvwl_bsc",   # nicht im UI
    "mhb_tvwl_MSc_de_aktuell.pdf":  "tvwl_msc",   # nicht im UI
}

# Anker einer Modul-Detailsektion: "Modul: <Name> [M-WIWI-105610]" bzw.
# englisch "Module: <Name> [...]". ID-Form M- (Modul) und T- (Teilleistung).
MODULE_ANCHOR_RE = re.compile(r'Modul[e]?:\s*([^\[\n]+?)\s*\[([MT]-[A-Z]+-\d+)\]')


def chunk_text(text, chunk_size=400, overlap=50):
    """Einfaches Zeichen-Chunking (für Nicht-Handbuch-PDFs)."""
    chunks = []
    start = 0
    while start < len(text):
        end = start + chunk_size
        chunks.append(text[start:end])
        start += chunk_size - overlap
    return chunks


def chunk_handbook(text, max_chars=1500, min_chars=50):
    """Segmentiert ein Modulhandbuch modulweise am Anker 'Modul: <Name> [ID]'.

    Aufeinanderfolgende Segmente mit gleicher ID (wiederholte Seitenköpfe)
    werden zusammengefasst. Jeder zurückgegebene Chunk beginnt mit einem
    normalisierten Header 'Modul: <Name> [<ID>]', sodass Name und ID immer
    am Chunk hängen. Überlange Modulblöcke werden mit Header-Präfix nachgeteilt.

    Liefert: Liste von (chunk_text, module_id, module_name).
    Leere Liste, wenn kein Modul-Anker gefunden wird (Aufrufer fällt dann auf
    chunk_text zurück).
    """
    matches = list(MODULE_ANCHOR_RE.finditer(text))
    if not matches:
        return []

    # Rohsegmente zwischen aufeinanderfolgenden Ankern
    raw = []
    for i, m in enumerate(matches):
        start = m.start()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
        raw.append((m.group(2), m.group(1).strip(), text[start:end]))

    # aufeinanderfolgende gleiche ID zusammenfassen
    merged = []
    for mid, name, seg in raw:
        if merged and merged[-1][0] == mid:
            merged[-1] = (mid, merged[-1][1], merged[-1][2] + "\n" + seg)
        else:
            merged.append((mid, name, seg))

    out = []
    for mid, name, seg in merged:
        header = f"Modul: {name} [{mid}]\n"
        body = re.sub(r"[ \t]+", " ", seg).strip()
        if len(header) + len(body) <= max_chars:
            out.append((header + body, mid, name))
        else:
            step = max(1, max_chars - len(header))
            for s in range(0, len(body), step):
                out.append((header + body[s:s + step], mid, name))

    return [(c, mid, name) for (c, mid, name) in out if len(c.strip()) >= min_chars]


def load_faqs(documents, ids, metadatas, counter):
    """Lädt FAQ-Dateien (de/en); überspringt leere/ungültige. Gibt (counter, faq_total) zurück."""
    faq_total = 0
    for faq_path, lang in FAQ_FILES:
        if not faq_path.exists():
            print(f"[FAQ] {faq_path.name} fehlt - uebersprungen")
            continue
        try:
            with open(faq_path, encoding="utf-8") as f:
                faqs = json.load(f)
        except (json.JSONDecodeError, ValueError):
            print(f"[FAQ] {faq_path.name} ist leer/ungueltig - uebersprungen")
            continue
        for item in faqs:
            documents.append(f"Frage: {item['question']}\nAntwort: {item['answer']}")
            ids.append(f"faq_{counter}")
            metadatas.append({"source": "faq", "doc_type": "faq", "program": "all",
                              "language": lang, "question": item["question"]})
            counter += 1
            faq_total += 1
        print(f"[FAQ] {faq_path.name}: {len(faqs)} Eintraege geladen ({lang})")
    print(f"[FAQ] {faq_total} FAQ-Eintraege gesamt")
    return counter, faq_total


def load_pdfs(documents, ids, metadatas, counter):
    """Lädt alle PDFs: Handbücher modulweise, sonstige als Info. Gibt (counter, chunk_count) zurück."""
    chunk_count = 0
    for filename in sorted(os.listdir(PDF_FOLDER)):
        if not filename.endswith(".pdf"):
            continue
        reader = PdfReader(os.path.join(PDF_FOLDER, filename))
        full_text = "".join((page.extract_text() or "") + "\n" for page in reader.pages)

        program = HANDBOOK_PROGRAM.get(filename)
        added = 0
        if program:
            module_chunks = chunk_handbook(full_text)
            if module_chunks:
                for chunk, module_id, module_name in module_chunks:
                    documents.append(chunk)
                    ids.append(f"pdf_{counter}")
                    metadatas.append({
                        "source": filename, "doc_type": "handbook", "program": program,
                        "module_id": module_id, "module_name": module_name,
                    })
                    counter += 1
                    added += 1
                print(f"[MHB] {filename}: {added} Modul-Chunks ({program})")
            else:
                # Kein Modul-Anker gefunden -> als Info behandeln
                program = None

        if not program:
            for chunk in chunk_text(full_text):
                if len(chunk.strip()) < 50:
                    continue
                documents.append(chunk)
                ids.append(f"pdf_{counter}")
                metadatas.append({"source": filename, "doc_type": "info", "program": "all"})
                counter += 1
                added += 1
            print(f"[PDF] {filename}: {added} Info-Chunks")

        chunk_count += added
    return counter, chunk_count


def load_crawled_data(documents, ids, metadatas, counter):
    """Lädt gecrawlte Webseiten aus crawled_data/. Gibt (counter, page_count) zurück."""
    if not CRAWLED_DATA_FOLDER.exists():
        print("[WEB] crawled_data/ Ordner nicht gefunden - übersprungen")
        return counter, 0

    files = sorted(f for f in os.listdir(CRAWLED_DATA_FOLDER)
                   if f.endswith(".json") and f != "module_ratings.json")
    page_count = 0
    chunk_count = 0

    for fn in files:
        try:
            with open(CRAWLED_DATA_FOLDER / fn, encoding="utf-8") as f:
                data = json.load(f)
        except (json.JSONDecodeError, ValueError):
            continue

        text = data.get("extracted_text", "").strip()
        if len(text) < 100:
            continue

        url = data.get("url", fn)
        title = data.get("page_title", "")
        lang = data.get("metadata", {}).get("language", "de")
        header = f"{title}\n{url}\n\n" if title else f"{url}\n\n"

        added = 0
        for chunk in chunk_text(text, chunk_size=600, overlap=80):
            if len(chunk.strip()) < 80:
                continue
            documents.append(header + chunk)
            ids.append(f"web_{counter}")
            metadatas.append({
                "source": url,
                "doc_type": "webpage",
                "program": "all",
                "language": lang,
            })
            counter += 1
            added += 1
            chunk_count += 1

        if added > 0:
            page_count += 1

    print(f"[WEB] {page_count} Seiten -> {chunk_count} Chunks")
    return counter, chunk_count


def main():
    embedding_fn = embedding_functions.SentenceTransformerEmbeddingFunction(
        model_name="paraphrase-multilingual-MiniLM-L12-v2"
    )
    chroma_client = chromadb.PersistentClient(path=CHROMA_PATH)

    # Sauberer Rebuild: alte Collection (evtl. anderes Schema) verwerfen.
    try:
        chroma_client.delete_collection("uni_beratung")
    except Exception:
        pass
    collection = chroma_client.get_or_create_collection(
        name="uni_beratung",
        embedding_function=embedding_fn,
    )

    documents, ids, metadatas, counter = [], [], [], 0
    counter, faq_total = load_faqs(documents, ids, metadatas, counter)
    counter, pdf_chunks = load_pdfs(documents, ids, metadatas, counter)
    counter, web_chunks = load_crawled_data(documents, ids, metadatas, counter)

    BATCH_SIZE = 2000
    for i in range(0, len(documents), BATCH_SIZE):
        # Collection vor jedem Batch neu abrufen (verhindert stale reference bei langen Läufen)
        col = chroma_client.get_or_create_collection(
            name="uni_beratung",
            embedding_function=embedding_fn,
        )
        col.upsert(
            documents=documents[i:i + BATCH_SIZE],
            ids=ids[i:i + BATCH_SIZE],
            metadatas=metadatas[i:i + BATCH_SIZE],
        )
        print(f"   Batch {i // BATCH_SIZE + 1}: {min(i + BATCH_SIZE, len(documents))}/{len(documents)} gespeichert")

    print(f"\n[FERTIG] Gesamt in ChromaDB: {len(documents)} Eintraege")
    print(f"   -> {faq_total} FAQ + {pdf_chunks} PDF-Chunks + {web_chunks} Web-Chunks")


if __name__ == "__main__":
    main()
