# prototype — AGT-902 Account Brain runtime

The first runnable Tier 2 brain in the GTM-OS prototype. Reads per-account
composite from `synth/corpus/`, calls Anthropic API, validates output, writes
a `BrainAnalysisLog` row.

This is a stub — small enough to read in 30 minutes, faithful to the AGT-902
spec on the contracts that matter (read-only on canonical data, source-trace
metadata, action taxonomy enforcement, staleness recognition).

## What's here

| File | Purpose |
|---|---|
| `agt902.py` | Brain runtime: extract brain-ready view from corpus, build prompt, call API, assemble BrainAnalysisLog row |
| `validation.py` | Output validators: schema, citations, action taxonomy, staleness disclosure, confidence calibration |
| `brain_analysis_log.py` | JSONL writer for the BrainAnalysisLog table (append-only) |
| `run_agt902.py` | CLI entry — runs on one or many corpus accounts |

## Quick start

Use `prototype/run.sh` — it auto-resolves the venv path regardless of where
you call it from:

```bash
# From the project root
prototype/run.sh --account 026a4a59

# From inside synth/
../prototype/run.sh --batch --archetype champion_loss_decliner

# From anywhere with absolute path
/Users/connorkasser/gtm-os/prototype/run.sh --batch --limit 5

# Override the question
prototype/run.sh \
    --account "Pendant Logistics" \
    --question "Why is this account at renewal risk and what's the play?"
```

`ANTHROPIC_API_KEY` must be set in the shell environment (it already is if
`synth/conversations.py` worked for you).

### Without the wrapper (raw form)

The wrapper just resolves paths. The underlying invocation is:

```bash
synth/venv/bin/python3 prototype/run_agt902.py --account 026a4a59
```

Use this if you've activated the venv yourself or want to inspect what's running.

## What it does

For one account:

1. Reads the corpus file (full account composite from `synth/corpus/<uuid>.json`)
2. Extracts a brain-ready view — compresses daily usage rows into monthly
   aggregates + trailing-30/90 summaries, snapshots health at multiple lookback
   points, summarizes payment events, passes conversation log through with
   archetype-aware projections
3. Builds the system prompt (AGT-902 role + constraints + output schema) and
   user prompt (view + question)
4. Calls Anthropic API (default model: `claude-sonnet-4-6`; override with
   `ANTHROPIC_MODEL` env var)
5. Parses the JSON output
6. Runs validation: schema compliance, source-citation resolution, action
   taxonomy enum check, staleness disclosure check, confidence calibration
7. Writes a BrainAnalysisLog row to `prototype/brain_analysis_log.jsonl`

## What "brain-ready view" means here

Per the AGT-902 spec, the brain doesn't read raw Tier 1 tables — it reads
projections. In a corporate environment, those projections are materialized
views that the underlying Tier 1 service maintains. For the prototype, the
brain-ready view is computed in `agt902.py:extract_brain_ready_view()` from
the corpus file every time the brain runs.

The view is bounded:
- **Account base**: passed through (small)
- **Usage**: monthly aggregates over the full contract age + trailing 30d/90d summaries — bounded ~2K tokens for a 540-day account
- **Health**: current + snapshots at 30d/60d/90d/180d ago + 30d trajectory band — bounded ~500 tokens
- **Conversations**: all calls (capped at 12 by `synth/conversations.py`) passed through with full transcript_summary — bounded ~3K tokens
- **Payments**: current state + 10 most recent events + transition count — bounded ~500 tokens
- **Expansion signals**: derived from usage (overage in last 30 days)
- **Churn risk**: derived from contract end date (renewal proximity band)

Components not synthesized in the prototype corpus (`opportunities`, `qbr_history`,
`onboarding`, `implementation`) appear in the view as `"not_in_corpus"` so the
brain knows what's missing and can acknowledge it explicitly rather than fabricate.

Total view payload: typically 5–8K tokens. With the system prompt (~1.5K) and
question (~50), input is ~7–10K tokens. Well within Sonnet's context window
and well within the AGT-902 spec's 35K input budget.

## Validation rules

Per the AGT-902 + BrainAnalysisLog specs, validators check:

