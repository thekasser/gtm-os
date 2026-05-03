"""AGT-901 Pipeline Brain runtime.

Sister to agt902 — same brain pattern, different shape:
  - reads cross-account aggregate view (segment×vertical rollups)
  - reasons about cohorts, not individual accounts
  - drills down to specific accounts via TOOL-004 / TOOL-008
  - action taxonomy is pipeline-shaped (draft_play, flag_coverage_gap, etc.)

Per the AGT-901 spec: brain proposes plays/gaps/queries; never writes
canonical data; outputs land in BrainAnalysisLog. Promotion to ABMPlaybook
or any canonical Tier 1 table is a gated human action — same approval
model as AGT-902.
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

from aggregates import extract_pipeline_view


# ─────────────────────────────────────────────────────────────────────
# Config
# ─────────────────────────────────────────────────────────────────────

MODEL = os.environ.get("ANTHROPIC_MODEL", "claude-sonnet-4-6")
WRITER_AGENT_ID = "AGT-901"

DEFAULT_QUESTION = "Diagnose the pipeline state. Where's the softness, where's the opportunity, what's the play?"


# ─────────────────────────────────────────────────────────────────────
# Action taxonomy — distinct from AGT-902's per-account actions
# ─────────────────────────────────────────────────────────────────────

ACTION_TAXONOMY = [
    "draft_play",                  # propose a play targeting a cohort (segment, vertical, ICP tier)
    "flag_coverage_gap",           # surface a gap in pipeline coverage / underweighted segment
    "recommend_query_for_human",   # query for RevOps/sales leader to investigate
    "none",                        # explicitly state no action needed
]


# ─────────────────────────────────────────────────────────────────────
# System prompt
# ─────────────────────────────────────────────────────────────────────

SYSTEM_PROMPT = f"""You are AGT-901 Pipeline Brain. Your role: cross-account synthesis at the cohort level (segment, vertical, ICP tier, archetype). You read brain-ready aggregate views; you never write canonical data.

You are the COMPLEMENT to AGT-902 Account Brain:
  - AGT-902 reasons about ONE account at a time (per-account view).
  - AGT-901 reasons about COHORTS (segment, vertical, archetype distribution).
You do NOT do per-account analysis — that's AGT-902's job. If a question needs deep per-account work, propose a recommend_query_for_human that calls AGT-902 with a specific account_id.

Your output is a JSON object that becomes a BrainAnalysisLog row. Strict schema:

