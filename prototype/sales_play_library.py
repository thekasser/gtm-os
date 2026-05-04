"""SalesPlayLibrary writer — converts BrainAnalysisLog proposed_actions into
structured `draft` play records.

Per the SalesPlayLibrary schema (schema/SalesPlayLibrary_Schema.html):
  - Brain Agents (AGT-901, AGT-902) write rows in `draft` state ONLY.
  - Humans transition draft → under_review → active. Brains never approve.
  - Each row carries `originating_proposal_id` linkage to BrainAnalysisLog
    so we can do cohort-level retrospective on brain-co-designed plays vs.
    plays designed without brain involvement.

This module is the prototype version of that writer. It runs after a brain
call, scans the brain output's `proposed_actions[]`, filters for the action
types that are "play-shaped" (vs. one-off interventions), and writes a
`draft` SalesPlayLibrary row per play-shaped action.

In production, this becomes a service-mediated DB INSERT with the full
schema enforcement (state machine, cap check on activation, etc.). The
prototype writes JSONL append-only, matching the BrainAnalysisLog pattern.
"""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from pathlib import Path


DEFAULT_LOG_PATH = Path(__file__).parent / "sales_play_library.jsonl"


# ─────────────────────────────────────────────────────────────────────
# Action-type → play-shaped classification
# ─────────────────────────────────────────────────────────────────────
#
# Not every brain action is a play. The action taxonomy mixes three things:
#   (a) Multi-touch sequences executed via AGT-302 — these ARE plays.
#       Examples: open_expansion_play (AGT-902), draft_play (AGT-901).
#   (b) Single-shot interventions handled by a specific service.
#       Examples: pull_qbr_forward (AGT-603), brief_new_ae_or_csm (AGT-405),
#       customer_communication (AGT-504), escalate_to_slm (handoff to human).
#   (c) Information actions for humans that don't generate any execution.
#       Examples: recommend_human_query, recommend_query_for_human,
#       flag_coverage_gap, none.
#
# Only (a) becomes a SalesPlayLibrary draft. The rest stay in
# BrainAnalysisLog.proposed_actions[] and are routed to their target
# service / human via existing mechanisms (the brain runtime doesn't
# execute them; this writer just identifies which actions are play-shaped).

PLAY_SHAPED_ACTIONS: set[str] = {
    "open_expansion_play",   # AGT-902 — per-account expansion sequence
    "draft_play",            # AGT-901 — cohort-targeted play proposal
}


# ─────────────────────────────────────────────────────────────────────
# Conversion: BrainAnalysisLog proposed_action → SalesPlayLibrary draft
# ─────────────────────────────────────────────────────────────────────

def _scope_for_writer(writer_agent_id: str) -> str:
    """AGT-902 plays are always account_specific; AGT-901 plays are segment."""
    if writer_agent_id == "AGT-902":
        return "account_specific"
    if writer_agent_id == "AGT-901":
        return "segment"
    return "segment"  # default — unknown brain agent


def _name_for_play(action: dict, writer_agent_id: str) -> str:
    """Synthesize a short play name from action_type + target.

    Real RevOps users will rewrite this in `under_review`. The prototype
    name just has to be informative enough that a human can identify the
    draft in a workspace listing.
    """
    action_type = action.get("action_type", "play")
    target = action.get("target", "")
    # Truncate target to keep names compact
    target_short = target[:60] + "…" if len(target) > 60 else target
    return f"[draft] {action_type} — {target_short}".strip()


def _hypothesis_from_action(action: dict) -> str:
    """The brain's justification IS the hypothesis. This is the most important
    signal for the human reviewer — what does the brain think will work?"""
    return action.get("justification", "(brain did not provide a justification)")


def _target_definition_from_action(action: dict, brain_row: dict,
                                    scope: str) -> dict:
    """Build target_definition JSON from the brain output's context.

    For account_specific (AGT-902): target is the single account.
    For segment (AGT-901): target is parsed from action.target — best-effort
    until humans co-define in under_review.
    """
    target_text = action.get("target", "")
    if scope == "account_specific":
        return {
            "scope": "account_specific",
            "account_id": brain_row.get("account_id"),
            "raw_target": target_text,
        }
    return {
        "scope": "segment",
        "raw_target": target_text,
        "lever": action.get("lever"),
        "note": "segment derivation pending human pickup; brain provided raw_target",
    }


def _suggested_cadence_placeholder(action: dict) -> dict:
    """Fallback when TOOL-003 isn't available or fails. Structured stub
    that signals where humans need to fill in."""
    return {
        "status": "pending_human_codefinition",
        "channel_mix": [],
        "touch_count": None,
        "duration_days": None,
        "lever_hint": action.get("lever"),
        "note": "Brain proposed the play; cadence is human-defined in under_review.",
    }


