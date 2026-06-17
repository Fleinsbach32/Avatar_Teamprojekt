# Teil-Projekt 5 — Avatar-Toolbar: Design

**Datum:** 2026-06-17
**Status:** Genehmigt
**Branch:** feature/tavus

## Ziel

Eine schwebende Toolbar im Avatar-Video, die während eines laufenden Gesprächs
die wichtigsten Steuerungen bündelt: Selbst-Mute, Avatar-Mute, Lautstärke,
Vollbild, Chat-Toggle und Beenden. Ersetzt den bisherigen einzelnen
Beenden-Overlay-Button oben links.

## Scope

Nur `static/index.html` (HTML + CSS + Vanilla-JS). Kein Backend-Change.

## Position & Sichtbarkeit

Schwebende Pill-Leiste unten mittig im `.avatar-container`
(`position:absolute; bottom:16px; left:50%; transform:translateX(-50%)`),
`z-index` über dem Video. Initial `display:none`; eingeblendet, sobald das
Avatar-Video erscheint (im `track-started`-Video-Zweig, wo bisher `endAvatarBtn`
gezeigt wurde); ausgeblendet im `left-meeting`-Handler, im `catch`-Fehlerzweig
von `_startAvatarTavus` und zu Beginn von `startAvatar()`.

Reihenfolge der Elemente:
`[Mikrofon] [Avatar-Lautsprecher] [Lautstärke-Slider] [Vollbild] [Chat] [Beenden]`

## Elemente & Verhalten

| Element | ID | Aktion | Zustand/Feedback |
|---|---|---|---|
| Selbst-Mute | `micBtn` | `tavusCall.setLocalAudio(!muted)` | `micMuted`-Flag; Icon Mikro ↔ Mikro-durchgestrichen; aktiv (stumm) = rot |
| Avatar-Mute | `speakerBtn` | `avatarAudio.muted = !avatarAudio.muted` | Icon Lautsprecher ↔ durchgestrichen; stumm = rot |
| Lautstärke | `volumeSlider` | `avatarAudio.volume = wert/100` (0–1) | Wert 0 ⇒ `avatarAudio.muted=true`; Wert >0 ⇒ `muted=false` und Speaker-Icon aktualisieren |
| Vollbild | `fullscreenBtn` | Toggle Fullscreen-API auf `.avatar-container` (`requestFullscreen()`/`document.exitFullscreen()`) | Icon Vollbild ↔ Vollbild-verlassen via `fullscreenchange`-Event |
| Chat | `toolbarChatBtn` | `chatPanel.classList.contains("open") ? closeChat() : openChat()` | — |
| Beenden | `toolbarEndBtn` | `endAvatar()` (bestehend) | rot eingefärbt |

### Detailregeln
- **Mute-Kopplung Lautstärke ↔ Avatar-Mute:** Beide steuern dasselbe
  `avatarAudio`. Der Speaker-Button setzt `avatarAudio.muted`; der Slider setzt
  `avatarAudio.volume`. Wird der Slider auf 0 gezogen, gilt der Avatar als stumm
  (Icon rot); wird er auf >0 gezogen während stumm, wird `muted=false` gesetzt.
  Eine Hilfsfunktion `syncSpeakerIcon()` hält Icon und Zustand konsistent.
- **Selbst-Mute** wirkt auf den Daily-Audiotrack des Nutzers; bei `setLocalAudio`
  nur aufrufen, wenn `tavusCall` existiert (sonst no-op).
- **Vollbild:** Ziel ist `.avatar-container` (zeigt Video formatfüllend). Der
  `fullscreenchange`-Listener aktualisiert das Icon; Fehler (z. B. Berechtigung)
  werden mit `.catch(()=>{})` ignoriert.

## Icons

