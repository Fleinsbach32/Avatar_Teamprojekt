# Codebase Cleanup & Optimization Design

**Date:** 2026-06-22
**Scope:** `app/` — Auth-Entfernung, httpx Connection-Pool, Dead Code

---

## Ziel

Auth/Passwort-Schutz aus dem App-Code entfernen, Connection-Overhead zur Tavus API reduzieren, toten Code löschen.

---

## Abschnitt 1: Auth entfernen

### Zu löschen
- `app/auth.py` — vollständig löschen

### `app/main.py`
- `from app.auth import check_auth` entfernen
- `from fastapi import Depends, FastAPI` → `from fastapi import FastAPI`
- `dependencies=[Depends(check_auth)]` von beiden `app.include_router(...)` entfernen
- `serve_index` vereinfachen:
  ```python
  @app.get("/")
  async def serve_index():
      return FileResponse("static/index.html")
  ```

### `app/routes/tavus.py`
- `from app.auth import check_auth` entfernen
- `dependencies=[Depends(check_auth)]` aus folgenden Routen entfernen:
  - `POST /tavus/settings`
  - `POST /tavus/session`
  - `POST /tavus/end`
  - `POST /tavus/message`
- `Depends` aus dem fastapi-Import entfernen (falls nicht mehr gebraucht)

---

## Abschnitt 2: httpx Shared Client

### Problem
`app/routes/tavus.py` erstellt bei jedem Request einen neuen `httpx.AsyncClient()` (3 Stellen). Das verhindert TCP Connection-Reuse zur Tavus API (~5-15ms Overhead pro Request).

### Fix

**`app/routes/tavus.py`** — Modul-Level Client:
```python
_http = httpx.AsyncClient(timeout=httpx.Timeout(15.0))
```

Alle 3 `async with httpx.AsyncClient() as http:` Blöcke ersetzen:
```python
# Vorher:
async with httpx.AsyncClient() as http:
    res = await http.post(...)

# Nachher:
res = await _http.post(...)
```

Pro-Route-Timeouts, die bisher im Client-Konstruktor oder `.post(timeout=...)` standen, bleiben im jeweiligen `await _http.post(..., timeout=...)` Call erhalten.

**`app/main.py`** — Cleanup im Lifespan:
```python
from app.routes import avatar, chat, tavus

@asynccontextmanager
async def lifespan(app: FastAPI):
    try:
        collection.query(query_texts=["Warmup"], n_results=1)
    except Exception as e:
        logging.warning(f"ChromaDB Warmup fehlgeschlagen: {e}")
    yield
    await tavus._http.aclose()
```

---

## Abschnitt 3: Dead Code entfernen

### `app/routes/avatar.py`
`_VALID_PROVIDERS` ist funktionslos (ein Wert, Reset zu demselben Wert bei Mismatch).

```python
# Vorher:
_VALID_PROVIDERS = {"tavus"}

@router.get("/avatar/config")
def avatar_config():
    provider = os.getenv("AVATAR_PROVIDER", "tavus").lower()
    if provider not in _VALID_PROVIDERS:
        provider = "tavus"
    return {"provider": provider}

# Nachher:
@router.get("/avatar/config")
def avatar_config():
    return {"provider": os.getenv("AVATAR_PROVIDER", "tavus").lower()}
```

### `app/routes/tavus.py` + `app/routes/chat.py`
```python
# Vorher:
import json as json_lib

# Nachher:
import json
```

Alle `json_lib.dumps(...)` → `json.dumps(...)`.

### `app/routes/chat.py`
Überflüssige Zwischenvariablen auf Zeilen 27-28:
```python
# Vorher:
session_id  = request.session_id
user_input  = request.message

# Nachher: direkt request.session_id / request.message verwenden
```

---

## Was sich NICHT ändert

- `active_voice_prefs` in `tavus.py` — saubere Lösung erfordert Frontend-Änderung, eigener Task
- `app/rag.py` — keine Änderungen
- `app/session.py` — keine Änderungen
- `app/gemini.py` — keine Änderungen
- `static/index.html` — keine Änderungen
- Tests — werden angepasst wo Auth-Mocking nötig ist