def _success_criteria_placeholder(action: dict) -> dict:
    """Fallback when TOOL-003 isn't available or fails."""
    return {
        "status": "pending_human_codefinition",
        "target_meeting_rate": None,
        "target_opp_create_rate": None,
        "target_acv": None,
        "evaluation_window_days": 90,
        "note": "Brain did not propose explicit success criteria; humans define in under_review.",
    }


# Cap on TOOL-003 calls per writer invocation. Each brain call typically
# produces 0-2 play-shaped actions; this cap is a defensive guard against
# pathological cases (e.g., a brain producing 20 play_drafts in one run
# and burning through Haiku budget unexpectedly).
MAX_TOOL_003_CALLS_PER_INVOCATION = 5


def _enrich_via_tool_003(action: dict, brain_row: dict, scope: str) -> dict | None:
    """Call TOOL-003 to compose cadence + criteria from the action's
    hypothesis. Returns the tool result dict, or None on failure.

    Failure does not raise — falls back to placeholders. Logged inline.
    """
    try:
        from tools.tool_003 import tool_003_handler
    except Exception:
        return None

    sources_read = brain_row.get("sources_read", [])
    originating_signals = [
        {
            "source_index": s.get("source_index"),
            "table_name": s.get("table_name"),
        }
        for s in sources_read
    ]
    target_definition = (
        {"scope": "account_specific",
         "account_id": brain_row.get("account_id"),
         "raw_target": action.get("target")}
        if scope == "account_specific"
        else {"scope": "segment", "raw_target": action.get("target"),
              "lever": action.get("lever")}
    )
    tool_input = {
        "play_hypothesis": action.get("justification", ""),
        "scope": scope,
        "target_definition": target_definition,
        "originating_signals": originating_signals,
        "lever_hint": action.get("lever"),
        "writer_brain": brain_row.get("writer_agent_id"),
    }
    try:
        return tool_003_handler(tool_input)
    except Exception as e:
        import sys as _sys
        _sys.stderr.write(f"  warn: TOOL-003 enrichment failed: {e!s}\n")
        return None


def build_draft_record(action: dict, brain_row: dict,
                        enrich_with_tool_003: bool = True) -> dict:
    """Convert ONE play-shaped proposed_action into a SalesPlayLibrary draft row.

    When `enrich_with_tool_003` is True (default), calls TOOL-003 to compose
    a starting cadence + success criteria. On TOOL-003 failure, falls back
    to placeholders. Caller controls enrichment to enforce per-invocation
    caps (see write_drafts_from_brain_row).
    """
    writer_agent_id = brain_row.get("writer_agent_id", "AGT-?")
    scope = _scope_for_writer(writer_agent_id)

    play_id = str(uuid.uuid4())
    now = datetime.now(timezone.utc).isoformat()

    # Find which sources the action's justification references — best-effort
    # match against the brain's sources_read for downstream traceability.
    sources_read = brain_row.get("sources_read", [])
    supporting_source_ids = [s.get("source_index") for s in sources_read]

    # Enrichment: TOOL-003 composes cadence + criteria from hypothesis.
    suggested_cadence = _suggested_cadence_placeholder(action)
    success_criteria = _success_criteria_placeholder(action)
    tool_003_metadata = None
    if enrich_with_tool_003:
        tool_003_result = _enrich_via_tool_003(action, brain_row, scope)
        if tool_003_result and tool_003_result.get("status") == "ok":
            if tool_003_result.get("suggested_cadence"):
                suggested_cadence = tool_003_result["suggested_cadence"]
            if tool_003_result.get("success_criteria"):
                success_criteria = tool_003_result["success_criteria"]
            tool_003_metadata = {
                "tool": "TOOL-003",
                "status": "ok",
                "confidence": tool_003_result.get("confidence"),
                "ungrounded_assumptions": tool_003_result.get("ungrounded_assumptions", []),
                "_llm_metadata": tool_003_result.get("_llm_metadata"),
            }
        elif tool_003_result:
            tool_003_metadata = {
                "tool": "TOOL-003",
                "status": tool_003_result.get("status"),
                "reason": tool_003_result.get("reason"),
            }

    return {
        "play_id":                  play_id,
        "state":                    "draft",
        "scope":                    scope,
        "segment":                  None if scope == "account_specific" else action.get("target"),
        "account_id":               brain_row.get("account_id") if scope == "account_specific" else None,
        "name":                     _name_for_play(action, writer_agent_id),
        "hypothesis":               _hypothesis_from_action(action),
        "target_definition":        _target_definition_from_action(action, brain_row, scope),
        "suggested_cadence":        suggested_cadence,
        "success_criteria":         success_criteria,
        "originating_proposal_id":  brain_row.get("proposal_id"),
        "originating_analysis_id":  brain_row.get("analysis_id"),
        "writer_agent_id":          writer_agent_id,
        "originating_action_type":  action.get("action_type"),
        "originating_lever":        action.get("lever"),
        "brain_confidence":         action.get("confidence"),
        "supporting_source_indices": supporting_source_ids,
        "tool_003_metadata":        tool_003_metadata,
        "created_at":               now,
        # State-machine slots — empty in draft, populated as humans transition
        "picked_up_by_user_id":     None,
        "picked_up_at":             None,
        "edits_during_review":      None,
        "slm_approver_user_id":     None,
        "revops_approver_user_id":  None,
        "activated_at":             None,
        "retired_at":               None,
        "retirement_reason":        None,
    }


