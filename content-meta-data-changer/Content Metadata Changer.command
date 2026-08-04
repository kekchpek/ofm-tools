#!/bin/bash
set -euo pipefail

APP_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$APP_DIR"

if [[ -x "$APP_DIR/.venv/bin/python" ]]; then
  PYTHON="$APP_DIR/.venv/bin/python"
elif command -v python3 >/dev/null 2>&1; then
  PYTHON="$(command -v python3)"
else
  echo "Python 3 not found. Install Python 3 or create .venv in:"
  echo "$APP_DIR"
  read -r -p "Press Enter to close."
  exit 1
fi

"$PYTHON" main.py
status=$?

if [[ $status -ne 0 ]]; then
  echo
  echo "Content Metadata Changer exited with code $status."
  read -r -p "Press Enter to close."
fi

exit "$status"
