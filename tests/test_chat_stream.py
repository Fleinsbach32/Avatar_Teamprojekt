import os
os.environ.setdefault("GOOGLE_API_KEY", "test-key")

import json
from app.main import app
from app.session import sessions
from fastapi.testclient import TestClient
from unittest.mock import patch, MagicMock, AsyncMock

test_client = TestClient(app)


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


def sse_events(body: str):
    events = []
    for block in body.split("\n\n"):
        line = block.strip()
        if line.startswith("data:"):
            events.append(json.loads(line[len("data:"):]))
    return events


@patch("app.rag.collection")
@patch("app.routes.chat.client")
def test_chat_streams_chunks_then_done(mock_client, mock_collection):
    mock_collection.query.return_value = {
        "documents": [["KIT Bewerbungsfrist 15. Juli."]],
        "distances": [[0.3]]
    }
    mock_client.aio.models.generate_content_stream = AsyncMock(
        return_value=make_async_stream(["Die Frist ", "ist der fünfzehnte Juli."])
    )
    mock_client.aio.models.generate_content = AsyncMock()

    response = test_client.post("/chat", json={"message": "Frist?", "session_id": "s_uni1"})

    assert response.status_code == 200
    assert "text/event-stream" in response.headers["content-type"]
    events = sse_events(response.text)
    chunks = [e for e in events if e["type"] == "chunk"]
    dones  = [e for e in events if e["type"] == "done"]
    assert [c["text"] for c in chunks] == ["Die Frist ", "ist der fünfzehnte Juli."]
    assert len(dones) == 1
    assert dones[0]["voice_text"] == "Die Frist ist der fünfzehnte Juli."
    assert dones[0]["source"] == "Wissensbasis"
    assert isinstance(dones[0]["latency_ms"], int)
    assert mock_client.aio.models.generate_content.call_count == 0


@patch("app.rag.collection")
@patch("app.routes.chat.client")
def test_chat_single_call_with_context(mock_client, mock_collection):
    mock_collection.query.return_value = {
        "documents": [["EINDEUTIGER_KONTEXT_42"]],
        "distances": [[0.3]]
    }
    mock_client.aio.models.generate_content_stream = AsyncMock(
        return_value=make_async_stream(["Antwort."])
    )
    mock_client.aio.models.generate_content = AsyncMock()

    test_client.post("/chat", json={"message": "Test", "session_id": "s_single"})

    prompt = mock_client.aio.models.generate_content_stream.call_args.kwargs["contents"]
    assert "EINDEUTIGER_KONTEXT_42" in prompt
    assert mock_client.aio.models.generate_content.call_count == 0
    assert mock_collection.query.call_count == 1


@patch("app.routes.chat.CHAT_RETRY_DELAY", 0)
@patch("app.rag.collection")
@patch("app.routes.chat.client")
def test_chat_error_event_on_stream_failure(mock_client, mock_collection):
    mock_collection.query.return_value = {"documents": [["Doc"]], "distances": [[0.3]]}
    mock_client.aio.models.generate_content_stream = AsyncMock(side_effect=RuntimeError("boom"))

    response = test_client.post("/chat", json={"message": "Test", "session_id": "s_err2"})

    events = sse_events(response.text)
    assert any(e["type"] == "error" for e in events)
    assert not any(e["type"] == "done" for e in events)
    assert mock_client.aio.models.generate_content_stream.call_count == 3


@patch("app.routes.chat.CHAT_RETRY_DELAY", 0)
@patch("app.rag.collection")
@patch("app.routes.chat.client")
def test_chat_retries_then_succeeds(mock_client, mock_collection):
    mock_collection.query.return_value = {"documents": [["Doc"]], "distances": [[0.3]]}
    mock_client.aio.models.generate_content_stream = AsyncMock(
        side_effect=[RuntimeError("boom"), make_async_stream(["Erfolg."])]
    )

    response = test_client.post("/chat", json={"message": "Test", "session_id": "s_retry"})

    events = sse_events(response.text)
    assert any(e["type"] == "done" for e in events)
    assert mock_client.aio.models.generate_content_stream.call_count == 2


@patch("app.rag.collection")
@patch("app.routes.chat.client")
def test_chat_history_stored(mock_client, mock_collection):
    mock_collection.query.return_value = {"documents": [["Doc"]], "distances": [[0.3]]}
    mock_client.aio.models.generate_content_stream = AsyncMock(
        return_value=make_async_stream(["Antwort A."])
    )

    test_client.post("/chat", json={"message": "Frage A", "session_id": "s_hist2"})

    history = sessions["s_hist2"]
    assert {"role": "Du", "content": "Frage A"} in history
    assert any(m["role"] == "Bot" and "Antwort A." in m["content"] for m in history)


