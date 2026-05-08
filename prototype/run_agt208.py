"""CLI entry for AGT-208 Developer Signal Scorer.

Examples (from any CWD):
    prototype/run_agt208.sh                              # all 50 accounts, default
    prototype/run_agt208.sh --limit 5                    # first 5 accounts only
    prototype/run_agt208.sh --archetype expansion_ready  # only one archetype
    prototype/run_agt208.sh --account "Stark Labs"       # single account by name
    prototype/run_agt208.sh --no-ae-briefs               # skip Haiku AE briefs

Output: prototype/developer_signal_log.jsonl (append-only, jsonl).
Console summary: tier distribution + cost totals.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import defaultdict
from pathlib import Path

# Ensure prototype/ is on sys.path
SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR))

from agt208 import score_account, write_to_log


CORPUS_DIR = SCRIPT_DIR.parent / "synth" / "corpus"


def load_account_corpus(account_id: str) -> dict | None:
    p = CORPUS_DIR / f"{account_id}.json"
    if not p.exists():
        return None
    return json.loads(p.read_text())


def select_accounts(args) -> list[dict]:
    gt = json.loads((CORPUS_DIR / "ground_truth.json").read_text())
    accounts = gt["accounts"]
    if args.archetype:
        accounts = [a for a in accounts if a["archetype_key"] == args.archetype]
    if args.account:
        accounts = [a for a in accounts if args.account.lower() in a["company_name"].lower()]
    if args.limit:
        accounts = accounts[: args.limit]
    return accounts


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--limit", type=int, help="cap on accounts processed")
    parser.add_argument("--archetype", type=str, help="filter to one archetype")
    parser.add_argument("--account", type=str, help="case-insensitive substring on company_name")
    parser.add_argument("--no-ae-briefs", dest="ae_briefs", action="store_false",
                        help="skip Haiku AE brief assembly (fully deterministic)")
    parser.add_argument("--ae-brief-max-devs", type=int, default=3,
                        help="max handoff-priority devs to brief per account")
    parser.add_argument("--quiet", action="store_true", help="suppress per-account console output")
    parser.set_defaults(ae_briefs=True)
    args = parser.parse_args()

    selection = select_accounts(args)
    if not selection:
        print("no accounts selected (check filters)")
        sys.exit(1)

    print(f"AGT-208 batch: {len(selection)} account(s) | "
          f"ae_briefs={'on' if args.ae_briefs else 'off'} | "
          f"max_priority_briefs_per_account={args.ae_brief_max_devs}")

    aggregate_tier_dist: dict[str, int] = defaultdict(int)
    n_contradicts = 0
    total_input_tokens = 0
    total_output_tokens = 0
    n_processed = 0

    for a in selection:
        account_id = a["account_id"]
        corpus_data = load_account_corpus(account_id)
        if corpus_data is None:
            if not args.quiet:
                print(f"  skip {account_id} — corpus file missing")
            continue
        result = score_account(
            corpus_data,
            enable_ae_brief=args.ae_briefs,
            ae_brief_max_devs=args.ae_brief_max_devs,
        )
        write_to_log(result)
        n_processed += 1

        for tier, count in result.get("tier_distribution", {}).items():
            aggregate_tier_dist[tier] += count
        n_contradicts += result.get("n_contradicts_agt201", 0)
        cost = result.get("_llm_brief_cost_tokens") or {}
        total_input_tokens += cost.get("input", 0)
        total_output_tokens += cost.get("output", 0)

        if not args.quiet:
            tier_str = " | ".join(
                f"{t}:{c}" for t, c in sorted(
                    result.get("tier_distribution", {}).items(),
                    key=lambda kv: -kv[1],
                )
            )
            agg = result.get("account_aggregate", {})
            override = " ⚡override" if agg.get("domain_override_triggered") else ""
            print(
                f"  {result['company_name']:30s} "
                f"[{result['archetype']:25s}] "
                f"acct={agg.get('account_tier','?'):16s}{override:9s} "
                f"devs[{tier_str}]"
            )

    # Final summary
    print("─" * 70)
    print(f"Processed: {n_processed} accounts")
    print(f"Total developer-signal rows in log: ~{sum(aggregate_tier_dist.values())}")
    print("Aggregate tier distribution across all developers:")
    for t in ("handoff-priority", "handoff-warm", "monitor", "stay-self-serve"):
        print(f"  {t:18s} {aggregate_tier_dist.get(t, 0):4d}")
    print(f"contradicts_agt201 flags: {n_contradicts}")
    if args.ae_briefs:
        # Haiku pricing approx — input $1/M, output $5/M (from anthropic pricing)
        cost_in = total_input_tokens / 1_000_000 * 1.0
        cost_out = total_output_tokens / 1_000_000 * 5.0
        total_cost = cost_in + cost_out
        print(f"AE brief tokens: in={total_input_tokens} out={total_output_tokens} "
              f"≈ ${total_cost:.4f} (Haiku)")
    print(f"Output: {(SCRIPT_DIR / 'developer_signal_log.jsonl').relative_to(SCRIPT_DIR.parent)}")


if __name__ == "__main__":
    main()
