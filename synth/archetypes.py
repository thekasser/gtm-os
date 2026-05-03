"""Account archetypes for synthetic GTM-OS corpus generation.

Each archetype defines parameter distributions for one persona. Generators
read these archetypes to produce internally-consistent time-series data
across UsageMeteringLog, CustomerHealthLog, PaymentEventLog, and the rest.

Eight archetypes cover the patterns the L9 brain agents and Tier 3 tools
need to recognize:

  ideal_power_user        — green, growing, expanding (control case)
  activating              — newly onboarded, ramping well
  surface_only_adopter    — using product but shallow, renewal-at-risk
  champion_loss_decliner  — was healthy, now slipping post-champion-departure
  expansion_ready         — overage signals + multi-team rollout
  spike_then_crash        — looked like expansion but was one-time event
  seasonal                — predictable cycle (looks risky to naive analysis)
  stalled_onboarding      — never activated properly, early-churn risk

Eight is enough to span the patterns; further archetypes added when the
prototype reveals real gaps.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional, Literal


# ─────────────────────────────────────────────────────────────────────
# Profile dataclasses — parameters per dimension
# ─────────────────────────────────────────────────────────────────────

@dataclass
class UsageProfile:
    pattern_type: Literal["linear", "exponential", "seasonal", "cliff", "flat"]
    baseline_daily_units: float
    growth_rate_per_day: float            # linear: units/day; exponential: pct/day as decimal
    volatility_pct: float                 # period-over-period gaussian noise
    seasonality_period_days: Optional[int]
    cliff_event_day: Optional[int]        # day relative to contract start
    cliff_magnitude: Optional[float]      # multiplier (2.5 = spike up; 0.4 = drop)
    cliff_recovery_day: Optional[int]     # if set, magnitude reverts at this day
    commit_units_monthly: float
    overage_propensity: float             # 0-1: probability of overage per month


@dataclass
class HealthProfile:
    baseline_score: int                   # 0-100
    trajectory: Literal["improving", "declining", "stable", "volatile"]
    trajectory_pct_per_30d: float         # health score points per 30 days
    trajectory_change_day: Optional[int]  # if set, trajectory inflects at this day
    post_change_trajectory_pct: Optional[float]
    payment_state: Literal["current", "overdue", "failed", "suspended"]
    payment_state_change_day: Optional[int]


@dataclass
class ConversationProfile:
    calls_per_month: float
    sentiment_baseline: Literal["positive", "neutral", "negative"]
    sentiment_trajectory: Literal["improving", "declining", "stable"]
    champion_present: bool
    champion_departure_day: Optional[int]   # day relative to contract start
    objection_themes: list[str]


@dataclass
class FeatureProfile:
    """Drives synthetic feature_engagement_telemetry generation per account.

    Maps to the TOOL-008 Product Adoption Pattern Recognizer input contract.
    Ground truth label is the pattern TOOL-008 should output; synth generator
    produces telemetry that lands consistently in that classification.
    """
    target_breadth: int                         # # distinct features used in 90d window
    category_breadth: dict[str, int]            # # features used per category
    users_per_feature_pct_mean: float           # 0-1: mean of users_pct_of_active across features
    concentration: Literal["broad", "moderate", "concentrated"]
    newly_adopted_in_window: int                # features whose first_use_at is in the trailing 30d
    abandoned_in_window: int                    # features whose last_use_at is >45d ago but were active before
    expected_pattern: Literal[
        "deeply_integrated", "surface_only", "siloed_by_team",
        "declining", "activating",
    ]


@dataclass
class Archetype:
    name: str
    description: str
    segment_distribution: dict[str, float]    # weights summing to ~1.0
    vertical_distribution: dict[str, float]
    icp_tier_distribution: dict[str, float]
    arr_range_usd: tuple[float, float]
    term_months_distribution: dict[int, float]
    licensed_seats_range: tuple[int, int]
    contract_age_range_days: tuple[int, int]  # how mature the account is at gen time
    usage: UsageProfile
    health: HealthProfile
    conversation: ConversationProfile
    feature: FeatureProfile
    expected_outcome_label: str               # ground truth for eval harness


# ─────────────────────────────────────────────────────────────────────
# 8 archetypes
# ─────────────────────────────────────────────────────────────────────

ARCHETYPES: dict[str, Archetype] = {

    "ideal_power_user": Archetype(
        name="Ideal Power User",
        description="Deeply integrated, multi-team, expanding usage, champion engaged. Control case.",
        segment_distribution={"MM": 0.4, "Ent": 0.6},
        vertical_distribution={"SaaS": 0.3, "FinTech": 0.3, "HealthTech": 0.2, "RetailTech": 0.2},
        icp_tier_distribution={"T1": 0.8, "T2": 0.2},
        arr_range_usd=(150_000, 500_000),
        term_months_distribution={12: 0.4, 24: 0.4, 36: 0.2},
        licensed_seats_range=(50, 300),
        contract_age_range_days=(180, 720),
        usage=UsageProfile(
            pattern_type="linear",
            baseline_daily_units=200,
            growth_rate_per_day=2.0,
            volatility_pct=0.10,
            seasonality_period_days=None,
            cliff_event_day=None,
            cliff_magnitude=None,
            cliff_recovery_day=None,
            commit_units_monthly=8000,
            overage_propensity=0.4,
        ),
        health=HealthProfile(
            baseline_score=82,
            trajectory="improving",
            trajectory_pct_per_30d=2.0,
            trajectory_change_day=None,
            post_change_trajectory_pct=None,
            payment_state="current",
            payment_state_change_day=None,
        ),
        conversation=ConversationProfile(
            calls_per_month=2.5,
            sentiment_baseline="positive",
            sentiment_trajectory="stable",
            champion_present=True,
            champion_departure_day=None,
            objection_themes=[],
        ),
        feature=FeatureProfile(
            target_breadth=18,                         # uses ~18 of 23 features
            category_breadth={"core": 5, "advanced": 5, "integration": 4, "admin": 3, "experimental": 1},
            users_per_feature_pct_mean=0.55,
            concentration="broad",
            newly_adopted_in_window=2,
            abandoned_in_window=0,
            expected_pattern="deeply_integrated",
        ),
        expected_outcome_label="renews_and_expands",
    ),

    "activating": Archetype(
        name="Activating",
        description="Newly onboarded, ramping rapidly, on track to power-user status.",
        segment_distribution={"SMB": 0.4, "MM": 0.5, "Ent": 0.1},
        vertical_distribution={"SaaS": 0.4, "FinTech": 0.2, "HealthTech": 0.2, "RetailTech": 0.2},
        icp_tier_distribution={"T1": 0.6, "T2": 0.4},
        arr_range_usd=(50_000, 200_000),
        term_months_distribution={12: 0.7, 24: 0.3},
        licensed_seats_range=(20, 100),
        contract_age_range_days=(14, 90),
        usage=UsageProfile(
            pattern_type="exponential",
            baseline_daily_units=20,
            growth_rate_per_day=0.06,             # 6% per day initially — strong ramp
            volatility_pct=0.25,
            seasonality_period_days=None,
            cliff_event_day=None,
            cliff_magnitude=None,
            cliff_recovery_day=None,
            commit_units_monthly=3000,
            overage_propensity=0.1,
        ),
        health=HealthProfile(
            baseline_score=65,
            trajectory="improving",
            trajectory_pct_per_30d=5.0,
            trajectory_change_day=None,
            post_change_trajectory_pct=None,
            payment_state="current",
            payment_state_change_day=None,
        ),
        conversation=ConversationProfile(
            calls_per_month=4.0,
            sentiment_baseline="positive",
            sentiment_trajectory="improving",
            champion_present=True,
            champion_departure_day=None,
            objection_themes=[],
        ),
        feature=FeatureProfile(
            target_breadth=8,
            category_breadth={"core": 5, "advanced": 2, "integration": 1, "admin": 0, "experimental": 0},
            users_per_feature_pct_mean=0.45,
            concentration="broad",
            newly_adopted_in_window=5,                  # rapid recent adoption
            abandoned_in_window=0,
            expected_pattern="activating",
        ),
        expected_outcome_label="activates_to_power_user",
    ),

    "surface_only_adopter": Archetype(
        name="Surface-Only Adopter",
        description="Using product but shallow — narrow features, low engagement, competitor-swap risk.",
        segment_distribution={"SMB": 0.5, "MM": 0.4, "Ent": 0.1},
        vertical_distribution={"SaaS": 0.3, "RetailTech": 0.3, "Other": 0.4},
        icp_tier_distribution={"T2": 0.5, "T3": 0.5},
        arr_range_usd=(40_000, 150_000),
        term_months_distribution={12: 0.8, 24: 0.2},
        licensed_seats_range=(15, 80),
        contract_age_range_days=(365, 720),
        usage=UsageProfile(
            pattern_type="flat",
            baseline_daily_units=80,
            growth_rate_per_day=0.0,
            volatility_pct=0.08,
            seasonality_period_days=None,
            cliff_event_day=None,
            cliff_magnitude=None,
            cliff_recovery_day=None,
            commit_units_monthly=2500,
            overage_propensity=0.05,
        ),
        health=HealthProfile(
            baseline_score=60,
            trajectory="stable",
            trajectory_pct_per_30d=0.0,
            trajectory_change_day=None,
            post_change_trajectory_pct=None,
            payment_state="current",
            payment_state_change_day=None,
        ),
        conversation=ConversationProfile(
            calls_per_month=0.5,
            sentiment_baseline="neutral",
            sentiment_trajectory="stable",
            champion_present=True,
            champion_departure_day=None,
            objection_themes=["renewal_uncertainty"],
        ),
        feature=FeatureProfile(
            target_breadth=4,                           # only the basics
            category_breadth={"core": 4, "advanced": 0, "integration": 0, "admin": 0, "experimental": 0},
            users_per_feature_pct_mean=0.20,
            concentration="moderate",
            newly_adopted_in_window=0,
            abandoned_in_window=1,                      # slight stagnation
            expected_pattern="surface_only",
        ),
        expected_outcome_label="at_risk_renewal",
    ),

    "champion_loss_decliner": Archetype(
        name="Champion-Loss Decliner",
        description="Was healthy. Champion departed mid-contract. Usage and engagement declining since.",
        segment_distribution={"MM": 0.5, "Ent": 0.5},
        vertical_distribution={"SaaS": 0.3, "FinTech": 0.3, "HealthTech": 0.2, "RetailTech": 0.2},
        icp_tier_distribution={"T1": 0.6, "T2": 0.4},
        arr_range_usd=(80_000, 300_000),
        term_months_distribution={12: 0.5, 24: 0.5},
        licensed_seats_range=(30, 150),
        contract_age_range_days=(365, 540),
        usage=UsageProfile(
            pattern_type="cliff",
            baseline_daily_units=180,
            growth_rate_per_day=0.5,
            volatility_pct=0.12,
            seasonality_period_days=None,
            cliff_event_day=210,                  # champion departs day 210
            cliff_magnitude=0.55,                 # usage drops 45%
            cliff_recovery_day=None,              # no recovery — adoption decay
            commit_units_monthly=6000,
            overage_propensity=0.2,
        ),
        health=HealthProfile(
            baseline_score=78,
            trajectory="declining",
            trajectory_pct_per_30d=-1.0,
            trajectory_change_day=210,            # accelerates decline at champion departure
            post_change_trajectory_pct=-4.5,
            payment_state="current",
            payment_state_change_day=None,
        ),
        conversation=ConversationProfile(
            calls_per_month=1.5,
            sentiment_baseline="positive",
            sentiment_trajectory="declining",
            champion_present=True,
            champion_departure_day=210,
            objection_themes=["renewal_uncertainty", "buyer_org_change"],
        ),
        feature=FeatureProfile(
            target_breadth=10,                          # was 14, declined post-departure
            category_breadth={"core": 4, "advanced": 3, "integration": 2, "admin": 1, "experimental": 0},
            users_per_feature_pct_mean=0.30,
            concentration="moderate",
            newly_adopted_in_window=0,
            abandoned_in_window=4,                      # post-departure abandonment
            expected_pattern="declining",
        ),
        expected_outcome_label="churn_risk_high",
    ),

    "expansion_ready": Archetype(
        name="Expansion-Ready",
        description="Hitting consumption overage, multi-team rollout, real expansion candidate.",
        segment_distribution={"MM": 0.5, "Ent": 0.5},
        vertical_distribution={"SaaS": 0.4, "FinTech": 0.3, "HealthTech": 0.3},
        icp_tier_distribution={"T1": 0.9, "T2": 0.1},
        arr_range_usd=(120_000, 400_000),
        term_months_distribution={12: 0.4, 24: 0.5, 36: 0.1},
        licensed_seats_range=(40, 200),
        contract_age_range_days=(240, 540),
        usage=UsageProfile(
            pattern_type="exponential",
            baseline_daily_units=150,
            growth_rate_per_day=0.012,            # 1.2% per day — sustained ramp
            volatility_pct=0.10,
            seasonality_period_days=None,
            cliff_event_day=None,
            cliff_magnitude=None,
            cliff_recovery_day=None,
            commit_units_monthly=6000,
            overage_propensity=0.85,              # consistently overages
        ),
        health=HealthProfile(
            baseline_score=88,
            trajectory="improving",
            trajectory_pct_per_30d=1.0,
            trajectory_change_day=None,
            post_change_trajectory_pct=None,
            payment_state="current",
            payment_state_change_day=None,
        ),
        conversation=ConversationProfile(
            calls_per_month=2.5,
            sentiment_baseline="positive",
            sentiment_trajectory="stable",
            champion_present=True,
            champion_departure_day=None,
            objection_themes=[],
        ),
        feature=FeatureProfile(
            target_breadth=12,                          # one team uses many features
            category_breadth={"core": 5, "advanced": 4, "integration": 2, "admin": 1, "experimental": 0},
            users_per_feature_pct_mean=0.18,            # low — only one team is using
            concentration="concentrated",               # high concentration index
            newly_adopted_in_window=2,
            abandoned_in_window=0,
            expected_pattern="siloed_by_team",
        ),
        expected_outcome_label="real_expansion",
    ),

    "spike_then_crash": Archetype(
        name="Spike-Then-Crash",
        description="One-time consumption spike (e.g., post-marketing-campaign) — not real expansion.",
        segment_distribution={"SMB": 0.4, "MM": 0.5, "Ent": 0.1},
        vertical_distribution={"SaaS": 0.3, "RetailTech": 0.4, "Other": 0.3},
        icp_tier_distribution={"T1": 0.3, "T2": 0.5, "T3": 0.2},
        arr_range_usd=(60_000, 250_000),
        term_months_distribution={12: 0.7, 24: 0.3},
        licensed_seats_range=(20, 120),
        contract_age_range_days=(300, 540),
        usage=UsageProfile(
            pattern_type="cliff",
            baseline_daily_units=100,
            growth_rate_per_day=0.0,
            volatility_pct=0.12,
            seasonality_period_days=None,
            cliff_event_day=180,                  # spike begins
            cliff_magnitude=2.8,                  # 2.8x baseline
            cliff_recovery_day=220,               # back to baseline at day 220
            commit_units_monthly=3500,
            overage_propensity=0.15,
        ),
        health=HealthProfile(
            baseline_score=72,
            trajectory="volatile",
            trajectory_pct_per_30d=0.0,
            trajectory_change_day=None,
            post_change_trajectory_pct=None,
            payment_state="current",
            payment_state_change_day=None,
        ),
        conversation=ConversationProfile(
            calls_per_month=1.5,
            sentiment_baseline="neutral",
            sentiment_trajectory="stable",
            champion_present=True,
            champion_departure_day=None,
            objection_themes=[],
        ),
        feature=FeatureProfile(
            target_breadth=5,
            category_breadth={"core": 4, "advanced": 1, "integration": 0, "admin": 0, "experimental": 0},
            users_per_feature_pct_mean=0.22,
            concentration="moderate",
            newly_adopted_in_window=0,
            abandoned_in_window=2,                      # post-spike features dropped
            expected_pattern="declining",
        ),
        expected_outcome_label="not_real_expansion",
    ),

    "seasonal": Archetype(
        name="Seasonal",
        description="Predictable usage cycle (e.g., quarterly budget pattern). Looks risky to naive analysis.",
        segment_distribution={"MM": 0.5, "Ent": 0.5},
        vertical_distribution={"FinTech": 0.4, "RetailTech": 0.4, "Other": 0.2},
        icp_tier_distribution={"T1": 0.5, "T2": 0.5},
        arr_range_usd=(80_000, 300_000),
        term_months_distribution={24: 0.5, 36: 0.5},  # multi-year — has had cycles
        licensed_seats_range=(30, 180),
        contract_age_range_days=(540, 900),
        usage=UsageProfile(
            pattern_type="seasonal",
            baseline_daily_units=140,
            growth_rate_per_day=0.0,
            volatility_pct=0.06,
            seasonality_period_days=90,           # quarterly
            cliff_event_day=None,
            cliff_magnitude=None,
            cliff_recovery_day=None,
            commit_units_monthly=4500,
            overage_propensity=0.3,               # in peak quarters
        ),
        health=HealthProfile(
            baseline_score=70,
            trajectory="volatile",                # mirrors seasonal usage
            trajectory_pct_per_30d=0.0,
            trajectory_change_day=None,
            post_change_trajectory_pct=None,
            payment_state="current",
            payment_state_change_day=None,
        ),
        conversation=ConversationProfile(
            calls_per_month=1.5,
            sentiment_baseline="neutral",
            sentiment_trajectory="stable",
            champion_present=True,
            champion_departure_day=None,
            objection_themes=[],
        ),
        feature=FeatureProfile(
            target_breadth=14,
            category_breadth={"core": 5, "advanced": 4, "integration": 3, "admin": 2, "experimental": 0},
            users_per_feature_pct_mean=0.42,
            concentration="broad",
            newly_adopted_in_window=1,
            abandoned_in_window=0,
            expected_pattern="deeply_integrated",
        ),
        expected_outcome_label="renews_stable",
    ),

    "stalled_onboarding": Archetype(
        name="Stalled Onboarding",
        description="Never properly activated. Minimal usage, milestones overdue, early-churn risk.",
        segment_distribution={"SMB": 0.7, "MM": 0.3},
        vertical_distribution={"SaaS": 0.4, "Other": 0.6},
        icp_tier_distribution={"T2": 0.4, "T3": 0.6},
        arr_range_usd=(30_000, 100_000),
        term_months_distribution={12: 1.0},
        licensed_seats_range=(10, 50),
        contract_age_range_days=(45, 120),
        usage=UsageProfile(
            pattern_type="flat",
            baseline_daily_units=4,               # almost nothing
            growth_rate_per_day=0.0,
            volatility_pct=0.4,                   # high noise on tiny base
            seasonality_period_days=None,
            cliff_event_day=None,
            cliff_magnitude=None,
            cliff_recovery_day=None,
            commit_units_monthly=2000,
            overage_propensity=0.0,
        ),
        health=HealthProfile(
            baseline_score=35,
            trajectory="declining",
            trajectory_pct_per_30d=-1.5,
            trajectory_change_day=None,
            post_change_trajectory_pct=None,
            payment_state="current",
            payment_state_change_day=None,
        ),
        conversation=ConversationProfile(
            calls_per_month=1.0,
            sentiment_baseline="neutral",
            sentiment_trajectory="declining",
            champion_present=False,               # no champion ever emerged
            champion_departure_day=None,
            objection_themes=["scope_unclear", "implementation_blocker"],
        ),
        feature=FeatureProfile(
            # Onboarding-aware test case: looks like surface_only but contract is <120 days old.
            # TOOL-008 must classify this "activating" not "surface_only" per spec eval criterion.
            target_breadth=3,
            category_breadth={"core": 3, "advanced": 0, "integration": 0, "admin": 0, "experimental": 0},
            users_per_feature_pct_mean=0.15,
            concentration="moderate",
            newly_adopted_in_window=1,
            abandoned_in_window=0,
            expected_pattern="activating",
        ),
        expected_outcome_label="early_churn_risk",
    ),
}


# ─────────────────────────────────────────────────────────────────────
# Default account-count weighting for corpus generation
# ─────────────────────────────────────────────────────────────────────
# Weight how many accounts of each archetype the corpus contains.
# Adjust based on which patterns you want richer eval coverage on.

DEFAULT_ARCHETYPE_WEIGHTS: dict[str, float] = {
    "ideal_power_user":       0.20,
    "activating":             0.15,
    "surface_only_adopter":   0.15,
    "champion_loss_decliner": 0.10,
    "expansion_ready":        0.10,
    "spike_then_crash":       0.10,
    "seasonal":               0.10,
    "stalled_onboarding":     0.10,
}
