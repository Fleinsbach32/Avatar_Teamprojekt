# KIRA UI Redesign Design Spec

**Goal:** Komplettes CSS-Overhaul der KIRA-Oberfläche — KIT-Brand, modernes Look & Feel, Avatar zentriert, Chat als aufklappbare Seitenleiste.

**Architecture:** CSS-only Overhaul. HTML-Struktur bleibt weitgehend erhalten (Element-IDs und JS-Logik unverändert), alle Styles werden neu geschrieben. Neue KIT-Design-Tokens als CSS-Variablen. Keine neuen Abhängigkeiten.

**Tech Stack:** Vanilla CSS (Custom Properties), keine externe CSS-Bibliothek, Systemschriften.

---

## 1. Layout & Struktur

Die Seite besteht aus drei Schichten:

**Seitenhintergrund:** `#f4f5f7` — helles Neutralgrau, kein reines Weiß.

**Hauptbereich (Avatar-Zone):** Nimmt die gesamte Viewport-Höhe ein. Vertikale Zentrierung des Avatars. Darüber eine schmale KIT-Kopfleiste (48px). Unter dem Avatar der "Gespräch starten"-Button.

**Chat-Seitenleiste:** 380px breites Overlay, fährt von rechts herein. Liegt über dem Avatar-Bereich ohne ihn zu verschieben (`position: fixed`, `right: 0`). Weißer Hintergrund, Schatten nach links. Schließen-Button oben rechts. Auf Mobile (< 768px) wird die Leiste zur Vollbild-Ansicht.

**Schwebender Chat-Button:** Fixer Button unten rechts (56px rund), öffnet/schließt die Seitenleiste. Zeigt roten Badge bei neuer ungelesener Antwort.

---

## 2. Farben & Typografie

### CSS Design-Tokens (`:root`)

```css
--kit-green:      #009682;
--kit-green-dark: #007a6a;
--kit-green-soft: #e6f4f2;
--bg:             #f4f5f7;
--surface:        #ffffff;
--text:           #1a1a1a;
--text-muted:     #6b7280;
--border:         #e5e7eb;
--shadow:         0 4px 24px rgba(0, 0, 0, 0.08);
--radius:         12px;
```

### Typografie

- Schrift: `-apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif`
- Kopfleiste: `13px`, Uppercase, `letter-spacing: 0.08em`
- Chat-Nachrichten: `15px`, `line-height: 1.5`
- Avatar-Label: `18px`, Medium-Weight

### Nachrichten-Bubbles

- **Nutzer:** Hintergrund `#009682`, Text weiß, abgerundete Ecken rechts oben, rechts unten, links oben
- **KIRA:** Hintergrund weiß, Border `1px solid #e5e7eb`, Text `#1a1a1a`, abgerundete Ecken links unten, rechts oben, rechts unten

### Status-Indikator (Punkt + Text, oben rechts in Kopfleiste)

- **Offline:** grau (`#9ca3af`)
- **Verbindet:** gelb (`#f59e0b`), kein Puls
- **Bereit / Verbunden:** grün (`#009682`), kein Puls
- **Spricht:** grün (`#009682`), Puls-Animation (`@keyframes pulse`)

---

## 3. Komponenten

### KIT-Kopfleiste

```
[KIT | KIRA Studienberatung]          [● bereit]
```

- Höhe: 48px
- Hintergrund: `#ffffff`
- Border-Bottom: `1px solid #e5e7eb`
- Box-Shadow: `0 1px 4px rgba(0,0,0,0.06)`
- Links: `KIT` in `font-weight: 700`, `color: #009682` + `|` + `KIRA Studienberatung` in `color: #1a1a1a`
- Rechts: Status-Punkt (8px) + Status-Text in `#6b7280`

### Avatar-Container

- Video/Placeholder zentriert, max-width `480px`, `border-radius: 16px`
- Schatten: `var(--shadow)`
- Darunter Label: `KIRA — Studienberaterin KIT` in `--text-muted`
- Placeholder-Hintergrund: Linearer Gradient `#009682 → #007a6a` mit KIT-Initialen zentriert

### "Gespräch starten"-Button

