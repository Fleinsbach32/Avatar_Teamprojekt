# Flash-Lite-Test Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Das Benchmark-Tool so erweitern, dass wir flash-lite gegen flash auf gemessene Latenz UND Antwortqualität vergleichen können — als Datenbasis für die Entscheidung, ob der Voice-Pfad auf flash-lite umgestellt wird.

**Architecture:** `stream_gemini` bekommt einen optionalen `model`-Parameter (Default `None` = bisheriges Verhalten mit flash + flash-lite-Fallback). `bench_latency.py` bekommt `--model` (Modell-Override) und `--show-answers` (generierten Antworttext erfassen + ausgeben). Reine Mess-Erweiterung — Produktivverhalten von `/chat` und `/tavus/llm` bleibt unverändert.

**Tech Stack:** Python 3.11, asyncio, Google Gemini SDK, pytest. Keine neue Dependency.

---

## Dateiübersicht

| Datei | Aktion | Verantwortung |
|---|---|---|
| `app/gemini.py` | Modify | `stream_gemini` optionaler `model`-Parameter |
| `tests/test_chat_stream.py` | Modify | Test: expliziter `model` wird für alle Versuche genutzt |
| `scripts/bench_latency.py` | Modify | `--model` + `--show-answers`, Antworttext erfassen |

---

### Task 1: `stream_gemini` — optionaler `model`-Parameter

**Files:**
- Modify: `app/gemini.py`
- Test: `tests/test_chat_stream.py`

- [ ] **Step 1: Failing Test schreiben**

In `tests/test_chat_stream.py` direkt nach dem Test `test_chat_last_attempt_uses_fallback_model` einfügen:
```python
def test_stream_gemini_explicit_model_overrides_all_attempts():
    import asyncio
    import app.gemini as gemini

    async def drive():
        out = []
        async for t in gemini.stream_gemini("p", 100, 0, model="gemini-2.5-flash-lite"):
            out.append(t)
        return out

    with patch("app.gemini.client") as mock_client:
        # Erster Versuch scheitert, zweiter gelingt — beide müssen flash-lite nutzen
        mock_client.aio.models.generate_content_stream = AsyncMock(
            side_effect=[RuntimeError("503"), make_async_stream(["ok"])]
        )
        result = asyncio.run(drive())

    assert result == ["ok"]
    calls = mock_client.aio.models.generate_content_stream.call_args_list
    assert calls, "stream_gemini hat generate_content_stream nicht aufgerufen"
    assert all(c.kwargs["model"] == "gemini-2.5-flash-lite" for c in calls)
```

- [ ] **Step 2: Test schlägt fehl**

Run: `python -m pytest tests/test_chat_stream.py::test_stream_gemini_explicit_model_overrides_all_attempts -v`
Expected: FAIL (`stream_gemini() got an unexpected keyword argument 'model'`).

- [ ] **Step 3: `model`-Parameter implementieren**

In `app/gemini.py` die Funktionssignatur und die Modellwahl anpassen. Ersetze:
```python
async def stream_gemini(prompt: str, max_tokens: int, retry_delay: float, attempts: int = 3):
    """Async-Generator: liefert Text-Chunks von Gemini.

    Retry nur VOR dem ersten Chunk (bis zu `attempts` Versuche) mit exponentiellem
    Backoff (`retry_delay`, dann ×2, ×4 …). Der letzte Versuch nutzt das Fallback-
    Modell, falls das Primärmodell überlastet ist (503 UNAVAILABLE).
    - Scheitert es vor dem ersten Chunk endgültig → raise GeminiUnavailable.
    - Scheitert es nach bereits gesendeten Chunks → raise GeminiMidStreamError (kein Retry).
    """
    gesendet = False
    for versuch in range(attempts):
        # Letzter Versuch weicht auf das Fallback-Modell aus.
        model = FALLBACK_MODEL if versuch == attempts - 1 else PRIMARY_MODEL
```
durch:
```python
async def stream_gemini(prompt: str, max_tokens: int, retry_delay: float, attempts: int = 3, model: str | None = None):
    """Async-Generator: liefert Text-Chunks von Gemini.

    Retry nur VOR dem ersten Chunk (bis zu `attempts` Versuche) mit exponentiellem
    Backoff (`retry_delay`, dann ×2, ×4 …). Ohne explizites `model` nutzt der letzte
    Versuch das Fallback-Modell, falls das Primärmodell überlastet ist (503). Wird
    `model` gesetzt, nutzen ALLE Versuche dieses Modell (für Benchmarks/Tests).
    - Scheitert es vor dem ersten Chunk endgültig → raise GeminiUnavailable.
    - Scheitert es nach bereits gesendeten Chunks → raise GeminiMidStreamError (kein Retry).
    """
    gesendet = False
    for versuch in range(attempts):
        # Explizites Modell überschreibt die Primär/Fallback-Logik.
        if model is not None:
            used_model = model
        else:
            used_model = FALLBACK_MODEL if versuch == attempts - 1 else PRIMARY_MODEL
```

