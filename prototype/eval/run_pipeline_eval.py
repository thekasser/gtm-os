"""CLI for the pipeline-fixture eval (AGT-901).

Sister to run_eval.py. Iterates PIPELINE_FIXTURES, scores each with
pipeline_scorer.score_pipeline_fixture, prints aggregate.

Usage:
  python run_pipeline_eval.py
  python run_pipeline_eval.py --fixture EVAL-P01
  python run_pipeline_eval.py --quiet
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
sys.path.insert(0, str(Path(__file__).parent.parent))

from pipeline_fixtures import PIPELINE_FIXTURES
from pipeline_scorer import score_pipeline_fixture
from brain_analysis_log import append_row as append_brain_analysis_row


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--corpus",
                        default=str(Path(__file__).parent.parent.parent / "synth" / "corpus"),
                        help="path to synth corpus directory")
    parser.add_argument("--fixture", default=None,
                        help="run only the named fixture (e.g., EVAL-P01)")
    parser.add_argument("--brain-log",
                        default=str(Path(__file__).parent.parent / "brain_analysis_log.jsonl"),
                        help="path to BrainAnalysisLog.jsonl")
    parser.add_argument("--quiet", action="store_true",
                        help="suppress per-criterion detail")
    args = parser.parse_args()

    corpus_dir = Path(args.corpus)
    if not corpus_dir.exists():
        sys.stderr.write(f"corpus not found: {corpus_dir}\n")
        sys.exit(2)

    fixtures = PIPELINE_FIXTURES
    if args.fixture:
        fixtures = [f for f in fixtures if f["fixture_id"] == args.fixture]
        if not fixtures:
            sys.stderr.write(f"no fixture named {args.fixture}\n")
            sys.exit(2)

    print("=" * 70)
    print("AGT-901 PIPELINE EVAL RUN")
    print(f"  fixtures:   {len(fixtures)}")
    print(f"  corpus:     {corpus_dir}")
    print(f"  brain log:  {args.brain_log}")
    print("=" * 70)
    print()

    results = []
    total_cost = 0.0

    for i, fixture in enumerate(fixtures, 1):
        fid = fixture["fixture_id"]
        qtype = fixture.get("question_type", "?")
        diff = fixture.get("difficulty", "?")
        print(f"[{i}/{len(fixtures)}] {fid} — {qtype} ({diff})")

        result = score_pipeline_fixture(fixture, corpus_dir)
        results.append(result)

        if result.failed_with_exception:
            print(f"  EXCEPTION: {result.failed_with_exception}", file=sys.stderr)
            continue

        # Persist BrainAnalysisLog row for joinability
        if result.brain_analysis_row:
            append_brain_analysis_row(result.brain_analysis_row,
                                      Path(args.brain_log))

        row = result.brain_analysis_row
        if not args.quiet:
            print(f"  question: {fixture['question'][:80]}...")
            print(f"  brain:    {row['model_used']}, "
                  f"{row['input_tokens']}in/{row['output_tokens']}out, "
                  f"${row['cost_usd_estimate']:.4f}, {row['response_time_ms']}ms")
            print(f"  tools:    {len(row.get('tool_calls_made', []))} "
                  f"({', '.join(tc['tool_name'] for tc in row.get('tool_calls_made', []))})")
            for cr in result.criterion_results:
                marker = "OK" if cr.passed else "XX"
                print(f"  {marker} {cr.name}: {cr.detail}")
        verdict = "PASS" if result.overall_pass else "FAIL"
        print(f"  → {verdict}")
        print()

        total_cost += row.get("cost_usd_estimate", 0.0) if row else 0.0

    print("=" * 70)
    print("AGGREGATE")
    passed = sum(1 for r in results if r.overall_pass)
    failed = len(results) - passed
    print(f"  passed:     {passed}/{len(results)}")
    print(f"  failed:     {failed}/{len(results)}")
    print(f"  total cost: ${total_cost:.4f}")
    if failed:
        print()
        print("FAILURES:")
        for r in results:
            if not r.overall_pass:
                if r.failed_with_exception:
                    print(f"  {r.fixture_id}: EXCEPTION {r.failed_with_exception}")
                else:
                    fails = [c.name for c in r.criterion_results if not c.passed]
                    print(f"  {r.fixture_id}: {fails}")
    print("=" * 70)

    sys.exit(0 if failed == 0 else 1)


if __name__ == "__main__":
    main()
