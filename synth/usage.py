"""Generate UsageMeteringLog rows for one (account, SKU) over its contract age.

Reads UsageProfile from archetypes.py. Produces daily-granularity rows
matching the UsageMeteringLog production schema. Numerical only — no LLM.

Pattern types implemented:
  linear       baseline + (day_offset * growth_rate)
  exponential  baseline * (1 + growth_rate) ^ day_offset
  flat         baseline (with volatility noise)
  seasonal     baseline * (1 + 0.3 * sin(2pi * day / period))
  cliff        baseline up to cliff_event_day, then magnitude * baseline,
               with optional revert at cliff_recovery_day

All patterns get gaussian volatility noise per day.
"""

from __future__ import annotations

import math
import random
from datetime import datetime, timedelta
from typing import Optional
import uuid

from archetypes import UsageProfile


def _baseline_at_day(profile: UsageProfile, day_offset: int) -> float:
    """Compute the deterministic baseline for a given day, before noise."""
    if profile.pattern_type == "linear":
        return profile.baseline_daily_units + day_offset * profile.growth_rate_per_day

    if profile.pattern_type == "exponential":
        return profile.baseline_daily_units * math.pow(1 + profile.growth_rate_per_day, day_offset)

    if profile.pattern_type == "flat":
        return profile.baseline_daily_units

    if profile.pattern_type == "seasonal":
        period = profile.seasonality_period_days or 90
        seasonal_mult = 1 + 0.3 * math.sin(2 * math.pi * day_offset / period)
        return profile.baseline_daily_units * seasonal_mult

    if profile.pattern_type == "cliff":
        base = profile.baseline_daily_units
        in_cliff = (profile.cliff_event_day is not None
                    and day_offset >= profile.cliff_event_day)
        in_recovery = (profile.cliff_recovery_day is not None
                       and day_offset >= profile.cliff_recovery_day)
        if in_cliff and not in_recovery:
            base = base * (profile.cliff_magnitude or 1.0)
        return base

    raise ValueError(f"Unknown pattern_type: {profile.pattern_type}")


def generate_usage_log(
    account_id: str,
    sku_id: str,
    contract_start: datetime,
    contract_age_days: int,
    profile: UsageProfile,
    rng: random.Random,
    source_system: str = "product-prod-us-east-1",
) -> list[dict]:
    """Generate daily UsageMeteringLog rows for one account+SKU."""
    rows: list[dict] = []
    ingest_batch_id = str(uuid.uuid4())

    for day_offset in range(contract_age_days):
        period_start = contract_start + timedelta(days=day_offset)
        period_end = period_start + timedelta(days=1)

        base = _baseline_at_day(profile, day_offset)
        noise = rng.gauss(0, profile.volatility_pct)
        units_consumed = max(0.0, base * (1 + noise))

        # Daily commit is monthly commit / 30. Overage when daily exceeds.
        commit_daily = profile.commit_units_monthly / 30.0
        overage_units = max(0.0, units_consumed - commit_daily)

        # Some archetypes overage less often than usage-vs-commit alone implies;
        # apply propensity gate to reset some overages to zero (simulates burstiness).
        if overage_units > 0 and rng.random() > profile.overage_propensity:
            overage_units = 0.0

        unit_price = 0.10
        overage_unit_price = 0.15
        overage_amount_usd = overage_units * overage_unit_price

        rows.append({
            "usage_id": str(uuid.uuid4()),
            "account_id": account_id,
            "sku_id": sku_id,
            "sku_type": "consumption",
            "period_start": period_start.isoformat() + "Z",
            "period_end": period_end.isoformat() + "Z",
            "period_granularity": "daily",
            "units_consumed": round(units_consumed, 4),
            "commit_units": round(commit_daily, 4),
            "overage_units": round(overage_units, 4),
            "unit_price_usd": unit_price,
            "overage_unit_price_usd": overage_unit_price,
            "overage_amount_usd": round(overage_amount_usd, 4),
            "active_seats": None,           # not modeled at daily granularity here
            "licensed_seats": None,
            "seat_utilization_pct": None,
            "source_system": source_system,
            "ingest_event_id": f"{account_id}_{sku_id}_{day_offset}",
            "ingest_batch_id": ingest_batch_id,
            "received_at": (period_end + timedelta(hours=1)).isoformat() + "Z",
            "effective_at": period_end.isoformat() + "Z",
            "record_version": 1,
            "prior_version_id": None,
            "correction_reason": None,
            "audit_status": "verified",
            "created_at": (period_end + timedelta(hours=1)).isoformat() + "Z",
            "updated_at": (period_end + timedelta(hours=1)).isoformat() + "Z",
        })

    return rows
