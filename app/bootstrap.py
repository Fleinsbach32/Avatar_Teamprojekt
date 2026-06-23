# app/bootstrap.py
import logging
import os
import shutil
import tarfile
import tempfile
import zipfile


def ensure_chroma_db(db_dir: str) -> None:
    """Lädt ChromaDB von Google Drive, falls sie lokal fehlt (Railway-Deployment).

    No-Op wenn:
    - db_dir existiert und ist nicht leer  (lokale Dev-Env oder Folge-Boot)
    - CHROMA_DRIVE_FILE_ID nicht gesetzt   (CI / lokale Dev ohne Wissensbasis)
    """
    if os.path.isdir(db_dir) and os.listdir(db_dir):
        return

    file_id = os.getenv("CHROMA_DRIVE_FILE_ID")
    if not file_id:
        logging.warning(
            f"ChromaDB-Verzeichnis '{db_dir}' fehlt und CHROMA_DRIVE_FILE_ID ist nicht "
            "gesetzt — starte mit leerer Wissensbasis."
        )
        return

    logging.info(f"ChromaDB nicht gefunden — lade von Google Drive (File-ID: {file_id}) …")

    import gdown  # lazy: nur beim echten Download erforderlich

    tmp_dir = tempfile.mkdtemp(prefix="chroma_download_")
    tmp_extract = db_dir + ".tmp"
    shutil.rmtree(tmp_extract, ignore_errors=True)  # evict stale .tmp from prior crash
    try:
        url = f"https://drive.google.com/uc?id={file_id}"
        tmp_archive = os.path.join(tmp_dir, "chroma_archive")
        out = gdown.download(url, tmp_archive, quiet=False, fuzzy=True)
        if out is None:
            raise RuntimeError(
                "gdown.download hat None zurückgegeben — Download fehlgeschlagen."
            )

        if tarfile.is_tarfile(out):
            with tarfile.open(out) as tf:
                tf.extractall(tmp_extract, filter="data")
        elif zipfile.is_zipfile(out):
            with zipfile.ZipFile(out) as zf:
                for member in zf.namelist():
                    if os.path.isabs(member) or ".." in member.split("/"):
                        raise RuntimeError(f"Unsicherer Pfad im Archiv: {member}")
                zf.extractall(tmp_extract)
        else:
            raise RuntimeError(f"Unbekanntes Archivformat: {out}")

        # Archiv gepackt als chroma_db/ → inneres Verzeichnis hochziehen
        entries = os.listdir(tmp_extract)
        if not entries:
            raise RuntimeError("Archiv ist leer — keine Dateien entpackt.")
        inner = os.path.join(tmp_extract, entries[0])
        if len(entries) == 1 and os.path.isdir(inner):
            os.rename(inner, db_dir)
            shutil.rmtree(tmp_extract, ignore_errors=True)
        else:
            os.rename(tmp_extract, db_dir)

        logging.info(f"ChromaDB erfolgreich nach '{db_dir}' entpackt.")
    except Exception:
        shutil.rmtree(tmp_extract, ignore_errors=True)
        raise
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)
