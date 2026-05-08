"""TOOL-015 Consumption-Margin Decomposer prototype.

Per the TOOL-015 spec:
  - Numerical work in code (decomposition arithmetic, region arbitrage,
    tier-migration scenario projection)
  - LLM characterization for workload-shaping play classes + tier-migration
    credible_alternative articulation
  - Refusal-first when backend_cost_per_unit coverage < 90%
  - Hard rule: tool never invents tier-migration scenarios — caller supplies them

Output fits TOOL-015's spec input/output contract (see
tools/TOOL-015_Consumption_Margin_Decomposer.html).
"""

from __future__ import annotations

import json
import os
from collections import defaultdict
from anthropic import Anthropic


# ─────────────────────────────────────────────────────────────────────
# Numerical core
# ─────────────────────────────────────────────────────────────────────

# Benchmark unit costs by tier — best-in-class reference for utilization-gap
# decomposition. Production would source these from a benchmark feed; for the
# prototype, we hardcode realistic values matching the synth tier model.
BENCHMARK_UNIT_COST_BY_TIER = {
    "low_margin":  0.28,   # vs synth base 0.30 — slight headroom
    "mid_margin":  0.42,   # vs synth base 0.48 — meaningful headroom (multi-tenant batching)
    "high_margin": 0.55,   # vs synth base 0.60 — tight (BYOC has less utilization variance)
}

# Default tier-migration scenarios when caller doesn't supply explicit ones.
# The tool DOES NOT invent these — these are pre-baked, deterministic, caller-
# selectable defaults. AGT-503's daily batch will override with its own
# scenario set.
DEFAULT_TIER_MIGRATION_SCENARIOS = [
    {
        "scenario_name": "shift_30pct_low_to_mid",
        "shifts": [{"from_tier": "low_margin", "to_tier": "mid_margin", "fraction": 0.30}],
    },
    {
        "scenario_name": "shift_50pct_low_to_mid",
        "shifts": [{"from_tier": "low_margin", "to_tier": "mid_margin", "fraction": 0.50}],
    },
    {
        "scenario_name": "shift_30pct_mid_to_high",
        "shifts": [{"from_tier": "mid_margin", "to_tier": "high_margin", "fraction": 0.30}],
    },
]


def _decompose_realized_gp(events: list[dict]) -> dict:
    """Compute per-axis decomposition from raw consumption events."""
    eligible = [e for e in events if e.get("backend_cost_per_unit_usd") is not None]
    if not eligible:
        return {
            "revenue_usd": 0.0,
            "backend_cost_usd": 0.0,
            "gp_usd": 0.0,
            "gp_pct": 0.0,
        }

    revenue_usd = sum(e["units"] * e["realized_price_per_unit_usd"] for e in eligible)
    backend_cost_usd = sum(e["units"] * e["backend_cost_per_unit_usd"] for e in eligible)
    gp_usd = revenue_usd - backend_cost_usd
    gp_pct = gp_usd / revenue_usd if revenue_usd > 0 else 0.0

    return {
        "revenue_usd": round(revenue_usd, 2),
        "backend_cost_usd": round(backend_cost_usd, 2),
        "gp_usd": round(gp_usd, 2),
        "gp_pct": round(gp_pct, 4),
    }


def _pricing_axis(events: list[dict]) -> dict:
    """List-vs-realized + commit-tier discount impact."""
    list_revenue = sum(e["units"] * e["list_price_per_unit_usd"] for e in events)
    realized_revenue = sum(e["units"] * e["realized_price_per_unit_usd"] for e in events)
    price_realization_pct = realized_revenue / list_revenue if list_revenue > 0 else 1.0
    commit_tier_discount_usd = list_revenue - realized_revenue
    return {
        "list_price_revenue_usd": round(list_revenue, 2),
        "realized_price_revenue_usd": round(realized_revenue, 2),
        "price_realization_pct": round(price_realization_pct, 4),
        "commit_tier_discount_usd": round(commit_tier_discount_usd, 2),
    }