Dann im `try`-Block und im `except`-Logging `model` → `used_model` umbenennen. Ersetze:
```python
        try:
            stream = await client.aio.models.generate_content_stream(
                model=model,
                contents=prompt,
                config=gemini_config(max_tokens),
            )
            async for chunk in stream:
                if chunk.text:
                    gesendet = True
                    yield chunk.text
            return
        except Exception as e:
            logging.warning(f"Gemini Stream Fehler (Modell {model}, Versuch {versuch + 1}): {e}")
```
durch:
```python
        try:
            stream = await client.aio.models.generate_content_stream(
                model=used_model,
                contents=prompt,
                config=gemini_config(max_tokens),
            )
            async for chunk in stream:
                if chunk.text:
                    gesendet = True
                    yield chunk.text
            return
        except Exception as e:
            logging.warning(f"Gemini Stream Fehler (Modell {used_model}, Versuch {versuch + 1}): {e}")
```

- [ ] **Step 4: Test grün + Regression**

Run: `python -m pytest tests/test_chat_stream.py -v`
Expected: alle PASS (inkl. `test_chat_last_attempt_uses_fallback_model`, das den Default-Pfad ohne `model` prüft).

- [ ] **Step 5: Commit**
```bash
git add app/gemini.py tests/test_chat_stream.py
git commit -m "feat(gemini): stream_gemini optionaler model-Parameter (Default unveraendert)"
```

---

### Task 2: `bench_latency.py` — `--model` + `--show-answers`

**Files:**
- Modify: `scripts/bench_latency.py`

- [ ] **Step 1: `measure_one` — Modell durchreichen + Antwort erfassen**

In `scripts/bench_latency.py` die Signatur von `measure_one` und die Stream-Schleife anpassen. Ersetze:
```python
async def measure_one(question: str, studiengang, with_llm: bool) -> dict:
    """Misst RAG-Zeit und (optional) Gemini-TTFT/Generierungszeit für eine Frage."""
    from app.rag import build_rag_context

    t0 = time.perf_counter()
    kontext, anweisung, _ = build_rag_context(question, studiengang)
    rag_ms = (time.perf_counter() - t0) * 1000

    ttft_ms = gen_ms = None
    e2e_ms = rag_ms
    ok = True
    if with_llm:
        from app.gemini import stream_gemini, GeminiUnavailable, GeminiMidStreamError
        from app.prompts import build_prompt

        prompt = f"""{build_prompt("text", "de")}

{anweisung}

Kontext:
{kontext}

Frage: {question}"""
        t1 = time.perf_counter()
        first = None
        try:
            async for chunk in stream_gemini(prompt, 400, 0):
                if first is None:
                    first = time.perf_counter()
                _ = chunk
        except (GeminiUnavailable, GeminiMidStreamError):
            # Gemini-Ausfall (z.B. 503): Frage als fehlgeschlagen vermerken,
            # Benchmark läuft weiter statt zu crashen.
            ok = False
        if ok:
            last = time.perf_counter()
            if first is not None:
                ttft_ms = (first - t1) * 1000
            gen_ms = (last - t1) * 1000
            e2e_ms = rag_ms + gen_ms

    return {
        "question": question,
        "studiengang": studiengang,
        "ok": ok,
        "rag_ms": round(rag_ms, 1),
        "ttft_ms": round(ttft_ms, 1) if ttft_ms is not None else None,
        "gen_ms": round(gen_ms, 1) if gen_ms is not None else None,
        "e2e_ms": round(e2e_ms, 1),
    }
```
durch:
```python
async def measure_one(question: str, studiengang, with_llm: bool, model=None) -> dict:
    """Misst RAG-Zeit und (optional) Gemini-TTFT/Generierungszeit für eine Frage.
    `model` (optional) erzwingt ein bestimmtes Gemini-Modell für den Vergleich."""
    from app.rag import build_rag_context

    t0 = time.perf_counter()
    kontext, anweisung, _ = build_rag_context(question, studiengang)
    rag_ms = (time.perf_counter() - t0) * 1000

    ttft_ms = gen_ms = None
    e2e_ms = rag_ms
    ok = True
    answer = None
    if with_llm:
        from app.gemini import stream_gemini, GeminiUnavailable, GeminiMidStreamError
        from app.prompts import build_prompt

        prompt = f"""{build_prompt("text", "de")}

{anweisung}

Kontext:
{kontext}

Frage: {question}"""
        t1 = time.perf_counter()
        first = None
        parts: list[str] = []
        try:
            async for chunk in stream_gemini(prompt, 400, 0, model=model):
                if first is None:
                    first = time.perf_counter()
                parts.append(chunk)
        except (GeminiUnavailable, GeminiMidStreamError):
            # Gemini-Ausfall (z.B. 503): Frage als fehlgeschlagen vermerken,
            # Benchmark läuft weiter statt zu crashen.
            ok = False
        if ok:
            last = time.perf_counter()
            if first is not None:
                ttft_ms = (first - t1) * 1000
            gen_ms = (last - t1) * 1000
            e2e_ms = rag_ms + gen_ms
            answer = "".join(parts).strip()

    return {
        "question": question,
        "studiengang": studiengang,
        "ok": ok,
        "rag_ms": round(rag_ms, 1),
        "ttft_ms": round(ttft_ms, 1) if ttft_ms is not None else None,
        "gen_ms": round(gen_ms, 1) if gen_ms is not None else None,
        "e2e_ms": round(e2e_ms, 1),
        "answer": answer,
    }
```

