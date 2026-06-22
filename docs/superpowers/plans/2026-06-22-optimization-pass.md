# Optimization Pass Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Senke RAG-Latenz, mache den Studiengang-Filter zuverlässig, gleiche die Prompts an und mache sie empathischer, verbessere Dropdown + Sprach-UI, räume Code auf und aktualisiere die Doku.

**Architecture:** FastAPI-Backend mit zweistufiger ChromaDB-Suche + CrossEncoder-Reranking, Google Gemini 2.5 Flash über SSE, Tavus-Voice-Pfad, statisches Frontend (`static/index.html`). Änderungen sind lokal und additiv; Reranker bleibt, wird aber gewärmt und mit kleinerem Kandidatenpool betrieben; Handbuch-Chunks erhalten garantierte Präsenz im finalen Kontext.

**Tech Stack:** Python 3.14, FastAPI, ChromaDB, sentence-transformers (CrossEncoder), google-genai, pytest, Vanilla-JS-Frontend.

**Spec:** `docs/superpowers/specs/2026-06-22-optimization-pass-design.md`

---

## File Structure

| Datei | Verantwortung | Workstreams |
|-------|---------------|-------------|
| `app/rag.py` | Retrieval, Reranking, Handbuch-Priorität | A, B |
| `app/main.py` | Lifespan-Warmup (ChromaDB + Reranker) | A |
| `scripts/bench_rag.py` (neu) | Latenz-Messung von `build_rag_context` | A |
| `static/index.html` | Dropdown-Labels, Sprach-Flaggen-UI | C, E |
| `app/prompts.py` | Voice/Text angleichen + Empathie | D |
| `scripts/fill_db.py` | DB-Pfad vereinheitlichen | F |
| `app/routes/chat.py` | Retry, Message-Längenlimit | F |
| `app/routes/tavus.py` | Logging-Level, Message-Längenlimit | F |
| `README.md` | Doku Endzustand | G |
| `docs/dev-log/2026-06-22-session-2.md` (neu) | Session-Doku | G |
| `tests/test_rag_reranking.py` | Tests Kandidaten + Handbuch-Priorität | A, B |
| `tests/test_chat_stream.py` | Tests Retry + Längenlimit | F |
| `tests/test_tavus.py` | Test Längenlimit | F |
| `tests/test_prompts.py` | Test Empathie-Marker | D |

**Test-Setup:** `tests/conftest.py` mockt `chromadb`, `sentence_transformers`, `google.genai`. Reranker ist im Test ein `MagicMock` mit `predict.side_effect = lambda pairs: [1.0 - i*0.01 for i in range(len(pairs))]`. TestClient wird ohne `with` instanziiert → Lifespan (Warmup/Shutdown) läuft im Test **nicht**, daher sind Warmup-Änderungen testneutral.

**Befehl für alle Tests:** `$env:PYTHONIOENCODING="utf-8"; python -m pytest tests/ -v`

---

## Task 1: Latenz — Kandidatenpool der zweistufigen Suche reduzieren (A)

Reduziert die Reranker-Last von 16–21 auf ~12 Paare pro Standard-Query mit Studiengang.

**Files:**
- Modify: `app/rag.py` (Funktion `build_rag_context`, Block "Standardsuche" ab dem `if studiengang and studiengang in STUDIENGANG_FILES:` im zweistufigen Zweig)
- Test: `tests/test_rag_reranking.py`

- [ ] **Step 1: Test schreiben — neue Kandidatenzahlen**

In `tests/test_rag_reranking.py` ans Ende anhängen:

```python
def test_zweistufig_fetches_8_prog_and_4_all(monkeypatch):
    """Zweistufige Suche holt 8 Handbuch- + 4 allgemeine Kandidaten (Latenz)."""
    mock_reranker = MagicMock()
    mock_reranker.predict.side_effect = lambda pairs: [1.0 - i * 0.01 for i in range(len(pairs))]
    monkeypatch.setattr(rag_module, "reranker", mock_reranker)

    requested_n = {}

    def fake_query(**kwargs):
        where = kwargs.get("where", {})
        n = kwargs["n_results"]
        key = where.get("program")
        requested_n[key] = n
        docs = [f"{key}_{i}" for i in range(n)]
        dists = [0.2 + i * 0.01 for i in range(n)]
        return {"documents": [docs], "distances": [dists]}

    mock_collection = MagicMock()
    mock_collection.query.side_effect = lambda **kw: fake_query(**kw)
    monkeypatch.setattr(rag_module, "collection", mock_collection)

    rag_module.build_rag_context("Welche Module gibt es?", studiengang="winfo_bsc")

    assert requested_n["winfo_bsc"] == 8
    assert requested_n["all"] == 4


def test_zweistufig_pflicht_fetches_12_prog(monkeypatch):
    """Pflichtmodul-Frage holt 12 Handbuch-Kandidaten."""
    mock_reranker = MagicMock()
    mock_reranker.predict.side_effect = lambda pairs: [1.0 - i * 0.01 for i in range(len(pairs))]
    monkeypatch.setattr(rag_module, "reranker", mock_reranker)

    requested_n = {}

    def fake_query(**kwargs):
        where = kwargs.get("where", {})
        n = kwargs["n_results"]
        requested_n[where.get("program")] = n
        docs = [f"d_{i}" for i in range(n)]
        dists = [0.2 + i * 0.01 for i in range(n)]
        return {"documents": [docs], "distances": [dists]}

    mock_collection = MagicMock()
    mock_collection.query.side_effect = lambda **kw: fake_query(**kw)
    monkeypatch.setattr(rag_module, "collection", mock_collection)

    rag_module.build_rag_context("Welche Pflichtmodule gibt es?", studiengang="wing_bsc")

    assert requested_n["wing_bsc"] == 12
```

- [ ] **Step 2: Tests laufen lassen — müssen fehlschlagen**

