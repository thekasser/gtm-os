"""AGT-902 Account Brain — runtime stub.

Implements the architectural commitments from the AGT-902 spec:
  - Reads per-account brain-ready view (composite from corpus file)
  - Calls Anthropic API with structured prompt
  - Output is BrainAnalysisLog row (never writes canonical Tier 1 data)
  - Source-trace metadata enforced
  - Action taxonomy enforced (validation.py)
  - Staleness recognition surfaced

For the solo prototype, this reads from synth/corpus/ files. In a corporate
environment, replace the file read with a database query against the
materialized per-account composite view per Brain_Ready_Views_Contract.
"""

from __future__ import annotations

import hashlib
import json
import os
import time
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

from anthropic import Anthropic


MODEL = os.environ.get("ANTHROPIC_MODEL", "claude-sonnet-4-6")
WRITER_AGENT_ID = "AGT-902"

DEFAULT_QUESTION = (
    "What's the move on this account? "
    "What's actually going on, and what are the next-best-actions?"
)


# ─────────────────────────────────────────────────────────────────────
# Brain-ready view extraction
# ─────────────────────────────────────────────────────────────────────

def _bucket_usage_by_month(usage_rows: list[dict]) -> list[dict]:
    """Aggregate daily usage into monthly buckets for the brain."""
    buckets: dict[str, dict] = {}
    for row in usage_rows:
        month_key = row["period_start"][:7]   # YYYY-MM
        b = buckets.setdefault(month_key, {
            "month": month_key,
            "units_consumed": 0.0,
            "overage_units": 0.0,
            "overage_amount_usd": 0.0,
            "days_in_bucket": 0,
            "days_with_overage": 0,
        })
        b["units_consumed"] += row["units_consumed"]
        b["overage_units"] += row["overage_units"]
        b["overage_amount_usd"] += row["overage_amount_usd"] or 0.0
        b["days_in_bucket"] += 1
        if row["overage_units"] > 0:
            b["days_with_overage"] += 1
    out = sorted(buckets.values(), key=lambda b: b["month"])
    for b in out:
        for k in ("units_consumed", "overage_units", "overage_amount_usd"):
            b[k] = round(b[k], 2)
    return out


def _summarize_usage(usage_rows: list[dict]) -> dict:
    """Compress daily usage into trailing-window summaries + monthly aggregates."""
    if not usage_rows:
        return {"trailing_30d": None, "trailing_90d": None, "monthly": []}
    monthly = _bucket_usage_by_month(usage_rows)
    last_30 = usage_rows[-30:] if len(usage_rows) >= 30 else usage_rows
    last_90 = usage_rows[-90:] if len(usage_rows) >= 90 else usage_rows

    def window_summary(rows):
        units = [r["units_consumed"] for r in rows]
        overages = [r["overage_units"] for r in rows]
        return {
            "n_days": len(rows),
            "total_units_consumed": round(sum(units), 2),
            "mean_daily_units": round(sum(units) / max(1, len(rows)), 2),
            "total_overage_units": round(sum(overages), 2),
            "days_with_overage": sum(1 for o in overages if o > 0),
        }

    return {
        "trailing_30d": window_summary(last_30),
        "trailing_90d": window_summary(last_90),
        "monthly_aggregates": monthly,
    }


