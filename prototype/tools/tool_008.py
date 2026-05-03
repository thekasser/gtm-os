"""TOOL-008 Product Adoption Pattern Recognizer.

Per the TOOL-008 spec:
  - Numerical work in code (breadth, concentration index, abandonment counts)
  - LLM characterization for primary_pattern + key_observations
  - Output is a structured pattern classification a brain can cite
  - Onboarding-aware: <60 days into contract → "activating", not "surface_only"
  - Cohort-baseline degradation: missing baseline → data_completeness="medium"

Different shape than TOOL-004 — this is feature engagement (which features
are used, by how many users), not consumption volume.
"""

from __future__ import annotations

import json
import math
import os
from datetime import datetime, timezone
from anthropic import Anthropic


# ─────────────────────────────────────────────────────────────────────
# Numerical core (no LLM)
# ─────────────────────────────────────────────────────────────────────

def _parse_iso(s: str | None) -> datetime | None:
    if not s:
        return None
    try:
        if s.endswith("Z"):
            s = s[:-1] + "+00:00"
        dt = datetime.fromisoformat(s)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt
    except Exception:
        return None


def _gini(values: list[float]) -> float:
    """Gini coefficient — 0 = uniform, 1 = fully concentrated."""
    if not values:
        return 0.0
    sorted_v = sorted(values)
    n = len(sorted_v)
    total = sum(sorted_v)
    if total == 0:
        return 0.0
    cum = 0.0
    for i, v in enumerate(sorted_v, start=1):
        cum += i * v
    return (2 * cum) / (n * total) - (n + 1) / n


def _compute_metrics(
    feature_usage: list[dict],
    window_days: int,
    snapshot_date: datetime,
    cohort_baseline: dict | None,
) -> dict:
    """Compute deterministic adoption metrics from feature_usage rows."""
    n = len(feature_usage)
    breadth = n

    # Per-category counts + adoption percentages
    category_counts: dict[str, int] = {}
    for row in feature_usage:
        cat = row.get("feature_category", "unknown")
        category_counts[cat] = category_counts.get(cat, 0) + 1

    # Spec category sizes — used to compute % of category adopted.
    # Hardcoded to match the synth taxonomy; production would derive from a
    # product-feature catalog table.
    category_total: dict[str, int] = {
        "core": 5, "advanced": 6, "integration": 5, "admin": 4, "experimental": 3,
    }
    core_pct = category_counts.get("core", 0) / category_total["core"]
    advanced_pct = category_counts.get("advanced", 0) / category_total["advanced"]
    integration_count = category_counts.get("integration", 0)

    # Concentration: Gini over users_pct_of_active across features.
    # High Gini = a few features dominate (concentrated); low = broad.
    user_pcts = [float(row.get("users_pct_of_active", 0.0)) for row in feature_usage]
    concentration_index = _gini(user_pcts) if user_pcts else 0.0

    # Newly adopted: first_use_at within trailing 30 days
    # Abandoned: last_use_at >= 45 days ago (relative to snapshot_date)
    newly_adopted = 0
    abandoned = 0
    cutoff_new = (snapshot_date.timestamp() - 30 * 86400)
    cutoff_abandoned = (snapshot_date.timestamp() - 45 * 86400)
    for row in feature_usage:
        first = _parse_iso(row.get("first_use_at"))
        last = _parse_iso(row.get("last_use_at"))
        if first and first.timestamp() >= cutoff_new:
            newly_adopted += 1
        if last and last.timestamp() <= cutoff_abandoned:
            abandoned += 1

    # Cohort comparison if baseline provided
    breadth_vs_cohort = None
    if cohort_baseline and cohort_baseline.get("cohort_typical_feature_breadth"):
        cohort_breadth = cohort_baseline["cohort_typical_feature_breadth"]
        if cohort_breadth > 0:
            breadth_vs_cohort = round(breadth / cohort_breadth, 3)

    return {
        "feature_breadth": breadth,
        "feature_breadth_vs_cohort": breadth_vs_cohort,
        "core_feature_adoption_pct": round(core_pct, 3),
        "advanced_feature_adoption_pct": round(advanced_pct, 3),
        "integration_feature_count": integration_count,
        "feature_concentration_index": round(concentration_index, 3),
        "newly_adopted_features_in_window": newly_adopted,
        "abandoned_features_in_window": abandoned,
        "category_counts": category_counts,
    }


