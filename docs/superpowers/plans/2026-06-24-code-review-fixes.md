# Code-Review-Fixes Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Die im Audit ausgewählten Befunde umsetzen: P1, D1, D2, D3, D4, D5, D6, D7, C2.

**Architecture:** Mehrheitlich kleine, isolierte Cleanups (Doku/Config/Skripte) plus zwei Code-Änderungen in `app/`: Modul-ID-Lookup ohne Embedding (P1) und ein gemeinsamer Gemini-Streaming-Retry-Helper (C2). Jede Änderung erhält einen eigenen Commit; nach jeder Task läuft `pytest tests/`.

**Tech Stack:** Python 3.11, FastAPI, ChromaDB, pytest

---

## Dateiübersicht

| Datei | Aktion | Befund |
|---|---|---|
| `.gitignore` | Modify | D5 |
| `.env.example` | Modify | D2 |
| `scripts/test_kira.py` | Modify | D3 |
| `scripts/inspect_db.py` | Delete | D4 |
| `app/rag.py` | Modify | P1, D6 |
| `tests/test_prompts.py` | Modify | P1 |
| `app/prompts.py` | Modify | D7 |
| `app/routes/tavus.py` | Modify | D7, C2 |
| `scripts/debug_rag.py` | Rewrite | D1 |
| `app/gemini.py` | Modify | C2 |
| `app/routes/chat.py` | Modify | C2 |
| `tests/test_chat_stream.py` | Modify | C2 |
| `tests/test_tavus.py` | Modify | C2 |

Reihenfolge: trivial → riskant (C2 zuletzt).

---

### Task 1: [D5] Root-Archiv in .gitignore

**Files:**
- Modify: `.gitignore`

- [ ] **Step 1: Einträge ergänzen**

Aktueller Inhalt von `.gitignore`:
```
.env
__pycache__/
*.pyc
chroma_db/
data/chroma_db.zip
crawled_data/
.superpowers/
tests/__pycache__/
.pip-stamp
```

Ergänze nach `data/chroma_db.zip` zwei Zeilen, sodass das im Deployment erzeugte Root-Archiv nie versehentlich committet wird:
```
chroma_db.zip
*.tar.gz
```

- [ ] **Step 2: Verifizieren**

Run: `git status --porcelain chroma_db.zip` (sollte nichts ausgeben, falls die Datei existiert → ignoriert) und `git check-ignore chroma_db.zip` → erwartet Ausgabe `chroma_db.zip`.

- [ ] **Step 3: Commit**

```bash
git add .gitignore
git commit -m "chore(D5): Root-Archiv (chroma_db.zip, *.tar.gz) ignorieren"
```

---

### Task 2: [D2] Stale Auth-Konfiguration aus .env.example entfernen

**Files:**
- Modify: `.env.example`

Hintergrund: HTTP Basic Auth wurde entfernt (Commit `1dfccde6`); `APP_USERNAME`/`APP_PASSWORD` werden im App-Code nirgends gelesen. Der Nutzer hat entschieden: kein Schutz nötig (Code nicht öffentlich) → Doku ehrlich machen.

- [ ] **Step 1: Auth-Block entfernen**

Entferne in `.env.example` diesen Block vollständig (Zeilen 4–8):
```
# ── Web-Authentifizierung (HTTP Basic Auth fuer Browser-Endpoints) ──
# Schuetzt die UI (/, /chat, /avatar/config, /tavus/session|end|message|settings).
# Die von Tavus serverseitig aufgerufenen LLM-Endpoints sind bewusst ausgenommen.
APP_USERNAME=admin
APP_PASSWORD=geheim
```

Die Datei beginnt danach mit dem `# ── Allgemein …`-Block, gefolgt direkt vom `# ── Avatar Provider …`-Block.

- [ ] **Step 2: Verifizieren**

Run: `grep -c "APP_USERNAME\|APP_PASSWORD" .env.example`
Expected: `0`

