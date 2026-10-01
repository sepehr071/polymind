"""Local entrypoint for the FastAPI ("bridge") app.

Run the migrated FastAPI backend (NOT the legacy Flask `run.py`):

    cd backend
    ./.venv-uv/Scripts/python.exe -m uvicorn main:app --reload --port 5000

.env is loaded HERE, before the app package is imported (app/config.py reads
os.environ at class-definition time, and importing app.asgi runs app/__init__ ->
app.config first). Loading it in this entrypoint — which the test harness never
imports — keeps local .env values out of the test environment. Prod serves the same
`app.asgi:app` via gunicorn + UvicornWorker (start-server.sh) with
container-injected env; this file is dev-only.
"""
from pathlib import Path

from dotenv import load_dotenv

# Resolve backend/.env by absolute path so it loads regardless of the directory
# uvicorn was launched from. override=False: real environment variables win.
load_dotenv(Path(__file__).resolve().parent / ".env", override=False)

from app.asgi import app  # noqa: E402,F401  (re-exported as the uvicorn target)