def _summarize_health(health_rows: list[dict]) -> dict:
    """Extract current + lookback snapshots + trajectory."""
    if not health_rows:
        return {"current": None, "snapshots": [], "trajectory": None}

    # health rows are daily in chronological order; index from end
    def snapshot_at(days_ago: int) -> dict | None:
        idx = len(health_rows) - 1 - days_ago
        if idx < 0:
            return None
        r = health_rows[idx]
        return {"date": r["observation_date"], "score": r["score"], "tier": r["tier"]}

    current = snapshot_at(0)
    snapshots = {
        "current":         snapshot_at(0),
        "30_days_ago":     snapshot_at(30),
        "60_days_ago":     snapshot_at(60),
        "90_days_ago":     snapshot_at(90),
        "180_days_ago":    snapshot_at(180),
    }
    snapshots = {k: v for k, v in snapshots.items() if v is not None}

    # Trajectory: sign of (current - 30d)
    if current and snapshots.get("30_days_ago"):
        delta = current["score"] - snapshots["30_days_ago"]["score"]
        if delta > 3:
            trajectory_30d = "improving"
        elif delta < -3:
            trajectory_30d = "declining"
        else:
            trajectory_30d = "stable"
    else:
        trajectory_30d = "unknown"

    payment_modifier = current["tier"] if current else None
    return {
        "current": current,
        "snapshots": snapshots,
        "trajectory_30d": trajectory_30d,
        "payment_modifier_state": health_rows[-1]["payment_health_status"] if health_rows else None,
    }


def _summarize_payments(payment_rows: list[dict]) -> dict:
    """Show recent state + count of state changes."""
    if not payment_rows:
        return {"current_state": "unknown", "recent_events": [], "transitions": 0}
    transitions = sum(
        1 for r in payment_rows if r.get("prior_state") and r["prior_state"] != r["new_state"]
    )
    recent = payment_rows[-10:]
    return {
        "current_state": payment_rows[-1]["new_state"],
        "recent_events": [
            {
                "event_type": r["event_type"],
                "new_state": r["new_state"],
                "prior_state": r.get("prior_state"),
                "event_at": r["event_at"],
                "reason": r["transition_reason"],
            }
            for r in recent
        ],
        "transitions_count": transitions,
    }


def _summarize_conversations(conv_rows: list[dict]) -> list[dict]:
    """Pass through conversations; already capped at 12 by synth/conversations.py."""
    return [
        {
            "call_date": c["call_date"][:10],
            "owner_role": c["call_owner_role"],
            "duration_minutes": c["duration_minutes"],
            "overall_sentiment": c["overall_sentiment"],
            "sentiment_trajectory": c.get("sentiment_trajectory"),
            "sentiment_drivers": c.get("sentiment_drivers", []),
            "transcript_summary": c["transcript_summary"],
            "next_step_committed": c["next_step_committed"],
            "missing_next_step_flag": c["missing_next_step_flag"],
            "objections_raised": c.get("objections_raised", []),
            "competitors_mentioned": c.get("competitors_mentioned", []),
            "unaddressed_showstopper": c["unaddressed_showstopper"],
            "conv_intelligence_score": c["conv_intelligence_score"],
        }
        for c in conv_rows
    ]


def _derive_expansion_signals(usage_rows: list[dict]) -> dict:
    """Derive what would come from ExpansionLog if it existed in the corpus."""
    if not usage_rows:
        return {"trailing_30d_overage_event_count": 0, "consistent_overage": False}
    last_30 = usage_rows[-30:] if len(usage_rows) >= 30 else usage_rows
    overage_count = sum(1 for r in last_30 if r["overage_units"] > 0)
    return {
        "trailing_30d_overage_event_count": overage_count,
        "consistent_overage": overage_count >= 15,   # >= half the days
        "trailing_30d_overage_units": round(sum(r["overage_units"] for r in last_30), 2),
    }


def _derive_churn_proximity(account: dict) -> dict:
    """Derive renewal proximity from contract end date."""
    end_date = datetime.fromisoformat(account["contract_end_date"])
    now = datetime.utcnow()
    days_to_renewal = (end_date - now).days
    return {
        "contract_end_date": account["contract_end_date"],
        "days_to_renewal": days_to_renewal,
        "renewal_proximity_band": (
            "in_window" if days_to_renewal < 90
            else "approaching" if days_to_renewal < 180
            else "distant"
        ),
    }


