"""TOOL-004 Consumption Forecasting / Runway Predictor.

Per the TOOL-004 spec:
  - Numerical work in code (pattern detection, forecast, confidence intervals)
  - LLM characterization for pattern label and interpretation
  - Output is a structured forecast a brain can cite

The numerical forecaster uses simple but real time-series methods:
  - Linear regression over trailing 90d for slope/intercept
  - Log-linear regression for exponential test
  - Cliff detection via large step-change in differences
  - Seasonality test via autocorrelation
  - Confidence intervals from residual standard deviation

Production would use proper time-series libs (statsmodels, prophet, etc.).
For the prototype, hand-rolled is sufficient and dependency-free.
"""

from __future__ import annotations

import math
import os
import json
from datetime import datetime, timedelta
from anthropic import Anthropic


# ─────────────────────────────────────────────────────────────────────
# Numerical core (no LLM)
# ─────────────────────────────────────────────────────────────────────

def _linreg(xs: list[float], ys: list[float]) -> tuple[float, float, float]:
    """Returns (slope, intercept, r_squared) for ordinary least squares."""
    n = len(xs)
    if n < 2:
        return 0.0, ys[0] if ys else 0.0, 0.0
    mx = sum(xs) / n
    my = sum(ys) / n
    sxy = sum((x - mx) * (y - my) for x, y in zip(xs, ys))
    sxx = sum((x - mx) ** 2 for x in xs)
    if sxx == 0:
        return 0.0, my, 0.0
    slope = sxy / sxx
    intercept = my - slope * mx
    # R²
    syy = sum((y - my) ** 2 for y in ys)
    if syy == 0:
        r2 = 1.0 if all(y == my for y in ys) else 0.0
    else:
        ss_res = sum((y - (slope * x + intercept)) ** 2 for x, y in zip(xs, ys))
        r2 = 1.0 - (ss_res / syy)
    return slope, intercept, r2


def _residual_std(xs: list[float], ys: list[float], slope: float, intercept: float) -> float:
    if len(xs) < 2:
        return 0.0
    residuals = [y - (slope * x + intercept) for x, y in zip(xs, ys)]
    n = len(residuals)
    mean_res = sum(residuals) / n
    var = sum((r - mean_res) ** 2 for r in residuals) / max(1, n - 1)
    return math.sqrt(var)


def _detect_cliff(daily_units: list[float]) -> tuple[bool, int | None, float]:
    """Cliff = large step-change in level. Returns (detected, day_index, magnitude_pct)."""
    n = len(daily_units)
    if n < 14:
        return False, None, 0.0
    # Compare halves of a sliding window
    best_step = 0.0
    best_idx = None
    for i in range(7, n - 7):
        before = sum(daily_units[max(0, i - 7):i]) / 7
        after = sum(daily_units[i:min(n, i + 7)]) / 7
        if before == 0:
            continue
        step_pct = (after - before) / abs(before)
        if abs(step_pct) > abs(best_step):
            best_step = step_pct
            best_idx = i
    # Cliff detected if step >= 50% in either direction
    if abs(best_step) >= 0.50:
        return True, best_idx, best_step
    return False, None, 0.0


def _detect_seasonality(daily_units: list[float]) -> tuple[bool, int | None]:
    """Crude seasonality test via autocorrelation at common periods."""
    n = len(daily_units)
    if n < 60:
        return False, None
    # Test periods of ~30, ~60, ~90 days
    best_corr = 0.0
    best_period = None
    for period in (30, 60, 90):
        if n < 2 * period:
            continue
        # Autocorrelation at this lag
        x = daily_units[:n - period]
        y = daily_units[period:]
        if not x or not y:
            continue
        mx = sum(x) / len(x)
        my = sum(y) / len(y)
        num = sum((a - mx) * (b - my) for a, b in zip(x, y))
        denx = math.sqrt(sum((a - mx) ** 2 for a in x))
        deny = math.sqrt(sum((b - my) ** 2 for b in y))
        if denx == 0 or deny == 0:
            continue
        corr = num / (denx * deny)
        if corr > best_corr:
            best_corr = corr
            best_period = period
    if best_corr > 0.55:
        return True, best_period
    return False, None


