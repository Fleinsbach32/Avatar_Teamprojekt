# Prompt-Optimierung Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** KIRAs Antwortqualität verbessern durch dreistufige distanzbasierte Grounding-Anweisung (`context_quality_hint`) und Stärkung des Base-Prompts.

**Architecture:** Neue reine Funktion `context_quality_hint(distanz: float) -> str` in `app/prompts.py` ersetzt die zweiteilige Inline-Logik am Ende von `build_rag_context()` in `app/rag.py`. Die spezifischen Pfade (Modul-ID, ECTS, "Was ist Modul X?") bleiben unverändert. Zwei Sätze zur Kontext-Hierarchie werden in `KIRA_BASE_PROMPT` ergänzt.

**Tech Stack:** Python 3.11, pytest. Keine neue Dependency.

---

## Dateiübersicht

| Datei | Aktion | Verantwortung |
|---|---|---|
| `app/prompts.py` | Modify | `context_quality_hint` + Base-Prompt-Ergänzung |
| `app/rag.py` | Modify | Import + Inline-Anweisung durch Funktionsaufruf ersetzen |
| `tests/test_prompts.py` | Modify | Tests für `context_quality_hint` + aktualisierte RAG-Tests |

---

### Task 1: `context_quality_hint` — TDD

**Files:**
- Test: `tests/test_prompts.py`
- Modify: `app/prompts.py`

- [ ] **Step 1: Failing Tests schreiben**

Am Ende von `tests/test_prompts.py` anhängen (nach dem letzten Test `test_prompts_have_empathy_marker_en`):

```python
# ── context_quality_hint ──────────────────────────────────
from app.prompts import context_quality_hint


def test_context_quality_hint_high_confidence():
    hint = context_quality_hint(0.10)
    assert "KIT-Wissensdatenbank" in hint
    assert "ungesichertes" in hint


def test_context_quality_hint_medium_confidence():
    hint = context_quality_hint(0.55)
    assert "kennzeichne" in hint.lower() or "Kennzeichne" in hint
    assert "allgemeinen Wissen" in hint or "allgemeines" in hint.lower()


def test_context_quality_hint_low_confidence():
    hint = context_quality_hint(0.70)
    assert "campus.kit.edu" in hint
    assert "allgemeinen Wissen" in hint or "allgemeinem" in hint.lower()


def test_context_quality_hint_thresholds():
    assert context_quality_hint(0.44) != context_quality_hint(0.45)
    assert context_quality_hint(0.64) != context_quality_hint(0.65)
```

- [ ] **Step 2: Tests schlagen fehl**

Run: `python -m pytest tests/test_prompts.py -k context_quality_hint -v`
Expected: FAIL (`cannot import name 'context_quality_hint'`).

- [ ] **Step 3: `context_quality_hint` implementieren**

In `app/prompts.py` direkt vor `@functools.lru_cache` (letzte Zeile der Datei vor `build_prompt`) einfügen:

```python
def context_quality_hint(distanz: float) -> str:
    """Dreistufige Grounding-Anweisung basierend auf Embedding-Distanz.

    d < 0.45  → Kontext sicher: nur aus DB antworten.
    0.45–0.65 → Kontext lückenhaft: DB bevorzugen, allgemeines Wissen kennzeichnen.
    d ≥ 0.65  → Kein ausreichender Kontext: allgemeines Wissen + Kennzeichnung.
    """
    if distanz < 0.45:
        return (
            "Der folgende Kontext aus der KIT-Wissensdatenbank ist sehr relevant. "
            "Beantworte die Frage auf Basis dieses Kontexts — "
            "füge kein ungesichertes allgemeines Wissen hinzu."
        )
    if distanz < 0.65:
        return (
            "Der folgende Kontext ist vorhanden, aber möglicherweise nicht vollständig passend. "
            "Nutze ihn, wo er relevant ist. Wo er lückenhaft ist, darfst du allgemeines "
            "KIT-Wissen ergänzen — kennzeichne es dann mit 'Nach meinem allgemeinen Wissen …'."
        )
    return (
        "Kein ausreichend passender Kontext gefunden. Beantworte die Frage aus allgemeinem "
        "KIT-Wissen — kennzeichne es mit 'Nach meinem allgemeinen Wissen …'. "
        "Wenn du die Antwort nicht sicher kennst, gib das ehrlich zu und empfehle campus.kit.edu."
    )
```

- [ ] **Step 4: Tests grün**

Run: `python -m pytest tests/test_prompts.py -k context_quality_hint -v`
Expected: PASS (4 Tests).

- [ ] **Step 5: Commit**

