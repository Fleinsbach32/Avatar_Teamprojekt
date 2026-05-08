import chromadb

chroma_client = chromadb.PersistentClient(path="chroma_db")
collection = chroma_client.get_or_create_collection(name="uni_beratung")

# Wie viele Einträge sind drin?
print(f"Einträge in DB: {collection.count()}")

# Testsuche
results = collection.query(
    query_texts=["Wann ist die Bewerbungsfrist?"],
    n_results=3
)

print("\nGefundene Dokumente:")
for doc in results["documents"][0]:
    print(f"→ {doc[:100]}")