Run: `python -m pytest tests/test_rag_reranking.py::test_zweistufig_fetches_8_prog_and_4_all tests/test_rag_reranking.py::test_zweistufig_pflicht_fetches_12_prog -v`
Expected: FAIL (aktuell `prog_n=10`/`15`, `all=6` → `assert 10 == 8` schlägt fehl)

- [ ] **Step 3: Implementierung — Kandidatenzahlen anpassen**

In `app/rag.py`, im zweistufigen Zweig von `build_rag_context`, die Zeilen

```python
        prog_n = 15 if is_pflicht else 10
```
ersetzen durch:
```python
        prog_n = 12 if is_pflicht else 8
```

und die Stufe-2-Query

```python
        all_r  = _query_safe({"program": "all"}, 6, query_texts=[query])
```
ersetzen durch:
```python
        all_r  = _query_safe({"program": "all"}, 4, query_texts=[query])
```

- [ ] **Step 4: Tests laufen lassen — müssen bestehen**

Run: `python -m pytest tests/test_rag_reranking.py -v`
Expected: PASS (alle, inkl. der beiden neuen und der bestehenden `test_zweistufige_suche_kombiniert_und_rerankt`)

- [ ] **Step 5: Commit**

```bash
git add app/rag.py tests/test_rag_reranking.py
git commit -m "perf(rag): reduce two-stage candidate pool to 8+4 (12 for pflicht)"
```

---

## Task 2: Latenz — Reranker im Lifespan wärmen (A)

Verhindert, dass die erste echte Anfrage den CrossEncoder-Init zahlt.

**Files:**
- Modify: `app/main.py:16-22` (Lifespan)
- Test: manuell (Lifespan läuft im pytest-TestClient ohne `with` nicht; daher kein Unit-Test)

- [ ] **Step 1: Implementierung — Warmup ergänzen**

In `app/main.py` den Import erweitern:

```python
from app.rag import collection, reranker
```

und den Lifespan-Body so ändern:

```python
@asynccontextmanager
async def lifespan(app: FastAPI):
    try:
        collection.query(query_texts=["Warmup"], n_results=1)
    except Exception as e:
        logging.warning(f"ChromaDB Warmup fehlgeschlagen: {e}")
    if reranker is not None:
        try:
            reranker.predict([("Warmup", "Warmup")])
        except Exception as e:
            logging.warning(f"Reranker Warmup fehlgeschlagen: {e}")
    yield
    await tavus._http.aclose()
```

- [ ] **Step 2: Importfähigkeit prüfen**

Run: `python -c "import app.main; print('OK')"`
Expected: Ausgabe endet mit `OK` (Modell-Ladewarnungen von HF sind ok)

- [ ] **Step 3: Bestehende Tests dürfen nicht brechen**

Run: `python -m pytest tests/ -q`
Expected: alle grün (Lifespan läuft im Test nicht, Warmup ist neutral)

- [ ] **Step 4: Commit**

```bash
git add app/main.py
git commit -m "perf(rag): warm up CrossEncoder reranker on startup"
```

---

## Task 3: Latenz — Mess-Skript `bench_rag.py` (A)

Belegt den Latenz-Effekt von Reranker an/aus pro Query-Typ.

**Files:**
- Create: `scripts/bench_rag.py`
- Test: manuell (Dev-Tool, braucht echte ChromaDB)

- [ ] **Step 1: Skript erstellen**

`scripts/bench_rag.py`:

```python
#!/usr/bin/env python3
"""
Latenz-Benchmark für build_rag_context — misst pro Query-Typ die Laufzeit
mit und ohne CrossEncoder-Reranker.

Aufruf (Server NICHT nötig, nutzt app.rag direkt):
    python scripts/bench_rag.py
    python scripts/bench_rag.py --runs 5
"""
import argparse
import sys
import time
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import app.rag as rag

# (Beschreibung, Query, Studiengang)
QUERIES = [
    ("Allgemein, kein Filter",      "Wie melde ich mich für Prüfungen an?", None),
    ("Allgemein, mit Filter",       "Welche Module gibt es?",               "winfo_bsc"),
    ("Pflichtmodule, mit Filter",   "Welche Pflichtmodule hat der Bachelor?", "wing_bsc"),
    ("Modul-ID",                    "Was ist M-WIWI-101430?",               "winfo_bsc"),
    ("Was ist Modul X",             "Was ist das Modul Controlling?",       "wing_bsc"),
]


def bench(runs: int) -> None:
    original = rag.reranker
    for label, with_reranker in (("MIT Reranker", True), ("OHNE Reranker", False)):
        rag.reranker = original if with_reranker else None
        print(f"\n=== {label} ===")
        for desc, query, sg in QUERIES:
            # Aufwärmen (Embedding-Cache)
            rag.build_rag_context(query, sg)
            t0 = time.perf_counter()
            for _ in range(runs):
                rag.build_rag_context(query, sg)
            ms = (time.perf_counter() - t0) / runs * 1000
            print(f"  {desc:<28} {ms:7.1f} ms/Query  [{sg or 'kein SG'}]")
    rag.reranker = original


def main() -> None:
    parser = argparse.ArgumentParser(description="RAG Latenz-Benchmark")
    parser.add_argument("--runs", type=int, default=3, help="Läufe pro Query (Default 3)")
    args = parser.parse_args()
    print(f"Reranker geladen: {rag.reranker is not None}")
    bench(args.runs)


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: Skript ausführen (manuell, mit echter DB)**

Run: `$env:PYTHONIOENCODING="utf-8"; python scripts/bench_rag.py`
Expected: Zwei Blöcke ("MIT Reranker" / "OHNE Reranker"), je 5 Query-Zeilen mit ms-Werten; "OHNE" deutlich schneller bei den Standard-Queries.

- [ ] **Step 3: Commit**

```bash
git add scripts/bench_rag.py
git commit -m "perf(rag): add bench_rag.py latency benchmark script"
```

---

## Task 4: Filter — Handbuch-Priorität im finalen Kontext (B)

Garantiert, dass bei gewähltem Studiengang mindestens 3 Handbuch-Chunks im Kontext landen, statt vom Reranker durch generische Web-Chunks verdrängt zu werden.

**Files:**
- Modify: `app/rag.py` (neue Helper-Funktion + zweistufiger Zweig in `build_rag_context`)
- Test: `tests/test_rag_reranking.py`

- [ ] **Step 1: Test schreiben — Handbuch-Priorität erzwingt 3 Handbuch-Chunks**

In `tests/test_rag_reranking.py` anhängen:

```python
def test_merge_handbook_priority_forces_min_handbook():
    """Auch wenn der Reranker alle 'all'-Chunks oben platziert, bleiben
    mindestens 3 Handbuch-Chunks im finalen Kontext."""
    prog_docs = [f"prog_{i}" for i in range(8)]
    all_docs = [f"all_{i}" for i in range(4)]

    class FakeReranker:
        # platziert absichtlich alle all_* vor prog_* (niedrigster Score für prog_*)
        def predict(self, pairs):
            scores = []
            for _q, doc in pairs:
                scores.append(0.1 if doc.startswith("prog_") else 0.9)
            return scores

    result = rag_module._merge_handbook_priority(
        prog_docs, all_docs, FakeReranker(), "frage", top_k=6, min_handbook=3
    )

    assert len(result) == 6
    handbook = [d for d in result if d.startswith("prog_")]
    assert len(handbook) >= 3


