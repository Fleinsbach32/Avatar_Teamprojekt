import asyncio
import logging
import os
from google import genai
from google.genai import types

client = genai.Client(api_key=os.getenv("GOOGLE_API_KEY"))

SSE_HEADERS = {"Cache-Control": "no-cache", "X-Accel-Buffering": "no"}

# Primärmodell; bei Überlastung (503 UNAVAILABLE) weicht der letzte Versuch auf
# das schlankere, seltener überlastete Fallback-Modell aus.
PRIMARY_MODEL = "gemini-2.5-flash"
FALLBACK_MODEL = "gemini-2.5-flash-lite"


def gemini_config(max_tokens: int) -> types.GenerateContentConfig:
    return types.GenerateContentConfig(
        temperature=0.2,
        max_output_tokens=max_tokens,
        thinking_config=types.ThinkingConfig(thinking_budget=0),
    )


class GeminiUnavailable(Exception):
    """Alle Versuche scheiterten, bevor ein Chunk gesendet wurde."""


class GeminiMidStreamError(Exception):
    """Der Stream brach ab, nachdem bereits Chunks gesendet wurden (kein Retry)."""


async def stream_gemini(prompt: str, max_tokens: int, retry_delay: float, attempts: int = 3):
    """Async-Generator: liefert Text-Chunks von Gemini.

    Retry nur VOR dem ersten Chunk (bis zu `attempts` Versuche) mit exponentiellem
    Backoff (`retry_delay`, dann ×2, ×4 …). Der letzte Versuch nutzt das Fallback-
    Modell, falls das Primärmodell überlastet ist (503 UNAVAILABLE).
    - Scheitert es vor dem ersten Chunk endgültig → raise GeminiUnavailable.
    - Scheitert es nach bereits gesendeten Chunks → raise GeminiMidStreamError (kein Retry).
    """
    gesendet = False
    for versuch in range(attempts):
        # Letzter Versuch weicht auf das Fallback-Modell aus.
        model = FALLBACK_MODEL if versuch == attempts - 1 else PRIMARY_MODEL
        try:
            stream = await client.aio.models.generate_content_stream(
                model=model,
                contents=prompt,
                config=gemini_config(max_tokens),
            )
            async for chunk in stream:
                if chunk.text:
                    gesendet = True
                    yield chunk.text
            return
        except Exception as e:
            logging.warning(f"Gemini Stream Fehler (Modell {model}, Versuch {versuch + 1}): {e}")
            if gesendet:
                raise GeminiMidStreamError() from e
            if versuch < attempts - 1:
                await asyncio.sleep(retry_delay * (2 ** versuch))
    raise GeminiUnavailable()
