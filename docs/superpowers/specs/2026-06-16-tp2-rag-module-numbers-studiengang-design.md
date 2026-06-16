# Teil-Projekt 2 — RAG, Modulnummern & Studiengang-Zugriff: Design

**Datum:** 2026-06-16
**Status:** Genehmigt
**Branch:** feature/tavus

## 1. Ziel

Drei zusammenhängende Probleme der Wissensbasis beheben:
1. KIRA findet/nennt die **richtigen Modulnummern** nicht.
2. Die **Studiengang-Auswahl** greift zu eng (nur ein Handbuch, FAQ/Allgemeines fällt weg).
3. Die zwei Ingestion-Wege erzeugen **inkonsistente Metadaten/Chunks**.

## 2. Befunde (verifiziert)

- Modul-IDs im Handbuch: Form `M-WIWI-106472` **und** `T-WIWI-102609`
  (Teilleistungen). Aktuelle Regex `\bM-[A-Z]+-\d+\b` erfasst nur `M-`.
- Jede Modul-Detailsektion beginnt mit dem Anker `Modul: <Name> [M-…-…]`
  (ID in eckigen Klammern) — konsistente Schnittkante.
- Umlaut-Extraktion ist **korrekt** (geprüft: `ö`=U+00F6, 0 Replacement-Zeichen)
  — kein Handlungsbedarf.
- Aktuelles Zeichen-Chunking (400/50) zerschneidet Name ↔ ID und erzeugt
  verrauschte Inhaltsverzeichnis-Fragmente.
- Studiengang-Filter `where={"source": {"$in": [pdf]}}` schließt FAQ, allgemeine
  Infos und (künftig) gecrawlte Inhalte aus.
- ChromaDB-`where` matcht nur Dokumente, die das Feld **besitzen** → ein
  einheitliches `program`-Feld auf ALLEN Chunks ist nötig, damit Filter
  zuverlässig wirken.

## 3. Entscheidungen (vom Nutzer bestätigt)

1. **Modulnummern:** nur auf ausdrückliche Nachfrage nennen, sonst Klarname.
2. **Studiengang-Filter:** gewähltes Handbuch + FAQ/Allgemeines; andere
   Studiengang-Handbücher ausschließen.
3. **Re-Indexierung:** Handbücher modulweise neu chunken, ChromaDB neu aufbauen.

## 4. Änderungen

### 4.1 Modulweises Chunking — `scripts/fill_db.py`

Neue Funktion `chunk_handbook(text)`:
- Findet alle Modul-Anker per Regex
  `re.compile(r'Modul:\s*(.+?)\s*\[([MT]-[A-Z]+-\d+)\]')`.
- Segmentiert den Text zwischen aufeinanderfolgenden Ankern → ein Block je Modul.
- Liefert pro Block: `(module_name, module_id, block_text)`.
- Ist ein Block länger als `MAX_CHARS` (z.B. 1500), wird er in Teilstücke
  zerlegt, denen jeweils ein Header `Modul: <Name> [<ID>]\n` vorangestellt wird,
  damit Name + ID an jedem Teilstück hängen.
- Sehr kurze Blöcke (< 50 Zeichen Rest) werden verworfen.

Erkennung „ist dies ein Handbuch?": Dateiname matcht `mhb_*.pdf`. Andere PDFs
laufen über das bestehende Zeichen-Chunking (`chunk_text`).

### 4.2 Einheitliches Metadaten-Schema + sauberer Rebuild — `scripts/fill_db.py`

Vor dem Befüllen: Collection **löschen und neu anlegen**, damit keine Altchunks
(altes Schema) zurückbleiben:
```python
try:
    chroma_client.delete_collection("uni_beratung")
except Exception:
    pass
collection = chroma_client.get_or_create_collection(name="uni_beratung", embedding_function=embedding_fn)
```

Reverse-Map Dateiname → program-Key (eigene Konstante in `fill_db.py`, deckt auch
TVWL ab, das nicht im UI ist):
```python
HANDBOOK_PROGRAM = {
    "mhb_wiing_BSc_de_aktuell.pdf": "wing_bsc",
    "mhb_wiinf_BSc_de_aktuell.pdf": "winfo_bsc",
    "mhb_de_BSc_de_aktuell.pdf":    "digieco_bsc",
    "mhb_wiing_MSc_de_aktuell.pdf": "wing_msc",
    "mhb_ieam_MSc_en_aktuell.pdf":  "ieam_msc",
    "mhb_wiinf_MSc_de_aktuell.pdf": "winfo_msc",
    "mhb_wima_MSc_de_aktuell.pdf":  "wima_msc",
    "mhb_de_MSc_en_aktuell.pdf":    "digieco_msc",
    "mhb_tvwl_BSc_de_aktuell.pdf":  "tvwl_bsc",   # nicht im UI -> nur ungefiltert sichtbar
    "mhb_tvwl_MSc_de_aktuell.pdf":  "tvwl_msc",
}
```

Metadaten pro Chunk:
| Quelle | Metadaten |
|---|---|
| Handbuch-Modulchunk | `{source: <pdf>, doc_type: "handbook", program: <key>, module_id: <ID>, module_name: <Name>}` |
| Allg. PDF | `{source: <pdf>, doc_type: "info", program: "all"}` |
| FAQ | `{source: "faq", doc_type: "faq", program: "all", language: <de|en>}` |

