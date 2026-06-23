# Latenz-Profiling, UI-Cleanup, Auto-Retry & Avatar-Pausen — Design

**Datum:** 2026-06-23
**Branch:** feature/tavus

## Ziel

Vier unabhängige Verbesserungen am KIRA-Chatbot:

1. **RAG-Latenz transparent machen** — Antworten dauern lange, wenn der RAG-Schritt läuft, obwohl die eigentliche LLM-Antwort schnell ist. Erst messen, dann gezielt optimieren.
2. **Mikrofon-/Spracheingabe-Button** aus dem Chat-UI entfernen.
3. **Automatischer Retry** im Frontend bei "Service momentan nicht verfügbar".
4. **Komische Pausen** des Avatars beim Erzählen untersuchen und beheben.

Jedes Item ist eigenständig und kann separat umgesetzt/committet werden.

---

## Kontext (Ist-Zustand)

- `app/rag.py`: `build_rag_context` macht Query-Embedding (SentenceTransformer, CPU),
  ChromaDB-Queries (zweistufig parallel via `ThreadPoolExecutor`, einstufig sonst) und
  CrossEncoder-Reranking (`reranker.predict` auf ~12–16 Paaren, CPU).
- `app/routes/chat.py`: misst `latency_ms` **erst ab dem Gemini-Stream** (`t1` wird nach
  dem RAG-Aufruf gesetzt). Die RAG-Zeit ist im UI also unsichtbar. Backend retryt Gemini 3×.
