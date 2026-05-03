"""Quick spot-check on the generated corpus.

Run after main.py to verify archetypes produce internally-consistent data.
Reads corpus/*.json and prints one example per archetype.

Usage:
    python3 inspect_corpus.py
"""

from __future__ import annotations

import glob
import json


def main():
    files = sorted(glob.glob("corpus/*.json"))
    files = [f for f in files if "ground_truth" not in f]
    print(f"account files: {len(files)}")
    print()

    by_archetype: dict[str, list[dict]] = {}
    for f in files:
        with open(f) as fh:
            a = json.load(fh)
        by_archetype.setdefault(a["archetype_key"], []).append(a)

    show_order = [
        "ideal_power_user",
        "activating",
        "expansion_ready",
        "champion_loss_decliner",
        "spike_then_crash",
        "seasonal",
        "surface_only_adopter",
        "stalled_onboarding",
    ]

    for key in show_order:
        if key not in by_archetype:
            continue
        a = by_archetype[key][0]
        s = a["summary"]
        acc = a["account"]
        print(f"{key}:")
        print(f"  company:               {acc['company_name']}")
        print(f"  segment / vertical:    {acc['segment']} / {acc['vertical']}")
        print(f"  arr_usd:               ${acc['arr_usd']:,.0f}")
        print(f"  contract_age_days:     {acc['contract_age_days_at_corpus_gen']}")
        print(f"  total_units_consumed:  {s['total_units_consumed']:,.1f}")
        print(f"  total_overage_units:   {s['total_overage_units']:,.1f}")
        print(f"  final_health_score:    {s['final_health_score']}")
        print(f"  final_health_tier:     {s['final_health_tier']}")
        print(f"  payment_events_count:  {s['payment_events_count']}")
        print(f"  final_payment_state:   {s['final_payment_state']}")
        if "call_count" in s:
            roles = s.get("call_count_by_role", {})
            roles_str = ", ".join(f"{r}={c}" for r, c in sorted(roles.items()))
            print(f"  call_count:            {s['call_count']} ({roles_str})")
            # Show a sample transcript_summary to spot-check archetype alignment
            calls = a.get("conversation_intelligence_log", [])
            if calls:
                first = calls[0]
                last = calls[-1]
                print(f"  first call:            [{first['call_owner_role']}, {first['overall_sentiment']}] \"{first['transcript_summary'][:100]}...\"")
                if len(calls) > 1:
                    print(f"  last call:             [{last['call_owner_role']}, {last['overall_sentiment']}] \"{last['transcript_summary'][:100]}...\"")
        print(f"  expected_outcome:      {a['expected_outcome_label']}")
        print()


if __name__ == "__main__":
    main()
