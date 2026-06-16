import os
import re
import chromadb
from chromadb.utils import embedding_functions

os.environ.setdefault("TOKENIZERS_PARALLELISM", "false")

MODULE_ID_RE = re.compile(r'\bM-[A-Z]+-\d+\b')

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


def _query_safe(where: dict | None, n_results: int, **kwargs) -> dict:
    """Führt eine ChromaDB-Query durch und reduziert n_results bei Bedarf."""
    base: dict = {"n_results": n_results, "include": ["documents", "distances"], **kwargs}
    if where is not None:
        base["where"] = where
    try:
        return collection.query(**base)
    except Exception:
        # Weniger Ergebnisse anfordern falls Collection zu klein ist
        base["n_results"] = 1
        try:
            return collection.query(**base)
        except Exception:
            return {"documents": [[]], "distances": [[]]}


def build_rag_context(query: str, studiengang: str | None = None) -> tuple[str, str, float]:
    where = {"source": {"$in": STUDIENGANG_FILES[studiengang]}} if studiengang and studiengang in STUDIENGANG_FILES else None

    # Modul-ID erkannt → Volltext-Suche per ID (semantisches Embedding taugt nicht für IDs)
    module_match = MODULE_ID_RE.search(query)
    if module_match:
        module_id = module_match.group()
        id_results = _query_safe(where, 3, query_texts=[query], where_document={"$contains": module_id})
        if id_results["documents"][0]:
            kontext = "\n\n".join(doc[:600] for doc in id_results["documents"][0])
            anweisung = (
                "Der folgende Kontext aus der KIT-Wissensdatenbank enthält Informationen zum genannten Modul. "
                "Beantworte die Frage auf Basis dieses Kontexts. "
                "Nenne das Modul nur mit seinem vollständigen Klarnamen, ohne die ID-Nummer."
            )
            return kontext, anweisung, 0.1

    # Standardsuche (semantisch)
    results = _query_safe(where, 3, query_texts=[query])
    beste_distanz = results["distances"][0][0] if results["distances"][0] else 1.0
    kontext = "\n\n".join(doc[:600] for doc in results["documents"][0])

    if beste_distanz < 0.45:
        anweisung = (
            "Der folgende Kontext stammt aus der KIT-Wissensdatenbank. "
            "Nutze ihn, wenn er zur Frage passt. "
            "Wenn der Kontext die Frage nicht beantwortet oder ein anderes Thema behandelt, "
            "ignoriere ihn und antworte auf Basis deines allgemeinen Hochschulwissens. "
            "Erfinde niemals Inhalte aus einem unpassenden Kontext."
        )
    else:
        anweisung = (
            "Nutze allgemeines Hochschulwissen. "
            "Nur wenn es um verbindliche Fristen oder offizielle Regelungen geht, "
            "empfiehl beiläufig eine kurze Bestätigung auf campus.kit.edu oder beim Prüfungsamt — "
            "nicht in jeder Antwort und jedes Mal anders formuliert."
        )
    return kontext, anweisung, beste_distanz
