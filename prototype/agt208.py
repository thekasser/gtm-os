"""AGT-208 Developer Signal Scorer — runtime prototype.

Per the AGT-208 spec (v38):
  - Pre-MQL PLG-funnel scoring on developer-led consumption-pricing platforms
  - 5-dimension scoring per developer (consumption velocity 30 / production
    signal 25 / enterprise context 20 / commercial intent 15 / stakeholder
    breadth 10) — additive, capped per dimension
  - Tier mapping: handoff-priority (80–100) / handoff-warm (60–79) /
    monitor (40–59) / stay-self-serve (<40)
  - Domain aggregation: 3+ devs at same domain each ≥ 60 → forces priority
    override even when summed scores cap
  - Optional LLM (Haiku) for AE brief assembly on handoff-priority devs
  - Outputs per-developer + account-aggregated rows to DeveloperSignalLog

Reads from synth corpus (or any source providing developer_event_stream +
developer_roster). Writes to prototype/developer_signal_log.jsonl.
"""

from __future__ import annotations

import json
import os
import uuid
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path
from anthropic import Anthropic


# ─────────────────────────────────────────────────────────────────────
# Event-type → dimension mapping (mirrors synth/developer_signals.py)
# ─────────────────────────────────────────────────────────────────────

EVENT_TYPE_WEIGHTS = {
    # consumption_velocity — weighted by call_count_in_event metadata
    "api_call":                    {"dim": "consumption_velocity", "weight_per": 0.001},
    # production_signal
    "deployment_create_dedicated": {"dim": "production_signal",    "weight_per": 6.0},
    "deployment_create_byoc":      {"dim": "production_signal",    "weight_per": 12.0},
    "p95_latency_query":           {"dim": "production_signal",    "weight_per": 1.5},
    "idempotency_key_usage":       {"dim": "production_signal",    "weight_per": 0.5},
    "error_rate_query":            {"dim": "production_signal",    "weight_per": 1.5},
    # commercial_intent
    "pricing_page_visit":          {"dim": "commercial_intent",    "weight_per": 2.5},
    "billing_dashboard_visit":     {"dim": "commercial_intent",    "weight_per": 2.0},
    "security_compliance_request": {"dim": "commercial_intent",    "weight_per": 5.0},
    "soc2_doc_view":               {"dim": "commercial_intent",    "weight_per": 4.5},
    "hipaa_doc_view":              {"dim": "commercial_intent",    "weight_per": 4.5},
    "procurement_inquiry":         {"dim": "commercial_intent",    "weight_per": 7.0},
    # neutral product engagement (counts toward stakeholder_breadth via distinct devs)
    "doc_view":                    {"dim": None,                    "weight_per": 0.0},
    "model_selection":             {"dim": None,                    "weight_per": 0.0},
}

# Per-dimension caps (from spec)
DIM_CAPS = {
    "consumption_velocity": 30,
    "production_signal":    25,
    "commercial_intent":    15,
}

# Tier thresholds (from spec)
TIER_THRESHOLDS = [
    (80, "handoff-priority"),
    (60, "handoff-warm"),
    (40, "monitor"),
    ( 0, "stay-self-serve"),
]


def _tier_for_score(score: float) -> str:
    for floor, tier in TIER_THRESHOLDS:
        if score >= floor:
            return tier
    return "stay-self-serve"


# ─────────────────────────────────────────────────────────────────────
# Per-developer scoring (deterministic)
# ─────────────────────────────────────────────────────────────────────

def _parse_iso(s: str) -> datetime:
    return datetime.fromisoformat(s.replace("Z", "+00:00"))


