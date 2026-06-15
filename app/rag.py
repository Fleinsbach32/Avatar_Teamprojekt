import os
import chromadb
from chromadb.utils import embedding_functions

os.environ.setdefault("TOKENIZERS_PARALLELISM", "false")

embedding_fn = embedding_functions.SentenceTransformerEmbeddingFunction(
    model_name="paraphrase-multilingual-MiniLM-L12-v2"
)
chroma_client = chromadb.PersistentClient(path="chroma_db")
collection = chroma_client.get_or_create_collection(
    name="uni_beratung",
    embedding_function=embedding_fn,
)

STUDIENGANG_FILES: dict[str, list[str]] = {
    # Bachelor
    "wing_bsc":    ["mhb_wiing_BSc_de_aktuell.pdf"],   # Wirtschaftsingenieurwesen
    "winfo_bsc":   ["mhb_wiinf_BSc_de_aktuell.pdf"],   # Wirtschaftsinformatik
    "digieco_bsc": ["mhb_de_BSc_de_aktuell.pdf"],      # Digital Economics
    # Master
    "wing_msc":    ["mhb_wiing_MSc_de_aktuell.pdf"],   # Wirtschaftsingenieurwesen
    "ieam_msc":    ["mhb_ieam_MSc_en_aktuell.pdf"],    # Industrial Engineering and Management
    "winfo_msc":   ["mhb_wiinf_MSc_de_aktuell.pdf"],   # Wirtschaftsinformatik
    "wima_msc":    ["mhb_wima_MSc_de_aktuell.pdf"],     # Wirtschaftsmathematik
    "digieco_msc": ["mhb_de_MSc_en_aktuell.pdf"],      # Digital Economics
}


def build_rag_context(query: str, studiengang: str | None = None) -> tuple[str, str, float]:
    where = {"source": {"$in": STUDIENGANG_FILES[studiengang]}} if studiengang and studiengang in STUDIENGANG_FILES else None
    kwargs: dict = dict(
        query_texts=[query],
        n_results=3,
        include=["documents", "distances"],
    )
    if where is not None:
        kwargs["where"] = where
    results = collection.query(**kwargs)
    beste_distanz = results["distances"][0][0] if results["distances"][0] else 1.0
    kontext = "\n\n".join(doc[:400] for doc in results["documents"][0])
    if beste_distanz < 0.45:
        anweisung = "Beantworte die Frage ausschließlich auf Basis des folgenden Kontexts aus der KIT-Wissensdatenbank."
    else:
        anweisung = "Nutze allgemeines Hochschulwissen. Nur wenn es um verbindliche Fristen oder offizielle Regelungen geht, empfiehl beiläufig eine kurze Bestätigung beim Prüfungsamt — nicht in jeder Antwort und jedes Mal anders formuliert."
    return kontext, anweisung, beste_distanz
