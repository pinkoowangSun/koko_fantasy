#!/usr/bin/env bash
# Start the Koko backend from the repo root.
# PYTHONPATH=backend is required so that intra-package imports (from app.X)
# resolve correctly when uvicorn is invoked as backend.app.main:app.
set -e
cd "$(dirname "$0")"
PYTHONPATH=backend backend/.venv/bin/uvicorn backend.app.main:app \
  --host 0.0.0.0 --port 8000 --reload
