# TP5 Avatar-Toolbar Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the single "Beenden" overlay button with a floating pill toolbar containing mic mute, speaker mute, volume slider, fullscreen, chat toggle, and end controls.

**Architecture:** All changes are confined to `static/index.html` (HTML + CSS + vanilla JS). No backend changes. The toolbar appears on `track-started` (video), hides on `left-meeting`, `catch`, and start of `startAvatar()`. Inline SVG icons, i18n tooltips via the existing `I18N` / `applyLang()` pattern.

**Tech Stack:** Vanilla JS, Daily.js (`tavusCall.setLocalAudio()`), Fullscreen API, HTML5 audio element (`avatarAudio`).

---

### Task 1: Replace CSS

**Files:**
- Modify: `static/index.html` lines 171–181

- [ ] **Step 1: Remove `.end-avatar-btn` CSS block and add toolbar CSS**

Replace:
```css
/* ── Avatar-Beenden-Button (Overlay) ───────────────── */
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

With:
```css
/* ── Avatar-Toolbar ────────────────────────────────── */
.avatar-toolbar {
  position:absolute; bottom:16px; left:50%; transform:translateX(-50%);
  z-index:6; display:flex; align-items:center; gap:6px;
  background:rgba(20,20,20,0.72); backdrop-filter:blur(6px);
  border-radius:24px; padding:6px 10px; box-shadow:0 4px 16px rgba(0,0,0,0.3);
}
.tb-btn {
  width:38px; height:38px; border-radius:50%; border:none;
  background:rgba(255,255,255,0.12); color:#fff; cursor:pointer;
  display:flex; align-items:center; justify-content:center; transition:background .15s;
}
.tb-btn:hover { background:rgba(255,255,255,0.22); }
.tb-btn.active { background:#ef4444; }
.tb-btn.end { background:#ef4444; }
.tb-btn.end:hover { background:#dc2626; }
.tb-volume { width:80px; accent-color:var(--kit-green); cursor:pointer; }
```

---

### Task 2: Replace HTML

**Files:**
- Modify: `static/index.html` line 589

- [ ] **Step 1: Replace `#endAvatarBtn` with `#avatarToolbar`**

Replace:
```html
    <button id="endAvatarBtn" class="end-avatar-btn" style="display:none;" onclick="endAvatar()">⏹ Beenden</button>
```

With:
```html
    <div id="avatarToolbar" class="avatar-toolbar" style="display:none;">
      <button id="micBtn" class="tb-btn" onclick="toggleMic()" title=""></button>
      <button id="speakerBtn" class="tb-btn" onclick="toggleAvatarMute()" title=""></button>
      <input id="volumeSlider" type="range" class="tb-volume" min="0" max="100" value="100" oninput="setVolume(this.value)">
      <button id="fullscreenBtn" class="tb-btn" onclick="toggleFullscreen()" title=""></button>
      <button id="toolbarChatBtn" class="tb-btn" onclick="toggleChatFromToolbar()" title=""></button>
      <button id="toolbarEndBtn" class="tb-btn end" onclick="endAvatar()" title=""></button>
    </div>
```

---

### Task 3: Add i18n keys

**Files:**
- Modify: `static/index.html` — I18N dict (de and en)

- [ ] **Step 1: Add tip* keys to both `de` and `en` objects**

In `de`: after `studiengangLabel: "Studiengang",` add:
```js
      tipMic: "Mikrofon stummschalten", tipSpeaker: "Avatar stummschalten",
      tipVolume: "Lautstärke", tipFullscreen: "Vollbild",
      tipChat: "Chat anzeigen/ausblenden", tipEnd: "Gespräch beenden",
```

In `en`: after `studiengangLabel: "Programme",` add:
```js
      tipMic: "Mute microphone", tipSpeaker: "Mute avatar",
      tipVolume: "Volume", tipFullscreen: "Fullscreen",
      tipChat: "Toggle chat", tipEnd: "End conversation",
```

---

### Task 4: Update applyLang()

**Files:**
- Modify: `static/index.html` — `applyLang()` function

- [ ] **Step 1: Remove `endAvatarBtn` reference, add toolbar tooltip updates**

Remove:
```js
    const endEl = document.getElementById("endAvatarBtn");
    if (endEl) endEl.textContent = t.endBtn;
```

Replace with:
```js
    const micBtn = document.getElementById("micBtn");
    if (micBtn) micBtn.title = t.tipMic;
    const speakerBtn = document.getElementById("speakerBtn");
    if (speakerBtn) speakerBtn.title = t.tipSpeaker;
    const volSlider = document.getElementById("volumeSlider");
    if (volSlider) volSlider.title = t.tipVolume;
    const fsBtn = document.getElementById("fullscreenBtn");
    if (fsBtn) fsBtn.title = t.tipFullscreen;
    const chatTbBtn = document.getElementById("toolbarChatBtn");
    if (chatTbBtn) chatTbBtn.title = t.tipChat;
    const endTbBtn = document.getElementById("toolbarEndBtn");
    if (endTbBtn) endTbBtn.title = t.tipEnd;
```

---

### Task 5: Add state + SVG constants

**Files:**
- Modify: `static/index.html` — after `const pendingEchoReplies = new Set();`

- [ ] **Step 1: Add micMuted and SVG icon constants**

After `const pendingEchoReplies = new Set();` add:
```js
  let micMuted = false;

  const SVG_MIC = '<svg viewBox="0 0 24 24" fill="currentColor" width="20" height="20"><path d="M12 1a3 3 0 0 0-3 3v8a3 3 0 0 0 6 0V4a3 3 0 0 0-3-3zM19 10v2a7 7 0 0 1-14 0v-2H3v2a9 9 0 0 0 8 8.94V22h-3v2h8v-2h-3v-1.06A9 9 0 0 0 21 12v-2h-2z"/></svg>';
  const SVG_MIC_OFF = '<svg viewBox="0 0 24 24" fill="currentColor" width="20" height="20"><path d="M19 11h-1.7c0 .74-.16 1.43-.43 2.05l1.23 1.23c.56-.98.9-2.09.9-3.28zm-4.02.17c0-.06.02-.11.02-.17V4c0-1.66-1.34-3-3-3S9 2.34 9 4v.18l5.98 5.99zM4.27 3L3 4.27l6.01 6.01V11c0 1.66 1.33 3 2.99 3 .22 0 .44-.03.65-.08l1.66 1.66c-.71.33-1.5.52-2.31.52-2.76 0-5.3-2.1-5.3-5.1H5c0 3.41 2.72 6.23 6 6.72V21h-2v2h6v-2h-2v-2.28c.91-.13 1.77-.45 2.54-.9L19.73 21 21 19.73 4.27 3z"/></svg>';
  const SVG_SPEAKER = '<svg viewBox="0 0 24 24" fill="currentColor" width="20" height="20"><path d="M3 9v6h4l5 5V4L7 9H3zm13.5 3c0-1.77-1.02-3.29-2.5-4.03v8.05c1.48-.73 2.5-2.25 2.5-4.02zM14 3.23v2.06c2.89.86 5 3.54 5 6.71s-2.11 5.85-5 6.71v2.06c4.01-.91 7-4.49 7-8.77s-2.99-7.86-7-8.77z"/></svg>';
  const SVG_SPEAKER_OFF = '<svg viewBox="0 0 24 24" fill="currentColor" width="20" height="20"><path d="M16.5 12c0-1.77-1.02-3.29-2.5-4.03v2.21l2.45 2.45c.03-.2.05-.41.05-.63zm2.5 0c0 .94-.2 1.82-.54 2.64l1.51 1.51C20.63 14.91 21 13.5 21 12c0-4.28-2.99-7.86-7-8.77v2.06c2.89.86 5 3.54 5 6.71zM4.27 3L3 4.27 7.73 9H3v6h4l5 5v-6.73l4.25 4.25c-.67.52-1.42.93-2.25 1.18v2.06c1.38-.31 2.63-.95 3.69-1.81L19.73 21 21 19.73l-9-9L4.27 3zM12 4L9.91 6.09 12 8.18V4z"/></svg>';
  const SVG_FULLSCREEN = '<svg viewBox="0 0 24 24" fill="currentColor" width="20" height="20"><path d="M7 14H5v5h5v-2H7v-3zm-2-4h2V7h3V5H5v5zm12 7h-3v2h5v-5h-2v3zM14 5v2h3v3h2V5h-5z"/></svg>';
  const SVG_FULLSCREEN_EXIT = '<svg viewBox="0 0 24 24" fill="currentColor" width="20" height="20"><path d="M5 16h3v3h2v-5H5v2zm3-8H5v2h5V5H8v3zm6 11h2v-3h3v-2h-5v5zm2-11V5h-2v5h5V8h-3z"/></svg>';
  const SVG_CHAT = '<svg viewBox="0 0 24 24" fill="currentColor" width="20" height="20"><path d="M20 2H4c-1.1 0-2 .9-2 2v18l4-4h14c1.1 0 2-.9 2-2V4c0-1.1-.9-2-2-2z"/></svg>';
  const SVG_X = '<svg viewBox="0 0 24 24" fill="currentColor" width="20" height="20"><path d="M19 6.41L17.59 5 12 10.59 6.41 5 5 6.41 10.59 12 5 17.59 6.41 19 12 13.41 17.59 19 19 17.59 13.41 12z"/></svg>';
```

---

### Task 6: Replace all endAvatarBtn show/hide (4 locations)

**Files:**
- Modify: `static/index.html` — `startAvatar()`, `track-started`, `left-meeting`, catch

- [ ] **Step 1: startAvatar() — hide toolbar**

Replace `document.getElementById("endAvatarBtn").style.display = "none";` (in startAvatar) with:
```js
    document.getElementById("avatarToolbar").style.display = "none";
```

- [ ] **Step 2: track-started — show toolbar + reset state**

Replace `document.getElementById("endAvatarBtn").style.display = "block";` with:
```js
          const toolbar = document.getElementById("avatarToolbar");
          toolbar.style.display = "flex";
          micMuted = false;
          avatarAudio.muted = false;
          document.getElementById("volumeSlider").value = 100;
          document.getElementById("micBtn").innerHTML = SVG_MIC;
          document.getElementById("micBtn").classList.remove("active");
          document.getElementById("fullscreenBtn").innerHTML = SVG_FULLSCREEN;
          document.getElementById("toolbarChatBtn").innerHTML = SVG_CHAT;
          document.getElementById("toolbarEndBtn").innerHTML = SVG_X;
          syncSpeakerIcon();
```

- [ ] **Step 3: left-meeting — hide toolbar**

Replace `document.getElementById("endAvatarBtn").style.display = "none";` (in left-meeting) with:
```js
        document.getElementById("avatarToolbar").style.display = "none";
```

- [ ] **Step 4: catch block — hide toolbar**

Replace `document.getElementById("endAvatarBtn").style.display = "none";` (in catch) with:
```js
      document.getElementById("avatarToolbar").style.display = "none";
```

---

### Task 7: Add toolbar functions + fullscreenchange listener

**Files:**
- Modify: `static/index.html` — before `// ── Initiale Sprache anwenden`

- [ ] **Step 1: Add all toolbar JS functions**

Before `// ── Initiale Sprache anwenden ─────────────────────────` add:
```js
  // ── Avatar-Toolbar ────────────────────────────────────
  function syncSpeakerIcon() {
    const btn = document.getElementById("speakerBtn");
    if (!btn) return;
    if (avatarAudio.muted || avatarAudio.volume === 0) {
      btn.innerHTML = SVG_SPEAKER_OFF;
      btn.classList.add("active");
    } else {
      btn.innerHTML = SVG_SPEAKER;
      btn.classList.remove("active");
    }
  }

  function toggleMic() {
    micMuted = !micMuted;
    if (tavusCall) { try { tavusCall.setLocalAudio(!micMuted); } catch (_) {} }
    const btn = document.getElementById("micBtn");
    if (!btn) return;
    if (micMuted) {
      btn.innerHTML = SVG_MIC_OFF;
      btn.classList.add("active");
    } else {
      btn.innerHTML = SVG_MIC;
      btn.classList.remove("active");
    }
  }

  function toggleAvatarMute() {
    avatarAudio.muted = !avatarAudio.muted;
    syncSpeakerIcon();
  }

  function setVolume(v) {
    avatarAudio.volume = v / 100;
    if (v == 0) {
      avatarAudio.muted = true;
    } else if (avatarAudio.muted) {
      avatarAudio.muted = false;
    }
    syncSpeakerIcon();
  }

  function toggleFullscreen() {
    const container = document.querySelector(".avatar-container");
    if (!document.fullscreenElement) {
      container.requestFullscreen().catch(() => {});
    } else {
      document.exitFullscreen().catch(() => {});
    }
  }

  document.addEventListener("fullscreenchange", () => {
    const btn = document.getElementById("fullscreenBtn");
    if (!btn) return;
    if (document.fullscreenElement) {
      btn.innerHTML = SVG_FULLSCREEN_EXIT;
    } else {
      btn.innerHTML = SVG_FULLSCREEN;
    }
  });

  function toggleChatFromToolbar() {
    if (chatPanel.classList.contains("open")) {
      closeChat();
    } else {
      openChat();
    }
  }
```

---

### Task 8: Verify + commit

- [ ] **Step 1: Grep — no `endAvatarBtn` remains**

```powershell
Select-String -Path "static/index.html" -Pattern "endAvatarBtn"
```
Expected: no output

- [ ] **Step 2: Grep — avatarToolbar appears exactly 4 times**

```powershell
(Select-String -Path "static/index.html" -Pattern "avatarToolbar").Count
```
Expected: 4 (HTML declaration + startAvatar hide + track-started show + left-meeting hide + catch hide = 5 actually)

- [ ] **Step 3: Grep — all handler functions defined**

```powershell
Select-String -Path "static/index.html" -Pattern "function (toggleMic|toggleAvatarMute|setVolume|syncSpeakerIcon|toggleFullscreen|toggleChatFromToolbar)"
```
Expected: 6 matches

- [ ] **Step 4: Commit**

```bash
git add static/index.html docs/superpowers/plans/2026-06-17-tp5-avatar-toolbar.md
git commit -m "feat(ui): add avatar toolbar (TP5) — mic/speaker/volume/fullscreen/chat/end"
```
