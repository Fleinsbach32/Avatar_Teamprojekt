# Teil-Projekt 1 — Aufräumen & Struktur: Design

**Datum:** 2026-06-16
**Status:** Genehmigt
**Branch:** feature/tavus
**Kontext:** Erstes von vier Teil-Projekten (Reihenfolge 1→4→2→3). TP1 schafft eine
saubere, stabile Struktur als Basis für die folgenden Teil-Projekte (UI-Button,
RAG-Kern, Crawler).

---

## 1. Ziel

Den Projekt-Root aufräumen, die durch den letzten Merge entstandenen
Inkonsistenzen beseitigen und den durch die Umstrukturierung eingeschleppten
Bug in `fill_db.py` beheben — ohne Verhaltensänderung an der laufenden App.

## 2. Ausgangslage (Funde)

- `crawler.py` und `crawl.ps1` liegen im Root; `fill_db.py` wurde bereits nach
  `scripts/` verschoben → inkonsistent.
- `chroma_db.zip` (142 MB) liegt im Root (von einer früheren Session erzeugt).
- PDFs liegen doppelt: 15 byte-identische Kopien direkt unter `data/` **und** in
  `data/pdfs/` (16 Dateien inkl. `mhb_wiing_BSc_de_aktuell.pdf`, das nur in
  `data/pdfs/` existiert). Identität per md5 verifiziert.
- **Bug:** `scripts/fill_db.py` liest `data/faq.json` (Zeile 11), aber diese
  Datei wurde in `data/faq_de.json` + `data/faq_eng.json` aufgeteilt →
  `FileNotFoundError` beim DB-Befüllen über `run.ps1`.

## 3. Änderungen

### 3.1 Dateibewegungen / Löschungen

| Aktion | Pfad |
|---|---|
| Verschieben | `crawler.py` → `scripts/crawler.py` |
| Verschieben | `crawl.ps1` → `scripts/crawl.ps1` |
| Löschen | `chroma_db.zip` (Root) — aus `chroma_db/` neu erzeugbar |
| Löschen | die 15 byte-identischen `data/*.pdf` (siehe Liste unten) |
| Behalten | `data/pdfs/` (16 PDFs, einzige Quelle, von `fill_db.py` genutzt) |
| Behalten | `data/faq_de.json`, `data/faq_eng.json` |

Zu löschende Root-PDFs (alle md5-identisch mit `data/pdfs/`):
`Arbeitsprogramm_nachStuPa.pdf`, `Handreichung-Einsicht-in-Pruefungsunterlagen.pdf`,
`Handreichung_GenerativeKI_WIWI.pdf`, `How to Studienstart_2025.pdf`,
`TVWL_BSc_SPO2015-Praktikantenrichtlinien_Stand_3-2020.pdf`,
`WiIngBSc_SPO2015-PraktikantenrichtlinienStand_3-2020.pdf`,
`mhb_de_BSc_de_aktuell.pdf`, `mhb_de_MSc_en_aktuell.pdf`,
`mhb_ieam_MSc_en_aktuell.pdf`, `mhb_tvwl_BSc_de_aktuell.pdf`,
`mhb_tvwl_MSc_de_aktuell.pdf`, `mhb_wiinf_BSc_de_aktuell.pdf`,
`mhb_wiinf_MSc_de_aktuell.pdf`, `mhb_wiing_MSc_de_aktuell.pdf`,
`mhb_wima_MSc_de_aktuell.pdf`

> Diese 15 Root-PDFs sind untracked (git kennt sie nicht), daher reicht ein
> Dateisystem-Löschen; `git rm` ist nicht nötig.

### 3.2 `scripts/crawler.py` — Default-Pfade auf Projekt-Root

`crawler.py` setzt aktuell:
```python
default=str(Path(__file__).parent / "crawled_data")   # --output-dir
default=str(Path(__file__).parent / "chroma_db")       # --chroma-dir
```
Nach dem Verschieben nach `scripts/` würde `Path(__file__).parent` auf `scripts/`
zeigen → `scripts/chroma_db` (falsch; `app/rag.py` öffnet `chroma_db` relativ zum
Projekt-Root). Fix: ein `PROJECT_ROOT = Path(__file__).resolve().parent.parent`
definieren und beide Defaults darauf beziehen:
```python
PROJECT_ROOT = Path(__file__).resolve().parent.parent
...
default=str(PROJECT_ROOT / "crawled_data")
default=str(PROJECT_ROOT / "chroma_db")
```

### 3.3 `scripts/crawl.ps1` — auf Projekt-Root operieren

- `Set-Location $PSScriptRoot` → `Set-Location (Split-Path $PSScriptRoot -Parent)`
  (damit `requirements.txt`, `.pip-stamp`, `chroma_db/` am Root korrekt sind).
- Alle vier Aufrufe `python crawler.py …` → `python scripts/crawler.py …`.

### 3.4 `scripts/fill_db.py` — FAQ-Bug-Fix + robuste Pfade

