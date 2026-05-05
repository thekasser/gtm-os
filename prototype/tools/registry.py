"""Tier 3 tool registry — maps tool names to handlers + Anthropic tool definitions.

Adding a new tool: register its definition + handler here. AGT-902's tool-use
loop reads from this registry.

The brain sees TOOL_DEFINITIONS in each API call. When it requests a tool, the
loop dispatches via TOOL_HANDLERS using the tool name.

Tools have a special parameter `_view`: when present, the corresponding handler
gets the brain-ready view (with full corpus data) injected at dispatch time. This
keeps the brain's tool_use input lightweight (just account_id + parameters)
while still giving the tool access to the data it needs.
"""

from __future__ import annotations

from typing import Callable

from tools.tool_003 import tool_003_handler, TOOL_003_DEFINITION
from tools.tool_004 import tool_004_handler, TOOL_004_DEFINITION
from tools.tool_008 import tool_008_handler, TOOL_008_DEFINITION
from tools.tool_010 import tool_010_handler, TOOL_010_DEFINITION


# Anthropic tool definitions (what the brain sees)
# Note: TOOL-003 is registered but NOT exposed to the brain via TOOL_DEFINITIONS.
# It's invoked by the SalesPlayLibrary writer, not as a brain tool_use call.
# Brains shouldn't draft plays — they propose, the writer enriches, humans
# co-define. Adding TOOL-003 to TOOL_DEFINITIONS would let the brain draft
# cadences directly, which conflates the layers.
TOOL_DEFINITIONS: list[dict] = [
    TOOL_004_DEFINITION,
    TOOL_008_DEFINITION,
    TOOL_010_DEFINITION,
]


# Handlers (what executes when the brain — or the writer — requests a tool)
TOOL_HANDLERS: dict[str, Callable[[dict], dict]] = {
    "tool_003_sales_play_composer": tool_003_handler,
    "tool_004_consumption_forecast": tool_004_handler,
    "tool_008_product_adoption_pattern": tool_008_handler,
    "tool_010_champion_movement_detector": tool_010_handler,
}


def _load_account_corpus(account_id: str, source=None) -> dict | None:
    """Load per-account corpus, preferring the BrainViewSource seam.

    If `source` is provided, route through source.load_account_corpus.
    Otherwise fall back to direct file IO from synth/corpus/ — legacy
    behavior for backwards compatibility with older callers.
    Returns None if the account cannot be found.
    """
    if source is not None:
        try:
            return source.load_account_corpus(account_id)
        except (FileNotFoundError, KeyError):
            return None

    # Legacy path
    from pathlib import Path
    import json as _json
    corpus_dir = Path(__file__).parent.parent.parent / "synth" / "corpus"
    corpus_path = corpus_dir / f"{account_id}.json"
    if not corpus_path.exists():
        for p in corpus_dir.glob("*.json"):
            if p.stem == account_id:
                corpus_path = p
                break
    if not corpus_path.exists():
        return None
    with corpus_path.open() as f:
        return _json.load(f)


