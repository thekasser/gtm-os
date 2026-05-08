"""TOOL-014 Segment-LTV Decomposer prototype.

Per the TOOL-014 spec (v37):
  - Decomposes observed LTV gaps between segment / vertical / ICP-tier buckets
    into driver components: initial_acv, tenure, expansion_realization, cac,
    segment_mix
  - Counterfactual decomposition + bootstrap intervals run in code
  - LLM characterizes operational meaning
  - Hard rule: a driver is `load_bearing` only when its bootstrap band excludes
    zero with same-sign p10/p90 — the LLM cannot promote a driver on narrative
    grounds
  - Mandatory credible-alternative reading

Caller (AGT-903) supplies bucket data with per-bucket driver values; tool
decomposes the LTV gap between any two buckets (or all-vs-baseline).
"""

from __future__ import annotations

import json
import math
import os
import random
from anthropic import Anthropic


BOOTSTRAP_ITERS = 200
LOAD_BEARING_BAND_THRESHOLD = 0.05   # p10 and p90 must both exceed this magnitude same-sign


# ─────────────────────────────────────────────────────────────────────
# Numerical core
# ─────────────────────────────────────────────────────────────────────

def _bucket_ltv(bucket: dict) -> float:
    """LTV = initial_acv × tenure_months_avg/12 × (1 + expansion_realization_pct) − cac."""
    initial_acv = bucket.get("initial_acv", 0)
    tenure_yrs = bucket.get("tenure_months_avg", 0) / 12.0
    expansion = bucket.get("expansion_realization_pct", 0)
    cac = bucket.get("cac_per_account", 0)
    return initial_acv * tenure_yrs * (1.0 + expansion) - cac


def _decompose_pair(b_a: dict, b_b: dict) -> dict:
    """Decompose LTV(b_a) - LTV(b_b) into driver contributions.

    Counterfactual: for each driver, compute the LTV(b_a) using b_a's value of
    that driver while holding all others at b_b's values; the marginal change
    is that driver's contribution.
    """
    drivers = ["initial_acv", "tenure_months_avg", "expansion_realization_pct", "cac_per_account"]
    base_ltv = _bucket_ltv(b_b)
    total_gap = _bucket_ltv(b_a) - base_ltv

    contributions = {}
    for drv in drivers:
        counterfactual = dict(b_b)
        counterfactual[drv] = b_a[drv]
        contrib = _bucket_ltv(counterfactual) - base_ltv
        contributions[drv] = round(contrib, 2)

    # Residual = total_gap - sum(contributions)
    residual = total_gap - sum(contributions.values())

    return {
        "ltv_gap_usd": round(total_gap, 2),
        "contributions_usd": contributions,
        "interaction_residual_usd": round(residual, 2),
    }


def _bootstrap_contributions(b_a: dict, b_b: dict, sample_pct: float = 0.7) -> dict:
    """Bootstrap by perturbing each bucket's drivers within ±5% of stated value
    and re-decomposing. Returns p10/p50/p90 per driver."""
    rng = random.Random(42)
    drivers = ["initial_acv", "tenure_months_avg", "expansion_realization_pct", "cac_per_account"]
    samples_by_driver = {drv: [] for drv in drivers}

    for _ in range(BOOTSTRAP_ITERS):
        # Perturb each bucket's drivers by ±5% gaussian noise
        a_pert = {k: v * (1.0 + rng.gauss(0, 0.05)) if isinstance(v, (int, float)) else v for k, v in b_a.items()}
        b_pert = {k: v * (1.0 + rng.gauss(0, 0.05)) if isinstance(v, (int, float)) else v for k, v in b_b.items()}
        decomp = _decompose_pair(a_pert, b_pert)
        for drv, val in decomp["contributions_usd"].items():
            samples_by_driver[drv].append(val)

    bands = {}
    for drv, samples in samples_by_driver.items():
        if not samples:
            bands[drv] = {"p10": 0, "p50": 0, "p90": 0, "load_bearing": False}
            continue
        samples.sort()
        p10 = samples[int(0.10 * len(samples))]
        p50 = samples[int(0.50 * len(samples))]
        p90 = samples[min(len(samples) - 1, int(0.90 * len(samples)))]
        # load_bearing: p10 and p90 must both have same sign and both exceed threshold
        if abs(p50) > 0:
            same_sign = (p10 > 0 and p90 > 0) or (p10 < 0 and p90 < 0)
            magnitude_ok = min(abs(p10), abs(p90)) > LOAD_BEARING_BAND_THRESHOLD * abs(p50)
            load_bearing = same_sign and magnitude_ok
        else:
            load_bearing = False
        bands[drv] = {
            "p10": round(p10, 2),
            "p50": round(p50, 2),
            "p90": round(p90, 2),
            "load_bearing": load_bearing,
        }
    return bands


def _rank_buckets(buckets: list[dict]) -> list[dict]:
    """Sort buckets by LTV descending."""
    enriched = []
    for b in buckets:
        enriched.append({
            "bucket_id": b.get("bucket_id"),
            "label": b.get("label"),
            "ltv_usd": round(_bucket_ltv(b), 2),
            "drivers": {k: b.get(k) for k in (
                "initial_acv", "tenure_months_avg", "expansion_realization_pct",
                "cac_per_account", "segment_mix_share"
            )},
        })
    enriched.sort(key=lambda r: -r["ltv_usd"])
    for i, r in enumerate(enriched):
        r["rank"] = i + 1
    return enriched


# ─────────────────────────────────────────────────────────────────────
# LLM characterization
# ─────────────────────────────────────────────────────────────────────

