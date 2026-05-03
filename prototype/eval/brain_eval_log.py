"""BrainEvalLog writer — append-only JSONL of eval-run results.

Parallel to brain_analysis_log (which records every brain run); this file
records the SCORE of each brain run when invoked under the eval harness.

Per the BrainEvalLog production schema spec, this is append-only with a
foreign key (brain_analysis_id) back to the BrainAnalysisLog row produced
during the eval run. That join lets you go from "this fixture failed" to
"here's the brain output that produced the failure."
"""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from pathlib import Path

DEFAULT_LOG_PATH = Path("brain_eval_log.jsonl")


def append_eval_run(run_metadata: dict, fixture_results: list[dict],
                    log_path: Path = DEFAULT_LOG_PATH) -> str:
    """Append one eval-run row + its per-fixture scores. Returns eval_run_id."""
    log_path.parent.mkdir(parents=True, exist_ok=True)

    eval_run_id = str(uuid.uuid4())
    row = {
        "eval_run_id":     eval_run_id,
        "run_started_at":  run_metadata.get("started_at"),
        "run_completed_at": datetime.now(timezone.utc).isoformat(),
        "run_trigger":     run_metadata.get("trigger", "on_demand"),
        "model_used":      run_metadata.get("model"),
        "fixture_count":   len(fixture_results),
        "fixture_results": fixture_results,
        "aggregate": {
            "total":             len(fixture_results),
            "passed":            sum(1 for r in fixture_results if r["overall_pass"]),
            "failed":            sum(1 for r in fixture_results if not r["overall_pass"]),
            "exception_failures": sum(1 for r in fixture_results if r.get("failed_with_exception")),
            "total_cost_usd":    sum(r.get("cost_usd_estimate", 0.0) for r in fixture_results),
            "total_tokens_in":   sum(r.get("input_tokens", 0) for r in fixture_results),
            "total_tokens_out":  sum(r.get("output_tokens", 0) for r in fixture_results),
        },
    }

    with log_path.open("a") as f:
        f.write(json.dumps(row, default=str) + "\n")

    return eval_run_id


def read_all_runs(log_path: Path = DEFAULT_LOG_PATH) -> list[dict]:
    if not log_path.exists():
        return []
    rows: list[dict] = []
    with log_path.open() as f:
        for line in f:
            line = line.strip()
            if line:
                rows.append(json.loads(line))
    return rows
