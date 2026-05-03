#!/bin/bash
# AGT-902 Account Brain runner — works from any CWD.
#
# Resolves its own location, finds the venv at ../synth/venv/, and execs
# run_agt902.py with whatever arguments were passed.
#
# Examples (run from anywhere):
#   prototype/run.sh --account "Pendant Logistics"
#   prototype/run.sh --batch --archetype champion_loss_decliner
#   /Users/connorkasser/gtm-os/prototype/run.sh --batch --limit 5
#
# Exits non-zero if the venv or script can't be found.

set -e

# Resolve script directory (handles symlinks)
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
VENV_PYTHON="$SCRIPT_DIR/../synth/venv/bin/python3"
PY_SCRIPT="$SCRIPT_DIR/run_agt902.py"

if [[ ! -x "$VENV_PYTHON" ]]; then
    echo "ERROR: venv python not found at $VENV_PYTHON" >&2
    echo "Did you create the venv? Run from synth/: python3 -m venv venv" >&2
    exit 1
fi

if [[ ! -f "$PY_SCRIPT" ]]; then
    echo "ERROR: run_agt902.py not found at $PY_SCRIPT" >&2
    exit 1
fi

exec "$VENV_PYTHON" "$PY_SCRIPT" "$@"
