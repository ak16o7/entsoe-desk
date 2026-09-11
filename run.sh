#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"
if [ ! -f .env ]; then cp .env.example .env; echo "Created .env — add your ENTSOE_API_KEY, then run again."; exit 1; fi
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -U pip
pip install -r requirements.txt
exec uvicorn app.main:app --host 0.0.0.0 --port "${PORT:-8000}"
