"""Developer-signal generator — feeds AGT-208 Developer Signal Scorer.

For PLG-funnel scoring on developer-led consumption-pricing platforms.
Generates a per-account roster of developers + per-developer event stream
covering AGT-208's 5 signal dimensions:

  1. consumption velocity      (API call volume + growth trajectory)
  2. production signal         (deployment-tier inference, p95 latency
                                queries, idempotency-key usage, error-rate
                                sensitivity)
  3. enterprise context        (corp domain, multi-developer presence at
                                same domain, funded-company signals,
                                vertical match)
  4. commercial intent         (pricing-page traffic, billing dashboard
                                visits, security/compliance docs,
                                procurement help-desk tickets)
  5. stakeholder breadth       (number of distinct contacts at same domain
                                interacting with product or docs trailing
                                30 days)

Output developer_signal_block per account contains the roster + raw event
stream + pre-computed dimension contributions. AGT-208 prototype reads
this for its scoring runs.

CRITICAL: per the corpus invariant, this generator derives its seed from
sha256(account_id) + module salt — does NOT consume from the main rng.
Adding this generator does not shift account UUIDs or break the existing
conversation / feature / consumption caches.
"""

from __future__ import annotations

import hashlib
import random
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Literal


# ─────────────────────────────────────────────────────────────────────
# Profile — archetype-driven
# ─────────────────────────────────────────────────────────────────────

@dataclass
class DeveloperProfile:
    """Drives developer roster + event stream per account.

    developer_count_range: how many devs the account has using the product.
    role_mix: weights across (engineer / architect / manager / vp / executive).
              Spread vs concentrated drives stakeholder_breadth dimension.
    adoption_pattern: 'clustered' = single team; 'spread' = multi-team;
                      'broad' = multi-org. Affects domain-aggregation tier
                      override (3+ devs ≥ 60 score → priority).
    production_signal_strength: 0-1 — how much production-readiness signal
                                (deployment-tier inference, p95 queries,
                                idempotency).
    commercial_intent_level: 0-1 — pricing-page traffic, billing inquiries,
                             security/compliance docs.
    consumption_velocity_class: 'rapid_growth' | 'flat' | 'declining'
    enterprise_signal_class: 'strong' (corp domain + funded + vertical match)
                            | 'mixed' | 'weak' (gmail/personal heavy)
    """
    developer_count_range: tuple[int, int]
    role_mix: dict[str, float]
    adoption_pattern: Literal["clustered", "spread", "broad"]
    production_signal_strength: float
    commercial_intent_level: float
    consumption_velocity_class: Literal["rapid_growth", "flat", "declining"]
    enterprise_signal_class: Literal["strong", "mixed", "weak"]


