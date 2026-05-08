"""AGT-903 Strategy Brain — runtime prototype.

Implements the v37 spec architectural commitments:
  - Multi-quarter portfolio reasoning (4-12 trailing quarters)
  - Reads strategy_brain_view extensions from Tier 1 services
  - Calls Anthropic API (Opus default) with structured prompt
  - Output is option-shaped (2-4 alternatives + 4-class risk surface +
    assumptions-must-hold), never single answers
  - Writes to BrainAnalysisLog + StrategyRecommendationLog (both jsonl)
  - Action taxonomy distinct from AGT-901/902 (propose_* family)
  - Tier 3 tool access: TOOL-013, TOOL-014, TOOL-015
  - Refusal-first when required strategy_brain_view missing/stale

For the prototype, strategy_brain_views are assembled from synth corpus
via prototype/strategy_brain_view.py shim — production reads materialized
views per Brain_Ready_Views_Contract v37 extension.
"""

from __future__ import annotations

import hashlib
import json
import os
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path

from anthropic import Anthropic


MODEL = os.environ.get("AGT_903_MODEL", "claude-opus-4-1-20250805")
WRITER_AGENT_ID = "AGT-903"

DEFAULT_QUESTION = (
    "Strategy retrospective: what does the multi-quarter cohort data say, "
    "and what are the 2-4 strategic options to consider next?"
)


# ─────────────────────────────────────────────────────────────────────
# Action taxonomy (per AGT-903 spec — distinct from AGT-901/902)
# ─────────────────────────────────────────────────────────────────────

ACTION_TAXONOMY = [
    "propose_icp_revision",
    "propose_segment_redefinition",
    "propose_vertical_entry",
    "propose_capacity_reallocation",
    "propose_pricing_packaging_review",
    "flag_strategic_risk",
    "recommend_market_research_query",
    "recommend_human_query",
    "none",
]

# Actions requiring options-discipline (2-4 options) per spec
OPTION_REQUIRING_ACTIONS = {
    "propose_icp_revision",
    "propose_segment_redefinition",
    "propose_vertical_entry",
    "propose_capacity_reallocation",
    "propose_pricing_packaging_review",
}

# Scope severity classifications (per StrategyRecommendationLog schema)
SCOPE_SEVERITIES = ["routine", "significant", "material"]


# ─────────────────────────────────────────────────────────────────────
# System prompt — option-shaped, risk-class enforcement, assumptions
# ─────────────────────────────────────────────────────────────────────

