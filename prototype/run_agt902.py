"""CLI entry point for the AGT-902 Account Brain stub.

Examples:

    # Run on one specific account (UUID prefix is enough)
    python3 run_agt902.py --account 026a4a59

    # Run on the first N corpus accounts (each is a separate API call)
    python3 run_agt902.py --batch --limit 5

    # Override the question
    python3 run_agt902.py --account Pendant_Logistics \\
        --question "Why is this account at renewal risk and what's the play?"

    # Filter by archetype
    python3 run_agt902.py --batch --archetype champion_loss_decliner

Output:
  - One BrainAnalysisLog row per analyzed account, appended to
    prototype/brain_analysis_log.jsonl
  - Validation issues printed to stderr
  - Summary stats to stdout
"""

from __future__ import annotations

import argparse
import glob
import json
import os
import sys
import time
from pathlib import Path

# Allow imports of agt902 / validation / brain_analysis_log when running
# this script from any directory.
_HERE = Path(__file__).parent.resolve()
if str(_HERE) not in sys.path:
    sys.path.insert(0, str(_HERE))

from agt902 import run_for_account, DEFAULT_QUESTION
from view_source import default_source
from validation import validate_all
from brain_analysis_log import append_row, DEFAULT_LOG_PATH


# ─────────────────────────────────────────────────────────────────────
# Account resolution
# ─────────────────────────────────────────────────────────────────────

def find_account_files(corpus_dir: Path,
                       account: str | None,
                       archetype: str | None,
                       limit: int | None) -> list[Path]:
    """Resolve --account / --archetype / --limit into a list of corpus file paths.

    --account matches if the user-provided value is a substring of either:
      - the account_id (UUID)
      - the company_name
    """
    all_files = sorted(p for p in corpus_dir.glob("*.json") if p.name != "ground_truth.json")

    if account:
        account_lower = account.lower().replace("_", " ")
        matches = []
        for path in all_files:
            with path.open() as f:
                data = json.load(f)
            if (account.lower() in path.stem.lower()
                    or account_lower in data["account"]["company_name"].lower()):
                matches.append(path)
        if not matches:
            raise SystemExit(f"No account found matching '{account}'")
        return matches

    if archetype:
        matches = []
        for path in all_files:
            with path.open() as f:
                data = json.load(f)
            if data.get("archetype_key") == archetype:
                matches.append(path)
        if not matches:
            raise SystemExit(f"No accounts with archetype '{archetype}'")
        return matches[:limit] if limit else matches

    return all_files[:limit] if limit else all_files


# ─────────────────────────────────────────────────────────────────────
# Per-account execution
# ─────────────────────────────────────────────────────────────────────

def run_one(corpus_path: Path, question: str, log_path: Path) -> dict:
    """Run AGT-902 on one corpus file, write to BrainAnalysisLog, return metadata."""
    with corpus_path.open() as f:
        data = json.load(f)
    company = data["account"]["company_name"]
    archetype = data.get("archetype_key", "?")
    expected = data.get("expected_outcome_label", "?")

    print(f"\n[{company}] archetype={archetype}, expected_outcome={expected}")

    t0 = time.time()
    try:
        row = run_for_account(corpus_path, question, source=default_source())
    except Exception as e:
        print(f"  FAILED: {type(e).__name__}: {e}", file=sys.stderr)
        return {"failed": True, "company": company}
    elapsed = time.time() - t0

    # Validate
    validation = validate_all({
        "narrative_output":            row["narrative_output"],
        "sources_read":                row["sources_read"],
        "proposed_actions":            row["proposed_actions"],
        "confidence_flags":            row["confidence_flags"],
        "data_staleness_acknowledged": row["data_staleness_acknowledged"],
        "stale_sources":               row["stale_sources"],
    })

    # Append to BrainAnalysisLog
    row["_meta_validation"] = {
        "issue_count":            len(validation.issues),
        "hard_failure":           validation.has_hard_failure,
        "citation_count":         validation.citation_count,
        "proposed_action_count":  validation.proposed_action_count,
        "confidence_flag_count":  validation.confidence_flag_count,
        "issues":                 [str(i) for i in validation.issues],
    }
    append_row(row, log_path)

    # Console summary
    print(f"  model:    {row['model_used']}")
    print(f"  tokens:   in={row['input_tokens']}, out={row['output_tokens']}")
    print(f"  cost:     ${row['cost_usd_estimate']:.4f}")
    print(f"  latency:  {row['response_time_ms']}ms (wall: {elapsed:.1f}s)")
    print(f"  citations: {validation.citation_count}, "
          f"actions: {validation.proposed_action_count}, "
          f"confidence_flags: {validation.confidence_flag_count}")
    if validation.issues:
        print(f"  validation issues:")
        for issue in validation.issues:
            print(f"    {issue}", file=sys.stderr)
    else:
        print(f"  validation: clean")

    return {
        "failed":       False,
        "company":      company,
        "archetype":    archetype,
        "expected":     expected,
        "row":          row,
        "validation":   validation,
    }


