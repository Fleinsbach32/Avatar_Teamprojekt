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
