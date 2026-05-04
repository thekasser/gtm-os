"""Generate feature_engagement_telemetry for one account.

Reads FeatureProfile from archetypes.py. Produces a list of feature_usage
records matching the TOOL-008 input schema. Numerical only — no LLM.

The taxonomy below models a B2B API product (background-check use case
as a concrete example):
core (basic-search workflow), advanced (compliance + customization),
integration (ATS + identity), admin (workspace controls), experimental
(newer GTM-led capabilities).
"""

from __future__ import annotations

import random
from datetime import datetime, timedelta

from archetypes import FeatureProfile


# ─────────────────────────────────────────────────────────────────────
# Feature taxonomy — 23 features across 5 categories
# Modeled on a B2B API product (UBB pricing) to keep the prototype concrete.
# ─────────────────────────────────────────────────────────────────────

FEATURE_TAXONOMY: dict[str, list[str]] = {
    "core": [
        "background_check_search",
        "subject_invite",
        "results_view",
        "pdf_download",
        "dashboard_home",
    ],
    "advanced": [
        "adverse_action_workflow",
        "package_customization",
        "webhook_subscription",
        "audit_log_export",
        "bulk_invite",
        "custom_dispositions",
    ],
    "integration": [
        "ats_integration_greenhouse",
        "ats_integration_lever",
        "sso_okta",
        "scim_provisioning",
        "api_v2_usage",
    ],
    "admin": [
        "user_management",
        "permissions_groups",
        "role_based_access",
        "billing_portal",
    ],
    "experimental": [
        "ai_summarization",
        "automated_redlining",
        "candidate_messaging",
    ],
}


def _pick_features(profile: FeatureProfile, rng: random.Random) -> list[tuple[str, str]]:
    """Deterministically select features per category. Returns [(feature_id, category)]."""
    selected: list[tuple[str, str]] = []
    for category, count in profile.category_breadth.items():
        pool = FEATURE_TAXONOMY.get(category, [])
        n = min(count, len(pool))
        if n <= 0:
            continue
        # Deterministic per-archetype selection: front of pool first (most common features)
        selected.extend((feature_id, category) for feature_id in pool[:n])
    return selected


def generate_feature_engagement(
    profile: FeatureProfile,
    contract_start: datetime,
    snapshot_date: datetime,
    active_seats: int,
    seed: int,
) -> dict:
    """Produce the feature_engagement_telemetry block for one account.

    Output matches the TOOL-008 input schema's feature_engagement_telemetry +
    derived ground-truth fields the eval harness can reference.
    """
    rng = random.Random(seed)
    window_days = 90
    window_start = snapshot_date - timedelta(days=window_days)

    selected = _pick_features(profile, rng)
    feature_usage: list[dict] = []

    # Determine which features count as "newly adopted" vs "abandoned"
    # newly_adopted: first_use_at within trailing 30d
    # abandoned: last_use_at >= 45d ago (still inside the 90d window)
    new_count = min(profile.newly_adopted_in_window, len(selected))
    abandoned_count = min(profile.abandoned_in_window, max(0, len(selected) - new_count))

    for idx, (feature_id, category) in enumerate(selected):
        # First-use date — most features used since contract start; new ones recent.
        is_newly_adopted = idx < new_count
        is_abandoned = (not is_newly_adopted) and (idx >= len(selected) - abandoned_count)

        if is_newly_adopted:
            first_use_offset = rng.randint(1, 28)
            first_use = snapshot_date - timedelta(days=first_use_offset)
        else:
            # Adopted somewhere between contract start and 35 days ago
            earliest = max(contract_start, snapshot_date - timedelta(days=540))
            spread = max(1, (snapshot_date - earliest).days - 35)
            first_use_offset = rng.randint(35, 35 + spread)
            first_use = snapshot_date - timedelta(days=first_use_offset)

        if is_abandoned:
            # Last use >= 45 days ago, but still within the 90d window
            last_use_offset = rng.randint(45, 80)
            last_use = snapshot_date - timedelta(days=last_use_offset)
        else:
            # Active recently — last use in the trailing 7 days
            last_use_offset = rng.randint(0, 7)
            last_use = snapshot_date - timedelta(days=last_use_offset)

        # users_pct_of_active — clamped via mean + jitter, but concentration distorts
        base_pct = profile.users_per_feature_pct_mean
        if profile.concentration == "concentrated":
            # A few features at base*2, the rest much lower
            if idx < 3:
                pct = min(0.95, base_pct * 2.5)
            else:
                pct = max(0.02, base_pct * 0.3)
        elif profile.concentration == "moderate":
            pct = max(0.02, base_pct + rng.uniform(-0.10, 0.10))
        else:  # broad
            pct = max(0.05, base_pct + rng.uniform(-0.05, 0.05))

        if is_abandoned:
            pct = max(0.0, pct * 0.2)  # users left

        # use_event_count — proportional to users using it and category type
        base_events_per_user = {
            "core": 60, "advanced": 25, "integration": 15,
            "admin": 8, "experimental": 5,
        }.get(category, 10)
        distinct_users = max(1, int(round(active_seats * pct)))
        if is_abandoned:
            event_count = rng.randint(1, max(2, base_events_per_user // 4))
        else:
            event_count = int(distinct_users * base_events_per_user
                               * rng.uniform(0.7, 1.3))

        feature_usage.append({
            "feature_id": feature_id,
            "feature_category": category,
            "first_use_at": first_use.isoformat(),
            "last_use_at": last_use.isoformat(),
            "use_event_count_in_window": event_count,
            "distinct_users_in_window": distinct_users,
            "users_pct_of_active": round(pct, 3),
        })

    # Age-aware ground truth override. Two cases collapse the rule:
    #   1. An archetype labeled "activating" with weak adoption signals
    #      (target_breadth < 5, newly_adopted < 3) past the 60-day onboarding
    #      window is correctly reclassified "surface_only" — the spec's
    #      onboarding rule no longer applies, so the account just looks shallow.
    #   2. An archetype with strong adoption signals (rapid_recent_adoption)
    #      stays "activating" regardless of age — it's genuinely ramping.
    days_into_contract = (snapshot_date - contract_start).days
    expected = profile.expected_pattern
    weak_adoption_signals = (profile.target_breadth < 5
                             and profile.newly_adopted_in_window < 3)
    if expected == "activating" and days_into_contract >= 60 and weak_adoption_signals:
        expected = "surface_only"

    return {
        "feature_engagement_telemetry": {
            "trailing_window_days": window_days,
            "window_start": window_start.date().isoformat(),
            "window_end": snapshot_date.date().isoformat(),
            "feature_usage": feature_usage,
        },
        "ground_truth_pattern": expected,
    }
