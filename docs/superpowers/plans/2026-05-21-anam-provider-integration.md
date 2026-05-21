# Anam.io Provider Integration — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Anam.io als zweiten Avatar-Provider neben HeyGen integrieren, umschaltbar per `AVATAR_PROVIDER` in `.env` ohne Code-Änderung.

**Architecture:** Zwei neue Backend-Endpoints (`GET /avatar/config`, `POST /avatar/session`) ermöglichen Provider-Erkennung und Anam Session-Token-Austausch. Das Frontend liest beim Start den aktiven Provider und verzweigt `startAvatar()` und `avatarSpeak()` entsprechend. HeyGen-Code bleibt unverändert.

**Tech Stack:** FastAPI, httpx, Anam JS SDK (`@anam-ai/js-sdk` via CDN), pytest + FastAPI TestClient

---

## File Map

| Datei | Aktion | Zweck |
|-------|--------|-------|
| `main.py` | Modify | 2 neue Endpoints: `/avatar/config` und `/avatar/session` |
| `static/index.html` | Modify | Anam SDK Script-Tag, `<audio>`-Element, neue Globals, bedingte `startAvatar()`/`avatarSpeak()`, beforeunload-Handler |
| `.env` | Modify | `AVATAR_PROVIDER`, `ANAM_API_KEY`, `ANAM_PERSONA_ID` hinzufügen |
| `tests/test_avatar_config.py` | Create | Tests für `/avatar/config` und `/avatar/session` |

---

## Task 1: `.env` + Test-Datei anlegen

**Files:**
- Modify: `.env`
- Create: `tests/test_avatar_config.py`

- [ ] **Step 1: Neue Variablen zu `.env` hinzufügen**

Datei `.env` öffnen und am Ende hinzufügen:

```
AVATAR_PROVIDER=anam
ANAM_API_KEY=your_anam_api_key_here
ANAM_PERSONA_ID=your_anam_persona_id_here
```

`AVATAR_PROVIDER` auf `heygen` setzen um HeyGen zu nutzen, auf `anam` für Anam.

- [ ] **Step 2: `tests/test_avatar_config.py` anlegen**

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


def test_avatar_config_default_heygen():
    env = {k: v for k, v in os.environ.items() if k != "AVATAR_PROVIDER"}
    with patch.dict(os.environ, env, clear=True):
        response = test_client.get("/avatar/config")
    assert response.status_code == 200
    assert response.json() == {"provider": "heygen"}


def test_avatar_config_heygen():
    with patch.dict(os.environ, {"AVATAR_PROVIDER": "heygen"}):
        response = test_client.get("/avatar/config")
    assert response.status_code == 200
    assert response.json() == {"provider": "heygen"}


def test_avatar_config_anam():
    with patch.dict(os.environ, {"AVATAR_PROVIDER": "anam"}):
        response = test_client.get("/avatar/config")
    assert response.status_code == 200
    assert response.json() == {"provider": "anam"}


def test_avatar_config_invalid_falls_back():
    with patch.dict(os.environ, {"AVATAR_PROVIDER": "unknown_provider"}):
        response = test_client.get("/avatar/config")
    assert response.status_code == 200
    assert response.json() == {"provider": "heygen"}
```

- [ ] **Step 3: Verify tests fail (endpoint fehlt noch)**

```
pytest tests/test_avatar_config.py::test_avatar_config_anam -v
```

Expected: `FAILED` — 404 oder 405

- [ ] **Step 4: Commit**

```
git add .env tests/test_avatar_config.py
git commit -m "test: add avatar config test file and env vars"
```

---

## Task 2: `GET /avatar/config` Endpoint (TDD)

**Files:**
- Modify: `main.py`
- Modify: `tests/test_avatar_config.py`

- [ ] **Step 1: Endpoint in `main.py` hinzufügen**

Nach dem `streaming_sessions = {}`-Block (direkt nach `# ── Streaming Avatar Endpoints`-Kommentar), aber VOR dem ersten `@app.post("/streaming/new")`, folgenden Block einfügen:

```python
# ── Avatar Provider Config ────────────────────────────────
@app.get("/avatar/config")
def avatar_config():
    provider = os.getenv("AVATAR_PROVIDER", "heygen").lower()
    if provider not in ("heygen", "anam"):
        provider = "heygen"
    return {"provider": provider}
```

- [ ] **Step 2: Tests ausführen**

```
pytest tests/test_avatar_config.py::test_avatar_config_default_heygen tests/test_avatar_config.py::test_avatar_config_heygen tests/test_avatar_config.py::test_avatar_config_anam tests/test_avatar_config.py::test_avatar_config_invalid_falls_back -v
```

Expected: `4 passed`

- [ ] **Step 3: Commit**

```
git add main.py tests/test_avatar_config.py
git commit -m "feat: add GET /avatar/config endpoint"
```

---

## Task 3: `POST /avatar/session` Endpoint (TDD)

**Files:**
- Modify: `main.py`
- Modify: `tests/test_avatar_config.py`

- [ ] **Step 1: Tests hinzufügen** — an `tests/test_avatar_config.py` anhängen:

```python
@patch("main.httpx.AsyncClient")
def test_avatar_session_success(mock_httpx_class):
    mock_http = AsyncMock()
    mock_http.post.return_value = make_mock_response(200, {
        "session_token": "anam_tok_abc123"
    })
    mock_httpx_class.return_value.__aenter__ = AsyncMock(return_value=mock_http)
    mock_httpx_class.return_value.__aexit__ = AsyncMock(return_value=False)

    with patch.dict(os.environ, {
        "ANAM_API_KEY": "test-anam-key",
        "ANAM_PERSONA_ID": "persona_123"
    }):
        response = test_client.post("/avatar/session")

    assert response.status_code == 200
    data = response.json()
    assert data["session_token"] == "anam_tok_abc123"
    assert data["persona_id"] == "persona_123"

    call_headers = mock_http.post.call_args.kwargs["headers"]
    assert call_headers["Authorization"] == "Bearer test-anam-key"


def test_avatar_session_missing_api_key():
    with patch.dict(os.environ, {"ANAM_API_KEY": ""}):
        response = test_client.post("/avatar/session")
    assert response.status_code == 500


@patch("main.httpx.AsyncClient")
def test_avatar_session_timeout(mock_httpx_class):
    import httpx as real_httpx
    mock_http = AsyncMock()
    mock_http.post.side_effect = real_httpx.TimeoutException("timeout")
    mock_httpx_class.return_value.__aenter__ = AsyncMock(return_value=mock_http)
    mock_httpx_class.return_value.__aexit__ = AsyncMock(return_value=False)

    with patch.dict(os.environ, {"ANAM_API_KEY": "test-key", "ANAM_PERSONA_ID": "p1"}):
        response = test_client.post("/avatar/session")

    assert response.status_code == 504
```

- [ ] **Step 2: Verify tests fail**

```
pytest tests/test_avatar_config.py::test_avatar_session_success -v
```

Expected: `FAILED` — 404

- [ ] **Step 3: Endpoint in `main.py` hinzufügen** — direkt nach `avatar_config()`:

```python
@app.post("/avatar/session")
async def avatar_session():
    api_key = os.getenv("ANAM_API_KEY")
    if not api_key:
        raise HTTPException(status_code=500, detail="ANAM_API_KEY nicht gesetzt")

    persona_id = os.getenv("ANAM_PERSONA_ID", "")

    async with httpx.AsyncClient() as http:
        try:
            response = await http.post(
                "https://api.anam.ai/v1/auth/session",
                headers={
                    "Authorization": f"Bearer {api_key}",
                    "Content-Type": "application/json"
                },
                json={"persona_id": persona_id},
                timeout=15.0
            )
            data = response.json()
            if response.status_code != 200:
                raise HTTPException(status_code=response.status_code, detail=str(data))
            return {
                "session_token": data["session_token"],
                "persona_id": persona_id
            }
        except httpx.TimeoutException:
            raise HTTPException(status_code=504, detail="Anam API Timeout")
```