- [ ] **Step 3: Commit**

```bash
git add .env.example
git commit -m "docs(D2): nicht mehr genutzte Auth-Variablen aus .env.example entfernen"
```

---

### Task 3: [D3] Ignorierte Auth-Credentials aus test_kira.py entfernen

**Files:**
- Modify: `scripts/test_kira.py`

Hintergrund: `test_kira.py` sendet `auth=(admin, geheim)` und bietet `--user/--pass`-Flags, die der Server ignoriert (keine Auth mehr).

- [ ] **Step 1: Docstring-Zeilen entfernen**

In `scripts/test_kira.py` im Modul-Docstring (Zeilen 6–12) die Auth-Hinweise entfernen. Vorher:
```python
Aufruf:
    python scripts/test_kira.py
    python scripts/test_kira.py --url http://localhost:8000 --user admin --pass geheim

Umgebungsvariablen (Alternative zu Flags):
    KIRA_URL, APP_USERNAME, APP_PASSWORD
"""
```
Nachher:
```python
Aufruf:
    python scripts/test_kira.py
    python scripts/test_kira.py --url http://localhost:8000

Umgebungsvariable (Alternative zum Flag):
    KIRA_URL
"""
```

- [ ] **Step 2: `auth` aus dem Client und `main()`-Signatur entfernen**

`main()` nutzt aktuell `auth = (username, password)` (Zeile 148) und `httpx.AsyncClient(base_url=url, auth=auth)` (Zeile 154). Ändere die Funktion so, dass sie keine Credentials mehr nimmt:

Vorher (Signatur Zeile 147):
```python
async def main(url: str, username: str, password: str) -> None:
    auth = (username, password)
    print(f"\n{'='*72}")
    print(f"  KIRA Systemtest  —  {url}")
    print(f"{'='*72}\n")

    failed = 0
    async with httpx.AsyncClient(base_url=url, auth=auth) as client:
```
Nachher:
```python
async def main(url: str) -> None:
    print(f"\n{'='*72}")
    print(f"  KIRA Systemtest  —  {url}")
    print(f"{'='*72}\n")

    failed = 0
    async with httpx.AsyncClient(base_url=url) as client:
```

- [ ] **Step 3: Argparse-Flags und Aufruf anpassen**

Vorher (Zeilen 174–181):
```python
if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="KIRA Systemtest")
    parser.add_argument("--url",  default=os.getenv("KIRA_URL",      "http://localhost:8000"))
    parser.add_argument("--user", default=os.getenv("APP_USERNAME",  "admin"))
    parser.add_argument("--pass", dest="pw",
                        default=os.getenv("APP_PASSWORD", "geheim"))
    args = parser.parse_args()
    asyncio.run(main(args.url, args.user, args.pw))
```
Nachher:
```python
if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="KIRA Systemtest")
    parser.add_argument("--url", default=os.getenv("KIRA_URL", "http://localhost:8000"))
    args = parser.parse_args()
    asyncio.run(main(args.url))
```

- [ ] **Step 4: Verifizieren**

Run: `python -c "import ast; ast.parse(open('scripts/test_kira.py', encoding='utf-8').read())"` → keine Ausgabe (Syntax ok).
Run: `grep -c "APP_USERNAME\|APP_PASSWORD\|auth=" scripts/test_kira.py` → `0`

- [ ] **Step 5: Commit**

```bash
git add scripts/test_kira.py
git commit -m "chore(D3): ignorierte Auth-Credentials aus test_kira.py entfernen"
```

---

### Task 4: [D4] Veraltetes Einmal-Skript inspect_db.py löschen

**Files:**
- Delete: `scripts/inspect_db.py`

Hintergrund: hartkodierte „Buchführung"-Debug-Queries ohne CLI, abgelöst durch `check_db.py` + `debug_rag.py`. Kein Python-Code importiert es (verifiziert via grep).

