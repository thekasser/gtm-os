"""TOOL-013 Cohort Retention Forecaster prototype.

Per the TOOL-013 spec (v37):
  - Reads observed retention curves for one or more signup-quarter cohorts
  - Projects forward with confidence bands per cohort
  - Cross-cohort characterization (stable / degrading / improving / mixed /
    insufficient_signal)
  - Numerical core: survival/decay fits with bootstrap intervals
  - LLM characterizes the operational meaning + mandatory credible_alternative
  - Refusal-first when cohort_size < 25 accounts or observed_periods < 4

Caller (AGT-903) assembles cohort observations from multi-quarter
strategy_brain_views; tool projects forward and classifies.
"""

from __future__ import annotations

import json
import math
import os
import random
from anthropic import Anthropic


# Refusal thresholds (per spec)
MIN_COHORT_SIZE = 25
MIN_OBSERVED_PERIODS = 4

# Bootstrap iterations for confidence bands
BOOTSTRAP_ITERS = 200


# ─────────────────────────────────────────────────────────────────────
# Numerical core — survival/decay fits + bootstrap
# ─────────────────────────────────────────────────────────────────────

def _fit_geometric_decay(periods: list[int], retained_pct: list[float]) -> tuple[float, float]:
    """Fit r_t = r_0 * d^t in log space. Returns (r_0, decay_rate_per_period).

    decay_rate_per_period = d, where 1.0 = no churn / 0.95 = 5% periodic churn.
    """
    # Filter out zeros (log-undefined)
    pairs = [(t, r) for t, r in zip(periods, retained_pct) if r > 0]
    if len(pairs) < 2:
        return retained_pct[0] if retained_pct else 1.0, 1.0
    ts = [p[0] for p in pairs]
    log_rs = [math.log(p[1]) for p in pairs]
    n = len(ts)
    mt = sum(ts) / n
    mlr = sum(log_rs) / n
    sxy = sum((t - mt) * (lr - mlr) for t, lr in zip(ts, log_rs))
    sxx = sum((t - mt) ** 2 for t in ts)
    if sxx == 0:
        return pairs[0][1], 1.0
    slope = sxy / sxx
    intercept = mlr - slope * mt
    r_0 = math.exp(intercept)
    decay = math.exp(slope)
    return r_0, decay


def _bootstrap_decay(retained_pct: list[float], n_iter: int = BOOTSTRAP_ITERS) -> dict:
    """Bootstrap (period, retained_pct) pairs to get decay distribution."""
    n = len(retained_pct)
    if n < 2:
        return {"p10": 1.0, "p50": 1.0, "p90": 1.0}
    rng = random.Random(42)  # deterministic bootstrap
    decays = []
    for _ in range(n_iter):
        sample_idx = [rng.randint(0, n - 1) for _ in range(n)]
        sample_periods = [i for i in sample_idx]
        sample_pct = [retained_pct[i] for i in sample_idx]
        try:
            _, d = _fit_geometric_decay(sample_periods, sample_pct)
            decays.append(d)
        except (ValueError, ZeroDivisionError):
            continue
    if not decays:
        return {"p10": 1.0, "p50": 1.0, "p90": 1.0}
    decays.sort()
    return {
        "p10": decays[int(0.10 * len(decays))],
        "p50": decays[int(0.50 * len(decays))],
        "p90": decays[min(len(decays) - 1, int(0.90 * len(decays)))],
    }


def _classify_decay(decay: float) -> str:
    """Period-over-period retention decay rate → label."""
    if decay >= 0.97:
        return "stable"
    if decay >= 0.92:
        return "degrading_slow"
    if decay >= 0.85:
        return "degrading_moderate"
    return "degrading_fast"


def _project_cohort_curve(
    r_0: float, decay: float, periods_observed: int,
    horizon_periods: int, decay_low: float, decay_high: float,
) -> dict:
    """Forward-project retention curve with confidence band."""
    proj_mid = []
    proj_low = []
    proj_high = []
    for t in range(periods_observed, periods_observed + horizon_periods):
        proj_mid.append(round(r_0 * (decay ** t), 4))
        proj_low.append(round(r_0 * (decay_low ** t), 4))
        proj_high.append(round(r_0 * (decay_high ** t), 4))
    return {
        "mid": proj_mid,
        "low": proj_low,
        "high": proj_high,
    }


