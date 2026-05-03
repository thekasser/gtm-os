"""CLI for the AGT-902 eval harness.

Examples:
    # Run all fixtures from fixtures.py
    python3 run_eval.py

    # Run only one fixture
    python3 run_eval.py --fixture EVAL-Q01

    # Run with custom corpus dir / log paths
    python3 run_eval.py --corpus ../../synth/corpus --eval-log ../brain_eval_log.jsonl

    # Show only failures (don't print full pass output)
    python3 run_eval.py --quiet

Output:
    - Per-fixture pass/fail printed to stdout
    - Aggregate run summary
    - Eval-run row appended to brain_eval_log.jsonl
    - BrainAnalysisLog rows for each run appended to ../brain_analysis_log.jsonl
"""

from __future__ import annotations

import argparse
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

_HERE = Path(__file__).parent.resolve()
_PROTOTYPE_DIR = _HERE.parent
if str(_HERE) not in sys.path:
    sys.path.insert(0, str(_HERE))
if str(_PROTOTYPE_DIR) not in sys.path:
    sys.path.insert(0, str(_PROTOTYPE_DIR))

from fixtures import FIXTURES
from scorer import score_fixture
from brain_eval_log import append_eval_run


def main():
    parser = argparse.ArgumentParser(
        description="Run AGT-902 eval harness against fixtures.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument("--fixture", type=str, default=None,
                        help="run only the fixture with this fixture_id")
    parser.add_argument("--corpus", type=Path,
                        default=_PROTOTYPE_DIR.parent / "synth" / "corpus",
                        help="path to synth/corpus directory")
    parser.add_argument("--brain-log", type=Path,
                        default=_PROTOTYPE_DIR / "brain_analysis_log.jsonl",
                        help="path to BrainAnalysisLog (where brain runs append rows)")
    parser.add_argument("--eval-log", type=Path,
                        default=_PROTOTYPE_DIR / "brain_eval_log.jsonl",
                        help="path to BrainEvalLog (where eval runs append rows)")
    parser.add_argument("--quiet", action="store_true",
                        help="suppress per-fixture detail; show only failures")
    args = parser.parse_args()

    if not os.environ.get("ANTHROPIC_API_KEY"):
        sys.stderr.write("ERROR: ANTHROPIC_API_KEY not set in environment.\n")
        raise SystemExit(1)

    if not args.corpus.is_dir():
        raise SystemExit(f"Corpus directory not found: {args.corpus}")

    fixtures = FIXTURES
    if args.fixture:
        fixtures = [f for f in FIXTURES if f["fixture_id"] == args.fixture]
        if not fixtures:
            raise SystemExit(f"No fixture with id='{args.fixture}'. "
                             f"Available: {[f['fixture_id'] for f in FIXTURES]}")

    started_at = datetime.now(timezone.utc).isoformat()
    print(f"=" * 70)
    print(f"AGT-902 EVAL RUN")
    print(f"  fixtures:   {len(fixtures)}")
    print(f"  corpus:     {args.corpus}")
    print(f"  brain log:  {args.brain_log}")
    print(f"  eval log:   {args.eval_log}")
    print(f"=" * 70)

    fixture_result_summaries: list[dict] = []
    model_used: str | None = None

    for i, fixture in enumerate(fixtures):
        fid = fixture["fixture_id"]
        print(f"\n[{i+1}/{len(fixtures)}] {fid} — {fixture.get('question_type','?')} "
              f"({fixture.get('difficulty','?')})")

        result = score_fixture(fixture, args.corpus, args.brain_log)
        if result.failed_with_exception:
            print(f"  EXCEPTION: {result.failed_with_exception}", file=sys.stderr)
            fixture_result_summaries.append({
                "fixture_id":       fid,
                "overall_pass":     False,
                "failed_with_exception": result.failed_with_exception,
                "company_name":     result.company_name,
                "archetype_key":    result.archetype_key,
            })
            continue

        if not args.quiet or not result.overall_pass:
            print(f"  account: {result.company_name} ({result.archetype_key})")
            print(f"  brain:   {result.brain_analysis_row['model_used']}, "
                  f"{result.brain_analysis_row['input_tokens']}in/"
                  f"{result.brain_analysis_row['output_tokens']}out, "
                  f"${result.brain_analysis_row['cost_usd_estimate']:.4f}, "
                  f"{result.brain_analysis_row['response_time_ms']}ms")
            for c in result.criterion_results:
                print(c)

        verdict = "PASS" if result.overall_pass else "FAIL"
        print(f"  → {verdict}")

        # Soft-validation issues (always show even on pass — calibration signal)
        soft = [i for i in result.validation.issues if i.severity == "soft"]
        if soft and not args.quiet:
            print(f"  soft issues:")
            for issue in soft:
                print(f"    {issue}", file=sys.stderr)

        if model_used is None:
            model_used = result.brain_analysis_row.get("model_used")

        fixture_result_summaries.append({
            "fixture_id":            fid,
            "overall_pass":          result.overall_pass,
            "company_name":          result.company_name,
            "archetype_key":         result.archetype_key,
            "account_id":            result.account_id,
            "brain_analysis_id":     result.brain_analysis_row.get("analysis_id"),
            "criterion_results": [
                {"name": c.name, "passed": c.passed, "detail": c.detail}
                for c in result.criterion_results
            ],
            "elapsed_seconds":       result.elapsed_seconds,
            "input_tokens":          result.brain_analysis_row.get("input_tokens", 0),
            "output_tokens":         result.brain_analysis_row.get("output_tokens", 0),
            "cost_usd_estimate":     result.brain_analysis_row.get("cost_usd_estimate", 0.0),
        })

    # ─── Aggregate summary ───────────────────────────────────────
    total = len(fixture_result_summaries)
    passed = sum(1 for r in fixture_result_summaries if r["overall_pass"])
    failed = total - passed
    total_cost = sum(r.get("cost_usd_estimate", 0.0) for r in fixture_result_summaries)

    print()
    print(f"=" * 70)
    print(f"AGGREGATE")
    print(f"  passed:     {passed}/{total}")
    print(f"  failed:     {failed}/{total}")
    print(f"  total cost: ${total_cost:.4f}")
    if failed > 0:
        print(f"\nFAILURES:")
        for r in fixture_result_summaries:
            if not r["overall_pass"]:
                if r.get("failed_with_exception"):
                    print(f"  {r['fixture_id']} ({r['company_name']}): "
                          f"EXCEPTION {r['failed_with_exception']}")
                else:
                    fails = [c["name"] for c in r["criterion_results"] if not c["passed"]]
                    print(f"  {r['fixture_id']} ({r['company_name']}): {fails}")

    eval_run_id = append_eval_run(
        run_metadata={
            "started_at": started_at,
            "trigger":    "on_demand",
            "model":      model_used,
        },
        fixture_results=fixture_result_summaries,
        log_path=args.eval_log,
    )
    print(f"\nEvalRunLog: {args.eval_log} (run_id={eval_run_id})")
    print(f"=" * 70)


if __name__ == "__main__":
    main()
