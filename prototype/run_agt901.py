"""CLI for AGT-901 Pipeline Brain.

Usage:
    python run_agt901.py --question "Why is the SMB segment underperforming?"
    python run_agt901.py    # default question
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

# Allow running from anywhere
sys.path.insert(0, str(Path(__file__).parent))

from agt901 import run_for_pipeline, DEFAULT_QUESTION
from brain_analysis_log import append_row as append_brain_analysis_row


def main():
    parser = argparse.ArgumentParser(description="AGT-901 Pipeline Brain runner")
    parser.add_argument("--corpus", default=str(Path(__file__).parent.parent / "synth" / "corpus"),
                        help="path to synth corpus directory (default: ../synth/corpus)")
    parser.add_argument("--question", default=DEFAULT_QUESTION,
                        help="cohort-level question for the brain")
    parser.add_argument("--brain-log", default=str(Path(__file__).parent / "brain_analysis_log.jsonl"),
                        help="path to BrainAnalysisLog.jsonl")
    parser.add_argument("--no-log", action="store_true",
                        help="don't write BrainAnalysisLog row")
    parser.add_argument("--quiet", action="store_true",
                        help="suppress narrative output, just show metadata")
    args = parser.parse_args()

    corpus_dir = Path(args.corpus)
    if not corpus_dir.exists():
        sys.stderr.write(f"corpus not found: {corpus_dir}\n")
        sys.exit(2)

    print(f"AGT-901 Pipeline Brain", file=sys.stderr)
    print(f"  corpus:   {corpus_dir}", file=sys.stderr)
    print(f"  question: {args.question}", file=sys.stderr)
    print(file=sys.stderr)

    row = run_for_pipeline(corpus_dir, question=args.question)

    if not args.no_log:
        append_brain_analysis_row(row, Path(args.brain_log))
        print(f"BrainAnalysisLog row appended to {args.brain_log}", file=sys.stderr)

    print(f"  model:        {row['model_used']}", file=sys.stderr)
    print(f"  tokens:       {row['input_tokens']}in / {row['output_tokens']}out", file=sys.stderr)
    print(f"  cost:         ${row['cost_usd_estimate']:.4f}", file=sys.stderr)
    print(f"  elapsed:      {row['response_time_ms']}ms", file=sys.stderr)
    print(f"  tool calls:   {len(row['tool_calls_made'])}", file=sys.stderr)
    for tc in row["tool_calls_made"]:
        print(f"    - {tc['tool_name']} → {tc['tool_result_status']}", file=sys.stderr)
    print(f"  actions:      {len(row['proposed_actions'])}", file=sys.stderr)
    for a in row["proposed_actions"]:
        print(f"    - {a.get('action_type')} → {a.get('target', '')[:60]}", file=sys.stderr)

    if not args.quiet:
        print()
        print("=" * 70)
        print("NARRATIVE OUTPUT")
        print("=" * 70)
        print(row["narrative_output"])
        print()
        print("=" * 70)
        print("PROPOSED ACTIONS (full)")
        print("=" * 70)
        print(json.dumps(row["proposed_actions"], indent=2, default=str))


if __name__ == "__main__":
    main()
