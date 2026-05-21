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


# ── /streaming/start ──────────────────────────────────────
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


# ── /streaming/ice ────────────────────────────────────────
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


# ── /streaming/task ───────────────────────────────────────
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


# ── /streaming/stop ───────────────────────────────────────
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
    assert response.status_code in (404, 405)
