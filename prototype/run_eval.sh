#!/bin/bash
# AGT-902 eval harness runner — works from any CWD.
#
# Examples:
#   prototype/run_eval.sh                     # run all fixtures
#   prototype/run_eval.sh --fixture EVAL-Q01  # one specific fixture
#   prototype/run_eval.sh --quiet             # suppress per-fixture detail; show failures only

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
VENV_PYTHON="$SCRIPT_DIR/../synth/venv/bin/python3"
PY_SCRIPT="$SCRIPT_DIR/eval/run_eval.py"

if [[ ! -x "$VENV_PYTHON" ]]; then
    echo "ERROR: venv python not found at $VENV_PYTHON" >&2
    exit 1
fi

if [[ ! -f "$PY_SCRIPT" ]]; then
    echo "ERROR: run_eval.py not found at $PY_SCRIPT" >&2
    exit 1
fi

exec "$VENV_PYTHON" "$PY_SCRIPT" "$@"
