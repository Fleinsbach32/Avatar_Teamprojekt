# fill_db.py
import chromadb
import json

CHROMA_PATH = r"chroma_db"
FAQ_PATH = r"data/faq.json"

# ChromaDB initialisieren
chroma_client = chromadb.PersistentClient(path=CHROMA_PATH)
collection = chroma_client.get_or_create_collection(name="uni_beratung")

# FAQ laden
with open(FAQ_PATH, encoding="utf-8") as f:
    faqs = json.load(f)

# Dokumente vorbereiten
documents = []
ids = []
metadatas = []

for i, item in enumerate(faqs):
    # Frage + Antwort zusammen als ein Dokument
    text = f"Frage: {item['question']}\nAntwort: {item['answer']}"
    documents.append(text)
    ids.append(f"faq_{i}")
    metadatas.append({"question": item["question"]})

# In ChromaDB speichern
collection.upsert(
    documents=documents,
    ids=ids,
    metadatas=metadatas
)

print(f"✅ {len(documents)} FAQ-Einträge in ChromaDB gespeichert")