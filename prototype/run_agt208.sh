#!/bin/bash
# AGT-208 Developer Signal Scorer runner — works from any CWD.
#
# Resolves its own location, finds the venv at ../synth/venv/, and execs
# run_agt208.py with whatever arguments were passed.
#
# Examples (run from anywhere):
#   prototype/run_agt208.sh                              # all 50 accounts
#   prototype/run_agt208.sh --limit 5                    # cap at 5 accounts
#   prototype/run_agt208.sh --archetype expansion_ready  # one archetype
#   prototype/run_agt208.sh --no-ae-briefs               # deterministic-only
#
# Exits non-zero if the venv or script can't be found.

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
VENV_PYTHON="$SCRIPT_DIR/../synth/venv/bin/python3"
PY_SCRIPT="$SCRIPT_DIR/run_agt208.py"

if [[ ! -x "$VENV_PYTHON" ]]; then
    echo "ERROR: venv python not found at $VENV_PYTHON" >&2
    echo "Did you create the venv? Run from synth/: python3 -m venv venv" >&2
    exit 1
fi

if [[ ! -f "$PY_SCRIPT" ]]; then
    echo "ERROR: run_agt208.py not found at $PY_SCRIPT" >&2
    exit 1
fi

exec "$VENV_PYTHON" "$PY_SCRIPT" "$@"
