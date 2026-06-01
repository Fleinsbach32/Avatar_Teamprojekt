# KIRA UI Redesign Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** CSS-Overhaul von `static/index.html` — KIT-Brand (helles Theme), Avatar zentriert, Chat als aufklappbare Seitenleiste, schwebender Chat-Button.

**Architecture:** Alle Änderungen ausschließlich in `static/index.html`. CSS-Variablen werden neu definiert, `<style>`-Block komplett ersetzt, HTML-Struktur neu organisiert (alle bestehenden Element-IDs bleiben erhalten), minimales JS für Sidebar-Toggle hinzugefügt. Kein Backend, keine Tests nötig — Verifikation im Browser.

**Tech Stack:** Vanilla HTML, Vanilla CSS (Custom Properties), bestehende JS-Logik unverändert.

---

## Datei-Überblick

- **Modify:** `static/index.html` — einzige Datei die sich ändert
  - Zeilen 10–427: `<style>`-Block komplett ersetzen
  - Zeilen 430–500: HTML-Body komplett ersetzen
  - Nach Zeile 502 (`<script>`): 30 Zeilen JS für Sidebar-Toggle einfügen

---

## Task 1: HTML-Struktur ersetzen

**Files:**
- Modify: `static/index.html:430-500`

- [ ] **Schritt 1: Alten HTML-Body löschen und neuen einsetzen**

Ersetze alles zwischen `</head>` und `<script>` (Zeilen 429–501) mit:

```html
<body>

<!-- KIT-Kopfleiste -->
<header id="kitHeader">
  <div class="header-left">
    <span class="kit-wordmark">KIT</span>
    <span class="header-divider">|</span>
    <span class="header-title">KIRA Studienberatung</span>
  </div>
  <div class="header-right">
    <div class="status-dot offline" id="statusDot"></div>
    <span class="status-text" id="statusText">verbinde...</span>
  </div>
</header>

<!-- Avatar-Zone (Hauptbereich) -->
<main class="avatar-zone">
  <div class="avatar-container">
    <div class="avatar-placeholder" id="avatarPlaceholder">
      <div class="avatar-ring">🎓</div>
      <span class="avatar-label" id="avatarLabel">KIRA ist bereit</span>
      <button class="start-btn" id="startBtn" onclick="startAvatar()">
        ▶ Gespräch starten
      </button>
    </div>
    <video
      id="avatarVideo"
      autoplay
      playsinline
      style="width:100%;height:100%;display:none;object-fit:cover;border-radius:16px;"
    ></video>
    <audio id="avatarAudio" autoplay></audio>
  </div>
  <p class="avatar-subtitle">KIRA — Studienberaterin KIT</p>
</main>

<!-- Chat-Seitenleiste -->
<aside id="chatPanel">
  <div class="chat-header">
    <span class="chat-title">KIRA</span>
    <button class="chat-close-btn" id="chatCloseBtn" aria-label="Schließen">✕</button>
  </div>

  <div id="messages">
    <div class="empty-state" id="emptyState">
      <div class="empty-icon">💬</div>
      <p>Willkommen bei KIRA.<br>Ich beantworte Ihre Fragen rund um das Studium am KIT.</p>
      <div class="chips-row" id="chipsRow">
        <div class="chip" onclick="quickSend('Wie melde ich mich für Prüfungen an?')">Prüfungsanmeldung</div>
        <div class="chip" onclick="quickSend('Wann ist die Bewerbungsfrist?')">Bewerbungsfristen</div>
        <div class="chip" onclick="quickSend('Wie beantrage ich Beurlaubung?')">Beurlaubung</div>
        <div class="chip" onclick="quickSend('Was sind die Sprechzeiten?')">Sprechzeiten</div>
      </div>
    </div>
  </div>

  <div class="input-area">
    <div class="input-row">
      <button class="tts-btn" id="ttsBtn" title="Spracheingabe (Chrome/Edge)">
        <svg viewBox="0 0 24 24" fill="currentColor" width="16" height="16">
          <path d="M12 1a3 3 0 0 0-3 3v8a3 3 0 0 0 6 0V4a3 3 0 0 0-3-3zM19 10v2a7 7 0 0 1-14 0v-2H3v2a9 9 0 0 0 8 8.94V22h-3v2h8v-2h-3v-1.06A9 9 0 0 0 21 12v-2h-2z"/>
        </svg>
      </button>
      <textarea id="userInput" placeholder="Ihre Frage an KIRA..." rows="1"></textarea>
      <button id="sendBtn" onclick="sendMessage()">
        <svg viewBox="0 0 24 24" width="18" height="18"><path d="M2.01 21L23 12 2.01 3 2 10l15 2-15 2z" fill="white"/></svg>
      </button>
    </div>
    <p class="hint">Enter zum Senden · Shift+Enter für neue Zeile</p>
  </div>
</aside>

<!-- Schwebender Chat-Button -->
<button class="chat-fab" id="chatToggleBtn" aria-label="Chat öffnen">
  <svg viewBox="0 0 24 24" width="24" height="24" fill="white">
    <path d="M20 2H4c-1.1 0-2 .9-2 2v18l4-4h14c1.1 0 2-.9 2-2V4c0-1.1-.9-2-2-2z"/>
  </svg>
  <span class="fab-badge" id="fabBadge"></span>
</button>

```

