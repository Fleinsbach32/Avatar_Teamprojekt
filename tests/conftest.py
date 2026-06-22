import sys
from unittest.mock import MagicMock

_mock_cross_encoder_instance = MagicMock()
_mock_cross_encoder_instance.predict.side_effect = lambda pairs: [1.0 - i * 0.01 for i in range(len(pairs))]
_mock_st = MagicMock()
_mock_st.CrossEncoder.return_value = _mock_cross_encoder_instance

sys.modules.update({
    'chromadb': MagicMock(),
    'chromadb.utils': MagicMock(),
    'chromadb.utils.embedding_functions': MagicMock(),
    'google': MagicMock(),
    'google.genai': MagicMock(),
    'google.genai.types': MagicMock(),
    'sentence_transformers': _mock_st,
    'torch': MagicMock(),
})
