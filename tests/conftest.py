import sys
from unittest.mock import MagicMock

import pytest

sys.modules.update({
    'chromadb': MagicMock(),
    'chromadb.utils': MagicMock(),
    'chromadb.utils.embedding_functions': MagicMock(),
    'google': MagicMock(),
    'google.genai': MagicMock(),
    'google.genai.types': MagicMock(),
    'sentence_transformers': MagicMock(),
    'torch': MagicMock(),
})


@pytest.fixture(autouse=True)
def _bypass_basic_auth():
    """HTTP-Basic-Auth in Tests umgehen (die Endpoints sind sonst passwortgeschützt).
    Greift nur, wenn app.main importierbar ist; pure Funktionstests ignorieren es."""
    try:
        from app.main import app
        from app.auth import check_auth
    except Exception:
        yield
        return
    app.dependency_overrides[check_auth] = lambda: "test-user"
    yield
    app.dependency_overrides.pop(check_auth, None)