- [ ] **Schritt 2: Im Browser prüfen**

```powershell
# Server starten falls nicht läuft:
uvicorn main:app --reload
```

Öffne `http://localhost:8000`. Die Seite zeigt jetzt unstyled HTML — das ist normal. Weiter zu Task 2.

---

## Task 2: CSS komplett ersetzen

**Files:**
- Modify: `static/index.html:10-427`

- [ ] **Schritt 1: Alten `<style>`-Block löschen und neuen einsetzen**

Ersetze alles zwischen `<style>` und `</style>` (Zeilen 11–426) mit:

```css
/* ── Design Tokens ─────────────────────────────────── */
:root {
  --kit-green:      #009682;
  --kit-green-dark: #007a6a;
  --kit-green-soft: #e6f4f2;
  --bg:             #f4f5f7;
  --surface:        #ffffff;
  --text:           #1a1a1a;
  --text-muted:     #6b7280;
  --border:         #e5e7eb;
  --shadow:         0 4px 24px rgba(0,0,0,0.08);
  --radius:         12px;
  --font:           -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
}

/* ── Reset & Base ──────────────────────────────────── */
*, *::before, *::after { box-sizing: border-box; margin: 0; padding: 0; }

body {
  font-family: var(--font);
  background: var(--bg);
  color: var(--text);
  height: 100vh;
  overflow: hidden;
}

/* ── KIT-Kopfleiste ────────────────────────────────── */
#kitHeader {
  position: fixed;
  top: 0; left: 0; right: 0;
  height: 48px;
  background: var(--surface);
  border-bottom: 1px solid var(--border);
  box-shadow: 0 1px 4px rgba(0,0,0,0.06);
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 0 20px;
  z-index: 100;
}

.header-left {
  display: flex;
  align-items: center;
  gap: 10px;
}

.kit-wordmark {
  font-size: 14px;
  font-weight: 700;
  color: var(--kit-green);
  letter-spacing: 0.06em;
}

.header-divider {
  color: var(--border);
  font-size: 16px;
}

.header-title {
  font-size: 14px;
  color: var(--text);
  font-weight: 400;
}

.header-right {
  display: flex;
  align-items: center;
  gap: 7px;
  font-size: 12px;
  color: var(--text-muted);
}

/* ── Status-Indikator ──────────────────────────────── */
.status-dot {
  width: 8px; height: 8px;
  border-radius: 50%;
  background: var(--kit-green);
  flex-shrink: 0;
}

.status-dot.offline { background: #9ca3af; }
.status-dot.connecting { background: #f59e0b; }
.status-dot.speaking { animation: pulse 1.5s infinite; }

@keyframes pulse {
  0%, 100% { opacity: 1; }
  50%       { opacity: 0.3; }
}

/* ── Avatar-Zone ───────────────────────────────────── */
.avatar-zone {
  position: fixed;
  top: 48px; left: 0; right: 0; bottom: 0;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 16px;
  background: var(--bg);
}

.avatar-container {
  width: 100%;
  max-width: 480px;
  aspect-ratio: 16/9;
  background: linear-gradient(135deg, var(--kit-green) 0%, var(--kit-green-dark) 100%);
  border-radius: 16px;
  overflow: hidden;
  position: relative;
  box-shadow: var(--shadow);
}

.avatar-placeholder {
  width: 100%;
  height: 100%;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 14px;
  position: absolute;
  top: 0; left: 0;
}

.avatar-ring {
  width: 72px; height: 72px;
  border-radius: 50%;
  background: rgba(255,255,255,0.15);
  border: 2px solid rgba(255,255,255,0.4);
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 32px;
}

.avatar-label {
  font-size: 13px;
  color: rgba(255,255,255,0.8);
}

.spinner {
  width: 16px; height: 16px;
  border: 2px solid rgba(255,255,255,0.3);
  border-top-color: white;
  border-radius: 50%;
  animation: spin 0.8s linear infinite;
}

@keyframes spin { to { transform: rotate(360deg); } }

.avatar-subtitle {
  font-size: 13px;
  color: var(--text-muted);
  letter-spacing: 0.02em;
}

/* ── Start-Button ──────────────────────────────────── */
.start-btn {
  background: var(--surface);
  color: var(--kit-green);
  border: none;
  border-radius: var(--radius);
  padding: 10px 24px;
  font-size: 14px;
  font-family: var(--font);
  font-weight: 500;
  cursor: pointer;
  transition: transform 0.15s ease, box-shadow 0.15s ease;
  box-shadow: 0 2px 8px rgba(0,0,0,0.12);
}

.start-btn:hover {
  transform: translateY(-1px);
  box-shadow: 0 4px 12px rgba(0,0,0,0.16);
}

.start-btn:disabled {
  opacity: 0.6;
  cursor: not-allowed;
  transform: none;
}

/* ── Chat-Seitenleiste ─────────────────────────────── */
#chatPanel {
  position: fixed;
  top: 0; right: 0;
  width: 380px;
  height: 100vh;
  background: var(--surface);
  box-shadow: -4px 0 24px rgba(0,0,0,0.10);
  display: flex;
  flex-direction: column;
  z-index: 200;
  transform: translateX(100%);
  transition: transform 0.3s ease;
}

#chatPanel.open {
  transform: translateX(0);
}

.chat-header {
  height: 48px;
  border-bottom: 1px solid var(--border);
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 0 16px;
  flex-shrink: 0;
  background: var(--surface);
}

.chat-title {
  font-size: 15px;
  font-weight: 600;
  color: var(--kit-green);
}

.chat-close-btn {
  background: none;
  border: none;
  font-size: 18px;
  color: var(--text-muted);
  cursor: pointer;
  padding: 4px 8px;
  border-radius: 6px;
  transition: background 0.15s;
  line-height: 1;
}

.chat-close-btn:hover { background: var(--bg); }

/* ── Nachrichten ───────────────────────────────────── */
#messages {
  flex: 1;
  overflow-y: auto;
  padding: 16px;
  display: flex;
  flex-direction: column;
  gap: 14px;
  scroll-behavior: smooth;
}

#messages::-webkit-scrollbar { width: 4px; }
#messages::-webkit-scrollbar-track { background: transparent; }
#messages::-webkit-scrollbar-thumb { background: var(--border); border-radius: 2px; }

.empty-state {
  flex: 1;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 12px;
  color: var(--text-muted);
  text-align: center;
  padding: 24px 16px;
}

.empty-icon { font-size: 36px; opacity: 0.4; }

.empty-state p {
  font-size: 13px;
  line-height: 1.7;
  max-width: 260px;
  color: var(--text-muted);
}

/* ── Schnellfragen-Chips ───────────────────────────── */
.chips-row {
  display: flex;
  flex-wrap: wrap;
  gap: 7px;
  justify-content: center;
  margin-top: 8px;
}

.chip {
  padding: 6px 14px;
  background: var(--kit-green-soft);
  color: var(--kit-green);
  border-radius: 20px;
  font-size: 12px;
  font-weight: 500;
  cursor: pointer;
  transition: background 0.15s, transform 0.1s;
  border: none;
}

.chip:hover {
  background: #c8e8e4;
  transform: translateY(-1px);
}

/* ── Nachrichten-Bubbles ───────────────────────────── */
.msg {
  display: flex;
  gap: 8px;
  animation: fadeInUp 0.2s ease;
}

@keyframes fadeInUp {
  from { opacity: 0; transform: translateY(8px); }
  to   { opacity: 1; transform: translateY(0); }
}

.msg.user { flex-direction: row-reverse; }

.msg-icon {
  width: 28px; height: 28px;
  border-radius: 50%;
  flex-shrink: 0;
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 12px;
  margin-top: 2px;
}

.msg.bot  .msg-icon { background: var(--kit-green-soft); border: 1px solid #c8e8e4; }
.msg.user .msg-icon { background: var(--bg); border: 1px solid var(--border); color: var(--text-muted); }

.bubble {
  max-width: 78%;
  padding: 10px 14px;
  border-radius: var(--radius);
  font-size: 14px;
  line-height: 1.65;
}

.msg.bot .bubble {
  background: var(--surface);
  border: 1px solid var(--border);
  border-bottom-left-radius: 4px;
  color: var(--text);
}

.msg.user .bubble {
  background: var(--kit-green);
  color: white;
  border-bottom-right-radius: 4px;
}

.role-label {
  font-size: 10px;
  font-weight: 600;
  margin-bottom: 4px;
  opacity: 0.55;
  letter-spacing: 0.08em;
  text-transform: uppercase;
}

.meta {
  font-size: 10px;
  color: var(--text-muted);
  margin-top: 5px;
  display: flex;
  gap: 8px;
}

.meta .wb  { color: var(--kit-green); }
.meta .llm { color: #f59e0b; }

/* Typing Indicator */
.typing-dots { display: flex; gap: 4px; align-items: center; padding: 4px 0; }
.typing-dots span {
  width: 6px; height: 6px;
  border-radius: 50%;
  background: var(--kit-green);
  animation: dot-bounce 1.2s infinite;
}
.typing-dots span:nth-child(2) { animation-delay: 0.2s; }
.typing-dots span:nth-child(3) { animation-delay: 0.4s; }

@keyframes dot-bounce {
  0%, 80%, 100% { transform: scale(0.6); opacity: 0.4; }
  40%            { transform: scale(1);   opacity: 1; }
}

/* Error */
.error-bubble {
  background: #fef2f2;
  border: 1px solid #fecaca;
  color: #dc2626;
  border-radius: var(--radius);
  padding: 10px 14px;
  font-size: 13px;
}

/* ── Input-Bereich ─────────────────────────────────── */
.input-area {
  padding: 12px 16px 16px;
  border-top: 1px solid var(--border);
  background: var(--surface);
  flex-shrink: 0;
}

.input-row { display: flex; gap: 8px; align-items: flex-end; }

.tts-btn {
  width: 40px; height: 40px;
  border-radius: 50%;
  border: 1px solid var(--border);
  background: var(--surface);
  cursor: pointer;
  display: flex;
  align-items: center;
  justify-content: center;
  flex-shrink: 0;
  color: var(--text-muted);
  transition: all 0.2s;
}

.tts-btn.active {
  background: #fef2f2;
  border-color: #ef4444;
  color: #ef4444;
}

#userInput {
  flex: 1;
  background: var(--bg);
  border: 1px solid var(--border);
  border-radius: var(--radius);
  padding: 11px 14px;
  font-size: 14px;
  font-family: var(--font);
  color: var(--text);
  resize: none;
  outline: none;
  min-height: 44px;
  max-height: 120px;
  line-height: 1.5;
  transition: border-color 0.2s;
}

#userInput:focus { border-color: var(--kit-green); }
#userInput::placeholder { color: var(--text-muted); }

#sendBtn {
  width: 44px; height: 44px;
  border-radius: var(--radius);
  background: var(--kit-green);
  border: none;
  cursor: pointer;
  display: flex;
  align-items: center;
  justify-content: center;
  flex-shrink: 0;
  transition: background 0.2s, transform 0.1s;
}

#sendBtn:hover    { background: var(--kit-green-dark); }
#sendBtn:active   { transform: scale(0.95); }
#sendBtn:disabled { opacity: 0.35; cursor: not-allowed; }

.hint { margin-top: 6px; font-size: 11px; color: var(--text-muted); text-align: center; }

/* ── Schwebender Chat-Button ───────────────────────── */
.chat-fab {
  position: fixed;
  bottom: 24px; right: 24px;
  width: 56px; height: 56px;
  border-radius: 50%;
  background: var(--kit-green);
  border: none;
  cursor: pointer;
  display: flex;
  align-items: center;
  justify-content: center;
  box-shadow: 0 4px 16px rgba(0,150,130,0.4);
  z-index: 150;
  transition: background 0.2s, transform 0.15s;
}

.chat-fab:hover {
  background: var(--kit-green-dark);
  transform: scale(1.05);
}

.fab-badge {
  position: absolute;
  top: 6px; right: 6px;
  width: 10px; height: 10px;
  border-radius: 50%;
  background: #ef4444;
  border: 2px solid white;
  display: none;
}

.chat-fab.unread .fab-badge { display: block; }

/* ── Mobile ────────────────────────────────────────── */
@media (max-width: 768px) {
  #chatPanel { width: 100vw; }
  .avatar-container { max-width: calc(100vw - 32px); }
}
```

