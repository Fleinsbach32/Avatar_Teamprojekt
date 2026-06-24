"""
KIRA Web Crawler — KIT WiWi-Fakultät
Crawls wiwi.kit.edu, extracts text + PDFs, chunks content, and stores
embeddings in ChromaDB for the KIRA RAG study-advisor.

Usage:
    python crawler.py --urls https://www.wiwi.kit.edu --max-pages 500
    python crawler.py --inject-ratings
"""

import argparse
import hashlib
import json
import logging
import re
import time
import unicodedata
import urllib.robotparser
from collections import deque
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional
from urllib.parse import urljoin, urlparse

import requests
from bs4 import BeautifulSoup

# ---------------------------------------------------------------------------
# Optional / lazy imports — fail loudly at runtime, not at import time
# ---------------------------------------------------------------------------
try:
    import fitz  # PyMuPDF
    _HAVE_FITZ = True
except ImportError:
    _HAVE_FITZ = False
    logging.warning("PyMuPDF (fitz) not installed — PDF extraction disabled")

try:
    from langdetect import detect as _langdetect
    _HAVE_LANGDETECT = True
except ImportError:
    _HAVE_LANGDETECT = False

try:
    import chromadb
    _HAVE_CHROMA = True
except ImportError:
    _HAVE_CHROMA = False
    logging.warning("chromadb not installed — ChromaDB storage disabled")

try:
    from sentence_transformers import SentenceTransformer
    _HAVE_ST = True
except ImportError:
    _HAVE_ST = False
    logging.warning("sentence-transformers not installed — embeddings disabled")

# ---------------------------------------------------------------------------
# Logging setup
# ---------------------------------------------------------------------------
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger(__name__)

# Projekt-Root (eine Ebene über scripts/) — Default-Pfade beziehen sich darauf,
# damit chroma_db/ und crawled_data/ im Projekt-Root landen (konsistent mit app/rag.py).
PROJECT_ROOT = Path(__file__).resolve().parent.parent

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
# Domains, deren interne Links beim Crawl verfolgt werden (ohne "www."-Präfix
# notiert; www-Varianten werden in _strip_www normalisiert). Bewusst NICHT die
# breite www.kit.edu — die bleibt seed-only, um Crawl-Explosion zu vermeiden.
ALLOWED_DOMAINS = {
    "wiwi.kit.edu",
    "fachschaft.org",
    "hoc.kit.edu",
    "studium.hoc.kit.edu",
    "zak.kit.edu",
    "sle.kit.edu",
}
SHIBBOLETH_PATTERNS = [
    "shibboleth", "idp.kit.edu", "idp2.kit.edu",
    "login", "sso", "auth", "saml",
]
USER_AGENT = (
    "Mozilla/5.0 (compatible; KIRA-Crawler/1.0; "
    "+https://www.wiwi.kit.edu)"
)
CHUNK_SIZE_TOKENS = 300
CHUNK_OVERLAP_TOKENS = 30
CHROMA_COLLECTION_NAME = "uni_beratung"
BATCH_SIZE = 50

# PHP scripts that are always behind a login — skip without any HTTP request
URL_BLACKLIST = {
    "ps_ankuendigung.php",
    "mhbDetails.php",
    "meinstundenplan.php",
    "ressourcen.php",
    "Newsarchiv.php",
    "wiwi-it.php",
}

# Extensions that are never useful for a text-based RAG system
SKIP_EXTENSIONS = {
    ".zip", ".tar", ".gz", ".rar", ".7z",
    ".exe", ".dmg", ".pkg", ".msi",
    ".mp4", ".avi", ".mov", ".mkv", ".wmv",
    ".mp3", ".wav", ".ogg", ".flac",
    ".psd", ".ai", ".sketch",
    ".woff", ".woff2", ".ttf", ".eot", ".otf",
    ".ico", ".bmp", ".tiff",
}

# Content-Type prefixes/values that mean binary/media — skip before body download
SKIP_CONTENT_TYPES = (
    "application/octet-stream",
    "video/",
    "audio/",
    "image/",
)

MAX_CONTENT_BYTES = 5 * 1024 * 1024  # 5 MB

# ---------------------------------------------------------------------------
# Robots.txt cache
# ---------------------------------------------------------------------------
_robots_cache: dict[str, urllib.robotparser.RobotFileParser] = {}


def _get_robots(base_url: str) -> urllib.robotparser.RobotFileParser:
    if base_url not in _robots_cache:
        rp = urllib.robotparser.RobotFileParser()
        robots_url = base_url.rstrip("/") + "/robots.txt"
        try:
            rp.set_url(robots_url)
            rp.read()
        except Exception:
            pass  # treat as allow-all if robots.txt unreachable
        _robots_cache[base_url] = rp
    return _robots_cache[base_url]