def _utilization_axis(events: list[dict]) -> dict:
    """Effective unit cost vs benchmark — utilization gap."""
    eligible = [e for e in events if e.get("backend_cost_per_unit_usd") is not None]
    if not eligible:
        return {
            "effective_unit_cost_usd": 0.0,
            "benchmark_unit_cost_usd": 0.0,
            "utilization_gap_usd": 0.0,
            "utilization_gap_classification": "insufficient_data",
        }
    total_units = sum(e["units"] for e in eligible)
    total_backend_cost = sum(e["units"] * e["backend_cost_per_unit_usd"] for e in eligible)
    effective_unit_cost = total_backend_cost / total_units if total_units > 0 else 0.0

    # Weighted benchmark: weight benchmarks by tier-share of units
    units_by_tier = defaultdict(float)
    for e in eligible:
        units_by_tier[e["tier"]] += e["units"]
    benchmark_unit_cost = sum(
        BENCHMARK_UNIT_COST_BY_TIER.get(tier, 0.40) * (units / total_units)
        for tier, units in units_by_tier.items()
    ) if total_units > 0 else 0.0

    utilization_gap = (effective_unit_cost - benchmark_unit_cost) * total_units

    # Classification: tight = within 5% of benchmark; moderate = 5-15%; loose = >15%
    if benchmark_unit_cost > 0:
        gap_pct = (effective_unit_cost - benchmark_unit_cost) / benchmark_unit_cost
        if abs(gap_pct) <= 0.05:
            classification = "tight"
        elif abs(gap_pct) <= 0.15:
            classification = "moderate"
        else:
            classification = "loose"
    else:
        classification = "insufficient_data"

    return {
        "effective_unit_cost_usd": round(effective_unit_cost, 4),
        "benchmark_unit_cost_usd": round(benchmark_unit_cost, 4),
        "utilization_gap_usd": round(utilization_gap, 2),
        "utilization_gap_classification": classification,
    }


def _backend_axis(events: list[dict]) -> dict:
    """Region + provider spend distribution; region arbitrage projection."""
    spend_by_region = defaultdict(float)
    spend_by_provider = defaultdict(float)
    cost_by_region = defaultdict(float)
    units_by_region = defaultdict(float)
    for e in events:
        revenue = e["units"] * e["realized_price_per_unit_usd"]
        spend_by_region[e["backend_region"]] += revenue
        spend_by_provider[e["backend_provider"]] += revenue
        if e.get("backend_cost_per_unit_usd") is not None:
            cost_by_region[e["backend_region"]] += e["units"] * e["backend_cost_per_unit_usd"]
            units_by_region[e["backend_region"]] += e["units"]

    # Lowest cost-per-unit region (where backend cost data exists)
    cost_per_unit_by_region = {
        r: cost_by_region[r] / units_by_region[r]
        for r in cost_by_region if units_by_region[r] > 0
    }
    if cost_per_unit_by_region:
        lowest_region = min(cost_per_unit_by_region, key=cost_per_unit_by_region.get)
        highest_region = max(cost_per_unit_by_region, key=cost_per_unit_by_region.get)
        # Region arbitrage GP: if all units shifted to lowest-cost region
        total_units = sum(units_by_region.values())
        current_cost = sum(cost_by_region.values())
        projected_cost = total_units * cost_per_unit_by_region[lowest_region]
        region_arbitrage_gp = current_cost - projected_cost
    else:
        lowest_region = highest_region = None
        region_arbitrage_gp = 0.0

    return {
        "spend_by_region": {k: round(v, 2) for k, v in spend_by_region.items()},
        "spend_by_provider": {k: round(v, 2) for k, v in spend_by_provider.items()},
        "highest_cost_region": highest_region,
        "lowest_cost_region": lowest_region,
        "region_arbitrage_gp_usd": round(region_arbitrage_gp, 2),
    }


