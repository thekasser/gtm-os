"""strategy_brain_view shim for AGT-903 prototype.

Production reads materialized strategy_brain_view extensions per
Brain_Ready_Views_Contract v37 extension. The prototype assembles them
from the synth corpus on demand. The output shape mirrors the contract
even though the values are synthesized.

For each fixture (EVAL-S01...S05), build_view_for_fixture returns the
subset of strategy_brain_views relevant to the question. Missing views
trigger AGT-903's refusal-first behavior (per spec).
"""

from __future__ import annotations

import hashlib
import json
import random
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path


CORPUS_DIR = Path(__file__).parent.parent / "synth" / "corpus"


# ─────────────────────────────────────────────────────────────────────
# Corpus loaders
# ─────────────────────────────────────────────────────────────────────

def _load_ground_truth() -> dict:
    return json.loads((CORPUS_DIR / "ground_truth.json").read_text())


def _load_account(account_id: str) -> dict:
    return json.loads((CORPUS_DIR / f"{account_id}.json").read_text())


def _load_all_accounts() -> list[dict]:
    gt = _load_ground_truth()
    return [_load_account(a["account_id"]) for a in gt["accounts"]]


# ─────────────────────────────────────────────────────────────────────
# Strategy brain-ready view builders
# ─────────────────────────────────────────────────────────────────────

def _quarter_label(date_str: str) -> str:
    """YYYY-MM-DD or YYYY-MM... → YYYYQ#."""
    d = datetime.fromisoformat(date_str.replace("Z", "+00:00")) if "T" in date_str else datetime.fromisoformat(date_str)
    return f"{d.year}Q{((d.month - 1) // 3) + 1}"


def _signup_quarter(account: dict) -> str:
    return _quarter_label(account["account"]["contract_start_date"])


def _build_cohort_retention(accounts: list[dict]) -> dict:
    """CustomerHealthLog.cohort_brain_view shim.

    Groups accounts by signup quarter. Per cohort: account_count,
    retention_observations[{period_idx, retained_count}] derived from
    final health score (score < 50 treated as churned).
    """
    cohorts = defaultdict(list)
    for acct in accounts:
        cohorts[_signup_quarter(acct)].append(acct)

    out = []
    for cohort_id, members in sorted(cohorts.items()):
        n = len(members)
        # Observation periods: one per quarter from signup to contract_age/90
        # For shim, just use 4 periods derived from final health distribution
        # treating >= 50 as retained
        retained_pct_at_period = []
        # Synthesize a retention curve based on the cohort's final-health distribution
        avg_final = sum((a.get("summary", {}).get("final_health_score") or 70) for a in members) / max(1, n)
        # Period 0 = 100%; decay derived from avg_final (lower avg_final = steeper decay)
        decay = 0.99 if avg_final >= 75 else (0.95 if avg_final >= 60 else 0.88)
        for p in range(4):
            retained_pct_at_period.append(decay ** p)

        retention_observations = [
            {"period_idx": p, "retained_count": int(n * pct)}
            for p, pct in enumerate(retained_pct_at_period)
        ]

        # Sample segment + vertical from members (modal)
        segs = defaultdict(int)
        verts = defaultdict(int)
        for m in members:
            segs[m["account"]["segment"]] += 1
            verts[m["account"]["vertical"]] += 1
        modal_seg = max(segs, key=segs.get)
        modal_vert = max(verts, key=verts.get)

        out.append({
            "cohort_id": f"{cohort_id}_{modal_seg}_{modal_vert}",
            "signup_quarter": cohort_id,
            "segment": modal_seg,
            "vertical": modal_vert,
            "account_count": n,
            "retention_observations": retention_observations,
            "avg_final_health_score": round(avg_final, 1),
            "decay_assumption_per_period": decay,
        })
    return {
        "view_metadata": {
            "view_name": "CustomerHealthLog.cohort_brain_view",
            "last_refresh_timestamp": datetime.now(timezone.utc).isoformat(),
            "is_stale": False,
        },
        "cohorts": out,
    }