- [ ] **Step 1: Datei löschen**

```bash
git rm scripts/inspect_db.py
```

- [ ] **Step 2: Verifizieren, dass nichts darauf verweist**

Run: `grep -rn "inspect_db" --include=*.py .`
Expected: keine Ausgabe.

- [ ] **Step 3: Commit**

```bash
git commit -m "chore(D4): veraltetes Einmal-Skript inspect_db.py entfernen"
```

---

### Task 5: [D6] Modulnamen-Extraktoren DRY zusammenführen

**Files:**
- Modify: `app/rag.py:93-120`
- Test: `tests/test_prompts.py` (bestehende Tests müssen grün bleiben — keine neuen nötig)

Hintergrund: `_module_name_from_number_question`, `_module_name_from_what_is_question` und `_module_name_from_ects_question` (rag.py:93–120) haben denselben Aufbau. Die Funktionsnamen bleiben (Tests importieren sie), nur die Innereien teilen einen Helper.

Bestehende Tests, die grün bleiben müssen: `test_module_name_extracted_from_number_question`, `test_ects_question_extracts_module_name` (tests/test_prompts.py). Hinweis: `_module_name_from_number_question` gibt bei nichtleerem Namen zurück (Mindestlänge 1), die beiden anderen verlangen Länge ≥ 3.

- [ ] **Step 1: Bestehende Tests laufen lassen (Baseline grün)**

Run: `pytest tests/test_prompts.py -k "module_name or ects_question_extracts" -v`
Expected: PASS (Baseline).

- [ ] **Step 2: Helper einführen und die drei Funktionen darauf umstellen**

Ersetze in `app/rag.py` die drei Funktionen (Zeilen 93–120) durch:

```python
def _extract_module_name(regex: re.Pattern, query: str, min_len: int = 1) -> str | None:
    """Extrahiert den Modulnamen aus group(1) des Treffers, strippt Anführungszeichen
    und verwirft zu kurze Namen (< min_len)."""
    m = regex.search(query)
    if not m:
        return None
    name = m.group(1).strip().strip('"\'')
    return name if len(name) >= min_len else None


def _module_name_from_number_question(query: str) -> str | None:
    """Erkennt Fragen wie 'Wie lautet die Modulnummer von <Name>?' und gibt
    <Name> zurück. So kann die Suche mit dem Modulnamen laufen statt mit der
    Füllfrage (deren Embedding sonst das falsche Modul trifft)."""
    return _extract_module_name(_NUMBER_Q_RE, query, min_len=1)


def _module_name_from_what_is_question(query: str) -> str | None:
    """Erkennt 'Was ist das Modul X?' und gibt den Modulnamen X zurück."""
    return _extract_module_name(_WHAT_IS_MODULE_RE, query, min_len=3)


def _module_name_from_ects_question(query: str) -> str | None:
    """Erkennt 'Wie viele ECTS hat das Modul X?' und gibt X zurück, damit die
    Frage über den Modulindex statt unzuverlässig semantisch beantwortet wird."""
    return _extract_module_name(_ECTS_Q_RE, query, min_len=3)
```

- [ ] **Step 3: Tests laufen lassen**

Run: `pytest tests/test_prompts.py -v`
Expected: alle PASS.

- [ ] **Step 4: Commit**

```bash
git add app/rag.py
git commit -m "refactor(D6): Modulnamen-Extraktoren über gemeinsamen Helper DRY"
```

---

### Task 6: [D7] _VOICE_CONTEXT nach prompts.py verschieben

**Files:**
- Modify: `app/prompts.py`
- Modify: `app/routes/tavus.py:30-43,130`

Hintergrund: `_VOICE_CONTEXT` (tavus.py) wiederholt KIRA-Persona-Text, der konzeptionell zu `prompts.py` gehört. Co-Location in einem Modul verhindert Drift. Kein Test importiert `_VOICE_CONTEXT` (verifiziert).

