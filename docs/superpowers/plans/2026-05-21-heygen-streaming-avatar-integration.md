# HeyGen Streaming Avatar Integration — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the liveavatar.com iframe with HeyGen Streaming Avatar (WebRTC) so KIRA's chatbot answers are spoken by the avatar with lip-sync, and the user can also speak to KIRA via microphone.

**Architecture:** Five new proxy endpoints in `main.py` relay WebRTC session management to HeyGen's Streaming API. The browser builds a WebRTC connection using those credentials, then calls `/streaming/task` after every `/chat` response. Voice input via the browser's Web Speech API is transcribed and sent to `/chat`.

**Tech Stack:** FastAPI, httpx (already installed), HeyGen Streaming Avatar REST API, WebRTC (browser-native), Web Speech API (browser-native), pytest + FastAPI TestClient

---

## File Map

| File | Action | Purpose |
|------|--------|---------|
| `main.py` | Modify | Remove `/liveavatar-embed`; add `streaming_sessions` dict + 5 new `/streaming/*` endpoints |
| `static/index.html` | Modify | Replace `<iframe>` with `<video>`, rewrite `startAvatar()` for WebRTC, add `avatarSpeak()`, replace TTS toggle with mic button |
| `.env` | Modify | Add `HEYGEN_AVATAR_ID` |
| `tests/__init__.py` | Create | Empty — makes `tests/` a package |
| `tests/conftest.py` | Create | Patches heavy dependencies before any test imports `main` |
| `tests/test_streaming.py` | Create | pytest tests for all 5 streaming endpoints |

---

## Task 1: Test infrastructure + env var

**Files:**
- Create: `tests/__init__.py`
- Create: `tests/conftest.py`
- Create: `tests/test_streaming.py`
- Modify: `.env`

- [ ] **Step 1: Install pytest**

```
pip install pytest
```

Expected: `Successfully installed pytest-...`

- [ ] **Step 2: Add `HEYGEN_AVATAR_ID` to `.env`**

Open `.env` and add (replace with your actual Streaming Avatar ID from the HeyGen Dashboard under Streaming Avatar):

```
HEYGEN_AVATAR_ID=your_streaming_avatar_id_here
```

- [ ] **Step 3: Create `tests/__init__.py`** (empty file)

```python
```

- [ ] **Step 4: Create `tests/conftest.py`**

This file must be loaded by pytest before any test file imports `main`, so the heavy ML/DB modules are mocked at the point `main` is first imported.

```python
import sys
from unittest.mock import MagicMock

sys.modules.update({
    'chromadb': MagicMock(),
    'chromadb.utils': MagicMock(),
    'chromadb.utils.embedding_functions': MagicMock(),
    'google': MagicMock(),
    'google.genai': MagicMock(),
    'google.genai.types': MagicMock(),
    'sentence_transformers': MagicMock(),
    'torch': MagicMock(),
})
```

- [ ] **Step 5: Create `tests/test_streaming.py` with smoke test + shared helper**

```python
import os
os.environ.setdefault("GOOGLE_API_KEY", "test-key")
os.environ.setdefault("HEYGEN_API_KEY", "test-heygen-key")
os.environ.setdefault("HEYGEN_AVATAR_ID", "test-avatar-id")
os.environ.setdefault("HEYGEN_VOICE_ID", "test-voice-id")

from main import app
from fastapi.testclient import TestClient
from unittest.mock import patch, MagicMock, AsyncMock

test_client = TestClient(app)


def make_mock_response(status_code: int, json_data: dict) -> MagicMock:
    mock_resp = MagicMock()
    mock_resp.status_code = status_code
    mock_resp.json.return_value = json_data
    return mock_resp


def test_health():
    response = test_client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}
```

- [ ] **Step 6: Run smoke test**

```
pytest tests/test_streaming.py::test_health -v
```

Expected:
```
PASSED tests/test_streaming.py::test_health
```

- [ ] **Step 7: Commit**

```
git add tests/__init__.py tests/conftest.py tests/test_streaming.py .env
git commit -m "test: add test infrastructure for streaming endpoints"
```

---

## Task 2: `/streaming/new` endpoint

**Files:**
- Modify: `main.py`
- Modify: `tests/test_streaming.py`