# ─────────────────────────────────────────────────────────────────────
# Main
# ─────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description="Run AGT-902 Account Brain on corpus accounts.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument("--account", type=str, default=None,
                        help="filter to one account (UUID prefix or company_name substring)")
    parser.add_argument("--archetype", type=str, default=None,
                        help="filter to all accounts of this archetype")
    parser.add_argument("--batch", action="store_true",
                        help="process multiple accounts (use with --limit / --archetype)")
    parser.add_argument("--limit", type=int, default=None,
                        help="cap the number of accounts processed in batch mode")
    parser.add_argument("--question", type=str, default=DEFAULT_QUESTION,
                        help=f"the brain query (default: {DEFAULT_QUESTION!r})")
    parser.add_argument("--corpus", type=Path,
                        default=Path(__file__).parent.parent / "synth" / "corpus",
                        help="path to corpus directory (default: ../synth/corpus)")
    parser.add_argument("--log", type=Path,
                        default=Path(__file__).parent / "brain_analysis_log.jsonl",
                        help="BrainAnalysisLog output path")
    args = parser.parse_args()

    if not os.environ.get("ANTHROPIC_API_KEY"):
        sys.stderr.write("ERROR: ANTHROPIC_API_KEY not set in environment.\n")
        raise SystemExit(1)

    if not args.corpus.is_dir():
        raise SystemExit(f"Corpus directory not found: {args.corpus}")

    files = find_account_files(args.corpus, args.account, args.archetype, args.limit)

    if not args.batch and len(files) > 1 and not args.account:
        # Default safety: don't accidentally process all 50 without --batch
        files = files[:1]
        print(f"NOTE: processing 1 of {len(files)} matched accounts. Use --batch to process more.\n")

    print(f"Running AGT-902 on {len(files)} account(s) → {args.log}")
    print(f"Question: {args.question}")

    aggregate = {"total": 0, "failed": 0, "hard_validation_failures": 0,
                 "total_cost": 0.0, "total_input_tokens": 0, "total_output_tokens": 0}

    for path in files:
        result = run_one(path, args.question, args.log)
        aggregate["total"] += 1
        if result["failed"]:
            aggregate["failed"] += 1
            continue
        aggregate["total_cost"] += result["row"]["cost_usd_estimate"]
        aggregate["total_input_tokens"] += result["row"]["input_tokens"]
        aggregate["total_output_tokens"] += result["row"]["output_tokens"]
        if result["validation"].has_hard_failure:
            aggregate["hard_validation_failures"] += 1

    print()
    print("=" * 60)
    print(f"Done. Processed {aggregate['total']} accounts.")
    print(f"  Failed:                       {aggregate['failed']}")
    print(f"  Hard validation failures:     {aggregate['hard_validation_failures']}")
    print(f"  Total tokens (in/out):        {aggregate['total_input_tokens']} / {aggregate['total_output_tokens']}")
    print(f"  Total cost (estimate):        ${aggregate['total_cost']:.4f}")
    print(f"  BrainAnalysisLog appended to: {args.log}")


if __name__ == "__main__":
    main()
