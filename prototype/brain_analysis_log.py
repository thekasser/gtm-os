"""BrainAnalysisLog writer — append-only JSONL.

Per the BrainAnalysisLog production schema spec, this table is append-only,
single-writer-per-row, with full source-trace metadata. For the prototype, we
emulate the table with a JSONL file (one row per line). Easy to inspect, easy
to load into pandas/jq, easy to port to a real database later.

Brain Agents (AGT-901, AGT-902) write rows here. Other Tier 1 services have
no read access by design; in the prototype that's enforced by convention only.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any


DEFAULT_LOG_PATH = Path("brain_analysis_log.jsonl")


def append_row(row: dict, log_path: Path = DEFAULT_LOG_PATH) -> None:
    """Append one BrainAnalysisLog row as a JSON line. Creates file if missing."""
    log_path.parent.mkdir(parents=True, exist_ok=True)
    with log_path.open("a") as f:
        f.write(json.dumps(row, default=str) + "\n")


def read_all(log_path: Path = DEFAULT_LOG_PATH) -> list[dict]:
    """Read every row from the log. Returns empty list if file missing."""
    if not log_path.exists():
        return []
    rows: list[dict] = []
    with log_path.open() as f:
        for line in f:
            line = line.strip()
            if line:
                rows.append(json.loads(line))
    return rows


def filter_rows(log_path: Path = DEFAULT_LOG_PATH,
                account_id: str | None = None,
                writer_agent_id: str | None = None,
                proposal_id: str | None = None) -> list[dict]:
    """Filter rows by account_id / writer / proposal_id."""
    rows = read_all(log_path)
    if account_id:
        rows = [r for r in rows if r.get("account_id") == account_id]
    if writer_agent_id:
        rows = [r for r in rows if r.get("writer_agent_id") == writer_agent_id]
    if proposal_id:
        rows = [r for r in rows if r.get("proposal_id") == proposal_id]
    return rows
