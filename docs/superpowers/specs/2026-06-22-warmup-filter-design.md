# Design: Gemini-Warmup + Studiengang-Filter-Reliability (22.06.2026)

**Status:** Freigegeben, bereit für Implementierungsplan
**Branch:** `feature/tavus`

## Ziel

Zwei konkrete Probleme beheben:
1. **Cold-Start-Latenz:** Erste Nachricht nach Server-Start hängt ~1–3 Sekunden, weil der Gemini-HTTP-Client noch keine offene Verbindung hat.
2. **Studiengang-Filter wirkt nicht:** Antworten unterscheiden sich nicht zwischen Studiengängen; gleiches Ergebnis wie ohne Filter.

---

## Getroffene Entscheidungen

| Thema | Entscheidung |
|-------|--------------|
| Latenz-Fix | Gemini-Warmup im Lifespan (ein Mini-Call mit `max_output_tokens=1`) |
| Filter-Ansatz | Erst diagnostizieren, dann gezielt fixen + defensive Logs |
| Diagnose-Werkzeug | Neues `scripts/debug_rag.py` (CLI, kein Server nötig) |
| Scope | Kein UX-Umbau des Dropdowns; Dropdown bleibt, Filter muss einfach wirken |
| Tests | Kein separater Unit-Test für Warmup (Lifespan läuft im TestClient nicht); Import-Check genügt |

---

## Workstream 1 — Gemini Cold-Start Warmup

### Problem

`app/main.py` wärmt ChromaDB, Embedding-Modell und CrossEncoder auf — aber nicht den **Gemini-HTTP-Client**. Der `genai.Client` öffnet die TCP+TLS-Verbindung zu Googles API erst beim ersten echten Request. Das kostet ~1–3 Sek. und trifft die erste Nutzeranfrage nach jedem Server-Start.

### Lösung

**Datei:** `app/main.py`

Im Lifespan nach dem Reranker-Warmup:

```python
from app.gemini import client
from google.genai import types

@asynccontextmanager
async def lifespan(app: FastAPI):
    # ChromaDB-Warmup (bereits vorhanden)
    try:
        collection.query(query_texts=["Warmup"], n_results=1)
    except Exception as e:
        logging.warning(f"ChromaDB Warmup fehlgeschlagen: {e}")

    # Reranker-Warmup (bereits vorhanden)
    if reranker is not None:
        try:
            reranker.predict([("Warmup", "Warmup")])
        except Exception as e:
            logging.warning(f"Reranker Warmup fehlgeschlagen: {e}")

    # Gemini-Warmup (NEU)
    try:
        await client.aio.models.generate_content(
            model="gemini-2.5-flash",
            contents="Warmup",
            config=types.GenerateContentConfig(
                max_output_tokens=1,
                thinking_config=types.ThinkingConfig(thinking_budget=0),
            ),
        )
    except Exception as e:
        logging.warning(f"Gemini Warmup fehlgeschlagen: {e}")

    yield
    await tavus._http.aclose()
```

### Verhalten

- Server-Start dauert ~1–2 Sek. länger (einmalig).
- Erste Nutzeranfrage fühlt sich gleich schnell an wie alle folgenden.
- Schlägt der Warmup fehl (z.B. kein Netz), startet der Server trotzdem — nur `logging.warning`.

### Tests

`pytest` läuft ohne Lifespan (TestClient ohne `with`), daher kein Unit-Test nötig. Import-Check genügt:

```bash
python -c "import app.main; print('IMPORT OK')"
```

---

## Workstream 2 — Studiengang-Filter Reliability

### Problem

Antworten mit gewähltem Studiengang unterscheiden sich nicht von Antworten ohne Filter. Diagnose noch ausstehend; zwei wahrscheinliche Ursachen:

**Ursache A:** Im `_WHAT_IS_MODULE_RE`-Pfad (z.B. "Was ist Introduction to Digital Economics?") schlägt die `$contains`-Suche fehl, weil der Modulname im PDF anders formatiert ist als die Benutzereingabe. Ergebnis: kein Handbuch-Treffer, Fallback auf Semantiksuche, die dann generische "all"-Chunks findet.

**Ursache B:** Im Standardsuch-Zweig (`_merge_handbook_priority`) ist `prog_docs` leer oder sehr kurz, weil die semantische Distanz zwischen Frage und Handbuch-Chunks groß ist. Reranker priorisiert dann "all"-Chunks.

### Lösung: Drei Phasen

#### Phase A — Diagnose-Skript `scripts/debug_rag.py`

CLI-Tool, das `build_rag_context` direkt aufruft und jeden Schritt offenlegt:

```
python scripts/debug_rag.py "Was ist Introduction to Digital Economics?" --studiengang digieco_bsc
python scripts/debug_rag.py "Welche Pflichtmodule hat WING?" --studiengang wing_bsc
```