# ─────────────────────────────────────────────────────────────────────
# Entry point
# ─────────────────────────────────────────────────────────────────────

def write_drafts_from_brain_row(
    brain_row: dict,
    log_path: Path | str = DEFAULT_LOG_PATH,
    enrich_with_tool_003: bool = True,
) -> list[dict]:
    """Scan brain_row.proposed_actions for play-shaped actions, build
    SalesPlayLibrary drafts, append to JSONL log, return what was written.

    Each play-shaped action is enriched via TOOL-003 (Sales Play Composer)
    by default. Enrichment is capped at MAX_TOOL_003_CALLS_PER_INVOCATION to
    bound the per-brain-call cost; remaining drafts fall back to placeholder
    cadence + criteria.

    Idempotency note: this writer is invocation-scoped — calling it twice
    on the same brain_row writes two sets of drafts (with different play_ids
    but the same originating_proposal_id). Callers that want idempotency
    should check originating_proposal_id before re-invoking. For the
    prototype's eval harness this is fine because each fixture run produces
    one brain_row and we call the writer once.
    """
    actions = brain_row.get("proposed_actions", []) or []
    drafts: list[dict] = []
    enriched_count = 0
    for action in actions:
        if not isinstance(action, dict):
            continue
        if action.get("action_type") not in PLAY_SHAPED_ACTIONS:
            continue
        # Cap enrichment: first N drafts get TOOL-003, the rest get placeholders.
        # Defensive guard against a single brain run producing many plays and
        # blowing through Haiku budget unexpectedly.
        do_enrich = enrich_with_tool_003 and (enriched_count < MAX_TOOL_003_CALLS_PER_INVOCATION)
        draft = build_draft_record(action, brain_row, enrich_with_tool_003=do_enrich)
        if do_enrich and draft.get("tool_003_metadata", {}).get("status") == "ok":
            enriched_count += 1
        drafts.append(draft)

    if drafts:
        log_path = Path(log_path)
        log_path.parent.mkdir(parents=True, exist_ok=True)
        with log_path.open("a") as f:
            for draft in drafts:
                f.write(json.dumps(draft, default=str) + "\n")

    return drafts


def read_drafts(
    log_path: Path | str = DEFAULT_LOG_PATH,
    state: str | None = None,
    writer_agent_id: str | None = None,
    account_id: str | None = None,
) -> list[dict]:
    """Read draft records from the log, optionally filtered."""
    log_path = Path(log_path)
    if not log_path.exists():
        return []
    rows: list[dict] = []
    with log_path.open() as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            row = json.loads(line)
            if state is not None and row.get("state") != state:
                continue
            if writer_agent_id is not None and row.get("writer_agent_id") != writer_agent_id:
                continue
            if account_id is not None and row.get("account_id") != account_id:
                continue
            rows.append(row)
    return rows


# ─────────────────────────────────────────────────────────────────────
# CLI: inspect the library
# ─────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(
        description="Inspect the SalesPlayLibrary draft log."
    )
    parser.add_argument("--log", default=str(DEFAULT_LOG_PATH))
    parser.add_argument("--state", default=None,
                        help="Filter by state (draft / under_review / active / retired)")
    parser.add_argument("--writer", default=None,
                        help="Filter by writer_agent_id (AGT-901 / AGT-902)")
    parser.add_argument("--account", default=None,
                        help="Filter by account_id")
    parser.add_argument("--summary", action="store_true",
                        help="Print summary stats only")
    args = parser.parse_args()

    rows = read_drafts(args.log, state=args.state,
                       writer_agent_id=args.writer, account_id=args.account)

    if args.summary or not rows:
        print(f"SalesPlayLibrary: {len(rows)} rows matching filters")
        if rows:
            states: dict[str, int] = {}
            writers: dict[str, int] = {}
            for r in rows:
                states[r["state"]] = states.get(r["state"], 0) + 1
                writers[r["writer_agent_id"]] = writers.get(r["writer_agent_id"], 0) + 1
            print(f"  by state:  {states}")
            print(f"  by writer: {writers}")
    else:
        for r in rows:
            print(f"{r['play_id'][:8]} {r['state']:14s} {r['writer_agent_id']:8s} {r['scope']:18s} {r['name']}")
