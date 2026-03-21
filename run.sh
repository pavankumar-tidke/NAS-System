#!/usr/bin/env bash
# Start the FastAPI server (development: --reload).
set -euo pipefail
ROOT="$(cd "$(dirname "$0")" && pwd)"
cd "$ROOT"

if [[ ! -x .venv/bin/uvicorn ]]; then
  echo "Virtualenv missing or uvicorn not installed. Run:  ./setup.sh"
  exit 1
fi

# Load only API_HOST / API_PORT from .env — never `source` the whole file (spaces in
# APP_NAME=NAS Core API, @ in MONGO_URI, etc. make bash treat tokens as commands).
if [[ -f .env ]]; then
  eval "$(.venv/bin/python <<'PY'
import shlex
from pathlib import Path

keys = {"API_HOST", "API_PORT"}
path = Path(".env")
if not path.is_file():
    raise SystemExit(0)
for raw in path.read_text(encoding="utf-8", errors="replace").splitlines():
    line = raw.strip()
    if not line or line.startswith("#"):
        continue
    if "=" not in line:
        continue
    key, _, val = line.partition("=")
    key = key.strip()
    if key not in keys:
        continue
    val = val.strip()
    if len(val) >= 2 and val[0] == val[-1] and val[0] in "\"'":
        val = val[1:-1]
    print(f"export {key}={shlex.quote(val)}")
PY
)"
fi

HOST="${API_HOST:-0.0.0.0}"
PORT="${API_PORT:-8000}"
exec .venv/bin/uvicorn app.main:app --host "$HOST" --port "$PORT" --reload