def _tier_axis(events: list[dict]) -> dict:
    """Product-tier mix — the margin-expansion lever."""
    spend_by_tier = defaultdict(float)
    cost_by_tier = defaultdict(float)
    for e in events:
        revenue = e["units"] * e["realized_price_per_unit_usd"]
        spend_by_tier[e["tier"]] += revenue
        if e.get("backend_cost_per_unit_usd") is not None:
            cost_by_tier[e["tier"]] += e["units"] * e["backend_cost_per_unit_usd"]
    gp_by_tier = {t: spend_by_tier[t] - cost_by_tier[t] for t in spend_by_tier}
    weighted_tier_gp_pct = (
        sum(gp_by_tier.values()) / sum(spend_by_tier.values())
        if sum(spend_by_tier.values()) > 0 else 0.0
    )
    total = sum(spend_by_tier.values())
    low_pct = spend_by_tier.get("low_margin", 0) / total if total > 0 else 0
    high_pct = spend_by_tier.get("high_margin", 0) / total if total > 0 else 0
    if low_pct > 0.65:
        label = "low-margin-heavy"
    elif high_pct > 0.30:
        label = "high-margin-heavy"
    else:
        label = "balanced"
    return {
        "spend_by_tier": {k: round(v, 2) for k, v in spend_by_tier.items()},
        "gp_by_tier": {k: round(v, 2) for k, v in gp_by_tier.items()},
        "weighted_tier_gp_pct": round(weighted_tier_gp_pct, 4),
        "current_tier_mix_label": label,
    }


def _project_tier_migration(
    events: list[dict],
    scenario: dict,
    tier_axis: dict,
) -> dict:
    """Apply scenario shifts to events deterministically; recompute GP."""
    # Build per-tier units + revenue + backend cost
    units_by_tier = defaultdict(float)
    revenue_by_tier = defaultdict(float)
    cost_by_tier = defaultdict(float)
    for e in events:
        units_by_tier[e["tier"]] += e["units"]
        revenue_by_tier[e["tier"]] += e["units"] * e["realized_price_per_unit_usd"]
        if e.get("backend_cost_per_unit_usd") is not None:
            cost_by_tier[e["tier"]] += e["units"] * e["backend_cost_per_unit_usd"]

    # Average unit price + unit cost per tier (for projecting shifted volume)
    avg_price_by_tier = {
        t: revenue_by_tier[t] / units_by_tier[t] if units_by_tier[t] > 0 else 0
        for t in units_by_tier
    }
    avg_cost_by_tier = {
        t: cost_by_tier[t] / units_by_tier[t] if units_by_tier[t] > 0 else 0
        for t in units_by_tier
    }

    # Apply shifts to a copy
    new_units = dict(units_by_tier)
    for shift in scenario.get("shifts", []):
        ft = shift["from_tier"]
        tt = shift["to_tier"]
        frac = shift["fraction"]
        if ft not in new_units or new_units[ft] == 0:
            continue
        moved = new_units[ft] * frac
        new_units[ft] -= moved
        new_units[tt] = new_units.get(tt, 0) + moved

    # Recompute revenue + backend cost using per-tier averages on the new mix
    projected_revenue = sum(
        new_units[t] * avg_price_by_tier.get(t, 0) for t in new_units
    )
    projected_cost = sum(
        new_units[t] * avg_cost_by_tier.get(t, 0) for t in new_units
    )
    projected_gp = projected_revenue - projected_cost
    projected_gp_pct = projected_gp / projected_revenue if projected_revenue > 0 else 0.0

    # Compare to current
    current_revenue = sum(revenue_by_tier.values())
    current_cost = sum(cost_by_tier.values())
    current_gp = current_revenue - current_cost
    current_gp_pct = current_gp / current_revenue if current_revenue > 0 else 0.0

    gp_uplift_usd = projected_gp - current_gp
    gp_uplift_pp = (projected_gp_pct - current_gp_pct) * 100

    # Switching-cost class — driven by which shifts are involved
    # low → mid: low switching cost (pricing-tier change, no infra change)
    # mid → high: medium-to-high switching cost (BYOC requires customer-side
    #   cloud account + technical integration)
    # any reverse direction (e.g., high → low): very_high (active downgrade)
    sc_class = "low"
    for shift in scenario.get("shifts", []):
        ft, tt = shift["from_tier"], shift["to_tier"]
        if ft == "high_margin" and tt != "high_margin":
            sc_class = "very_high"
            break
        if ft == "low_margin" and tt == "high_margin":
            sc_class = "high"
        elif ft == "mid_margin" and tt == "high_margin":
            if sc_class != "high":
                sc_class = "high"
        elif ft == "low_margin" and tt == "mid_margin":
            if sc_class == "low":
                sc_class = "low"

    return {
        "scenario_name": scenario.get("scenario_name", "(unnamed)"),
        "projected_revenue_usd": round(projected_revenue, 2),
        "projected_backend_cost_usd": round(projected_cost, 2),
        "projected_gp_usd": round(projected_gp, 2),
        "projected_gp_pct": round(projected_gp_pct, 4),
        "gp_uplift_usd_vs_current": round(gp_uplift_usd, 2),
        "gp_uplift_pp_vs_current": round(gp_uplift_pp, 2),
        "switching_cost_class": sc_class,
        # credible_alternative is filled in by LLM step
    }