SYSTEM_PROMPT = f"""You are AGT-903 Strategy Brain — the multi-quarter portfolio-reasoning layer of the GTM OS. Your role: long-horizon strategic queries (ICP revision, vertical entry, capacity reallocation, pricing strategy, strategic-bet retrospective). You read strategy_brain_view extensions from Tier 1 services; you never write canonical data.

YOUR OUTPUT: a JSON object that becomes a BrainAnalysisLog row PLUS the body of a StrategyRecommendationLog row. Strict schema:

{{
  "narrative_output": "string with inline source citations like [src:1] [src:2] for every numerical or factual claim. Multi-paragraph; describes what the multi-quarter data shows.",
  "sources_read": [
    {{
      "source_index": 1,
      "table_name": "metrics_strategy_brain_view | win_loss_strategy_brain_view | cohort_brain_view | icp_outcome_brain_view | market_assumptions_strategy_brain_view | voc_strategy_brain_view | capacity_strategy_brain_view | quota_strategy_brain_view | expansion_strategy_brain_view | top_down_forecast_strategy_brain_view",
      "view_name": "strategy_brain_view",
      "row_count_consumed": <int>,
      "last_refresh_timestamp": "<view_metadata.last_refresh_timestamp>"
    }}
  ],
  "scope_severity": "routine | significant | material",
  "action_type": "one of: {' | '.join(ACTION_TAXONOMY)}",
  "options_enumerated": [
    {{
      "option_label": "string — 1-3 word label distinct per option",
      "hypothesis": "1-2 sentences — what this option assumes is true",
      "projected_impact_range": "string — RANGE not point estimate (e.g. 'GP +3-7pp over 4 quarters')",
      "required_investment": "string — qualitative or quantitative",
      "capacity_implications": "string — rep / engineering / FP&A capacity needed",
      "tier1_dependencies": ["AGT-NNN", ...]
    }}
  ],
  "tradeoffs_matrix": [
    {{
      "option_label": "string (matches options_enumerated)",
      "upside_scenario": "1 sentence",
      "downside_scenario": "1 sentence",
      "preconditions_for_success": ["string", ...]
    }}
  ],
  "risk_surface": {{
    "market_risks": [{{"description": "string", "confidence_flag": "high | medium | low | speculation"}}],
    "execution_risks": [{{"description": "string", "confidence_flag": "high | medium | low | speculation"}}],
    "capacity_risks": [{{"description": "string", "confidence_flag": "high | medium | low | speculation"}}],
    "model_assumption_risks": [{{"description": "string", "confidence_flag": "high | medium | low | speculation"}}]
  }},
  "assumptions_must_hold": [
    {{
      "assumption": "string — a falsifiable assumption underlying the analysis",
      "evidence_basis": "string — what supports this currently",
      "brittleness": "brittle | stable | untested",
      "source_ref": "[src:N] or null"
    }}
  ],
  "suggested_workstream_owners": [
    {{
      "owner": "AGT-NNN or 'cross-functional pricing committee' or 'RevOps strategic research'",
      "scope_of_responsibility": "1 sentence describing what the workstream does"
    }}
  ],
  "data_staleness_acknowledged": <bool>,
  "stale_sources": [<source_index>, ...] or null,
  "confidence_flags": [
    {{
      "claim": "short description of a claim in narrative_output",
      "level": "high_confidence | multi_source | inference | speculation",
      "supporting_source_indices": [<int>, ...]
    }}
  ]
}}

CRITICAL DISCIPLINE — NON-NEGOTIABLE:

1. OPTIONS-SHAPED, NOT SINGLE-ANSWER. For propose_* action types, options_enumerated MUST contain 2-4 distinct options with different hypotheses. If you find yourself with one obvious answer, articulate at least one credible alternative + the conditions under which it would be correct. Eval enforces option_count_in_range. Single-answer outputs on propose_* actions are hard fails.

2. RISK SURFACE — ALL 4 CLASSES. For propose_* actions, risk_surface must populate market_risks, execution_risks, capacity_risks, AND model_assumption_risks. Each may have 1-3 entries; each entry carries a confidence_flag. Eval enforces risk_classes_present.

3. PROJECTED IMPACT RANGE, NOT POINT ESTIMATE. Each option's projected_impact_range MUST be a range (e.g., 'GP +3-7pp over 4 quarters'), not a point estimate. Strategic uncertainty is real; pretending it isn't is dishonest. Eval enforces no_point_estimates.

4. ASSUMPTIONS-MUST-HOLD ARE FALSIFIABLE. Each assumption is something that could be checked/disproved. Vague aspirations ('the market will continue to be receptive') don't qualify. Mark brittleness honestly: brittle = single-event-could-disprove, untested = no historical evidence, stable = confirmed across multiple quarters.

5. SOURCE CITATION RATE >= 95%. Every numerical claim in narrative_output cites a [src:N]. Multi-quarter trends, cohort comparisons, GP attributions — all require source citations.

6. STALENESS HARD-REQUIREMENT. If any source has is_stale=true in view_metadata, set data_staleness_acknowledged=true AND surface staleness in narrative. Do NOT estimate values from stale data. Refuse if the question's load-bearing source is stale.

7. REFUSAL IS FIRST-CLASS. If a required strategy_brain_view is missing entirely, set action_type='recommend_human_query' or 'recommend_market_research_query' (whichever fits) and explain the gap in narrative. Do NOT fabricate the missing analysis. Refusal-correctness is eval-enforced.

8. SPECULATION CAN REACH 25-30%. Unlike AGT-901/902 (where speculation should be <10%), AGT-903 multi-quarter strategic reasoning involves more legitimate uncertainty. Mark speculation honestly; don't dress it up as inference.

9. WORKSTREAM OWNERS MAP TO REAL TIER 1 SERVICES. Each suggested_workstream_owners entry names AGT-NNN (per the proposed action). Endorsement triggers a HUMAN-LED workstream owned by that service — never a direct table edit. If the workstream is cross-functional (pricing committee, external research), name the function not an AGT-ID.

10. OUTPUT JSON ONLY. No preamble, no markdown fences. Pure JSON object that parses cleanly.

AVAILABLE TIER 3 TOOLS:

- tool_013_cohort_retention_forecaster: Reads observed retention curves for signup-quarter cohorts and projects forward with confidence bands. Refusal-first when cohort < 25 accounts or < 4 observed periods. Use for "did the bet work?" / "is retention flattening on newer cohorts?" / "what's the projected NRR floor on the 2024 cohort?". Pass cohorts as caller-supplied input — tool projects what you give it, never invents cohorts.

- tool_014_segment_ltv_decomposer: Decomposes LTV gaps between segment / vertical / ICP-tier / control-tier buckets into driver components (initial_acv, tenure, expansion_realization, cac, segment_mix). Hard rule: a driver is load_bearing only when bootstrap band excludes zero with same-sign p10/p90. Use for ICP-revision (which dimensions correlate with realized LTV?), capacity-reallocation (where's the highest LTV-per-rep payoff?), vertical-entry (LTV in opportunistic-vertical vs core).

- tool_015_consumption_margin_decomposer: Per-customer GP attribution + tier-migration projection for consumption-pricing tiered platforms. Decomposes GP into pricing / utilization / backend-cost / tier-mix axes. Refusal-first when backend cost coverage < 90%. Use cohort-aggregated mode for "where is segment-X margin compressing?".

Tool selection: TOOL-013 = cohort retention; TOOL-014 = LTV-driver decomposition; TOOL-015 = GP attribution + tier migration. Call the one(s) that match the question's actual dimension. Don't fabricate tool results."""