```bash
git add app/prompts.py tests/test_prompts.py
git commit -m "feat(prompt): context_quality_hint — dreistufige Grounding-Anweisung"
```

---

### Task 2: KIRA_BASE_PROMPT stärken

**Files:**
- Test: `tests/test_prompts.py`
- Modify: `app/prompts.py`

- [ ] **Step 1: Failing Test schreiben**

Direkt nach den `context_quality_hint`-Tests in `tests/test_prompts.py` anhängen:

```python
def test_base_prompt_has_grounding_hierarchy():
    assert "primäre Quelle" in KIRA_BASE_PROMPT
    assert "Nach meinem allgemeinen Wissen" in KIRA_BASE_PROMPT
```

- [ ] **Step 2: Test schlägt fehl**

Run: `python -m pytest tests/test_prompts.py -k grounding_hierarchy -v`
Expected: FAIL (Sätze noch nicht im Prompt).

- [ ] **Step 3: KIRA_BASE_PROMPT erweitern**

In `app/prompts.py` den Wissensgrenzen-Abschnitt des `KIRA_BASE_PROMPT` anpassen. Die bisherige Passage:

```python
Wissensgrenzen:
Wenn du zu einer Frage innerhalb deines Zuständigkeitsbereichs keine genauen oder aktuellen Informationen hast (zum Beispiel zu konkreten NC-Werten, aktuellen Bewerbungsfristen oder spezifischen Modulinhalten), gib das ehrlich zu und verweise auf campus.kit.edu oder die zuständige KIT-Stelle. Sage zum Beispiel: "Genaue aktuelle Zahlen habe ich dazu leider nicht, aber auf campus.kit.edu findest du die offiziellen Infos."
```

ersetzen durch:

```python
Wissensgrenzen:
Wenn du zu einer Frage innerhalb deines Zuständigkeitsbereichs keine genauen oder aktuellen Informationen hast (zum Beispiel zu konkreten NC-Werten, aktuellen Bewerbungsfristen oder spezifischen Modulinhalten), gib das ehrlich zu und verweise auf campus.kit.edu oder die zuständige KIT-Stelle. Wenn dir Kontext aus der Wissensdatenbank vorliegt, nutze ihn als primäre Quelle und bleibe nah daran. Wenn du eine Frage aus allgemeinem Wissen beantwortest, kennzeichne das deutlich mit 'Nach meinem allgemeinen Wissen …' — damit die Person weiß, dass sie es offiziell bestätigen sollte. Sage zum Beispiel: "Genaue aktuelle Zahlen habe ich dazu leider nicht, aber auf campus.kit.edu findest du die offiziellen Infos."
```

Hinweis: Die zwei neuen Sätze werden zwischen den ersten Satz ("...verweise auf campus.kit.edu...") und den "Sage zum Beispiel:"-Satz eingefügt.

- [ ] **Step 4: Tests grün**

Run: `python -m pytest tests/test_prompts.py -k "grounding_hierarchy or base_prompt" -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add app/prompts.py tests/test_prompts.py
git commit -m "feat(prompt): KIRA_BASE_PROMPT — Kontext-Hierarchie und Kennzeichnungspflicht"
```

---

### Task 3: `context_quality_hint` in `rag.py` verdrahten + kaputte Tests reparieren

**Files:**
- Modify: `app/rag.py`
- Modify: `tests/test_prompts.py`

Hintergrund: `build_rag_context()` hat am Ende eine zweiteilige Inline-Anweisung (d < 0.45 / d ≥ 0.45). Diese wird durch den Aufruf von `context_quality_hint` ersetzt. Zwei bestehende Tests prüfen den alten Anweisungstext und schlagen danach fehl — sie werden aktualisiert.

- [ ] **Step 1: Import hinzufügen und Inline-Anweisung ersetzen**

In `app/rag.py` den Import-Block (erste Zeile: `import logging`) um die neue Import-Zeile ergänzen. Die existierende Import-Zeile:

```python
from app.bootstrap import ensure_chroma_db
```

ersetzen durch:

```python
from app.bootstrap import ensure_chroma_db
from app.prompts import context_quality_hint
```

Dann am Ende von `build_rag_context()` die Inline-Anweisung ersetzen. Den Block:

