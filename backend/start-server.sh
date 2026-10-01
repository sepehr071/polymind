#! /usr/bin/env sh
set -e

# Run database migrations
uv run --no-sync alembic upgrade head

###################################
### run FastAPI (ASGI) w/ gunicorn ###
###################################
# Prod serves the FastAPI app (app.asgi:app) via gunicorn's UvicornWorker.
# Async workers handle SSE streaming natively (no per-thread blocking like the
# old gthread + Flask wsgi:app path). GUNICORN_THREADS is ignored by the async
# worker, so it is dropped here.
export GUNICORN_CONF="/opt/gunicorn.conf.py"
uv run --no-sync gunicorn --worker-class uvicorn.workers.UvicornWorker --workers "${WORKERS_NUM:-2}" --timeout 120 app.asgi:app
