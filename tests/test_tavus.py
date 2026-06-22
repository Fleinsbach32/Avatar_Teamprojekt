import os
os.environ.setdefault("GOOGLE_API_KEY", "test-key")
os.environ.setdefault("TAVUS_API_KEY", "test-tavus-key")
os.environ.setdefault("TAVUS_REPLICA_ID", "test-replica-id")

from app.main import app
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


def make_failing_stream(texts, exc):
    async def gen():
        for t in texts:
            chunk = MagicMock()
            chunk.text = t
            yield chunk
        raise exc
    return gen()


@patch("app.routes.tavus._http")
def test_tavus_session_success(mock_http):
    mock_http.post = AsyncMock(return_value=make_mock_response(200, {
        "conversation_id": "conv_abc123",
        "conversation_url": "https://tavus.daily.co/abc123"
    }))
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
    assert call_kwargs["json"]["custom_greeting"] == ""


def test_tavus_session_missing_api_key():
    with patch.dict(os.environ, {"TAVUS_API_KEY": ""}):
        response = test_client.post("/tavus/session")
    assert response.status_code == 500


@patch("app.routes.tavus._http")
def test_tavus_session_api_error(mock_http):
    mock_http.post = AsyncMock(return_value=make_mock_response(401, {"error": "unauthorized"}))
    with patch.dict(os.environ, {"TAVUS_API_KEY": "bad-key"}):
        response = test_client.post("/tavus/session")
    assert response.status_code == 401


@patch("app.routes.tavus._http")
def test_tavus_session_timeout(mock_http):
    import httpx as real_httpx
    mock_http.post = AsyncMock(side_effect=real_httpx.TimeoutException("timeout"))
    response = test_client.post("/tavus/session")
    assert response.status_code == 504


@patch("app.routes.tavus._http")
def test_tavus_end_success(mock_http):
    mock_http.delete = AsyncMock(return_value=make_mock_response(200, {}))
    response = test_client.post("/tavus/end", json={"conversation_id": "conv_abc123"})
    assert response.status_code == 200
    assert response.json() == {"status": "ended"}
    call_url = mock_http.delete.call_args.args[0]
    assert "conv_abc123" in call_url


@patch("app.rag.collection")
@patch("app.routes.tavus.client")
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
    import json as j
    deltas = [
        j.loads(line[5:])["choices"][0]["delta"].get("content")
        for line in body.split("\n\n")
        if line.strip().startswith("data:") and "[DONE]" not in line
    ]
    assert "Prüfungen meldest du " in deltas
    assert "über campus.kit.edu an." in deltas
    assert response.headers["cache-control"] == "no-cache"
    assert response.headers["x-accel-buffering"] == "no"


@patch("app.rag.collection")
@patch("app.routes.tavus.client")
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
    assert "Was ist die Bewerbungsfrist?" in prompt
    assert "Die Frist ist der fünfzehnte Juli." in prompt
    assert prompt.rstrip().endswith("Und wo reiche ich das ein?")


@patch("app.routes.tavus.VOICE_RETRY_DELAY", 0)
@patch("app.rag.collection")
@patch("app.routes.tavus.client")
def test_tavus_llm_fallback_after_failures(mock_client, mock_collection):
    mock_collection.query.return_value = {"documents": [["Doc"]], "distances": [[0.3]]}
    mock_client.aio.models.generate_content_stream = AsyncMock(side_effect=RuntimeError("boom"))
    response = test_client.post("/tavus/llm", json={
        "messages": [{"role": "user", "content": "Test"}],
        "stream": True
    })
    body = response.text
    assert "Service momentan nicht verf" in body
    assert "[DONE]" in body
    assert mock_client.aio.models.generate_content_stream.call_count == 3


@patch("app.routes.tavus.VOICE_RETRY_DELAY", 0)
@patch("app.rag.collection")
@patch("app.routes.tavus.client")
def test_tavus_llm_no_retry_after_first_chunk(mock_client, mock_collection):
    mock_collection.query.return_value = {"documents": [["Doc"]], "distances": [[0.3]]}
    mock_client.aio.models.generate_content_stream = AsyncMock(
        side_effect=lambda **kwargs: make_failing_stream(["Teil eins"], RuntimeError("boom"))
    )
    response = test_client.post("/tavus/llm", json={
        "messages": [{"role": "user", "content": "Test"}],
        "stream": True
    })
    assert mock_client.aio.models.generate_content_stream.call_count == 1
    assert response.text.count("Teil eins") == 1
    assert "[DONE]" in response.text


