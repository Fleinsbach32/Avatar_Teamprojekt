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
    "wiwi_bsc":  ["mhb_de_BSc_de_aktuell.pdf"],
    "wiwi_msc":  ["mhb_de_MSc_en_aktuell.pdf"],
    "tvwl_bsc":  ["mhb_tvwl_BSc_de_aktuell.pdf"],
    "tvwl_msc":  ["mhb_tvwl_MSc_de_aktuell.pdf"],
    "wiinf_bsc": ["mhb_wiinf_BSc_de_aktuell.pdf"],
    "wiinf_msc": ["mhb_wiinf_MSc_de_aktuell.pdf"],
    "wiing_bsc": ["mhb_wiing_BSc_de_aktuell.pdf"],
    "wiing_msc": ["mhb_wiing_MSc_de_aktuell.pdf"],
    "wima_msc":  ["mhb_wima_MSc_de_aktuell.pdf"],
    "ieam_msc":  ["mhb_ieam_MSc_en_aktuell.pdf"],
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
