#!/usr/bin/env bash
set -euo pipefail

# Pass --lan to also allow phones/other devices on your Wi-Fi to connect.
HOST="127.0.0.1"
if [ "${1:-}" = "--lan" ]; then
  HOST="0.0.0.0"
fi

if [ ! -d ".venv" ]; then
  echo "Creating virtual environment..."
  python3 -m venv .venv
fi

source .venv/bin/activate
python -m pip install --upgrade pip --quiet
pip install -r requirements.txt --quiet

if [ ! -f ".env" ]; then
  cp .env.example .env
  echo "Created .env from .env.example"
fi

echo ""
echo "Starting Garmin Progress Coach..."
echo "Open: http://localhost:8000"
if [ "$HOST" = "0.0.0.0" ]; then
  echo "LAN mode: other devices on your network can also connect."
fi
echo ""
uvicorn app.main:app --reload --host "$HOST" --port 8000
