"""Generate CustomerHealthLog rows for one account over its contract age.

Reads HealthProfile from archetypes.py. Produces daily health-score rows
matching AGT-501 Customer Health Monitor spec — score 0-100, 7 dimensions
(simplified to a single composite here; expand later if needed), payment
modifier from HealthProfile.payment_state.

Trajectory math:
  baseline + (day_offset / 30) * trajectory_pct_per_30d
  with optional inflection at trajectory_change_day:
    pre-change: trajectory_pct_per_30d
    post-change: post_change_trajectory_pct
  plus volatility noise per day

Payment modifier (per AGT-501 spec):
  current   no effect
  overdue   cap at 77
  failed    cap at 62
  suspended floor at Critical (cap 44)
"""

from __future__ import annotations

import random
from datetime import datetime, timedelta
import uuid

from archetypes import HealthProfile


def _trajectory_at_day(profile: HealthProfile, day_offset: int) -> float:
    """Compute deterministic health-score adjustment from baseline."""
    inflect = profile.trajectory_change_day
    post_pct = profile.post_change_trajectory_pct

    if inflect is None or day_offset < inflect:
        # Single trajectory the whole way
        return (day_offset / 30.0) * profile.trajectory_pct_per_30d

    # Inflected trajectory: pre + post components
    pre_phase = (inflect / 30.0) * profile.trajectory_pct_per_30d
    post_phase = ((day_offset - inflect) / 30.0) * (post_pct or 0.0)
    return pre_phase + post_phase


def _payment_state_at_day(profile: HealthProfile, day_offset: int) -> str:
    """Resolve which payment state applies on this day."""
    if profile.payment_state_change_day is None:
        return profile.payment_state
    if day_offset < profile.payment_state_change_day:
        return "current"
    return profile.payment_state


def _apply_payment_modifier(score: float, payment_state: str) -> float:
    """AGT-501 cap/floor model from payment health."""
    if payment_state == "current":
        return score
    if payment_state == "overdue":
        return min(score, 77.0)
    if payment_state == "failed":
        return min(score, 62.0)
    if payment_state == "suspended":
        return min(score, 44.0)
    return score


def generate_health_log(
    account_id: str,
    contract_start: datetime,
    contract_age_days: int,
    profile: HealthProfile,
    rng: random.Random,
) -> list[dict]:
    """Generate daily CustomerHealthLog rows for one account."""
    rows: list[dict] = []

    for day_offset in range(contract_age_days):
        observation_date = contract_start + timedelta(days=day_offset)

        deterministic = profile.baseline_score + _trajectory_at_day(profile, day_offset)
        noise = rng.gauss(0, 3.5 if profile.trajectory == "volatile" else 1.5)
        raw_score = deterministic + noise

        payment_state = _payment_state_at_day(profile, day_offset)
        score_after_modifier = _apply_payment_modifier(raw_score, payment_state)

        # Clamp to [0, 100]
        final_score = max(0.0, min(100.0, score_after_modifier))

        # Simple tier mapping mirroring AGT-501 bands
        if final_score >= 78:
            tier = "Green"
        elif final_score >= 62:
            tier = "Yellow"
        elif final_score >= 45:
            tier = "Amber"
        else:
            tier = "Red"

        rows.append({
            "health_log_id": str(uuid.uuid4()),
            "account_id": account_id,
            "observation_date": observation_date.date().isoformat(),
            "score": round(final_score, 2),
            "tier": tier,
            "trajectory_30d": profile.trajectory,
            "payment_health_status": payment_state,
            "payment_modifier_applied": payment_state != "current",
            "created_at": (observation_date + timedelta(hours=2)).isoformat() + "Z",
        })

    return rows
