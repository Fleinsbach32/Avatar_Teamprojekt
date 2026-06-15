from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_run_ps1_exists():
    assert (ROOT / "run.ps1").is_file()


def test_run_ps1_contains_required_checks():
    content = (ROOT / "run.ps1").read_text(encoding="utf-8")
    assert "GOOGLE_API_KEY" in content
    assert "fill_db.py" in content
    assert "chroma_db" in content
    assert "uvicorn" in content
    assert "ngrok" in content
    assert "app.main:app" in content


def test_old_start_scripts_removed():
    assert not (ROOT / "start.ps1").exists()
    assert not (ROOT / "start.sh").exists()
    assert not (ROOT / "setup.ps1").exists()


def test_readme_has_run_ps1():
    content = (ROOT / "README.md").read_text(encoding="utf-8")
    assert "run.ps1" in content
