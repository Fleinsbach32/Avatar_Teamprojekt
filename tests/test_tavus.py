import os
os.environ.setdefault("GOOGLE_API_KEY", "test-key")
os.environ.setdefault("TAVUS_API_KEY", "test-tavus-key")
os.environ.setdefault("TAVUS_REPLICA_ID", "test-replica-id")

from main import app
from fastapi.testclient import TestClient
from unittest.mock import patch, MagicMock, AsyncMock

test_client = TestClient(app)


def make_mock_response(status_code: int, json_data: dict) -> MagicMock:
    mock_resp = MagicMock()
    mock_resp.status_code = status_code
    mock_resp.json.return_value = json_data
    return mock_resp


# ── /tavus/session ────────────────────────────────────────
@patch("main.httpx.AsyncClient")
def test_tavus_session_success(mock_httpx_class):
    mock_http = AsyncMock()
    mock_http.post.return_value = make_mock_response(200, {
        "conversation_id": "conv_abc123",
        "conversation_url": "https://tavus.daily.co/abc123"
    })
    mock_httpx_class.return_value.__aenter__ = AsyncMock(return_value=mock_http)
    mock_httpx_class.return_value.__aexit__ = AsyncMock(return_value=False)

    with patch.dict(os.environ, {
        "TAVUS_API_KEY": "real-key",
        "TAVUS_REPLICA_ID": "replica_xyz",
        "TAVUS_PERSONA_ID": "",
        "BASE_URL": "http://localhost:8000"
    }):
        response = test_client.post("/tavus/session")

    assert response.status_code == 200
    data = response.json()
    assert data["conversation_id"] == "conv_abc123"
    assert data["conversation_url"] == "https://tavus.daily.co/abc123"

    call_kwargs = mock_http.post.call_args.kwargs
    assert call_kwargs["headers"]["x-api-key"] == "real-key"
    assert call_kwargs["json"]["replica_id"] == "replica_xyz"
    assert "llm_websocket_url" in call_kwargs["json"]["custom_llm_extra_body"]


def test_tavus_session_missing_api_key():
    with patch.dict(os.environ, {"TAVUS_API_KEY": ""}):
        response = test_client.post("/tavus/session")
    assert response.status_code == 500


@patch("main.httpx.AsyncClient")
def test_tavus_session_api_error(mock_httpx_class):
    mock_http = AsyncMock()
    mock_http.post.return_value = make_mock_response(401, {"error": "unauthorized"})
    mock_httpx_class.return_value.__aenter__ = AsyncMock(return_value=mock_http)
    mock_httpx_class.return_value.__aexit__ = AsyncMock(return_value=False)

    with patch.dict(os.environ, {"TAVUS_API_KEY": "bad-key"}):
        response = test_client.post("/tavus/session")

    assert response.status_code == 401


@patch("main.httpx.AsyncClient")
def test_tavus_session_timeout(mock_httpx_class):
    import httpx as real_httpx
    mock_http = AsyncMock()
    mock_http.post.side_effect = real_httpx.TimeoutException("timeout")
    mock_httpx_class.return_value.__aenter__ = AsyncMock(return_value=mock_http)
    mock_httpx_class.return_value.__aexit__ = AsyncMock(return_value=False)

    response = test_client.post("/tavus/session")
    assert response.status_code == 504


# ── /tavus/end ────────────────────────────────────────────
@patch("main.httpx.AsyncClient")
def test_tavus_end_success(mock_httpx_class):
    mock_http = AsyncMock()
    mock_http.delete.return_value = make_mock_response(200, {})
    mock_httpx_class.return_value.__aenter__ = AsyncMock(return_value=mock_http)
    mock_httpx_class.return_value.__aexit__ = AsyncMock(return_value=False)

    response = test_client.post("/tavus/end", json={"conversation_id": "conv_abc123"})

    assert response.status_code == 200
    assert response.json() == {"status": "ended"}

    call_url = mock_http.delete.call_args.args[0]
    assert "conv_abc123" in call_url


# ── /tavus/llm ────────────────────────────────────────────
@patch("main.collection")
@patch("main.client")
def test_tavus_llm_success(mock_client, mock_collection):
    mock_collection.query.return_value = {
        "documents": [["KIT Prüfungsanmeldung erfolgt über das Campus-Portal."]],
        "distances": [[0.3]]
    }
    mock_response = MagicMock()
    mock_response.text = "Prüfungen werden im Campus-Portal unter campus.kit.edu angemeldet."
    mock_client.models.generate_content.return_value = mock_response

    response = test_client.post("/tavus/llm", json={
        "messages": [{"role": "user", "content": "Wie melde ich mich für Prüfungen an?"}],
        "stream": True
    })

    assert response.status_code == 200
    assert "text/event-stream" in response.headers.get("content-type", "")
    body = response.text
    assert "data:" in body
    assert "[DONE]" in body
    assert "campus.kit.edu" in body
