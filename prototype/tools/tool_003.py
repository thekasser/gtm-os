"""TOOL-003 Sales Play Composer.

Per the TOOL-003 spec — converts a brain's play hypothesis (justification +
target + lever) into a structured starting point: cadence steps + success
criteria. Output goes into a SalesPlayLibrary draft to replace the
`pending_human_codefinition` placeholders.

Hard rules from the spec:
  - Tool NEVER invents account-specific information (champion names,
    revenue figures, contact details). If hypothesis mentions "champion
    engagement", cadence may say "champion-engaged touchpoint" but
    cannot say "engage Sarah Chen".
  - When numbers must be guessed (target_meeting_rate, target_acv, etc.)
    confidence drops to "low" and ungrounded_assumptions is annotated.
  - Cadence stays in the lever's domain. AGT-302's cadence vocabulary —
    channels (email/linkedin/phone/in-app), step counts (5-12 typical),
    durations (14-45 days typical).

Not called by the brain directly. Called by the SalesPlayLibrary writer
when it converts a play-shaped proposed_action into a draft record.

Default model: Haiku. Per-call ~3K input + 1K output ≈ $0.005.
"""

from __future__ import annotations

import json
import os
from anthropic import Anthropic


# ─────────────────────────────────────────────────────────────────────
# LLM call — Haiku composes cadence + criteria from hypothesis
# ─────────────────────────────────────────────────────────────────────

def _compose_via_llm(input_dict: dict) -> dict:
    hypothesis = input_dict.get("play_hypothesis", "")
    scope = input_dict.get("scope", "unknown")
    target = input_dict.get("target_definition", {})
    signals = input_dict.get("originating_signals", [])
    lever = input_dict.get("lever_hint", "")
    writer_brain = input_dict.get("writer_brain", "")

    prompt = f"""You are TOOL-003 Sales Play Composer. Your job: convert a brain-drafted play hypothesis into a structured starting point that a RevOps reviewer can edit in `under_review` state.

PLAY HYPOTHESIS (the brain's justification — verbatim):
{hypothesis!r}

SCOPE: {scope}
TARGET: {json.dumps(target, default=str)}
LEVER (which Tier 1 service executes): {lever}
WRITER BRAIN: {writer_brain}
ORIGINATING SIGNALS: {json.dumps(signals, default=str)}

Compose a starting cadence + success criteria. Output JSON only with this exact shape:

{{
  "suggested_cadence": {{
    "channel_mix": ["email" | "linkedin" | "phone" | "in_app" | ...],
    "touch_count": <integer 4-12>,
    "duration_days": <integer 14-45>,
    "steps": [
      {{"step": 1, "channel": "email", "day": 0, "intent": "<short, e.g. 'open with consumption-overage observation'>"}},
      ...
    ]
  }},
  "success_criteria": {{
    "target_meeting_rate": <float 0-1, or null if cannot estimate>,
    "target_opp_create_rate": <float 0-1, or null>,
    "target_acv_uplift_pct": <float, or null>,
    "evaluation_window_days": <integer, default 90>,
    "rationale": "<1-2 sentences explaining the targets given the hypothesis>"
  }},
  "ungrounded_assumptions": ["<each assumption that's a guess rather than derived from the hypothesis>"],
  "confidence": "high" | "medium" | "low"
}}

HARD RULES (the human reviewer relies on these):
1. NEVER invent account-specific facts. The hypothesis is the only ground truth. If you don't have a champion's name from the hypothesis, don't write one.
2. If you guess a number (rate, percentage, ACV), include it in ungrounded_assumptions.
3. Use confidence="high" only when target rates are derivable from the hypothesis itself or the lever's documented norms. Default to "medium" or "low".
4. Keep cadence in the lever's vocabulary. AGT-302 cadences are 4-12 touches over 14-45 days. AGT-603 (QBR) is event-driven, not multi-touch.
5. Step intents are short imperatives ("validate cross-team adoption", "request integration owner intro"). Not full email copy."""

    client = Anthropic()
    model = os.environ.get("TOOL_003_MODEL", "claude-haiku-4-5-20251001")
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
# Entry point — what SalesPlayLibrary writer calls
# ─────────────────────────────────────────────────────────────────────

def tool_003_handler(input_dict: dict) -> dict:
    """Compose cadence + criteria for a draft play.

    Input shape (informal — the writer constructs this from the brain's
    proposed_action + brain_row context):
      play_hypothesis:        str (required)
      scope:                  "account_specific" | "segment"
      target_definition:      dict
      originating_signals:    list[dict] — sources_read entries that
                              support the hypothesis
      lever_hint:             str — Tier 1 service the play routes to
      writer_brain:           "AGT-901" | "AGT-902"

    Output matches the spec's output schema. On llm_error or
    insufficient_data, returns a status field; the SalesPlayLibrary writer
    falls back to its placeholder cadence/criteria.
    """
    if not input_dict.get("play_hypothesis"):
        return {
            "tool_name": "TOOL-003",
            "status": "insufficient_data",
            "reason": "play_hypothesis is required",
        }

    try:
        composed = _compose_via_llm(input_dict)
    except Exception as e:
        return {
            "tool_name": "TOOL-003",
            "status": "llm_error",
            "reason": str(e),
        }

    return {
        "tool_name": "TOOL-003",
        "status": "ok",
        "suggested_cadence": composed.get("suggested_cadence"),
        "success_criteria": composed.get("success_criteria"),
        "ungrounded_assumptions": composed.get("ungrounded_assumptions", []),
        "confidence": composed.get("confidence"),
        "_llm_metadata": composed.get("_llm_metadata"),
    }


# ─────────────────────────────────────────────────────────────────────
# Anthropic tool definition — only used if a brain ever calls TOOL-003
# directly. Currently TOOL-003 is invoked by the SalesPlayLibrary writer,
# not as a brain tool_use call. Definition included for consistency + future.
# ─────────────────────────────────────────────────────────────────────

TOOL_003_DEFINITION = {
    "name": "tool_003_sales_play_composer",
    "description": (
        "TOOL-003 Sales Play Composer. Given a play hypothesis (the brain's "
        "justification) plus target context, returns a structured starting "
        "cadence (channel mix, touch count, day-by-day steps) and success "
        "criteria (target rates, evaluation window). Output is a starting "
        "point for human co-definition in `under_review` — not a final play. "
        "Hard rule: never invents account-specific facts."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "play_hypothesis": {
                "type": "string",
                "description": "Brain's justification verbatim — the hypothesis the play tests.",
            },
            "scope": {
                "type": "string",
                "enum": ["account_specific", "segment"],
            },
            "lever_hint": {
                "type": "string",
                "description": "Tier 1 service that executes the play (e.g., AGT-302 / AGT-503 / AGT-603).",
            },
        },
        "required": ["play_hypothesis"],
    },
}
