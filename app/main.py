import logging
from contextlib import asynccontextmanager

from dotenv import load_dotenv
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse

load_dotenv()

from app.gemini import client, gemini_config
from app.rag import collection, reranker
from app.routes import avatar, chat, tavus


@asynccontextmanager
async def lifespan(app: FastAPI):
    try:
        collection.query(query_texts=["Warmup"], n_results=1)
    except Exception as e:
        logging.warning(f"ChromaDB Warmup fehlgeschlagen: {e}")
    if reranker is not None:
        try:
            reranker.predict([("Warmup", "Warmup")])
        except Exception as e:
            logging.warning(f"Reranker Warmup fehlgeschlagen: {e}")
    try:
        await client.aio.models.generate_content(
            model="gemini-2.5-flash",
            contents="Warmup",
            config=gemini_config(1),
        )
    except Exception as e:
        logging.warning(f"Gemini Warmup fehlgeschlagen: {e}")
    yield
    await tavus._http.aclose()


app = FastAPI(lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(avatar.router)
app.include_router(chat.router)
app.include_router(tavus.router)


@app.get("/health")
def health():
    return {"status": "ok"}


@app.get("/")
async def serve_index():
    return FileResponse("static/index.html")