def robots_allows(url: str) -> bool:
    parsed = urlparse(url)
    base = f"{parsed.scheme}://{parsed.netloc}"
    rp = _get_robots(base)
    return rp.can_fetch(USER_AGENT, url)

# ---------------------------------------------------------------------------
# HTTP helpers
# ---------------------------------------------------------------------------

SESSION = requests.Session()
SESSION.headers.update({"User-Agent": USER_AGENT})


def fetch_url(
    url: str,
    timeout: int = 10,
    max_retries: int = 3,
) -> Optional[requests.Response]:
    """
    Fetch URL with retries + exponential backoff using stream=True so that
    response headers arrive before the body is downloaded. The caller is
    responsible for calling resp.content / resp.text when it decides the
    response is worth keeping, and resp.close() otherwise.
    Returns None on failure.
    """
    for attempt in range(max_retries):
        try:
            resp = SESSION.get(url, timeout=timeout, allow_redirects=True, stream=True)
            return resp
        except requests.exceptions.Timeout:
            logger.warning("Timeout on %s (attempt %d/%d)", url, attempt + 1, max_retries)
        except requests.exceptions.SSLError as exc:
            logger.warning("SSL error on %s: %s", url, exc)
            return None  # no retry for SSL errors — likely misconfigured cert
        except requests.exceptions.RequestException as exc:
            logger.warning("Request error on %s: %s (attempt %d/%d)", url, exc, attempt + 1, max_retries)
        if attempt < max_retries - 1:
            backoff = 2 ** attempt
            logger.debug("Backoff %ds before retry", backoff)
            time.sleep(backoff)
    return None


def is_skippable_extension(url: str) -> bool:
    """Check URL path extension before making any HTTP request."""
    path = urlparse(url).path.lower()
    return any(path.endswith(ext) for ext in SKIP_EXTENSIONS)


def is_skippable_response(resp: requests.Response) -> tuple[bool, str]:
    """
    Inspect response headers (available before body download with stream=True).
    Returns (should_skip, reason).
    """
    content_type = resp.headers.get("content-type", "").lower()
    if any(content_type.startswith(ct) for ct in SKIP_CONTENT_TYPES):
        return True, f"content_type:{content_type.split(';')[0].strip()}"

    content_length = resp.headers.get("content-length")
    if content_length and int(content_length) > MAX_CONTENT_BYTES:
        mb = int(content_length) / (1024 * 1024)
        return True, f"too_large:{mb:.1f}MB"

    return False, ""

# ---------------------------------------------------------------------------
# URL classification helpers
# ---------------------------------------------------------------------------

def _strip_www(netloc: str) -> str:
    """Entfernt ein 'www.'-Präfix (Präfix, nicht Zeichenmenge wie lstrip)."""
    netloc = netloc.lower()
    return netloc[4:] if netloc.startswith("www.") else netloc


def is_internal(url: str) -> bool:
    domain = _strip_www(urlparse(url).netloc)
    return any(domain == _strip_www(d) for d in ALLOWED_DOMAINS)


def is_pdf(url: str, content_type: str = "") -> bool:
    return url.lower().endswith(".pdf") or "application/pdf" in content_type


def is_login_redirect(resp: requests.Response) -> bool:
    """Detect Shibboleth/KIT-SSO redirects."""
    final_url = resp.url.lower()
    return any(p in final_url for p in SHIBBOLETH_PATTERNS)


def is_blocked(resp: requests.Response) -> bool:
    return resp.status_code in (401, 403) or is_login_redirect(resp)

# ---------------------------------------------------------------------------
# Language detection
# ---------------------------------------------------------------------------

def detect_language(text: str) -> str:
    if not _HAVE_LANGDETECT or len(text) < 50:
        return "de"
    try:
        return _langdetect(text[:2000])
    except Exception:
        return "de"

# ---------------------------------------------------------------------------
# Content-type classification
# ---------------------------------------------------------------------------

def classify_content(url: str, text: str) -> str:
    url_lower = url.lower()
    text_lower = text.lower()
    if "pruefungsamt" in url_lower or "prüfungsamt" in url_lower or "pruefungsamt" in text_lower:
        return "pruefungsamt"
    if "studienordnung" in url_lower or "spo" in url_lower or "studienordnung" in text_lower:
        return "studienordnung"
    if url_lower.endswith(".pdf"):
        return "pdf"
    return "general"

# ---------------------------------------------------------------------------
# Text extraction
# ---------------------------------------------------------------------------

def extract_text_html(soup: BeautifulSoup) -> str:
    for tag in soup(["script", "style", "nav", "footer", "header", "aside"]):
        tag.decompose()
    text = soup.get_text(separator=" ", strip=True)
    return re.sub(r"\s{2,}", " ", text).strip()