def _classify_pattern(daily_units: list[float]) -> dict:
    """Classify the trend pattern from a daily-units series. Returns numerical
    facts for the LLM to characterize, NOT a final label."""
    n = len(daily_units)
    if n < 14:
        return {
            "pattern_hint": "insufficient_data",
            "slope_units_per_day": 0.0,
            "linear_r2": 0.0,
            "log_linear_r2": 0.0,
            "cliff_detected": False,
            "seasonality_detected": False,
        }

    xs = list(range(n))
    slope, _intercept, r2 = _linreg(xs, daily_units)

    # Log-linear (test for exponential growth — only on positive series)
    log_r2 = 0.0
    if all(y > 0 for y in daily_units):
        log_ys = [math.log(y) for y in daily_units]
        _, _, log_r2 = _linreg(xs, log_ys)

    cliff_detected, cliff_idx, cliff_magnitude = _detect_cliff(daily_units)
    seasonality_detected, seasonality_period = _detect_seasonality(daily_units)

    # Volatility: coefficient of variation
    mean = sum(daily_units) / n
    sd = _residual_std(xs, daily_units, slope, _intercept)
    cv = sd / mean if mean > 0 else 0.0

    return {
        "pattern_hint": "to_be_characterized_by_llm",
        "n_days": n,
        "mean_daily_units": round(mean, 2),
        "slope_units_per_day": round(slope, 4),
        "linear_r2": round(r2, 3),
        "log_linear_r2": round(log_r2, 3),
        "coefficient_of_variation": round(cv, 3),
        "cliff_detected": cliff_detected,
        "cliff_event_day_index": cliff_idx,
        "cliff_magnitude_pct": round(cliff_magnitude, 3) if cliff_detected else None,
        "seasonality_detected": seasonality_detected,
        "seasonality_period_days": seasonality_period if seasonality_detected else None,
    }


def _forecast_overage_date(
    daily_units: list[float],
    slope: float,
    intercept: float,
    residual_sd: float,
    commit_daily: float,
    horizon_days: int,
) -> dict:
    """Project when daily usage will exceed daily commit. Returns timing + interval."""
    n = len(daily_units)
    if commit_daily <= 0:
        return {
            "predicted_overage": False,
            "predicted_overage_day_offset": None,
            "rationale": "no commit set; pure pay-as-you-go pricing",
        }

    # Already in overage territory?
    recent_mean = sum(daily_units[-7:]) / 7 if n >= 7 else daily_units[-1]
    already_over = recent_mean > commit_daily

    # Forecast: project linearly forward
    future_xs = list(range(n, n + horizon_days))
    forecasts = [slope * x + intercept for x in future_xs]

    # Find first day where forecast exceeds commit_daily
    overage_day_offset = None
    for i, f in enumerate(forecasts):
        if f > commit_daily:
            overage_day_offset = i
            break

    return {
        "predicted_overage": overage_day_offset is not None or already_over,
        "predicted_overage_day_offset": overage_day_offset if not already_over else 0,
        "currently_in_overage": already_over,
        "forecast_horizon_days": horizon_days,
        "forecast_mean_at_horizon": round(forecasts[-1], 2) if forecasts else None,
        "forecast_low_at_horizon": round(forecasts[-1] - 1.96 * residual_sd, 2) if forecasts else None,
        "forecast_high_at_horizon": round(forecasts[-1] + 1.96 * residual_sd, 2) if forecasts else None,
        "commit_daily_units": commit_daily,
        "recent_7d_mean_daily_units": round(recent_mean, 2),
    }


# ─────────────────────────────────────────────────────────────────────
# LLM characterization — interpret the numerical output
# ─────────────────────────────────────────────────────────────────────