- [ ] **Schritt 2: Im Browser prüfen**

Lade `http://localhost:8000` neu. Du solltest sehen:
- Weiße Kopfleiste mit `KIT | KIRA Studienberatung`
- Avatar (grüner Gradient) zentriert auf der Seite
- Grüner schwebender Button unten rechts

---

## Task 3: JS-Toggle für Sidebar

**Files:**
- Modify: `static/index.html` — direkt nach `<script>` (Zeile ~502), vor `const API_URL`

- [ ] **Schritt 1: Sidebar-Toggle-Code einfügen**

Füge folgende Zeilen **ganz am Anfang des `<script>`-Blocks** ein (vor `const API_URL`):

```javascript
// ── Sidebar-Toggle ────────────────────────────────────
const chatPanel      = document.getElementById("chatPanel");
const chatToggleBtn  = document.getElementById("chatToggleBtn");
const chatCloseBtn   = document.getElementById("chatCloseBtn");
const fabBadge       = document.getElementById("fabBadge");
const chipsRow       = document.getElementById("chipsRow");

function openChat() {
  chatPanel.classList.add("open");
  chatToggleBtn.classList.remove("unread");
}

function closeChat() {
  chatPanel.classList.remove("open");
}

chatToggleBtn.addEventListener("click", openChat);
chatCloseBtn.addEventListener("click", closeChat);

function markUnread() {
  if (!chatPanel.classList.contains("open")) {
    chatToggleBtn.classList.add("unread");
  }
}
```