- `PROJECT_ROOT = Path(__file__).resolve().parent.parent` einführen; `CHROMA_PATH`,
  `FAQ`-Pfade und `PDF_FOLDER` darauf beziehen (läuft dann unabhängig vom cwd).
- Statt der einen `data/faq.json` **beide** Dateien laden:
  ```python
  FAQ_FILES = [
      (PROJECT_ROOT / "data" / "faq_de.json",  "de"),
      (PROJECT_ROOT / "data" / "faq_eng.json", "en"),
  ]
  for faq_path, lang in FAQ_FILES:
      if not faq_path.exists():
          print(f"[WARN] {faq_path.name} fehlt - uebersprungen")
          continue
      with open(faq_path, encoding="utf-8") as f:
          faqs = json.load(f)
      for item in faqs:
          text = f"Frage: {item['question']}\nAntwort: {item['answer']}"
          documents.append(text)
          ids.append(f"faq_{counter}")
          metadatas.append({"source": "faq", "language": lang, "question": item["question"]})
          counter += 1
  ```
- `PDF_FOLDER = PROJECT_ROOT / "data" / "pdfs"`.
- Restliche Logik (Zeichen-Chunking 400/50, 5000er-Batch-Upsert) bleibt
  unverändert — Chunking/Metadaten-Vereinheitlichung ist Thema von TP2.

> Annahme: `faq_de.json` und `faq_eng.json` haben dasselbe Schema wie die alte
> `faq.json` (Liste von Objekten mit `question`/`answer`). Wird beim Umsetzen
> durch kurzes Einlesen verifiziert; falls abweichend → melden statt raten.

## 4. Tests / Verifikation

- **Bestehende Suite bleibt grün** (`python -m pytest tests/ -q` → 55 passed).
  Keine der Änderungen berührt die App-Endpoints oder die getesteten Module.
- **`test_start_scripts.py`**: prüft `run.ps1` (unverändert) — bleibt grün. Es
  testet `crawl.ps1` nicht; kein Anpassungsbedarf.
- **Neuer Smoke-Test** `tests/test_fill_db_paths.py`: importiert `scripts/fill_db.py`
  nicht (führt Top-Level-Code aus), sondern prüft statisch, dass die FAQ-Dateien
  existieren und ladbar sind und das erwartete Schema haben:
  ```python
  import json
  from pathlib import Path
  ROOT = Path(__file__).resolve().parents[1]

  def test_faq_files_exist_and_valid():
      for name in ("faq_de.json", "faq_eng.json"):
          p = ROOT / "data" / name
          assert p.is_file(), f"{name} fehlt"
          data = json.loads(p.read_text(encoding="utf-8"))
          assert isinstance(data, list) and data
          assert "question" in data[0] and "answer" in data[0]

  def test_pdf_folder_has_handbooks():
      pdfs = list((ROOT / "data" / "pdfs").glob("*.pdf"))
      assert len(pdfs) >= 16

  def test_old_faq_json_removed():
      assert not (ROOT / "data" / "faq.json").exists()

  def test_no_stray_chroma_zip_in_root():
      assert not (ROOT / "chroma_db.zip").exists()

  def test_crawler_moved_to_scripts():
      assert (ROOT / "scripts" / "crawler.py").is_file()
      assert (ROOT / "scripts" / "crawl.ps1").is_file()
      assert not (ROOT / "crawler.py").exists()
      assert not (ROOT / "crawl.ps1").exists()
  ```
- **PowerShell-Syntaxcheck** für das verschobene `scripts/crawl.ps1`
  (`Parser::ParseFile`) — kein Parse-Fehler.
- **Manuelle Root-Sichtprüfung**: nur noch `README.md`, `app/`, `data/`, `docs/`,
  `requirements.txt`, `run.ps1`, `scripts/`, `static/`, `tests/` (+ gitignored
  `chroma_db/`, ggf. `crawled_data/`).

## 5. Nicht im Scope (spätere Teil-Projekte)

- Chunking-/Metadaten-Vereinheitlichung der beiden Ingestion-Wege → **TP2**
- Modulnummern-Auffindbarkeit + Prompt-Regeln → **TP2**
- Studiengang-Filter über gecrawlte Inhalte → **TP2**
- Inhaltliche Crawler-Verbesserungen → **TP3**
- Avatar-Beenden-Button → **TP4**

## 6. Risiken

- **`fill_db.py` wird nicht automatisch ausgeführt**, solange `chroma_db/`
  existiert (`run.ps1` überspringt). Der FAQ-Fix wird also erst bei einem
  Neuaufbau der DB wirksam — für die Verifikation reicht der statische Smoke-Test
  plus optionaler manueller `python scripts/fill_db.py`-Lauf gegen eine
  Wegwerf-DB.
- Löschen der Root-PDFs ist sicher (verifiziert identisch, untracked), betrifft
  `data/pdfs/` nicht.