# ─────────────────────────────────────────────────────────────────────
# LLM characterization
# ─────────────────────────────────────────────────────────────────────

def _llm_characterize(
    per_cohort_facts: list[dict],
    cross_cohort_label: str,
) -> dict:
    """Send numerical facts to Haiku for cross-cohort interpretation +
    per-cohort credible_alternative."""

    prompt = f"""You are TOOL-013 (Cohort Retention Forecaster). The numerical fits + bootstrap
intervals + classification labels have already been computed deterministically.
Your job:

(1) Provide a short cross-cohort interpretation paragraph (2-3 sentences) grounded in
the per-cohort facts below. Cite specific cohort_ids.

(2) For each cohort, write a short credible_alternative — the case for NOT trusting
this cohort's projection. Mandatory; not wave-of-the-hand. Acceptable bases: small
cohort size, short observation window, atypical product/segment context, recent
mix shift, exogenous events (pricing change, GTM shift).

PER-COHORT FACTS:
{json.dumps(per_cohort_facts, indent=2)}

CROSS-COHORT CLASSIFICATION (deterministic): "{cross_cohort_label}"

Output JSON only:
{{
  "cross_cohort_interpretation": "string — 2-3 sentences citing specific cohort_ids",
  "credible_alternatives": [
    {{
      "cohort_id": "string",
      "credible_alternative": "1-2 sentences — case for NOT trusting this cohort's projection"
    }}
  ]
}}"""

    client = Anthropic()
    model = os.environ.get("TOOL_013_MODEL", "claude-haiku-4-5-20251001")
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
# Cross-cohort classification
# ─────────────────────────────────────────────────────────────────────

def _classify_cross_cohort(per_cohort_labels: list[str]) -> str:
    """stable / degrading / improving / mixed / insufficient_signal."""
    if not per_cohort_labels:
        return "insufficient_signal"
    counts = {}
    for label in per_cohort_labels:
        counts[label] = counts.get(label, 0) + 1
    if "insufficient_signal" in counts and counts["insufficient_signal"] >= len(per_cohort_labels) // 2:
        return "insufficient_signal"
    if all(l == "stable" for l in per_cohort_labels):
        return "stable"
    if all(l.startswith("degrading") for l in per_cohort_labels):
        # Are later cohorts (higher signup_quarter) degrading faster?
        # Simpler heuristic: dominant degrade label
        slow = counts.get("degrading_slow", 0)
        mod = counts.get("degrading_moderate", 0)
        fast = counts.get("degrading_fast", 0)
        if fast > slow + mod:
            return "degrading_fast"
        return "degrading"
    return "mixed"


# ─────────────────────────────────────────────────────────────────────
# Entry point
# ─────────────────────────────────────────────────────────────────────

