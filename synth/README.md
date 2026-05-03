# synth — synthetic GTM-OS corpus generator

Generates internally-consistent synthetic accounts spanning eight archetypes,
producing time-series data across `UsageMeteringLog`, `CustomerHealthLog`,
and `PaymentEventLog` matching the production schema specs.

Used by the prototype to test brain agents, tools, and the eval harness
end-to-end without real customer data.

## What's here

| File | Lines | Purpose |
|---|---|---|
| `archetypes.py` | ~340 | 8 account archetypes + dataclasses defining their parameters |
| `usage.py` | ~110 | `UsageMeteringLog` time-series generator (linear / exponential / seasonal / cliff / flat patterns) |
| `health.py` | ~110 | `CustomerHealthLog` daily health-score generator with payment-modifier cap/floor |
| `payments.py` | ~110 | `PaymentEventLog` generator (clean current OR retry-and-escalation chain into overdue/failed/suspended) |
| `main.py` | ~190 | Orchestrator: generates account base + applies generators + writes JSON corpus |
| `conversations.py` | ~250 | LLM-generated `ConvIntelligence` call summaries via Claude API. Run after `main.py`. |
| `inspect_corpus.py` | ~50 | Spot-check: prints one example per archetype with summary stats |

## The 8 archetypes

| Key | Pattern | Expected outcome |
|---|---|---|
| `ideal_power_user` | linear growth, multi-team, champion engaged | renews_and_expands |
| `activating` | exponential growth from low baseline | activates_to_power_user |
| `surface_only_adopter` | flat usage, narrow features | at_risk_renewal |
| `champion_loss_decliner` | cliff drop at champion departure (day 210) | churn_risk_high |
| `expansion_ready` | sustained exponential, hitting overage | real_expansion |
| `spike_then_crash` | cliff up at day 180, recovery at 220 | not_real_expansion |
| `seasonal` | quarterly cycle, predictable | renews_stable |
| `stalled_onboarding` | flat near-zero usage | early_churn_risk |

## Quick start

### Step 1: Generate the structural corpus (no API needed)

```bash
cd /Users/connorkasser/gtm-os/synth
python3 main.py
```

Defaults: seed=42, generates 50 accounts → `synth/corpus/`. Numerical only — no LLM calls, no cost.

### Step 2: Add LLM-generated call summaries (requires Anthropic API key)

```bash
pip install anthropic                    # one-time
export ANTHROPIC_API_KEY=sk-ant-...      # one-time

python3 conversations.py --limit 3       # test on 3 accounts first (~$0.05)
python3 conversations.py                 # generate for all 50 accounts (~$1-3)
```

This appends a `conversation_intelligence_log` array to each corpus file with archetype-aware call summaries (sentiment trajectories, objections, next steps, competitor mentions). Calls match each archetype's `ConversationProfile` — e.g., a `champion_loss_decliner` produces calls before the departure day showing engaged champion, calls after showing absent champion + declining sentiment.

### Step 3: Verify

```bash
python3 inspect_corpus.py
```

## Custom runs

```bash
python3 main.py --seed 1234 --n 100 --out /tmp/big_corpus
python3 conversations.py --force                   # regenerate (re-spend tokens)
python3 conversations.py --limit 5                 # batch process
ANTHROPIC_MODEL=claude-sonnet-4-6 python3 conversations.py   # use Sonnet instead of default Haiku
```

## What you get

After running, `corpus/` contains:

- `<account_uuid>.json` — one file per account, with:
  - `account` — base record (segment, vertical, ARR, contract terms, etc.)
  - `archetype_key` — which archetype generated this account
  - `expected_outcome_label` — ground truth for eval
  - `usage_metering_log` — daily usage rows over the contract age
  - `customer_health_log` — daily health rows with tier + payment modifier
  - `payment_event_log` — invoice-cycle payment events
  - `conversation_intelligence_log` — call summaries (after running `conversations.py`)
  - `summary` — convenience aggregates (total consumed, final health, call counts, etc.)

- `ground_truth.json` — index mapping `account_id → archetype_key + expected_outcome_label`. This is what the eval harness uses to score brain output.

## Verification — does the data look right?

Spot-check by archetype:

```bash
# Count accounts per archetype
python3 -c "
import json
with open('corpus/ground_truth.json') as f: gt = json.load(f)
print(gt['archetype_distribution'])
"

# Inspect one account
python3 -c "
import json, glob
with open(sorted(glob.glob('corpus/*.json'))[0]) as f:
    a = json.load(f)
print(f\"Archetype: {a['archetype_key']}\")
print(f\"Company:   {a['account']['company_name']}\")
print(f\"Summary:   {a['summary']}\")
"
```

A `champion_loss_decliner` account should have:
- `summary.final_health_tier` = Yellow or Amber (not Green)
- `total_units_consumed` showing visible drop ~70% through the time series

A `expansion_ready` account should have:
- `summary.total_overage_units` > 0
- `summary.final_health_tier` = Green

A `stalled_onboarding` account should have:
- `summary.final_health_tier` = Red
- `summary.total_units_consumed` very low

## How to extend

**Add an archetype** → add a new entry in `ARCHETYPES` dict in `archetypes.py`, plus a weight in `DEFAULT_ARCHETYPE_WEIGHTS`. Generators pick it up automatically.

**Add a new dimension** (e.g., QBRLog or OnboardingLog) → write a new generator file in this dir, call it after `main.py` for structural data, or via API like `conversations.py` for LLM-generated content. The pattern is the same.

**Tune patterns** — edit archetype parameters. Re-run with the same seed to see deterministic deltas; change seed to explore robustness.

## Caveats — what synthetic data is and isn't

**This data is good enough for**:
- Prototype testing of brain agents and tools
- Eval harness fixture authoring with known ground truth
- Demo / interview / presentation scenarios
- Architectural validation that the read contracts work

**This data is NOT a substitute for**:
- Real production telemetry quirks (replay events, late arrivals, schema drift, multi-tenant noise)
- Long-tail customer behavior synthetic generators don't anticipate
- Cohort comparisons against real cohorts (synthetic-vs-synthetic cohort math is circular)

When porting to a corporate environment with real data: replace JSON file readers with database queries, keep everything else.

## Reproducibility

Same seed → same corpus. Always. If output differs across runs with the same seed, that's a bug in the generator. Default seed is 42; change it to explore variance.