def extract_text_pdf(content: bytes) -> str:
    if not _HAVE_FITZ:
        return ""
    try:
        doc = fitz.open(stream=content, filetype="pdf")
        pages = [doc[i].get_text() for i in range(len(doc))]
        doc.close()
        return "\n".join(pages).strip()
    except Exception as exc:
        logger.warning("PDF extraction failed: %s", exc)
        return ""

# ---------------------------------------------------------------------------
# Chunking
# ---------------------------------------------------------------------------

def _normalize_text(text: str) -> str:
    """Unicode-Normalisierung: NFC, Soft-Hyphen (U+00AD) entfernen, NBSP→Space,
    Steuerzeichen entfernen, Whitespace kollabieren."""
    text = unicodedata.normalize("NFC", text)
    text = text.replace("\xad", "").replace("\xa0", " ")
    text = "".join(
        ch for ch in text
        if ch in "\t\n\r " or unicodedata.category(ch)[0] != "C"
    )
    return re.sub(r"\s+", " ", text).strip()


def _split_sentences(text: str) -> list[str]:
    """Naive sentence splitter that handles German/English text."""
    sentences = re.split(r'(?<=[.!?])\s+', text)
    return [s.strip() for s in sentences if s.strip()]


def _approx_tokens(text: str) -> int:
    """Word-based token approximation (≈ real token count ±15%)."""
    return len(text.split())


def chunk_text(text: str, chunk_tokens: int = CHUNK_SIZE_TOKENS, overlap_tokens: int = CHUNK_OVERLAP_TOKENS) -> list[str]:
    """
    Sentence-aware chunking:
    accumulate sentences until chunk_tokens reached, then slide
    back by overlap_tokens worth of sentences.
    """
    sentences = _split_sentences(text)
    if not sentences:
        return []

    chunks: list[str] = []
    current_sentences: list[str] = []
    current_tokens = 0

    for sent in sentences:
        sent_tokens = _approx_tokens(sent)
        if current_tokens + sent_tokens > chunk_tokens and current_sentences:
            chunks.append(" ".join(current_sentences))
            # slide back: drop sentences from front until we're within overlap budget
            overlap_budget = overlap_tokens
            while current_sentences and overlap_budget > 0:
                overlap_budget -= _approx_tokens(current_sentences[0])
                if overlap_budget > 0:
                    current_sentences.pop(0)
                else:
                    break
            current_tokens = sum(_approx_tokens(s) for s in current_sentences)
        current_sentences.append(sent)
        current_tokens += sent_tokens

    if current_sentences:
        chunks.append(" ".join(current_sentences))

    return [c for c in chunks if len(c.strip()) >= 50]

# ---------------------------------------------------------------------------
# ChromaDB helpers
# ---------------------------------------------------------------------------

def get_or_create_collection(chroma_dir: str):
    """Create (or open) the uni_beratung collection with HNSW cosine index."""
    if not _HAVE_CHROMA or not _HAVE_ST:
        return None, None
    from chromadb.utils import embedding_functions as ef
    embedding_fn = ef.SentenceTransformerEmbeddingFunction(
        model_name="paraphrase-multilingual-MiniLM-L12-v2"
    )
    client = chromadb.PersistentClient(path=chroma_dir)
    # Kein hnsw:space-Override -> gleiche Distanzmetrik wie fill_db.py/app.rag
    # (sonst wäre der Distanz-Schwellwert in app/rag.py je nach Erzeuger anders).
    collection = client.get_or_create_collection(
        name=CHROMA_COLLECTION_NAME,
        embedding_function=embedding_fn,
    )
    logger.info("Opened/created ChromaDB collection '%s'", CHROMA_COLLECTION_NAME)
    return client, collection


def url_already_indexed(collection, url: str) -> bool:
    """Check whether any chunk from this URL is already in ChromaDB."""
    try:
        results = collection.get(where={"source_url": url}, limit=1)
        return len(results["ids"]) > 0
    except Exception:
        return False


def store_chunks(
    collection,
    model,
    chunks: list[str],
    metadata_base: dict,
) -> int:
    """Embed chunks in batches and upsert into ChromaDB. Returns inserted count."""
    if not chunks or collection is None or model is None:
        return 0

    ids, docs, metas = [], [], []
    for idx, chunk in enumerate(chunks):
        chunk_id = hashlib.md5(
            f"{metadata_base['source_url']}::{idx}".encode()
        ).hexdigest()
        meta = {**metadata_base, "chunk_index": idx}
        ids.append(chunk_id)
        docs.append(chunk)
        metas.append(meta)

    inserted = 0
    for start in range(0, len(ids), BATCH_SIZE):
        batch_ids = ids[start : start + BATCH_SIZE]
        batch_docs = docs[start : start + BATCH_SIZE]
        batch_metas = metas[start : start + BATCH_SIZE]
        try:
            embeddings = model.encode(batch_docs, show_progress_bar=False).tolist()
            collection.upsert(
                ids=batch_ids,
                embeddings=embeddings,
                documents=batch_docs,
                metadatas=batch_metas,
            )
            inserted += len(batch_ids)
        except Exception as exc:
            logger.error("ChromaDB upsert failed: %s", exc)

    return inserted

