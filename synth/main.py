"""Orchestrator for synthetic GTM-OS corpus generation.

Reads archetypes, generates ~50 accounts spanning the archetype distribution,
runs each archetype through the usage / health / payments generators, and
writes one JSON file per account plus a ground_truth.json mapping.

Usage:
    cd /Users/connorkasser/gtm-os/synth
    python main.py                      # default seed=42, ~50 accounts
    python main.py --seed 1234 --n 100  # custom seed + count

Output goes to synth/corpus/.
"""

from __future__ import annotations

import argparse
import json
import os
import random
import uuid
from datetime import datetime, timedelta
from pathlib import Path

from archetypes import ARCHETYPES, DEFAULT_ARCHETYPE_WEIGHTS, Archetype
from usage import generate_usage_log
from health import generate_health_log
from payments import generate_payment_events
from feature_engagement import generate_feature_engagement


# ─────────────────────────────────────────────────────────────────────
# Account base generation
# ─────────────────────────────────────────────────────────────────────

# Pool of fictional company-name fragments — keeps anonymization clean.
_NAME_PREFIXES = [
    "Acme", "Globex", "Initech", "Hooli", "Pied Piper", "Vandelay",
    "Wonka", "Stark", "Nakatomi", "Cyberdyne", "Aperture", "Tyrell",
    "Soylent", "Massive Dynamic", "Dunder Mifflin", "Strickland",
    "Pendant", "Bluth", "Sterling", "Northwind",
]
_NAME_SUFFIXES = [
    "Industries", "Logistics", "Holdings", "Systems", "Labs",
    "Group", "Partners", "Solutions", "Networks", "Analytics",
]


def _weighted_choice(rng: random.Random, weights: dict) -> str:
    """Sample a key from a weight dict (weights normalized internally)."""
    keys = list(weights.keys())
    vals = list(weights.values())
    return rng.choices(keys, weights=vals, k=1)[0]


def _generate_company_name(rng: random.Random, used: set[str]) -> str:
    """Generate a unique fictional company name. Loops on collision."""
    for _ in range(50):
        name = f"{rng.choice(_NAME_PREFIXES)} {rng.choice(_NAME_SUFFIXES)}"
        if name not in used:
            used.add(name)
            return name
    # Fallback: append a number
    return f"{rng.choice(_NAME_PREFIXES)} {rng.choice(_NAME_SUFFIXES)} {rng.randint(100, 999)}"


def generate_account_base(
    archetype: Archetype,
    rng: random.Random,
    used_names: set[str],
) -> dict:
    """Generate the base Account record for one synthetic account."""
    account_id = str(uuid.uuid4())
    company = _generate_company_name(rng, used_names)
    segment = _weighted_choice(rng, archetype.segment_distribution)
    vertical = _weighted_choice(rng, archetype.vertical_distribution)
    tier = _weighted_choice(rng, archetype.icp_tier_distribution)
    term_months = int(_weighted_choice(rng,
        {str(k): v for k, v in archetype.term_months_distribution.items()}))

    arr_min, arr_max = archetype.arr_range_usd
    arr = round(rng.uniform(arr_min, arr_max), 2)
    seat_min, seat_max = archetype.licensed_seats_range
    licensed_seats = rng.randint(seat_min, seat_max)

    age_min, age_max = archetype.contract_age_range_days
    contract_age_days = rng.randint(age_min, age_max)

    # Anchor "now" at the date this script runs; contract start is "now" minus age
    now = datetime.utcnow().replace(microsecond=0)
    contract_start = now - timedelta(days=contract_age_days)
    contract_end = contract_start + timedelta(days=term_months * 30)

    return {
        "account_id": account_id,
        "company_name": company,
        "segment": segment,
        "vertical": vertical,
        "icp_tier": tier,
        "arr_usd": arr,
        "term_months": term_months,
        "licensed_seats": licensed_seats,
        "contract_start_date": contract_start.date().isoformat(),
        "contract_end_date": contract_end.date().isoformat(),
        "contract_age_days_at_corpus_gen": contract_age_days,
    }


# ─────────────────────────────────────────────────────────────────────
# Per-account corpus assembly
# ─────────────────────────────────────────────────────────────────────

