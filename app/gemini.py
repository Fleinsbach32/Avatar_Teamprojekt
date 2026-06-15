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
