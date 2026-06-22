import logging
import os
import re
import chromadb
from chromadb.utils import embedding_functions
from sentence_transformers import CrossEncoder

os.environ.setdefault("TOKENIZERS_PARALLELISM", "false")

MODULE_ID_RE = re.compile(r'\b[MT]-[A-Z]+-\d+\b')

embedding_fn = embedding_functions.SentenceTransformerEmbeddingFunction(
    model_name="paraphrase-multilingual-MiniLM-L12-v2"
)
chroma_client = chromadb.PersistentClient(path="data/chroma_db")
collection = chroma_client.get_or_create_collection(
    name="uni_beratung",
    embedding_function=embedding_fn,
)

try:
    reranker = CrossEncoder("cross-encoder/mmarco-mMiniLMv2-L12-H384-v1")
except Exception as e:
    logging.warning(f"Reranker konnte nicht geladen werden: {e}")
    reranker = None

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


def _studiengang_where(studiengang: str | None) -> dict | None:
    """Filter auf den gewählten Studiengang: dessen Handbuch (program==key) plus
    FAQ/allgemeine Infos (program=="all"). Andere Handbücher fallen weg.
    Ohne (gültigen) Studiengang: kein Filter."""
    if studiengang and studiengang in STUDIENGANG_FILES:
        return {"$or": [{"program": studiengang}, {"program": "all"}]}
    return None


def _combine(a: dict | None, b: dict | None) -> dict | None:
    """Kombiniert zwei ChromaDB-where-Filter mit $and (None-sicher)."""
    if a and b:
        return {"$and": [a, b]}
    return a or b


_NUMBER_Q_RE = re.compile(
    r'(?:modul-?nummer|nummer|kennung|modul-?id)\s+(?:von|für|fuer|des|zum|zur|der)\s+'
    r'(?:(?:dem|der|das|die|den|modul)\s+)*(.+?)[\?\.!]*\s*$',
    re.IGNORECASE,
)

# Erkennt "Was ist das Modul X?" / "Erkläre das Modul X" / "Was macht Modul X?"
_WHAT_IS_MODULE_RE = re.compile(
    r'(?:was\s+(?:ist|sind|bedeutet|beinhaltet|umfasst)|erkl(?:ä|ae)re?\s+(?:mir\s+)?(?:kurz\s+)?|'
    r'beschreibe?\s+(?:mir\s+)?(?:kurz\s+)?|was\s+macht)\s+'
    r'(?:(?:das|ein|die|dem|den)\s+)?(?:modul\s+)'
    r'(.+?)[\?\.!]*\s*$',
    re.IGNORECASE,
)


def _module_name_from_number_question(query: str) -> str | None:
    """Erkennt Fragen wie 'Wie lautet die Modulnummer von <Name>?' und gibt
    <Name> zurück. So kann die semantische Suche mit dem Modulnamen laufen statt
    mit der Füllfrage (deren Embedding sonst das falsche Modul trifft)."""
    m = _NUMBER_Q_RE.search(query)
    if m:
        name = m.group(1).strip().strip('"\'')
        return name or None
    return None


def _module_name_from_what_is_question(query: str) -> str | None:
    """Erkennt 'Was ist das Modul X?' und gibt den Modulnamen X zurück."""
    m = _WHAT_IS_MODULE_RE.search(query)
    if m:
        name = m.group(1).strip().strip('"\'')
        return name if len(name) >= 3 else None
    return None


def _contains_variants(name: str) -> list[str]:
    """Erzeugt Schreibvarianten für where_document $contains (Case-Varianten
    + erster Bestandteil als Fallback bei mehrteiligen Namen)."""
    variants = [name, name.title(), name.capitalize()]
    words = name.split()
    if len(words) > 1 and len(words[0]) >= 4:
        variants.append(words[0])
        variants.append(words[0].title())
    return list(dict.fromkeys(v for v in variants if v))


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


def rerank(docs: list[str], query: str, top_k: int = 6) -> list[str]:
    """Rankt Dokumente mit CrossEncoder neu und gibt die top_k zurück.
    Fallback auf einfaches Slicing wenn reranker nicht verfügbar."""
    if not docs:
        return docs
    if reranker is None:
        return docs[:top_k]
    pairs = [(query, doc) for doc in docs]
    scores = reranker.predict(pairs)
    ranked = sorted(zip(scores, docs), key=lambda x: x[0], reverse=True)
    return [doc for _, doc in ranked[:top_k]]


