import chromadb
from chromadb.utils import embedding_functions

embedding_fn = embedding_functions.SentenceTransformerEmbeddingFunction(
    model_name="paraphrase-multilingual-MiniLM-L12-v2"
)

chroma_client = chromadb.PersistentClient(path="chroma_db")
collection = chroma_client.get_or_create_collection(
    name="uni_beratung",
    embedding_function=embedding_fn
)

results = collection.query(
    query_texts=["Wann ist die Bewerbungsfrist ?"],
    n_results=3,
    include=["documents", "distances"]
)

print("Distanzen:")
for doc, dist in zip(results["documents"][0], results["distances"][0]):
    print(f"  {dist:.3f} → {doc[:100]}")