- [ ] **Schritt 2: `markUnread()` in `addMessage()` aufrufen**

Suche die Funktion `addMessage` im `<script>`-Block. Füge am Ende der Funktion (vor der letzten `}`) folgende Zeile ein:

```javascript
if (role === "bot") markUnread();
```

- [ ] **Schritt 3: Chips nach erster Nachricht ausblenden**

Suche in `sendMessage()` die Zeile:
```javascript
const emptyState = document.getElementById("emptyState");
if (emptyState) emptyState.remove();
```

Füge darunter ein:
```javascript
if (chipsRow) chipsRow.style.display = "none";
```

- [ ] **Schritt 4: Im Browser testen**

1. Lade `http://localhost:8000` neu
2. Klicke den grünen Floating-Button → Sidebar fährt von rechts herein ✓
3. Klicke `✕` → Sidebar schließt sich ✓
4. Schreibe eine Nachricht → Chips verschwinden ✓
5. Schließe Sidebar, warte auf Bot-Antwort → Roter Badge erscheint auf FAB ✓

---

## Task 4: Commit

**Files:**
- Modify: `static/index.html`

- [ ] **Schritt 1: Alle Tests laufen lassen**

```powershell
cd "c:\Users\lucat\OneDrive\Uni\teamprojekt\Avatar_Teamprojekt-main\Avatar_Teamprojekt-main"
python -m pytest tests/ -v
```

Erwartetes Ergebnis: `16 passed`

- [ ] **Schritt 2: Commit**

```powershell
git add static/index.html
git commit -m "feat: KIRA UI redesign — KIT brand, avatar-centered, chat sidebar"
```

- [ ] **Schritt 3: Push**

```powershell
git push
```
