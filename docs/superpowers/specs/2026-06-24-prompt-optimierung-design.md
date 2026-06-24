# Design: Prompt-Optimierung (Block 2 von 3)

**Datum:** 2026-06-24
**Status:** Approved
**Kontext:** Zweiter von drei Blöcken zur Antwortverbesserung. Block 1 (Wissensbasis-Qualität) abgeschlossen: 18/20 Eval-Fragen, 90% Fakt-Recall. Block 3 folgt: Latenz-Minimierung.

## Problem

KIRA-Antworten sind zu vage und nutzen vorhandenen Kontext nicht konsequent. Zwei Kernprobleme:

1. **Kein Kontext → keine Kennzeichnung:** Wenn `beste_distanz ≥ 0.65` (kein ausreichender DB-Treffer), lautet die aktuelle Anweisung nur "Nutze allgemeines Hochschulwissen" — ohne Verpflichtung, das gegenüber der Person kenntlich zu machen. KIRA antwortet als ob sie Fakten aus der DB hätte.

2. **Guter Kontext → Anweisung zu weich:** Bei `d < 0.45` sagt die aktuelle Anweisung "Nutze ihn, wenn er zur Frage passt — sonst ignoriere ihn". Das gibt dem Modell zu viel Freiheit, guten Kontext zu übergehen.

Kein Halluzinations-Problem im strengen Sinne (KIRA erfindet keine Fakten aus dem Nichts), aber die Grenze zwischen "aus DB" und "aus allgemeinem Wissen" ist für die antwortende Person nicht erkennbar.

## Entscheidungen

- **Ansatz A + B:** Dreistufige distanzbasierte Prompt-Injection (`context_quality_hint`) + leichte Stärkung des Base-Prompts (Hierarchie-Satz).
- **Kein neues Dependency.**
- **Fallback-Verhalten:** Allgemeines KIT-Wissen erlaubt, aber mit Kennzeichnungspflicht ("Nach meinem allgemeinen Wissen …").
- **Spezifische Modul-Pfade unverändert** (Modul-ID, ECTS, "Was ist Modul X?" — diese haben bereits präzise, gut getestete Anweisungen).

## Architektur & Komponenten

### `app/prompts.py`

**Neue Funktion `context_quality_hint(distanz: float) -> str`:**

Gibt eine Grounding-Anweisung zurück, die direkt vor den `Kontext:`-Block in den Prompt eingefügt wird. Drei Stufen:

| Distanz | Tier | Inhalt der Anweisung |
|---|---|---|
| `d < 0.45` | Sicher | "Der folgende Kontext aus der KIT-Wissensdatenbank ist sehr relevant. Beantworte die Frage auf Basis dieses Kontexts — füge kein ungesichertes allgemeines Wissen hinzu." |
| `0.45 ≤ d < 0.65` | Lückenhaft | "Der folgende Kontext ist vorhanden, aber möglicherweise nicht vollständig passend. Nutze ihn, wo er relevant ist. Wo er lückenhaft ist, darfst du allgemeines KIT-Wissen ergänzen — kennzeichne es dann mit 'Nach meinem allgemeinen Wissen …'." |
| `d ≥ 0.65` | Kein Kontext | "Kein ausreichend passender Kontext gefunden. Beantworte die Frage aus allgemeinem KIT-Wissen — kennzeichne es mit 'Nach meinem allgemeinen Wissen …'. Wenn du die Antwort nicht sicher kennst, gib das ehrlich zu und empfehle campus.kit.edu." |

Die Schwellenwerte (`0.45`, `0.65`) sind konsistent mit dem bestehenden `RERANK_SKIP_DISTANCE = 0.3` und dem `source`-Label in `chat.py` (Schwellenwert 0.45 für "Wissensbasis" vs "LLM").

**Ergänzung in `KIRA_BASE_PROMPT` (Wissensgrenzen-Abschnitt):**

Zwei Sätze nach dem bestehenden Satz "Wenn du zu einer Frage … keine genauen oder aktuellen Informationen hast …":

> "Wenn dir Kontext aus der Wissensdatenbank vorliegt, nutze ihn als primäre Quelle und bleibe nah daran. Wenn du eine Frage aus allgemeinem Wissen beantwortest, kennzeichne das deutlich mit 'Nach meinem allgemeinen Wissen …' — damit die Person weiß, dass sie es offiziell bestätigen sollte."

### `app/rag.py`

Import: `from app.prompts import context_quality_hint`

Ersetze die zweiteilige Inline-Anweisung am Ende von `build_rag_context()` (aktuell Zeilen 456–472, generischer Semantik-Pfad) durch:

```python
anweisung = context_quality_hint(beste_distanz)
return kontext, anweisung, beste_distanz
```

Die spezifischen Pfade (Modul-ID, Modulnummer-Frage, "Was ist Modul X?", ECTS) sind vom Refactor nicht betroffen — sie geben weiterhin ihre eigene maßgeschneiderte `anweisung` zurück.

### `tests/test_prompts.py`

Neue Tests für `context_quality_hint`:

```python
from app.prompts import context_quality_hint

def test_context_quality_hint_high_confidence():
    hint = context_quality_hint(0.10)
    assert "relevant" in hint.lower()

def test_context_quality_hint_medium_confidence():
    hint = context_quality_hint(0.55)
    assert "allgemeinen wissen" in hint.lower()
    assert "kennzeichne" in hint.lower() or "kennzeichne" in hint.lower()

def test_context_quality_hint_low_confidence():
    hint = context_quality_hint(0.70)
    assert "campus.kit.edu" in hint

def test_context_quality_hint_thresholds():
    # Grenzwerte prüfen
    assert context_quality_hint(0.44) != context_quality_hint(0.45)
    assert context_quality_hint(0.64) != context_quality_hint(0.65)
```

## Datenfluss

```
build_rag_context(query, studiengang)
  → generischer Pfad: anweisung = context_quality_hint(beste_distanz)
  → return (kontext, anweisung, beste_distanz)

chat.py / tavus.py (unverändert):
  prompt = build_prompt(...) + kontext_anweisung + "\nKontext:\n" + kontext + ...
```

## Erfolgskriterien

- Keine Änderung an `chat.py`, `tavus.py`, oder den spezifischen Modul-Pfaden in `rag.py`.
- `context_quality_hint` Unit-Tests PASS.
- Bestehende 133 Tests weiterhin PASS.
- Manuell: KIRA antwortet bei Urlaubssemester/NC-Fragen mit erkennbarer "allgemeines Wissen"-Kennzeichnung statt faktenloser Vaguheit.

## Außerhalb des Scope

Latenz-Optimierung (Block 3), Änderungen an den spezifischen Modul-Pfaden, Änderungen am Voice-Prompt-Stil, neue Dependencies.
