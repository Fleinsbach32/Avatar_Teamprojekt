import os
os.environ.setdefault("GOOGLE_API_KEY", "test-key")
os.environ.setdefault("LIVEAVATAR_API_KEY", "test-liveavatar-key")
os.environ.setdefault("LIVEAVATAR_AVATAR_ID", "test-avatar-id")
os.environ.setdefault("LIVEAVATAR_CONTEXT_ID", "test-context-id")

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


# ── /liveavatar/session ───────────────────────────────────
@patch("main.httpx.AsyncClient")
def test_liveavatar_session_success(mock_httpx_class):
    mock_http = AsyncMock()
    mock_http.post.side_effect = [
        make_mock_response(200, {
            "data": {
                "session_id": "sess_abc",
                "session_token": "jwt_token_xyz"
            }
        }),
        make_mock_response(201, {
            "data": {
                "session_id": "sess_abc",
                "livekit_url": "wss://livekit.example.com",
                "livekit_client_token": "lk_client_token"
            }
        })
    ]
    mock_httpx_class.return_value.__aenter__ = AsyncMock(return_value=mock_http)
    mock_httpx_class.return_value.__aexit__ = AsyncMock(return_value=False)

    with patch.dict(os.environ, {
        "LIVEAVATAR_API_KEY": "test-key",
        "LIVEAVATAR_AVATAR_ID": "avatar_123",
        "LIVEAVATAR_CONTEXT_ID": "ctx_456"
    }):
        response = test_client.post("/liveavatar/session")

    assert response.status_code == 200
    data = response.json()
    assert data["session_id"] == "sess_abc"
    assert data["livekit_url"] == "wss://livekit.example.com"
    assert data["livekit_client_token"] == "lk_client_token"

    # Erster Aufruf muss X-API-KEY enthalten
    first_call = mock_http.post.call_args_list[0]
    assert first_call.kwargs["headers"]["X-API-KEY"] == "test-key"
    assert first_call.kwargs["json"]["mode"] == "FULL"
    assert first_call.kwargs["json"]["avatar_id"] == "avatar_123"

    # Zweiter Aufruf muss Bearer token enthalten
    second_call = mock_http.post.call_args_list[1]
    assert second_call.kwargs["headers"]["Authorization"] == "Bearer jwt_token_xyz"


def test_liveavatar_session_missing_api_key():
    with patch.dict(os.environ, {"LIVEAVATAR_API_KEY": ""}):
        response = test_client.post("/liveavatar/session")
    assert response.status_code == 500


@patch("main.httpx.AsyncClient")
def test_liveavatar_session_token_error(mock_httpx_class):
    mock_http = AsyncMock()
    mock_http.post.return_value = make_mock_response(401, {"error": "unauthorized"})
    mock_httpx_class.return_value.__aenter__ = AsyncMock(return_value=mock_http)
    mock_httpx_class.return_value.__aexit__ = AsyncMock(return_value=False)

    with patch.dict(os.environ, {"LIVEAVATAR_API_KEY": "bad-key"}):
        response = test_client.post("/liveavatar/session")

    assert response.status_code == 401


@patch("main.httpx.AsyncClient")
def test_liveavatar_session_timeout(mock_httpx_class):
    import httpx as real_httpx
    mock_http = AsyncMock()
    mock_http.post.side_effect = real_httpx.TimeoutException("timeout")
    mock_httpx_class.return_value.__aenter__ = AsyncMock(return_value=mock_http)
    mock_httpx_class.return_value.__aexit__ = AsyncMock(return_value=False)

    response = test_client.post("/liveavatar/session")
    assert response.status_code == 504


# ── /liveavatar/stop ──────────────────────────────────────
@patch("main.httpx.AsyncClient")
def test_liveavatar_stop_success(mock_httpx_class):
    mock_http = AsyncMock()
    mock_http.post.return_value = make_mock_response(200, {"code": 100, "data": None})
    mock_httpx_class.return_value.__aenter__ = AsyncMock(return_value=mock_http)
    mock_httpx_class.return_value.__aexit__ = AsyncMock(return_value=False)

    response = test_client.post("/liveavatar/stop", json={"session_id": "sess_abc"})

    assert response.status_code == 200
    assert response.json() == {"status": "stopped"}

    call_json = mock_http.post.call_args.kwargs["json"]
    assert call_json["session_id"] == "sess_abc"
    assert call_json["reason"] == "USER_CLOSED"


@patch("main.httpx.AsyncClient")
def test_liveavatar_stop_timeout(mock_httpx_class):
    import httpx as real_httpx
    mock_http = AsyncMock()
    mock_http.post.side_effect = real_httpx.TimeoutException("timeout")
    mock_httpx_class.return_value.__aenter__ = AsyncMock(return_value=mock_http)
    mock_httpx_class.return_value.__aexit__ = AsyncMock(return_value=False)

    response = test_client.post("/liveavatar/stop", json={"session_id": "sess_abc"})
    assert response.status_code == 504


# ── Alte Streaming-Endpoints sind entfernt ────────────────
def test_streaming_new_removed():
    response = test_client.post("/streaming/new")
    assert response.status_code in (404, 405)


def test_streaming_task_removed():
    response = test_client.post("/streaming/task", json={"session_id": "x", "text": "y"})
    assert response.status_code in (404, 405)


# ── Prompt-Qualität /chat ──────────────────────────────────

def make_async_stream(texts):
    async def gen():
        for t in texts:
            chunk = MagicMock()
            chunk.text = t
            yield chunk
    return gen()


@patch("main.collection")
@patch("main.client")
def test_chat_uses_kira_persona(mock_client, mock_collection):
    mock_collection.query.return_value = {
        "documents": [["KIT Bewerbungsfrist 15. Juli."]],
        "distances": [[0.3]]
    }
    mock_client.aio.models.generate_content_stream = AsyncMock(
        return_value=make_async_stream(["Die Bewerbungsfrist ist am 15. Juli."])
    )
    mock_client.aio.models.generate_content = AsyncMock(
        return_value=MagicMock(text="Die Bewerbungsfrist ist am fünfzehnten Juli.")
    )

    test_client.post("/chat", json={"message": "Wann ist die Bewerbungsfrist?", "session_id": "test_persona"})

    prompt = mock_client.aio.models.generate_content_stream.call_args.kwargs["contents"]
    assert isinstance(prompt, str) and len(prompt) > 0
    assert "KIRA" in prompt
    assert "Karlsruher Institut für Technologie" in prompt
    # /chat darf KEINE Sprach-Anweisungen enthalten
    assert "vorgelesen" not in prompt
    assert "Sprachausgabe" not in prompt


@patch("main.collection")
@patch("main.client")
def test_chat_context_limit_400(mock_client, mock_collection):
    long_doc = "B" * 500
    mock_collection.query.return_value = {
        "documents": [[long_doc]],
        "distances": [[0.3]]
    }
    mock_client.aio.models.generate_content_stream = AsyncMock(
        return_value=make_async_stream(["Antwort."])
    )
    mock_client.aio.models.generate_content = AsyncMock(return_value=MagicMock(text="Antwort."))

    test_client.post("/chat", json={"message": "Test", "session_id": "test_limit"})

    prompt = mock_client.aio.models.generate_content_stream.call_args.kwargs["contents"]
    assert isinstance(prompt, str) and len(prompt) > 0
    # Harte Zeichen-Trunkierung bei 400
    assert "B" * 400 in prompt
    assert "B" * 401 not in prompt