def test_merge_handbook_priority_no_reranker_keeps_order():
    """Ohne Reranker: Handbuch zuerst, dann allgemein, auf top_k geschnitten."""
    prog_docs = ["prog_0", "prog_1", "prog_2", "prog_3"]
    all_docs = ["all_0", "all_1"]

    result = rag_module._merge_handbook_priority(
        prog_docs, all_docs, None, "frage", top_k=6, min_handbook=3
    )

    assert result[:4] == prog_docs
    assert "all_0" in result and "all_1" in result
```

- [ ] **Step 2: Tests laufen lassen — müssen fehlschlagen**

Run: `python -m pytest tests/test_rag_reranking.py::test_merge_handbook_priority_forces_min_handbook tests/test_rag_reranking.py::test_merge_handbook_priority_no_reranker_keeps_order -v`
Expected: FAIL mit `AttributeError: module 'app.rag' has no attribute '_merge_handbook_priority'`

- [ ] **Step 3: Helper implementieren**

In `app/rag.py` direkt nach der Funktion `rerank(...)` einfügen:

```python
def _merge_handbook_priority(
    prog_docs: list[str],
    all_docs: list[str],
    reranker_obj,
    query: str,
    top_k: int = 6,
    min_handbook: int = 3,
) -> list[str]:
    """Kombiniert Handbuch- (prog_docs) und allgemeine Chunks (all_docs),
    rankt sie neu und garantiert mindestens `min_handbook` Handbuch-Chunks im
    Ergebnis (max. `top_k`). Verhindert, dass studiengangsspezifische Inhalte
    vom Reranker durch generische Web-Chunks verdrängt werden.

    Ohne Reranker: Handbuch zuerst, dann allgemein, auf top_k geschnitten.
    """
    combined = prog_docs + all_docs
    if not combined:
        return []

    if reranker_obj is None:
        ranked = combined
    else:
        pairs = [(query, doc) for doc in combined]
        scores = reranker_obj.predict(pairs)
        ranked = [doc for _, doc in sorted(zip(scores, combined), key=lambda x: x[0], reverse=True)]

    prog_set = set(prog_docs)
    final = ranked[:top_k]
    handbook_in_final = [d for d in final if d in prog_set]
    if len(handbook_in_final) >= min_handbook:
        return final

    needed = min_handbook - len(handbook_in_final)
    extra_handbook = [d for d in ranked if d in prog_set and d not in final][:needed]
    if not extra_handbook:
        return final  # nicht genug Handbuch-Chunks vorhanden

    non_handbook = [d for d in final if d not in prog_set]
    drop = set(non_handbook[-len(extra_handbook):])
    result = [d for d in final if d not in drop] + extra_handbook
    return result[:top_k]
```

- [ ] **Step 4: Zweistufigen Zweig auf den Helper umstellen**

In `app/rag.py`, im zweistufigen Zweig von `build_rag_context`, den Block

```python
        # Kombinieren und via Cross-Encoder auf 6 reranken
        combined_docs  = prog_docs + all_docs
        combined_dists = prog_dists + all_dists
        docs  = rerank(combined_docs, query, top_k=6)
        dists = combined_dists
        # beste_distanz aus allen Kandidaten-Distanzen (Proxy für DB-Relevanz)
        beste_distanz = min(dists) if dists else 1.0
```

ersetzen durch:

```python
        # Kombinieren mit garantierter Handbuch-Priorität (max. 6 Chunks)
        docs = _merge_handbook_priority(prog_docs, all_docs, reranker, query, top_k=6, min_handbook=3)
        combined_dists = prog_dists + all_dists
        # beste_distanz aus allen Kandidaten-Distanzen (Proxy für DB-Relevanz)
        beste_distanz = min(combined_dists) if combined_dists else 1.0
