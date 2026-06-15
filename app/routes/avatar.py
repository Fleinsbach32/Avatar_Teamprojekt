import os
from fastapi import APIRouter

router = APIRouter()

_VALID_PROVIDERS = {"tavus"}


@router.get("/avatar/config")
def avatar_config():
    provider = os.getenv("AVATAR_PROVIDER", "tavus").lower()
    if provider not in _VALID_PROVIDERS:
        provider = "tavus"
    return {"provider": provider}
