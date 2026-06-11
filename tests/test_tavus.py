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


def make_async_stream(texts):
    async def gen():
        for t in texts:
            chunk = MagicMock()
            chunk.text = t
            yield chunk
    return gen()


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
        "TAVUS_PERSONA_ID": ""
    }):
        response = test_client.post("/tavus/session")

    assert response.status_code == 200
    data = response.json()
    assert data["conversation_id"] == "conv_abc123"
    assert data["conversation_url"] == "https://tavus.daily.co/abc123"

    call_kwargs = mock_http.post.call_args.kwargs
    assert call_kwargs["headers"]["x-api-key"] == "real-key"
    assert call_kwargs["json"]["replica_id"] == "replica_xyz"
    # Tavus-Standardbegrüßung unterdrücken — die verzögerte Begrüßung kommt vom Frontend
    assert call_kwargs["json"]["custom_greeting"] == ""


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
def test_tavus_llm_streams_chunks(mock_client, mock_collection):
    mock_collection.query.return_value = {
        "documents": [["KIT Prüfungsanmeldung erfolgt über das Campus-Portal."]],
        "distances": [[0.3]]
    }
    mock_client.aio.models.generate_content_stream = AsyncMock(
        return_value=make_async_stream(["Prüfungen meldest du ", "über campus.kit.edu an."])
    )

    response = test_client.post("/tavus/llm", json={
        "messages": [{"role": "user", "content": "Wie melde ich mich für Prüfungen an?"}],
        "stream": True
    })

    assert response.status_code == 200
    assert "text/event-stream" in response.headers.get("content-type", "")
    body = response.text
    assert "[DONE]" in body
    assert "campus.kit.edu" in body
    # Echtes Streaming: zwei getrennte content-Deltas
    import json as j
    deltas = [
        j.loads(line[5:])["choices"][0]["delta"].get("content")
        for line in body.split("\n\n")
        if line.strip().startswith("data:") and "[DONE]" not in line
    ]
    assert "Prüfungen meldest du " in deltas
    assert "über campus.kit.edu an." in deltas
    # Anti-Proxy-Buffering-Header für SSE
    assert response.headers["cache-control"] == "no-cache"
    assert response.headers["x-accel-buffering"] == "no"


def make_failing_stream(texts, exc):
    async def gen():
        for t in texts:
            chunk = MagicMock()
            chunk.text = t
            yield chunk
        raise exc
    return gen()


@patch("main.collection")
@patch("main.client")
def test_tavus_llm_includes_conversation_history(mock_client, mock_collection):
    mock_collection.query.return_value = {"documents": [["Doc"]], "distances": [[0.3]]}
    mock_client.aio.models.generate_content_stream = AsyncMock(
        return_value=make_async_stream(["Antwort."])
    )

    test_client.post("/tavus/llm", json={
        "messages": [
            {"role": "user", "content": "Was ist die Bewerbungsfrist?"},
            {"role": "assistant", "content": "Die Frist ist der fünfzehnte Juli."},
            {"role": "user", "content": "Und wo reiche ich das ein?"}
        ],
        "stream": True
    })

    prompt = mock_client.aio.models.generate_content_stream.call_args.kwargs["contents"]
    # Vorherige Gesprächszüge müssen im Prompt stehen
    assert "Was ist die Bewerbungsfrist?" in prompt
    assert "Die Frist ist der fünfzehnte Juli." in prompt
    # Die aktuelle Frage steht am Ende
    assert prompt.rstrip().endswith("Und wo reiche ich das ein?")


@patch("main.VOICE_RETRY_DELAY", 0)
@patch("main.collection")
@patch("main.client")
def test_tavus_llm_fallback_after_failures(mock_client, mock_collection):
    mock_collection.query.return_value = {"documents": [["Doc"]], "distances": [[0.3]]}
    mock_client.aio.models.generate_content_stream = AsyncMock(side_effect=RuntimeError("boom"))

    response = test_client.post("/tavus/llm", json={
        "messages": [{"role": "user", "content": "Test"}],
        "stream": True
    })

    body = response.text
    # json.dumps escapt Umlaute, daher Teilstring ohne Umlaut prüfen
    assert "Service momentan nicht verf" in body
    assert "[DONE]" in body
    # Genau 3 Versuche
    assert mock_client.aio.models.generate_content_stream.call_count == 3


@patch("main.VOICE_RETRY_DELAY", 0)
@patch("main.collection")
@patch("main.client")
def test_tavus_llm_no_retry_after_first_chunk(mock_client, mock_collection):
    mock_collection.query.return_value = {"documents": [["Doc"]], "distances": [[0.3]]}
    mock_client.aio.models.generate_content_stream = AsyncMock(
        side_effect=lambda **kwargs: make_failing_stream(["Teil eins"], RuntimeError("boom"))
    )

    response = test_client.post("/tavus/llm", json={
        "messages": [{"role": "user", "content": "Test"}],
        "stream": True
    })

    # Mitten im Stream abgebrochen: KEIN Retry (sonst doppelter gesprochener Text)
    assert mock_client.aio.models.generate_content_stream.call_count == 1
    assert response.text.count("Teil eins") == 1
    assert "[DONE]" in response.text


