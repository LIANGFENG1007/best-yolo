#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PYTHON="$ROOT/.venv/bin/python"

[ -x "$PYTHON" ] || {
  echo "Run ./scripts/bootstrap.sh first." >&2
  exit 1
}

export BEST_YOLO_DATA_DIR="${BEST_YOLO_DATA_DIR:-$ROOT/.dev-data}"
export PYTHONDONTWRITEBYTECODE=1
exec "$PYTHON" "$ROOT/gui/app.py" "$@"
