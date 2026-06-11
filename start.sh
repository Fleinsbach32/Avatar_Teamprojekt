#!/usr/bin/env bash
# KIRA Start-Skript (Linux/Mac)
set -e
cd "$(dirname "$0")"

if [ ! -f .env ]; then
    echo "FEHLER: .env fehlt. Kopiere .env.example zu .env und trage die Keys ein." >&2
    exit 1
fi

set -a
source .env
set +a

if [ -z "$GOOGLE_API_KEY" ] || [ "$GOOGLE_API_KEY" = "your_google_api_key_here" ]; then
    echo "FEHLER: GOOGLE_API_KEY ist nicht gesetzt (.env pruefen)." >&2
    exit 1
fi
if [ "$AVATAR_PROVIDER" = "tavus" ] && [ -z "$TAVUS_API_KEY" ]; then
    echo "FEHLER: TAVUS_API_KEY ist nicht gesetzt (.env pruefen)." >&2
    exit 1
fi

if [ ! -d chroma_db ]; then
    echo "ChromaDB wird befuellt (einmalig)..."
    python fill_db.py
fi

echo "KIRA startet auf http://localhost:8000 ..."
python -m uvicorn main:app --host 0.0.0.0 --port 8000 --reload
