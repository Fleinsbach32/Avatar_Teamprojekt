# Änderungen – 15. Juni 2026

## 1. KIRA Prompt grundlegend überarbeitet (`main.py`)

### Struktur
Der Prompt wurde von einem einzelnen Block in zwei separate Konstanten aufgeteilt:

- `KIRA_PERSONA` — Kerndefinition: Rolle, Aufgabe, Persönlichkeit, Antwortregeln, Sicherheit, Klärungsverhalten
- `KIRA_VOICE_EXTRA` — Zusatzregeln speziell für Sprachausgabe (Zahlen ausschreiben, keine Abkürzungen)
- `KIRA_PROMPT = KIRA_PERSONA + KIRA_VOICE_EXTRA` — kombinierter Prompt wie bisher

### Inhaltliche Änderungen im Prompt

**Neu hinzugekommen:**

- **Aufgabe-Sektion**: Explizite Beschreibung des Zuständigkeitsbereichs (Wirtschaftswissenschaften am KIT, Bewerbung, Prüfungen, Fristen, Campusleben, Organisatorisches)
- **Modulnummern weglassen**: KIRA nennt keine kryptischen IDs (z.B. `M-MACH-101267`), nur den reinen Modulnamen
- **Adaptive Antwortlänge**: 1–2 Sätze bei einfachen Fragen, 3–5 Sätze bei komplexen Themen
- **Schritte fließend**: Bei Schritt-für-Schritt-Antworten "Erstens... Zweitens... Zuletzt..." statt Listen
- **Sicherheits-Sektion**: Expliziter Block gegen Prompt-Injection / Rollenveränderung
- **Nachfragen-Sektion**: KIRA antwortet direkt und präzise, fragt nur nach wenn die Frage wirklich unklar ist

**Geändert:**

- Abgrenzungsformel präzisiert: nur noch Fragen ohne KIT/Studium-Bezug werden abgelehnt (vorher allgemeiner)
- Rhythmus und Satzstruktur explizit auf Vorlesen optimiert (war vorher implizit)

---

## 2. Begrüßungs-Logik vereinfacht (`main.py` + `static/index.html`)

### Vorher
- `custom_greeting: ""` (leerer String) → Tavus-Standardbegrüßung unterdrückt
- Frontend hat nach 3 Sekunden (`GREETING_DELAY_MS`) selbst eine Begrüßung abgespielt und in den Chat geschrieben

### Jetzt
- `custom_greeting: " "` (einzelnes Leerzeichen) → Tavus-Begrüßung weiterhin unterdrückt
- **Frontend-Begrüßungslogik komplett entfernt** — kein `setTimeout`, kein `speakAnswer(KIRA_GREETING)`, kein `addMessage` beim Verbindungsaufbau
- Begrüßung kommt künftig direkt vom Avatar/Backend, nicht mehr vom Frontend injiziert

**Effekt:** Weniger Race-Condition-Risiko (Avatar spricht nicht mehr, bevor er sichtbar ist, weil das Frontend-Timing weggefallen ist).

---

## 3. Neue API-Route (`main.py`)

```
POST /chat/completions
```

Identische Handler-Funktion wie `/tavus/llm` und `/tavus/llm/chat/completions`. Ermöglicht direkten Zugriff auf den LLM-Endpunkt im OpenAI-kompatiblen Format ohne Tavus-Präfix.

---

## 4. Test angepasst (`tests/test_prompts.py`)

- `assert "Variiere" in main.KIRA_PROMPT` → `assert "Rhythmus" in main.KIRA_PROMPT`
- Grund: "Variiere Satzbau..." wurde aus dem Prompt entfernt, "Rhythmus" ist weiterhin enthalten
