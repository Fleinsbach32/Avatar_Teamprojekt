import os
os.environ.setdefault("GOOGLE_API_KEY", "test-key")

import json
import main
from main import app
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


def sse_events(body: str):
    events = []
    for block in body.split("\n\n"):
        line = block.strip()
        if line.startswith("data:"):
            events.append(json.loads(line[len("data:"):]))
    return events


@patch("main.collection")
@patch("main.client")
def test_chat_streams_chunks_then_done(mock_client, mock_collection):
    mock_collection.query.return_value = {
        "documents": [["KIT Bewerbungsfrist 15. Juli."]],
        "distances": [[0.3]]
    }
    mock_client.aio.models.generate_content_stream = AsyncMock(
        return_value=make_async_stream(["Die Frist ", "ist der 15. Juli."])
    )
    # Voice-Antwort hat < 15 Wörter -> garantiert kein Filler, deterministisch
    mock_client.aio.models.generate_content = AsyncMock(
        return_value=MagicMock(text="Die Frist ist der fünfzehnte Juli.")
    )

    response = test_client.post("/chat", json={"message": "Frist?", "session_id": "s_stream1"})

    assert response.status_code == 200
    assert "text/event-stream" in response.headers["content-type"]
    events = sse_events(response.text)
    chunks = [e for e in events if e["type"] == "chunk"]
    dones = [e for e in events if e["type"] == "done"]
    assert [c["text"] for c in chunks] == ["Die Frist ", "ist der 15. Juli."]
    assert len(dones) == 1
    assert dones[0]["voice_text"] == "Die Frist ist der fünfzehnte Juli."
    assert dones[0]["source"] == "Wissensbasis"
    assert isinstance(dones[0]["latency_ms"], int)


@patch("main.collection")
@patch("main.client")
def test_chat_dual_prompts_share_context(mock_client, mock_collection):
    mock_collection.query.return_value = {
        "documents": [["EINDEUTIGER_KONTEXT_42"]],
        "distances": [[0.3]]
    }
    mock_client.aio.models.generate_content_stream = AsyncMock(
        return_value=make_async_stream(["Antwort."])
    )
    mock_client.aio.models.generate_content = AsyncMock(
        return_value=MagicMock(text="Antwort.")
    )

    test_client.post("/chat", json={"message": "Test", "session_id": "s_dual"})

    chat_prompt = mock_client.aio.models.generate_content_stream.call_args.kwargs["contents"]
    voice_prompt = mock_client.aio.models.generate_content.call_args.kwargs["contents"]
    assert "EINDEUTIGER_KONTEXT_42" in chat_prompt
    assert "EINDEUTIGER_KONTEXT_42" in voice_prompt
    assert "vorgelesen" not in chat_prompt
    assert "vorgelesen" in voice_prompt
    # Nur EINE ChromaDB-Abfrage für beide Prompts
    assert mock_collection.query.call_count == 1


@patch("main.VOICE_RETRY_DELAY", 0)
@patch("main.collection")
@patch("main.client")
def test_chat_voice_fallback_on_error(mock_client, mock_collection):
    mock_collection.query.return_value = {"documents": [["Doc"]], "distances": [[0.3]]}
    mock_client.aio.models.generate_content_stream = AsyncMock(
        return_value=make_async_stream(["Chat-Antwort."])
    )
    mock_client.aio.models.generate_content = AsyncMock(side_effect=RuntimeError("boom"))

    response = test_client.post("/chat", json={"message": "Test", "session_id": "s_fallback"})

    events = sse_events(response.text)
    done = next(e for e in events if e["type"] == "done")
    # Voice-Call kaputt -> voice_text fällt auf Chat-Antwort zurück
    assert done["voice_text"] == "Chat-Antwort."


@patch("main.collection")
@patch("main.client")
def test_chat_error_event_on_stream_failure(mock_client, mock_collection):
    mock_collection.query.return_value = {"documents": [["Doc"]], "distances": [[0.3]]}
    mock_client.aio.models.generate_content_stream = AsyncMock(side_effect=RuntimeError("boom"))
    mock_client.aio.models.generate_content = AsyncMock(return_value=MagicMock(text="Voice."))

    response = test_client.post("/chat", json={"message": "Test", "session_id": "s_err"})

    events = sse_events(response.text)
    assert any(e["type"] == "error" for e in events)
    assert not any(e["type"] == "done" for e in events)


@patch("main.collection")
@patch("main.client")
def test_chat_history_stored(mock_client, mock_collection):
    mock_collection.query.return_value = {"documents": [["Doc"]], "distances": [[0.3]]}
    mock_client.aio.models.generate_content_stream = AsyncMock(
        return_value=make_async_stream(["Antwort A."])
    )
    mock_client.aio.models.generate_content = AsyncMock(return_value=MagicMock(text="Antwort A."))

    test_client.post("/chat", json={"message": "Frage A", "session_id": "s_hist"})

    history = main.sessions["s_hist"]
    assert {"role": "Du", "content": "Frage A"} in history
    assert any(m["role"] == "Bot" and "Antwort A." in m["content"] for m in history)
