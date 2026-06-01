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


# ── /avatar/session ───────────────────────────────────────
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
