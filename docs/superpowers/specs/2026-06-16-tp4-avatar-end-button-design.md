# Teil-Projekt 4 — Avatar-Beenden-Button: Design

**Datum:** 2026-06-16
**Status:** Genehmigt
**Branch:** feature/tavus

## Ziel

Einen sichtbaren Button hinzufügen, mit dem ein laufendes Avatar-Gespräch
(Tavus) beendet werden kann. Bisher endet die Session nur über `left-meeting`
(serverseitig/Timeout) oder `beforeunload` (Seite schließen) — es gibt kein
UI-Element zum aktiven Beenden.

## Platzierung

Overlay oben links auf dem Avatar-Video (`position:absolute` in
`.avatar-container`). Nur sichtbar, während ein Gespräch läuft.

## Umsetzung (nur `static/index.html`)

### HTML
Neuer Button in `.avatar-container`, initial versteckt:
```html
<button id="endAvatarBtn" class="end-avatar-btn" style="display:none;" onclick="endAvatar()"></button>
```

### CSS
```css
.end-avatar-btn {
  position: absolute; top: 12px; left: 12px; z-index: 5;
  background: #ef4444; color: #fff; border: none;
  border-radius: 20px; padding: 8px 16px;
  font-size: 13px; font-weight: 500; font-family: var(--font);
  cursor: pointer; box-shadow: 0 2px 8px rgba(0,0,0,0.2);
  transition: background 0.15s, transform 0.1s;
}
.end-avatar-btn:hover  { background: #dc2626; transform: translateY(-1px); }
.end-avatar-btn:active { transform: scale(0.97); }
```

### JS — Logik
- `endAvatar()`: `if (tavusCall) tavusCall.leave();` — der bestehende
  `left-meeting`-Handler erledigt den gesamten Teardown (`/tavus/end`,
  `destroy()`, UI-Reset auf „Erneut verbinden", Status „getrennt"). Kein
  duplizierter Teardown-Code.
- **Einblenden:** im `track-started`-Video-Zweig, direkt nachdem `avatarPH`
  versteckt wird (`endAvatarBtn.style.display = "block"`).
- **Ausblenden:** im `left-meeting`-Handler, im `catch`-Fehlerzweig von
  `_startAvatarTavus`, und zu Beginn von `startAvatar()`.

### i18n
Neuer Eintrag `endBtn` im `I18N`-Dictionary:
- de: `"⏹ Beenden"`
- en: `"⏹ End"`

`applyLang()` setzt `document.getElementById("endAvatarBtn").textContent = t.endBtn;`.
Der Button-Text wird zusätzlich beim Einblenden gesetzt (falls Sprache vorher
gewechselt wurde, deckt `applyLang` das bereits ab).

## Backend
Keine Änderung — nutzt den vorhandenen `/tavus/end`-Pfad über den
`left-meeting`-Teardown.

## Verifikation
- Keine Testsuite fürs Frontend → Brace-Balance-Check des `<script>`-Blocks.
- Grep-Check: `endAvatar`, `endAvatarBtn` vorhanden; Ein-/Ausblenden an allen
  drei Stellen (track-started, left-meeting, catch + startAvatar).
- Manueller Test (sobald der Google-API-Key rotiert ist): Gespräch starten →
  Button erscheint → Klick → Avatar trennt sauber, UI zeigt „Erneut verbinden".

## Nicht im Scope
Weitere Steuerelemente (Mute, Kamera) — nur der Beenden-Button.