def dispatch_tool(name: str, tool_input: dict, view: dict, source=None) -> dict:
    """Execute a tool by name. Injects the brain-ready view as input where needed.

    For TOOL-004 + TOOL-008, we automatically populate the tool's input from
    the per-account corpus. The corpus is loaded via the BrainViewSource if
    `source` is provided (the prototype/corporate seam) or via direct file IO
    as a legacy fallback.
    """
    handler = TOOL_HANDLERS.get(name)
    if handler is None:
        return {
            "tool_name": name,
            "status": "error",
            "reason": f"no handler registered for tool '{name}'",
        }

    # Per-tool input augmentation
    if name == "tool_010_champion_movement_detector":
        from datetime import datetime, timedelta, timezone
        account_id = tool_input.get("account_id") or view.get("account_id")
        corpus_data = _load_account_corpus(account_id, source=source)
        if corpus_data is None:
            return {
                "tool_name": name,
                "status": "error",
                "reason": f"corpus file not found for account_id={account_id}",
            }

        account = corpus_data.get("account", {})
        conv_log = corpus_data.get("conversation_intelligence_log", []) or []

        # Snapshot date — corpus generation moment
        contract_start = corpus_data.get("account", {}).get("contract_start_date")
        contract_age_days = corpus_data.get("account", {}).get("contract_age_days_at_corpus_gen", 0) or 0
        snapshot_iso = None
        if contract_start:
            try:
                cs = datetime.fromisoformat(contract_start.replace("Z","")).replace(tzinfo=timezone.utc)
                snapshot_dt = cs + timedelta(days=int(contract_age_days))
                snapshot_iso = snapshot_dt.isoformat()
            except Exception:
                snapshot_iso = None
        if snapshot_iso is None:
            snapshot_iso = datetime.now(timezone.utc).isoformat()
        snapshot_dt = datetime.fromisoformat(snapshot_iso.replace("Z","")) if "Z" in snapshot_iso else datetime.fromisoformat(snapshot_iso)
        if snapshot_dt.tzinfo is None:
            snapshot_dt = snapshot_dt.replace(tzinfo=timezone.utc)

        # Synthesize champion roster + attendance signals from conv_intel.
        # The synth corpus doesn't track per-contact attendance, so we
        # derive it: there's one inferred primary champion per account,
        # and "attendance" = call_count over a rolling window where calls
        # happen with call_owner_role in {AE, CSM, AM} (champion presumed
        # attending since the call was held with their cadence).
        # When archetype.conversation.champion_present is False or the
        # account is post-departure, attendance dwindles per the
        # synthetic timeline.
        from datetime import datetime as _dt
        def _parse(s):
            try:
                return _dt.fromisoformat(s.replace("Z","+00:00")) if s else None
            except Exception:
                return None

        all_calls = sorted(
            [c for c in conv_log if c.get("call_date")],
            key=lambda c: c["call_date"],
        )
        # Attendance counts in trailing 30d / 90d
        last_30_cutoff = snapshot_dt - timedelta(days=30)
        last_90_cutoff = snapshot_dt - timedelta(days=90)
        t30 = sum(1 for c in all_calls if (_parse(c["call_date"]) or snapshot_dt) >= last_30_cutoff)
        t90 = sum(1 for c in all_calls if (_parse(c["call_date"]) or snapshot_dt) >= last_90_cutoff)
        last_call_dt = _parse(all_calls[-1]["call_date"]) if all_calls else None
        last_call_iso = last_call_dt.isoformat() if last_call_dt else None
        last_sentiment = (all_calls[-1].get("overall_sentiment") if all_calls else None)

        # Single inferred champion. The contact_id is fabricated for the
        # synth corpus; in production this comes from CRM / Contacts.
        import hashlib
        synthetic_contact_id = hashlib.sha256(
            (account_id + ":primary_champion").encode()
        ).hexdigest()[:8]
        synthetic_first_id_iso = (snapshot_dt - timedelta(days=int(contract_age_days))).isoformat()

        augmented_input = {
            "account_id": account_id,
            "snapshot_date": snapshot_iso,
            "tracked_champions": [{
                "contact_id": synthetic_contact_id,
                "contact_name": "(primary champion — inferred from conv intel)",
                "title_at_last_check": "VP RevOps (synthetic)",
                "company_at_last_check": account.get("company_name"),
                "champion_classification": "primary",
                "first_identified_as_champion_date": synthetic_first_id_iso,
                "last_engaged_at": last_call_iso,
            }],
            # Synth corpus has no LinkedIn / email-bounce signals — tool
            # degrades gracefully to internal-signal-only mode.
            "external_signals": {
                "linkedin_signals": [],
                "email_bounce_signals": [],
            },
            "internal_signals": {
                "conv_intelligence_attendance": [{
                    "contact_id": synthetic_contact_id,
                    "calls_attended_trailing_30d": t30,
                    "calls_attended_trailing_90d": t90,
                    "last_call_attendance_at": last_call_iso,
                    "last_call_sentiment": last_sentiment,
                }],
                "email_engagement": [],
            },
            "account_context": {
                "renewal_date": account.get("contract_end_date"),
                "current_health_tier": (corpus_data.get("summary") or {}).get("final_health_tier"),
                "open_opportunities_count": 0,
            },
        }
        return handler(augmented_input)

    if name == "tool_008_product_adoption_pattern":
        account_id = tool_input.get("account_id") or view.get("account_id")
        corpus_data = _load_account_corpus(account_id, source=source)
        if corpus_data is None:
            return {
                "tool_name": name,
                "status": "error",
                "reason": f"corpus file not found for account_id={account_id}",
            }
        feature_engagement = corpus_data.get("feature_engagement")
        if not feature_engagement:
            return {
                "tool_name": name,
                "status": "error",
                "reason": "corpus has no feature_engagement block — regenerate corpus",
            }
        account = corpus_data.get("account", {})
        augmented_input = {
            "account_id": account_id,
            "feature_engagement_telemetry": feature_engagement,
            "account_context": {
                "contract_start_date": account.get("contract_start_date"),
                "active_seats": account.get("licensed_seats"),
                "licensed_seats": account.get("licensed_seats"),
                "primary_use_case": account.get("vertical"),
            },
            # No cohort baseline in synth corpus — tool degrades to data_completeness="medium"
            "comparison_baseline": None,
        }
        return handler(augmented_input)

    if name == "tool_004_consumption_forecast":
        # The brain-ready view's monthly_aggregates is lossy — TOOL-004 needs
        # daily granularity. Re-read full per-account corpus through the
        # source seam (or legacy file IO if no source).
        account_id = tool_input.get("account_id") or view.get("account_id")
        corpus_data = _load_account_corpus(account_id, source=source)
        if corpus_data is None:
            return {
                "tool_name": name,
                "status": "error",
                "reason": f"corpus file not found for account_id={account_id}",
            }
        metering_history = corpus_data.get("usage_metering_log", [])

        # Pull commit + contract context from account
        account = corpus_data.get("account", {})
        commit_monthly = None
        if metering_history:
            cmt = metering_history[0].get("commit_units")
            if cmt:
                commit_monthly = cmt * 30  # commit_units in our corpus is daily

        augmented_input = {
            "account_id": account_id,
            "metering_history": metering_history,
            "context": {
                "commit_units_monthly": commit_monthly,
                "contract_start_date": account.get("contract_start_date"),
                "contract_end_date": account.get("contract_end_date"),
            },
            "forecast_horizon_days": tool_input.get("forecast_horizon_days", 60),
        }
        return handler(augmented_input)

    # Generic dispatch for tools that take input as-is
    return handler(tool_input)