def tool_013_handler(input_dict: dict) -> dict:
    """Main entry."""
    cohorts = input_dict.get("cohorts", [])
    horizon = input_dict.get("horizon_periods", 4)

    if not cohorts:
        return {
            "tool_name": "TOOL-013",
            "status": "insufficient_data",
            "reason": "no cohorts supplied",
        }

    # Refusal pass + per-cohort fitting
    per_cohort_facts = []
    per_cohort_projections = []
    per_cohort_labels = []
    refused_cohorts = []

    for cohort in cohorts:
        cid = cohort.get("cohort_id", "?")
        size = cohort.get("account_count", 0)
        observations = cohort.get("retention_observations", []) or []

        if size < MIN_COHORT_SIZE:
            refused_cohorts.append({
                "cohort_id": cid,
                "reason": f"cohort_size={size} below {MIN_COHORT_SIZE}",
            })
            per_cohort_labels.append("insufficient_signal")
            continue
        if len(observations) < MIN_OBSERVED_PERIODS:
            refused_cohorts.append({
                "cohort_id": cid,
                "reason": f"observed_periods={len(observations)} below {MIN_OBSERVED_PERIODS}",
            })
            per_cohort_labels.append("insufficient_signal")
            continue

        observations.sort(key=lambda o: o["period_idx"])
        periods = [o["period_idx"] for o in observations]
        retained_counts = [o["retained_count"] for o in observations]
        retained_pct = [c / size for c in retained_counts]

        r_0, decay = _fit_geometric_decay(periods, retained_pct)
        bootstrap = _bootstrap_decay(retained_pct)
        label = _classify_decay(decay)
        projection = _project_cohort_curve(
            r_0, decay, len(observations), horizon,
            bootstrap["p10"], bootstrap["p90"],
        )

        per_cohort_facts.append({
            "cohort_id": cid,
            "signup_quarter": cohort.get("signup_quarter"),
            "segment": cohort.get("segment"),
            "vertical": cohort.get("vertical"),
            "account_count": size,
            "observed_periods": len(observations),
            "observed_retained_pct": [round(p, 4) for p in retained_pct],
            "fit": {
                "r_0": round(r_0, 4),
                "decay_per_period_p50": round(decay, 4),
                "decay_per_period_p10": round(bootstrap["p10"], 4),
                "decay_per_period_p90": round(bootstrap["p90"], 4),
            },
            "label": label,
            "projection_horizon_periods": horizon,
        })
        per_cohort_projections.append({
            "cohort_id": cid,
            "projection_mid_pct": projection["mid"],
            "projection_p10_pct": projection["low"],
            "projection_p90_pct": projection["high"],
        })
        per_cohort_labels.append(label)

    if not per_cohort_facts:
        return {
            "tool_name": "TOOL-013",
            "status": "refusal",
            "refusal": {
                "reason": "all supplied cohorts refused per spec thresholds",
                "refused_cohorts": refused_cohorts,
                "thresholds": {
                    "min_cohort_size": MIN_COHORT_SIZE,
                    "min_observed_periods": MIN_OBSERVED_PERIODS,
                },
            },
            "confidence_flags": {"overall_confidence": "refusal"},
        }

    cross_label = _classify_cross_cohort(
        [c["label"] for c in per_cohort_facts]
    )

    # LLM characterization
    try:
        llm_out = _llm_characterize(per_cohort_facts, cross_label)
    except Exception as e:
        return {
            "tool_name": "TOOL-013",
            "status": "llm_error",
            "reason": str(e),
            "per_cohort_facts": per_cohort_facts,
            "per_cohort_projections": per_cohort_projections,
            "cross_cohort_classification": cross_label,
            "refused_cohorts": refused_cohorts,
        }

    # Merge credible_alternatives by cohort_id
    ca_by_cohort = {
        item.get("cohort_id"): item.get("credible_alternative", "")
        for item in llm_out.get("credible_alternatives", [])
    }
    for f in per_cohort_facts:
        f["credible_alternative"] = ca_by_cohort.get(f["cohort_id"], "")

    return {
        "tool_name": "TOOL-013",
        "status": "ok",
        "cross_cohort_classification": cross_label,
        "cross_cohort_interpretation": llm_out.get("cross_cohort_interpretation", ""),
        "per_cohort_facts": per_cohort_facts,
        "per_cohort_projections": per_cohort_projections,
        "refused_cohorts": refused_cohorts,
        "confidence_flags": {
            "n_cohorts_fit": len(per_cohort_facts),
            "n_cohorts_refused": len(refused_cohorts),
            "overall_confidence": (
                "high" if len(refused_cohorts) == 0 and len(per_cohort_facts) >= 3 else
                "medium" if len(per_cohort_facts) >= 2 else
                "low"
            ),
        },
        "_llm_metadata": llm_out.get("_llm_metadata"),
    }


TOOL_013_DEFINITION = {
    "name": "tool_013_cohort_retention_forecaster",
    "description": (
        "TOOL-013 Cohort Retention Forecaster. Reads observed retention curves "
        "for signup-quarter cohorts and projects forward with confidence bands. "
        "Cohort-level analogue of TOOL-004. Refusal-first when cohort < 25 "
        "accounts or < 4 observed periods. Used by AGT-903 for 'did the bet "
        "work?', 'is retention flattening on newer cohorts?', 'what's the "
        "projected NRR floor on the 2024 cohort?' queries. Output is canonical "
        "and should be cited like a Tier 1 source."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "cohorts": {
                "type": "array",
                "description": "Array of cohort descriptors with retention observations.",
            },
            "horizon_periods": {
                "type": "integer",
                "description": "Forward periods to project. Default 4.",
                "default": 4,
            },
        },
        "required": ["cohorts"],
    },
}
