from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_start_scripts_exist():
    assert (ROOT / "start.ps1").is_file()
    assert (ROOT / "start.sh").is_file()


def test_start_ps1_contains_required_checks():
    content = (ROOT / "start.ps1").read_text(encoding="utf-8")
    assert "GOOGLE_API_KEY" in content
    assert "TAVUS_API_KEY" in content
    assert "fill_db.py" in content
    assert "chroma_db" in content
    assert "uvicorn" in content


def test_start_sh_contains_required_checks():
    content = (ROOT / "start.sh").read_text(encoding="utf-8")
    assert "GOOGLE_API_KEY" in content
    assert "TAVUS_API_KEY" in content
    assert "fill_db.py" in content
    assert "chroma_db" in content
    assert "uvicorn" in content


def test_readme_has_quickstart():
    content = (ROOT / "README.md").read_text(encoding="utf-8")
    assert "start.ps1" in content
    assert "start.sh" in content