def _is_view_stale(corpus_path: Path) -> bool:
    """Per Brain_Ready_Views_Contract: view is stale if >24h since file mtime.

    For the prototype, we treat each corpus file's mtime as the view's
    last_refresh_timestamp. In production this would come from the
    materialization job's metadata.
    """
    if not corpus_path.exists():
        return True
    age_hours = (time.time() - corpus_path.stat().st_mtime) / 3600
    return age_hours > 24


def extract_brain_ready_view(corpus_data: dict, corpus_path: Path) -> dict:
    """Build the per-account composite brain-ready view from a corpus file.

    Mirrors the AGT-902 composite view shape from Brain_Ready_Views_Contract.
    Components not in the corpus are marked as not_in_corpus rather than null,
    so the brain can acknowledge missing dimensions explicitly.
    """
    account = corpus_data["account"]
    usage_rows = corpus_data.get("usage_metering_log", [])
    health_rows = corpus_data.get("customer_health_log", [])
    payment_rows = corpus_data.get("payment_event_log", [])
    conv_rows = corpus_data.get("conversation_intelligence_log", [])

    is_stale = _is_view_stale(corpus_path)
    last_refresh = datetime.fromtimestamp(corpus_path.stat().st_mtime, tz=timezone.utc).isoformat()

    return {
        "view_metadata": {
            "last_refresh_timestamp": last_refresh,
            "staleness_threshold_hours": 24,
            "is_stale": is_stale,
            "stale_components": ["all"] if is_stale else [],
        },
        "account_id": account["account_id"],
        "components": {
            "account_root": {
                "company_name": account["company_name"],
                "segment": account["segment"],
                "vertical": account["vertical"],
                "icp_tier": account["icp_tier"],
                "arr_usd": account["arr_usd"],
                "contract_start_date": account["contract_start_date"],
                "contract_end_date": account["contract_end_date"],
                "term_months": account["term_months"],
                "licensed_seats": account["licensed_seats"],
                "contract_age_days": account["contract_age_days_at_corpus_gen"],
            },
            "usage_metering": _summarize_usage(usage_rows),
            "customer_health": _summarize_health(health_rows),
            "conversation_intel": _summarize_conversations(conv_rows),
            "payment_health": _summarize_payments(payment_rows),
            "expansion_signals": _derive_expansion_signals(usage_rows),
            "churn_risk": _derive_churn_proximity(account),
            # Components not synthesized in the prototype corpus
            "opportunities": "not_in_corpus",
            "qbr_history": "not_in_corpus",
            "onboarding": "not_in_corpus",
            "implementation": "not_in_corpus",
        },
    }


# ─────────────────────────────────────────────────────────────────────
# Prompt construction
# ─────────────────────────────────────────────────────────────────────

ACTION_TAXONOMY = [
    "pull_qbr_forward",
    "open_expansion_play",
    "brief_new_ae_or_csm",
    "customer_communication",
    "escalate_to_slm",
    "recommend_human_query",
    "none",
]