**Hinweis:** Den Anam API-Endpoint `https://api.anam.ai/v1/auth/session` vor dem Test mit echten Credentials in der [Anam-Dokumentation](https://docs.anam.ai) verifizieren — URL könnte abweichen.

- [ ] **Step 4: Alle neuen Tests ausführen**

```
pytest tests/test_avatar_config.py -v
```

Expected: `7 passed`

- [ ] **Step 5: Gesamte Test-Suite prüfen**

```
pytest tests/ -v
```

Expected: alle Tests bestehen (9 aus test_streaming.py + 7 neue = 16 total)

- [ ] **Step 6: Commit**

```
git add main.py tests/test_avatar_config.py
git commit -m "feat: add POST /avatar/session endpoint for Anam"
```

---

## Task 4: Frontend — SDK, Audio-Element und Globals

**Files:**
- Modify: `static/index.html`

- [ ] **Step 1: Anam SDK Script-Tag im `<head>` hinzufügen**

Im `<head>`-Block, direkt vor `</head>`:

```html
  <script src="https://cdn.jsdelivr.net/npm/@anam-ai/js-sdk/dist/index.umd.js"></script>
```

- [ ] **Step 2: `<audio>`-Element nach dem `<video>`-Element einfügen**

Direkt nach:
```html
      <video
        id="avatarVideo"
        ...
      ></video>
```

Einfügen:
```html
      <audio id="avatarAudio" autoplay></audio>
```

- [ ] **Step 3: Neue globale Variablen hinzufügen**

In `<script>`, direkt nach der Zeile `let peerConnection = null;`:

```javascript
  let avatarProvider = "heygen";
  let anamClient = null;
  const avatarAudio = document.getElementById("avatarAudio");
```

- [ ] **Step 4: Provider beim Seitenstart laden**

Direkt nach den Variablen-Deklarationen (vor dem Health-Check-Block), einfügen:

```javascript
  // Provider aus Backend laden
  fetch("/avatar/config")
    .then(r => r.json())
    .then(data => { avatarProvider = data.provider; })
    .catch(() => { avatarProvider = "heygen"; });
```

- [ ] **Step 5: Manual test**

```
uvicorn main:app --reload
```

Öffne `http://localhost:8000`. DevTools → Console: kein Fehler. DevTools → Network: `/avatar/config` wird aufgerufen und gibt `{"provider": "anam"}` (oder `"heygen"`) zurück.

- [ ] **Step 6: Commit**

```
git add static/index.html
git commit -m "feat: add Anam SDK, audio element and provider globals"
```

---

## Task 5: Frontend — Bedingte `startAvatar()` Funktion

**Files:**
- Modify: `static/index.html`

- [ ] **Step 1: Die gesamte `startAvatar()` Funktion ersetzen**

Finde die aktuelle `startAvatar()`-Funktion (beginnt mit `async function startAvatar()`) und ersetze sie vollständig durch:

```javascript
  async function startAvatar() {
    startBtn.disabled = true;
    avatarLabel.innerHTML = '<div style="display:flex;align-items:center;gap:8px;color:#009682"><div class="spinner"></div> Verbinde mit KIRA...</div>';

    if (avatarProvider === "anam") {
      await _startAvatarAnam();
    } else {
      await _startAvatarHeygen();
    }
  }

  async function _startAvatarAnam() {
    try {
      const res = await fetch("/avatar/session", { method: "POST" });
      if (!res.ok) {
        const err = await res.json();
        throw new Error(err.detail || "Session konnte nicht erstellt werden");
      }
      const { session_token, persona_id } = await res.json();

      anamClient = AnamSDK.createClient(session_token, {
        personaId: persona_id,
        disableInputAudio: true
      });

      await anamClient.streamToVideoAndAudioElements(avatarVideo, avatarAudio);

      avatarVideo.style.display = "block";
      avatarPH.style.display = "none";
      document.getElementById("statusText").textContent = "bereit";

    } catch (err) {
      console.error("Anam Fehler:", err);
      avatarLabel.textContent = "Avatar nicht verfügbar: " + err.message;
      startBtn.disabled = false;
      startBtn.textContent = "Erneut versuchen";
      anamClient = null;
    }
  }

  async function _startAvatarHeygen() {
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
      console.error("HeyGen Fehler:", err);
      avatarLabel.textContent = "Avatar nicht verfügbar: " + err.message;
      startBtn.disabled = false;
      startBtn.textContent = "Erneut versuchen";
      streamingSessionId = null;
      peerConnection = null;
    }
  }
```

- [ ] **Step 2: Manual test — Anam-Pfad**

Mit `AVATAR_PROVIDER=anam` in `.env`:

```
uvicorn main:app --reload
```

`http://localhost:8000` öffnen → "Avatar starten" klicken → DevTools → Network: `/avatar/session` erscheint. Bei gültigem `ANAM_API_KEY` und `ANAM_PERSONA_ID` erscheint der Anam-Avatar im Video-Element.

- [ ] **Step 3: Manual test — HeyGen-Pfad**

`AVATAR_PROVIDER=heygen` in `.env` setzen, Server neu starten. Gleicher Ablauf wie bisher — `/streaming/new` und WebRTC erscheinen im Network-Tab.

- [ ] **Step 4: Commit**

```
git add static/index.html
git commit -m "feat: add conditional startAvatar() for Anam and HeyGen"
```

---

## Task 6: Frontend — Bedingte `avatarSpeak()` + beforeunload-Handler

**Files:**
- Modify: `static/index.html`

- [ ] **Step 1: `avatarSpeak()` ersetzen**

Finde die bestehende `avatarSpeak()`-Funktion und ersetze sie vollständig durch:

```javascript
  async function avatarSpeak(text) {
    if (recognition) recognition.stop();
    if (avatarProvider === "anam" && anamClient) {
      try {
        await anamClient.talk(text);
      } catch (err) {
        console.warn("Anam konnte nicht sprechen:", err);
      }
    } else if (avatarProvider === "heygen" && streamingSessionId) {
      try {
        await fetch("/streaming/task", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ session_id: streamingSessionId, text })
        });
      } catch (err) {
        console.warn("HeyGen konnte nicht sprechen:", err);
      }
    }
  }
```

- [ ] **Step 2: `beforeunload`-Handler hinzufügen**

Direkt nach der `avatarSpeak()`-Funktion einfügen:

```javascript
  window.addEventListener("beforeunload", () => {
    if (avatarProvider === "anam" && anamClient) {
      anamClient.stopStreaming();
    } else if (avatarProvider === "heygen" && streamingSessionId) {
      navigator.sendBeacon("/streaming/stop",
        JSON.stringify({ session_id: streamingSessionId }));
    }
  });
```

- [ ] **Step 3: Vollständige Test-Suite ausführen**

```
pytest tests/ -v
```

Expected: 16 passed (alle Tests grün)

- [ ] **Step 4: Manual test — Ende-zu-Ende**

Mit `AVATAR_PROVIDER=anam`:
1. `http://localhost:8000` öffnen, "Avatar starten"
2. Frage tippen: "Was ist BAföG?" → Antwort erscheint im Chat UND Avatar spricht
3. Mikrofon-Button: sprechen → Avatar antwortet
4. Tab schließen → DevTools zeigen `stopStreaming()` wurde aufgerufen

Mit `AVATAR_PROVIDER=heygen`:
1. Gleicher Ablauf → WebRTC-Verbindung, HeyGen-Avatar spricht

- [ ] **Step 5: Commit**

```
git add static/index.html
git commit -m "feat: add conditional avatarSpeak() and beforeunload cleanup"
```