- [ ] **Step 2: `run` — Modell durchreichen + in Summary aufnehmen**

Ersetze:
```python
async def run(with_llm: bool) -> dict:
    from dotenv import load_dotenv
    load_dotenv(PROJECT_ROOT / ".env")

    eval_set = json.loads(EVAL_SET_PATH.read_text(encoding="utf-8"))
    records = []
    for item in eval_set:
        rec = await measure_one(item["question"], item.get("studiengang"), with_llm)
        records.append(rec)
    return {
        "with_llm": with_llm,
        "questions": len(records),
        "failed": sum(1 for r in records if not r.get("ok", True)),
        "aggregate": _aggregate(records),
        "records": records,
    }
```
durch:
```python
async def run(with_llm: bool, model=None) -> dict:
    from dotenv import load_dotenv
    load_dotenv(PROJECT_ROOT / ".env")

    eval_set = json.loads(EVAL_SET_PATH.read_text(encoding="utf-8"))
    records = []
    for item in eval_set:
        rec = await measure_one(item["question"], item.get("studiengang"), with_llm, model=model)
        records.append(rec)
    return {
        "with_llm": with_llm,
        "model": model or "default (flash + flash-lite-Fallback)",
        "questions": len(records),
        "failed": sum(1 for r in records if not r.get("ok", True)),
        "aggregate": _aggregate(records),
        "records": records,
    }
```

- [ ] **Step 3: `_print` zeigt das Modell + neue `_print_answers`**

In `_print` die Kopfzeile um das Modell ergänzen. Ersetze:
```python
    print(f"\n{'='*64}")
    print(f"  Latenz-Benchmark — {summary['questions']} Fragen — {mode}")
```
durch:
```python
    print(f"\n{'='*64}")
    print(f"  Latenz-Benchmark — {summary['questions']} Fragen — {mode}")
    print(f"  Modell: {summary.get('model', 'default')}")
```

Direkt nach der `_print`-Funktion (vor `def main()`) einfügen:
```python
def _print_answers(summary: dict) -> None:
    print(f"\n{'-'*64}")
    print("  GENERIERTE ANTWORTEN")
    print(f"{'-'*64}")
    for r in summary["records"]:
        ans = (r.get("answer") or "—").replace("\n", " ")
        if len(ans) > 200:
            ans = ans[:200] + "…"
        print(f"\n  • {r['question']}")
        print(f"    {ans}")
    print()
```

- [ ] **Step 4: `main` — `--model` + `--show-answers`**