{{
  "narrative_output": "string with inline source citations like [src:1] [src:2] for every numerical or factual claim. Cohort claims must cite the rollup section they came from.",
  "sources_read": [
    {{
      "source_index": 1,
      "table_name": "headline_metrics | segment_rollup | vertical_rollup | icp_tier_rollup | archetype_distribution | top_expansion_candidates | top_churn_risks | stalled_onboardings | tool_004_consumption_forecast | tool_008_product_adoption_pattern",
      "view_name": "pipeline_aggregate",
      "row_count_consumed": <int>,
      "last_refresh_timestamp": "<view.snapshot_date>"
    }}
  ],
  "proposed_actions": [
    {{
      "action_type": "one of: {' | '.join(ACTION_TAXONOMY)}",
      "target": "the cohort the action operates on (e.g., 'SMB segment', 'HealthTech vertical', 'T1 ICP accounts in stalled_onboarding'). For recommend_query_for_human, the target is which downstream agent or human role.",
      "lever": "which Tier 1 service or downstream brain executes this (e.g., 'AGT-203 ABM Target Selection', 'AGT-302 Cadence Coordinator', 'AGT-902 Account Brain', 'RevOps leader')",
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

1. SOURCE-TRACE INTEGRITY. Every numerical claim in narrative_output cites a [src:N] that resolves to an entry in sources_read. Cohort metrics MUST cite the specific rollup table they came from (segment_rollup, vertical_rollup, etc.) — not just a generic "view".

2. COHORT-LEVEL ONLY. Your job is patterns across cohorts, not individual accounts. Phrases like "Acme Corp is in trouble because..." belong in AGT-902, not here. You may NAME individual accounts only when they appear in top_expansion_candidates / top_churn_risks / stalled_onboardings — and only as evidence FOR a cohort claim, not as the focus.

3. ACTION TAXONOMY. Every proposed_actions[].action_type MUST be exactly one of: {', '.join(ACTION_TAXONOMY)}. Inventing action types fails eval.

4. NEVER WRITE CANONICAL. You produce analysis only. Plays you draft go to a SalesPlayLibrary draft state; promotion to ABMPlaybook (which AGT-203 owns) requires human approval.

5. CONFIDENCE CALIBRATION. Honest. Be especially conservative when the corpus is small — a 12-account SMB cohort is a small sample, and statements about it should usually be inference or speculation, not high_confidence.

6. STALENESS RECOGNITION. If the view's snapshot_date is more than a few days old or any source is flagged stale, set data_staleness_acknowledged=true and surface it.

7. OUTPUT JSON ONLY. No preamble, no commentary, no markdown fences. Pure JSON object that parses cleanly.

AVAILABLE TIER 3 TOOLS:

You have access to Tier 3 specialist tools for drill-down. Call them when answering a cohort question requires evidence from a specific account in the cohort. Tool output is canonical for its domain — when you cite a tool, treat it as a source.

- tool_004_consumption_forecast: Per-account consumption-trajectory analysis. Useful when a top_expansion_candidates entry's overage signal needs validation as real expansion vs. one-time spike. Pass account_id from the candidate record.

- tool_008_product_adoption_pattern: Per-account feature-engagement classification. Useful when a top_churn_risks or stalled_onboardings entry needs adoption-depth diagnosis. Pass account_id from the candidate record.

Tool selection: use sparingly. Drilling into 5+ accounts per cohort question is overkill — pick 1-2 representative accounts to validate or refute the cohort hypothesis. If the question is purely cohort-level (e.g., "compare SMB to MM expansion-readiness"), no drill-down is needed.

When you have called any tool, your final response is still the same BrainAnalysisLog JSON schema described above. Cite the tool result like any other source."""


# ─────────────────────────────────────────────────────────────────────
# Prompt + parsing utilities
# ─────────────────────────────────────────────────────────────────────

def build_user_prompt(view: dict, question: str) -> str:
    return f"""Question: {question}

Pipeline brain-ready aggregate view:
```json
{json.dumps(view, indent=2, default=str)}
```

Produce the BrainAnalysisLog JSON object per the schema in the system prompt. Output JSON only."""


def _hash_prompt(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()


def _parse_brain_output(text: str) -> dict:
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
    if "haiku" in model.lower():
        in_per_m, out_per_m = 0.80, 4.00
    elif "opus" in model.lower():
        in_per_m, out_per_m = 15.00, 75.00
    else:
        in_per_m, out_per_m = 3.00, 15.00
    return round((input_tokens / 1_000_000) * in_per_m
                 + (output_tokens / 1_000_000) * out_per_m, 6)


# ─────────────────────────────────────────────────────────────────────
# API call orchestration — multi-turn tool-use loop, mirrors agt902
# ─────────────────────────────────────────────────────────────────────

def call_brain(view: dict, question: str, max_tokens: int = 8192) -> dict:
    """Call Anthropic API with the AGT-901 prompt + tool-use support.

    max_tokens=8192 (vs AGT-902's 4096) — the cohort brain produces longer
    narratives that cite multiple rollups + drill-down accounts. The smoke
    test hit consistent unterminated-string truncation at 4096.
    """
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

        tool_use_blocks = [b for b in response.content if b.type == "tool_use"]
        text_blocks = [b for b in response.content if b.type == "text"]

        if response.stop_reason == "tool_use" and tool_use_blocks:
            messages.append({"role": "assistant", "content": response.content})
            tool_results = []
            for block in tool_use_blocks:
                tool_name = block.name
                tool_input = block.input
                # AGT-901 doesn't have a per-account view; pass an empty
                # view with the account_id the brain provided so dispatch's
                # corpus augmentation works.
                tool_view = {"account_id": tool_input.get("account_id")}
                result = dispatch_tool(tool_name, tool_input, tool_view)
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


# ─────────────────────────────────────────────────────────────────────
# Public entry point
# ─────────────────────────────────────────────────────────────────────

def run_for_pipeline(corpus_dir: Path, question: str = DEFAULT_QUESTION,
                     invocation_path: str = "operator_query",
                     operator_user_id: str | None = None,
                     view_mutation_fn=None) -> dict:
    """Full pipeline: extract aggregate view → call brain → assemble BrainAnalysisLog row.

    No per-account corpus loading — the aggregate view comes from
    aggregates.extract_pipeline_view, which iterates the whole corpus dir.
    """
    view = extract_pipeline_view(corpus_dir)
    if view_mutation_fn is not None:
        view = view_mutation_fn(view)

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

    proposal_id = str(uuid.uuid4())
    cost = _estimate_cost_usd(api_result["input_tokens"],
                              api_result["output_tokens"], api_result["model"])

    return {
        "analysis_id": str(uuid.uuid4()),
        "proposal_id": proposal_id,
        "writer_agent_id": WRITER_AGENT_ID,
        "invocation_path": invocation_path,
        "operator_user_id": operator_user_id,
        "account_id": None,                # cohort-level, no single account
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
        "cache_hit": False,
        "response_time_ms": api_result["elapsed_ms"],
        "budget_exceeded": False,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "tool_calls_made": api_result.get("tool_calls_made", []),
        "_meta_view_corpus_size": view.get("corpus_size"),
        "_meta_view_snapshot_date": view.get("snapshot_date"),
    }
