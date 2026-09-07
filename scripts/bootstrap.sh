#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PYTHON="${PYTHON:-python3.10}"

command -v "$PYTHON" >/dev/null 2>&1 || {
  echo "Python 3.10 is required." >&2
  exit 1
}

"$PYTHON" -m venv "$ROOT/.venv"
"$ROOT/.venv/bin/python" -m pip install --upgrade pip
"$ROOT/.venv/bin/python" -m pip install -r "$ROOT/requirements.txt"

echo "Environment ready. Run: ./scripts/run-dev.sh"