- [ ] **Step 1: Konstante nach prompts.py verschieben**

Füge in `app/prompts.py` nach dem `KIRA_VOICE_EXT`-Dict (vor `build_prompt`) hinzu:

```python
# Kurzer Gesprächskontext für die Tavus-Persona (conversational_context).
# Bewusst knapp gehalten — nicht der volle Voice-Prompt.
VOICE_CONTEXT: dict[str, str] = {
    "de": (
        "Du bist KIRA, Studienberaterin am KIT (Karlsruher Institut für Technologie) "
        "für Fragen rund um das Studium der Wirtschaftswissenschaften. "
        "Antworte auf Deutsch, freundlich, kurz und präzise wie eine erfahrene Kommilitonin. "
        "Sprich Studierende mit 'du' an. Keine Listen oder Aufzählungen. "
        "Bei offiziellen Daten verweise auf campus.kit.edu."
    ),
    "en": (
        "You are KIRA, an academic advisor at KIT (Karlsruhe Institute of Technology). "
        "Answer in English, friendly and precise. "
        "For official data, refer to campus.kit.edu."
    ),
}
```

- [ ] **Step 2: tavus.py auf den Import umstellen**

In `app/routes/tavus.py`:
1. Entferne die lokale Definition `_VOICE_CONTEXT = { … }` (Zeilen 29–43, inkl. des Kommentars darüber).
2. Erweitere den bestehenden Prompt-Import (Zeile 14) von:
   ```python
   from app.prompts import build_prompt
   ```
   auf:
   ```python
   from app.prompts import build_prompt, VOICE_CONTEXT
   ```
3. Ersetze die Nutzung (Zeile 130) von:
   ```python
   "conversational_context": _VOICE_CONTEXT.get(prefs.lang, _VOICE_CONTEXT["de"]),
   ```
   auf:
   ```python
   "conversational_context": VOICE_CONTEXT.get(prefs.lang, VOICE_CONTEXT["de"]),
   ```

- [ ] **Step 3: Tests laufen lassen**

Run: `pytest tests/test_tavus.py tests/test_prompts.py -v`
Expected: alle PASS.

- [ ] **Step 4: Commit**

```bash
git add app/prompts.py app/routes/tavus.py
git commit -m "refactor(D7): VOICE_CONTEXT nach prompts.py (Persona-Text zentral)"
```

---

### Task 7: [P1] Modul-ID-Lookup ohne Embedding

**Files:**
- Modify: `app/rag.py` (neuer Helper `_get_by_where` + Block bei Zeile 293–307)
- Test: `tests/test_prompts.py` (zwei bestehende Tests umstellen)

Hintergrund: Der Modul-ID-Pfad nutzt `_query_safe(..., query_texts=[query])` und berechnet damit unnötig ein Embedding für einen exakten Metadaten-Match. Stattdessen `collection.get(where=…)` (kein Embedding).

- [ ] **Step 1: Bestehende Tests umstellen (Red)**

In `tests/test_prompts.py` die beiden Tests anpassen.

`test_build_rag_context_module_id_exact_lookup` (Zeilen 174–184) — neu:
```python
def test_build_rag_context_module_id_exact_lookup():
    with patch("app.rag.collection") as mock_collection:
        mock_collection.get.return_value = {
            "documents": ["Modul: Angewandte Informatik [M-WIWI-101430] ..."],
        }
        from app.rag import build_rag_context
        _, _, distanz = build_rag_context("Was ist M-WIWI-101430?")
    # Exakter Metadaten-Match via get (kein Embedding-Query)
    first_where = mock_collection.get.call_args_list[0].kwargs.get("where")
    assert first_where == {"module_id": "M-WIWI-101430"}
    assert mock_collection.query.call_count == 0
    assert distanz == 0.1
```