- `static/index.html`:
  - `ttsBtn` ([672](../../../static/index.html#L672)) = Mikrofon-Button für Spracheingabe
    (Web Speech API), JS bei [935–967](../../../static/index.html#L935-L967), Sprachwechsel
    bei [813](../../../static/index.html#L813), Stop bei [1137](../../../static/index.html#L1137).
  - SSE-`error`-Handling bei [1233–1236](../../../static/index.html#L1233-L1236) ruft nur
    `showError()`, kein Retry.
  - `speakAnswer()` ([1270](../../../static/index.html#L1270)) schickt den **Text-Mode-Antworttext**
    via `conversation.echo` an Tavus (Path A).
- `app/routes/tavus.py`: `/tavus/llm` (Path B) nutzt den **Voice-Mode-Prompt** und streamt
  Gemini-Chunks unverändert an Tavus weiter ([207–230](../../../app/routes/tavus.py#L207-L230)).

---

## Item 1 — RAG-Latenz: erst messen

**Ansatz:** Instrumentierung vor Optimierung. Keine Optimierung wird committet, bevor
echte Zahlen vorliegen.

**Änderungen:**
- In `build_rag_context` (`app/rag.py`) Phasen-Timing per `time.perf_counter()` um die
  teuren Schritte legen: ChromaDB-Query(s) und Reranking getrennt messen.
- Eine `logging.info`-Zeile am Ende mit den Phasenzeiten, z.B.:
  `[RAG-TIMING] total=Xms (query=Yms, rerank=Zms) sg=<studiengang>`.
- Optional (Item 1b, nach Messung zu entscheiden): die gemessene RAG-Gesamtzeit aus
  `build_rag_context` zusätzlich zurückgeben, damit `chat.py` sie im `done`-Event neben
  `latency_ms` ausweisen kann (z.B. `rag_ms`). Nur umsetzen, wenn die Messung zeigt, dass
  RAG der Engpass ist.

**Entscheidung nach Messung:** Erst nach Vorliegen der Zahlen wird eine gezielte Optimierung
gewählt (wahrscheinliche Kandidaten: Reranker-Kandidatenzahl senken oder Reranking im
einstufigen Pfad überspringen). Diese Optimierung ist **nicht** Teil dieses Specs — sie wird
auf Basis der Messung separat entschieden.

**Akzeptanz:** Nach einer Chat-Anfrage steht im Log eine `[RAG-TIMING]`-Zeile mit
getrennten Query- und Rerank-Zeiten. Bestehende Tests bleiben grün.

---

## Item 2 — Mikrofon-/Spracheingabe-Button entfernen

**Bestätigt:** Gemeint ist `ttsBtn` (Mikrofon-Symbol, "Spracheingabe") im Chat-Eingabebereich.

**Änderungen in `static/index.html`:**
- Button-Markup [672–676](../../../static/index.html#L672-L676) entfernen.
- Zugehöriges JS entfernen: `ttsBtn`-Referenz [913](../../../static/index.html#L913),
  `recognition`-Setup + Event-Handler [935–967](../../../static/index.html#L935-L967),
  Sprachzeile [813](../../../static/index.html#L813), Stop-Aufruf [1137](../../../static/index.html#L1137).
- Ungenutztes CSS (`.tts-btn`, `.tts-btn.active`) [414–428, 567–568](../../../static/index.html#L414-L428)
  entfernen.
- Prüfen, dass keine verwaisten Referenzen auf `ttsBtn`/`recognition` zurückbleiben.

**Akzeptanz:** Kein Mikrofon-Button mehr im Chat; keine JS-Konsolen-Fehler; Senden per
Text/Enter funktioniert unverändert.

---

## Item 3 — Auto-Retry im Frontend

**Ansatz:** Stiller automatischer Retry im Frontend, zusätzlich zum bestehenden Backend-Retry.

**Änderungen in `static/index.html`:**
- Beim Empfang eines SSE-`error`-Events mit der Meldung "Service momentan nicht verfügbar"
  (bzw. allgemeinem Fehler) die ursprüngliche Anfrage automatisch **bis zu 2×** mit kurzem
  Backoff (~1.5s) erneut senden, statt sofort `showError()` aufzurufen.
- Während des Retrys einen dezenten Status anzeigen (z.B. "Verbindung wird erneut versucht…").
- Erst wenn auch der letzte Versuch fehlschlägt, `showError()` mit der dauerhaften Meldung.
- Retry-Zähler pro Sende-Vorgang, damit keine Endlosschleife entsteht.

**Akzeptanz:** Bei einem transienten Fehler versucht das UI automatisch erneut; erst nach
erschöpften Versuchen erscheint die Fehlermeldung. Erfolgreicher Retry zeigt die Antwort
normal an.

---

## Item 4 — Avatar-Pausen untersuchen & beheben

**Leithypothese:** In Path B (`/tavus/llm`) spricht Tavus den Gemini-Stream chunkweise;
uneinheitliche Chunk-Grenzen (mitten im Satz) und Generierungs-Lücken erzeugen unnatürliche
Pausen. Sekundär: URLs wie "campus.kit.edu" lassen die TTS stocken.

**Vorgehen:**
1. Stream-Verhalten verifizieren (Chunk-Größen/-Grenzen aus `/tavus/llm` betrachten).
2. Fix (sofern Hypothese bestätigt): den Stream in `stream_answer()` (`app/routes/tavus.py`)
   in **vollständige Sätze puffern**, bevor jedes `delta` an Tavus geht — TTS erhält saubere
   Satzeinheiten statt Token-Fragmente.
3. TTS-feindliche Tokens normalisieren (z.B. "campus.kit.edu" → vorlesefreundliche Form).
   Gilt für beide Pfade: Path B im Backend; Path A optional in `speakAnswer()`.

**Akzeptanz:** Der Avatar spricht flüssiger ohne unnatürliche Pausen mitten im Satz;
URLs werden sauber vorgelesen. Der sichtbare Chat-Text bleibt unverändert.

---

## Nicht im Scope

- Konkrete RAG-Optimierung (Item 1 misst nur; Optimierung folgt separat nach Messung).
- GPU-Beschleunigung oder Reranker-Modellwechsel.
- Änderungen am Voice-/Text-Prompt-Inhalt (außer ggf. TTS-Normalisierung von URLs).

## Reihenfolge

1 (Messung) → 2 (UI-Cleanup) → 3 (Auto-Retry) → 4 (Avatar-Pausen). Items sind unabhängig
und einzeln committebar.
