"""TOOL-010 Champion Movement Detector.

Per the TOOL-010 spec — multi-signal fusion to classify champion contact
movement. Five movement types: left_company, role_changed_internal,
stopped_engaging, engagement_declining, no_movement_detected.

Hard rules (eval-enforced):
  - Any classification stronger than no_movement_detected requires at least
    one contributing_signal of strength >= moderate. Single weak signals
    never produce high confidence.
  - Privacy-disciplined: only signals already in OS or from approved
    enrichment. Tool itself does not invent signal sources.
  - Graceful degradation: when external signals (LinkedIn / email-bounce)
    are absent, tool reports external_signal_coverage="none" and degrades
    confidence accordingly. Internal signals (AGT-407 attendance, email
    engagement) alone can detect stopped_engaging reliably; cannot detect
    left_company with high confidence.

The deterministic core analyzes attendance trends + email-reply trends.
LLM characterization synthesizes the movement_type label + interventions.
"""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from anthropic import Anthropic


# ─────────────────────────────────────────────────────────────────────
# Signal-strength derivation (deterministic)
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


def _attendance_strength(att: dict, snapshot_date: datetime) -> dict:
    """Classify attendance signal strength for a single contact.

    Returns {strength: weak|moderate|strong, detail: str, last_call_age_days: int|None}.
    Spec: stopped_engaging requires moderate-or-stronger attendance signal.
    """
    last_at = _parse_iso(att.get("last_call_attendance_at"))
    last_age_days = None
    if last_at:
        last_age_days = (snapshot_date - last_at).days

    t30 = att.get("calls_attended_trailing_30d", 0) or 0
    t90 = att.get("calls_attended_trailing_90d", 0) or 0

    # Strong: zero attendance in 30d AND attended >=2 calls in 90d (i.e., abrupt
    # cessation). Moderate: zero attendance in 30d but rare attendance overall,
    # OR last call was <0 sentiment with no follow-on activity.
    # Weak: low attendance without other corroborating signals.
    if t30 == 0 and t90 >= 2:
        return {
            "signal_strength": "strong",
            "signal_detail": (
                f"Champion attended {t90} calls in trailing 90d but zero in trailing 30d "
                f"(last attendance {last_age_days}d ago). Abrupt cessation."
            ),
        }
    if t30 == 0 and last_age_days and last_age_days >= 60:
        return {
            "signal_strength": "moderate",
            "signal_detail": (
                f"No attendance in trailing 30d; last call {last_age_days}d ago. "
                f"Sustained absence beyond normal cadence."
            ),
        }
    if t30 < t90 / 4:
        return {
            "signal_strength": "moderate",
            "signal_detail": (
                f"Attendance frequency dropped: {t30} in trailing 30d vs ~{t90/3:.1f} "
                f"per-month average over 90d (declining trend)."
            ),
        }
    if t30 == 0:
        return {
            "signal_strength": "weak",
            "signal_detail": (
                f"Zero attendance in trailing 30d, but trailing 90d sample is small ({t90}); "
                f"insufficient to distinguish from normal cadence gap."
            ),
        }
    return None


def _email_strength(eng: dict, snapshot_date: datetime) -> dict | None:
    last_reply = _parse_iso(eng.get("last_reply_at"))
    reply_age_days = None
    if last_reply:
        reply_age_days = (snapshot_date - last_reply).days
    t30_replies = eng.get("trailing_30d_reply_count", 0) or 0

    if reply_age_days is not None and reply_age_days >= 45 and t30_replies == 0:
        return {
            "signal_strength": "moderate",
            "signal_detail": (
                f"No email reply in trailing 30d; last reply {reply_age_days}d ago."
            ),
        }
    if t30_replies == 0:
        return {
            "signal_strength": "weak",
            "signal_detail": (
                f"No email reply in trailing 30d (last_reply_at={eng.get('last_reply_at') or 'never'})."
            ),
        }
    return None


def _bounce_strength(bounce: dict) -> dict:
    """Hard-bounce on champion email = strong signal of left_company."""
    btype = bounce.get("bounce_type", "")
    consec = bounce.get("consecutive_bounce_count", 0) or 0
    if btype == "hard" and consec >= 2:
        return {
            "signal_strength": "strong",
            "signal_detail": (
                f"{consec} consecutive hard bounces on champion email — strong "
                f"left_company indicator."
            ),
        }
    if btype == "hard" and consec == 1:
        return {
            "signal_strength": "moderate",
            "signal_detail": "Single hard bounce on champion email; verify with second send.",
        }
    if btype == "soft" and consec >= 3:
        return {
            "signal_strength": "moderate",
            "signal_detail": f"{consec} consecutive soft bounces — possible mailbox-full or vacation.",
        }
    return None


