#!/bin/bash
# AGT-903 Strategy Brain runner — works from any CWD.
set -e
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
VENV_PYTHON="$SCRIPT_DIR/../synth/venv/bin/python3"
PY_SCRIPT="$SCRIPT_DIR/run_agt903.py"
if [[ ! -x "$VENV_PYTHON" ]]; then
    echo "ERROR: venv python not found at $VENV_PYTHON" >&2
    exit 1
fi
exec "$VENV_PYTHON" "$PY_SCRIPT" "$@"
