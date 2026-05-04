"""Aggregate view extractor for AGT-901 Pipeline Brain.

AGT-902 reads a per-account composite view; AGT-901 reads cross-account
rollups. Same seam (a brain-ready view dict), different shape.

The view answers cohort-level questions like "where's the softness?" or
"which segments are underweighted?". For drill-down on specific accounts
in the cohort the brain calls TOOL-004 / TOOL-008 with account_id.

The prototype computes aggregates from the synth corpus on demand. In
production this view is a query against MetricsCalc, AGT-701/702/703,
AGT-401/402, plus per-account snapshots from CustomerHealthLog.
"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from statistics import mean, median


# ─────────────────────────────────────────────────────────────────────
# Health-tier classification (mirrors AGT-501)
# ─────────────────────────────────────────────────────────────────────

def _tier_for_score(score: float | int | None) -> str:
    if score is None:
        return "Unknown"
    if score >= 80:
        return "Green"
    if score >= 60:
        return "Yellow"
    if score >= 40:
        return "Amber"
    return "Red"


# ─────────────────────────────────────────────────────────────────────
# Per-account derived signals — used to roll up
# ─────────────────────────────────────────────────────────────────────

def _account_signals(corpus: dict) -> dict:
    """Compute account-level derived signals the brain can roll up."""
    account = corpus.get("account", {})
    summary = corpus.get("summary", {})
    archetype = corpus.get("archetype_key", "?")

    # Health
    health = corpus.get("customer_health_log", [])
    final_health = summary.get("final_health_score")
    final_tier = summary.get("final_health_tier") or _tier_for_score(final_health)
    health_30d_ago = None
    if len(health) >= 30:
        health_30d_ago = health[-30].get("score")
    health_trajectory = None
    if final_health is not None and health_30d_ago is not None:
        delta = final_health - health_30d_ago
        if delta > 3:
            health_trajectory = "improving"
        elif delta < -3:
            health_trajectory = "declining"
        else:
            health_trajectory = "stable"

    # Usage
    usage = corpus.get("usage_metering_log", [])
    overage_30d = 0
    for row in usage[-30:]:
        if row.get("overage_units", 0) > 0:
            overage_30d += 1

    # Conversations
    conv_log = corpus.get("conversation_intelligence_log", [])
    last_call_days_ago = None
    if conv_log:
        try:
            last_call = max(
                datetime.fromisoformat(c["call_date"].replace("Z", "+00:00"))
                for c in conv_log if c.get("call_date")
            )
            snapshot = (datetime.fromisoformat(account["contract_start_date"])
                if "contract_start_date" in account else None)
            if snapshot:
                from datetime import timedelta, timezone
                snap_now = (snapshot.replace(tzinfo=timezone.utc)
                             + timedelta(days=account.get("contract_age_days_at_corpus_gen", 0)))
                last_call_days_ago = (snap_now - last_call).days
        except Exception:
            pass

    # Payment status
    final_payment_state = summary.get("final_payment_state", "current")

    # Feature engagement
    fe_pattern = corpus.get("feature_engagement_ground_truth_pattern")

    # At-risk / expansion-ready signals — heuristic flags
    at_risk = (final_tier in ("Amber", "Red")
               or final_payment_state in ("overdue", "failed", "suspended")
               or health_trajectory == "declining")

    # Expansion-ready: green/yellow health AND consistent overage
    expansion_ready = (final_tier in ("Green", "Yellow")
                       and overage_30d >= 5
                       and final_payment_state == "current")

    # Stalled-onboarding: <120 days into contract AND health <60 AND low usage
    contract_age = account.get("contract_age_days_at_corpus_gen", 999)
    is_onboarding = contract_age < 120
    stalled_onboarding = (is_onboarding
                          and final_health is not None and final_health < 60)

    return {
        "account_id": account.get("account_id"),
        "company_name": account.get("company_name"),
        "segment": account.get("segment"),
        "vertical": account.get("vertical"),
        "icp_tier": account.get("icp_tier"),
        "arr_usd": account.get("arr_usd"),
        "term_months": account.get("term_months"),
        "licensed_seats": account.get("licensed_seats"),
        "contract_age_days": contract_age,
        "archetype": archetype,
        "final_health_score": final_health,
        "final_health_tier": final_tier,
        "health_trajectory_30d": health_trajectory,
        "overage_days_in_30d": overage_30d,
        "final_payment_state": final_payment_state,
        "last_call_days_ago": last_call_days_ago,
        "feature_pattern": fe_pattern,
        "at_risk": at_risk,
        "expansion_ready": expansion_ready,
        "stalled_onboarding": stalled_onboarding,
    }


# ─────────────────────────────────────────────────────────────────────
# Rollup helpers
# ─────────────────────────────────────────────────────────────────────

def _rollup_by(signals: list[dict], key: str) -> list[dict]:
    """Group account signals by `key` (e.g., 'segment') and aggregate."""
    groups: dict[str, list[dict]] = {}
    for s in signals:
        k = s.get(key) or "Unknown"
        groups.setdefault(k, []).append(s)

    rollup: list[dict] = []
    for k, accts in sorted(groups.items()):
        health_scores = [a["final_health_score"] for a in accts
                         if a["final_health_score"] is not None]
        rollup.append({
            key: k,
            "account_count": len(accts),
            "total_arr_usd": round(sum(a["arr_usd"] or 0 for a in accts), 2),
            "avg_health_score": round(mean(health_scores), 2) if health_scores else None,
            "median_health_score": round(median(health_scores), 2) if health_scores else None,
            "tier_distribution": {
                tier: sum(1 for a in accts if a["final_health_tier"] == tier)
                for tier in ("Green", "Yellow", "Amber", "Red")
            },
            "at_risk_count": sum(1 for a in accts if a["at_risk"]),
            "at_risk_pct": round(
                sum(1 for a in accts if a["at_risk"]) / len(accts), 3),
            "expansion_ready_count": sum(1 for a in accts if a["expansion_ready"]),
            "stalled_onboarding_count": sum(1 for a in accts if a["stalled_onboarding"]),
            "median_contract_age_days": int(median(a["contract_age_days"] for a in accts)),
            "archetype_breakdown": {
                arch: sum(1 for a in accts if a["archetype"] == arch)
                for arch in {a["archetype"] for a in accts}
            },
        })
    return rollup


def _top_k(signals: list[dict], filter_fn, sort_key, k: int = 5,
           reverse: bool = True) -> list[dict]:
    """Filter then top-K. Returns lightweight per-account anchor records
    (not full per-account composites)."""
    filtered = [s for s in signals if filter_fn(s)]
    sorted_list = sorted(filtered, key=sort_key, reverse=reverse)
    out = []
    for s in sorted_list[:k]:
        out.append({
            "account_id": s["account_id"],
            "company_name": s["company_name"],
            "segment": s["segment"],
            "vertical": s["vertical"],
            "icp_tier": s["icp_tier"],
            "arr_usd": s["arr_usd"],
            "archetype": s["archetype"],
            "final_health_score": s["final_health_score"],
            "feature_pattern": s["feature_pattern"],
            "overage_days_in_30d": s["overage_days_in_30d"],
            "stalled_onboarding": s["stalled_onboarding"],
        })
    return out


# ─────────────────────────────────────────────────────────────────────
# Public entry point
# ─────────────────────────────────────────────────────────────────────

def extract_pipeline_view(corpus_dir: Path | str, source=None) -> dict:
    """Build the AGT-901 brain-ready view.

    Args:
      corpus_dir:  Path to a synth corpus directory (legacy entry point).
                   Ignored when `source` is provided.
      source:      Optional BrainViewSource. When supplied, account corpora
                   are pulled through the source's load_account_corpus instead
                   of via direct file IO. This is the seam for swapping
                   synth → real warehouse.

    Returns a single dict with cross-account rollups + drill-down anchors.
    """
    if source is not None:
        meta = source.metadata()
        snapshot_date = meta.get("snapshot_date", "unknown")
        signals: list[dict] = []
        for aid in source.iterate_account_ids():
            corpus = source.load_account_corpus(aid)
            signals.append(_account_signals(corpus))
    else:
        corpus_dir = Path(corpus_dir)
        ground_truth_path = corpus_dir / "ground_truth.json"
        if not ground_truth_path.exists():
            raise FileNotFoundError(f"missing ground_truth.json in {corpus_dir}")

        with ground_truth_path.open() as f:
            gt = json.load(f)

        signals = []
        for entry in gt.get("accounts", []):
            aid = entry["account_id"]
            path = corpus_dir / f"{aid}.json"
            if not path.exists():
                continue
            with path.open() as f:
                corpus = json.load(f)
            signals.append(_account_signals(corpus))

        # Snapshot date — derived from corpus generation time
        snapshot_date = gt.get("generated_at", "").split("T")[0] or "unknown"

    # Rollups
    segment_rollup = _rollup_by(signals, "segment")
    vertical_rollup = _rollup_by(signals, "vertical")
    icp_tier_rollup = _rollup_by(signals, "icp_tier")

    archetype_dist: dict[str, int] = {}
    for s in signals:
        archetype_dist[s["archetype"]] = archetype_dist.get(s["archetype"], 0) + 1

    # Top-K drill-down anchors — keep small to keep view in budget
    top_expansion = _top_k(
        signals,
        filter_fn=lambda s: s["expansion_ready"],
        sort_key=lambda s: (s["overage_days_in_30d"], s["arr_usd"] or 0),
    )
    top_churn = _top_k(
        signals,
        filter_fn=lambda s: s["at_risk"],
        sort_key=lambda s: (
            -((s["final_health_score"] or 100)),  # lower score = higher risk
            -(s["arr_usd"] or 0),
        ),
        reverse=False,
    )
    stalled = [
        {
            "account_id": s["account_id"],
            "company_name": s["company_name"],
            "segment": s["segment"],
            "vertical": s["vertical"],
            "contract_age_days": s["contract_age_days"],
            "final_health_score": s["final_health_score"],
        }
        for s in signals if s["stalled_onboarding"]
    ]

    # Headline metrics
    total_arr = round(sum(s["arr_usd"] or 0 for s in signals), 2)
    at_risk_arr = round(
        sum(s["arr_usd"] or 0 for s in signals if s["at_risk"]), 2)
    expansion_ready_arr = round(
        sum(s["arr_usd"] or 0 for s in signals if s["expansion_ready"]), 2)

    return {
        "view_type": "pipeline_aggregate",
        "snapshot_date": snapshot_date,
        "corpus_size": len(signals),
        "headline_metrics": {
            "total_arr_usd": total_arr,
            "at_risk_arr_usd": at_risk_arr,
            "at_risk_arr_pct_of_total": round(at_risk_arr / total_arr, 3) if total_arr else 0,
            "expansion_ready_arr_usd": expansion_ready_arr,
            "expansion_ready_arr_pct_of_total": round(expansion_ready_arr / total_arr, 3) if total_arr else 0,
            "at_risk_account_count": sum(1 for s in signals if s["at_risk"]),
            "expansion_ready_account_count": sum(1 for s in signals if s["expansion_ready"]),
            "stalled_onboarding_count": len(stalled),
        },
        "segment_rollup": segment_rollup,
        "vertical_rollup": vertical_rollup,
        "icp_tier_rollup": icp_tier_rollup,
        "archetype_distribution": archetype_dist,
        "top_expansion_candidates": top_expansion,
        "top_churn_risks": top_churn,
        "stalled_onboardings": stalled,
        "view_caveats": [
            "rollups are over a 50-account synthetic corpus, not a production warehouse",
            "at_risk and expansion_ready are derived heuristics — not Tier 1 service outputs",
        ],
    }


if __name__ == "__main__":
    # CLI: pretty-print the view for inspection
    import argparse, sys
    parser = argparse.ArgumentParser()
    parser.add_argument("--corpus", default="../synth/corpus")
    parser.add_argument("--summary", action="store_true",
                        help="print headline summary only")
    args = parser.parse_args()
    view = extract_pipeline_view(args.corpus)
    if args.summary:
        print(json.dumps({
            "view_type": view["view_type"],
            "snapshot_date": view["snapshot_date"],
            "corpus_size": view["corpus_size"],
            "headline_metrics": view["headline_metrics"],
            "segment_summary": [
                {k: r[k] for k in ("segment", "account_count", "at_risk_count",
                                   "expansion_ready_count", "avg_health_score")}
                for r in view["segment_rollup"]
            ],
        }, indent=2, default=str))
    else:
        json.dump(view, sys.stdout, indent=2, default=str)