def generate_account_corpus(
    archetype_key: str,
    archetype: Archetype,
    rng: random.Random,
    used_names: set[str],
) -> dict:
    """Build the full per-account composite: base + usage + health + payments."""
    account = generate_account_base(archetype, rng, used_names)
    contract_start = datetime.fromisoformat(account["contract_start_date"])
    contract_age = account["contract_age_days_at_corpus_gen"]

    sku_id = "consumption_core"
    usage = generate_usage_log(
        account["account_id"], sku_id, contract_start, contract_age,
        archetype.usage, rng,
    )
    health = generate_health_log(
        account["account_id"], contract_start, contract_age,
        archetype.health, rng,
    )
    payments = generate_payment_events(
        account["account_id"], contract_start, contract_age,
        archetype.health, rng,
    )
    snapshot_date = contract_start + timedelta(days=contract_age)
    # Derive the feature seed from account_id (NOT the main rng) so adding
    # this generator doesn't shift the rng sequence and break account UUIDs
    # / conversation cache invariance. Use hashlib for cross-run determinism
    # (Python's built-in hash() is randomized per process by default).
    import hashlib
    feature_seed = int(
        hashlib.sha256(account["account_id"].encode()).hexdigest()[:8], 16
    )
    feature_block = generate_feature_engagement(
        archetype.feature, contract_start, snapshot_date,
        active_seats=account["licensed_seats"],
        seed=feature_seed,
    )

    return {
        "account": account,
        "archetype_key": archetype_key,
        "expected_outcome_label": archetype.expected_outcome_label,
        "usage_metering_log": usage,
        "customer_health_log": health,
        "payment_event_log": payments,
        "feature_engagement": feature_block["feature_engagement_telemetry"],
        "feature_engagement_ground_truth_pattern": feature_block["ground_truth_pattern"],
        # Convenience aggregates for quick eyeballing — recomputable from raw rows
        "summary": {
            "total_units_consumed": round(sum(r["units_consumed"] for r in usage), 2),
            "total_overage_units": round(sum(r["overage_units"] for r in usage), 2),
            "final_health_score": health[-1]["score"] if health else None,
            "final_health_tier": health[-1]["tier"] if health else None,
            "payment_events_count": len(payments),
            "final_payment_state": payments[-1]["new_state"] if payments else "current",
        },
    }


# ─────────────────────────────────────────────────────────────────────
# Main
# ─────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--n", type=int, default=50, help="number of accounts to generate")
    parser.add_argument("--out", type=str, default="corpus", help="output directory")
    args = parser.parse_args()

    rng = random.Random(args.seed)
    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)

    used_names: set[str] = set()
    archetype_keys = list(DEFAULT_ARCHETYPE_WEIGHTS.keys())
    archetype_weights = list(DEFAULT_ARCHETYPE_WEIGHTS.values())

    ground_truth: list[dict] = []
    archetype_counts: dict[str, int] = {k: 0 for k in archetype_keys}

    for i in range(args.n):
        archetype_key = rng.choices(archetype_keys, weights=archetype_weights, k=1)[0]
        archetype = ARCHETYPES[archetype_key]
        archetype_counts[archetype_key] += 1

        corpus = generate_account_corpus(archetype_key, archetype, rng, used_names)
        account_id = corpus["account"]["account_id"]
        company = corpus["account"]["company_name"]

        out_path = out_dir / f"{account_id}.json"
        with out_path.open("w") as f:
            json.dump(corpus, f, indent=2)

        ground_truth.append({
            "account_id": account_id,
            "company_name": company,
            "archetype_key": archetype_key,
            "expected_outcome_label": archetype.expected_outcome_label,
            "summary": corpus["summary"],
        })

    # Ground-truth index for eval-harness use
    with (out_dir / "ground_truth.json").open("w") as f:
        json.dump({
            "seed": args.seed,
            "account_count": args.n,
            "generated_at": datetime.utcnow().isoformat() + "Z",
            "archetype_distribution": archetype_counts,
            "accounts": ground_truth,
        }, f, indent=2)

    # Console summary
    print(f"Generated {args.n} accounts → {out_dir}/")
    print(f"  seed: {args.seed}")
    print("  archetype distribution:")
    for k in archetype_keys:
        print(f"    {k:28s} {archetype_counts[k]:3d}")
    print(f"  ground truth: {out_dir}/ground_truth.json")


if __name__ == "__main__":
    main()
