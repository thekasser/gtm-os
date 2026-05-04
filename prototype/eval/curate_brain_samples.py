"""Curate static brain output samples for the explainer's Brain Outputs gallery.

Reads the latest passing run per fixture from BrainAnalysisLog + BrainEvalLog,
strips the run-state-only fields, attaches fixture metadata, and writes a
single static JSON file at /eval/samples/brain_outputs.json that the
explainer's Brain Outputs tab loads.

Run after a fresh eval sweep to refresh the gallery.

Usage:
    cd prototype
    ../synth/venv/bin/python3 eval/curate_brain_samples.py

Cost: $0 (no API calls — just reads existing logs).
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

# Resolve paths
PROTOTYPE_DIR = Path(__file__).parent.parent
REPO_ROOT = PROTOTYPE_DIR.parent
sys.path.insert(0, str(PROTOTYPE_DIR))
sys.path.insert(0, str(PROTOTYPE_DIR / "eval"))

from fixtures import FIXTURES
from pipeline_fixtures import PIPELINE_FIXTURES

BRAIN_LOG = PROTOTYPE_DIR / "brain_analysis_log.jsonl"
EVAL_LOG = PROTOTYPE_DIR / "brain_eval_log.jsonl"
OUTPUT = REPO_ROOT / "eval" / "samples" / "brain_outputs.json"


def _read_jsonl(path: Path) -> list[dict]:
    rows = []
    if not path.exists():
        return rows
    with path.open() as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                rows.append(json.loads(line))
            except Exception:
                continue
    return rows


def _strip_brain_row(row: dict) -> dict:
    """Strip non-presentation fields. Keep what a CRO needs to see + audit
    fields that demonstrate the "every claim cites a source" discipline.
    """
    return {
        "analysis_id":              row.get("analysis_id"),
        "proposal_id":              row.get("proposal_id"),
        "writer_agent_id":          row.get("writer_agent_id"),
        "account_id":               row.get("account_id"),
        "question":                 row.get("question"),
        "narrative_output":         row.get("narrative_output", ""),
        "sources_read":             row.get("sources_read", []),
        "proposed_actions":         row.get("proposed_actions", []),
        "confidence_flags":         row.get("confidence_flags", []),
        "data_staleness_acknowledged": row.get("data_staleness_acknowledged", False),
        "stale_sources":            row.get("stale_sources", []),
        "tool_calls_made":          row.get("tool_calls_made", []),
        "model_used":               row.get("model_used"),
        "input_tokens":             row.get("input_tokens"),
        "output_tokens":            row.get("output_tokens"),
        "cost_usd_estimate":        row.get("cost_usd_estimate"),
        "response_time_ms":         row.get("response_time_ms"),
        "created_at":               row.get("created_at"),
        # Meta fields that help frame each sample for the gallery
        "_meta_archetype_key":      row.get("_meta_archetype_key"),
        "_meta_expected_outcome":   row.get("_meta_expected_outcome"),
    }


def main():
    brain_rows = _read_jsonl(BRAIN_LOG)
    eval_runs = _read_jsonl(EVAL_LOG)

    # ── AGT-902: pull latest passing run per Q-fixture from BrainEvalLog ──
    q_latest: dict[str, dict] = {}
    for run in eval_runs:
        started = run.get("run_started_at", "")
        for fr in run.get("fixture_results", []):
            fid = fr.get("fixture_id")
            if not fid or not fid.startswith("EVAL-Q"):
                continue
            if not fr.get("overall_pass"):
                continue
            existing = q_latest.get(fid)
            if not existing or started > existing["started"]:
                q_latest[fid] = {
                    "started": started,
                    "fixture_result": fr,
                }

    # Look up brain row by analysis_id for each Q-fixture
    brain_by_aid = {r.get("analysis_id"): r for r in brain_rows if r.get("analysis_id")}
    fixture_by_id = {f["fixture_id"]: f for f in FIXTURES}

    samples = []
    for fid, entry in q_latest.items():
        fr = entry["fixture_result"]
        aid = fr.get("brain_analysis_id")
        brain_row = brain_by_aid.get(aid)
        if not brain_row:
            print(f"  warn: no brain row found for {fid} analysis_id={aid}")
            continue
        fixture = fixture_by_id.get(fid, {})
        samples.append({
            "fixture_id":      fid,
            "fixture_summary": {
                "question_type": fixture.get("question_type"),
                "difficulty":    fixture.get("difficulty"),
                "comment":       fixture.get("comment"),
            },
            "company_name":    fr.get("company_name"),
            "archetype_key":   fr.get("archetype_key"),
            "criterion_results": fr.get("criterion_results", []),
            "elapsed_seconds": fr.get("elapsed_seconds"),
            "brain_row":       _strip_brain_row(brain_row),
        })

    # ── AGT-901: pull latest run per P-fixture from BrainAnalysisLog directly ──
    # (run_pipeline_eval writes to brain_analysis_log but not to brain_eval_log)
    p_questions = {f["question"]: f for f in PIPELINE_FIXTURES}
    p_latest: dict[str, dict] = {}
    for r in brain_rows:
        if r.get("writer_agent_id") != "AGT-901":
            continue
        q = r.get("question") or ""
        fixture = p_questions.get(q)
        if not fixture:
            continue
        fid = fixture["fixture_id"]
        existing = p_latest.get(fid)
        ts = r.get("created_at") or ""
        if not existing or ts > existing["created_at"]:
            p_latest[fid] = r

    for fid, brain_row in p_latest.items():
        fixture = next((f for f in PIPELINE_FIXTURES if f["fixture_id"] == fid), {})
        samples.append({
            "fixture_id":      fid,
            "fixture_summary": {
                "question_type": fixture.get("question_type"),
                "difficulty":    fixture.get("difficulty"),
                "comment":       fixture.get("comment"),
            },
            "company_name":    None,    # cohort-level
            "archetype_key":   None,    # cohort-level
            "criterion_results": [],    # not captured for pipeline eval today
            "elapsed_seconds": (brain_row.get("response_time_ms") or 0) / 1000,
            "brain_row":       _strip_brain_row(brain_row),
        })

    # Sort by fixture_id for stable output
    samples.sort(key=lambda s: s["fixture_id"])

    # Aggregate stats for the gallery header
    total_cost = sum(s["brain_row"].get("cost_usd_estimate") or 0 for s in samples)
    by_writer: dict[str, int] = {}
    for s in samples:
        w = s["brain_row"].get("writer_agent_id") or "?"
        by_writer[w] = by_writer.get(w, 0) + 1

    payload = {
        "generated_at":  __import__("datetime").datetime.utcnow().isoformat() + "Z",
        "sample_count":  len(samples),
        "total_cost_usd": round(total_cost, 4),
        "by_writer":     by_writer,
        "note":          (
            "Curated from latest passing run per fixture. "
            "Refresh by running `prototype/run_eval.sh && prototype/run_pipeline_eval.sh && "
            "prototype/eval/curate_brain_samples.py`."
        ),
        "samples":       samples,
    }

    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    with OUTPUT.open("w") as f:
        json.dump(payload, f, indent=2, default=str)

    print(f"wrote {len(samples)} samples to {OUTPUT}")
    print(f"  total cost across samples: ${total_cost:.4f}")
    print(f"  by writer: {by_writer}")


if __name__ == "__main__":
    main()
