import os
os.environ.setdefault("GOOGLE_API_KEY", "test-key")

from app.main import app
from fastapi.testclient import TestClient
from unittest.mock import patch

test_client = TestClient(app)


def test_avatar_config_default_tavus():
    env = {k: v for k, v in os.environ.items() if k != "AVATAR_PROVIDER"}
    with patch.dict(os.environ, env, clear=True):
        response = test_client.get("/avatar/config")
    assert response.status_code == 200
    assert response.json() == {"provider": "tavus"}


def test_avatar_config_tavus_explicit():
    with patch.dict(os.environ, {"AVATAR_PROVIDER": "tavus"}):
        response = test_client.get("/avatar/config")
    assert response.status_code == 200
    assert response.json() == {"provider": "tavus"}


def test_avatar_config_invalid_value_returned_as_is():
    with patch.dict(os.environ, {"AVATAR_PROVIDER": "unknown_provider"}):
        response = test_client.get("/avatar/config")
    assert response.status_code == 200
    assert response.json() == {"provider": "unknown_provider"}


def test_health():
    response = test_client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}