# ── /tavus/message ────────────────────────────────────────
@patch("main.httpx.AsyncClient")
def test_tavus_message_success(mock_httpx_class):
    mock_http = AsyncMock()
    mock_http.post.return_value = make_mock_response(200, {})
    mock_httpx_class.return_value.__aenter__ = AsyncMock(return_value=mock_http)
    mock_httpx_class.return_value.__aexit__ = AsyncMock(return_value=False)

    with patch.dict(os.environ, {"TAVUS_API_KEY": "real-key"}):
        response = test_client.post("/tavus/message", json={
            "conversation_id": "conv_abc123",
            "message": "Wie melde ich mich für Prüfungen an?"
        })

    assert response.status_code == 200
    assert response.json() == {"status": "sent"}

    call_args = mock_http.post.call_args
    assert "conv_abc123" in call_args.args[0]
    assert call_args.kwargs["json"]["message"] == "Wie melde ich mich für Prüfungen an?"
    assert call_args.kwargs["headers"]["x-api-key"] == "real-key"


def test_tavus_message_empty_message():
    response = test_client.post("/tavus/message", json={
        "conversation_id": "conv_abc123",
        "message": "   "
    })
    assert response.status_code == 422


def test_tavus_message_missing_api_key():
    with patch.dict(os.environ, {"TAVUS_API_KEY": ""}):
        response = test_client.post("/tavus/message", json={
            "conversation_id": "conv_abc123",
            "message": "Hallo"
        })
    assert response.status_code == 500


@patch("main.httpx.AsyncClient")
def test_tavus_message_api_error(mock_httpx_class):
    mock_http = AsyncMock()
    mock_http.post.return_value = make_mock_response(404, {"error": "conversation not found"})
    mock_httpx_class.return_value.__aenter__ = AsyncMock(return_value=mock_http)
    mock_httpx_class.return_value.__aexit__ = AsyncMock(return_value=False)

    with patch.dict(os.environ, {"TAVUS_API_KEY": "real-key"}):
        response = test_client.post("/tavus/message", json={
            "conversation_id": "nonexistent",
            "message": "Hallo"
        })

    assert response.status_code == 404


@patch("main.httpx.AsyncClient")
def test_tavus_message_timeout(mock_httpx_class):
    import httpx as real_httpx
    mock_http = AsyncMock()
    mock_http.post.side_effect = real_httpx.TimeoutException("timeout")
    mock_httpx_class.return_value.__aenter__ = AsyncMock(return_value=mock_http)
    mock_httpx_class.return_value.__aexit__ = AsyncMock(return_value=False)

    response = test_client.post("/tavus/message", json={
        "conversation_id": "conv_abc123",
        "message": "Hallo"
    })
    assert response.status_code == 504


# ── Prompt-Qualität ────────────────────────────────────────
@patch("main.collection")
@patch("main.client")
def test_tavus_llm_uses_kira_persona(mock_client, mock_collection):
    mock_collection.query.return_value = {
        "documents": [["KIT Prüfungsanmeldung über das Campus-Portal."]],
        "distances": [[0.3]]
    }
    mock_client.aio.models.generate_content_stream = AsyncMock(
        return_value=make_async_stream(["Prüfungen meldest du über campus.kit.edu an."])
    )

    test_client.post("/tavus/llm", json={
        "messages": [{"role": "user", "content": "Wie melde ich Prüfungen an?"}],
        "stream": True
    })

    prompt = mock_client.aio.models.generate_content_stream.call_args.kwargs["contents"]
    assert isinstance(prompt, str) and len(prompt) > 0
    assert "KIRA" in prompt
    assert "Karlsruher Institut für Technologie" in prompt
    assert "vorgelesen" in prompt


@patch("main.collection")
@patch("main.client")
def test_tavus_llm_context_limit_400(mock_client, mock_collection):
    long_doc = "A" * 500
    mock_collection.query.return_value = {
        "documents": [[long_doc]],
        "distances": [[0.3]]
    }
    mock_client.aio.models.generate_content_stream = AsyncMock(
        return_value=make_async_stream(["Antwort."])
    )

    test_client.post("/tavus/llm", json={
        "messages": [{"role": "user", "content": "Test"}],
        "stream": True
    })

    prompt = mock_client.aio.models.generate_content_stream.call_args.kwargs["contents"]
    assert "A" * 400 in prompt
    assert "A" * 401 not in prompt