@patch("app.rag.collection")
@patch("app.routes.chat.client")
def test_chat_second_request_varies_opening(mock_client, mock_collection):
    mock_collection.query.return_value = {"documents": [["Doc"]], "distances": [[0.3]]}
    mock_client.aio.models.generate_content_stream = AsyncMock(
        side_effect=lambda **kwargs: make_async_stream(["Genau, das ist richtig."])
    )

    test_client.post("/chat", json={"message": "Frage eins", "session_id": "s_vary2"})
    test_client.post("/chat", json={"message": "Frage zwei", "session_id": "s_vary2"})

    prompt_2 = mock_client.aio.models.generate_content_stream.call_args.kwargs["contents"]
    assert 'Beginne deine Antwort nicht mit dem Wort "Genau"' in prompt_2


@patch("app.rag.collection")
@patch("app.routes.chat.client")
def test_chat_sse_headers_prevent_proxy_buffering(mock_client, mock_collection):
    mock_collection.query.return_value = {"documents": [["Doc"]], "distances": [[0.3]]}
    mock_client.aio.models.generate_content_stream = AsyncMock(
        return_value=make_async_stream(["Hi."])
    )

    response = test_client.post("/chat", json={"message": "Test", "session_id": "s_hdr"})

    assert response.headers["cache-control"] == "no-cache"
    assert response.headers["x-accel-buffering"] == "no"


@patch("app.rag.collection")
@patch("app.routes.chat.client")
def test_chat_midstream_failure_no_done_no_history(mock_client, mock_collection):
    mock_collection.query.return_value = {"documents": [["Doc"]], "distances": [[0.3]]}
    mock_client.aio.models.generate_content_stream = AsyncMock(
        return_value=make_failing_stream(["Teil eins "], RuntimeError("boom"))
    )

    response = test_client.post("/chat", json={"message": "Test", "session_id": "s_mid"})

    events = sse_events(response.text)
    assert any(e["type"] == "chunk" for e in events)
    assert any(e["type"] == "error" for e in events)
    assert not any(e["type"] == "done" for e in events)
    assert sessions.get("s_mid", []) == []


@patch("app.rag.collection")
@patch("app.routes.chat.client")
def test_chat_lang_en_uses_english_prompt(mock_client, mock_collection):
    mock_collection.query.return_value = {"documents": [["Doc"]], "distances": [[0.3]]}
    mock_client.aio.models.generate_content_stream = AsyncMock(
        return_value=make_async_stream(["Answer."])
    )

    test_client.post("/chat", json={"message": "Test", "session_id": "s_en", "lang": "en"})

    prompt = mock_client.aio.models.generate_content_stream.call_args.kwargs["contents"]
    assert "English" in prompt or "english" in prompt.lower()


@patch("app.rag.collection")
@patch("app.routes.chat.client")
def test_chat_studiengang_passes_filter_to_rag(mock_client, mock_collection):
    mock_collection.query.return_value = {"documents": [["Doc"]], "distances": [[0.3]]}
    mock_client.aio.models.generate_content_stream = AsyncMock(
        return_value=make_async_stream(["Antwort."])
    )

    test_client.post("/chat", json={
        "message": "Was muss ich im WINFO BSc belegen?",
        "session_id": "s_sg",
        "studiengang": "winfo_bsc"
    })

    # Zweistufige RAG-Suche: zwei separate Queries statt einer $or-Query
    all_calls = mock_collection.query.call_args_list
    where_filters = [c.kwargs.get("where") for c in all_calls]
    assert {"program": "winfo_bsc"} in where_filters
    assert {"program": "all"} in where_filters


@patch("app.rag.collection")
@patch("app.routes.chat.client")
def test_chat_uses_kira_persona(mock_client, mock_collection):
    mock_collection.query.return_value = {
        "documents": [["KIT Bewerbungsfrist 15. Juli."]],
        "distances": [[0.3]]
    }
    mock_client.aio.models.generate_content_stream = AsyncMock(
        return_value=make_async_stream(["Die Bewerbungsfrist ist am fünfzehnten Juli."])
    )

    test_client.post("/chat", json={"message": "Wann ist die Bewerbungsfrist?", "session_id": "test_persona2"})

    prompt = mock_client.aio.models.generate_content_stream.call_args.kwargs["contents"]
    assert "KIRA" in prompt
    assert "Karlsruher Institut für Technologie" in prompt


@patch("app.rag.collection")
@patch("app.routes.chat.client")
def test_chat_context_limit_600(mock_client, mock_collection):
    long_doc = "B" * 700
    mock_collection.query.return_value = {"documents": [[long_doc]], "distances": [[0.3]]}
    mock_client.aio.models.generate_content_stream = AsyncMock(
        return_value=make_async_stream(["Antwort."])
    )

    test_client.post("/chat", json={"message": "Test", "session_id": "test_limit"})

    prompt = mock_client.aio.models.generate_content_stream.call_args.kwargs["contents"]
    assert "B" * 600 in prompt
    assert "B" * 601 not in prompt