- Padding: `14px 32px`, `border-radius: var(--radius)`
- Hintergrund: `#009682`, Text weiß, `font-size: 16px`
- Hover: `#007a6a`, leichter Schatten
- Nach Verbindung: Text `● Verbunden`, Hintergrund `#e6f4f2`, Text `#009682`, nicht klickbar

### Chat-Seitenleiste

- Breite: `380px` (Mobile: 100vw)
- `position: fixed; top: 0; right: 0; height: 100vh`
- Transform: `translateX(100%)` wenn geschlossen → `translateX(0)` wenn offen
- Transition: `transform 0.3s ease`
- Header: `KIRA` links, Schließen-Button (`×`) rechts
- Nachrichten-Bereich: scrollbar, Padding `16px`
- Input-Bereich: fixiert am unteren Rand der Leiste, weiß, Border-Top

### Chat-Eingabe

- Textfeld + Senden-Button in einer Zeile
- Mikrofon-Icon links im Textfeld: grau wenn inaktiv, rot (`#ef4444`) wenn aktiv
- Senden-Button: KIT-Grün, Arrow-Icon

### Schnellfragen-Chips (nur beim ersten Öffnen)

Erscheinen als klickbare Zeile unter dem leeren Nachrichtenbereich:

- "Prüfungsanmeldung"
- "Stundenplan"  
- "Beurlaubung"
- "Sprechzeiten"

Stil: `background: #e6f4f2; color: #009682; border-radius: 20px; padding: 6px 14px; font-size: 13px`

### Schwebender Chat-Button

- `position: fixed; bottom: 24px; right: 24px`
- 56px runder Button, `background: #009682`
- Icon: Sprechblasen-SVG, weiß
- Badge: Roter Kreis (8px) oben rechts wenn neue Antwort und Leiste geschlossen

---

## 4. Animationen

- Seitenleiste: `transform 0.3s ease` beim Öffnen/Schließen
- Status-Puls: `@keyframes pulse { 0%,100%{opacity:1} 50%{opacity:0.4} }`, 1.5s infinite, nur wenn Avatar spricht
- Button-Hover: `transform: translateY(-1px)`, `0.15s ease`
- Nachrichten-Eintritt: `fadeInUp` — `opacity 0→1`, `translateY(8px→0)`, `0.2s ease`

---

## 5. Dateien & JS-Änderungen

- **Modifiziert:** `static/index.html` — alle `<style>`-Blöcke ersetzen, minimale HTML-Anpassungen (Klassen, neue Elemente für Chip-Leiste und schwebenden Button)
- **Keine neuen Dateien** — CSS bleibt im `<style>`-Tag von `index.html`

### Minimale JS-Ergänzungen (neu, keine bestehende Logik geändert)

```javascript
// Seitenleiste öffnen/schließen
const chatPanel = document.getElementById("chatPanel");
const chatToggleBtn = document.getElementById("chatToggleBtn");
const chatCloseBtn = document.getElementById("chatCloseBtn");
let hasUnread = false;

function openChat() {
  chatPanel.classList.add("open");
  chatToggleBtn.classList.remove("unread");
  hasUnread = false;
}
function closeChat() {
  chatPanel.classList.remove("open");
}
chatToggleBtn.addEventListener("click", openChat);
chatCloseBtn.addEventListener("click", closeChat);

// Badge bei neuer Antwort wenn Leiste geschlossen
// Wird in addMessage() aufgerufen: markUnread()
function markUnread() {
  if (!chatPanel.classList.contains("open")) {
    chatToggleBtn.classList.add("unread");
  }
}
```

Alle bestehenden Element-IDs (`avatarVideo`, `messages`, `userInput`, `sendBtn`, `ttsBtn`, `startBtn`, `statusDot`, `statusText`) bleiben erhalten. `addMessage()` erhält einen `markUnread()`-Aufruf am Ende.

---

## 6. Was sich nicht ändert

- Alle Element-IDs (`avatarVideo`, `avatarAudio`, `messages`, `userInput`, `sendBtn`, `ttsBtn`, `startBtn`, `avatarPlaceholder`, `statusDot`, `statusText`)
- Gesamte JavaScript-Logik
- Backend (`main.py`)
- Tests