def _linkedin_strength(li: dict) -> dict | None:
    company_change = li.get("company_change_detected")
    title_change = li.get("title_change_detected")
    if company_change:
        return {
            "signal_strength": "strong",
            "signal_detail": "LinkedIn detected company change — definitive left_company indicator.",
        }
    if title_change:
        return {
            "signal_strength": "moderate",
            "signal_detail": "LinkedIn detected title change at same company — role_changed_internal candidate.",
        }
    return None


# ─────────────────────────────────────────────────────────────────────
# Per-champion signal aggregation
# ─────────────────────────────────────────────────────────────────────

def _aggregate_signals_for_champion(contact_id: str, input_dict: dict,
                                     snapshot_date: datetime) -> list[dict]:
    """Collect all signals for one contact_id across the input. Returns a list
    of {signal_type, signal_detail, signal_strength} entries."""
    signals: list[dict] = []

    # Internal — attendance
    for att in (input_dict.get("internal_signals", {}) or {}).get("conv_intelligence_attendance", []) or []:
        if att.get("contact_id") != contact_id:
            continue
        s = _attendance_strength(att, snapshot_date)
        if s:
            signals.append({"signal_type": "conv_intel_attendance", **s})

    # Internal — email engagement
    for eng in (input_dict.get("internal_signals", {}) or {}).get("email_engagement", []) or []:
        if eng.get("contact_id") != contact_id:
            continue
        s = _email_strength(eng, snapshot_date)
        if s:
            signals.append({"signal_type": "email_engagement", **s})

    # External — LinkedIn
    for li in (input_dict.get("external_signals", {}) or {}).get("linkedin_signals", []) or []:
        if li.get("contact_id") != contact_id:
            continue
        s = _linkedin_strength(li)
        if s:
            signals.append({"signal_type": "linkedin", **s})

    # External — email bounces
    for bounce in (input_dict.get("external_signals", {}) or {}).get("email_bounce_signals", []) or []:
        if bounce.get("contact_id") != contact_id:
            continue
        s = _bounce_strength(bounce)
        if s:
            signals.append({"signal_type": "email_bounce", **s})

    return signals


def _signal_coverage(input_dict: dict) -> tuple[str, str]:
    """Determine external_signal_coverage + internal_signal_coverage."""
    ext = input_dict.get("external_signals", {}) or {}
    has_li = bool(ext.get("linkedin_signals"))
    has_bounce = bool(ext.get("email_bounce_signals"))
    if has_li and has_bounce:
        external = "full"
    elif has_li or has_bounce:
        external = "partial"
    else:
        external = "none"

    intern = input_dict.get("internal_signals", {}) or {}
    has_att = bool(intern.get("conv_intelligence_attendance"))
    has_email = bool(intern.get("email_engagement"))
    if has_att and has_email:
        internal = "full"
    elif has_att or has_email:
        internal = "partial"
    else:
        internal = "none"

    return external, internal


# ─────────────────────────────────────────────────────────────────────
# LLM characterization
# ─────────────────────────────────────────────────────────────────────