# Archetype defaults — shape AGT-208 fixture coverage.
PROFILE_DEFAULTS_BY_ARCHETYPE: dict[str, DeveloperProfile] = {

    "ideal_power_user": DeveloperProfile(
        # Multi-team enterprise. Strong on every dimension.
        developer_count_range=(8, 18),
        role_mix={"engineer": 0.55, "architect": 0.20, "manager": 0.15, "vp": 0.07, "executive": 0.03},
        adoption_pattern="spread",
        production_signal_strength=0.80,
        commercial_intent_level=0.65,
        consumption_velocity_class="rapid_growth",
        enterprise_signal_class="strong",
    ),

    "activating": DeveloperProfile(
        # Just landed, single team ramping.
        developer_count_range=(2, 6),
        role_mix={"engineer": 0.75, "architect": 0.10, "manager": 0.15},
        adoption_pattern="clustered",
        production_signal_strength=0.45,
        commercial_intent_level=0.30,
        consumption_velocity_class="rapid_growth",
        enterprise_signal_class="mixed",
    ),

    "surface_only_adopter": DeveloperProfile(
        # 1-2 devs using shallowly. Flat consumption. Mostly engineers.
        developer_count_range=(1, 3),
        role_mix={"engineer": 0.85, "manager": 0.15},
        adoption_pattern="clustered",
        production_signal_strength=0.20,
        commercial_intent_level=0.15,
        consumption_velocity_class="flat",
        enterprise_signal_class="mixed",
    ),

    "champion_loss_decliner": DeveloperProfile(
        # Was multi-team, champion (architect/manager) departed → declining.
        # Roster might still show but engagement dropping.
        developer_count_range=(5, 12),
        role_mix={"engineer": 0.65, "architect": 0.15, "manager": 0.18, "vp": 0.02},
        adoption_pattern="spread",
        production_signal_strength=0.55,
        commercial_intent_level=0.25,
        consumption_velocity_class="declining",
        enterprise_signal_class="strong",
    ),

    "expansion_ready": DeveloperProfile(
        # Strong PLG signal. AGT-208 should fire handoff-priority repeatedly.
        # Multi-team with manager/vp engagement. Rising consumption.
        developer_count_range=(10, 22),
        role_mix={"engineer": 0.55, "architect": 0.18, "manager": 0.18, "vp": 0.07, "executive": 0.02},
        adoption_pattern="broad",
        production_signal_strength=0.85,
        commercial_intent_level=0.75,
        consumption_velocity_class="rapid_growth",
        enterprise_signal_class="strong",
    ),

    "spike_then_crash": DeveloperProfile(
        # Was clustered, had a spike, now reverted. Engineer-heavy.
        developer_count_range=(3, 7),
        role_mix={"engineer": 0.85, "manager": 0.15},
        adoption_pattern="clustered",
        production_signal_strength=0.40,
        commercial_intent_level=0.20,
        consumption_velocity_class="declining",
        enterprise_signal_class="mixed",
    ),

    "seasonal": DeveloperProfile(
        # Multi-team, predictable cycle. Mid-strength on every dimension.
        developer_count_range=(6, 14),
        role_mix={"engineer": 0.60, "architect": 0.18, "manager": 0.17, "vp": 0.05},
        adoption_pattern="spread",
        production_signal_strength=0.60,
        commercial_intent_level=0.45,
        consumption_velocity_class="flat",
        enterprise_signal_class="strong",
    ),

    "stalled_onboarding": DeveloperProfile(
        # Single dev signed up, never activated. Low signal across the board.
        # AGT-208 should NOT fire handoff for this account.
        developer_count_range=(1, 2),
        role_mix={"engineer": 1.0},
        adoption_pattern="clustered",
        production_signal_strength=0.10,
        commercial_intent_level=0.10,
        consumption_velocity_class="flat",
        enterprise_signal_class="weak",
    ),
}


# ─────────────────────────────────────────────────────────────────────
# Event-type catalog — per AGT-208 dimension mapping
# ─────────────────────────────────────────────────────────────────────

# Each event type maps to one or more AGT-208 dimensions for downstream scoring.
EVENT_TYPES = {
    # consumption velocity
    "api_call":                   {"dimensions": ["consumption_velocity"], "weight_per": 0.001},
    # production signal
    "deployment_create_dedicated": {"dimensions": ["production_signal"],   "weight_per": 6},
    "deployment_create_byoc":      {"dimensions": ["production_signal"],   "weight_per": 12},
    "p95_latency_query":           {"dimensions": ["production_signal"],   "weight_per": 1.5},
    "idempotency_key_usage":       {"dimensions": ["production_signal"],   "weight_per": 0.5},
    "error_rate_query":            {"dimensions": ["production_signal"],   "weight_per": 1.5},
    # commercial intent
    "pricing_page_visit":          {"dimensions": ["commercial_intent"],   "weight_per": 2.5},
    "billing_dashboard_visit":     {"dimensions": ["commercial_intent"],   "weight_per": 2.0},
    "security_compliance_request": {"dimensions": ["commercial_intent"],   "weight_per": 5.0},
    "soc2_doc_view":               {"dimensions": ["commercial_intent"],   "weight_per": 4.5},
    "hipaa_doc_view":              {"dimensions": ["commercial_intent"],   "weight_per": 4.5},
    "procurement_inquiry":         {"dimensions": ["commercial_intent"],   "weight_per": 7.0},
    # neutral product engagement (counted toward stakeholder breadth)
    "doc_view":                    {"dimensions": [],                       "weight_per": 0},
    "model_selection":             {"dimensions": [],                       "weight_per": 0},
}