def _classify_baseline(
    metrics: dict,
    days_into_contract: int,
    active_seats: int,
) -> dict:
    """Pre-LLM classification scaffolding. Captures the deterministic
    decision facts that constrain the LLM's primary_pattern label.
    """
    breadth = metrics["feature_breadth"]
    abandoned = metrics["abandoned_features_in_window"]
    new = metrics["newly_adopted_features_in_window"]
    core_pct = metrics["core_feature_adoption_pct"]
    advanced_pct = metrics["advanced_feature_adoption_pct"]
    integration_count = metrics["integration_feature_count"]
    concentration = metrics["feature_concentration_index"]

    # Onboarding-aware gate (spec eval criterion: hard 100%)
    is_onboarding = days_into_contract < 60

    # Multi-team threshold — siloed_by_team requires enough seats to be plausibly multi-team
    multi_team_eligible = active_seats >= 30

    # Decision hints — LLM uses these but we record them for audit.
    # high_concentration takes priority over broad_and_deep — same set of
    # features used by everyone is "deeply integrated"; same set used by one
    # team is "siloed". The mutual-exclusivity gate here keeps the LLM from
    # firing both on the same account.
    high_concentration = concentration >= 0.45
    hints = {
        "is_onboarding": is_onboarding,
        "multi_team_eligible": multi_team_eligible,
        "abandonment_dominant": abandoned > new and abandoned >= 2,
        "high_concentration": high_concentration,
        "broad_and_deep": (
            breadth >= 12 and core_pct >= 0.8 and advanced_pct >= 0.5
            and not high_concentration
        ),
        "narrow_core_only": breadth <= 5 and advanced_pct <= 0.2 and integration_count == 0,
        "rapid_recent_adoption": new >= 3 and abandoned <= 1,
    }
    return hints


# ─────────────────────────────────────────────────────────────────────
# LLM characterization
# ─────────────────────────────────────────────────────────────────────