- [ ] **Step 1: Write failing tests** — append to `tests/test_streaming.py`:

```python
@patch("main.httpx.AsyncClient")
def test_streaming_new_success(mock_httpx_class):
    mock_http = AsyncMock()
    mock_http.post.return_value = make_mock_response(200, {
        "data": {
            "session_id": "sess_123",
            "sdp": {"sdp": "v=0...", "type": "offer"},
            "ice_servers": [{"urls": "stun:stun.l.google.com:19302"}],
            "access_token": "tok_abc"
        }
    })
    mock_httpx_class.return_value.__aenter__ = AsyncMock(return_value=mock_http)
    mock_httpx_class.return_value.__aexit__ = AsyncMock(return_value=False)

    response = test_client.post("/streaming/new")

    assert response.status_code == 200
    data = response.json()
    assert data["session_id"] == "sess_123"
    assert data["sdp"]["type"] == "offer"
    assert len(data["ice_servers"]) == 1


@patch("main.httpx.AsyncClient")
def test_streaming_new_missing_api_key(mock_httpx_class):
    with patch.dict(os.environ, {"HEYGEN_API_KEY": ""}):
        response = test_client.post("/streaming/new")
    assert response.status_code == 500
```

- [ ] **Step 2: Run to verify failure**

```
pytest tests/test_streaming.py::test_streaming_new_success -v
```

