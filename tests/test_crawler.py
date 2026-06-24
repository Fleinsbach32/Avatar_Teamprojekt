import sys
from pathlib import Path

# scripts/ ist kein Paket -> Pfad ergänzen. chromadb/sentence_transformers sind
# in conftest.py gemockt; requests/bs4/fitz/langdetect sind installiert.
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import crawler  # noqa: E402


# ── is_internal / _strip_www (Bugfix: lstrip -> removeprefix) ──
def test_strip_www_removes_prefix_only():
    assert crawler._strip_www("www.wiwi.kit.edu") == "wiwi.kit.edu"
    assert crawler._strip_www("wiwi.kit.edu") == "wiwi.kit.edu"
    # Regression: das alte lstrip("www.") haette "iwi.kit.edu" geliefert
    assert crawler._strip_www("www.wiwi.kit.edu") != "iwi.kit.edu"


def test_is_internal_www_and_plain():
    assert crawler.is_internal("https://www.wiwi.kit.edu/studium.php")
    assert crawler.is_internal("https://wiwi.kit.edu/lehrePruefungen.php")


def test_is_internal_added_domains():
    assert crawler.is_internal("https://fachschaft.org/studium/")
    assert crawler.is_internal("https://www.hoc.kit.edu/sq_angebote.php")
    assert crawler.is_internal("https://zak.kit.edu/")


def test_is_internal_excludes_external_and_broad_kit():
    assert not crawler.is_internal("https://www.google.com/")
    # breite www.kit.edu bleibt bewusst seed-only (nicht intern)
    assert not crawler.is_internal("https://www.kit.edu/index.php")


# ── store_chunks: program/Metadaten landen im upsert ──────
class _Emb(list):
    def tolist(self):
        return [list(x) for x in self]


class _FakeModel:
    def encode(self, docs, show_progress_bar=False):
        return _Emb([[0.0] for _ in docs])


class _FakeCollection:
    def __init__(self):
        self.metadatas = None

    def upsert(self, ids, embeddings, documents, metadatas):
        self.metadatas = metadatas


def test_store_chunks_propagates_program_metadata():
    col, model = _FakeCollection(), _FakeModel()
    n = crawler.store_chunks(col, model, ["Chunk eins", "Chunk zwei"],
                             {"source_url": "https://x", "program": "all", "doc_type": "webpage"})
    assert n == 2
    assert col.metadatas is not None
    assert all(m["program"] == "all" for m in col.metadatas)
    assert col.metadatas[0]["chunk_index"] == 0
    assert col.metadatas[1]["chunk_index"] == 1


# ── reine Hilfsfunktionen ─────────────────────────────────
def test_classify_content():
    assert crawler.classify_content("https://x/pruefungsamt.php", "") == "pruefungsamt"
    assert crawler.classify_content("https://x/datei.pdf", "") == "pdf"
    assert crawler.classify_content("https://x/normal", "neutraler Text") == "general"


def test_chunk_text_produces_nonempty_chunks():
    chunks = crawler.chunk_text("Das ist ein Satz. " * 200, chunk_tokens=50, overlap_tokens=10)
    assert chunks
    assert all(len(c.strip()) >= 50 for c in chunks)


# ── _normalize_text ───────────────────────────────────────
def test_normalize_text_removes_soft_hyphen_and_nbsp():
    raw = "Fakult\xadät\xa0der\xa0Wirtschaft"
    assert crawler._normalize_text(raw) == "Fakultät der Wirtschaft"


def test_normalize_text_collapses_whitespace():
    assert crawler._normalize_text("a   b\n\nc\t d") == "a b c d"


def test_normalize_text_strips_control_chars():
    # \x00 und \x07 werden entfernt (kein Space-Ersatz)
    assert crawler._normalize_text("Text\x00mit\x07Steuerzeichen") == "TextmitSteuerzeichen"


# ── _decode_response (Encoding-Fix) ───────────────────────
class _FakeResp:
    def __init__(self, content: bytes, apparent_encoding: str = "utf-8"):
        self.content = content
        self.apparent_encoding = apparent_encoding


def test_decode_response_utf8_without_charset_header():
    # UTF-8-Bytes ohne charset-Header → korrekte Umlaute, kein Mojibake/U+FFFD
    html = "<html><body><p>Prüfungsamt Fakultät Wirtschaft</p></body></html>"
    resp = _FakeResp(html.encode("utf-8"))
    soup = crawler._decode_response(resp)
    text = soup.get_text()
    assert "Prüfungsamt" in text
    assert "Fakultät" in text
    assert "�" not in text


# ── extract_text_html: Boilerplate ────────────────────────
def test_extract_text_html_drops_div_navigation():
    from bs4 import BeautifulSoup
    html = """
    <html><body>
      <div class="main-navigation">Startseite Über uns Kontakt</div>
      <div id="cookie-banner">Wir nutzen Cookies</div>
      <main><p>Die Bewerbungsfrist endet am 15. Juli.</p></main>
      <footer class="site-footer">Impressum Datenschutz</footer>
    </body></html>
    """
    soup = BeautifulSoup(html, "html.parser")
    text = crawler.extract_text_html(soup)
    assert "Bewerbungsfrist endet am 15. Juli" in text
    assert "Über uns" not in text
    assert "Cookies" not in text
    assert "Impressum" not in text


# ── Qualitätsfilter + Dedup ───────────────────────────────
def test_is_low_quality_chunk_rejects_short_and_fffd():
    assert crawler._is_low_quality_chunk("Zu kurz hier.")            # < 8 Wörter
    assert crawler._is_low_quality_chunk("Text mit � Loch drin hier weiter mehr")  # U+FFFD
    assert not crawler._is_low_quality_chunk(
        "Die Bewerbungsfrist für das Wintersemester endet jedes Jahr am fünfzehnten Juli."
    )


def test_is_low_quality_chunk_rejects_symbol_soup():
    # Überwiegend Nicht-Wort-Tokens (Navigation/Symbole)
    assert crawler._is_low_quality_chunk("» | › • — / \\ > < — » Home | Kontakt | Impressum | A")


def test_clean_chunks_dedups_identical_content():
    seen = set()
    text = "Die Bewerbungsfrist endet am fünfzehnten Juli jedes Jahr im Sommer regelmäßig. " * 10
    first = crawler.clean_chunks(text, seen)
    second = crawler.clean_chunks(text, seen)   # gleiche Inhalte → bereits gesehen
    assert first              # erster Lauf liefert Chunks
    assert second == []       # zweiter Lauf komplett dedupliziert


def test_clean_chunks_shared_seen_set_across_pages():
    # Zwei "Seiten" mit identischem Inhalt → zweite trägt nichts mehr bei
    seen = set()
    page = "Das Studienbüro hilft bei Fragen zu Anmeldung Prüfung und Fristen jederzeit gern. " * 8
    a = crawler.clean_chunks(page, seen)
    b = crawler.clean_chunks(page, seen)
    assert a and not b