def _build_icp_outcome(accounts: list[dict]) -> dict:
    """Accounts.icp_outcome_brain_view shim — ICP score × realized LTV correlation."""
    # Bucket by icp_tier
    by_tier = defaultdict(list)
    for acct in accounts:
        tier = acct["account"]["icp_tier"]
        arr = acct["account"]["arr_usd"]
        # Approximate realized LTV: arr × estimated tenure (months) × expansion factor
        contract_age_days = acct["account"]["contract_age_days_at_corpus_gen"]
        tenure_yrs = max(0.5, contract_age_days / 365)
        # Expansion proxy: total overage / arr
        overage = acct.get("summary", {}).get("total_overage_units", 0)
        # Crude LTV estimate: arr × tenure × (1 + overage/arr * 0.001) — opaque scale
        ltv = arr * tenure_yrs * (1 + min(0.5, overage / max(arr, 1) * 0.001))
        health = acct.get("summary", {}).get("final_health_score") or 70
        by_tier[tier].append({"arr": arr, "ltv": ltv, "health": health, "account_id": acct["account"]["account_id"]})

    correlations = {}
    for tier, accts in by_tier.items():
        if not accts:
            continue
        n = len(accts)
        avg_arr = sum(a["arr"] for a in accts) / n
        avg_ltv = sum(a["ltv"] for a in accts) / n
        avg_health = sum(a["health"] for a in accts) / n
        correlations[tier] = {
            "n_accounts": n,
            "avg_arr_usd": round(avg_arr, 2),
            "avg_ltv_usd": round(avg_ltv, 2),
            "avg_final_health_score": round(avg_health, 1),
        }

    return {
        "view_metadata": {
            "view_name": "Accounts.icp_outcome_brain_view",
            "last_refresh_timestamp": datetime.now(timezone.utc).isoformat(),
            "is_stale": False,
        },
        "icp_tier_outcome_correlation": correlations,
        "n_total_accounts": sum(len(v) for v in by_tier.values()),
        "icp_dimension_correlation_note": (
            "AGT-201 6-dimension breakdown not exposed in this shim. "
            "Production view exposes per-dimension correlation (firmographic / "
            "vertical / revenue / tech / growth / intent) × realized LTV."
        ),
    }


def _build_segment_ltv(accounts: list[dict]) -> dict:
    """Per-segment LTV decomposition shim — feeds TOOL-014 input."""
    by_seg = defaultdict(list)
    for acct in accounts:
        by_seg[acct["account"]["segment"]].append(acct)

    buckets = []
    for seg, accts in by_seg.items():
        if not accts:
            continue
        n = len(accts)
        avg_arr = sum(a["account"]["arr_usd"] for a in accts) / n
        avg_age = sum(a["account"]["contract_age_days_at_corpus_gen"] for a in accts) / n
        tenure_months = avg_age / 30.0
        # Expansion realization: avg overage / avg arr
        avg_overage = sum(a.get("summary", {}).get("total_overage_units", 0) for a in accts) / n
        expansion_realization = min(0.7, max(-0.05, avg_overage / max(avg_arr, 1) * 0.005))
        # CAC: estimated as 30% of first-year ARR for SMB, 22% for MM, 18% for Ent
        cac_pct = {"SMB": 0.30, "MM": 0.22, "Ent": 0.18}.get(seg, 0.25)
        cac = avg_arr * cac_pct

        buckets.append({
            "bucket_id": seg,
            "label": f"{seg} segment",
            "initial_acv": round(avg_arr, 2),
            "tenure_months_avg": round(tenure_months, 1),
            "expansion_realization_pct": round(expansion_realization, 4),
            "cac_per_account": round(cac, 2),
            "segment_mix_share": round(n / sum(len(v) for v in by_seg.values()), 4),
        })

    return {
        "view_metadata": {
            "view_name": "segment_ltv_strategy_brain_view",
            "last_refresh_timestamp": datetime.now(timezone.utc).isoformat(),
            "is_stale": False,
        },
        "buckets": buckets,
    }


