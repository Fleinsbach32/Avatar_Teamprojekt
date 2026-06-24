import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import eval_rag  # noqa: E402


def test_facts_present_all_found():
    kontext = "Das Modul Mathematik 1 umfasst 7,5 ECTS und ist Pflicht."
    hits, total = eval_rag._facts_present(["Mathematik 1", "ECTS"], kontext)
    assert (hits, total) == (2, 2)


def test_facts_present_case_and_whitespace_insensitive():
    kontext = "Die   BEWERBUNG  läuft über das Portal."
    hits, total = eval_rag._facts_present(["bewerbung"], kontext)
    assert (hits, total) == (1, 1)


def test_facts_present_missing_fact():
    kontext = "Nur allgemeiner Text ohne den gesuchten Begriff."
    hits, total = eval_rag._facts_present(["Erasmus"], kontext)
    assert (hits, total) == (0, 1)