`test_build_rag_context_module_id_with_studiengang_combines` (Zeilen 187–199) — neu:
```python
def test_build_rag_context_module_id_with_studiengang_combines():
    with patch("app.rag.collection") as mock_collection:
        mock_collection.get.return_value = {
            "documents": ["Modul: X [M-WIWI-101430]"],
        }
        from app.rag import build_rag_context
        build_rag_context("Infos zu M-WIWI-101430?", studiengang="winfo_bsc")
    first_where = mock_collection.get.call_args_list[0].kwargs.get("where")
    assert first_where == {"$and": [
        {"$or": [{"program": "winfo_bsc"}, {"program": "all"}]},
        {"module_id": "M-WIWI-101430"},
    ]}
```

- [ ] **Step 2: Tests laufen lassen (müssen scheitern)**

Run: `pytest tests/test_prompts.py -k "module_id" -v`
Expected: FAIL (Code ruft noch `collection.query`, nicht `collection.get`).

- [ ] **Step 3: Helper `_get_by_where` hinzufügen**

Füge in `app/rag.py` direkt nach `_get_by_contains` (nach Zeile 163) hinzu:

```python
def _get_by_where(where: dict | None, limit: int = 3) -> list[str]:
    """Exakter Metadaten-Lookup via collection.get — OHNE Embedding.
    Für exakte Treffer (z.B. module_id) ist die semantische Distanz irrelevant.
    Gibt eine flache Dokumentliste zurück (leer bei Fehler/keinem Treffer)."""
    base: dict = {"limit": limit, "include": ["documents"]}
    if where is not None:
        base["where"] = where
    try:
        return collection.get(**base).get("documents") or []
    except Exception:
        return []
```

- [ ] **Step 4: Modul-ID-Block umstellen**

Ersetze in `build_rag_context` den Modul-ID-Block. Vorher (Zeilen 293–299):
```python
    if module_match:
        module_id = module_match.group()
        id_results = _query_safe(_combine(where, {"module_id": module_id}), 3, query_texts=[query])
        id_docs = id_results["documents"][0]
        if not id_docs:
            # Volltext-Fallback ohne Embedding — Modul-IDs sind exakte Strings
            id_docs = _get_by_contains(where, module_id, 3)
```
Nachher:
```python
    if module_match:
        module_id = module_match.group()
        # Exakter Metadaten-Match ohne Embedding (semantische Distanz ist hier egal)
        id_docs = _get_by_where(_combine(where, {"module_id": module_id}), 3)
        if not id_docs:
            # Volltext-Fallback, falls module_id nicht als Metadatum, aber im Text steht
            id_docs = _get_by_contains(where, module_id, 3)
```

- [ ] **Step 5: Tests laufen lassen**

Run: `pytest tests/test_prompts.py -v`
Expected: alle PASS.

- [ ] **Step 6: Volle Suite**

Run: `pytest tests/ -v`
Expected: alle PASS.

- [ ] **Step 7: Commit**

```bash
git add app/rag.py tests/test_prompts.py
git commit -m "perf(P1): Modul-ID exakt via collection.get statt Embedding-Query"
```

---

### Task 8: [D1] debug_rag.py auf build_rag_context umstellen

**Files:**
- Rewrite: `scripts/debug_rag.py`

Hintergrund: Das Tool dupliziert veraltete RAG-Logik (alte n_results 12/8/15, kein Modulindex, kein ECTS-Pfad). Statt das Duplikat zu pflegen, ruft es jetzt direkt `build_rag_context` auf — kann nie wieder driften. Kein Test importiert `debug_rag` (verifiziert).

- [ ] **Step 1: Datei ersetzen**

Ersetze den gesamten Inhalt von `scripts/debug_rag.py` durch:

```python
#!/usr/bin/env python3
"""Debug-Tool: Zeigt den von build_rag_context erzeugten RAG-Kontext für eine Query.

Ruft direkt die echte RAG-Pipeline auf (kein Logik-Duplikat → bleibt immer aktuell).

Verwendung:
    python scripts/debug_rag.py "Was ist Introduction to Digital Economics?" --studiengang digieco_bsc
    python scripts/debug_rag.py "Welche Pflichtmodule hat WING?" --studiengang wing_bsc
    python scripts/debug_rag.py "Wie bewerbe ich mich?"
"""
import argparse
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from dotenv import load_dotenv
load_dotenv(PROJECT_ROOT / ".env")

from app.rag import build_rag_context, STUDIENGANG_FILES


def debug(query: str, studiengang: str | None = None) -> None:
    print(f"\nQuery      : {query!r}")
    print(f"Studiengang: {studiengang or '(kein)'}")
    print("-" * 64)

    kontext, anweisung, distanz = build_rag_context(query, studiengang)

    chunks = kontext.split("\n\n") if kontext else []
    quelle = "Wissensbasis" if distanz < 0.45 else "LLM"
    print(f"Beste Distanz: {distanz:.3f}   ->   Quelle: {quelle}")
    print(f"Kontext-Chunks: {len(chunks)}")
    print(f"\nAnweisung an das LLM:\n  {anweisung}\n")
    print(f"Kontext ({len(chunks)} Chunks):")
    if not chunks:
        print("  (leer)")
    for i, c in enumerate(chunks):
        print(f"  [{i}] {c[:200]!r}")


def main() -> None:
    parser = argparse.ArgumentParser(description="KIRA RAG Debug Tool")
    parser.add_argument("query", help="Die Testfrage")
    parser.add_argument(
        "--studiengang",
        default=None,
        help=f"Studiengang-Key (z.B. wing_bsc). Gültig: {', '.join(STUDIENGANG_FILES)}",
    )
    args = parser.parse_args()

    if args.studiengang and args.studiengang not in STUDIENGANG_FILES:
        print(f"Fehler: Unbekannter Studiengang {args.studiengang!r}")
        print(f"Gültige Keys: {', '.join(STUDIENGANG_FILES)}")
        sys.exit(1)

    debug(args.query, args.studiengang)


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: Syntax verifizieren**

Run: `python -c "import ast; ast.parse(open('scripts/debug_rag.py', encoding='utf-8').read())"`
Expected: keine Ausgabe.

- [ ] **Step 3: Volle Suite (stellt sicher, dass keine Importe brachen)**

Run: `pytest tests/ -v`
Expected: alle PASS.

- [ ] **Step 4: Commit**

```bash
git add scripts/debug_rag.py
git commit -m "refactor(D1): debug_rag.py ruft build_rag_context direkt (kein Logik-Duplikat)"
```

---

### Task 9: [C2] Gemeinsamer Gemini-Streaming-Retry-Helper

**Files:**
- Modify: `app/gemini.py` (neuer Helper + zwei Exceptions)
- Modify: `app/routes/chat.py:59-88` (Retry-Schleife durch Helper ersetzen)
- Modify: `app/routes/tavus.py:241-273` (Retry-Schleife durch Helper ersetzen)
- Modify: `tests/test_chat_stream.py` (12× Patch-Ziel `app.routes.chat.client` → `app.gemini.client`)
- Modify: `tests/test_tavus.py` (9× Patch-Ziel `app.routes.tavus.client` → `app.gemini.client`)

Hintergrund: Beide Routen haben dieselbe 3-Versuch-Retry-Schleife um `generate_content_stream` mit „kein Retry nach erstem Chunk". Die Semantik unterscheidet sich nur im Fehlerfall:
- **chat:** Fehler vor erstem Chunk → Fehler-Event; Fehler mitten im Stream → Fehler-Event, kein „done", keine History.
- **tavus:** Fehler vor erstem Chunk → „Service momentan nicht verfügbar."; Fehler mitten im Stream → vorhandenes flushen und sauber beenden.

Beide Fälle lassen sich mit zwei Exceptions abbilden: `GeminiUnavailable` (vor erstem Chunk gescheitert) und `GeminiMidStreamError` (nach Chunks gescheitert). Die Retry-Delays bleiben in den Routen und werden übergeben — so funktionieren die bestehenden `@patch("app.routes.*.{CHAT,VOICE}_RETRY_DELAY", 0)` weiter.

Wichtig: Der Helper nutzt `client` aus `app.gemini`. Deshalb müssen die Streaming-Tests künftig `app.gemini.client` patchen statt `app.routes.chat.client` / `app.routes.tavus.client` (nach dem Refactor importieren die Routen `client` nicht mehr → ein Patch auf den alten Namen schlägt fehl).

- [ ] **Step 1: Helper + Exceptions in app/gemini.py**

Aktueller Inhalt von `app/gemini.py`:
```python
import os
from google import genai
from google.genai import types