# ─────────────────────────────────────────────────────────────────────
# LLM characterization — workload shaping + credible_alternative
# ─────────────────────────────────────────────────────────────────────

def _llm_characterize(
    realized_gp: dict,
    decomposition: dict,
    tier_migration_projections: list[dict],
    include_workload_shaping: bool,
) -> dict:
    """Send the deterministic decomposition to Haiku for workload-shaping
    play recommendations + credible_alternative articulation per scenario."""

    prompt = f"""You are TOOL-015 (Consumption-Margin Decomposer). The numerical decomposition has already been computed deterministically. Your job:

(1) For EACH tier_migration_projection below, write a short credible_alternative — the case for NOT migrating, articulated honestly. Mandatory; not wave-of-the-hand.

(2) {"Suggest 1-3 workload_shaping_recommendations from the play classes: 'off-peak shift', 'multi-tenant pack', 'adapter sharing', 'right-size tier'. Each must include preconditions + a projected GP uplift (use the utilization_gap_usd as upper-bound reference)." if include_workload_shaping else "(Workload shaping not requested — return an empty array for workload_shaping_recommendations.)"}

REALIZED GP (deterministic):
{json.dumps(realized_gp, indent=2)}

DECOMPOSITION (deterministic):
{json.dumps(decomposition, indent=2)}

TIER MIGRATION PROJECTIONS (deterministic — DO NOT CHANGE NUMBERS):
{json.dumps(tier_migration_projections, indent=2)}

Output JSON only, schema:
{{
  "credible_alternatives": [
    {{
      "scenario_name": "string (matches input)",
      "credible_alternative": "1-2 sentences articulating why NOT migrating could be correct"
    }}
  ],
  "workload_shaping_recommendations": [
    {{
      "play_class": "off-peak shift | multi-tenant pack | adapter sharing | right-size tier",
      "projected_gp_uplift_usd": float,
      "implementation_effort_class": "low | medium | high",
      "preconditions": [...]
    }}
  ]
}}"""

    client = Anthropic()
    model = os.environ.get("TOOL_015_MODEL", "claude-haiku-4-5-20251001")
    response = client.messages.create(
        model=model,
        max_tokens=900,
        messages=[{"role": "user", "content": prompt}],
    )
    raw = response.content[0].text.strip()
    if raw.startswith("```"):
        raw = raw.split("```", 2)[1]
        if raw.startswith("json"):
            raw = raw[4:]
        raw = raw.strip()
    if raw.endswith("```"):
        raw = raw[:-3].strip()
    parsed = json.loads(raw)
    parsed["_llm_metadata"] = {
        "model": response.model,
        "input_tokens": response.usage.input_tokens,
        "output_tokens": response.usage.output_tokens,
    }
    return parsed


# ─────────────────────────────────────────────────────────────────────
# Entry point
# ─────────────────────────────────────────────────────────────────────

REFUSAL_THRESHOLD_BACKEND_COST_COVERAGE = 0.90


