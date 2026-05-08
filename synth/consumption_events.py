"""Consumption-event generator — feeds TOOL-015 Consumption-Margin Decomposer.

For consumption-pricing tiered platforms (per-token / per-message / per-API-call
businesses with multi-tier product mix). Generates per-account-quarter consumption
events broken out by:

  - tier:     low_margin / mid_margin / high_margin (generic across products)
  - region:   us-east-1 / us-west-2 / eu-west-1 / ap-southeast-1
  - provider: aws / gcp / azure / on-prem
  - SKU:      consumption_core / consumption_premium / consumption_byoc-control-plane

Output events fit TOOL-015's input contract directly. Per-account corpus block
contains both the raw event log and a summary aggregation for quick eyeballing.

CRITICAL: per the corpus invariant, this generator derives its seed from
sha256(account_id) — does NOT consume from the main rng. Adding this generator
does not shift account UUIDs or break the existing conversation / feature cache.
"""

from __future__ import annotations

import hashlib
import random
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Literal


# ─────────────────────────────────────────────────────────────────────
# Tier + backend pricing model (illustrative, generic)
# ─────────────────────────────────────────────────────────────────────

# Realized GP varies by tier. Low_margin tier is the volume play (50% GP),
# mid_margin is dedicated infrastructure (60% GP), high_margin is BYOC-style
# control-plane (75% GP). All numbers expressed per-unit (where unit is e.g.
# 1M tokens, 1K API calls, 1K messages — opaque to the generator).

TIER_PRICING = {
    "low_margin":  {"list_price_per_unit": 0.60, "backend_cost_per_unit": 0.30},
    "mid_margin":  {"list_price_per_unit": 1.20, "backend_cost_per_unit": 0.48},
    "high_margin": {"list_price_per_unit": 2.40, "backend_cost_per_unit": 0.60},
}

# Region cost multipliers — applied to backend_cost_per_unit. Real CROs feel this:
# us-east is cheapest, ap-southeast and eu-west cost more.
REGION_COST_MULTIPLIER = {
    "us-east-1":      1.00,
    "us-west-2":      1.05,
    "eu-west-1":      1.18,
    "ap-southeast-1": 1.25,
}

# Provider cost multipliers — on top of region. AWS is baseline; GCP/Azure carry
# slight premiums; on-prem is cheaper but rarely used in early-stage platforms.
PROVIDER_COST_MULTIPLIER = {
    "aws":    1.00,
    "gcp":    1.04,
    "azure":  1.06,
    "on-prem": 0.85,
}

# SKU labels per tier (illustrative — opaque semantics to TOOL-015)
SKU_BY_TIER = {
    "low_margin":  "consumption_core_shared",
    "mid_margin":  "consumption_dedicated",
    "high_margin": "consumption_byoc_control_plane",
}


# ─────────────────────────────────────────────────────────────────────
# Profile — archetype-driven
# ─────────────────────────────────────────────────────────────────────

@dataclass
class ConsumptionProfile:
    """Drives consumption-event mix per account.

    tier_mix: weights summing to ~1.0 across (low/mid/high). Defines what
              fraction of consumption volume the account runs on each tier.
    region_mix: weights summing to ~1.0 across regions. Multi-region orgs
                spread across 2-4 regions; single-region stays focused.
    provider_mix: weights summing to ~1.0 across providers. Most accounts
                  are single-cloud (~95% on aws); some multi-cloud.
    discount_pct: 0-1 — applied to list price for realized price (commit-tier
                  discount, larger for larger-deal accounts).
    quarterly_volume_baseline: total units for a typical quarter (units
                               opaque to generator — could be 1M tokens,
                               1K API calls, etc.).
    quarterly_growth_rate: pct per quarter (e.g., 0.15 = +15% q/q).
    backend_cost_attribution_completeness: 0-1 — what fraction of events
                                           have backend_cost_per_unit data.
                                           Sub-90% triggers TOOL-015 refusal
                                           per spec.
    """
    tier_mix: dict[str, float]
    region_mix: dict[str, float]
    provider_mix: dict[str, float]
    discount_pct: float
    quarterly_volume_baseline: float
    quarterly_growth_rate: float
    backend_cost_attribution_completeness: float


