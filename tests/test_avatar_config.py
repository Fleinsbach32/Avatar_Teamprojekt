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