```

- [ ] **Step 5: Tests laufen lassen — alles grün**

Run: `python -m pytest tests/test_rag_reranking.py tests/test_prompts.py -v`
Expected: PASS (inkl. bestehendem `test_zweistufige_suche_kombiniert_und_rerankt`: liefert weiter ≤6 Chunks, `distanz==0.2`)

- [ ] **Step 6: Commit**

```bash
git add app/rag.py tests/test_rag_reranking.py
git commit -m "fix(rag): guarantee handbook chunks survive reranking when studiengang set"
```

---

## Task 5: Dropdown — eindeutige Labels (C)

Behebt die mehrdeutigen Master/Bachelor-Labels ("WING"/"WINFO" doppelt).

**Files:**
- Modify: `static/index.html:605-617`
- Test: manuell (Frontend)

- [ ] **Step 1: Option-Labels eindeutig machen**

In `static/index.html` den `<select id="studiengangSelect">`-Inhalt (Optionen) ersetzen durch:

```html
      <option value="">— Studiengang —</option>
      <optgroup label="Bachelor">
        <option value="wing_bsc">WING (B.Sc.)</option>
        <option value="winfo_bsc">WINFO (B.Sc.)</option>
        <option value="digieco_bsc">DigiEco (B.Sc.)</option>
      </optgroup>
      <optgroup label="Master">
        <option value="wing_msc">WING (M.Sc.)</option>
        <option value="ieam_msc">Industrial Engineering and Management (M.Sc.)</option>
        <option value="winfo_msc">WINFO (M.Sc.)</option>
        <option value="wima_msc">WIMA (M.Sc.)</option>
        <option value="digieco_msc">DigiEco (M.Sc.)</option>
      </optgroup>
```

- [ ] **Step 2: Manuell prüfen**

Run: `.\run.ps1` (oder Server bereits laufend), Seite öffnen.
Expected: Dropdown zeigt jede Option mit Abschluss-Suffix; Bachelor und Master sind unterscheidbar; Auswahl setzt weiterhin den Filter (eine WING-BSc-Frage liefert Handbuch-gestützte Antwort).

- [ ] **Step 3: Commit**

```bash
git add static/index.html
git commit -m "fix(ui): disambiguate Bachelor/Master entries in studiengang dropdown"
```

---

## Task 6: Prompts — Voice/Text angleichen + moderat empathischer (D)

**Files:**
- Modify: `app/prompts.py` (`KIRA_TEXT_EXT`, `KIRA_VOICE_EXT`, beide DE+EN)
- Test: `tests/test_prompts.py`

- [ ] **Step 1: Test schreiben — Empathie-Marker in beiden Modi**

In `tests/test_prompts.py` anhängen:

```python
def test_prompts_have_empathy_marker_de():
    for mode in ("text", "voice"):
        p = build_prompt(mode, "de").lower()
        assert "ermutig" in p, f"DE {mode}-Prompt sollte ermutigenden Ton enthalten"

def test_prompts_have_empathy_marker_en():
    for mode in ("text", "voice"):
        p = build_prompt(mode, "en").lower()
        assert "encourag" in p, f"EN {mode}-Prompt sollte ermutigenden Ton enthalten"
```

- [ ] **Step 2: Tests laufen lassen — müssen fehlschlagen**

Run: `python -m pytest tests/test_prompts.py::test_prompts_have_empathy_marker_de tests/test_prompts.py::test_prompts_have_empathy_marker_en -v`
Expected: FAIL (Wörter "ermutig"/"encourag" noch nicht vorhanden)

- [ ] **Step 3: Empathie-Sätze ergänzen (Ton & Stil), Struktur angleichen**

In `app/prompts.py`, in `KIRA_TEXT_EXT["de"]` im Abschnitt "Ton & Stil" den vorhandenen Satz so erweitern (Satz am Ende des Absatzes ergänzen):

```
Sprich Studierende konsequent mit "du" an. Antworte wie eine erfahrene Kommilitonin im persönlichen Gespräch — warmherzig, direkt, ohne Behördendeutsch. Greife Gefühle und Unsicherheiten kurz auf und ermutige, ohne zu beschönigen. Kurze Small-Talk-Momente darfst du warmherzig aufgreifen, bevor du natürlich zum Studienthema zurücklenkst. Fragen ohne Bezug zu Studium, Bewerbung, Campusleben oder KIT beantwortest du nicht; sage stattdessen: "Dafür bin ich leider nicht zuständig, aber bei Fragen rund ums Studium am KIT helfe ich gerne weiter."
```

In `KIRA_TEXT_EXT["en"]`, Abschnitt "Tone & style":

```
Address students as "you". Sound like an experienced fellow student in a real conversation — warm, direct, unpretentious. Briefly acknowledge feelings and worries and encourage, without sugar-coating. Brief small talk is fine; steer back to study topics naturally. Do not answer questions unrelated to studies, applications, campus life, or KIT; instead say: "I'm afraid that's outside my area, but I'm happy to help with questions about studying at KIT."
```

In `KIRA_VOICE_EXT["de"]`, Abschnitt "Voice-Stil" den ersten Satz erweitern:

```
Kling wie eine echte Beraterin im direkten Gespräch — warm, locker, menschlich. Greife Gefühle kurz auf und ermutige. Kurze, klare Sätze die sich gut vorlesen lassen. Typisch 2 bis 3 Sätze; bei komplexen Themen bis zu 4. Variiere Satzanfänge für natürlichen Klang — nicht immer dasselbe Muster.
```

In `KIRA_VOICE_EXT["en"]`, Abschnitt "Voice style":

```
Sound like a real advisor in a direct conversation — warm, relaxed, human. Briefly acknowledge feelings and encourage. Short, clear sentences that read naturally aloud. Typically 2–3 sentences; up to 4 for complex topics. Vary sentence openings for natural rhythm.
```

- [ ] **Step 4: Alle Prompt-Tests laufen lassen**

Run: `python -m pytest tests/test_prompts.py -v`
Expected: PASS — inkl. der bestehenden Constraints: `test_build_prompt_voice_de_shorter_than_text_de` (Voice bleibt kürzer), `test_build_prompt_voice_de_has_voice_rules` ("vorlesen"), `test_build_prompt_voice_de_no_lists` ("keine Listen"), `test_prompt_module_number_only_on_request`.

- [ ] **Step 5: Commit**

```bash
git add app/prompts.py tests/test_prompts.py
git commit -m "feat(prompts): add moderate empathy and align voice/text tone (de/en)"
```

---

## Task 7: Sprach-UI — zwei Flaggen-Buttons nebeneinander (E)

Ersetzt den Single-Toggle (zeigt Zielsprache) durch zwei Flaggen mit markierter aktiver Sprache.

**Files:**
- Modify: `static/index.html` — HTML bei `#langToggle` (Zeile 619), JS `setLangButton`/`toggleLang` (Zeilen 817-828), Aufrufstellen `setLangButton()` (Zeile 826) und initial (~Zeile 1423)
- Test: manuell (Frontend)