Ausgabe:
```
Query   : Was ist Introduction to Digital Economics?
SG      : digieco_bsc
Pfad    : WAS_IST_MODULE  (was_is_name="Introduction to Digital Economics")
$contains-Varianten: ['Introduction to Digital Economics', 'Introduction To...', 'Introduction']
  Variante "Introduction to Digital Economics" → 0 Treffer
  Variante "Introduction To Digital Economics" → 0 Treffer
  Variante "Introduction"                     → 3 Treffer

prog_docs (Semantik): 8 Chunks  [SG=digieco_bsc]
all_docs  (Semantik): 4 Chunks  [SG=all]
Nach _merge_handbook_priority: 6 Chunks (3 Handbuch, 3 all)

Finaler Kontext (Auszug):
  [0] digieco_bsc | 0.18 | "Modul: Grundlagen Digital Economics..."
  [1] all         | 0.22 | "Das KIT bietet..."
  ...

beste_distanz: 0.18  → Quelle: Wissensbasis
```

**Datei:** `scripts/debug_rag.py`
- Setzt `sys.path` auf Project-Root (kein installiertes Package nötig)
- Importiert `build_rag_context` und interne Hilfsfunktionen direkt
- `--studiengang` optional
- Kein Server nötig; nutzt echte ChromaDB

#### Phase B — Defensive Logs in `app/rag.py`

Im zweistufigen Zweig (nach den beiden `_query_safe`-Calls) und im `$contains`-Pfad je eine `logging.info`-Zeile einbauen:

```python
# Zweistufige Suche:
logging.info(
    f"[RAG] SG={studiengang}: prog={len(prog_docs)} handbuch, all={len(all_docs)} general"
    f" → final={len(docs)} chunks"
)

# $contains-Pfad:
logging.info(
    f"[RAG] was_ist='{what_is_name}': contains-Treffer={len(what_results['documents'][0])}"
    f" (where={where})"
)
```

Mit `uvicorn --log-level info` sieht man sofort ob der Filter greift.

#### Phase C — Fix je nach Diagnosebefund

**Fix C1 (falls $contains scheitert wegen Formatunterschied):**

`_contains_variants()` um weitere Varianten erweitern — insbesondere lowercase und partielle Matches für englische Modulnamen:

```python
def _contains_variants(name: str) -> list[str]:
    variants = [name, name.title(), name.capitalize(), name.lower()]
    words = name.split()
    if len(words) > 1:
        # Ersten Teil ab 4 Zeichen als Fallback
        for w in words:
            if len(w) >= 4:
                variants.extend([w, w.title(), w.lower()])
                break
    return list(dict.fromkeys(v for v in variants if v))
```

**Fix C2 (falls prog_docs konsistent leer ist):**

Vor `_merge_handbook_priority` prüfen ob `prog_docs` leer ist und in diesem Fall eine deutliche Warnung loggen:

```python
if studiengang and not prog_docs:
    logging.warning(
        f"[RAG] Keine Handbuch-Chunks für studiengang={studiengang!r} gefunden "
        f"— Filter greift möglicherweise nicht. DB-Metadaten prüfen."
    )
```

**Fix C3 (falls $contains-Pfad korrekt "nicht gefunden" meldet, Semantiksuche aber falsch fällt):**

Im Fallback ohne Studiengang (`# Kein Studiengang → weiter zur Standard-Semantiksuche unten`) sicherstellen, dass auch die Semantiksuche mit dem extrahierten Modulnamen als Query läuft, nicht mit der Originalfrage.

### Welcher Fix wird angewandt?

Das bestimmt das Diagnose-Skript (`debug_rag.py`). Die drei Fixes schließen sich nicht aus; alle drei können gleichzeitig angewandt werden.

---

## Betroffene Dateien

| Datei | Änderung |
|-------|----------|
| `app/main.py` | Gemini-Warmup im Lifespan |
| `app/rag.py` | Defensive Logs, ggf. `_contains_variants`-Erweiterung, ggf. empty-prog-Warning |
| `scripts/debug_rag.py` | Neu — Diagnose-Tool |

## Nicht im Scope

- Umbau des Dropdown-Menüs (User: "Filter soll einfach wirken")
- Neu-Befüllung der ChromaDB (erst nach Diagnose entscheiden)
- Änderungen an `fill_db.py` (außer wenn Diagnose Metadata-Mismatch zeigt)
- Änderungen an der Frontend-Logik für `studiengang`-Übergabe (funktioniert bereits)

---

## Akzeptanzkriterien

1. Erste Nachricht nach Server-Start fühlt sich nicht langsamer an als folgende Nachrichten.
2. `python scripts/debug_rag.py "Was ist Introduction to Digital Economics?" --studiengang digieco_bsc` zeigt ≥1 Handbuch-Chunk mit `SG=digieco_bsc` im finalen Kontext.
3. Dieselbe Query mit `--studiengang wing_bsc` zeigt entweder WING-spezifische Handbuch-Chunks oder eine klare "nicht in diesem Studiengang"-Anweisung.
4. `python -m pytest tests/ -q` → alle grün.
5. Im Server-Log (`logging.info`) ist pro Anfrage sichtbar wie viele Handbuch- vs. allgemeine Chunks gefunden wurden.
