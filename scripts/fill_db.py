import chromadb
import json
from pathlib import Path
from pypdf import PdfReader
from chromadb.utils import embedding_functions

# Projekt-Root (eine Ebene über scripts/) — alle Pfade beziehen sich darauf,
# damit das Skript unabhängig vom Arbeitsverzeichnis läuft.
PROJECT_ROOT = Path(__file__).resolve().parent.parent

embedding_fn = embedding_functions.SentenceTransformerEmbeddingFunction(
    model_name="paraphrase-multilingual-MiniLM-L12-v2"
)

CHROMA_PATH = str(PROJECT_ROOT / "chroma_db")
FAQ_FILES = [
    (PROJECT_ROOT / "data" / "faq_de.json",  "de"),
    (PROJECT_ROOT / "data" / "faq_eng.json", "en"),
]
PDF_FOLDER = PROJECT_ROOT / "data" / "pdfs"

chroma_client = chromadb.PersistentClient(path=CHROMA_PATH)
collection = chroma_client.get_or_create_collection(
    name="uni_beratung",
    embedding_function=embedding_fn
)
documents = []
ids = []
metadatas = []
counter = 0

# ── 1. FAQ laden (de + en; leere/ungültige Dateien überspringen) ──
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
        text = f"Frage: {item['question']}\nAntwort: {item['answer']}"
        documents.append(text)
        ids.append(f"faq_{counter}")
        metadatas.append({"source": "faq", "language": lang, "question": item["question"]})
        counter += 1
        faq_total += 1
    print(f"[FAQ] {faq_path.name}: {len(faqs)} Eintraege geladen ({lang})")

print(f"[FAQ] {faq_total} FAQ-Eintraege gesamt")

# ── 2. PDFs laden & chunken ───────────────────────────────
import os

def chunk_text(text, chunk_size=300, overlap=100):
    chunks = []
    start = 0
    while start < len(text):
        end = start + chunk_size
        chunks.append(text[start:end])
        start += chunk_size - overlap
    return chunks

pdf_count = 0
chunk_count = 0

for filename in os.listdir(PDF_FOLDER):
    if not filename.endswith(".pdf"):
        continue

    pdf_path = os.path.join(PDF_FOLDER, filename)
    reader = PdfReader(pdf_path)

    # Text aus allen Seiten extrahieren
    full_text = ""
    for page in reader.pages:
        full_text += page.extract_text() + "\n"

    # In Chunks aufteilen
    chunks = chunk_text(full_text, chunk_size=400, overlap=50)

    for chunk in chunks:
        if len(chunk.strip()) < 50:  # leere Chunks überspringen
            continue
        documents.append(chunk)
        ids.append(f"pdf_{counter}")
        metadatas.append({"source": filename})
        counter += 1
        chunk_count += 1

    pdf_count += 1
    print(f"[PDF] {filename}: {chunk_count} Chunks geladen")

# ── 3. Alles in ChromaDB speichern (in 5000er-Batches) ───
BATCH_SIZE = 5000
for i in range(0, len(documents), BATCH_SIZE):
    collection.upsert(
        documents=documents[i:i + BATCH_SIZE],
        ids=ids[i:i + BATCH_SIZE],
        metadatas=metadatas[i:i + BATCH_SIZE]
    )
    print(f"   Batch {i // BATCH_SIZE + 1}: {min(i + BATCH_SIZE, len(documents))}/{len(documents)} gespeichert")

print(f"\n[FERTIG] Gesamt in ChromaDB: {len(documents)} Eintraege")
print(f"   -> {faq_total} FAQ + {chunk_count} PDF-Chunks")