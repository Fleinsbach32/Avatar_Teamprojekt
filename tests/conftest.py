import sys
from unittest.mock import MagicMock

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