- [ ] **Step 1: HTML — Single-Button durch zwei Flaggen ersetzen**

In `static/index.html` die Zeile

```html
    <button id="langToggle" onclick="toggleLang()" style="background:none; border:1px solid var(--border); border-radius:6px; padding:3px 10px; font-size:12px; cursor:pointer; color:var(--text-muted); font-family:var(--font); margin-right:8px; display:flex; align-items:center; gap:6px;"></button>
```

ersetzen durch:

```html
    <div id="langSwitch" style="display:flex; align-items:center; gap:4px; margin-right:8px;">
      <button type="button" id="langDe" onclick="setLang('de')" title="Deutsch"
        style="background:none; border:1px solid var(--border); border-radius:6px; padding:3px 8px; cursor:pointer; display:flex; align-items:center; gap:4px; font-size:12px; font-family:var(--font);"></button>
      <button type="button" id="langEn" onclick="setLang('en')" title="English"
        style="background:none; border:1px solid var(--border); border-radius:6px; padding:3px 8px; cursor:pointer; display:flex; align-items:center; gap:4px; font-size:12px; font-family:var(--font);"></button>
    </div>
```

- [ ] **Step 2: JS — `setLangButtons` + `setLang` statt Single-Toggle**

In `static/index.html` die Funktionen `setLangButton` und `toggleLang` (Zeilen ~817-828)

```javascript
  // Button zeigt die Zielsprache (zu der gewechselt würde) samt Flagge.
  function setLangButton() {
    const target = lang === "de" ? "en" : "de";
    document.getElementById("langToggle").innerHTML = FLAG_SVG[target] + "<span>" + target.toUpperCase() + "</span>";
  }

  function toggleLang() {
    lang = lang === "de" ? "en" : "de";
    setLangButton();
    applyLang();
    pushVoicePrefs();
  }
```

ersetzen durch:

```javascript
  // Markiert die aktive Sprache; beide Flaggen bleiben sichtbar.
  function setLangButtons() {
    const deBtn = document.getElementById("langDe");
    const enBtn = document.getElementById("langEn");
    deBtn.innerHTML = FLAG_SVG.de + "<span>DE</span>";
    enBtn.innerHTML = FLAG_SVG.en + "<span>EN</span>";
    const active = "var(--text)";
    const inactive = "var(--text-muted)";
    deBtn.style.opacity = lang === "de" ? "1" : "0.5";
    enBtn.style.opacity = lang === "en" ? "1" : "0.5";
    deBtn.style.borderColor = lang === "de" ? "var(--kit-green, #009682)" : "var(--border)";
    enBtn.style.borderColor = lang === "en" ? "var(--kit-green, #009682)" : "var(--border)";
    deBtn.style.color = lang === "de" ? active : inactive;
    enBtn.style.color = lang === "en" ? active : inactive;
  }

  // Setzt die Sprache direkt (Klick auf die jeweilige Flagge).
  function setLang(target) {
    if (target === lang) return;
    lang = target;
    setLangButtons();
    applyLang();
    pushVoicePrefs();
  }
```

- [ ] **Step 3: Aufrufstellen anpassen**

In `static/index.html` jede verbliebene Referenz `setLangButton()` auf `setLangButtons()` ändern. Es gibt zwei Stellen:
- In `applyLang()` (Zeile ~826, falls dort aufgerufen) bzw. die ehemalige Aufrufzeile.
- Die Initialisierung am Dateiende (~Zeile 1423, neben `applyLang();`): sicherstellen, dass `setLangButtons();` einmal beim Laden aufgerufen wird.

Konkret: Suche im File nach `setLangButton` (ohne `s`) — falls noch `setLangButton()` irgendwo steht, durch `setLangButtons()` ersetzen. Und im Init-Block neben `applyLang();` die Zeile `setLangButtons();` ergänzen, falls nicht schon vorhanden.

- [ ] **Step 4: Manuell prüfen**

Run: Server starten/neuladen, Seite öffnen.
Expected: Zwei Flaggen DE | EN nebeneinander; aktive Sprache deutlich hervorgehoben (volle Deckkraft + grüner Rahmen), inaktive gedimmt. Klick auf die inaktive Flagge wechselt UI-Sprache und (bei laufendem Avatar) Voice-Prefs. Klick auf die aktive ist No-Op.

- [ ] **Step 5: Commit**

```bash
git add static/index.html
git commit -m "feat(ui): side-by-side DE/EN flag language switch with active state"
```

---

## Task 8: Hygiene — DB-Pfad vereinheitlichen auf `chroma_db/` (F)

`fill_db.py` schreibt nach `data/chroma_db/`, alles andere liest `chroma_db/`. Auf `chroma_db/` standardisieren.

**Files:**
- Modify: `scripts/fill_db.py:14`
- Test: manuell

- [ ] **Step 1: Pfad ändern**

In `scripts/fill_db.py` die Zeile

```python
CHROMA_PATH = str(PROJECT_ROOT / "data" / "chroma_db")
```
ersetzen durch:
```python
CHROMA_PATH = str(PROJECT_ROOT / "chroma_db")
```

- [ ] **Step 2: Konsistenz prüfen (alle DB-Pfade gleich)**

Run: `python -c "import app.rag as r; print(r.chroma_client)"; ` und grep:
Run: `git grep -n "chroma_db" -- app/ scripts/`
Expected: `app/rag.py`, `scripts/fill_db.py`, `scripts/check_db.py`, `scripts/inspect_db.py` referenzieren alle `chroma_db` (Root); kein `data/chroma_db` mehr in Lese-/Schreibpfaden (nur `data/chroma_db.zip` als Backup ist erlaubt).