def score_developer(
    developer: dict,
    events_for_dev: list[dict],
    snapshot_date: datetime,
    account_level_dims: dict,
) -> dict:
    """Compute 5-dimension score for one developer at snapshot_date.

    Trailing 30-day window for consumption_velocity / production_signal /
    commercial_intent. Account-level dimensions (enterprise_context,
    stakeholder_breadth) are passed in so all developers in same account
    share them.
    """
    trailing_30_cutoff = snapshot_date - timedelta(days=30)

    velocity_pts = 0.0
    production_pts = 0.0
    intent_pts = 0.0
    top_signals: list[dict] = []

    for e in events_for_dev:
        ts = _parse_iso(e["timestamp"])
        if ts < trailing_30_cutoff:
            continue
        et = e["event_type"]
        meta = EVENT_TYPE_WEIGHTS.get(et)
        if not meta or meta["dim"] is None:
            continue
        weight = meta["weight_per"]
        if meta["dim"] == "consumption_velocity":
            count = e.get("metadata", {}).get("call_count_in_event", 1)
            contribution = count * weight
            velocity_pts += contribution
        elif meta["dim"] == "production_signal":
            production_pts += weight
            contribution = weight
        elif meta["dim"] == "commercial_intent":
            intent_pts += weight
            contribution = weight
        else:
            contribution = 0
        top_signals.append({
            "event_id": e.get("event_id"),
            "event_type": et,
            "timestamp": e["timestamp"],
            "dimension": meta["dim"],
            "contribution_pts": round(contribution, 3),
        })

    # Cap each dimension per spec
    velocity_capped = min(DIM_CAPS["consumption_velocity"], round(velocity_pts, 2))
    production_capped = min(DIM_CAPS["production_signal"], round(production_pts, 2))
    intent_capped = min(DIM_CAPS["commercial_intent"], round(intent_pts, 2))

    # Account-level dimensions shared across all devs in same account
    enterprise_context_pts = account_level_dims.get("enterprise_context_pts", 0)
    stakeholder_breadth_pts = account_level_dims.get("stakeholder_breadth_pts", 0)

    composite = (
        velocity_capped
        + production_capped
        + enterprise_context_pts
        + intent_capped
        + stakeholder_breadth_pts
    )
    composite = min(100.0, round(composite, 2))

    # Pick top 3 signals by contribution_pts (for AE brief assembly)
    top_signals.sort(key=lambda s: s["contribution_pts"], reverse=True)
    top_3 = top_signals[:3]

    return {
        "developer_id": developer["developer_id"],
        "developer_name": developer.get("name"),
        "email": developer.get("email"),
        "email_domain": developer["email_domain"],
        "role_class": developer["role_class"],
        "consumption_velocity_pts": velocity_capped,
        "production_signal_pts": production_capped,
        "enterprise_context_pts": enterprise_context_pts,
        "commercial_intent_pts": intent_capped,
        "stakeholder_breadth_pts": stakeholder_breadth_pts,
        "composite_score": composite,
        "tier": _tier_for_score(composite),
        "top_3_signals": top_3,
    }


# ─────────────────────────────────────────────────────────────────────
# Account-level aggregation + domain override
# ─────────────────────────────────────────────────────────────────────

def aggregate_account_signal(
    developer_scores: list[dict],
    corp_domain: str,
) -> dict:
    """Domain-aggregate per spec: 3+ corp-domain devs each ≥ 60 → priority override."""
    corp_devs = [d for d in developer_scores if d["email_domain"] == corp_domain]
    devs_60_plus = [d for d in corp_devs if d["composite_score"] >= 60]
    domain_override_triggered = len(devs_60_plus) >= 3

    # Sum of corp-dev scores capped at 100 per spec
    summed_score = min(100, sum(d["composite_score"] for d in corp_devs))

    # Highest individual + retained as separate field
    if developer_scores:
        max_dev = max(developer_scores, key=lambda d: d["composite_score"])
        highest_individual_score = max_dev["composite_score"]
    else:
        highest_individual_score = 0

    # Account-level tier — domain override beats summed-score tier
    account_tier_via_sum = _tier_for_score(summed_score)
    if domain_override_triggered and account_tier_via_sum != "handoff-priority":
        account_tier = "handoff-priority"
        override_reason = "domain_aggregation_3+_devs_60+"
    else:
        account_tier = account_tier_via_sum
        override_reason = None

    return {
        "domain_aggregated_score": summed_score,
        "highest_individual_score": highest_individual_score,
        "account_tier": account_tier,
        "domain_override_triggered": domain_override_triggered,
        "domain_override_reason": override_reason,
        "n_corp_devs": len(corp_devs),
        "n_corp_devs_60_plus": len(devs_60_plus),
    }


# ─────────────────────────────────────────────────────────────────────
# Optional Haiku — AE brief on handoff-priority developers
# ─────────────────────────────────────────────────────────────────────

