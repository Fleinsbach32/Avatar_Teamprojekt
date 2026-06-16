import os
os.environ.setdefault("GOOGLE_API_KEY", "test-key")

from app.main import app
from app.auth import check_auth
from fastapi.testclient import TestClient
from unittest.mock import patch, MagicMock, AsyncMock

client = TestClient(app)


def _make_stream(texts):
    async def gen():
        for t in texts:
            c = MagicMock()
            c.text = t
            yield c
    return gen()


def test_protected_endpoint_requires_auth():
    # echte Auth aktivieren (autouse-Override aus conftest entfernen)
    app.dependency_overrides.pop(check_auth, None)
    assert client.get("/avatar/config").status_code == 401
    assert client.post("/tavus/session").status_code == 401


def test_health_open_without_auth():
    app.dependency_overrides.pop(check_auth, None)
    assert client.get("/health").status_code == 200


@patch("app.rag.collection")
@patch("app.routes.tavus.client")
def test_llm_endpoints_open_without_auth(mock_client, mock_collection):
    # /chat/completions wird von Tavus serverseitig ohne Credentials aufgerufen
    # und MUSS ohne Auth funktionieren.
    app.dependency_overrides.pop(check_auth, None)
    mock_collection.query.return_value = {"documents": [["Doc"]], "distances": [[0.3]]}
    mock_client.aio.models.generate_content_stream = AsyncMock(return_value=_make_stream(["Hi."]))
    r = client.post("/chat/completions", json={"messages": [{"role": "user", "content": "Test"}], "stream": True})
    assert r.status_code == 200
    assert "[DONE]" in r.text


def test_correct_credentials_accepted():
    app.dependency_overrides.pop(check_auth, None)
    with patch.dict(os.environ, {"APP_USERNAME": "admin", "APP_PASSWORD": "geheim"}):
        r = client.get("/avatar/config", auth=("admin", "geheim"))
    assert r.status_code == 200
    assert r.json() == {"provider": "tavus"}
