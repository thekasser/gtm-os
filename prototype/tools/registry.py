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

from tools.tool_004 import tool_004_handler, TOOL_004_DEFINITION
from tools.tool_008 import tool_008_handler, TOOL_008_DEFINITION


# Anthropic tool definitions (what the brain sees)
TOOL_DEFINITIONS: list[dict] = [
    TOOL_004_DEFINITION,
    TOOL_008_DEFINITION,
]


# Handlers (what executes when the brain requests a tool)
TOOL_HANDLERS: dict[str, Callable[[dict], dict]] = {
    "tool_004_consumption_forecast": tool_004_handler,
    "tool_008_product_adoption_pattern": tool_008_handler,
}


def dispatch_tool(name: str, tool_input: dict, view: dict) -> dict:
    """Execute a tool by name. Injects the brain-ready view as input where needed.

    For TOOL-004, we automatically populate metering_history and context from
    the brain's per-account composite view, so the brain's tool_use call only
    needs to specify account_id + forecast_horizon_days.
    """
    handler = TOOL_HANDLERS.get(name)
    if handler is None:
        return {
            "tool_name": name,
            "status": "error",
            "reason": f"no handler registered for tool '{name}'",
        }

    # Per-tool input augmentation
    if name == "tool_008_product_adoption_pattern":
        from pathlib import Path
        import json as _json
        account_id = tool_input.get("account_id") or view.get("account_id")
        corpus_dir = Path(__file__).parent.parent.parent / "synth" / "corpus"
        corpus_path = corpus_dir / f"{account_id}.json"
        if not corpus_path.exists():
            return {
                "tool_name": name,
                "status": "error",
                "reason": f"corpus file not found for account_id={account_id}",
            }
        with corpus_path.open() as f:
            corpus_data = _json.load(f)
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
        usage_component = view.get("components", {}).get("usage_metering", {})
        # Reconstruct day-level metering_history from the view's monthly_aggregates
        # is lossy. The brain-ready view doesn't carry daily rows by design (size).
        # For the prototype, the tool re-reads the full corpus file via account_id.
        # Cleaner alternative — pass daily series in the view as a tool-specific
        # extra. But that bloats every brain call. Trade-off: tool re-reads.
        from pathlib import Path
        import json as _json
        account_id = tool_input.get("account_id") or view.get("account_id")
        corpus_dir = Path(__file__).parent.parent.parent / "synth" / "corpus"
        corpus_path = corpus_dir / f"{account_id}.json"
        if not corpus_path.exists():
            # Fallback: search by account_id (UUID)
            for p in corpus_dir.glob("*.json"):
                if p.stem == account_id:
                    corpus_path = p
                    break
        if not corpus_path.exists():
            return {
                "tool_name": name,
                "status": "error",
                "reason": f"corpus file not found for account_id={account_id}",
            }
        with corpus_path.open() as f:
            corpus_data = _json.load(f)
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