> ChromaDB-Metadaten erlauben nur skalare Werte (str/int/float/bool) — alle Felder
> oben sind Strings. `module_id`/`module_name` werden bei Nicht-Modul-Chunks
> weggelassen (Feld fehlt) — das ist in Ordnung, da der Lookup in 4.4 nur darauf
> filtert, wenn eine ID in der Frage steht.

### 4.3 Studiengang-Filter — `app/rag.py`

`STUDIENGANG_FILES` (Map key → PDF) wird durch die program-Logik ersetzt/ergänzt.
`build_rag_context(query, studiengang)`:
```python
if studiengang:
    where = {"$or": [{"program": studiengang}, {"program": "all"}]}
else:
    where = None
```
- Mit Studiengang: gewähltes Handbuch (`program==key`) + FAQ/Allgemeines
  (`program=="all"`); andere Handbücher ausgeschlossen.
- Ohne Studiengang: kein Filter (gesamte Wissensbasis).

> `STUDIENGANG_FILES` bleibt als Quelle der gültigen UI-Keys erhalten (zur
> Validierung von `studiengang`), die Werte (PDF-Namen) werden für den Filter
> nicht mehr gebraucht. Unbekannte Keys → kein Filter (wie bisher).

### 4.4 Modulnummer-Lookup — `app/rag.py`

- `MODULE_ID_RE = re.compile(r'\b[MT]-[A-Z]+-\d+\b')` (M- **und** T-).
- Wenn die Frage eine Modul-ID enthält:
  1. exakter Metadaten-Treffer: zusätzliche Bedingung `{"module_id": <ID>}`
     in den `where`-Filter (kombiniert mit ggf. Studiengang über `$and`);
  2. wenn kein Treffer → Fallback auf `where_document={"$contains": <ID>}`.
- Trefferanweisung wie bisher (Modul-Kontext, Klarname bevorzugen).

### 4.5 Prompt — `app/prompts.py`

In `KIRA_TEXT_EXT` (de/en) und `KIRA_VOICE_EXT` (de/en) die Regel ändern:
- alt: „Lass Modulnummern … komplett weg. Nenne immer nur den reinen Namen."
- neu (de): „Nenne Modulnummern wie M-WIWI-101430 nur, wenn ausdrücklich danach
  gefragt wird; sonst verwende nur den Klarnamen des Moduls."
- neu (en): sinngemäß übersetzt.

## 5. Tests

Alle gegen gemockte `app.rag.collection` bzw. reine Funktionen:

- `test_chunk_handbook_keeps_module_id_with_name`: Beispieltext mit zwei
  `Modul: X [M-WIWI-1] … Modul: Y [T-INFO-2] …` → zwei Chunks, jeder enthält
  Name **und** ID seines Moduls; kein Modul landet im Chunk des anderen.
- `test_chunk_handbook_long_block_keeps_header`: überlanger Block → mehrere
  Teilstücke, jedes beginnt mit `Modul: <Name> [<ID>]`.
- `test_module_id_regex_matches_m_and_t`: Regex matcht `M-WIWI-1` und `T-INFO-2`.
- `test_build_rag_context_studiengang_or_filter`: `studiengang="winfo_bsc"` →
  `where == {"$or": [{"program": "winfo_bsc"}, {"program": "all"}]}`.
- `test_build_rag_context_no_studiengang_no_filter`: kein `where`.
- `test_build_rag_context_module_id_lookup`: Frage mit `M-WIWI-101430` →
  `where` enthält `module_id`-Bedingung (bzw. Fallback `where_document`).
- `test_prompt_allows_module_number_on_request`: `build_prompt("text","de")`
  enthält die neue Formulierung („nur, wenn ausdrücklich danach gefragt") und
  **nicht** mehr „komplett weg".
- Bestehende Tests anpassen: `test_build_rag_context_studiengang_filter`
  (alt `$in`/`source`) → neuer `$or`/`program`-Filter;
  `test_chat_studiengang_passes_filter_to_rag` analog.

## 6. Rebuild & Verifikation

- `chroma_db/` löschen, dann `python scripts/fill_db.py` (oder `run.ps1`) →
  Neuaufbau mit neuem Schema/Chunking.
- `python -m pytest tests/ -q` grün.
- Qualitäts-Check (manuell, sobald Google-Key rotiert):
  - „Welche Module gibt es zu Finance im WINFO BSc?" (mit Studiengang-Auswahl)
    → relevante Module aus dem richtigen Handbuch.
  - „Wie lautet die Modulnummer von Angewandte Informatik?" → nennt
    `M-WIWI-101430`.
  - Ohne explizite Frage nach der Nummer → KIRA nennt nur den Namen.

## 7. Nicht im Scope

- Crawler schreibt `program`/`doc_type` konsistent → **TP3** (der Crawler muss
  für gecrawlte Webinhalte `program: "all"` bzw. erkannte Programme setzen, damit
  sie im Studiengang-Filter erscheinen).
- Numerische LV-Nummern (stehen nicht im Handbuch).

## 8. Risiken

- Der Modul-Anker `Modul: <Name> [ID]` basiert auf einer Stichprobe (WiInf BSc).
  Andere Handbücher (z.B. englische MSc) können „Module: <Name> [ID]" lauten →
  bei der Umsetzung an mehreren Handbüchern verifizieren und die Regex ggf. um
  `Modul(e)?:`/`Module:` erweitern. Fällt ein Handbuch nicht unter das Muster,
  greift als Fallback das normale Zeichen-Chunking (keine Verschlechterung).
- Rebuild ist Pflicht, damit die Änderungen wirken (altes Schema sonst gemischt).
