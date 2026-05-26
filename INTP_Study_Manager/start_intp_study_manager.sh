#!/usr/bin/env bash
set -euo pipefail

APP_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$APP_DIR"

if [[ -x "$APP_DIR/../.venv/bin/python" ]]; then
    PYTHON_EXE="$APP_DIR/../.venv/bin/python"
elif command -v python3 >/dev/null 2>&1; then
    PYTHON_EXE="python3"
else
    PYTHON_EXE="python"
fi

exec "$PYTHON_EXE" -m streamlit run app.py --server.headless true
