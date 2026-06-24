import asyncio
import logging
import os
from google import genai
from google.genai import types

client = genai.Client(api_key=os.getenv("GOOGLE_API_KEY"))

SSE_HEADERS = {"Cache-Control": "no-cache", "X-Accel-Buffering": "no"}


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

    Retry nur VOR dem ersten Chunk (bis zu `attempts` Versuche, `retry_delay` s Pause).
    - Scheitert es vor dem ersten Chunk endgültig → raise GeminiUnavailable.
    - Scheitert es nach bereits gesendeten Chunks → raise GeminiMidStreamError (kein Retry).
    """
    gesendet = False
    for versuch in range(attempts):
        try:
            stream = await client.aio.models.generate_content_stream(
                model="gemini-2.5-flash",
                contents=prompt,
                config=gemini_config(max_tokens),
            )
            async for chunk in stream:
                if chunk.text:
                    gesendet = True
                    yield chunk.text
            return
        except Exception as e:
            logging.warning(f"Gemini Stream Fehler (Versuch {versuch + 1}): {e}")
            if gesendet:
                raise GeminiMidStreamError() from e
            if versuch < attempts - 1:
                await asyncio.sleep(retry_delay)
    raise GeminiUnavailable()