# ---------------------------------------------------------------------------
# JSON file helpers
# ---------------------------------------------------------------------------

def url_to_filename(url: str) -> str:
    return hashlib.md5(url.encode()).hexdigest() + ".json"


def save_json(data: dict, output_dir: Path) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    path = output_dir / url_to_filename(data["url"])
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def log_skipped(url: str, reason: str, log_path: Path) -> None:
    with log_path.open("a", encoding="utf-8") as f:
        f.write(f"{datetime.now(timezone.utc).isoformat()} | {reason} | {url}\n")

# ---------------------------------------------------------------------------
# Core crawl logic
# ---------------------------------------------------------------------------

def crawl(
    start_urls: list[str],
    output_dir: Path,
    chroma_dir: str,
    max_pages: int = 500,
    max_depth: int = 5,
    delay: float = 1.0,
    skip_pdfs: bool = True,
    embed: bool = False,
) -> dict:
    """
    BFS crawler. Returns stats dict.
    Pass embed=True to also write into ChromaDB during the crawl.
    Default is False — use --fill-db as a separate step instead.
    """
    skip_log = output_dir / "skipped_urls.log"
    found_pdfs: set[str] = set()
    output_dir.mkdir(parents=True, exist_ok=True)

    # Load embedding model and ChromaDB only when requested
    model = None
    collection = None
    if embed and _HAVE_ST and _HAVE_CHROMA:
        logger.info("Loading SentenceTransformer model …")
        model = SentenceTransformer("paraphrase-multilingual-MiniLM-L12-v2")
        _, collection = get_or_create_collection(chroma_dir)

    visited: set[str] = set()
    queue: deque[tuple[str, int]] = deque()
    for u in start_urls:
        if u.startswith("http://"):
            u = "https://" + u[7:]
        queue.append((u, 0))
        visited.add(u)

    stats = {
        "crawled": 0,
        "skipped": 0,
        "chunks_stored": 0,
        "pdfs_processed": 0,
    }

    while queue and stats["crawled"] < max_pages:
        url, depth = queue.popleft()

        if any(pattern in url for pattern in URL_BLACKLIST):
            logger.debug("Blacklisted URL, skipping: %s", url)
            log_skipped(url, "blacklisted", skip_log)
            stats["skipped"] += 1
            continue

        if not robots_allows(url):
            logger.info("robots.txt disallows: %s", url)
            log_skipped(url, "robots.txt", skip_log)
            stats["skipped"] += 1
            continue

        # Skip HTTP fetch if already saved + indexed — but still enqueue child links
        json_file = output_dir / url_to_filename(url)
        if json_file.exists() and collection is not None and url_already_indexed(collection, url):
            logger.debug("Already processed, skipping fetch: %s", url)
            stats["crawled"] += 1
            if depth < max_depth:
                try:
                    cached = json.loads(json_file.read_text(encoding="utf-8"))
                    for child_url in cached.get("links_found", []):
                        if child_url not in visited:
                            visited.add(child_url)
                            queue.append((child_url, depth + 1))
                except Exception:
                    pass
            continue

        # ── Extension check (before any HTTP request) ────────────────────────
        if skip_pdfs and is_pdf(url):
            logger.debug("Skipping PDF (--skip-pdfs): %s", url)
            log_skipped(url, "pdf_skipped", skip_log)
            found_pdfs.add(url)
            stats["skipped"] += 1
            continue

        if is_skippable_extension(url):
            logger.debug("Skipping binary extension: %s", url)
            log_skipped(url, "binary_extension", skip_log)
            stats["skipped"] += 1
            continue

        logger.info("[%d/%d | queue: %d] Crawling (depth=%d): %s",
                    stats["crawled"] + 1, max_pages, len(queue), depth, url)
        resp = fetch_url(url)

        if resp is None:
            log_skipped(url, "fetch_failed", skip_log)
            stats["skipped"] += 1
            time.sleep(delay)
            continue

        if is_blocked(resp):
            reason = f"HTTP {resp.status_code}" if resp.status_code in (401, 403) else "login_redirect"
            logger.info("Skipping (blocked): %s — %s", url, reason)
            log_skipped(url, reason, skip_log)
            resp.close()
            stats["skipped"] += 1
            time.sleep(delay)
            continue

        if resp.status_code != 200:
            logger.info("Skipping (HTTP %d): %s", resp.status_code, url)
            log_skipped(url, f"HTTP {resp.status_code}", skip_log)
            resp.close()
            stats["skipped"] += 1
            time.sleep(delay)
            continue

        # ── Header check (before body download) ──────────────────────────────
        should_skip, skip_reason = is_skippable_response(resp)
        if should_skip:
            logger.info("Skipping (%s): %s", skip_reason, url)
            log_skipped(url, skip_reason, skip_log)
            resp.close()
            stats["skipped"] += 1
            time.sleep(delay)
            continue

        # Body is now safe to download
        content_type = resp.headers.get("content-type", "")

        # ── PDF via Content-Type (URL had no .pdf extension) ─────────────────
        if skip_pdfs and "application/pdf" in content_type:
            logger.debug("Skipping PDF by content-type: %s", url)
            log_skipped(url, "pdf_skipped", skip_log)
            found_pdfs.add(url)
            resp.close()
            stats["skipped"] += 1
            time.sleep(delay)
            continue

        now_iso = datetime.now(timezone.utc).isoformat()
        links_found: list[str] = []
        extracted_text = ""
        page_title = ""
        doc_type = "webpage"

        # ── PDF ──────────────────────────────────────────────────────────────
        if is_pdf(url, content_type):
            doc_type = "pdf"
            extracted_text = extract_text_pdf(resp.content)
            page_title = Path(urlparse(url).path).name

            if len(extracted_text) < 100:
                log_skipped(url, "pdf_no_text", skip_log)
                stats["skipped"] += 1
                time.sleep(delay)
                continue

            stats["pdfs_processed"] += 1

        # ── HTML ─────────────────────────────────────────────────────────────
        else:
            try:
                soup = BeautifulSoup(resp.text, "html.parser")
            except Exception as exc:
                logger.warning("Parse error on %s: %s", url, exc)
                log_skipped(url, "parse_error", skip_log)
                stats["skipped"] += 1
                time.sleep(delay)
                continue

            title_tag = soup.find("title")
            page_title = title_tag.get_text(strip=True) if title_tag else ""
            extracted_text = extract_text_html(soup)

            if len(extracted_text) < 100:
                log_skipped(url, "too_short", skip_log)
                stats["skipped"] += 1
                time.sleep(delay)
                continue

            # Collect internal links (and PDF links)
            if depth < max_depth:
                for tag in soup.find_all("a", href=True):
                    href = tag["href"].strip()
                    try:
                        abs_url = urljoin(url, href)
                        parsed_abs = urlparse(abs_url)
                    except ValueError:
                        continue
                    # normalise: drop fragment
                    abs_url = abs_url.split("#")[0]
                    if not abs_url:
                        continue
                    if abs_url.startswith("http://"):
                        abs_url = "https://" + abs_url[7:]
                    if abs_url in visited:
                        continue
                    if parsed_abs.scheme not in ("http", "https"):
                        continue
                    if is_pdf(abs_url):
                        found_pdfs.add(abs_url)
                        if skip_pdfs:
                            continue
                    if is_internal(abs_url) or is_pdf(abs_url):
                        links_found.append(abs_url)
                        visited.add(abs_url)
                        queue.append((abs_url, depth + 1))

        # ── Build JSON record ─────────────────────────────────────────────────
        language = detect_language(extracted_text)
        content_type_label = classify_content(url, extracted_text)
        word_count = len(extracted_text.split())

        record = {
            "url": url,
            "page_title": page_title,
            "doc_type": doc_type,
            "crawl_date": now_iso,
            "extracted_text": extracted_text,
            "word_count": word_count,
            "links_found": links_found,
            "metadata": {
                "faculty": "wiwi",
                "language": language,
                "content_type": content_type_label,
            },
        }

        save_json(record, output_dir)
        stats["crawled"] += 1

        # ── ChromaDB ingestion ────────────────────────────────────────────────
        if collection is not None and model is not None:
            if not url_already_indexed(collection, url):
                chunks = chunk_text(extracted_text)
                meta_base = {
                    "source_url": url,
                    "page_title": page_title,
                    "doc_type": doc_type,
                    "crawl_date": now_iso,
                    "content_type": content_type_label,
                    "faculty": "wiwi",
                    "language": language,
                    # Webinhalte sind nicht studiengangsspezifisch -> "all", damit
                    # sie im Studiengang-$or-Filter (app/rag.py) erscheinen.
                    "program": "all",
                }
                n = store_chunks(collection, model, chunks, meta_base)
                stats["chunks_stored"] += n
            else:
                logger.debug("Already indexed, skipping ChromaDB: %s", url)

        time.sleep(delay)

    if found_pdfs:
        pdf_out = output_dir / "found_pdfs.txt"
        pdf_out.write_text("\n".join(sorted(found_pdfs)) + "\n", encoding="utf-8")
        logger.info("Wrote %d found PDF URLs to %s", len(found_pdfs), pdf_out)

    remaining = len(queue)
    if remaining > 0:
        logger.info("Stop reason: PAGE LIMIT reached — %d URLs still in queue", remaining)
    else:
        logger.info("Stop reason: QUEUE EMPTY — all reachable URLs processed")
    stats["queue_remaining"] = remaining

    return stats