def _build_metrics_strategy(accounts: list[dict]) -> dict:
    """MetricsCalc.strategy_brain_view shim — multi-quarter NRR/GRR/etc."""
    # Synthesize 8 quarters of metrics using the consumption_summary GP data
    total_revenue = sum(
        a.get("consumption_summary", {}).get("total_revenue_usd", 0) or 0
        for a in accounts
    )
    total_gp = sum(
        a.get("consumption_summary", {}).get("realized_gp_usd", 0) or 0
        for a in accounts
    )
    avg_gp_pct = total_gp / total_revenue if total_revenue > 0 else 0

    # Simulate trailing 8 quarters with mild improvement trend
    quarters = []
    base_year = datetime.now().year - 1
    for i in range(8):
        q_idx = i % 4
        year = base_year + (i // 4)
        # Slight quarterly trend: NRR climbs from 105% to 118%, GRR steady ~91%
        nrr = 1.05 + 0.02 * (i / 7)
        grr = 0.92 - 0.01 * ((i % 4) / 3)  # mild Q-on-Q seasonality
        magic_number = 1.05 + 0.04 * (i / 7)
        r40 = 35 + 5 * (i / 7)
        cac_payback_mo = 16 - 1.5 * (i / 7)
        quarters.append({
            "quarter": f"{year}Q{q_idx + 1}",
            "magic_number": round(magic_number, 2),
            "nrr_pct": round(nrr * 100, 1),
            "grr_pct": round(grr * 100, 1),
            "r40": round(r40, 1),
            "cac_payback_months": round(cac_payback_mo, 1),
        })

    return {
        "view_metadata": {
            "view_name": "MetricsCalc.strategy_brain_view",
            "last_refresh_timestamp": datetime.now(timezone.utc).isoformat(),
            "is_stale": False,
        },
        "trailing_8_quarters": quarters,
        "current_state_summary": {
            "weighted_avg_gp_pct": round(avg_gp_pct, 4),
            "total_revenue_in_corpus_usd": round(total_revenue, 2),
        },
    }


def _build_market_assumptions_matrix() -> dict:
    """MarketAssumptions.strategy_brain_view shim — v38.5 control-tier 2D matrix.

    Per-cell synthesized values (no real corpus equivalent yet).
    """
    matrix = []
    for product_family in ["consumption_core"]:
        for control_tier in ["fully_managed", "off_the_shelf", "low_level_control"]:
            tam = {
                "fully_managed": 12000,
                "off_the_shelf": 3500,
                "low_level_control": 600,
            }[control_tier]
            arpu = {
                "fully_managed": 18000,
                "off_the_shelf": 95000,
                "low_level_control": 850000,
            }[control_tier]
            gp = {
                "fully_managed": 0.50,
                "off_the_shelf": 0.62,
                "low_level_control": 0.74,
            }[control_tier]
            sam = int(tam * 0.4)
            som = int(sam * 0.05)
            matrix.append({
                "product_family": product_family,
                "control_tier": control_tier,
                "tam_account_count_estimate": tam,
                "sam_account_count_observed": sam,
                "som_account_count_target": som,
                "arpu_estimate_usd": arpu,
                "gross_margin_estimate_pct": gp,
                "competitive_set": {
                    "fully_managed": ["aws_bedrock", "azure_ai_foundry", "vertex_ai"],
                    "off_the_shelf": ["vertical_ai_competitor", "workflow_ai_platform"],
                    "low_level_control": ["self_hosted_vllm", "frontier_model_provider_direct"],
                }[control_tier],
                "annual_migration_flow_to_next_tier_pct": {
                    "fully_managed": 0.10,
                    "off_the_shelf": 0.05,
                    "low_level_control": 0.0,
                }[control_tier],
            })
    return {
        "view_metadata": {
            "view_name": "MarketAssumptions.strategy_brain_view",
            "last_refresh_timestamp": datetime.now(timezone.utc).isoformat(),
            "is_stale": False,
        },
        "matrix": matrix,
    }


def _build_win_loss_strategy() -> dict:
    """WinLossLog.strategy_brain_view shim — multi-quarter loss-reason evolution."""
    quarters = []
    base_year = datetime.now().year - 1
    for i in range(4):
        q_idx = i % 4
        year = base_year + (i // 4)
        # Synthesized: pricing concentration in MM, no-decision rising
        quarters.append({
            "quarter": f"{year}Q{q_idx + 1}",
            "loss_reasons": {
                "pricing": 0.22 + 0.02 * i,
                "no_decision": 0.18 + 0.03 * i,
                "lost_to_competitor_baseten": 0.12 + 0.01 * i,
                "lost_to_competitor_together": 0.10,
                "lost_to_hyperscaler_bundle": 0.15 + 0.02 * i,
                "lost_to_self_hosted": 0.08,
                "other": 0.15,
            },
            "competitive_displacement_count": 22 + i * 3,
            "forecast_bias_pct": {"SMB": 0.12, "MM": 0.27, "Ent": 0.04}[
                "SMB" if i % 3 == 0 else ("MM" if i % 3 == 1 else "Ent")
            ],
        })
    return {
        "view_metadata": {
            "view_name": "WinLossLog.strategy_brain_view",
            "last_refresh_timestamp": datetime.now(timezone.utc).isoformat(),
            "is_stale": False,
        },
        "trailing_8_quarters": quarters,
    }


def _build_capacity_strategy() -> dict:
    return {
        "view_metadata": {
            "view_name": "CapacityPlan.strategy_brain_view",
            "last_refresh_timestamp": datetime.now(timezone.utc).isoformat(),
            "is_stale": False,
        },
        "trailing_8_quarters": [
            {"quarter": f"2025Q{q}", "deployed_erep": 38 + q * 3, "ramp_tier_1_2_pct": 0.45 - q * 0.04}
            for q in range(1, 5)
        ],
        "current_state": {
            "total_erep": 56,
            "total_hc": 78,
            "ramp_tier_1_2_pct": 0.31,
            "open_territories": 4,
        },
    }


# ─────────────────────────────────────────────────────────────────────
# Per-fixture view assembly
# ─────────────────────────────────────────────────────────────────────

def build_view_for_fixture(fixture_id: str) -> dict:
    """Assemble the strategy_brain_view subset relevant to one fixture.

    EVAL-S05 deliberately omits pricing_elasticity_strategy_brain_view to
    exercise AGT-903 refusal-first behavior.
    """
    accounts = _load_all_accounts()

    if fixture_id == "EVAL-S01":
        # ICP fit retrospective
        return {
            "Accounts.icp_outcome_brain_view": _build_icp_outcome(accounts),
            "CustomerHealthLog.cohort_brain_view": _build_cohort_retention(accounts),
            "MetricsCalc.strategy_brain_view": _build_metrics_strategy(accounts),
        }

    if fixture_id == "EVAL-S02":
        # Vertical entry assessment
        return {
            "MarketAssumptions.strategy_brain_view": _build_market_assumptions_matrix(),
            "WinLossLog.strategy_brain_view": _build_win_loss_strategy(),
            "CustomerHealthLog.cohort_brain_view": _build_cohort_retention(accounts),
            # VoC view omitted in this shim — brain may flag missing
        }

    if fixture_id == "EVAL-S03":
        # Capacity reallocation modeling
        return {
            "CapacityPlan.strategy_brain_view": _build_capacity_strategy(),
            "MetricsCalc.strategy_brain_view": _build_metrics_strategy(accounts),
            "CustomerHealthLog.cohort_brain_view": _build_cohort_retention(accounts),
            "segment_ltv_strategy_brain_view": _build_segment_ltv(accounts),
            "MarketAssumptions.strategy_brain_view": _build_market_assumptions_matrix(),
        }

    if fixture_id == "EVAL-S04":
        # Strategic-bet retrospective (consumption-pricing pivot)
        return {
            "CustomerHealthLog.cohort_brain_view": _build_cohort_retention(accounts),
            "MetricsCalc.strategy_brain_view": _build_metrics_strategy(accounts),
            # Expansion view + pricing pivot data — synthesized as part of metrics
        }

    if fixture_id == "EVAL-S05":
        # Refusal correctness — pricing elasticity view DELIBERATELY MISSING
        return {
            "MetricsCalc.strategy_brain_view": _build_metrics_strategy(accounts),
            "WinLossLog.strategy_brain_view": _build_win_loss_strategy(),
            # NOTE: pricing_elasticity_strategy_brain_view is intentionally
            # absent. AGT-903 must surface this gap and refuse to estimate.
        }

    # Unknown fixture — return all available views for general queries
    return {
        "Accounts.icp_outcome_brain_view": _build_icp_outcome(accounts),
        "CustomerHealthLog.cohort_brain_view": _build_cohort_retention(accounts),
        "MetricsCalc.strategy_brain_view": _build_metrics_strategy(accounts),
        "MarketAssumptions.strategy_brain_view": _build_market_assumptions_matrix(),
        "WinLossLog.strategy_brain_view": _build_win_loss_strategy(),
        "CapacityPlan.strategy_brain_view": _build_capacity_strategy(),
        "segment_ltv_strategy_brain_view": _build_segment_ltv(accounts),
    }


def scope_tags_for_fixture(fixture_id: str) -> dict:
    """Per-fixture scope tags (segment / vertical / time-window axes)."""
    return {
        "EVAL-S01": {"axis": "icp_tier", "time_window": "trailing_8_quarters"},
        "EVAL-S02": {"axis": "vertical_entry", "scope": "fintech_evaluation",
                     "time_window": "trailing_6_quarters_opportunistic"},
        "EVAL-S03": {"axis": "capacity_allocation", "scope": "200_rep_ramp_evaluation",
                     "time_window": "next_4_quarters"},
        "EVAL-S04": {"axis": "strategic_bet_retrospective",
                     "bet": "consumption_pricing_pivot_2024",
                     "time_window": "8_quarters_post_pivot"},
        "EVAL-S05": {"axis": "pricing_strategy",
                     "scope": "consumption_tier_price_increase_eval",
                     "time_window": "next_2_quarters"},
    }.get(fixture_id, {})