# Archetype defaults — these mirror the Account-archetype names in archetypes.py.
# Each archetype produces a distinctive tier/region/cost pattern so TOOL-015 can
# decompose meaningfully.
PROFILE_DEFAULTS_BY_ARCHETYPE: dict[str, ConsumptionProfile] = {

    "ideal_power_user": ConsumptionProfile(
        # Mid-tier-heavy, on dedicated infra. Multi-region. Reasonable discount.
        tier_mix={"low_margin": 0.20, "mid_margin": 0.55, "high_margin": 0.25},
        region_mix={"us-east-1": 0.50, "us-west-2": 0.30, "eu-west-1": 0.20},
        provider_mix={"aws": 0.85, "gcp": 0.15},
        discount_pct=0.18,
        quarterly_volume_baseline=120000,
        quarterly_growth_rate=0.18,
        backend_cost_attribution_completeness=0.99,
    ),

    "activating": ConsumptionProfile(
        # Low-tier-heavy (just got started, on shared). Single region. Light discount.
        tier_mix={"low_margin": 0.85, "mid_margin": 0.15, "high_margin": 0.0},
        region_mix={"us-east-1": 1.0},
        provider_mix={"aws": 1.0},
        discount_pct=0.05,
        quarterly_volume_baseline=15000,
        quarterly_growth_rate=0.45,
        backend_cost_attribution_completeness=0.97,
    ),

    "surface_only_adopter": ConsumptionProfile(
        # Low-tier-heavy, flat consumption. Single region. Light discount.
        # Tier-migration candidate? No — flat consumption means low GP uplift potential.
        tier_mix={"low_margin": 0.90, "mid_margin": 0.10, "high_margin": 0.0},
        region_mix={"us-east-1": 0.70, "us-west-2": 0.30},
        provider_mix={"aws": 1.0},
        discount_pct=0.10,
        quarterly_volume_baseline=22000,
        quarterly_growth_rate=0.02,
        backend_cost_attribution_completeness=0.96,
    ),

    "champion_loss_decliner": ConsumptionProfile(
        # Was mid-tier-heavy, sliding back to low-tier as champion departed.
        # Real risk: usage drops on dedicated infrastructure during decline.
        tier_mix={"low_margin": 0.55, "mid_margin": 0.40, "high_margin": 0.05},
        region_mix={"us-east-1": 0.55, "us-west-2": 0.45},
        provider_mix={"aws": 1.0},
        discount_pct=0.20,
        quarterly_volume_baseline=85000,
        quarterly_growth_rate=-0.08,
        backend_cost_attribution_completeness=0.98,
    ),

    "expansion_ready": ConsumptionProfile(
        # MID + HIGH tier already in use, growing fast. Strong tier-migration
        # candidate — the expansion play that TOOL-015 should surface meaningfully.
        tier_mix={"low_margin": 0.10, "mid_margin": 0.55, "high_margin": 0.35},
        region_mix={"us-east-1": 0.40, "us-west-2": 0.30, "eu-west-1": 0.20, "ap-southeast-1": 0.10},
        provider_mix={"aws": 0.70, "gcp": 0.20, "azure": 0.10},
        discount_pct=0.22,
        quarterly_volume_baseline=180000,
        quarterly_growth_rate=0.32,
        backend_cost_attribution_completeness=0.99,
    ),

    "spike_then_crash": ConsumptionProfile(
        # Looks like expansion but it was a one-time event. Low-tier-heavy mix
        # with a recent volume spike followed by reversion.
        tier_mix={"low_margin": 0.75, "mid_margin": 0.25, "high_margin": 0.0},
        region_mix={"us-east-1": 1.0},
        provider_mix={"aws": 1.0},
        discount_pct=0.08,
        quarterly_volume_baseline=45000,
        quarterly_growth_rate=0.05,   # mild apparent growth across full window
        backend_cost_attribution_completeness=0.94,
    ),

    "seasonal": ConsumptionProfile(
        # Predictable cycle. Mixed-tier. Multi-region for global retail/etc.
        tier_mix={"low_margin": 0.40, "mid_margin": 0.45, "high_margin": 0.15},
        region_mix={"us-east-1": 0.40, "us-west-2": 0.20, "eu-west-1": 0.25, "ap-southeast-1": 0.15},
        provider_mix={"aws": 0.75, "azure": 0.25},
        discount_pct=0.15,
        quarterly_volume_baseline=95000,
        quarterly_growth_rate=0.0,    # net-flat across cycle
        backend_cost_attribution_completeness=0.97,
    ),

    "stalled_onboarding": ConsumptionProfile(
        # Never activated. Low-tier-only. Single region. Heavy discount (deal incentive).
        # Backend cost attribution intentionally weak — surfaces TOOL-015 refusal in eval.
        tier_mix={"low_margin": 1.0, "mid_margin": 0.0, "high_margin": 0.0},
        region_mix={"us-east-1": 1.0},
        provider_mix={"aws": 1.0},
        discount_pct=0.30,
        quarterly_volume_baseline=4500,
        quarterly_growth_rate=-0.10,
        backend_cost_attribution_completeness=0.78,   # below 90% — refusal trigger
    ),
}


