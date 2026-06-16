import logging
from contextlib import asynccontextmanager

from dotenv import load_dotenv
from fastapi import Depends, FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse

load_dotenv()

from app.auth import check_auth
from app.rag import collection
from app.routes import avatar, chat, tavus


@asynccontextmanager
async def lifespan(app: FastAPI):
    try:
        collection.query(query_texts=["Warmup"], n_results=1)
    except Exception as e:
        logging.warning(f"ChromaDB Warmup fehlgeschlagen: {e}")
    yield


app = FastAPI(lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# Browser-Endpoints sind passwortgeschützt. Die Tavus-LLM-Endpoints
# (/tavus/llm, /tavus/llm/chat/completions, /chat/completions) sind bewusst
# NICHT geschützt — Tavus ruft sie serverseitig ohne Credentials auf. Die Auth
# auf diese Routen würde den gesprochenen Avatar-Pfad mit 401 abbrechen.
app.include_router(avatar.router, dependencies=[Depends(check_auth)])
app.include_router(chat.router, dependencies=[Depends(check_auth)])
app.include_router(tavus.router)  # Auth pro Route in app/routes/tavus.py (LLM ausgenommen)


@app.get("/health")
def health():
    return {"status": "ok"}


@app.get("/")
async def serve_index(username: str = Depends(check_auth)):
    return FileResponse("static/index.html")
