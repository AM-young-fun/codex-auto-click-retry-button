#!/usr/bin/env bash
# Start the Codex Retry auto-clicker using the project's virtualenv when present.
set -euo pipefail
cd "$(dirname "$0")"

if [[ -x ".venv/bin/python" ]]; then
  PYTHON=".venv/bin/python"
else
  PYTHON="${PYTHON:-python3}"
fi

exec "$PYTHON" main.py "$@"