# ─────────────────────────────────────────────────────────────────────
# Generator
# ─────────────────────────────────────────────────────────────────────

def _seed_for_account(account_id: str, salt: str = "developer_signals") -> int:
    """Stable per-account-per-module seed. Independent of main rng."""
    return int(hashlib.sha256(f"{account_id}|{salt}".encode()).hexdigest()[:8], 16)


def _weighted_choice(rng: random.Random, weights: dict[str, float]) -> str:
    keys = list(weights.keys())
    vals = list(weights.values())
    return rng.choices(keys, weights=vals, k=1)[0]


def _company_to_domain(company_name: str) -> str:
    """Slug-style corp domain from a company name. Stable per account."""
    slug = company_name.lower().replace(" ", "").replace("'", "")
    # Strip non-alnum to be safe
    slug = "".join(c for c in slug if c.isalnum())
    return f"{slug}.com"


def _gen_developer_name(rng: random.Random, used: set[str]) -> str:
    """Pick a stable fictional developer name. Anonymized."""
    firsts = ["Alex", "Jordan", "Sam", "Morgan", "Riley", "Casey", "Taylor",
              "Jamie", "Avery", "Quinn", "Devon", "Reese", "Sage", "Drew",
              "Hayden", "Cameron", "Skyler", "Parker", "Rowan", "Logan"]
    lasts = ["Chen", "Patel", "Kim", "Nguyen", "Garcia", "Smith", "Johnson",
             "Singh", "Khan", "Lopez", "Wong", "Park", "Liu", "Martinez",
             "Brown", "Jones", "Davis", "Wilson", "Anderson", "Thomas"]
    for _ in range(50):
        n = f"{rng.choice(firsts)} {rng.choice(lasts)}"
        if n not in used:
            used.add(n)
            return n
    return f"{rng.choice(firsts)} {rng.choice(lasts)}-{rng.randint(2,999)}"