# ---------------------------------------------------------------------------
# Module ratings
# ---------------------------------------------------------------------------

MODULE_RATINGS_TEMPLATE = {
    "modules": [
        {
            "module_name": "Investition und Finanzierung",
            "module_id": "2530550",
            "rating": 4.2,
            "difficulty": "mittel",
            "workload_hours_per_week": 8,
            "exam_type": "Klausur",
            "recommendation": (
                "Sehr empfehlenswert als Einstieg in Finance. "
                "Guter Überblick, faire Klausur."
            ),
            "tips": "Altklausuren lösen reicht meistens aus.",
            "source": "Studierendenbewertung (manuell gepflegt)",
            "tags": ["Finance", "Pflicht", "Bachelor"],
        },
        {
            "module_name": "Grundlagen der BWL",
            "module_id": "2500010",
            "rating": 3.8,
            "difficulty": "leicht",
            "workload_hours_per_week": 6,
            "exam_type": "Klausur",
            "recommendation": (
                "Guter Pflichtstart. Breiter Überblick über alle BWL-Bereiche."
            ),
            "tips": "Skript ausreicht; Folien durcharbeiten.",
            "source": "Studierendenbewertung (manuell gepflegt)",
            "tags": ["BWL", "Pflicht", "Bachelor"],
        },
        {
            "module_name": "Statistik",
            "module_id": "2500090",
            "rating": 3.5,
            "difficulty": "schwer",
            "workload_hours_per_week": 12,
            "exam_type": "Klausur",
            "recommendation": (
                "Wichtige Grundlage, aber anspruchsvoll. "
                "Übungsaufgaben regelmäßig bearbeiten."
            ),
            "tips": "Tutorien besuchen, früh anfangen zu üben.",
            "source": "Studierendenbewertung (manuell gepflegt)",
            "tags": ["Methodik", "Pflicht", "Bachelor"],
        },
    ]
}


