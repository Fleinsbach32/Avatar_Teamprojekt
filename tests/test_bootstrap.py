# tests/test_bootstrap.py
import io
import os
import logging
import sys
import tarfile
from unittest.mock import MagicMock

import pytest


def test_no_download_when_db_exists(tmp_path):
    """Verzeichnis existiert und ist nicht leer → kein Download."""
    db_dir = tmp_path / "chroma_db"
    db_dir.mkdir()
    (db_dir / "chroma.sqlite3").write_bytes(b"x")

    mock_gdown = MagicMock()
    sys.modules["gdown"] = mock_gdown
    try:
        from app.bootstrap import ensure_chroma_db
        ensure_chroma_db(str(db_dir))
    finally:
        sys.modules.pop("gdown", None)

    mock_gdown.download.assert_not_called()


def test_no_download_without_file_id(tmp_path, monkeypatch, caplog):
    """Verzeichnis fehlt + CHROMA_DRIVE_FILE_ID nicht gesetzt → No-Op mit Warnung."""
    db_dir = tmp_path / "chroma_db"  # existiert nicht
    monkeypatch.delenv("CHROMA_DRIVE_FILE_ID", raising=False)

    mock_gdown = MagicMock()
    sys.modules["gdown"] = mock_gdown
    try:
        with caplog.at_level(logging.WARNING):
            from app.bootstrap import ensure_chroma_db
            ensure_chroma_db(str(db_dir))
    finally:
        sys.modules.pop("gdown", None)

    mock_gdown.download.assert_not_called()
    assert not db_dir.exists()
    assert any("CHROMA_DRIVE_FILE_ID" in r.message for r in caplog.records)


def test_download_and_extract_tar(tmp_path, monkeypatch):
    """Verzeichnis fehlt + FILE_ID gesetzt → gdown aufgerufen, Ziel entsteht."""
    db_dir = tmp_path / "chroma_db"
    monkeypatch.setenv("CHROMA_DRIVE_FILE_ID", "abc123")

    # Baue echtes tar.gz-Archiv: enthält chroma_db/chroma.sqlite3
    archive_path = tmp_path / "archive.tar.gz"
    with tarfile.open(str(archive_path), "w:gz") as tf:
        dir_info = tarfile.TarInfo(name="chroma_db")
        dir_info.type = tarfile.DIRTYPE
        tf.addfile(dir_info)
        data = b"fake-db"
        file_info = tarfile.TarInfo(name="chroma_db/chroma.sqlite3")
        file_info.size = len(data)
        tf.addfile(file_info, io.BytesIO(data))

    def fake_download(url, output, **kwargs):
        import shutil
        shutil.copy(str(archive_path), output)
        return output

    mock_gdown = MagicMock()
    mock_gdown.download.side_effect = fake_download
    sys.modules["gdown"] = mock_gdown
    try:
        from app.bootstrap import ensure_chroma_db
        ensure_chroma_db(str(db_dir))
    finally:
        sys.modules.pop("gdown", None)

    assert db_dir.exists()
    assert (db_dir / "chroma.sqlite3").exists()
    mock_gdown.download.assert_called_once()


def test_download_failure_raises(tmp_path, monkeypatch):
    """gdown.download gibt None zurück → RuntimeError wird propagiert."""
    db_dir = tmp_path / "chroma_db"
    monkeypatch.setenv("CHROMA_DRIVE_FILE_ID", "abc123")

    mock_gdown = MagicMock()
    mock_gdown.download.return_value = None
    sys.modules["gdown"] = mock_gdown
    try:
        from app.bootstrap import ensure_chroma_db
        with pytest.raises(RuntimeError, match="fehlgeschlagen"):
            ensure_chroma_db(str(db_dir))
    finally:
        sys.modules.pop("gdown", None)
