"""CLI entry for AGT-903 Strategy Brain.

Examples (from any CWD):
    prototype/run_agt903.sh --fixture EVAL-S01
    prototype/run_agt903.sh --fixture EVAL-S05    # tests refusal correctness
    prototype/run_agt903.sh --all-fixtures        # full eval sweep

Output: prototype/brain_analysis_log.jsonl + prototype/strategy_recommendation_log.jsonl
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR))
sys.path.insert(0, str(SCRIPT_DIR / "eval"))

from agt903 import run_query
from strategy_brain_view import build_view_for_fixture, scope_tags_for_fixture
from strategy_fixtures import STRATEGY_FIXTURES


FIXTURE_BY_ID = {f["fixture_id"]: f for f in STRATEGY_FIXTURES}


def run_one(fixture_id: str) -> dict:
    if fixture_id not in FIXTURE_BY_ID:
        raise SystemExit(f"unknown fixture {fixture_id}; valid: {sorted(FIXTURE_BY_ID.keys())}")
    fixture = FIXTURE_BY_ID[fixture_id]
    question = fixture["question"]
    view = build_view_for_fixture(fixture_id)
    scope_tags = scope_tags_for_fixture(fixture_id)

    print(f"\n=== {fixture_id} | {fixture['question_type']} ({fixture['difficulty']}) ===")
    print(f"  Question: {question[:140]}{'...' if len(question) > 140 else ''}")
    print(f"  Views supplied: {list(view.keys())}")
    expected_action = fixture.get("expected_action_type") or fixture.get("expected_action_type_one_of", "?")
    print(f"  Expected action_type: {expected_action}")

    result = run_query(view, question, scope_tags=scope_tags, fixture_id=fixture_id)
    parsed = result["parsed"]
    cost = result["cost_metadata"]

    print(f"\n  AGT-903 output:")
    print(f"    action_type: {parsed.get('action_type')}")
    print(f"    scope_severity: {parsed.get('scope_severity')}")
    print(f"    options_count: {len(parsed.get('options_enumerated', []))}")
    print(f"    risk_classes_present: {sorted((parsed.get('risk_surface') or {}).keys())}")
    print(f"    assumptions_must_hold count: {len(parsed.get('assumptions_must_hold', []))}")
    print(f"    sources_read: {[s.get('table_name') for s in parsed.get('sources_read', [])]}")
    print(f"    data_staleness_acknowledged: {parsed.get('data_staleness_acknowledged')}")
    if parsed.get('options_enumerated'):
        for i, opt in enumerate(parsed['options_enumerated']):
            print(f"      [opt {i+1}] {opt.get('option_label')}: {opt.get('hypothesis', '')[:120]}{'...' if len(opt.get('hypothesis',''))>120 else ''}")
            print(f"               projected_impact_range: {opt.get('projected_impact_range', '')[:80]}")
    print(f"\n    narrative_output (first 400 chars): {parsed.get('narrative_output','')[:400]}{'...' if len(parsed.get('narrative_output',''))>400 else ''}")
    print(f"\n  Cost: model={cost['model']} in={cost['input_tokens']} out={cost['output_tokens']} ${cost['cost_usd_estimate']} ({cost['elapsed_ms']/1000:.1f}s)")
    print(f"  Tool calls: {len(result.get('tool_calls_made', []))}")
    for tc in result.get("tool_calls_made", []):
        print(f"    - {tc['tool_name']} → {tc['tool_result_status']}")
    return result


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--fixture", help="run a single fixture (EVAL-S01..S05)")
    parser.add_argument("--all-fixtures", action="store_true", help="run all 5 fixtures")
    args = parser.parse_args()

    total_cost = 0.0
    if args.all_fixtures:
        for fid in ["EVAL-S01", "EVAL-S02", "EVAL-S03", "EVAL-S04", "EVAL-S05"]:
            try:
                r = run_one(fid)
                total_cost += r["cost_metadata"]["cost_usd_estimate"]
            except Exception as e:
                print(f"\n  FIXTURE {fid} ERROR: {type(e).__name__}: {e}")
        print(f"\n{'─'*70}\nTotal AGT-903 sweep cost: ${total_cost:.4f}")
    elif args.fixture:
        r = run_one(args.fixture)
        print(f"\n{'─'*70}\nDone. ${r['cost_metadata']['cost_usd_estimate']:.4f}")
    else:
        parser.print_help()
        sys.exit(1)


if __name__ == "__main__":
    main()