SYSTEM_PROMPT = f"""You are AGT-902 Account Brain. Your role: per-account synthesis across all available signals (health, usage, payments, conversations, churn risk, expansion signals). You read brain-ready views; you never write canonical data.

Your output is a JSON object that becomes a BrainAnalysisLog row. Strict schema:

{{
  "narrative_output": "string with inline source citations like [src:1] [src:2] for every numerical or factual claim",
  "sources_read": [
    {{
      "source_index": 1,
      "table_name": "customer_health | usage_metering | conversation_intel | payment_health | expansion_signals | churn_risk | account_root",
      "view_name": "account_brain_view",
      "row_count_consumed": <int>,
      "last_refresh_timestamp": "<view_metadata.last_refresh_timestamp>"
    }}
  ],
  "proposed_actions": [
    {{
      "action_type": "one of: {' | '.join(ACTION_TAXONOMY)}",
      "target": "what entity the action operates on (account, AE, CSM, etc.)",
      "lever": "which Tier 1 service executes this (e.g., AGT-503 / AGT-603 / AGT-504)",
      "justification": "1-2 sentences, must reference a [src:N]",
      "confidence": "high | medium | low"
    }}
  ],
  "confidence_flags": [
    {{
      "claim": "short description of a claim made in narrative_output",
      "level": "high_confidence | multi_source | inference | speculation",
      "supporting_source_indices": [<int>, ...]
    }}
  ],
  "data_staleness_acknowledged": <bool>,
  "stale_sources": [<source_index>, ...]
}}

Rules (these are eval-enforced, treat as hard requirements):

1. SOURCE-TRACE INTEGRITY. Every numerical claim in narrative_output cites a [src:N] that resolves to an entry in sources_read. Reviewers will check.

2. STALENESS RECOGNITION. If view_metadata.is_stale is true OR any component is in view_metadata.stale_components, you MUST set data_staleness_acknowledged=true AND surface staleness in narrative_output (use a phrase like "data is stale" or "last refreshed N days ago"). Operating on stale data without disclosure is a sev-2 incident.

3. ACTION TAXONOMY. Every proposed_actions[].action_type MUST be exactly one of the enum values. Inventing action types fails eval.

4. NEVER WRITE CANONICAL. You produce analysis only. You don't update health scores, never recalculate metrics that AGT-501/AGT-702 own. If a number looks wrong, surface it; don't recompute.

5. CONFIDENCE CALIBRATION. Be honest. Use:
   - high_confidence: directly cited from a single source
   - multi_source: corroborated across multiple sources
   - inference: combined inputs to draw a conclusion
   - speculation: explicit guess where you don't have data
   ~60% of claims should be high_confidence/multi_source. Speculation should be <10%.

6. NOT_IN_CORPUS COMPONENTS. If a component is "not_in_corpus" in the brain-ready view, do not invent data for it. Note explicitly in narrative if relevant ("no QBR history available for this account").

7. OUTPUT JSON ONLY. No preamble, no commentary, no markdown fences. Pure JSON object that parses cleanly.

AVAILABLE TIER 3 TOOLS:

You have access to Tier 3 specialist tools. Call them when relevant. Tool output is canonical for its domain — when you cite a number from a tool, treat the tool itself as a source (add a sources_read entry with table_name set to the tool name, e.g., "tool_004_consumption_forecast" or "tool_008_product_adoption_pattern", and reference it like any other source via [src:N]).

- tool_004_consumption_forecast: Reads the account's UsageMeteringLog history, runs deterministic time-series analysis (linear/log-linear regression, cliff detection, autocorrelation seasonality), and returns a structured forecast plus pattern characterization (linear / exponential / seasonal / cliff / flat). Call this when the question is about expansion qualification, consumption trajectory, "real expansion vs spike," or projected overage timing. The tool's output disambiguates surface signals — if AGT-503 fired but the tool returns is_likely_one_time_spike=true, the brain should weight the tool's classification heavily.

- tool_008_product_adoption_pattern: Reads the account's feature_engagement telemetry (which features are used, by how many users, when first/last used) and classifies the adoption pattern as deeply_integrated / surface_only / siloed_by_team / declining / activating. Different shape than TOOL-004 — TOOL-008 is about WHICH features, not HOW MUCH consumption. Call this when the question is about whether the account is "actually getting value," renewal risk despite green health metrics, cross-team expansion signal, or onboarding success. The tool is onboarding-aware (accounts <60 days into contract are correctly classified "activating" not "surface_only").

Tool selection: TOOL-004 and TOOL-008 are complementary. If a question concerns both volume trajectory and feature depth (e.g., "is this real expansion or just one team using a lot?"), call both. If unsure, prefer calling neither over fabricating tool results.

When you have called any tool, your final response is still the same BrainAnalysisLog JSON schema described above. Cite the tool result like any other source: add it as an entry in sources_read and use [src:N] inline."""