Inline-SVG (kein Emoji) für saubere Aktiv-Zustände und konsistente Darstellung
über Browser/OS (gleiche Begründung wie bei den Sprach-Flaggen, die als Emoji
unter Windows nicht rendern). Pro Button ein kleines 20×20-SVG; gemutete Zustände
erhalten die Klasse `.active` (rote Färbung). Speaker-/Mikro-Button tauschen
zwischen „an"- und „durchgestrichen"-SVG.

## i18n

Tooltips über `title`-Attribute, lokalisiert im bestehenden `I18N`-Dictionary
(DE/EN) und in `applyLang()` gesetzt:
- de: `tipMic:"Mikrofon stummschalten"`, `tipSpeaker:"Avatar stummschalten"`,
  `tipVolume:"Lautstärke"`, `tipFullscreen:"Vollbild"`, `tipChat:"Chat anzeigen/ausblenden"`,
  `tipEnd:"Gespräch beenden"`
- en: entsprechende Übersetzungen.

## CSS

```
.avatar-toolbar {
  position:absolute; bottom:16px; left:50%; transform:translateX(-50%);
  z-index:6; display:flex; align-items:center; gap:6px;
  background:rgba(20,20,20,0.72); backdrop-filter:blur(6px);
  border-radius:24px; padding:6px 10px; box-shadow:0 4px 16px rgba(0,0,0,0.3);
}
.tb-btn { width:38px; height:38px; border-radius:50%; border:none;
  background:rgba(255,255,255,0.12); color:#fff; cursor:pointer;
  display:flex; align-items:center; justify-content:center; transition:background .15s; }
.tb-btn:hover { background:rgba(255,255,255,0.22); }
.tb-btn.active { background:#ef4444; }           /* stumm */
.tb-btn.end { background:#ef4444; }
.tb-btn.end:hover { background:#dc2626; }
.tb-volume { width:80px; accent-color:var(--kit-green); cursor:pointer; }
```

## Änderungen im Detail

1. HTML: `#avatarToolbar` in `.avatar-container` einfügen; bisherigen
   `#endAvatarBtn` (Overlay oben links) entfernen.
2. CSS: `.avatar-toolbar`, `.tb-btn`, `.tb-volume` ergänzen; `.end-avatar-btn`
   entfernen (nicht mehr genutzt).
3. JS:
   - Zustand `micMuted=false`; Funktionen `toggleMic()`, `toggleAvatarMute()`,
     `setVolume(v)`, `toggleFullscreen()`, `toggleChatFromToolbar()`,
     `syncSpeakerIcon()`.
   - `endAvatar()` bleibt; `endAvatarBtn`-Referenzen → Toolbar ein-/ausblenden
     (`document.getElementById("avatarToolbar").style.display = ...`).
   - `applyLang()` setzt die `title`-Tooltips.
   - Beim Start zurücksetzen: `micMuted=false`, `avatarAudio.muted=false`,
     Slider auf 100.

## Verifikation

- Frontend hat keine Testsuite → statische Checks:
  - Klammer-/Klammerpaar-Balance des `<script>`-Blocks.
  - Grep: `avatarToolbar` wird an genau drei Stellen ein-/ausgeblendet
    (track-started=block, left-meeting/​catch/​startAvatar=none); `endAvatarBtn`
    kommt nicht mehr vor; alle Handler (`toggleMic`, `toggleAvatarMute`,
    `setVolume`, `toggleFullscreen`) sind referenziert und definiert.
- Manuell im laufenden Avatar (sobald gestartet): jeder Button + Slider + Vollbild.

## Nicht im Scope

- „Neu verbinden" (bewusst weggelassen).
- Auto-Hide der Toolbar bei Inaktivität.
- Nutzer-Kamera-Steuerung (Nutzervideo wird nicht angezeigt).

## Risiken

- `setLocalAudio` / Fullscreen-API sind browserabhängig; Aufrufe werden defensiv
  (Existenzprüfung, `.catch`) gekapselt, damit ein nicht unterstützter Browser den
  Rest der Toolbar nicht bricht.