client = genai.Client(api_key=os.getenv("GOOGLE_API_KEY"))

SSE_HEADERS = {"Cache-Control": "no-cache", "X-Accel-Buffering": "no"}


def gemini_config(max_tokens: int) -> types.GenerateContentConfig:
    return types.GenerateContentConfig(
        temperature=0.2,
        max_output_tokens=max_tokens,
        thinking_config=types.ThinkingConfig(thinking_budget=0),
    )
```

Ergänze `import asyncio` und `import logging` oben sowie nach `gemini_config` den Helper und die Exceptions:

```python
import asyncio
import logging
import os
from google import genai
from google.genai import types

client = genai.Client(api_key=os.getenv("GOOGLE_API_KEY"))

SSE_HEADERS = {"Cache-Control": "no-cache", "X-Accel-Buffering": "no"}


def gemini_config(max_tokens: int) -> types.GenerateContentConfig:
    return types.GenerateContentConfig(
        temperature=0.2,
        max_output_tokens=max_tokens,
        thinking_config=types.ThinkingConfig(thinking_budget=0),
    )


class GeminiUnavailable(Exception):
    """Alle Versuche scheiterten, bevor ein Chunk gesendet wurde."""


class GeminiMidStreamError(Exception):
    """Der Stream brach ab, nachdem bereits Chunks gesendet wurden (kein Retry)."""


async def stream_gemini(prompt: str, max_tokens: int, retry_delay: float, attempts: int = 3):
    """Async-Generator: liefert Text-Chunks von Gemini.

    Retry nur VOR dem ersten Chunk (bis zu `attempts` Versuche, `retry_delay` s Pause).
    - Scheitert es vor dem ersten Chunk endgültig → raise GeminiUnavailable.
    - Scheitert es nach bereits gesendeten Chunks → raise GeminiMidStreamError (kein Retry).
    """
    gesendet = False
    for versuch in range(attempts):
        try:
            stream = await client.aio.models.generate_content_stream(
                model="gemini-2.5-flash",
                contents=prompt,
                config=gemini_config(max_tokens),
            )
            async for chunk in stream:
                if chunk.text:
                    gesendet = True
                    yield chunk.text
            return
        except Exception as e:
            logging.warning(f"Gemini Stream Fehler (Versuch {versuch + 1}): {e}")
            if gesendet:
                raise GeminiMidStreamError() from e
            if versuch < attempts - 1:
                await asyncio.sleep(retry_delay)
    raise GeminiUnavailable()