def _assemble_ae_brief(
    developer_score: dict,
    account_context: dict,
) -> dict:
    """Generate a short AE first-touch brief for handoff-priority developers.
    Haiku, deterministic shape: 2-paragraph context + 1 recommended angle."""

    prompt = f"""You are AGT-208 Developer Signal Scorer assembling an AE first-touch brief.
The developer has been routed handoff-priority based on the score below. Assemble a SHORT
brief (max 3 short paragraphs total) the AE can read in 30 seconds before reaching out.

DEVELOPER SCORE:
{json.dumps(developer_score, indent=2)}

ACCOUNT CONTEXT:
{json.dumps(account_context, indent=2)}

Output JSON only, schema:
{{
  "summary_one_liner": "string — 1 sentence: who this is and why now",
  "evidence": "string — 1-2 sentences citing the specific signals (cite top_3_signals)",
  "recommended_angle": "string — 1 sentence: what the AE should lead with"
}}

Discipline:
- Cite specific signals from top_3_signals — do not generalize.
- Don't promise anything to the AE the data doesn't support.
- If consumption_velocity is the top signal, lead with usage growth.
- If commercial_intent (pricing/billing/SOC2) is the top signal, lead with buying-process readiness.
- If production_signal is the top signal, lead with technical depth + production-readiness."""

    client = Anthropic()
    model = os.environ.get("AGT_208_MODEL", "claude-haiku-4-5-20251001")
    response = client.messages.create(
        model=model,
        max_tokens=400,
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
# AGT-201 contradiction flag
# ─────────────────────────────────────────────────────────────────────

def _check_contradicts_agt201(
    developer_score: dict,
    account_icp_tier: str | None,
) -> bool:
    """Per spec: contradicts_agt201 = TRUE when AGT-201 has rated the account
    T3 (poor fit) but AGT-208 score ≥ 60. Surfaces firmographic-vs-behavioral
    disagreement for RevOps review."""
    return account_icp_tier == "T3" and developer_score["composite_score"] >= 60


# ─────────────────────────────────────────────────────────────────────
# Per-account scoring run
# ─────────────────────────────────────────────────────────────────────

def score_account(
    corpus_data: dict,
    enable_ae_brief: bool = True,
    ae_brief_max_devs: int = 3,
) -> dict:
    """Score all developers on one account. Returns rows ready for
    DeveloperSignalLog write."""
    account = corpus_data.get("account", {})
    account_id = account.get("account_id")
    company_name = account.get("company_name")
    icp_tier = account.get("icp_tier")
    archetype_key = corpus_data.get("archetype_key")

    roster = corpus_data.get("developer_roster", []) or []
    events = corpus_data.get("developer_event_stream", []) or []

    if not roster:
        return {
            "account_id": account_id,
            "status": "no_developer_roster",
            "scored_at": datetime.now(timezone.utc).isoformat(),
            "developer_count": 0,
        }

    # Snapshot date = contract_start + contract_age_days. Force UTC so
    # comparisons against tz-aware event timestamps work.
    contract_start = datetime.fromisoformat(account["contract_start_date"]).replace(tzinfo=timezone.utc)
    contract_age_days = account.get("contract_age_days_at_corpus_gen", 0)
    snapshot_date = contract_start + timedelta(days=contract_age_days)

    # Account-level dimensions (read from pre-computed if present, else recompute)
    pre_computed = corpus_data.get("developer_signal_dimensions_pre_computed") or {}
    account_level = pre_computed.get("account_level") or {}
    if not account_level:
        # Fallback: recompute account-level dims from events
        trailing_30 = snapshot_date - timedelta(days=30)
        distinct_devs_30d = len({
            e["developer_id"] for e in events
            if _parse_iso(e["timestamp"]) >= trailing_30
        })
        corp_domain_guess = roster[0]["email_domain"] if roster else None
        corp_devs = sum(1 for d in roster if d["email_domain"] == corp_domain_guess)
        account_level = {
            "stakeholder_breadth_pts": min(10, distinct_devs_30d),
            "enterprise_context_pts": min(20, int((corp_devs / max(1, len(roster))) * 12) + (6 if corp_devs >= 3 else 0) + 2),
            "distinct_devs_trailing_30d": distinct_devs_30d,
            "n_devs_total": len(roster),
        }

    # Index events by developer_id for efficient per-dev scoring
    events_by_dev: dict[str, list[dict]] = defaultdict(list)
    for e in events:
        events_by_dev[e["developer_id"]].append(e)

    # Score each developer
    developer_scores = []
    for dev in roster:
        score_row = score_developer(
            dev, events_by_dev.get(dev["developer_id"], []),
            snapshot_date, account_level,
        )
        score_row["contradicts_agt201"] = _check_contradicts_agt201(score_row, icp_tier)
        developer_scores.append(score_row)

    # Domain aggregation (corp domain = most-represented domain in roster)
    domain_counts = defaultdict(int)
    for d in roster:
        domain_counts[d["email_domain"]] += 1
    corp_domain = max(domain_counts, key=domain_counts.get) if domain_counts else None
    account_aggregate = aggregate_account_signal(developer_scores, corp_domain)

    # Optional AE brief assembly — for top N handoff-priority devs only
    ae_briefs: dict[str, dict] = {}
    total_brief_cost_tokens = {"input": 0, "output": 0}
    if enable_ae_brief:
        priority_devs = [d for d in developer_scores if d["tier"] == "handoff-priority"]
        priority_devs.sort(key=lambda d: d["composite_score"], reverse=True)
        for dev in priority_devs[:ae_brief_max_devs]:
            try:
                brief = _assemble_ae_brief(dev, {
                    "company_name": company_name,
                    "icp_tier": icp_tier,
                    "archetype": archetype_key,
                    "segment": account.get("segment"),
                    "vertical": account.get("vertical"),
                })
                ae_briefs[dev["developer_id"]] = brief
                md = brief.get("_llm_metadata") or {}
                total_brief_cost_tokens["input"] += md.get("input_tokens", 0)
                total_brief_cost_tokens["output"] += md.get("output_tokens", 0)
            except Exception as e:
                ae_briefs[dev["developer_id"]] = {"error": str(e)}

    # Tier distribution summary
    tier_counts: dict[str, int] = defaultdict(int)
    for d in developer_scores:
        tier_counts[d["tier"]] += 1

    return {
        "scored_at": datetime.now(timezone.utc).isoformat(),
        "account_id": account_id,
        "company_name": company_name,
        "archetype": archetype_key,
        "icp_tier_from_agt201": icp_tier,
        "snapshot_date": snapshot_date.isoformat(),
        "corp_domain": corp_domain,
        "developer_scores": developer_scores,
        "account_aggregate": account_aggregate,
        "tier_distribution": dict(tier_counts),
        "ae_briefs": ae_briefs,
        "n_contradicts_agt201": sum(1 for d in developer_scores if d["contradicts_agt201"]),
        "_llm_brief_cost_tokens": total_brief_cost_tokens,
    }


# ─────────────────────────────────────────────────────────────────────
# DeveloperSignalLog writer
# ─────────────────────────────────────────────────────────────────────

DEFAULT_LOG_PATH = Path(__file__).parent / "developer_signal_log.jsonl"


def write_to_log(account_result: dict, log_path: Path = DEFAULT_LOG_PATH) -> None:
    """Append per-developer DeveloperSignalLog rows to the jsonl log.

    Per AGT-208 spec: one row per developer per scoring run.
    """
    if account_result.get("status") == "no_developer_roster":
        return

    log_path.parent.mkdir(parents=True, exist_ok=True)
    with log_path.open("a") as f:
        for dev_score in account_result.get("developer_scores", []):
            row = {
                "signal_id": str(uuid.uuid4()),
                "developer_id": dev_score["developer_id"],
                "email_domain": dev_score["email_domain"],
                "account_id": account_result["account_id"],
                "scored_at": account_result["scored_at"],
                "consumption_velocity_pts": dev_score["consumption_velocity_pts"],
                "production_signal_pts": dev_score["production_signal_pts"],
                "enterprise_context_pts": dev_score["enterprise_context_pts"],
                "commercial_intent_pts": dev_score["commercial_intent_pts"],
                "stakeholder_breadth_pts": dev_score["stakeholder_breadth_pts"],
                "composite_score": dev_score["composite_score"],
                "tier": dev_score["tier"],
                "domain_aggregated_score": account_result["account_aggregate"]["domain_aggregated_score"],
                "contradicts_agt201": dev_score["contradicts_agt201"],
                "top_signals": dev_score["top_3_signals"],
                "ae_brief": account_result["ae_briefs"].get(dev_score["developer_id"]),
            }
            f.write(json.dumps(row) + "\n")