```python
    kontext = "\n\n".join(doc[:600] for doc in docs)

    if beste_distanz < 0.45:
        anweisung = (
            "Der folgende Kontext stammt aus der KIT-Wissensdatenbank. "
            "Nutze ihn, wenn er zur Frage passt. "
            "Wenn der Kontext die Frage nicht beantwortet oder ein anderes Thema behandelt, "
            "ignoriere ihn und antworte auf Basis deines allgemeinen Hochschulwissens. "
            "Wenn nach einem bestimmten Modul gefragt wird, nenne es nur wenn es explizit "
            "im Kontext steht — schlage niemals andere Modulnamen als Alternative vor. "
            "Erfinde niemals Inhalte aus einem unpassenden Kontext."
        )
    else:
        anweisung = (
            "Nutze allgemeines Hochschulwissen. "
            "Nur wenn es um verbindliche Fristen oder offizielle Regelungen geht, "
            "empfiehl beiläufig eine kurze Bestätigung auf campus.kit.edu oder beim Prüfungsamt — "
            "nicht in jeder Antwort und jedes Mal anders formuliert."
        )
    return kontext, anweisung, beste_distanz
```

ersetzen durch:

```python
    kontext = "\n\n".join(doc[:600] for doc in docs)
    anweisung = context_quality_hint(beste_distanz)
    return kontext, anweisung, beste_distanz
```

- [ ] **Step 2: Kaputte Tests identifizieren**

Run: `python -m pytest tests/test_prompts.py -v`
Expected: 2 Failures:
- `test_build_rag_context_general_fallback` — assertiert `"allgemeines Hochschulwissen"` (alter Text)
- `test_rag_fallback_no_disclaiming` — assertiert `"nicht in jeder Antwort"` (alter Text)

- [ ] **Step 3: Kaputte Tests reparieren**

In `tests/test_prompts.py` den Test `test_build_rag_context_general_fallback` (Zeilen 88–99) anpassen:

```python
def test_build_rag_context_general_fallback():
    with patch("app.rag.collection") as mock_collection:
        mock_collection.query.return_value = {
            "documents": [["Irrelevantes Dokument"]],
            "distances": [[0.9]]
        }
        with patch("app.rag.rerank") as mock_rerank:
            mock_rerank.return_value = ["Irrelevantes Dokument"]
            from app.rag import build_rag_context
            _, anweisung, distanz = build_rag_context("Testfrage")
    assert distanz == 0.9
    assert "campus.kit.edu" in anweisung          # Tier-3: Verweis bei Unsicherheit
    assert "allgemeinen Wissen" in anweisung      # Tier-3: Kennzeichnungspflicht
```

Den Test `test_rag_fallback_no_disclaiming` (Zeilen 142–151) anpassen:

```python
def test_rag_fallback_no_disclaiming():
    with patch("app.rag.collection") as mock_collection:
        mock_collection.query.return_value = {
            "documents": [["Irrelevant"]],
            "distances": [[0.9]]
        }
        from app.rag import build_rag_context
        _, anweisung, _ = build_rag_context("Testfrage")
    assert "kennzeichne" in anweisung.lower()     # Kennzeichnungspflicht für allgemeines Wissen
    assert "campus.kit.edu" in anweisung          # Verweis bei Unsicherheit
```

- [ ] **Step 4: Alle Tests grün**

Run: `python -m pytest tests/test_prompts.py -v`
Expected: alle PASS.

- [ ] **Step 5: Syntax-Check**

Run: `python -c "import ast; ast.parse(open('app/rag.py', encoding='utf-8').read()); print('ok')"`
Expected: `ok`.

- [ ] **Step 6: Commit**

```bash
git add app/rag.py tests/test_prompts.py
git commit -m "feat(prompt): context_quality_hint in build_rag_context — 3-stufige Grounding-Anweisung"
```

---

### Task 4: Volle Suite + Abschluss

**Files:** keine Änderung — Verifikation.

- [ ] **Step 1: Gesamte Test-Suite**

Run: `python -m pytest tests/ -q`
Expected: alle PASS (133 bestehende + neue Tests).

- [ ] **Step 2: Manuelle Verifikation (optional)**

Den lokalen Server starten und im Chat testen:
- Frage mit guter Handbuch-Antwort (z.B. "Wie viele ECTS hat Mathematik 1?"): KIRA antwortet ohne Kennzeichnung ✓
- Frage ohne DB-Treffer (z.B. "Was ist ein NC?"): KIRA antwortet mit "Nach meinem allgemeinen Wissen …" ✓
- Frage zu Urlaubssemester: KIRA kennzeichnet oder gibt ehrlich zu, keine genauen Infos zu haben ✓

---

## Self-Review-Notiz

Abgedeckt: `context_quality_hint` (T1), Base-Prompt-Hierarchie (T2), Verdrahtung in `rag.py` + Reparatur der 2 betroffenen Tests (T3), Verifikation (T4). Funktionsname konsistent: `context_quality_hint` in allen Dateien. Schwellenwerte 0.45 / 0.65 konsistent mit Spec und bestehenden Konstanten. Kein Placeholder.