Expected: `FAILED` with 404 (endpoint doesn't exist yet)

- [ ] **Step 3: Add `streaming_sessions` dict and `/streaming/new` to `main.py`**

After the line `sessions = {}` (line 38), add:

```python
streaming_sessions = {}
```

After the `class ChatRequest` block and before the `# ── LiveAvatar Embed` comment, add:

```python
# ── Streaming Avatar Endpoints ────────────────────────────
@app.post("/streaming/new")
async def streaming_new():
    api_key = os.getenv("HEYGEN_API_KEY")
    if not api_key:
        raise HTTPException(status_code=500, detail="HEYGEN_API_KEY nicht gesetzt")

    async with httpx.AsyncClient() as http:
        try:
            response = await http.post(
                "https://api.heygen.com/v1/streaming.new",
                headers={"X-Api-Key": api_key, "Content-Type": "application/json"},
                json={
                    "quality": "high",
                    "avatar_name": os.getenv("HEYGEN_AVATAR_ID", ""),
                    "voice": {"voice_id": os.getenv("HEYGEN_VOICE_ID", "")}
                },
                timeout=15.0
            )
            data = response.json()
            if response.status_code != 200:
                raise HTTPException(status_code=response.status_code, detail=str(data))
            session_id = data["data"]["session_id"]
            streaming_sessions[session_id] = True
            return {
                "session_id": session_id,
                "sdp": data["data"]["sdp"],
                "ice_servers": data["data"]["ice_servers"],
                "access_token": data["data"]["access_token"]
            }
        except httpx.TimeoutException:
            raise HTTPException(status_code=504, detail="HeyGen API Timeout")
```

- [ ] **Step 4: Run tests**

```
pytest tests/test_streaming.py::test_streaming_new_success tests/test_streaming.py::test_streaming_new_missing_api_key -v
```

Expected: `2 passed`

- [ ] **Step 5: Commit**

```
git add main.py tests/test_streaming.py
git commit -m "feat: add /streaming/new endpoint"
```

---

## Task 3: `/streaming/start` endpoint

**Files:**
- Modify: `main.py`
- Modify: `tests/test_streaming.py`

- [ ] **Step 1: Write failing test** — append to `tests/test_streaming.py`:

```python
@patch("main.httpx.AsyncClient")
def test_streaming_start_success(mock_httpx_class):
    mock_http = AsyncMock()
    mock_http.post.return_value = make_mock_response(200, {"code": 100, "data": {}})
    mock_httpx_class.return_value.__aenter__ = AsyncMock(return_value=mock_http)
    mock_httpx_class.return_value.__aexit__ = AsyncMock(return_value=False)

    response = test_client.post("/streaming/start", json={
        "session_id": "sess_123",
        "sdp": {"sdp": "v=0...", "type": "answer"}
    })

    assert response.status_code == 200
    assert response.json() == {"status": "started"}
```

- [ ] **Step 2: Run to verify failure**

```
pytest tests/test_streaming.py::test_streaming_start_success -v
```

Expected: `FAILED` with 422 (endpoint doesn't exist, body validation fails)

- [ ] **Step 3: Add `StreamingStartRequest` and `/streaming/start` to `main.py`** — after the `/streaming/new` endpoint:

```python
class StreamingStartRequest(BaseModel):
    session_id: str
    sdp: dict


@app.post("/streaming/start")
async def streaming_start(request: StreamingStartRequest):
    api_key = os.getenv("HEYGEN_API_KEY")
    async with httpx.AsyncClient() as http:
        try:
            response = await http.post(
                "https://api.heygen.com/v1/streaming.start",
                headers={"X-Api-Key": api_key, "Content-Type": "application/json"},
                json={"session_id": request.session_id, "sdp": request.sdp},
                timeout=15.0
            )
            data = response.json()
            if response.status_code != 200:
                raise HTTPException(status_code=response.status_code, detail=str(data))
            return {"status": "started"}
        except httpx.TimeoutException:
            raise HTTPException(status_code=504, detail="HeyGen API Timeout")
```

- [ ] **Step 4: Run tests**

```
pytest tests/test_streaming.py::test_streaming_start_success -v
```

Expected: `1 passed`

- [ ] **Step 5: Commit**

```
git add main.py tests/test_streaming.py
git commit -m "feat: add /streaming/start endpoint"
```

---

## Task 4: `/streaming/ice` endpoint

**Files:**
- Modify: `main.py`
- Modify: `tests/test_streaming.py`

- [ ] **Step 1: Write failing test** — append to `tests/test_streaming.py`:

```python
@patch("main.httpx.AsyncClient")
def test_streaming_ice_success(mock_httpx_class):
    mock_http = AsyncMock()
    mock_http.post.return_value = make_mock_response(200, {"code": 100, "data": {}})
    mock_httpx_class.return_value.__aenter__ = AsyncMock(return_value=mock_http)
    mock_httpx_class.return_value.__aexit__ = AsyncMock(return_value=False)

    response = test_client.post("/streaming/ice", json={
        "session_id": "sess_123",
        "candidate": {
            "candidate": "candidate:1 1 UDP 2130706431 192.168.0.1 54400 typ host",
            "sdpMid": "0",
            "sdpMLineIndex": 0
        }
    })

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}
```

- [ ] **Step 2: Run to verify failure**

```
pytest tests/test_streaming.py::test_streaming_ice_success -v
```

Expected: `FAILED` with 404

- [ ] **Step 3: Add `StreamingIceRequest` and `/streaming/ice` to `main.py`** — after `/streaming/start`:

```python
class StreamingIceRequest(BaseModel):
    session_id: str
    candidate: dict


@app.post("/streaming/ice")
async def streaming_ice(request: StreamingIceRequest):
    api_key = os.getenv("HEYGEN_API_KEY")
    async with httpx.AsyncClient() as http:
        response = await http.post(
            "https://api.heygen.com/v1/streaming.ice",
            headers={"X-Api-Key": api_key, "Content-Type": "application/json"},
            json={"session_id": request.session_id, "candidate": request.candidate},
            timeout=10.0
        )
        data = response.json()
        if response.status_code != 200:
            raise HTTPException(status_code=response.status_code, detail=str(data))
        return {"status": "ok"}
```

- [ ] **Step 4: Run tests**

```
pytest tests/test_streaming.py::test_streaming_ice_success -v
```

Expected: `1 passed`

- [ ] **Step 5: Commit**

```
git add main.py tests/test_streaming.py
git commit -m "feat: add /streaming/ice endpoint"
```

---

## Task 5: `/streaming/task` endpoint

**Files:**
- Modify: `main.py`
- Modify: `tests/test_streaming.py`

- [ ] **Step 1: Write failing tests** — append to `tests/test_streaming.py`:

```python
@patch("main.httpx.AsyncClient")
def test_streaming_task_success(mock_httpx_class):
    mock_http = AsyncMock()
    mock_http.post.return_value = make_mock_response(200, {"code": 100, "data": {}})
    mock_httpx_class.return_value.__aenter__ = AsyncMock(return_value=mock_http)
    mock_httpx_class.return_value.__aexit__ = AsyncMock(return_value=False)

    response = test_client.post("/streaming/task", json={
        "session_id": "sess_123",
        "text": "Willkommen bei KIRA!"
    })

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}
    call_kwargs = mock_http.post.call_args.kwargs["json"]
    assert call_kwargs["task_type"] == "repeat"
    assert call_kwargs["text"] == "Willkommen bei KIRA!"


@patch("main.httpx.AsyncClient")
def test_streaming_task_timeout(mock_httpx_class):
    import httpx as real_httpx
    mock_http = AsyncMock()
    mock_http.post.side_effect = real_httpx.TimeoutException("timeout")
    mock_httpx_class.return_value.__aenter__ = AsyncMock(return_value=mock_http)
    mock_httpx_class.return_value.__aexit__ = AsyncMock(return_value=False)

    response = test_client.post("/streaming/task", json={
        "session_id": "sess_123",
        "text": "Test"
    })

    assert response.status_code == 504
```

- [ ] **Step 2: Run to verify failure**

```
pytest tests/test_streaming.py::test_streaming_task_success -v
```

Expected: `FAILED` with 404

- [ ] **Step 3: Add `StreamingTaskRequest` and `/streaming/task` to `main.py`** — after `/streaming/ice`:

```python
class StreamingTaskRequest(BaseModel):
    session_id: str
    text: str


@app.post("/streaming/task")
async def streaming_task(request: StreamingTaskRequest):
    api_key = os.getenv("HEYGEN_API_KEY")
    async with httpx.AsyncClient() as http:
        try:
            response = await http.post(
                "https://api.heygen.com/v1/streaming.task",
                headers={"X-Api-Key": api_key, "Content-Type": "application/json"},
                json={
                    "session_id": request.session_id,
                    "text": request.text,
                    "task_type": "repeat"
                },
                timeout=10.0
            )
            data = response.json()
            if response.status_code != 200:
                raise HTTPException(status_code=response.status_code, detail=str(data))
            return {"status": "ok"}
        except httpx.TimeoutException:
            raise HTTPException(status_code=504, detail="HeyGen API Timeout")
```

- [ ] **Step 4: Run tests**

```
pytest tests/test_streaming.py::test_streaming_task_success tests/test_streaming.py::test_streaming_task_timeout -v
```

Expected: `2 passed`

- [ ] **Step 5: Commit**

```
git add main.py tests/test_streaming.py
git commit -m "feat: add /streaming/task endpoint"
```

---

## Task 6: `/streaming/stop` endpoint + remove `/liveavatar-embed`

**Files:**
- Modify: `main.py`
- Modify: `tests/test_streaming.py`

- [ ] **Step 1: Write failing tests** — append to `tests/test_streaming.py`:

```python
@patch("main.httpx.AsyncClient")
def test_streaming_stop_success(mock_httpx_class):
    mock_http = AsyncMock()
    mock_http.post.return_value = make_mock_response(200, {"code": 100, "data": {}})
    mock_httpx_class.return_value.__aenter__ = AsyncMock(return_value=mock_http)
    mock_httpx_class.return_value.__aexit__ = AsyncMock(return_value=False)

    from main import streaming_sessions
    streaming_sessions["sess_999"] = True

    response = test_client.post("/streaming/stop", json={"session_id": "sess_999"})

    assert response.status_code == 200
    assert response.json() == {"status": "stopped"}
    assert "sess_999" not in streaming_sessions


def test_liveavatar_embed_removed():
    response = test_client.post("/liveavatar-embed")
    assert response.status_code == 404
```

- [ ] **Step 2: Run to verify failure**

```
pytest tests/test_streaming.py::test_streaming_stop_success tests/test_streaming.py::test_liveavatar_embed_removed -v
```

Expected: both `FAILED` (stop returns 404, liveavatar-embed still exists)

- [ ] **Step 3: Add `StreamingStopRequest` and `/streaming/stop` to `main.py`** — after `/streaming/task`:

```python
class StreamingStopRequest(BaseModel):
    session_id: str


@app.post("/streaming/stop")
async def streaming_stop(request: StreamingStopRequest):
    api_key = os.getenv("HEYGEN_API_KEY")
    async with httpx.AsyncClient() as http:
        try:
            response = await http.post(
                "https://api.heygen.com/v1/streaming.stop",
                headers={"X-Api-Key": api_key, "Content-Type": "application/json"},
                json={"session_id": request.session_id},
                timeout=10.0
            )
            data = response.json()
            if response.status_code != 200:
                raise HTTPException(status_code=response.status_code, detail=str(data))
            streaming_sessions.pop(request.session_id, None)
            return {"status": "stopped"}
        except httpx.TimeoutException:
            raise HTTPException(status_code=504, detail="HeyGen API Timeout")
```

- [ ] **Step 4: Remove the `/liveavatar-embed` endpoint from `main.py`**

Delete the entire block — from the comment through the final `except` block:

```python
# ── LiveAvatar Embed Endpoint ─────────────────────────────
@app.post("/liveavatar-embed")
async def get_liveavatar_embed():
    ...
    # (entire function body)
    ...
        except httpx.TimeoutException:
            raise HTTPException(status_code=504, detail="LiveAvatar API Timeout")
```

- [ ] **Step 5: Run all streaming tests**

```
pytest tests/test_streaming.py -v
```

Expected: all tests pass

- [ ] **Step 6: Commit**

```
git add main.py tests/test_streaming.py
git commit -m "feat: add /streaming/stop, remove /liveavatar-embed"
```

---

## Task 7: Frontend — Replace `<iframe>` with `<video>` element

**Files:**
- Modify: `static/index.html`

*(Note: Tasks 7–10 use manual testing — there is no JS test framework in this project.)*

- [ ] **Step 1: Replace the iframe HTML** — find (around line 453):

```html
      <!-- LiveAvatar Embed iframe -->
      <iframe
        id="avatarIframe"
        allow="microphone; camera"
        title="KIRA LiveAvatar"
      ></iframe>
```

Replace with:

```html
      <video
        id="avatarVideo"
        autoplay
        playsinline
        style="width:100%;height:100%;border:none;border-radius:12px;display:none;object-fit:cover;"
      ></video>
```

- [ ] **Step 2: Replace the CSS rule** — find in `<style>`:

```css
    /* LiveAvatar iframe */
    #avatarIframe {
      width: 100%;
      height: 100%;
      border: none;
      display: none;
      border-radius: 12px;
    }
```

Replace with:

```css
    #avatarVideo {
      width: 100%;
      height: 100%;
      border: none;
      border-radius: 12px;
      object-fit: cover;
      display: none;
    }
```

- [ ] **Step 3: Update JS globals** — find in `<script>`:

```javascript
  const avatarIframe = document.getElementById("avatarIframe");
```

Replace with:

```javascript
  const avatarVideo  = document.getElementById("avatarVideo");
  let streamingSessionId = null;
  let peerConnection = null;
```

- [ ] **Step 4: Manual test**

```
uvicorn main:app --reload
```

Open `http://localhost:8000` in Chrome. Open DevTools → Elements.

Confirm: `<video id="avatarVideo">` exists, `<iframe>` is gone, placeholder and "Avatar starten" button are visible.

- [ ] **Step 5: Commit**

```
git add static/index.html
git commit -m "feat: replace avatar iframe with video element"
```

---

## Task 8: Frontend — WebRTC setup in `startAvatar()`

**Files:**
- Modify: `static/index.html`

- [ ] **Step 1: Replace `startAvatar()` entirely** — find the whole function (from `async function startAvatar()` to its closing `}`) and replace with:

```javascript
  async function startAvatar() {
    startBtn.disabled = true;
    avatarLabel.innerHTML = '<div style="display:flex;align-items:center;gap:8px;color:#009682"><div class="spinner"></div> Verbinde mit KIRA...</div>';

    try {
      const res = await fetch("/streaming/new", { method: "POST" });
      if (!res.ok) {
        const err = await res.json();
        throw new Error(err.detail || "Session konnte nicht erstellt werden");
      }
      const { session_id, sdp, ice_servers } = await res.json();
      streamingSessionId = session_id;

      peerConnection = new RTCPeerConnection({ iceServers: ice_servers });

      peerConnection.ontrack = (event) => {
        avatarVideo.srcObject = event.streams[0];
        avatarVideo.style.display = "block";
        avatarPH.style.display = "none";
        document.getElementById("statusText").textContent = "bereit";
      };

      peerConnection.onicecandidate = async (event) => {
        if (!event.candidate) return;
        await fetch("/streaming/ice", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            session_id: streamingSessionId,
            candidate: event.candidate.toJSON()
          })
        });
      };

      peerConnection.onconnectionstatechange = () => {
        const state = peerConnection.connectionState;
        if (state === "disconnected" || state === "failed") {
          avatarVideo.style.display = "none";
          avatarPH.style.display = "flex";
          avatarLabel.textContent = "Verbindung getrennt";
          startBtn.disabled = false;
          startBtn.textContent = "Erneut verbinden";
          streamingSessionId = null;
          peerConnection = null;
          document.getElementById("statusText").textContent = "getrennt";
        }
      };

      await peerConnection.setRemoteDescription(new RTCSessionDescription(sdp));
      const answer = await peerConnection.createAnswer();
      await peerConnection.setLocalDescription(answer);

      const startRes = await fetch("/streaming/start", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          session_id: streamingSessionId,
          sdp: { sdp: answer.sdp, type: answer.type }
        })
      });
      if (!startRes.ok) throw new Error("Stream konnte nicht gestartet werden");

    } catch (err) {
      console.error("Avatar Fehler:", err);
      avatarLabel.textContent = "Avatar nicht verfügbar: " + err.message;
      startBtn.disabled = false;
      startBtn.textContent = "Erneut versuchen";
      streamingSessionId = null;
      peerConnection = null;
    }
  }
```

- [ ] **Step 2: Add `avatarSpeak()` helper** — add directly after the closing `}` of `startAvatar()`:

```javascript
  async function avatarSpeak(text) {
    if (!streamingSessionId) return;
    try {
      await fetch("/streaming/task", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ session_id: streamingSessionId, text })
      });
    } catch (err) {
      console.warn("Avatar konnte nicht sprechen:", err);
    }
  }
```

- [ ] **Step 3: Manual test**

```
uvicorn main:app --reload
```

Open `http://localhost:8000` in Chrome. Click "Avatar starten".

In DevTools → Network: confirm calls to `/streaming/new` then `/streaming/ice` (multiple) then `/streaming/start` appear in sequence.

If `HEYGEN_AVATAR_ID` is a valid streaming avatar ID, the avatar video should appear after a few seconds.

- [ ] **Step 4: Commit**

```
git add static/index.html
git commit -m "feat: implement WebRTC setup for HeyGen Streaming Avatar"
```

---

## Task 9: Frontend — Connect chat responses to `avatarSpeak()`

**Files:**
- Modify: `static/index.html`

- [ ] **Step 1: In `sendMessage()`, replace the TTS call with `avatarSpeak()`**

Find:

```javascript
      // TTS Fallback (Avatar hat eigene Stimme im iframe)
      speak(data.answer);
```

Replace with:

```javascript
      await avatarSpeak(data.answer);
```

- [ ] **Step 2: Delete the `speak()` function entirely**

Find and delete this whole block:

```javascript
 async function speak(text) {
  if (!ttsEnabled) return;
  try {
    const res = await fetch("/tts", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ text })
    });
    const data = await res.json();
    const audio = new Audio(data.audio_url);
    audio.play();
  } catch {
    // Fallback Browser TTS
    const utt = new SpeechSynthesisUtterance(text);
    utt.lang = "de-DE";
    window.speechSynthesis.speak(utt);
  }
}
```

- [ ] **Step 3: Manual test — full chat + avatar flow**

```
uvicorn main:app --reload
```

1. Open `http://localhost:8000` in Chrome
2. Click "Avatar starten", wait for avatar video to appear
3. Type "Was ist das Semesterticket?" and press Enter
4. Confirm: answer appears in text chat bubble AND avatar speaks it (lip-sync)
5. In DevTools → Network: confirm `/chat` followed immediately by `/streaming/task`

- [ ] **Step 4: Commit**

```
git add static/index.html
git commit -m "feat: route chatbot answers through avatar speech"
```

---

## Task 10: Frontend — Microphone button (Web Speech API)

**Files:**
- Modify: `static/index.html`

- [ ] **Step 1: Replace the TTS button HTML** — find:

```html
      <button class="tts-btn active" id="ttsBtn" title="Text-to-Speech">
        <svg viewBox="0 0 24 24" fill="currentColor"><path d="M3 9v6h4l5 5V4L7 9H3zm13.5 3c0-1.77-1.02-3.29-2.5-4.03v8.05c1.48-.73 2.5-2.25 2.5-4.02z"/></svg>
      </button>
```

Replace with:

```html
      <button class="tts-btn" id="ttsBtn" title="Spracheingabe (Chrome/Edge)">
        <svg viewBox="0 0 24 24" fill="currentColor">
          <path d="M12 1a3 3 0 0 0-3 3v8a3 3 0 0 0 6 0V4a3 3 0 0 0-3-3zM19 10v2a7 7 0 0 1-14 0v-2H3v2a9 9 0 0 0 8 8.94V22h-3v2h8v-2h-3v-1.06A9 9 0 0 0 21 12v-2h-2z"/>
        </svg>
      </button>
```

- [ ] **Step 2: Remove the `ttsEnabled` variable** — find and delete:

```javascript
  let ttsEnabled  = true;
```

- [ ] **Step 3: Replace the TTS button click listener** — find and delete:

```javascript
  ttsBtn.addEventListener("click", () => {
    ttsEnabled = !ttsEnabled;
    ttsBtn.classList.toggle("active", ttsEnabled);
    if (!ttsEnabled) window.speechSynthesis.cancel();
  });
```

In its place, add the microphone logic:

```javascript
  let recognition = null;

  if (!('SpeechRecognition' in window) && !('webkitSpeechRecognition' in window)) {
    ttsBtn.disabled = true;
    ttsBtn.title = "Spracheingabe nur in Chrome/Edge verfügbar";
  } else {
    const SpeechRecognition = window.SpeechRecognition || window.webkitSpeechRecognition;
    recognition = new SpeechRecognition();
    recognition.lang = "de-DE";
    recognition.interimResults = false;
    recognition.maxAlternatives = 1;

    recognition.onresult = (event) => {
      const transcript = event.results[0][0].transcript;
      document.getElementById("userInput").value = transcript;
      sendMessage();
    };

    recognition.onerror = (event) => {
      console.warn("Spracherkennung:", event.error);
      ttsBtn.classList.remove("active");
    };

    recognition.onend = () => {
      ttsBtn.classList.remove("active");
    };

    ttsBtn.addEventListener("click", () => {
      if (ttsBtn.classList.contains("active")) {
        recognition.stop();
      } else {
        recognition.start();
        ttsBtn.classList.add("active");
      }
    });
  }
```

- [ ] **Step 4: Pause mic during avatar speech** — in `avatarSpeak()` (written in Task 8), add `if (recognition) recognition.stop();` as the first line of the function body:

```javascript
  async function avatarSpeak(text) {
    if (!streamingSessionId) return;
    if (recognition) recognition.stop();   // ← add this line
    try {
      await fetch("/streaming/task", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ session_id: streamingSessionId, text })
      });
    } catch (err) {
      console.warn("Avatar konnte nicht sprechen:", err);
    }
  }
```

- [ ] **Step 5: Manual test — full voice flow**

```
uvicorn main:app --reload
```

1. Open `http://localhost:8000` in Chrome
2. Click "Avatar starten", wait for avatar video
3. Click the mic button (it lights up)
4. Speak: "Wie melde ich mich für Prüfungen an?"
5. Confirm: transcript appears in input field, is sent automatically, avatar speaks the answer
6. Mic button returns to inactive while avatar speaks

Test degraded mode: open in Firefox. Confirm mic button is `disabled` and tooltip says "Spracheingabe nur in Chrome/Edge verfügbar". Text chat still works normally.

- [ ] **Step 6: Commit**

```
git add static/index.html
git commit -m "feat: add microphone button with Web Speech API for voice input"
```