# ─────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────

def _hash_prompt(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()


def build_user_prompt(view: dict, question: str, scope_tags: dict | None = None) -> str:
    scope_str = json.dumps(scope_tags, indent=2) if scope_tags else "(none)"
    return f"""Strategic Question: {question}

Scope tags (segment / vertical / time-window axes covered):
{scope_str}

Strategy brain-ready views available:
```json
{json.dumps(view, indent=2, default=str)}
```

Produce the BrainAnalysisLog + StrategyRecommendationLog JSON object per the schema in the system prompt. Output JSON only."""


def _parse_brain_output(text: str) -> dict:
    text = text.strip()
    if text.startswith("```"):
        text = text.split("```", 2)[1]
        if text.startswith("json"):
            text = text[4:]
        text = text.strip()
    if text.endswith("```"):
        text = text[:-3].strip()
    return json.loads(text)


# ─────────────────────────────────────────────────────────────────────
# API call + multi-turn tool-use loop
# ─────────────────────────────────────────────────────────────────────

def call_brain(view: dict, question: str, scope_tags: dict | None = None,
               max_tokens: int = 8192, max_turns: int = 4) -> dict:
    """Call Opus with strategy view + question, support multi-turn tool use.

    Returns parsed JSON + cumulative metadata across all loop turns.
    """
    from tools.registry import TOOL_DEFINITIONS, dispatch_tool

    user_prompt = build_user_prompt(view, question, scope_tags)
    client = Anthropic()

    messages: list[dict] = [{"role": "user", "content": user_prompt}]
    cumulative_input = 0
    cumulative_output = 0
    cumulative_cached = 0
    tool_calls_made: list[dict] = []
    final_text: str | None = None
    final_response_model: str | None = None
    t0 = time.time()

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

        tool_use_blocks = [b for b in response.content if b.type == "tool_use"]
        text_blocks = [b for b in response.content if b.type == "text"]

        if response.stop_reason == "tool_use" and tool_use_blocks:
            messages.append({"role": "assistant", "content": response.content})
            tool_results = []
            for block in tool_use_blocks:
                tool_name = block.name
                tool_input = block.input
                # AGT-903 tools take input as-is (no view-based augmentation
                # like AGT-902); brain assembles tool input from the strategy
                # view it has access to. Call dispatch_tool with empty view
                # since the brain provides its own input.
                try:
                    result = dispatch_tool(tool_name, tool_input, view={}, source=None)
                except Exception as e:
                    result = {"tool_name": tool_name, "status": "dispatch_error", "reason": str(e)}
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

        if text_blocks:
            final_text = text_blocks[0].text
        break

    elapsed_ms = int((time.time() - t0) * 1000)

    if final_text is None:
        raise RuntimeError(
            f"Brain did not return final text after {max_turns} turns. "
            f"Last stop_reason: {response.stop_reason}"
        )

    # JSON parse with one retry (mirrors AGT-902 v36.2 retry pattern)
    try:
        parsed = _parse_brain_output(final_text)
    except json.JSONDecodeError:
        # Retry: re-prompt asking for clean JSON
        messages.append({"role": "assistant", "content": [{"type": "text", "text": final_text}]})
        messages.append({"role": "user", "content": (
            "Your last response was not valid JSON. Please re-emit the JSON object "
            "described in the schema. Output JSON only — no preamble, no markdown."
        )})
        retry_response = client.messages.create(
            model=MODEL, max_tokens=max_tokens, system=SYSTEM_PROMPT, messages=messages,
        )
        cumulative_input += retry_response.usage.input_tokens
        cumulative_output += retry_response.usage.output_tokens
        retry_text = "".join(b.text for b in retry_response.content if b.type == "text")
        parsed = _parse_brain_output(retry_text)
        final_text = retry_text

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


# ─────────────────────────────────────────────────────────────────────
# Output assembly + log writers
# ─────────────────────────────────────────────────────────────────────

DEFAULT_BRAIN_LOG = Path(__file__).parent / "brain_analysis_log.jsonl"
DEFAULT_STRATEGY_LOG = Path(__file__).parent / "strategy_recommendation_log.jsonl"


def assemble_brain_analysis_row(parsed: dict, raw_meta: dict, question: str,
                                  proposal_id: str | None = None) -> dict:
    """Build BrainAnalysisLog row from parsed brain output."""
    if proposal_id is None:
        proposal_id = str(uuid.uuid4())
    return {
        "analysis_id": str(uuid.uuid4()),
        "proposal_id": proposal_id,
        "writer_agent_id": WRITER_AGENT_ID,
        "invocation_path": "operator_query",
        "operator_user_id": None,
        "account_id": None,    # AGT-903 outputs are cross-account
        "question": question,
        "system_prompt_hash": raw_meta["system_prompt_hash"],
        "sources_read": parsed.get("sources_read", []),
        "narrative_output": parsed.get("narrative_output", ""),
        "proposed_actions": [{
            "action_type": parsed.get("action_type", "none"),
            "scope_severity": parsed.get("scope_severity", "routine"),
            "options_count": len(parsed.get("options_enumerated", [])),
        }],
        "confidence_flags": parsed.get("confidence_flags", []),
        "data_staleness_acknowledged": parsed.get("data_staleness_acknowledged", False),
        "stale_sources": parsed.get("stale_sources"),
        "model_used": raw_meta["model"],
        "input_tokens": raw_meta["input_tokens"],
        "output_tokens": raw_meta["output_tokens"],
        "cached_tokens": raw_meta["cached_tokens"],
        "cost_usd_estimate": _estimate_cost_usd(
            raw_meta["model"], raw_meta["input_tokens"], raw_meta["output_tokens"]
        ),
        "tool_calls_made": raw_meta["tool_calls_made"],
        "response_time_ms": raw_meta["elapsed_ms"],
        "created_at": datetime.now(timezone.utc).isoformat(),
    }


def assemble_strategy_recommendation_row(parsed: dict, raw_meta: dict, question: str,
                                          proposal_id: str, scope_tags: dict | None) -> dict:
    """Build StrategyRecommendationLog row from parsed brain output."""
    return {
        "recommendation_id": str(uuid.uuid4()),
        "state": "draft",
        "question": question,
        "scope_tags": scope_tags or {},
        "scope_severity": parsed.get("scope_severity", "routine"),
        "action_type": parsed.get("action_type", "none"),
        "options_enumerated": parsed.get("options_enumerated", []),
        "tradeoffs_matrix": parsed.get("tradeoffs_matrix", []),
        "risk_surface": parsed.get("risk_surface", {}),
        "assumptions_must_hold": parsed.get("assumptions_must_hold", []),
        "sources_read": parsed.get("sources_read", []),
        "narrative": parsed.get("narrative_output", ""),
        "suggested_workstream_owners": parsed.get("suggested_workstream_owners", []),
        "data_staleness_acknowledged": parsed.get("data_staleness_acknowledged", False),
        "originating_proposal_id": proposal_id,
        "writer_agent_id": WRITER_AGENT_ID,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "cost_metadata": {
            "model": raw_meta["model"],
            "input_tokens": raw_meta["input_tokens"],
            "output_tokens": raw_meta["output_tokens"],
            "cached_tokens": raw_meta["cached_tokens"],
            "cost_usd_estimate": _estimate_cost_usd(
                raw_meta["model"], raw_meta["input_tokens"], raw_meta["output_tokens"]
            ),
        },
    }


def _estimate_cost_usd(model: str, input_tokens: int, output_tokens: int) -> float:
    """Approximate cost using public pricing snapshots (Anthropic)."""
    if "opus" in model.lower():
        # Opus 4.x: ~$15/M input + $75/M output
        return round(input_tokens / 1_000_000 * 15.0 + output_tokens / 1_000_000 * 75.0, 4)
    if "sonnet" in model.lower():
        return round(input_tokens / 1_000_000 * 3.0 + output_tokens / 1_000_000 * 15.0, 4)
    if "haiku" in model.lower():
        return round(input_tokens / 1_000_000 * 1.0 + output_tokens / 1_000_000 * 5.0, 4)
    return round(input_tokens / 1_000_000 * 3.0 + output_tokens / 1_000_000 * 15.0, 4)


def write_brain_analysis(row: dict, path: Path = DEFAULT_BRAIN_LOG) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a") as f:
        f.write(json.dumps(row, default=str) + "\n")


def write_strategy_recommendation(row: dict, path: Path = DEFAULT_STRATEGY_LOG) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a") as f:
        f.write(json.dumps(row, default=str) + "\n")


# ─────────────────────────────────────────────────────────────────────
# Main entry — used by run_agt903.py
# ─────────────────────────────────────────────────────────────────────

def run_query(view: dict, question: str, scope_tags: dict | None = None,
              fixture_id: str | None = None) -> dict:
    """End-to-end: call brain, assemble logs, write to both jsonl outputs.

    Returns the parsed brain output + cost metadata for the caller.
    """
    raw = call_brain(view, question, scope_tags)
    parsed = raw["parsed"]
    proposal_id = str(uuid.uuid4())

    # BrainAnalysisLog row (always)
    brain_row = assemble_brain_analysis_row(parsed, raw, question, proposal_id)
    if fixture_id:
        brain_row["fixture_id"] = fixture_id
    write_brain_analysis(brain_row)

    # StrategyRecommendationLog row (always — brain output's natural target)
    strategy_row = assemble_strategy_recommendation_row(
        parsed, raw, question, proposal_id, scope_tags
    )
    if fixture_id:
        strategy_row["fixture_id"] = fixture_id
    write_strategy_recommendation(strategy_row)

    return {
        "parsed": parsed,
        "brain_analysis_row": brain_row,
        "strategy_recommendation_row": strategy_row,
        "cost_metadata": {
            "model": raw["model"],
            "input_tokens": raw["input_tokens"],
            "output_tokens": raw["output_tokens"],
            "cost_usd_estimate": brain_row["cost_usd_estimate"],
            "elapsed_ms": raw["elapsed_ms"],
        },
        "tool_calls_made": raw["tool_calls_made"],
    }
