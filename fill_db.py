import chromadb
import json
from pypdf import PdfReader
from chromadb.utils import embedding_functions

embedding_fn = embedding_functions.SentenceTransformerEmbeddingFunction(
    model_name="paraphrase-multilingual-MiniLM-L12-v2"
)

CHROMA_PATH = r"chroma_db"
FAQ_PATH = r"data/faq.json"
PDF_FOLDER = r"data"

chroma_client = chromadb.PersistentClient(path=CHROMA_PATH)
collection = chroma_client.get_or_create_collection(
    name="uni_beratung",
    embedding_function=embedding_fn
)
documents = []
ids = []
metadatas = []
counter = 0

# ── 1. FAQ laden ──────────────────────────────────────────
with open(FAQ_PATH, encoding="utf-8") as f:
    faqs = json.load(f)

for item in faqs:
    text = f"Frage: {item['question']}\nAntwort: {item['answer']}"
    documents.append(text)
    ids.append(f"faq_{counter}")
    metadatas.append({"source": "faq", "question": item["question"]})
    counter += 1

print(f"📄 {len(faqs)} FAQ-Einträge geladen")

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
    print(f"📑 {filename}: {chunk_count} Chunks geladen")

# ── 3. Alles in ChromaDB speichern (in 5000er-Batches) ───
BATCH_SIZE = 5000
for i in range(0, len(documents), BATCH_SIZE):
    collection.upsert(
        documents=documents[i:i + BATCH_SIZE],
        ids=ids[i:i + BATCH_SIZE],
        metadatas=metadatas[i:i + BATCH_SIZE]
    )
    print(f"   Batch {i // BATCH_SIZE + 1}: {min(i + BATCH_SIZE, len(documents))}/{len(documents)} gespeichert")

print(f"\n✅ Gesamt in ChromaDB: {len(documents)} Einträge")
print(f"   → {len(faqs)} FAQ + {chunk_count} PDF-Chunks")