def build_user_prompt(view: dict, question: str) -> str:
    return f"""Question: {question}

Per-account brain-ready view:
```json
{json.dumps(view, indent=2, default=str)}
```

Produce the BrainAnalysisLog JSON object per the schema in the system prompt. Output JSON only."""


def _hash_prompt(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()


# ─────────────────────────────────────────────────────────────────────
# API call + orchestration
# ─────────────────────────────────────────────────────────────────────

def call_brain(view: dict, question: str, max_tokens: int = 4096) -> dict:
    """Call Anthropic API with the brain prompt + tool-use support.

    Multi-turn loop:
      1. Send view + question with tool definitions
      2. If brain returns tool_use blocks → dispatch tools, send results back
      3. Loop until brain produces a text-only response (final output)

    Returns parsed JSON + cumulative metadata across all loop turns.
    """
    # Lazy import to avoid circulars at module load
    from tools.registry import TOOL_DEFINITIONS, dispatch_tool

    user_prompt = build_user_prompt(view, question)
    client = Anthropic()

    messages: list[dict] = [{"role": "user", "content": user_prompt}]
    cumulative_input = 0
    cumulative_output = 0
    cumulative_cached = 0
    tool_calls_made: list[dict] = []
    final_text: str | None = None
    final_response_model: str | None = None
    t0 = time.time()
    max_turns = 4

    for turn in range(max_turns):
        response = client.messages.create(
            model=MODEL,
            max_tokens=max_tokens,
            system=SYSTEM_PROMPT,
            tools=TOOL_DEFINITIONS,
            messages=messages,
        )
        cumulative_input += response.usage.input_tokens
        cumulative_output += response.usage.output_tokens
        cumulative_cached += getattr(response.usage, "cache_read_input_tokens", 0) or 0
        final_response_model = response.model

        # Inspect content blocks. If brain wants tools, execute and continue.
        # If brain returned text only, we have our final output.
        tool_use_blocks = [b for b in response.content if b.type == "tool_use"]
        text_blocks = [b for b in response.content if b.type == "text"]

        if response.stop_reason == "tool_use" and tool_use_blocks:
            # Append assistant response (with tool_use blocks) to message history
            messages.append({"role": "assistant", "content": response.content})

            # Execute each tool, append a single user message containing all tool_results
            tool_results = []
            for block in tool_use_blocks:
                tool_name = block.name
                tool_input = block.input
                result = dispatch_tool(tool_name, tool_input, view)
                tool_calls_made.append({
                    "tool_name": tool_name,
                    "tool_input": tool_input,
                    "tool_result_status": result.get("status", "ok"),
                })
                tool_results.append({
                    "type": "tool_result",
                    "tool_use_id": block.id,
                    "content": json.dumps(result, default=str),
                })
            messages.append({"role": "user", "content": tool_results})
            continue

        # No more tools — brain returned final text
        if text_blocks:
            final_text = text_blocks[0].text
        break

    elapsed_ms = int((time.time() - t0) * 1000)

    if final_text is None:
        raise RuntimeError(
            f"Brain did not return final text after {max_turns} turns. "
            f"Last stop_reason: {response.stop_reason}"
        )

    parsed = _parse_brain_output(final_text)

    return {
        "parsed": parsed,
        "raw_text": final_text,
        "model": final_response_model,
        "input_tokens": cumulative_input,
        "output_tokens": cumulative_output,
        "cached_tokens": cumulative_cached,
        "elapsed_ms": elapsed_ms,
        "system_prompt_hash": _hash_prompt(SYSTEM_PROMPT),
        "tool_calls_made": tool_calls_made,
    }


def _parse_brain_output(text: str) -> dict:
    """Parse JSON, tolerating markdown fences. Raises on empty input with a
    clearer error than json.loads."""
    text = (text or "").strip()
    if not text:
        raise ValueError("brain returned empty text — likely a transient API issue; retry recommended")
    if text.startswith("```"):
        text = text.split("```", 2)[1]
        if text.startswith("json"):
            text = text[4:]
        text = text.strip()
    if text.endswith("```"):
        text = text[:-3].strip()
    return json.loads(text)


def _estimate_cost_usd(input_tokens: int, output_tokens: int, model: str) -> float:
    """Per-token pricing — adjust if Anthropic pricing changes.

    Sonnet 4.x: ~$3/M input, ~$15/M output.
    Haiku 4.x:  ~$0.80/M input, ~$4/M output.
    Opus 4.x:   ~$15/M input, ~$75/M output.
    """
    if "haiku" in model.lower():
        in_per_m, out_per_m = 0.80, 4.00
    elif "opus" in model.lower():
        in_per_m, out_per_m = 15.00, 75.00
    else:    # default sonnet
        in_per_m, out_per_m = 3.00, 15.00
    cost = (input_tokens / 1_000_000) * in_per_m + (output_tokens / 1_000_000) * out_per_m
    return round(cost, 6)


def run_for_account(corpus_path: Path, question: str = DEFAULT_QUESTION,
                    invocation_path: str = "operator_query",
                    operator_user_id: str | None = None,
                    view_mutation_fn=None) -> dict:
    """Full pipeline: read corpus → extract view → call brain → assemble BrainAnalysisLog row.

    view_mutation_fn: optional callable (view: dict) -> dict applied to the brain-ready
    view after extraction. Used by the eval harness to inject staleness or other
    fixture mutations without modifying the corpus on disk.
    """
    with corpus_path.open() as f:
        corpus_data = json.load(f)

    view = extract_brain_ready_view(corpus_data, corpus_path)
    if view_mutation_fn is not None:
        view = view_mutation_fn(view)

    # Up to 2 retries on transient failures (empty response, parse errors).
    # The empty-text flake has hit on Q05/Q08 across runs; one retry is not
    # always enough since a single retry can land on the same cold-cache slot.
    import sys as _sys
    api_result = None
    last_err: Exception | None = None
    for attempt in range(3):
        try:
            api_result = call_brain(view, question)
            break
        except (ValueError, json.JSONDecodeError) as e:
            last_err = e
            _sys.stderr.write(
                f"  brain call failed transiently ({e!s}); attempt {attempt+1}/3...\n"
            )
    if api_result is None:
        raise last_err  # type: ignore[misc]
    parsed = api_result["parsed"]

    # Assemble the BrainAnalysisLog row
    proposal_id = str(uuid.uuid4())
    cost = _estimate_cost_usd(api_result["input_tokens"], api_result["output_tokens"], api_result["model"])

    return {
        "analysis_id": str(uuid.uuid4()),
        "proposal_id": proposal_id,
        "writer_agent_id": WRITER_AGENT_ID,
        "invocation_path": invocation_path,
        "operator_user_id": operator_user_id,
        "account_id": view["account_id"],
        "question": question,
        "system_prompt_hash": api_result["system_prompt_hash"],
        "sources_read": parsed.get("sources_read", []),
        "narrative_output": parsed.get("narrative_output", ""),
        "proposed_actions": parsed.get("proposed_actions", []),
        "confidence_flags": parsed.get("confidence_flags", []),
        "data_staleness_acknowledged": parsed.get("data_staleness_acknowledged", False),
        "stale_sources": parsed.get("stale_sources", []),
        "model_used": api_result["model"],
        "input_tokens": api_result["input_tokens"],
        "output_tokens": api_result["output_tokens"],
        "cached_tokens": api_result["cached_tokens"],
        "cost_usd_estimate": cost,
        "account_synthesis_signature": None,    # not implemented in stub
        "cache_hit": False,
        "response_time_ms": api_result["elapsed_ms"],
        "budget_exceeded": False,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "tool_calls_made": api_result.get("tool_calls_made", []),
        "_meta_view_used": view["view_metadata"],
        "_meta_archetype_key": corpus_data.get("archetype_key"),
        "_meta_expected_outcome": corpus_data.get("expected_outcome_label"),
    }
