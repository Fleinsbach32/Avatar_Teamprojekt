import logging
import os
import secrets
from contextlib import asynccontextmanager

from dotenv import load_dotenv
from fastapi import Depends, FastAPI, HTTPException, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.security import HTTPBasic, HTTPBasicCredentials

load_dotenv()

from app.rag import collection
from app.routes import avatar, chat, tavus

security = HTTPBasic()


def check_auth(credentials: HTTPBasicCredentials = Depends(security)):
    correct_username = os.getenv("APP_USERNAME", "admin")
    correct_password = os.getenv("APP_PASSWORD", "geheim")

    is_correct = (
        secrets.compare_digest(credentials.username, correct_username) and
        secrets.compare_digest(credentials.password, correct_password)
    )

    if not is_correct:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Falsches Passwort",
            headers={"WWW-Authenticate": "Basic"},
        )
    return credentials.username


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

app.include_router(avatar.router, dependencies=[Depends(check_auth)])
app.include_router(chat.router, dependencies=[Depends(check_auth)])
app.include_router(tavus.router, dependencies=[Depends(check_auth)])


@app.get("/health")
def health():
    return {"status": "ok"}


@app.get("/")
async def serve_index(username: str = Depends(check_auth)):
    return FileResponse("static/index.html")