Ersetze die `main`-Funktion:
```python
def main() -> None:
    parser = argparse.ArgumentParser(description="KIRA Latenz-Benchmark")
    parser.add_argument("--no-llm", action="store_true", help="Nur RAG messen (offline)")
    parser.add_argument("--save", help="Ergebnis als JSON speichern")
    args = parser.parse_args()

    summary = asyncio.run(run(with_llm=not args.no_llm))
    _print(summary)

    if args.save:
        Path(args.save).write_text(
            json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        print(f"  Gespeichert: {args.save}\n")
```
durch:
```python
def main() -> None:
    parser = argparse.ArgumentParser(description="KIRA Latenz-Benchmark")
    parser.add_argument("--no-llm", action="store_true", help="Nur RAG messen (offline)")
    parser.add_argument("--model", help="Gemini-Modell erzwingen (z.B. gemini-2.5-flash-lite)")
    parser.add_argument("--show-answers", action="store_true", help="Generierte Antworten ausgeben")
    parser.add_argument("--save", help="Ergebnis als JSON speichern")
    args = parser.parse_args()

    summary = asyncio.run(run(with_llm=not args.no_llm, model=args.model))
    _print(summary)
    if args.show_answers and not args.no_llm:
        _print_answers(summary)

    if args.save:
        Path(args.save).write_text(
            json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        print(f"  Gespeichert: {args.save}\n")
```

- [ ] **Step 5: Import-Check + Aggregations-Tests**

Run: `python -c "import sys; sys.path.insert(0, 'scripts'); import bench_latency; print('ok')"`
Expected: `ok`.

Run: `python -m pytest tests/test_bench_latency.py -q`
Expected: PASS (Signatur von `_aggregate` unverändert; neue `answer`-Key wird ignoriert).

- [ ] **Step 6: Offline-Smoke-Run (keine Antworten, kein API-Key)**

Run: `python scripts/bench_latency.py --no-llm`
Expected: Tabelle wie zuvor, zusätzlich Zeile `Modell: default (flash + flash-lite-Fallback)`; kein Crash.

- [ ] **Step 7: Volle Test-Suite**

Run: `python -m pytest tests/ -q`
Expected: alle PASS.

- [ ] **Step 8: Commit**
```bash
git add scripts/bench_latency.py
git commit -m "feat(bench): --model + --show-answers fuer flash-vs-flash-lite-Vergleich"
```

---

### Task 3: Vergleich durchführen + Entscheidung

**Files:** keine Änderung — Ausführung/Auswertung (Nutzer, mit API-Key).

- [ ] **Step 1: flash-Baseline mit Antworten**

Run: `python scripts/bench_latency.py --save bench_flash.json --show-answers`
Erwartet: Latenz + generierte Antworten für flash. (`bench_flash.json` liegt im Root — bewusst NICHT committen.)

- [ ] **Step 2: flash-lite messen mit Antworten**

Run: `python scripts/bench_latency.py --model gemini-2.5-flash-lite --save bench_lite.json --show-answers`
Erwartet: Latenz + generierte Antworten für flash-lite.

- [ ] **Step 3: Vergleichen + entscheiden**

Gegenüberstellen:
- **Latenz-Delta:** Median `ttft_ms`, `gen_ms`, `e2e_ms` flash vs flash-lite — bestätigt/widerlegt die ~−400ms-Schätzung.
- **Qualität:** Die `--show-answers`-Ausgaben Seite an Seite lesen. Bleibt flash-lite bei den Modul-/Fakten-Fragen nah am Kontext, oder wird es vager/ungenauer?

Entscheidung: Wenn flash-lite spürbar schneller ist UND die Antwortqualität bei den 20 Gold-Fragen hält → eigener Folge-Block, der den Voice-Pfad (`app/routes/tavus.py`) auf flash-lite umstellt. Wenn die Qualität abfällt → bei flash bleiben.

---

## Self-Review-Notiz

Abgedeckt: `stream_gemini` `model`-Parameter mit Default-Erhalt (T1, getestet inkl. Regression des Fallback-Defaults), `--model`/`--show-answers` + Antworterfassung (T2), Vergleichs-Durchführung + Entscheidungskriterien (T3). Parameternamen konsistent: `model` durch `measure_one`/`run`/`stream_gemini`. Default `None` erhält bisheriges flash+flash-lite-Verhalten — `/chat` und `/tavus/llm` rufen ohne `model` auf, also keine Produktiv-Änderung. Keine Platzhalter.