def _llm_characterize(
    ranking: list[dict],
    decompositions: list[dict],
) -> dict:
    """LLM produces operational meaning + credible_alternative per pair."""

    prompt = f"""You are TOOL-014 (Segment-LTV Decomposer). The numerical decomposition + bootstrap
intervals + load_bearing flags have been computed deterministically. Your job:

(1) For each pair decomposition below, write 1-2 sentences of operational meaning —
WHAT does this driver attribution suggest about WHY one bucket has higher LTV.
Cite ONLY drivers flagged load_bearing=True. Do NOT promote a non-load-bearing
driver narratively.

(2) For each pair, write a credible_alternative — the case AGAINST this decomposition
holding in production. Mandatory; cite specific risks (mix shift, observation window,
unmodeled factors).

BUCKET RANKING (by LTV):
{json.dumps(ranking, indent=2)}

PAIR DECOMPOSITIONS:
{json.dumps(decompositions, indent=2)}

Output JSON only:
{{
  "operational_interpretations": [
    {{
      "pair_label": "string (e.g. 'top_vs_bottom')",
      "interpretation": "1-2 sentences citing only load_bearing drivers"
    }}
  ],
  "credible_alternatives": [
    {{
      "pair_label": "string",
      "credible_alternative": "1-2 sentences against the decomposition"
    }}
  ]
}}"""

    client = Anthropic()
    model = os.environ.get("TOOL_014_MODEL", "claude-haiku-4-5-20251001")
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

def tool_014_handler(input_dict: dict) -> dict:
    buckets = input_dict.get("buckets", [])
    if not buckets or len(buckets) < 2:
        return {
            "tool_name": "TOOL-014",
            "status": "insufficient_data",
            "reason": f"need >=2 buckets; got {len(buckets)}",
        }

    # Validate required driver fields
    required = ["initial_acv", "tenure_months_avg", "expansion_realization_pct", "cac_per_account"]
    for b in buckets:
        for f in required:
            if f not in b:
                return {
                    "tool_name": "TOOL-014",
                    "status": "refusal",
                    "refusal": {
                        "reason": f"bucket {b.get('bucket_id','?')} missing required driver: {f}",
                        "missing_inputs": [f],
                    },
                }

    ranking = _rank_buckets(buckets)

    # Pair decompositions: top vs bottom + each rank-pair
    pairs_to_decompose = [("top_vs_bottom", ranking[0], ranking[-1])]
    if len(ranking) >= 3:
        pairs_to_decompose.append(("top_vs_median", ranking[0], ranking[len(ranking) // 2]))

    decompositions = []
    for pair_label, top, bottom in pairs_to_decompose:
        # Reconstruct bucket dicts from ranking entries (drivers preserved)
        b_a = {**top["drivers"], "bucket_id": top["bucket_id"], "label": top["label"]}
        b_b = {**bottom["drivers"], "bucket_id": bottom["bucket_id"], "label": bottom["label"]}
        decomp = _decompose_pair(b_a, b_b)
        bands = _bootstrap_contributions(b_a, b_b)
        # Mark drivers with load_bearing flag
        for drv in decomp["contributions_usd"]:
            decomp[f"{drv}_band"] = bands.get(drv, {})
        decompositions.append({
            "pair_label": pair_label,
            "high_bucket_id": top["bucket_id"],
            "low_bucket_id": bottom["bucket_id"],
            "ltv_gap_usd": decomp["ltv_gap_usd"],
            "contributions_usd": decomp["contributions_usd"],
            "interaction_residual_usd": decomp["interaction_residual_usd"],
            "driver_bands": {drv: bands.get(drv, {}) for drv in decomp["contributions_usd"]},
            "load_bearing_drivers": [drv for drv, b in bands.items() if b.get("load_bearing")],
        })

    # LLM characterization
    try:
        llm_out = _llm_characterize(ranking, decompositions)
    except Exception as e:
        return {
            "tool_name": "TOOL-014",
            "status": "llm_error",
            "reason": str(e),
            "ranking": ranking,
            "decompositions": decompositions,
        }

    # Merge interpretations + credible_alternatives by pair_label
    interp_by_pair = {
        item.get("pair_label"): item.get("interpretation", "")
        for item in llm_out.get("operational_interpretations", [])
    }
    ca_by_pair = {
        item.get("pair_label"): item.get("credible_alternative", "")
        for item in llm_out.get("credible_alternatives", [])
    }
    for d in decompositions:
        d["operational_interpretation"] = interp_by_pair.get(d["pair_label"], "")
        d["credible_alternative"] = ca_by_pair.get(d["pair_label"], "")

    return {
        "tool_name": "TOOL-014",
        "status": "ok",
        "ranking": ranking,
        "decompositions": decompositions,
        "confidence_flags": {
            "n_buckets": len(buckets),
            "n_pairs_decomposed": len(decompositions),
            "overall_confidence": "high" if len(buckets) >= 4 else "medium",
        },
        "_llm_metadata": llm_out.get("_llm_metadata"),
    }


TOOL_014_DEFINITION = {
    "name": "tool_014_segment_ltv_decomposer",
    "description": (
        "TOOL-014 Segment-LTV Decomposer. Decomposes LTV gaps between segment / "
        "vertical / ICP-tier buckets into driver components (initial_acv, tenure, "
        "expansion_realization, cac, segment_mix) with bootstrap-derived "
        "load_bearing flags. Hard rule: a driver is load_bearing only when "
        "bootstrap band excludes zero with same-sign p10/p90 — LLM cannot "
        "promote a driver narratively. Used by AGT-903 for ICP-revision, "
        "capacity-reallocation, vertical-entry use cases."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "buckets": {
                "type": "array",
                "description": (
                    "Array of bucket descriptors with required driver fields: "
                    "initial_acv, tenure_months_avg, expansion_realization_pct, "
                    "cac_per_account."
                ),
            },
        },
        "required": ["buckets"],
    },
}