# ─────────────────────────────────────────────────────────────────────
# Generator
# ─────────────────────────────────────────────────────────────────────

def _seed_for_account(account_id: str, salt: str = "consumption") -> int:
    """Stable per-account-per-module seed. Independent of main rng."""
    return int(hashlib.sha256(f"{account_id}|{salt}".encode()).hexdigest()[:8], 16)


def _weighted_choice(rng: random.Random, weights: dict[str, float]) -> str:
    keys = list(weights.keys())
    vals = list(weights.values())
    return rng.choices(keys, weights=vals, k=1)[0]


def generate_consumption_events(
    account_id: str,
    archetype_key: str,
    contract_start: datetime,
    contract_age_days: int,
    arr_usd: float,
) -> dict:
    """Build the consumption-event log + summary for one account."""
    profile = PROFILE_DEFAULTS_BY_ARCHETYPE.get(
        archetype_key, PROFILE_DEFAULTS_BY_ARCHETYPE["ideal_power_user"]
    )
    rng = random.Random(_seed_for_account(account_id))

    # ARR scaling — bigger accounts have higher consumption baseline
    arr_scale = max(0.3, min(4.0, arr_usd / 250000.0))
    quarterly_volume = profile.quarterly_volume_baseline * arr_scale

    # Trailing 4 quarters of events from contract_start + contract_age_days
    snapshot_date = contract_start + timedelta(days=contract_age_days)
    quarter_starts: list[datetime] = []
    for q in range(4):
        qs = snapshot_date - timedelta(days=90 * (4 - q))
        qs = max(qs, contract_start)
        quarter_starts.append(qs)

    events: list[dict] = []
    for q_idx, qs in enumerate(quarter_starts):
        # Volume grows quarter-over-quarter per growth rate
        q_volume = quarterly_volume * ((1.0 + profile.quarterly_growth_rate) ** q_idx)
        # spike_then_crash: inflate Q3 volume, deflate Q4 toward baseline
        if archetype_key == "spike_then_crash":
            if q_idx == 2:
                q_volume *= 2.4
            elif q_idx == 3:
                q_volume *= 0.7
        # Seasonal: Q4 spike on retail/etc. — apply if seasonal archetype
        if archetype_key == "seasonal" and q_idx == 3:
            q_volume *= 1.6

        # Generate 30-90 events per quarter (varies per account size)
        events_per_quarter = max(20, int(quarterly_volume / 800))
        for _ in range(events_per_quarter):
            tier = _weighted_choice(rng, profile.tier_mix)
            region = _weighted_choice(rng, profile.region_mix)
            provider = _weighted_choice(rng, profile.provider_mix)
            sku = SKU_BY_TIER[tier]

            # Volume per event — distribute q_volume across the events with noise
            base_units = q_volume / events_per_quarter
            units = round(base_units * rng.uniform(0.6, 1.4), 2)

            list_price = TIER_PRICING[tier]["list_price_per_unit"]
            realized_price = round(list_price * (1.0 - profile.discount_pct), 4)

            # Backend cost: tier base × region × provider, with some volatility
            base_backend = TIER_PRICING[tier]["backend_cost_per_unit"]
            backend_cost_per_unit = round(
                base_backend
                * REGION_COST_MULTIPLIER[region]
                * PROVIDER_COST_MULTIPLIER[provider]
                * rng.uniform(0.95, 1.08),
                4,
            )
            # Refusal-trigger pattern: drop backend_cost_per_unit for some events
            if rng.random() > profile.backend_cost_attribution_completeness:
                backend_cost_per_unit = None  # missing data

            # Random offset within the quarter
            offset_days = rng.uniform(0, 89)
            metered_at = qs + timedelta(days=offset_days)

            events.append({
                "event_id": str(uuid.UUID(int=rng.getrandbits(128))),
                "sku": sku,
                "tier": tier,
                "units": units,
                "list_price_per_unit_usd": list_price,
                "realized_price_per_unit_usd": realized_price,
                "backend_region": region,
                "backend_provider": provider,
                "backend_cost_per_unit_usd": backend_cost_per_unit,
                "metered_at": metered_at.isoformat() + "Z",
                "quarter_index": q_idx,
            })

    # Sort by metered_at for realism
    events.sort(key=lambda e: e["metered_at"])

    # Summary aggregation (deterministic from the events)
    total_revenue = sum(
        e["units"] * e["realized_price_per_unit_usd"] for e in events
    )
    total_backend_cost = sum(
        e["units"] * e["backend_cost_per_unit_usd"]
        for e in events if e["backend_cost_per_unit_usd"] is not None
    )
    realized_gp = total_revenue - total_backend_cost
    realized_gp_pct = realized_gp / total_revenue if total_revenue > 0 else 0.0

    backend_cost_coverage = sum(
        1 for e in events if e["backend_cost_per_unit_usd"] is not None
    ) / max(1, len(events))

    spend_by_tier: dict[str, float] = {}
    for e in events:
        spend_by_tier[e["tier"]] = spend_by_tier.get(e["tier"], 0) + (
            e["units"] * e["realized_price_per_unit_usd"]
        )

    spend_by_region: dict[str, float] = {}
    for e in events:
        spend_by_region[e["backend_region"]] = spend_by_region.get(e["backend_region"], 0) + (
            e["units"] * e["realized_price_per_unit_usd"]
        )

    return {
        "consumption_events": events,
        "consumption_summary": {
            "total_events": len(events),
            "total_revenue_usd": round(total_revenue, 2),
            "total_backend_cost_usd": round(total_backend_cost, 2),
            "realized_gp_usd": round(realized_gp, 2),
            "realized_gp_pct": round(realized_gp_pct, 4),
            "backend_cost_coverage_pct": round(backend_cost_coverage, 4),
            "spend_by_tier": {k: round(v, 2) for k, v in spend_by_tier.items()},
            "spend_by_region": {k: round(v, 2) for k, v in spend_by_region.items()},
            "tier_mix_label": _classify_tier_mix(spend_by_tier),
            "tool15_refusal_expected": backend_cost_coverage < 0.90,
        },
        "consumption_profile_used": archetype_key,
    }


def _classify_tier_mix(spend_by_tier: dict[str, float]) -> str:
    """Match TOOL-015's expected current_tier_mix_label output values."""
    total = sum(spend_by_tier.values())
    if total == 0:
        return "unknown"
    low = spend_by_tier.get("low_margin", 0) / total
    high = spend_by_tier.get("high_margin", 0) / total
    if low > 0.65:
        return "low-margin-heavy"
    if high > 0.30:
        return "high-margin-heavy"
    return "balanced"
