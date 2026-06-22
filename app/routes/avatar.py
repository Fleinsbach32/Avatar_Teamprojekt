import os
from fastapi import APIRouter

router = APIRouter()


@router.get("/avatar/config")
def avatar_config():
    provider = os.getenv("AVATAR_PROVIDER", "tavus").lower()
    if provider != "tavus":
        provider = "tavus"
    return {"provider": provider}