def build_rag_context(query: str, studiengang: str | None = None) -> tuple[str, str, float]:
    where = _studiengang_where(studiengang)

    # Modul-ID erkannt → exakter Metadaten-Treffer (module_id), sonst Volltext-Fallback
    # (semantisches Embedding taugt nicht für IDs)
    module_match = MODULE_ID_RE.search(query)
    if module_match:
        module_id = module_match.group()
        id_results = _query_safe(_combine(where, {"module_id": module_id}), 3, query_texts=[query])
        if not id_results["documents"][0]:
            id_results = _query_safe(where, 3, query_texts=[query], where_document={"$contains": module_id})
        if id_results["documents"][0]:
            kontext = "\n\n".join(doc[:600] for doc in id_results["documents"][0])
            anweisung = (
                "Der folgende Kontext aus der KIT-Wissensdatenbank enthält Informationen zum genannten Modul. "
                "Beantworte die Frage auf Basis dieses Kontexts. "
                "Nenne den vollständigen Klarnamen des Moduls; die Modulnummer nur, wenn ausdrücklich danach gefragt wird."
            )
            return kontext, anweisung, 0.1

    # "Modulnummer von <Name>?" → Volltext-Treffer auf den Modulnamen.
    # Semantische Suche rankt kurze Namen unzuverlässig, daher where_document
    # $contains (mit Groß-/Kleinschreibungs-Varianten + erstem Wort als Fallback).
    name_query = _module_name_from_number_question(query)
    if name_query:
        name_results = {"documents": [[]], "distances": [[]]}
        for variant in _contains_variants(name_query):
            name_results = _query_safe(where, 3, query_texts=[name_query],
                                       where_document={"$contains": variant})
            if name_results["documents"][0]:
                break
        if name_results["documents"][0]:
            kontext = "\n\n".join(doc[:600] for doc in name_results["documents"][0])
            anweisung = (
                "Der folgende Kontext aus der KIT-Wissensdatenbank enthält Module mit ihren "
                "Modulnummern. Beantworte die Frage auf Basis dieses Kontexts "
                "und nenne die Modulnummer des gefragten Moduls, da ausdrücklich danach gefragt wurde. "
                "Wähle das Modul, dessen Name am besten zur Frage passt. "
                "Wenn das gesuchte Modul nicht im Kontext vorkommt, sage ehrlich, dass du die "
                "Modulnummer nicht in der Datenbank hast, und empfehle campus.kit.edu."
            )
            distanz = name_results["distances"][0][0] if name_results["distances"][0] else 0.2
            return kontext, anweisung, distanz
        # Modul nicht in DB → kein Kontext, direkte Anweisung
        return (
            "",
            "Das angefragte Modul ist nicht in der Wissensdatenbank. "
            "Sage das ehrlich in einem Satz und empfehle campus.kit.edu für die Modulnummer.",
            1.0,
        )

    # "Was ist das Modul X?" → gezielter Volltext-Treffer auf Modulname,
    # verhindert Halluzination von Alternativmodulen bei fehlendem Treffer.
    what_is_name = _module_name_from_what_is_question(query)
    if what_is_name:
        what_results = {"documents": [[]], "distances": [[]]}
        for variant in _contains_variants(what_is_name):
            what_results = _query_safe(where, 3, query_texts=[what_is_name],
                                       where_document={"$contains": variant})
            if what_results["documents"][0]:
                break
        if what_results["documents"][0]:
            kontext = "\n\n".join(doc[:600] for doc in what_results["documents"][0])
            anweisung = (
                "Der folgende Kontext enthält Informationen zum angefragten Modul aus der "
                "KIT-Wissensdatenbank. Beantworte die Frage ausschließlich auf Basis dieses Kontexts. "
                "Nenne den vollständigen Modulnamen wie er im Kontext steht. "
                "Nenne keine anderen Modulnamen, die nicht explizit im Kontext erwähnt werden."
            )
            # Fester Distanzwert — Treffer via $contains ist immer aus der DB,
            # unabhängig von der semantischen Embedding-Distanz.
            return kontext, anweisung, 0.1
        # Modul nicht gefunden → klare Aussage, kein Raten
        return (
            "",
            "Das angefragte Modul ist nicht in der Wissensdatenbank. "
            "Sage kurz und ehrlich, dass du dazu keine Informationen hast. "
            "Schlage KEINE anderen Modulnamen vor. Empfehle campus.kit.edu.",
            1.0,
        )

    # Standardsuche — zweistufig wenn Studiengang gewählt, sonst einstufig.
    # Problem: "all"-getaggte Web-Chunks (54k) überdecken bei einstufiger Suche
    # die Modulhandbuch-Chunks des gewählten Studiengangs (je ~1.5k Chunks).
    # Bei Pflichtmodul-Fragen werden mehr Studiengang-Chunks abgerufen.
    is_pflicht = any(kw in query.lower() for kw in ("pflichtmodul", "pflicht", "orientierungsprüfung", "orientierungspruefung"))
    if studiengang and studiengang in STUDIENGANG_FILES:
        prog_n = 15 if is_pflicht else 10
        # Stufe 1: Handbuch des gewählten Studiengangs (Priorität)
        prog_r = _query_safe({"program": studiengang}, prog_n, query_texts=[query])
        prog_docs  = prog_r["documents"][0]
        prog_dists = prog_r["distances"][0]
        # Stufe 2: allgemeiner Inhalt (FAQ, Info, Web)
        all_r  = _query_safe({"program": "all"}, 6, query_texts=[query])
        all_docs  = all_r["documents"][0]
        all_dists = all_r["distances"][0]
        # Kombinieren und via Cross-Encoder auf 6 reranken
        combined_docs  = prog_docs + all_docs
        combined_dists = prog_dists + all_dists
        docs  = rerank(combined_docs, query, top_k=6)
        dists = combined_dists
        # beste_distanz aus allen Kandidaten-Distanzen (Proxy für DB-Relevanz)
        beste_distanz = min(dists) if dists else 1.0
    else:
        results = _query_safe(where, 15, query_texts=[query])
        docs  = rerank(results["documents"][0], query, top_k=6)
        dists = results["distances"][0]
        beste_distanz = dists[0] if dists else 1.0

    kontext = "\n\n".join(doc[:600] for doc in docs)

    if beste_distanz < 0.45:
        anweisung = (
            "Der folgende Kontext stammt aus der KIT-Wissensdatenbank. "
            "Nutze ihn, wenn er zur Frage passt. "
            "Wenn der Kontext die Frage nicht beantwortet oder ein anderes Thema behandelt, "
            "ignoriere ihn und antworte auf Basis deines allgemeinen Hochschulwissens. "
            "Wenn nach einem bestimmten Modul gefragt wird, nenne es nur wenn es explizit "
            "im Kontext steht — schlage niemals andere Modulnamen als Alternative vor. "
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