def generate_developer_signals(
    account_id: str,
    company_name: str,
    archetype_key: str,
    contract_start: datetime,
    contract_age_days: int,
    licensed_seats: int,
) -> dict:
    """Build the developer roster + event stream + pre-computed dimensions."""
    profile = PROFILE_DEFAULTS_BY_ARCHETYPE.get(
        archetype_key, PROFILE_DEFAULTS_BY_ARCHETYPE["ideal_power_user"]
    )
    rng = random.Random(_seed_for_account(account_id))
    snapshot_date = contract_start + timedelta(days=contract_age_days)

    # Roster size scales with archetype range and lightly with seat count
    n_min, n_max = profile.developer_count_range
    seat_factor = max(0.6, min(1.6, licensed_seats / 100.0))
    n_devs = max(1, int(rng.uniform(n_min, n_max) * seat_factor))

    # Domain logic — all devs at the corp domain, except enterprise_signal_class=weak
    # which adds gmail/personal mix
    corp_domain = _company_to_domain(company_name)
    used_names: set[str] = set()
    roster: list[dict] = []
    for i in range(n_devs):
        name = _gen_developer_name(rng, used_names)
        slug = name.lower().replace(" ", "")
        # Domain assignment per enterprise_signal_class
        if profile.enterprise_signal_class == "weak":
            domain = corp_domain if rng.random() < 0.30 else rng.choice(
                ["gmail.com", "outlook.com", "yahoo.com"]
            )
        elif profile.enterprise_signal_class == "mixed":
            domain = corp_domain if rng.random() < 0.75 else rng.choice(
                ["gmail.com", "outlook.com"]
            )
        else:  # strong
            domain = corp_domain

        role = _weighted_choice(rng, profile.role_mix)
        # Signup offset within the contract window
        signup_offset = rng.randint(0, max(1, contract_age_days - 1))
        first_call_offset = signup_offset + rng.randint(0, 14)

        roster.append({
            "developer_id": str(uuid.UUID(int=rng.getrandbits(128))),
            "name": name,
            "email": f"{slug.split()[0] if ' ' in name else slug}@{domain}",
            "email_domain": domain,
            "role_class": role,
            "signup_at": (contract_start + timedelta(days=signup_offset)).isoformat() + "Z",
            "first_api_call_at": (contract_start + timedelta(days=first_call_offset)).isoformat() + "Z",
        })

    # Event stream — generate per-developer events biased by profile
    events: list[dict] = []
    for dev in roster:
        first_call = datetime.fromisoformat(dev["first_api_call_at"].rstrip("Z"))
        active_days = max(1, (snapshot_date - first_call).days)

        # Base API call count — driven by consumption_velocity_class
        if profile.consumption_velocity_class == "rapid_growth":
            base_calls = int(rng.uniform(800, 3500) * (active_days / 90))
        elif profile.consumption_velocity_class == "flat":
            base_calls = int(rng.uniform(150, 500) * (active_days / 90))
        else:  # declining
            base_calls = int(rng.uniform(100, 700) * (active_days / 90))
        base_calls = max(20, base_calls)

        # API calls — sampled in time
        for _ in range(min(base_calls, 200)):  # cap event volume per dev
            offset = rng.randint(0, active_days - 1)
            ts = first_call + timedelta(days=offset)
            events.append({
                "event_id": str(uuid.UUID(int=rng.getrandbits(128))),
                "developer_id": dev["developer_id"],
                "event_type": "api_call",
                "timestamp": ts.isoformat() + "Z",
                "metadata": {"call_count_in_event": int(rng.uniform(20, 300))},
            })

        # Production signal — gated by production_signal_strength
        if rng.random() < profile.production_signal_strength * 0.85:
            events.append(_gen_production_event(rng, dev, first_call, active_days, "deployment_create_dedicated"))
        if rng.random() < profile.production_signal_strength * 0.30:
            events.append(_gen_production_event(rng, dev, first_call, active_days, "deployment_create_byoc"))
        # p95 / error-rate / idempotency — multiple per dev when strong
        prod_event_count = int(profile.production_signal_strength * rng.uniform(2, 8))
        for _ in range(prod_event_count):
            events.append(_gen_production_event(
                rng, dev, first_call, active_days,
                rng.choice(["p95_latency_query", "idempotency_key_usage", "error_rate_query"])
            ))

        # Commercial intent — gated by commercial_intent_level
        intent_event_count = int(profile.commercial_intent_level * rng.uniform(2, 10))
        for _ in range(intent_event_count):
            events.append(_gen_intent_event(rng, dev, first_call, active_days))

        # Doc views (neutral, contributes to stakeholder breadth)
        for _ in range(rng.randint(2, 12)):
            offset = rng.randint(0, active_days - 1)
            ts = first_call + timedelta(days=offset)
            events.append({
                "event_id": str(uuid.UUID(int=rng.getrandbits(128))),
                "developer_id": dev["developer_id"],
                "event_type": "doc_view",
                "timestamp": ts.isoformat() + "Z",
                "metadata": {"page": rng.choice(["quickstart", "api_reference", "deployments", "fine_tuning", "embeddings", "tools"])},
            })

    # Sort events by timestamp
    events.sort(key=lambda e: e["timestamp"])

    # Pre-compute dimension contributions per developer (so AGT-208 prototype
    # has a deterministic baseline to score against). Captures only events in
    # trailing 30 days of snapshot per spec.
    trailing_30 = snapshot_date - timedelta(days=30)
    dimension_contribs: list[dict] = []
    for dev in roster:
        dev_events = [e for e in events if e["developer_id"] == dev["developer_id"]
                      and datetime.fromisoformat(e["timestamp"].rstrip("Z")) >= trailing_30]
        velocity_pts = 0.0
        production_pts = 0.0
        intent_pts = 0.0
        for e in dev_events:
            t_meta = EVENT_TYPES.get(e["event_type"], {})
            dims = t_meta.get("dimensions", [])
            w = t_meta.get("weight_per", 0)
            if "consumption_velocity" in dims:
                velocity_pts += e["metadata"].get("call_count_in_event", 1) * w
            if "production_signal" in dims:
                production_pts += w
            if "commercial_intent" in dims:
                intent_pts += w
        dimension_contribs.append({
            "developer_id": dev["developer_id"],
            "consumption_velocity_pts_raw": round(velocity_pts, 2),
            "consumption_velocity_pts_capped": min(30.0, round(velocity_pts, 2)),
            "production_signal_pts_raw": round(production_pts, 2),
            "production_signal_pts_capped": min(25.0, round(production_pts, 2)),
            "commercial_intent_pts_raw": round(intent_pts, 2),
            "commercial_intent_pts_capped": min(15.0, round(intent_pts, 2)),
        })

    # Stakeholder breadth (account-level): distinct devs with any event in trailing 30
    distinct_devs_30d = len({
        e["developer_id"] for e in events
        if datetime.fromisoformat(e["timestamp"].rstrip("Z")) >= trailing_30
    })
    stakeholder_breadth_pts = min(10, distinct_devs_30d)

    # Enterprise context (account-level): score = corp_domain_pct × 12 + (multi_dev>=3 ? 6 : 0) + vertical_match (2)
    corp_dev_count = sum(1 for d in roster if d["email_domain"] == corp_domain)
    corp_pct = corp_dev_count / max(1, len(roster))
    enterprise_context_pts = min(20, int(corp_pct * 12) + (6 if corp_dev_count >= 3 else 0) + 2)

    return {
        "developer_roster": roster,
        "developer_event_stream": events,
        "developer_signal_dimensions_pre_computed": {
            "per_developer": dimension_contribs,
            "account_level": {
                "stakeholder_breadth_pts": stakeholder_breadth_pts,
                "enterprise_context_pts": enterprise_context_pts,
                "corp_domain_pct": round(corp_pct, 3),
                "distinct_devs_trailing_30d": distinct_devs_30d,
                "n_devs_total": len(roster),
            },
        },
        "developer_profile_used": archetype_key,
    }


def _gen_production_event(rng: random.Random, dev: dict, first_call: datetime, active_days: int, event_type: str) -> dict:
    offset = rng.randint(0, active_days - 1)
    ts = first_call + timedelta(days=offset)
    return {
        "event_id": str(uuid.UUID(int=rng.getrandbits(128))),
        "developer_id": dev["developer_id"],
        "event_type": event_type,
        "timestamp": ts.isoformat() + "Z",
        "metadata": {},
    }


def _gen_intent_event(rng: random.Random, dev: dict, first_call: datetime, active_days: int) -> dict:
    offset = rng.randint(0, active_days - 1)
    ts = first_call + timedelta(days=offset)
    et = rng.choices(
        ["pricing_page_visit", "billing_dashboard_visit", "security_compliance_request",
         "soc2_doc_view", "hipaa_doc_view", "procurement_inquiry"],
        weights=[0.25, 0.25, 0.10, 0.20, 0.10, 0.10],
        k=1,
    )[0]
    return {
        "event_id": str(uuid.UUID(int=rng.getrandbits(128))),
        "developer_id": dev["developer_id"],
        "event_type": et,
        "timestamp": ts.isoformat() + "Z",
        "metadata": {},
    }