def create_module_ratings_template(output_dir: Path) -> Path:
    """Write the module_ratings.json template if it does not already exist."""
    output_dir.mkdir(parents=True, exist_ok=True)
    path = output_dir / "module_ratings.json"
    if not path.exists():
        path.write_text(
            json.dumps(MODULE_RATINGS_TEMPLATE, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        logger.info("Created module_ratings.json template at %s", path)
    else:
        logger.info("module_ratings.json already exists at %s — not overwritten", path)
    return path


def inject_module_ratings(
    ratings_path: Path,
    chroma_dir: str,
) -> int:
    """
    Read module_ratings.json and upsert each module as a rich text chunk
    into ChromaDB so KIRA can answer questions like
    'Wie wird Modul X bewertet?'
    """
    if not _HAVE_CHROMA or not _HAVE_ST:
        logger.error("chromadb or sentence-transformers not available")
        return 0

    if not ratings_path.exists():
        logger.error("module_ratings.json not found at %s", ratings_path)
        return 0

    data = json.loads(ratings_path.read_text(encoding="utf-8"))
    modules = data.get("modules", [])

    model = SentenceTransformer("paraphrase-multilingual-MiniLM-L12-v2")
    _, collection = get_or_create_collection(chroma_dir)

    now_iso = datetime.now(timezone.utc).isoformat()
    inserted_total = 0

    for mod in modules:
        name = mod.get("module_name", "Unbekanntes Modul")
        mod_id = mod.get("module_id", "")
        rating = mod.get("rating", "N/A")
        difficulty = mod.get("difficulty", "")
        workload = mod.get("workload_hours_per_week", "")
        exam = mod.get("exam_type", "")
        recommendation = mod.get("recommendation", "")
        tips = mod.get("tips", "")
        tags = ", ".join(mod.get("tags", []))
        source = mod.get("source", "manuell gepflegt")

        chunk_text_str = (
            f"Modul: {name} (ID: {mod_id})\n"
            f"Bewertung: {rating}/5 — Schwierigkeit: {difficulty}\n"
            f"Arbeitsaufwand: ca. {workload} Stunden/Woche\n"
            f"Prüfungsform: {exam}\n"
            f"Empfehlung: {recommendation}\n"
            f"Tipps: {tips}\n"
            f"Kategorie: {tags}\n"
            f"Quelle: {source}"
        )

        chunk_id = hashlib.md5(f"module_rating::{mod_id}::{name}".encode()).hexdigest()
        meta = {
            "source_url": f"module_ratings:{mod_id}",
            "page_title": name,
            "doc_type": "module_rating",
            "crawl_date": now_iso,
            "content_type": "module_rating",
            "faculty": "wiwi",
            "language": "de",
            "chunk_index": 0,
            "program": "all",
        }

        try:
            embedding = model.encode([chunk_text_str], show_progress_bar=False).tolist()
            collection.upsert(
                ids=[chunk_id],
                embeddings=embedding,
                documents=[chunk_text_str],
                metadatas=[meta],
            )
            logger.info("Injected module rating: %s (%.1f/5)", name, rating)
            inserted_total += 1
        except Exception as exc:
            logger.error("Failed to inject module '%s': %s", name, exc)

    logger.info("Module ratings injected: %d", inserted_total)
    return inserted_total

# ---------------------------------------------------------------------------
# Fill ChromaDB from saved JSON files
# ---------------------------------------------------------------------------

def fill_db_from_crawled(output_dir: Path, chroma_dir: str) -> int:
    """
    Read all JSON files previously saved by crawl() and embed them into ChromaDB.
    Already-indexed URLs are skipped.  Returns total chunks inserted.
    """
    if not _HAVE_ST or not _HAVE_CHROMA:
        logger.error("sentence-transformers or chromadb not available — cannot fill DB")
        return 0

    json_files = sorted(output_dir.glob("*.json"))
    if not json_files:
        logger.error("No JSON files found in %s — run the crawler first", output_dir)
        return 0

    logger.info("Loading SentenceTransformer model …")
    model = SentenceTransformer("paraphrase-multilingual-MiniLM-L12-v2")
    _, collection = get_or_create_collection(chroma_dir)

    total_inserted = 0
    for path in json_files:
        try:
            record = json.loads(path.read_text(encoding="utf-8"))
        except Exception as exc:
            logger.warning("Could not read %s: %s", path.name, exc)
            continue

        url = record.get("url", "")
        if not url:
            continue
        if url_already_indexed(collection, url):
            logger.debug("Already indexed, skipping: %s", url)
            continue

        text = record.get("extracted_text", "")
        if len(text) < 100:
            continue

        meta_base = {
            "source_url": url,
            "page_title": record.get("page_title", ""),
            "doc_type": record.get("doc_type", "webpage"),
            "crawl_date": record.get("crawl_date", ""),
            "content_type": record.get("metadata", {}).get("content_type", "general"),
            "faculty": record.get("metadata", {}).get("faculty", "wiwi"),
            "language": record.get("metadata", {}).get("language", "de"),
            "program": "all",
        }
        chunks = chunk_text(text)
        n = store_chunks(collection, model, chunks, meta_base)
        total_inserted += n
        logger.info("Indexed %s — %d chunks", url, n)

    logger.info("fill-db complete: %d chunks inserted", total_inserted)
    return total_inserted


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def build_arg_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description="KIRA Web Crawler — KIT WiWi-Fakultät",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    p.add_argument(
        "--urls",
        nargs="+",
        default=[
            # WiWi Hauptseiten
            "https://www.wiwi.kit.edu/",
            "https://www.wiwi.kit.edu/studium.php",
            "https://www.wiwi.kit.edu/forschung.php",
            "https://www.wiwi.kit.edu/fakultaet.php",
            # WiWi Studium & Prüfungen
            "https://www.wiwi.kit.edu/Bachelorstudiengaenge.php",
            "https://www.wiwi.kit.edu/Masterstudiengaenge.php",
            "https://www.wiwi.kit.edu/Studien-_und_Pruefungsplanung.php",
            "https://www.wiwi.kit.edu/lehrePruefungen.php",
            "https://www.wiwi.kit.edu/pruefSekretariat.php",
            "https://www.wiwi.kit.edu/pruefungstermine.php",
            "https://www.wiwi.kit.edu/studienstart.php",
            "https://www.wiwi.kit.edu/studienProg.php",
            "https://www.wiwi.kit.edu/abschlussarbeiten.php",
            # WiWi International & Aktuelles
            "https://www.wiwi.kit.edu/internationalRelations.php",
            "https://www.wiwi.kit.edu/news.php",
            "https://www.wiwi.kit.edu/veranstaltungen.php",
            # Externe Seeds
            "https://www.sle.kit.edu",
            "https://www.kit.edu/",
            "https://www.asta-kit.de/",
            # Studium
            "https://fachschaft.org/studium/",
            "https://fachschaft.org/studium/bachelor/",
            "https://fachschaft.org/studium/master/",
            "https://fachschaft.org/studium/praktikum/",
            "https://fachschaft.org/studium/abschlussarbeit/",
            "https://fachschaft.org/studium/ausland/",
            "https://fachschaft.org/studium/studienbeginn/",
            # Beratung & Support
            "https://fachschaft.org/sprechstunde/",
            "https://fachschaft.org/sprechstunde/klausurenangebot/",
            "https://fachschaft.org/sprechstunde/pruefungsprotokolle/",
            "https://fachschaft.org/studienberatung/",
            "https://fachschaft.org/unterstuetzung-im-studium/",
            "https://fachschaft.org/internationale-studierende/",
            # Studieninteressenten
            "https://fachschaft.org/unsere-studiengaenge/",
            "https://fachschaft.org/bewerbung-und-zulassung/",
            # FAQs
            "https://fachschaft.org/faq_category/faq-studienberatung/",
            # Neu: tiefer gecrawlt
            "https://www.zak.kit.edu/",
            "https://www.hoc.kit.edu/",
            # HOC
            "https://www.hoc.kit.edu/",
            "https://www.hoc.kit.edu/sq_angebote.php",
            "https://www.hoc.kit.edu/schluesselqualifikationen.php",
            "https://www.hoc.kit.edu/sq-wahlbereiche.php",
            "https://studium.hoc.kit.edu/hocampus/",
        ],
        help="Seed URLs to start crawling from",
    )
    p.add_argument("--max-pages", type=int, default=4000)
    p.add_argument("--max-depth", type=int, default=3)
    p.add_argument("--delay", type=float, default=0.5, help="Seconds between requests")
    p.add_argument(
        "--output-dir",
        default=str(PROJECT_ROOT / "crawled_data"),
        help="Directory for JSON output files",
    )
    p.add_argument(
        "--chroma-dir",
        default=str(PROJECT_ROOT / "chroma_db"),
        help="ChromaDB persist directory",
    )
    p.add_argument(
        "--skip-pdfs",
        action="store_true",
        default=True,
        help="Skip PDF files during crawl (upload manually instead)",
    )
    p.add_argument(
        "--inject-ratings",
        action="store_true",
        help="Load module_ratings.json into ChromaDB and exit",
    )
    p.add_argument(
        "--create-ratings-template",
        action="store_true",
        help="Write a starter module_ratings.json template and exit",
    )
    p.add_argument(
        "--fill-db",
        action="store_true",
        help="Embed all previously crawled JSON files into ChromaDB and exit",
    )
    return p


def main() -> None:
    args = build_arg_parser().parse_args()
    output_dir = Path(args.output_dir)
    chroma_dir = str(args.chroma_dir)

    # ── Template creation ────────────────────────────────────────────────────
    if args.create_ratings_template:
        create_module_ratings_template(output_dir)
        return

    # ── Ratings injection ─────────────────────────────────────────────────────
    if args.inject_ratings:
        ratings_path = output_dir / "module_ratings.json"
        if not ratings_path.exists():
            logger.info("module_ratings.json missing — creating template first")
            create_module_ratings_template(output_dir)
        n = inject_module_ratings(ratings_path, chroma_dir)
        print(f"\nModule ratings injected into ChromaDB: {n}")
        return

    # ── Fill DB from previously crawled JSONs ────────────────────────────────
    if args.fill_db:
        n = fill_db_from_crawled(output_dir, chroma_dir)
        print(f"\nChunks inserted into ChromaDB: {n}")
        return

    # ── Create ratings template if it doesn't exist yet ─────────────────────
    create_module_ratings_template(output_dir)

    # ── Main crawl ────────────────────────────────────────────────────────────
    logger.info(
        "Starting crawl: seeds=%s  max_pages=%d  max_depth=%d  delay=%.1fs",
        args.urls,
        args.max_pages,
        args.max_depth,
        args.delay,
    )
    start_time = time.time()
    stats = crawl(
        start_urls=args.urls,
        output_dir=output_dir,
        chroma_dir=chroma_dir,
        max_pages=args.max_pages,
        max_depth=args.max_depth,
        delay=args.delay,
        skip_pdfs=args.skip_pdfs,
    )
    elapsed = time.time() - start_time

    print("\n" + "=" * 60)
    print("KIRA Crawl Summary")
    print("=" * 60)
    remaining = stats.get("queue_remaining", 0)
    stop_reason = f"Page limit ({remaining} URLs remaining in queue)" if remaining > 0 else "Queue empty"

    print(f"  Pages crawled:      {stats['crawled']}")
    print(f"  Pages skipped:      {stats['skipped']}")
    print(f"  PDFs processed:     {stats['pdfs_processed']}")
    print(f"  Chunks in ChromaDB: {stats['chunks_stored']}")
    print(f"  Stop reason:        {stop_reason}")
    print(f"  Time elapsed:       {elapsed:.1f}s")
    print(f"  Output dir:         {output_dir}")
    print(f"  ChromaDB dir:       {chroma_dir}")
    print("=" * 60)


if __name__ == "__main__":
    main()