def _characterize_via_llm(
    metrics: dict,
    hints: dict,
    account_context: dict,
    data_completeness: str,
) -> dict:
    """Send metrics + hints to Haiku for pattern label + key observations."""

    prompt = f"""You are TOOL-008 (Product Adoption Pattern Recognizer). Your job: classify the account's product adoption pattern into ONE of: deeply_integrated, surface_only, siloed_by_team, declining, activating.

DETERMINISTIC METRICS (computed in code — do not invent values):
{json.dumps(metrics, indent=2)}

DETERMINISTIC HINTS (decision scaffolding):
{json.dumps(hints, indent=2)}

ACCOUNT CONTEXT:
{json.dumps(account_context, indent=2)}

DATA COMPLETENESS: {data_completeness}

Classification rules (apply in this priority order):

1. If hints.is_onboarding is true → primary_pattern = "activating" (HARD RULE — onboarding-aware classification, even if breadth is low).

2. Else if hints.abandonment_dominant is true → primary_pattern = "declining".

3. Else if hints.high_concentration is true AND hints.multi_team_eligible is true AND breadth >= 8 → primary_pattern = "siloed_by_team".

4. Else if hints.broad_and_deep is true → primary_pattern = "deeply_integrated".

5. Else if hints.narrow_core_only is true → primary_pattern = "surface_only".

6. Else if hints.rapid_recent_adoption is true → primary_pattern = "activating".

7. Else default to the closest fit ("surface_only" if narrow, "deeply_integrated" if broad).

Output JSON only, schema:
{{
  "primary_pattern": "deeply_integrated | surface_only | siloed_by_team | declining | activating",
  "secondary_pattern": "string or null",
  "pattern_confidence": "high | medium | low",
  "key_observations": [
    {{"observation": "string", "supporting_metric": "string", "interpretation": "string"}}
  ],
  "expansion_signal": "strong | moderate | none",
  "churn_signal": "strong | moderate | none",
  "intervention_recommendation": "string or null",
  "ungrounded_assumptions": ["string"]
}}

Provide 2-4 key_observations. Tie each to a specific metric value. If data_completeness is "medium" or "low", lower pattern_confidence accordingly and note the cohort-baseline gap in ungrounded_assumptions."""

    client = Anthropic()
    model = os.environ.get("TOOL_008_MODEL", "claude-haiku-4-5-20251001")
    response = client.messages.create(
        model=model,
        max_tokens=1500,
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
# Entry point — what AGT-902 calls
# ─────────────────────────────────────────────────────────────────────

def tool_008_handler(input_dict: dict) -> dict:
    """Main entry. Input matches the TOOL-008 spec input schema (with corpus
    augmentation handled by the registry); returns the structured output the
    brain consumes."""
    telemetry = input_dict.get("feature_engagement_telemetry", {})
    feature_usage = telemetry.get("feature_usage", [])
    if not feature_usage:
        return {
            "tool_name": "TOOL-008",
            "status": "insufficient_data",
            "reason": "feature_engagement_telemetry.feature_usage is empty or missing",
        }

    window_days = telemetry.get("trailing_window_days", 90)
    window_end_str = telemetry.get("window_end")
    snapshot_date = _parse_iso(window_end_str) or datetime.now(timezone.utc)

    account_context = input_dict.get("account_context", {})
    cohort_baseline = input_dict.get("comparison_baseline")

    # Days into contract
    contract_start = _parse_iso(account_context.get("contract_start_date"))
    days_into_contract = 999  # unknown → treat as mature
    if contract_start:
        days_into_contract = max(0, (snapshot_date - contract_start).days)

    active_seats = account_context.get("active_seats")
    if active_seats is None:
        active_seats = account_context.get("licensed_seats", 0)

    # Compute metrics
    metrics = _compute_metrics(feature_usage, window_days, snapshot_date, cohort_baseline)
    hints = _classify_baseline(metrics, days_into_contract, active_seats)

    data_completeness = "high"
    if not cohort_baseline or not cohort_baseline.get("cohort_typical_feature_breadth"):
        data_completeness = "medium"
    if not active_seats:
        data_completeness = "low"

    # LLM characterization
    try:
        characterization = _characterize_via_llm(
            metrics, hints, account_context, data_completeness,
        )
    except Exception as e:
        return {
            "tool_name": "TOOL-008",
            "status": "llm_error",
            "reason": str(e),
            "metrics": metrics,
            "hints": hints,
        }

    return {
        "tool_name": "TOOL-008",
        "status": "ok",
        "adoption_pattern": {
            "primary_pattern": characterization.get("primary_pattern"),
            "secondary_pattern": characterization.get("secondary_pattern"),
            "pattern_confidence": characterization.get("pattern_confidence"),
        },
        "adoption_metrics": {
            "feature_breadth": metrics["feature_breadth"],
            "feature_breadth_vs_cohort": metrics["feature_breadth_vs_cohort"],
            "core_feature_adoption_pct": metrics["core_feature_adoption_pct"],
            "advanced_feature_adoption_pct": metrics["advanced_feature_adoption_pct"],
            "integration_feature_count": metrics["integration_feature_count"],
            "feature_concentration_index": metrics["feature_concentration_index"],
            "newly_adopted_features_in_window": metrics["newly_adopted_features_in_window"],
            "abandoned_features_in_window": metrics["abandoned_features_in_window"],
        },
        "key_observations": characterization.get("key_observations", []),
        "implications_for_caller": {
            "expansion_signal": characterization.get("expansion_signal"),
            "churn_signal": characterization.get("churn_signal"),
            "intervention_recommendation": characterization.get("intervention_recommendation"),
        },
        "ungrounded_assumptions": characterization.get("ungrounded_assumptions", []),
        "data_completeness": data_completeness,
        "decision_hints_used": hints,
        "_llm_metadata": characterization.get("_llm_metadata"),
    }


# ─────────────────────────────────────────────────────────────────────
# Anthropic tool definition — what AGT-902 sees
# ─────────────────────────────────────────────────────────────────────

TOOL_008_DEFINITION = {
    "name": "tool_008_product_adoption_pattern",
    "description": (
        "TOOL-008 Product Adoption Pattern Recognizer. Reads the account's "
        "feature_engagement telemetry (which product features are used, by "
        "how many users, when first/last used) and classifies the adoption "
        "pattern as deeply_integrated / surface_only / siloed_by_team / "
        "declining / activating. Different shape than TOOL-004 — TOOL-008 is "
        "about WHICH features, not HOW MUCH consumption. Use this when "
        "answering 'is the account actually getting value?', 'is this "
        "renewal at risk despite green health?', or 'what's the cross-team "
        "expansion signal?'. Onboarding-aware: accounts <60 days into "
        "contract are correctly classified as 'activating' rather than "
        "'surface_only'."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "account_id": {
                "type": "string",
                "description": "Account UUID — used for logging only.",
            },
        },
        "required": ["account_id"],
    },
}
