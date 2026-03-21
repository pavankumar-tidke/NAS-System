#!/usr/bin/env bash
# One-shot: sync dependencies then start the server (handy on a fresh clone).
set -euo pipefail
ROOT="$(cd "$(dirname "$0")" && pwd)"
"$ROOT/setup.sh"
exec "$ROOT/run.sh"