```

- [ ] **Step 2: chat.py auf den Helper umstellen**

In `app/routes/chat.py`:
1. Import (Zeile 10) ändern von:
   ```python
   from app.gemini import client, gemini_config, SSE_HEADERS
   ```
   auf:
   ```python
   from app.gemini import SSE_HEADERS, stream_gemini, GeminiUnavailable, GeminiMidStreamError
   ```
2. Ersetze die Retry-Schleife im `event_stream` (Zeilen 59–88) durch:
   ```python
   async def event_stream():
       t1 = time.time()
       chat_parts = []
       try:
           async for text in stream_gemini(prompt, 400, CHAT_RETRY_DELAY):
               chat_parts.append(text)
               yield f'data: {json.dumps({"type": "chunk", "text": text})}\n\n'
       except (GeminiUnavailable, GeminiMidStreamError):
           yield f'data: {json.dumps({"type": "error", "message": "Service momentan nicht verfügbar."})}\n\n'
           return
   ```
   Der Rest der Funktion (ab `answer = "".join(chat_parts).strip()`) bleibt unverändert.

- [ ] **Step 3: tavus.py auf den Helper umstellen**

In `app/routes/tavus.py`:
1. Import (Zeile 13) ändern von:
   ```python
   from app.gemini import client, gemini_config, SSE_HEADERS
   ```
   auf:
   ```python
   from app.gemini import SSE_HEADERS, stream_gemini, GeminiUnavailable, GeminiMidStreamError
   ```
2. Ersetze `stream_answer` (Zeilen 241–273) durch:
   ```python
   async def stream_answer():
       gesendet = False
       buffer = ""
       try:
           async for text in stream_gemini(prompt, 300, VOICE_RETRY_DELAY):
               gesendet = True
               buffer += text
               deltas, buffer = _flush_sentences(buffer)
               for d in deltas:
                   yield f'data: {json.dumps({"choices": [{"delta": {"content": d}, "finish_reason": None}]})}\n\n'
       except GeminiMidStreamError:
           pass  # bereits gesendete Sätze stehen; Rest wird unten geflusht
       except GeminiUnavailable:
           gesendet = False
       if gesendet:
           deltas, _ = _flush_sentences(buffer, final=True)
           for d in deltas:
               yield f'data: {json.dumps({"choices": [{"delta": {"content": d}, "finish_reason": None}]})}\n\n'
       else:
           yield f'data: {json.dumps({"choices": [{"delta": {"content": "Service momentan nicht verfügbar."}, "finish_reason": None}]})}\n\n'
       yield f'data: {json.dumps({"choices": [{"delta": {}, "finish_reason": "stop"}]})}\n\n'
       yield 'data: [DONE]\n\n'
   ```

- [ ] **Step 4: Test-Patch-Ziele umstellen**

In `tests/test_chat_stream.py`: alle 12 Vorkommen von `@patch("app.routes.chat.client")` durch `@patch("app.gemini.client")` ersetzen (die per Decorator injizierten `mock_client`-Argumente und Methodenaufrufe bleiben unverändert).

In `tests/test_tavus.py`: alle 9 Vorkommen von `@patch("app.routes.tavus.client")` durch `@patch("app.gemini.client")` ersetzen.

Hinweis: Die `@patch("app.routes.chat.CHAT_RETRY_DELAY", 0)` und `@patch("app.routes.tavus.VOICE_RETRY_DELAY", 0)` bleiben unverändert — diese Konstanten bleiben in den Routen.

- [ ] **Step 5: Volle Suite**

Run: `pytest tests/ -v`
Expected: alle PASS (insb. `test_chat_error_event_on_stream_failure` mit call_count 3, `test_chat_retries_then_succeeds` mit 2, `test_chat_midstream_failure_no_done_no_history`, `test_tavus_llm_fallback_after_failures` mit 3, `test_tavus_llm_no_retry_after_first_chunk` mit 1).

- [ ] **Step 6: Commit**

```bash
git add app/gemini.py app/routes/chat.py app/routes/tavus.py tests/test_chat_stream.py tests/test_tavus.py
git commit -m "refactor(C2): gemeinsamer Gemini-Streaming-Retry-Helper in gemini.py"
```

---

## Abschluss

- [ ] **Volle Suite + Smoke**

Run: `pytest tests/ -v` → alle PASS.

Die Befunde C1 (globaler Voice-State) und P2 (Mehrfach-Normalisierung) bleiben bewusst offen und sind im Audit dokumentiert.
