#!/bin/sh
# Payment Reconciliation API - Linux/macOS launcher
cd "$(dirname "$0")" || exit 1
[ -d .venv ] || { python3 -m venv .venv && .venv/bin/pip install -q -r requirements.txt; }
[ -f .env ] || { echo "ERROR: .env not found. Copy .env.example and add your connection string."; exit 1; }
echo "Dashboard: http://localhost:8000"
exec .venv/bin/uvicorn api.main:app --host 127.0.0.1 --port 8000