def _classify_via_llm(input_dict: dict, per_champion_signals: list[dict],
                      external_coverage: str, internal_coverage: str) -> dict:
    """Send pre-computed signals to Haiku for movement_type + intervention
    classification. Hard rules baked into the prompt."""

    prompt = f"""You are TOOL-010 Champion Movement Detector. Your job: classify champion-contact movement based on multi-signal fusion. Output JSON only.

ACCOUNT CONTEXT:
{json.dumps(input_dict.get("account_context", {}), indent=2)}

TRACKED CHAMPIONS:
{json.dumps(input_dict.get("tracked_champions", []), indent=2)}

PER-CHAMPION SIGNALS (deterministically derived — do not invent values):
{json.dumps(per_champion_signals, indent=2)}

EXTERNAL SIGNAL COVERAGE: {external_coverage}
INTERNAL SIGNAL COVERAGE: {internal_coverage}

CLASSIFY each champion into one of:
  - left_company: contact left the company (strongest evidence: hard email bounce + LinkedIn company change)
  - role_changed_internal: contact still at company but in different role (LinkedIn title change without company change)
  - stopped_engaging: still at company, still in role, but no longer attending calls or replying (sustained internal-signal evidence)
  - engagement_declining: reduced but not zero engagement (declining trend in attendance/replies)
  - no_movement_detected: signals are weak or inconclusive — default state

HARD RULES:
1. Any classification stronger than no_movement_detected MUST have at least one contributing_signal with strength="moderate" or "strong". If you only have weak signals, classify as no_movement_detected with confidence="low".
2. left_company with confidence="high" REQUIRES at least one strong external signal (hard bounce ≥2 OR LinkedIn company change). Without external signals, max confidence for left_company is "medium".
3. When external_signal_coverage is "none", left_company classifications cannot be high-confidence — they degrade to "medium" or to stopped_engaging if internal signals dominate.
4. Recommended interventions must be from: identify_new_champion, executive_sponsor_outreach, escalate_to_slm, introduce_csm_handoff, reconfirm_renewal_path, no_action_needed.

Output JSON only (single object, no preamble):
{{
  "champion_movements": [
    {{
      "contact_id": "<uuid from input>",
      "movement_type": "<one of the 5 enums>",
      "confidence": "high|medium|low",
      "earliest_signal_at": "<ISO date or null>",
      "contributing_signals": [<copy from per-champion signals that you used>],
      "implications": {{
        "champion_replacement_needed": true|false,
        "renewal_risk_uplift": "none|low|medium|high",
        "deal_risk_uplift": "none|low|medium|high"
      }},
      "recommended_interventions": [
        {{"intervention_type": "<enum>", "urgency": "high|medium|low", "rationale": "<short>"}}
      ]
    }}
  ],
  "account_level_summary": {{
    "primary_champion_status": "stable|at_risk|lost",
    "champion_redundancy": "high|medium|single_threaded",
    "overall_movement_signal": "stable|early_warning|active_concern|critical"
  }},
  "ungrounded_assumptions": ["<each guess where data is missing>"]
}}"""

    client = Anthropic()
    model = os.environ.get("TOOL_010_MODEL", "claude-haiku-4-5-20251001")
    response = client.messages.create(
        model=model,
        max_tokens=2000,
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

def tool_010_handler(input_dict: dict) -> dict:
    """Main entry. Input matches TOOL-010 spec input schema; returns the
    structured output the brain consumes.
    """
    champions = input_dict.get("tracked_champions", []) or []
    if not champions:
        return {
            "tool_name": "TOOL-010",
            "status": "insufficient_data",
            "reason": "no tracked_champions provided",
        }

    # Snapshot date — derived from input or now
    snapshot_str = input_dict.get("snapshot_date") or input_dict.get("account_context", {}).get("renewal_date")
    snapshot_date = _parse_iso(snapshot_str) or datetime.now(timezone.utc)

    # Aggregate signals per champion deterministically
    per_champion_signals = []
    for champ in champions:
        cid = champ.get("contact_id")
        signals = _aggregate_signals_for_champion(cid, input_dict, snapshot_date)
        per_champion_signals.append({
            "contact_id": cid,
            "contact_name": champ.get("contact_name"),
            "champion_classification": champ.get("champion_classification"),
            "signals": signals,
        })

    external_coverage, internal_coverage = _signal_coverage(input_dict)

    # LLM classification
    try:
        classified = _classify_via_llm(
            input_dict, per_champion_signals, external_coverage, internal_coverage,
        )
    except Exception as e:
        return {
            "tool_name": "TOOL-010",
            "status": "llm_error",
            "reason": str(e),
            "deterministic_signals": per_champion_signals,
            "data_quality": {
                "external_signal_coverage": external_coverage,
                "internal_signal_coverage": internal_coverage,
            },
        }

    # Determine overall data quality
    if external_coverage == "full" and internal_coverage == "full":
        overall_quality = "high"
    elif external_coverage in ("full", "partial") or internal_coverage == "full":
        overall_quality = "medium"
    else:
        overall_quality = "low"

    return {
        "tool_name": "TOOL-010",
        "status": "ok",
        "champion_movements": classified.get("champion_movements", []),
        "account_level_summary": classified.get("account_level_summary"),
        "data_quality": {
            "external_signal_coverage": external_coverage,
            "internal_signal_coverage": internal_coverage,
            "overall_quality": overall_quality,
        },
        "ungrounded_assumptions": classified.get("ungrounded_assumptions", []),
        "deterministic_signals": per_champion_signals,
        "_llm_metadata": classified.get("_llm_metadata"),
    }


# ─────────────────────────────────────────────────────────────────────
# Anthropic tool definition — what the brain sees
# ─────────────────────────────────────────────────────────────────────

TOOL_010_DEFINITION = {
    "name": "tool_010_champion_movement_detector",
    "description": (
        "TOOL-010 Champion Movement Detector. Given the account's tracked "
        "champions + multi-signal context (AGT-407 ConvIntelligence call "
        "attendance, email engagement, optional LinkedIn / email-bounce "
        "external signals), classifies each champion's movement: "
        "left_company / role_changed_internal / stopped_engaging / "
        "engagement_declining / no_movement_detected. Hard rule: any "
        "classification beyond 'no_movement_detected' requires at least one "
        "contributing signal of moderate-or-strong strength. Use this when "
        "diagnosing renewal risk for accounts with sentiment shift, attendance "
        "decline, or champion-name changes in conv intel."
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
