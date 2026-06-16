import sys
from pathlib import Path

# scripts/ ist kein Paket -> Pfad ergänzen, dann fill_db importieren.
# chromadb etc. werden in conftest.py gemockt; chunk_handbook ist eine reine Funktion.
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from fill_db import chunk_handbook, MODULE_ANCHOR_RE  # noqa: E402


SAMPLE = (
    "Inhaltsverzeichnis-Rauschen das vor dem ersten Modul steht .......... 5\n"
    "Modul: Angewandte Informatik [M-WIWI-101430]\n"
    + "Dieses Modul behandelt Themen der angewandten Informatik. " * 3 + "\n"
    "Modul: Mathematik II [T-MATH-109944]\n"
    + "Inhalte der Teilleistung Mathematik zwei. " * 3
)


def test_anchor_regex_matches_m_and_t_and_english():
    ids = [m.group(2) for m in MODULE_ANCHOR_RE.finditer(SAMPLE)]
    assert "M-WIWI-101430" in ids
    assert "T-MATH-109944" in ids
    # englische Schreibweise "Module:"
    en = "Module: Electives in Informatics [M-INFO-107201]"
    assert MODULE_ANCHOR_RE.search(en).group(2) == "M-INFO-107201"


def test_chunk_keeps_name_and_id_together():
    chunks = chunk_handbook(SAMPLE)
    c1 = [c for c in chunks if c[1] == "M-WIWI-101430"]
    c2 = [c for c in chunks if c[1] == "T-MATH-109944"]
    assert c1 and c2
    assert "Angewandte Informatik" in c1[0][0] and "M-WIWI-101430" in c1[0][0]
    assert "Mathematik II" in c2[0][0] and "T-MATH-109944" in c2[0][0]


def test_no_content_leak_between_modules():
    chunks = chunk_handbook(SAMPLE)
    c1 = next(c[0] for c in chunks if c[1] == "M-WIWI-101430")
    # Inhalt des zweiten Moduls darf nicht im Chunk des ersten landen
    assert "Teilleistung Mathematik" not in c1


def test_toc_noise_before_first_anchor_dropped():
    chunks = chunk_handbook(SAMPLE)
    assert all("Inhaltsverzeichnis-Rauschen" not in c[0] for c in chunks)


def test_no_anchor_returns_empty():
    assert chunk_handbook("Reiner Fliesstext ganz ohne Modul-Anker.") == []


def test_long_block_split_each_piece_has_header():
    long_body = "Modul: Riesenmodul [M-WIWI-999999]\n" + ("Sehr viel Inhalt hier. " * 400)
    chunks = chunk_handbook(long_body, max_chars=400)
    assert len(chunks) > 1
    for text, mid, name in chunks:
        assert mid == "M-WIWI-999999"
        assert "[M-WIWI-999999]" in text
        assert "Riesenmodul" in text
