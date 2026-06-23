# Design: Railway + Google Drive ChromaDB Bootstrap

**Datum:** 2026-06-23  
**Status:** Approved

## Problem

Die ChromaDB (`chroma_db/`) ist 6,8 GB groß, im `.gitignore` und kann deshalb nicht im Docker-Image ausgeliefert werden. Auf Railway (cloud deployment) muss die Wissensbasis trotzdem verfügbar sein, ohne manuellen Upload-Step bei jedem Deploy.

## Lösung: Volume-backed Startup-Bootstrap

Beim ersten Start lädt ein kleines Modul die DB von Google Drive auf ein Railway Persistent Volume. Folgende Starts überspringen den Download (Volume ist befüllt). Lokal und in Tests ist es ein No-Op.

## Env-Variablen (neu)

| Variable | Beschreibung | Default |
|---|---|---|
| `CHROMA_DB_DIR` | Pfad zur ChromaDB | `chroma_db` |
| `CHROMA_DRIVE_FILE_ID` | Google Drive File-ID des Archivs | *(nicht gesetzt → No-Op)* |

Railway-Config: `CHROMA_DB_DIR=/data/chroma_db`, Volume auf `/data`, `CHROMA_DRIVE_FILE_ID=<ID>`.

## Architektur

### Neues Modul: `app/bootstrap.py`

Einzige öffentliche Funktion: `ensure_chroma_db(db_dir: str) -> None`

**Logik:**
1. `db_dir` existiert und ist nicht leer → return (No-Op). Deckt lokale Entwicklung (6,8 GB liegt schon da) und alle Folge-Deployments ab.
2. `db_dir` fehlt/leer + `CHROMA_DRIVE_FILE_ID` nicht gesetzt → Warning loggen + return. Lokale Entwicklung ohne Wissensbasis (Tests, CI).
3. `db_dir` fehlt/leer + `CHROMA_DRIVE_FILE_ID` gesetzt → Download via **gdown** in Temp, entpacken nach `db_dir`, Temp aufräumen.

**Archivformat:** Erkannt per Dateiendung aus dem Drive-Dateinamen (`.zip` → `zipfile`, `.tar.gz` → `tarfile`). Standard: `.tar.gz` (kleineres Ergebnis via gzip).

**Atomizität:** Entpacken in `db_dir.tmp`, dann `rename()` zum Zielpfad. Temp wird in `finally` bereinigt.

**Fehlerverhalten:** Bei Download- oder Entpack-Fehler → Exception werfen (sichtbarer Deploy-Fehler statt stiller leerer Wissensbasis).

### Geänderte Datei: `app/rag.py`

`CHROMA_DB_DIR = os.getenv("CHROMA_DB_DIR", "chroma_db")` ersetzt den Hardcode-Pfad.

`ensure_chroma_db(CHROMA_DB_DIR)` wird **direkt vor** `PersistentClient(path=CHROMA_DB_DIR)` aufgerufen — greift bei jedem Importpfad (App-Start, Skripte, Tests).

### Geänderte Datei: `requirements.txt`

`gdown` wird ergänzt.

## Datenfluss

```
Railway Boot
  └─ import app.rag
       └─ ensure_chroma_db("/data/chroma_db")
            ├─ Volume leer? → gdown lädt chroma_db.tar.gz
            │                 → tar entpackt nach /data/chroma_db.tmp
            │                 → rename → /data/chroma_db
            └─ Volume befüllt? → skip
  └─ PersistentClient(path="/data/chroma_db")
  └─ App ready
```

Zweiter und jeder weitere Boot: `ensure_chroma_db` ist ein No-Op (Verzeichnis existiert).

## Tests: `tests/test_bootstrap.py`

Alle Tests mocken `gdown.download` und `os.rename`:

1. **Verzeichnis existiert + nicht leer** → `gdown.download` wird nicht aufgerufen.
2. **Verzeichnis fehlt + keine FILE_ID** → Warnung, kein Download, kein Fehler.
3. **Verzeichnis fehlt + FILE_ID gesetzt** → `gdown.download` aufgerufen, Zielverzeichnis entsteht.
4. **Download schlägt fehl** → Exception propagiert.

## Außerhalb des Scope

Laut Nutzerentscheidung **nicht implementiert:**
- Admin-Reload-Endpoint (`POST /admin/reload-db`)
- Upload-Skript (`scripts/upload_db.py`)
- `railway.json` / `Procfile`

## Manueller Vorab-Schritt (kein Code, nur Dokumentation)

```bash
# DB packen (einmalig lokal)
tar -czf chroma_db.tar.gz chroma_db/

# In Google Drive hochladen → "Jeder mit Link" → File-ID kopieren
# Railway: Volume auf /data mounten
# Railway Env: CHROMA_DB_DIR=/data/chroma_db, CHROMA_DRIVE_FILE_ID=<ID>
```
