import os
from fastapi import APIRouter

router = APIRouter()


@router.get("/avatar/config")
def avatar_config():
    return {"provider": os.getenv("AVATAR_PROVIDER", "tavus").lower()}
