#!/bin/bash
# AGT-901 Pipeline Brain runner — works from any CWD.
#
# Examples (run from anywhere):
#   prototype/run_agt901.sh
#   prototype/run_agt901.sh --question "Why is SMB churn elevated?"
#   /Users/connorkasser/gtm-os/prototype/run_agt901.sh --quiet
#
# Exits non-zero if the venv or script can't be found.

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
VENV_PYTHON="$SCRIPT_DIR/../synth/venv/bin/python3"
PY_SCRIPT="$SCRIPT_DIR/run_agt901.py"

if [[ ! -x "$VENV_PYTHON" ]]; then
    echo "ERROR: venv python not found at $VENV_PYTHON" >&2
    exit 1
fi

if [[ ! -f "$PY_SCRIPT" ]]; then
    echo "ERROR: run_agt901.py not found at $PY_SCRIPT" >&2
    exit 1
fi

exec "$VENV_PYTHON" "$PY_SCRIPT" "$@"
