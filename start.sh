#!/usr/bin/env bash
set -e

# Load .env if present
if [ -f .env ]; then
  export $(grep -v '^#' .env | xargs)
fi

echo "==> Seeding database in background..."
python seed_db.py --days 7 &

echo "==> Starting API server..."
uvicorn mlb_app.app:app --host 0.0.0.0 --port "${PORT:-8000}"
