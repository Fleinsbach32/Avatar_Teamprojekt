import os
import secrets

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPBasic, HTTPBasicCredentials

security = HTTPBasic()


def check_auth(credentials: HTTPBasicCredentials = Depends(security)) -> str:
    """HTTP-Basic-Auth für die Browser-Endpoints.

    Wird NICHT auf die von Tavus serverseitig aufgerufenen LLM-Endpoints
    (/tavus/llm, /tavus/llm/chat/completions, /chat/completions) angewandt —
    Tavus kann keine Credentials mitsenden.
    """
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
