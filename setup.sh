#!/usr/bin/env bash
# Install / refresh Python dependencies (run after editing requirements.txt).
set -euo pipefail
ROOT="$(cd "$(dirname "$0")" && pwd)"
cd "$ROOT"

if ! command -v python3 >/dev/null 2>&1; then
  echo "python3 not found. Install Python 3.10+ first."
  exit 1
fi

python3 -m venv .venv
./.venv/bin/pip install -U pip
./.venv/bin/pip install -r requirements.txt

echo ""
echo "Setup complete. Start the API with:  ./run.sh"