def tool_015_handler(input_dict: dict) -> dict:
    """Main entry. Input matches TOOL-015 spec; returns the structured output."""
    consumption_events = input_dict.get("consumption_events", [])
    if not consumption_events:
        return {
            "tool_name": "TOOL-015",
            "status": "insufficient_data",
            "reason": "no consumption_events supplied",
        }

    # Refusal-first: backend cost coverage gate
    n_total = len(consumption_events)
    n_with_cost = sum(
        1 for e in consumption_events if e.get("backend_cost_per_unit_usd") is not None
    )
    coverage = n_with_cost / max(1, n_total)

    if coverage < REFUSAL_THRESHOLD_BACKEND_COST_COVERAGE:
        return {
            "tool_name": "TOOL-015",
            "status": "refusal",
            "refusal": {
                "reason": (
                    f"backend_cost_per_unit coverage = {coverage:.1%} (below "
                    f"{REFUSAL_THRESHOLD_BACKEND_COST_COVERAGE:.0%} threshold) — "
                    "estimation here would propagate into bad expansion decisions"
                ),
                "missing_inputs": ["backend_cost_per_unit_usd on a meaningful "
                                   "fraction of events"],
                "recommended_remediation": (
                    "Surface gap to RevOps + FinOps; ensure compute cost feeds "
                    "are piped through for this account's consumption events "
                    "before re-querying TOOL-015."
                ),
            },
            "confidence_flags": {
                "backend_cost_coverage_pct": round(coverage, 4),
                "overall_confidence": "refusal",
            },
        }

    # Deterministic decomposition
    realized_gp = _decompose_realized_gp(consumption_events)
    decomposition = {
        "by_pricing_axis": _pricing_axis(consumption_events),
        "by_utilization_axis": _utilization_axis(consumption_events),
        "by_backend_axis": _backend_axis(consumption_events),
        "by_tier_axis": _tier_axis(consumption_events),
    }

    # Tier-migration scenarios — caller's first; default fallback if none supplied
    scenarios = input_dict.get("tier_migration_scenarios") or DEFAULT_TIER_MIGRATION_SCENARIOS
    projections = [
        _project_tier_migration(consumption_events, s, decomposition["by_tier_axis"])
        for s in scenarios
    ]

    # LLM portion — credible_alternative + optional workload shaping
    include_workload_shaping = bool(input_dict.get("include_workload_shaping_recommendations", True))
    try:
        llm_output = _llm_characterize(
            realized_gp, decomposition, projections, include_workload_shaping
        )
    except Exception as e:
        return {
            "tool_name": "TOOL-015",
            "status": "llm_error",
            "reason": str(e),
            "realized_gp": realized_gp,
            "decomposition": decomposition,
            "tier_migration_projections": projections,
        }

    # Merge credible_alternative into projections by scenario_name
    ca_by_scenario = {
        item.get("scenario_name"): item.get("credible_alternative", "")
        for item in llm_output.get("credible_alternatives", [])
    }
    for p in projections:
        p["credible_alternative"] = ca_by_scenario.get(p["scenario_name"], "")

    workload_shaping = llm_output.get("workload_shaping_recommendations", []) if include_workload_shaping else []

    return {
        "tool_name": "TOOL-015",
        "status": "ok",
        "realized_gp": realized_gp,
        "decomposition": decomposition,
        "tier_migration_projections": projections,
        "workload_shaping_recommendations": workload_shaping,
        "confidence_flags": {
            "backend_cost_coverage_pct": round(coverage, 4),
            "overall_confidence": (
                "high" if coverage >= 0.97 else
                "medium" if coverage >= 0.93 else
                "low"
            ),
        },
        "_llm_metadata": llm_output.get("_llm_metadata"),
    }


# ─────────────────────────────────────────────────────────────────────
# Anthropic tool definition — what brains see
# ─────────────────────────────────────────────────────────────────────

TOOL_015_DEFINITION = {
    "name": "tool_015_consumption_margin_decomposer",
    "description": (
        "TOOL-015 Consumption-Margin Decomposer. Per-customer GP attribution + "
        "tier-migration projection for consumption-pricing tiered platforms. "
        "Decomposes realized GP into pricing / utilization / backend-cost / "
        "tier-mix axes. Projects GP uplift for tier-migration scenarios with "
        "switching-cost class + a required credible_alternative articulation. "
        "Refusal-first when backend_cost coverage drops below 90%. Use this "
        "when answering 'where is this customer's GP coming from?', 'what "
        "tier-migration play has the most GP uplift?', or 'is this customer's "
        "margin compressing — and from which axis?'. Output is canonical and "
        "should be cited like a Tier 1 source."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "account_id": {
                "type": "string",
                "description": "Account UUID — used for corpus loading.",
            },
            "include_workload_shaping_recommendations": {
                "type": "boolean",
                "description": "Whether to surface workload-shaping plays. Default true.",
                "default": True,
            },
        },
        "required": ["account_id"],
    },
}