- [ ] **Step 3: DB weiterhin lesbar**

Run: `$env:PYTHONIOENCODING="utf-8"; python scripts/check_db.py`
Expected: 67.112 Einträge, alle Sanity Checks grün.

- [ ] **Step 4: Commit**

```bash
git add scripts/fill_db.py
git commit -m "fix(db): unify ChromaDB path to chroma_db/ across scripts and app"
```

---

## Task 9: Hygiene — Retry im Text-Chat (F)

Spiegelt das Retry-Verhalten des Voice-Pfads: bis zu 3 Versuche, solange noch kein Chunk gesendet wurde; nach erstem Chunk kein Retry (Fehler → error-Event, kein done).

**Files:**
- Modify: `app/routes/chat.py`
- Test: `tests/test_chat_stream.py`

- [ ] **Step 1: Tests schreiben/anpassen**

In `tests/test_chat_stream.py` den bestehenden Test `test_chat_error_event_on_stream_failure` ersetzen durch (Delay patchen + Versuchszahl prüfen):

```python
@patch("app.routes.chat.CHAT_RETRY_DELAY", 0)
@patch("app.rag.collection")
@patch("app.routes.chat.client")
def test_chat_error_event_on_stream_failure(mock_client, mock_collection):
    mock_collection.query.return_value = {"documents": [["Doc"]], "distances": [[0.3]]}
    mock_client.aio.models.generate_content_stream = AsyncMock(side_effect=RuntimeError("boom"))

    response = test_client.post("/chat", json={"message": "Test", "session_id": "s_err2"})

    events = sse_events(response.text)
    assert any(e["type"] == "error" for e in events)
    assert not any(e["type"] == "done" for e in events)
    assert mock_client.aio.models.generate_content_stream.call_count == 3
```

und einen neuen Test anhängen:

```python
@patch("app.routes.chat.CHAT_RETRY_DELAY", 0)
@patch("app.rag.collection")
@patch("app.routes.chat.client")
def test_chat_retries_then_succeeds(mock_client, mock_collection):
    mock_collection.query.return_value = {"documents": [["Doc"]], "distances": [[0.3]]}
    mock_client.aio.models.generate_content_stream = AsyncMock(
        side_effect=[RuntimeError("boom"), make_async_stream(["Erfolg."])]
    )

    response = test_client.post("/chat", json={"message": "Test", "session_id": "s_retry"})

    events = sse_events(response.text)
    assert any(e["type"] == "done" for e in events)
    assert mock_client.aio.models.generate_content_stream.call_count == 2
```

- [ ] **Step 2: Tests laufen lassen — müssen fehlschlagen**

Run: `python -m pytest tests/test_chat_stream.py::test_chat_error_event_on_stream_failure tests/test_chat_stream.py::test_chat_retries_then_succeeds -v`
Expected: FAIL (`AttributeError: ... CHAT_RETRY_DELAY` bzw. call_count 1 statt 3/2)

- [ ] **Step 3: Retry implementieren**

In `app/routes/chat.py`, nach den Importen eine Konstante ergänzen:

```python
CHAT_RETRY_DELAY = 2
```

(`import asyncio` ist bereits vorhanden.) Dann die `event_stream`-Funktion (aktuell Zeilen ~54-85) ersetzen durch:

```python
    async def event_stream():
        t1 = time.time()
        chat_parts = []
        gesendet = False
        fehler = False
        for versuch in range(3):
            fehler = False
            try:
                stream = await client.aio.models.generate_content_stream(
                    model="gemini-2.5-flash",
                    contents=prompt,
                    config=gemini_config(400),
                )
                async for chunk in stream:
                    if chunk.text:
                        gesendet = True
                        chat_parts.append(chunk.text)
                        yield f'data: {json_lib.dumps({"type": "chunk", "text": chunk.text})}\n\n'
                break
            except Exception as e:
                logging.warning(f"/chat Gemini Fehler (Versuch {versuch + 1}): {e}")
                fehler = True
                if gesendet:
                    break  # mitten im Stream → kein Retry
                if versuch < 2:
                    await asyncio.sleep(CHAT_RETRY_DELAY)

        if fehler:
            yield f'data: {json_lib.dumps({"type": "error", "message": "Service momentan nicht verfügbar."})}\n\n'
            return

        answer = "".join(chat_parts).strip()
        remember_opening(session_id, answer)

        sessions[session_id].append({"role": "Du", "content": user_input})
        sessions[session_id].append({"role": "Bot", "content": answer})

        done_event = {
            "type": "done",
            "voice_text": answer,
            "source": quelle,
            "latency_ms": round((time.time() - t1) * 1000),
            "session_id": session_id,
        }
        yield f'data: {json_lib.dumps(done_event)}\n\n'
```

- [ ] **Step 4: Gesamten Chat-Test laufen lassen**

Run: `python -m pytest tests/test_chat_stream.py -v`
Expected: PASS — inkl. `test_chat_midstream_failure_no_done_no_history` (Fehler nach erstem Chunk → error, kein done, leere History) und `test_chat_streams_chunks_then_done`.

- [ ] **Step 5: Commit**

```bash
git add app/routes/chat.py tests/test_chat_stream.py
git commit -m "fix(chat): retry Gemini stream up to 3x before first chunk"
```

---

## Task 10: Hygiene — Message-Längenlimit (F)

Begrenzt Eingaben auf 2000 Zeichen in `/chat` und `/tavus/message`.

**Files:**
- Modify: `app/routes/chat.py` (`ChatRequest`), `app/routes/tavus.py` (`TavusMessageRequest`)
- Test: `tests/test_chat_stream.py`, `tests/test_tavus.py`

- [ ] **Step 1: Tests schreiben**

In `tests/test_chat_stream.py` anhängen:

```python
def test_chat_message_too_long_rejected():
    response = test_client.post("/chat", json={"message": "x" * 2001, "session_id": "s_long"})
    assert response.status_code == 422
```

In `tests/test_tavus.py` anhängen:

```python
def test_tavus_message_too_long_rejected():
    with patch.dict(os.environ, {"TAVUS_API_KEY": "real-key"}):
        response = test_client.post("/tavus/message", json={
            "conversation_id": "conv_abc123",
            "message": "x" * 2001
        })
    assert response.status_code == 422
```

- [ ] **Step 2: Tests laufen lassen — müssen fehlschlagen**

Run: `python -m pytest tests/test_chat_stream.py::test_chat_message_too_long_rejected tests/test_tavus.py::test_tavus_message_too_long_rejected -v`
Expected: FAIL (aktuell 200/500 statt 422)

- [ ] **Step 3: `ChatRequest` mit Längenlimit**

In `app/routes/chat.py` den Import

```python
from pydantic import BaseModel
```
ersetzen durch:
```python
from pydantic import BaseModel, Field
```

und in `ChatRequest` das Feld `message`:

```python
class ChatRequest(BaseModel):
    message: str = Field(..., max_length=2000)
    session_id: str = "default"
    lang: str = "de"
    studiengang: str | None = None
```

- [ ] **Step 4: `TavusMessageRequest` mit Längenlimit**

In `app/routes/tavus.py` den Import

```python
from pydantic import BaseModel, field_validator
```
ersetzen durch:
```python
from pydantic import BaseModel, Field, field_validator
```

und in `TavusMessageRequest` das Feld `message`:

```python
class TavusMessageRequest(BaseModel):
    conversation_id: str
    message: str = Field(..., max_length=2000)

    @field_validator("message")
    @classmethod
    def message_not_empty(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("message must not be empty")
        return v
```

- [ ] **Step 5: Tests laufen lassen**

Run: `python -m pytest tests/test_chat_stream.py tests/test_tavus.py -v`
Expected: PASS (inkl. bestehendem `test_tavus_message_empty_message` → 422 für Leerstring)

- [ ] **Step 6: Commit**

```bash
git add app/routes/chat.py app/routes/tavus.py tests/test_chat_stream.py tests/test_tavus.py
git commit -m "fix(api): cap chat and tavus message length at 2000 chars"
```

---

## Task 11: Hygiene — Logging-Level Tavus-Statuslog (F)

`tavus.py` loggt den Tavus-API-Status immer als `warning`, auch bei Erfolg.

**Files:**
- Modify: `app/routes/tavus.py` (im `tavus_session`-Handler, aktuell Zeile ~111)
- Test: bestehende Tavus-Tests müssen grün bleiben

- [ ] **Step 1: Logging differenzieren**

In `app/routes/tavus.py` die Zeile

```python
            logging.warning(f"Tavus API status: {res.status_code}, body: {data}")
```
ersetzen durch:
```python
            if res.status_code in (200, 201):
                logging.info(f"Tavus API status: {res.status_code}")
            else:
                logging.warning(f"Tavus API status: {res.status_code}, body: {data}")
```

- [ ] **Step 2: Tavus-Tests laufen lassen**

Run: `python -m pytest tests/test_tavus.py -v`
Expected: PASS (Verhalten unverändert, nur Logging)

- [ ] **Step 3: Commit**

```bash
git add app/routes/tavus.py
git commit -m "chore(tavus): log API success at info level, errors at warning"
```

---

## Task 12: Dokumentation (G)

**Files:**
- Modify: `README.md`
- Create: `docs/dev-log/2026-06-22-session-2.md`
- Test: manuell (Inhalt)

- [ ] **Step 1: README aktualisieren**

In `README.md`:
- Abschnitt "RAG-Strategie": ergänzen, dass nach der zweistufigen Suche ein **CrossEncoder-Reranker** (`cross-encoder/mmarco-mMiniLMv2-L12-H384-v1`) die kombinierten Kandidaten neu sortiert und **mindestens 3 Handbuch-Chunks garantiert** bleiben; Kandidatenzahlen (8 Handbuch + 4 allgemein, 12 bei Pflicht).
- Abschnitt "Tests": die Skripte `scripts/check_db.py` (DB-Statusübersicht) und `scripts/bench_rag.py` (Latenz-Benchmark) dokumentieren.
- Falls noch ein Abschnitt "Web-Authentifizierung" / HTTP Basic Auth existiert: entfernen (Auth wurde entfernt). Falls bereits weg: prüfen, dass kein Auth-Verweis mehr im README steht.
- DB-Pfad als `chroma_db/` (Root) benennen; ZIP-Backup `data/chroma_db.zip`.
- Sprach-UI: zwei Flaggen DE/EN; Dropdown-Labels mit (B.Sc.)/(M.Sc.).

- [ ] **Step 2: Dev-Log erstellen**

`docs/dev-log/2026-06-22-session-2.md` mit Abschnitten:
- DB-Reparatur: zwei ChromaDB-Verzeichnisse erkannt (`chroma_db/` voll = 67.112 Einträge, `data/chroma_db/` leer); Pfad in `rag.py`/`fill_db.py`/Skripten auf `chroma_db/` vereinheitlicht; volle DB als `data/chroma_db.zip` (1,15 GB) gesichert; leeres `data/chroma_db/` entfernt; `crawl.ps1` versehentlich gelöscht und wiederhergestellt.
- Neues Skript `scripts/check_db.py` (Typen/Studiengänge/Sanity Checks).
- RAG-Filter-Fix: `_WHAT_IS_MODULE_RE` "Modul" optional (fängt "Was ist Introduction to Digital Economics?"); ohne Studiengang Fallback auf Semantiksuche; Handbuch-Priorität im Reranking.
- Latenz: Reranker-Warmup im Lifespan, Kandidatenpool 8+4 (12 Pflicht), `scripts/bench_rag.py`.
- Prompts: moderat empathischer + Voice/Text angeglichen (DE/EN).
- UI: Dropdown-Labels eindeutig, Sprach-UI zwei Flaggen.
- Hygiene: Chat-Retry, Message-Längenlimit (2000), Tavus-Logging-Level; `voice_openings`-Cleanup war bereits vorhanden.
- Offen (dokumentiert, nicht umgesetzt): Webcrawl-`source`-Metadatum (1 unique URL/leere Domain), `is_pflicht`-Metadatum für vollständige Pflichtmodul-Listen.

