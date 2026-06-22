import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_faq_de_valid():
    """faq_de.json muss vorhanden, nicht leer und im erwarteten Schema sein."""
    p = ROOT / "data" / "faq_de.json"
    assert p.is_file(), "faq_de.json fehlt"
    data = json.loads(p.read_text(encoding="utf-8"))
    assert isinstance(data, list) and data, "faq_de.json ist leer"
    assert "question" in data[0] and "answer" in data[0]


def test_faq_eng_present_but_may_be_empty():
    """faq_eng.json ist aktuell ein leerer Platzhalter — darf leer sein,
    aber falls befüllt, muss das Schema stimmen."""
    p = ROOT / "data" / "faq_eng.json"
    assert p.is_file(), "faq_eng.json fehlt"
    raw = p.read_text(encoding="utf-8").strip()
    if raw:
        data = json.loads(raw)
        assert isinstance(data, list)
        if data:
            assert "question" in data[0] and "answer" in data[0]


def test_old_faq_json_removed():
    assert not (ROOT / "data" / "faq.json").exists()


def test_pdf_folder_has_handbooks():
    pdfs = list((ROOT / "data" / "pdfs").glob("*.pdf"))
    assert len(pdfs) >= 16


def test_no_duplicate_pdfs_in_data_root():
    """PDFs liegen nur noch in data/pdfs/, nicht direkt unter data/."""
    root_pdfs = list((ROOT / "data").glob("*.pdf"))
    assert root_pdfs == [], f"Unerwartete PDFs in data/: {root_pdfs}"


def test_no_stray_chroma_zip_in_root():
    assert not (ROOT / "chroma_db.zip").exists()


def test_crawler_moved_to_scripts():
    assert (ROOT / "scripts" / "crawler.py").is_file()
    assert (ROOT / "scripts" / "crawl.ps1").is_file()
    assert not (ROOT / "crawler.py").exists()
    # crawl.ps1 in root is an intentional thin wrapper forwarding to scripts/crawl.ps1