| Check | Severity | What it catches |
|---|---|---|
| Required fields present | hard | missing schema fields → unparseable BrainAnalysisLog row |
| Source citations resolve | hard | `[src:N]` in narrative referencing non-existent `sources_read` entry |
| Action taxonomy | hard | `proposed_actions[].action_type` outside the AGT-902 enum (7 values) |
| Staleness disclosure | hard | `data_staleness_acknowledged=true` but narrative has no staleness phrase |
| Confidence calibration | soft | 100% high_confidence flags (likely dishonest) or no flags at all |
| Citation presence | soft | narrative with zero citations (suspicious; every numerical claim should cite) |

`hard` issues are eval failures — production brain wouldn't be promoted with hard
issues. `soft` issues are calibration items, logged but not blocking.

## Output: BrainAnalysisLog rows

Each row is appended to `prototype/brain_analysis_log.jsonl` (one JSON object
per line). Inspect with:

```bash
# Most recent row
tail -1 prototype/brain_analysis_log.jsonl | python3 -m json.tool

# All rows for one account (jq required)
jq 'select(.account_id == "026a4a59-...")' prototype/brain_analysis_log.jsonl

# Hard validation failures across all runs
jq 'select(._meta_validation.hard_failure == true)' prototype/brain_analysis_log.jsonl

# Cost summary
jq '.cost_usd_estimate' prototype/brain_analysis_log.jsonl | awk '{s+=$1} END {print "total $", s}'
```

A row contains everything from the BrainAnalysisLog production schema spec
(analysis_id, proposal_id, writer_agent_id, sources_read, narrative_output,
proposed_actions, confidence_flags, etc.) plus a `_meta_validation` field with
the local validation result.

## Cost expectation

Per call at default Sonnet:
- Input: ~7–10K tokens
- Output: ~1–2K tokens
- Cost: ~$0.05–0.10

Per call at Haiku (`ANTHROPIC_MODEL=claude-haiku-4-5-20251001 python3 run_agt902.py …`):
- Cost: ~$0.01–0.02

50 corpus accounts in batch: ~$3–5 on Sonnet, ~$0.50–1 on Haiku. Adjust per the
brain calibration story when you start running the eval harness.

## What's not in this stub (deferred)

- **Account synthesis signature caching** (per AGT-902 spec): repeat queries on
  the same account within the freshness window should hit cache. Stub does a
  fresh API call every invocation. Add when running iterative meeting-prep
  workflows shows the need.
- **Tier 3 tool invocation**: AGT-902 should call TOOL-004 (consumption forecasting)
  and TOOL-008 (adoption pattern recognizer) for "is this real expansion" / "is
  this account getting value" queries. Stub doesn't yet — brain produces analysis
  from view alone. Tools wire in once they're built.
- **Prompt caching**: Anthropic's 5-minute prompt cache should be enabled on the
  system prompt. Stub doesn't configure it — saves ~$0.30/run when running
  several queries back-to-back.
- **Approval gate enforcement on proposed plays**: when the brain proposes an
  `open_expansion_play` action, the workflow that takes that into SalesPlayLibrary
  drafts isn't built. Stub just records the proposal in BrainAnalysisLog.

These are all valid next steps after the brain itself is producing reasonable
output. Use the eval harness (Week 6 in the timeline) to decide which to
prioritize based on observed behavior.

## Architecture invariants this stub preserves

These come straight from the AGT-902 spec — when porting to a corporate environment,
keep them:

1. **Brain reads brain-ready views, never raw canonical tables.** In the prototype,
   the view is constructed from the corpus file (because corpus IS the canonical
   data here). In production, the view is materialized by the underlying Tier 1
   service.
2. **Brain never writes canonical data.** Output goes only to BrainAnalysisLog
   (and would go to SalesPlayLibrary drafts when those are wired).
3. **Source-trace metadata enforced.** Every numerical claim cites `[src:N]`;
   validators check that every citation resolves.
4. **Action taxonomy enumerated.** Brain cannot invent action types — only the 7
   in AGT-902 spec are valid.
5. **Staleness recognition is a hard requirement.** Stale data without disclosure
   = sev-2 incident.
6. **Honest confidence calibration.** Output marks claims as high_confidence /
   multi_source / inference / speculation — calibrated to support, not asserted.

If you change the runtime, double-check none of these invariants drift.