- [ ] **Step 3: Manuell prüfen**

Run: `git diff --stat README.md; ls docs/dev-log/`
Expected: README geändert, Dev-Log-Datei vorhanden; README enthält keinen Auth-Abschnitt mehr und nennt Reranker + neue Skripte.

- [ ] **Step 4: Commit**

```bash
git add README.md docs/dev-log/2026-06-22-session-2.md
git commit -m "docs: update README + dev-log for optimization pass"
```

---

## Task 13: Abschließendes ganzheitliches Review & Optimierung (H)

**Files:**
- Review: alle `app/**`, `scripts/**`
- Modify: nur risikoarme Findings; Rest dokumentieren in Dev-Log (Task 12)
- Test: gesamte Suite

- [ ] **Step 1: Gesamte Testsuite grün**

Run: `$env:PYTHONIOENCODING="utf-8"; python -m pytest tests/ -v`
Expected: alle Tests PASS.

- [ ] **Step 2: Import- und Startfähigkeit**

Run: `python -c "import app.main; print('IMPORT OK')"`
Expected: endet mit `IMPORT OK`.

- [ ] **Step 3: DB-Status prüfen**

Run: `$env:PYTHONIOENCODING="utf-8"; python scripts/check_db.py`
Expected: 67.112 Einträge, Sanity Checks grün.

- [ ] **Step 4: Review-Durchsicht mit Checkliste**

Lies `app/main.py`, `app/rag.py`, `app/gemini.py`, `app/session.py`, `app/prompts.py`, `app/routes/*.py`, `scripts/*.py` und prüfe:
- **Effizienz/Latenz:** keine doppelten ChromaDB-Queries auf demselben Pfad; kein synchroner Blocker außerhalb `asyncio.to_thread`; `doc[:600] × N` Kontextgröße vertretbar.
- **Edge Cases:** leere/zu lange Eingaben (jetzt begrenzt), fehlende Env-Vars (`GOOGLE_API_KEY`, `TAVUS_*`), leere ChromaDB, Sprach-Fallback (`build_prompt` unbekannte Sprache → de), globaler `active_voice_prefs` (Einzel-Session — dokumentiert).
- **Bugs/Konsistenz:** SSE-Fehlerpfade (chat: error/no-done; tavus: fallback/stop), `_query_safe` schluckt Exceptions (bewusst, dokumentieren), Distanz-/Quelle-Logik konsistent (0.1 für DB-Treffer, 0.45 Schwelle).

Notiere jedes Finding. **Risikoarme** Findings (z.B. Tippfehler, ungenutzte Importe, irreführende Kommentare) sofort fixen und einzeln committen. **Größere** Findings in den Dev-Log (Task 12) als nummerierte Liste "Offene Punkte" aufnehmen.

- [ ] **Step 5: Ungenutzte Importe / Dead Code prüfen**

Run: `python -m pyflakes app/ scripts/ 2>&1 | head -40` (falls `pyflakes` fehlt: `python -m pip install pyflakes` oder diesen Step überspringen und manuell prüfen)
Expected: keine ungenutzten Importe / undefinierten Namen in geänderten Dateien; gefundene risikoarme Punkte fixen.

- [ ] **Step 6: Abschluss-Commit (falls Review-Fixes anfielen)**

```bash
git add -A
git commit -m "chore: holistic review fixes (optimization pass)"
```

(Wenn keine Änderungen: diesen Step überspringen.)

---

## Self-Review (vom Plan-Autor)

**1. Spec-Abdeckung:**
- A Latenz → Task 1 (Kandidaten), Task 2 (Warmup), Task 3 (Bench) ✓
- B Filter → Task 4 (Handbuch-Priorität); "was ist X"-Regex bereits in Arbeitskopie gefixt ✓
- C Dropdown → Task 5 ✓
- D Prompts → Task 6 ✓
- E Sprach-UI → Task 7 ✓
- F Review/Hygiene → Task 8 (DB-Pfad), 9 (Retry), 10 (Längenlimit), 11 (Logging); `voice_openings`-Cleanup bereits vorhanden (in Task 12/13 als verifiziert vermerkt) ✓
- G Doku → Task 12 ✓
- H Ganzheitliches Review → Task 13 ✓

**2. Platzhalter-Scan:** Keine TBD/TODO/„später"; jeder Code-Step enthält vollständigen Code oder exakte Ersetzung. ✓

**3. Typ-/Namens-Konsistenz:** `_merge_handbook_priority(prog_docs, all_docs, reranker_obj, query, top_k, min_handbook)` einheitlich in Task 4 (Definition, Aufruf, Tests). `CHAT_RETRY_DELAY` in Task 9 konsistent (Definition + Patch in Tests). `setLang`/`setLangButtons` in Task 7 konsistent. Kandidatenzahlen 8/4/12 konsistent zwischen Task 1 und Bench/Doku. ✓

**Hinweis zur Arbeitskopie:** Vor Beginn liegen uncommittete Änderungen vor (`app/rag.py` DB-Pfad-Revert + "was ist X"-Regex-Fix, `scripts/inspect_db.py` Pfad, neues `scripts/check_db.py`). Diese gehören thematisch zu B/F und sollten als erster Commit gesichert werden, bevor Task 1 startet:

```bash
git add app/rag.py scripts/inspect_db.py scripts/check_db.py
git commit -m "fix(rag): make 'was ist X' detection optional-Modul + add check_db.py"
```