@patch("app.routes.tavus._http")
def test_tavus_message_success(mock_http):
    mock_http.post = AsyncMock(return_value=make_mock_response(200, {}))
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


@patch("app.routes.tavus._http")
def test_tavus_message_timeout(mock_http):
    import httpx as real_httpx
    mock_http.post = AsyncMock(side_effect=real_httpx.TimeoutException("timeout"))
    response = test_client.post("/tavus/message", json={
        "conversation_id": "conv_abc123",
        "message": "Hallo"
    })
    assert response.status_code == 504


@patch("app.rag.collection")
@patch("app.routes.tavus.client")
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
    assert "vorlesen" in prompt.lower() or "vorgelesen" in prompt.lower()


@patch("app.rag.collection")
@patch("app.routes.tavus.client")
def test_tavus_llm_context_limit_600(mock_client, mock_collection):
    long_doc = "A" * 700
    mock_collection.query.return_value = {"documents": [[long_doc]], "distances": [[0.3]]}
    mock_client.aio.models.generate_content_stream = AsyncMock(
        return_value=make_async_stream(["Antwort."])
    )
    test_client.post("/tavus/llm", json={
        "messages": [{"role": "user", "content": "Test"}],
        "stream": True
    })
    prompt = mock_client.aio.models.generate_content_stream.call_args.kwargs["contents"]
    assert "A" * 600 in prompt
    assert "A" * 601 not in prompt


# ── Voice-Prefs: /tavus/settings + Wirkung auf /tavus/llm ──
def _reset_voice_prefs():
    test_client.post("/tavus/settings", json={"lang": "de", "studiengang": None})


def test_tavus_settings_updates_prefs():
    r = test_client.post("/tavus/settings", json={"lang": "en", "studiengang": "wima_msc"})
    assert r.status_code == 200
    data = r.json()
    assert data["lang"] == "en"
    assert data["studiengang"] == "wima_msc"
    _reset_voice_prefs()


@patch("app.rag.collection")
@patch("app.routes.tavus.client")
def test_tavus_llm_uses_voice_prefs(mock_client, mock_collection):
    mock_collection.query.return_value = {"documents": [["Doc"]], "distances": [[0.3]]}
    mock_client.aio.models.generate_content_stream = AsyncMock(
        return_value=make_async_stream(["Answer."])
    )
    # Frontend setzt Sprache + Studiengang vor dem Tavus-LLM-Aufruf
    test_client.post("/tavus/settings", json={"lang": "en", "studiengang": "winfo_bsc"})
    test_client.post("/tavus/llm", json={
        "messages": [{"role": "user", "content": "Test"}],
        "stream": True
    })
    # Zweistufige RAG-Suche: zwei separate Queries statt einer $or-Query
    all_calls = mock_collection.query.call_args_list
    where_filters = [c.kwargs.get("where") for c in all_calls]
    assert {"program": "winfo_bsc"} in where_filters
    assert {"program": "all"} in where_filters
    # Englischer Voice-Prompt aus den Prefs
    prompt = mock_client.aio.models.generate_content_stream.call_args.kwargs["contents"]
    assert "English" in prompt or "english" in prompt.lower()
    _reset_voice_prefs()


@patch("app.rag.collection")
@patch("app.routes.tavus.client")
def test_chat_completions_alias(mock_client, mock_collection):
    """Tavus' OpenAI-Client ruft /chat/completions (an die ngrok-Root) auf."""
    mock_collection.query.return_value = {"documents": [["Doc"]], "distances": [[0.3]]}
    mock_client.aio.models.generate_content_stream = AsyncMock(
        return_value=make_async_stream(["Hi."])
    )
    response = test_client.post("/chat/completions", json={
        "messages": [{"role": "user", "content": "Test"}],
        "stream": True
    })
    assert response.status_code == 200
    assert "[DONE]" in response.text
    _reset_voice_prefs()


def test_avatar_config_returns_tavus():
    response = test_client.get("/avatar/config")
    assert response.status_code == 200
    assert response.json() == {"provider": "tavus"}