def _characterize_via_llm(numerical_facts: dict, forecast_facts: dict,
                          context: dict) -> dict:
    """Send numerical facts to Haiku for pattern label + interpretation."""

    prompt = f"""You are TOOL-004 (Consumption Forecasting). Your job: characterize the pre-computed numerical facts below into a pattern label and a 1-2 sentence interpretation.

NUMERICAL FACTS (computed deterministically — do not invent values):
{json.dumps(numerical_facts, indent=2)}

FORECAST FACTS (linear projection — also deterministic):
{json.dumps(forecast_facts, indent=2)}

CONTEXT:
{json.dumps(context, indent=2)}

Classify the primary pattern as ONE of: linear, exponential, seasonal, cliff, flat.

Decision rules (apply in order):
- If cliff_detected is true → pattern = "cliff" (whether up or down)
- Else if seasonality_detected is true → "seasonal"
- Else if log_linear_r2 > linear_r2 + 0.1 AND log_linear_r2 > 0.6 AND slope_units_per_day > 0 → "exponential"
- Else if abs(slope_units_per_day) is large relative to mean (slope * 90 > 0.2 * mean) AND linear_r2 > 0.5 → "linear"
- Else → "flat"

Output JSON only, schema:
{{
  "primary_pattern": "linear | exponential | seasonal | cliff | flat",
  "is_likely_real_expansion": true | false,
  "is_likely_one_time_spike": true | false,
  "is_likely_seasonal_recurrence": true | false,
  "rationale": "1-2 sentences grounded in the numerical facts above"
}}"""

    client = Anthropic()
    model = os.environ.get("TOOL_004_MODEL", "claude-haiku-4-5-20251001")
    response = client.messages.create(
        model=model,
        max_tokens=600,
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
# Entry point — what AGT-902 calls
# ─────────────────────────────────────────────────────────────────────

def tool_004_handler(input_dict: dict) -> dict:
    """Main entry. Input matches the TOOL-004 spec input schema; returns the
    structured output the brain consumes."""
    metering_history = input_dict.get("metering_history", [])
    if not metering_history or len(metering_history) < 14:
        return {
            "tool_name": "TOOL-004",
            "status": "insufficient_data",
            "reason": f"need >= 14 days of history; got {len(metering_history)}",
        }

    # Filter to most recent 180 days max
    metering_history = metering_history[-180:]
    daily_units = [float(r.get("units_consumed", 0)) for r in metering_history]

    # Numerical pattern classification
    numerical_facts = _classify_pattern(daily_units)

    # Forecast (use commit_units from input or first row of history)
    commit_daily = 0.0
    if input_dict.get("context", {}).get("commit_units_monthly"):
        commit_daily = input_dict["context"]["commit_units_monthly"] / 30.0
    elif metering_history and metering_history[0].get("commit_units"):
        commit_daily = float(metering_history[0]["commit_units"])

    xs = list(range(len(daily_units)))
    slope, intercept, _ = _linreg(xs, daily_units)
    residual_sd = _residual_std(xs, daily_units, slope, intercept)
    horizon = input_dict.get("forecast_horizon_days", 60)
    forecast_facts = _forecast_overage_date(
        daily_units, slope, intercept, residual_sd, commit_daily, horizon,
    )

    # LLM characterization
    context = input_dict.get("context", {})
    try:
        characterization = _characterize_via_llm(numerical_facts, forecast_facts, context)
    except Exception as e:
        return {
            "tool_name": "TOOL-004",
            "status": "llm_error",
            "reason": str(e),
            "numerical_facts": numerical_facts,
            "forecast_facts": forecast_facts,
        }

    return {
        "tool_name": "TOOL-004",
        "status": "ok",
        "primary_pattern": characterization.get("primary_pattern"),
        "interpretation": characterization.get("rationale"),
        "is_likely_real_expansion": characterization.get("is_likely_real_expansion"),
        "is_likely_one_time_spike": characterization.get("is_likely_one_time_spike"),
        "is_likely_seasonal_recurrence": characterization.get("is_likely_seasonal_recurrence"),
        "forecast_summary": forecast_facts,
        "numerical_facts": numerical_facts,
        "_llm_metadata": characterization.get("_llm_metadata"),
    }


# ─────────────────────────────────────────────────────────────────────
# Anthropic tool definition — what AGT-902 sees
# ─────────────────────────────────────────────────────────────────────

TOOL_004_DEFINITION = {
    "name": "tool_004_consumption_forecast",
    "description": (
        "TOOL-004 Consumption Forecasting. Reads the account's UsageMeteringLog "
        "history, runs deterministic time-series analysis (linear/log-linear "
        "regression, cliff detection, autocorrelation seasonality test), and "
        "returns a structured forecast plus pattern characterization. Use this "
        "when answering 'is this real expansion or a spike?', 'when will overage "
        "hit?', or 'what's the consumption trajectory?'. Output is canonical and "
        "should be cited like a Tier 1 source."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "account_id": {
                "type": "string",
                "description": "Account UUID — used for logging only.",
            },
            "forecast_horizon_days": {
                "type": "integer",
                "description": "How far forward to project. Default 60. Max 180.",
                "default": 60,
            },
        },
        "required": ["account_id"],
    },
}
