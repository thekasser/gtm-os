# prototype/eval — AGT-902 eval harness

Runs AGT-902 against a set of fixtures, scores per-criterion, writes a
BrainEvalLog row, prints a pass/fail summary.

## Quick start

```bash
# From anywhere — the wrapper auto-resolves paths
prototype/run_eval.sh                    # run all fixtures
prototype/run_eval.sh --fixture EVAL-Q01 # run one
prototype/run_eval.sh --quiet            # show only failures
```

## What's here

| File | Purpose |
|---|---|
| `fixtures.py` | The fixture catalog. 3 starter fixtures + a TEMPLATE for the 7 you'll add. Edit this file to expand the harness. |
| `scorer.py` | Per-fixture scoring: resolves account, applies mutations, runs brain, validates, checks pass criteria. |
| `brain_eval_log.py` | JSONL writer for eval-run results. Parallel to BrainAnalysisLog. |
| `run_eval.py` | CLI entry point — iterates over fixtures, prints summary. |

## How it scores

Each fixture defines `pass_criteria`. The scorer runs every applicable check and reports per-criterion pass/fail:

| Criterion | What it checks | Source |
|---|---|---|
| `schema_compliance` | Required fields present in brain output | `validation.py` |
| `citations_resolve` | Every `[src:N]` resolves to a `sources_read` entry | `validation.py` |
| `action_taxonomy_compliant` | Every `proposed_action.action_type` is in the AGT-902 enum | `validation.py` |
| `min_citation_count` | Brain produced ≥ N citations | scorer |
| `diagnosis_match_pass` | `should_mention` phrases present, `should_not_mention` absent | scorer |
| `expected_actions_pass` | `must_include_at_least_one_of` satisfied, `must_not_include` not violated | scorer |
| `data_staleness_acknowledged` | Brain set the flag to True (stale fixtures only) | scorer |
| `narrative_contains_staleness` | Narrative contains a staleness phrase (stale fixtures only) | scorer |

Fixture passes = all configured criteria pass.

## How to add a fixture

1. Open `fixtures.py`.
2. Copy the `TEMPLATE_FIXTURE` dict at the bottom.
3. Fill in the fields. The template has inline comments explaining each.
4. Add your new fixture to the `FIXTURES` list at the top.
5. Run `prototype/run_eval.sh --fixture EVAL-Q??` (your new ID) to test it.
6. Iterate on `should_mention` / `must_not_include` lists until pass/fail aligns with your intuition.

## Reading the output

```
[1/3] EVAL-Q01 — churn_diagnosis (easy)
  account: Pendant Logistics (champion_loss_decliner)
  brain:   claude-sonnet-4-6, 6934in/3214out, $0.0690, 50100ms
  ✓ schema_compliance — all required fields present
  ✓ citations_resolve — 39 citations all resolve
  ✓ action_taxonomy_compliant — 4 actions all in enum
  ✓ min_citation_count >= 10 — found 39 citations
  ✓ diagnosis_match — matched 3/3 should_mention
  ✓ expected_actions — matched ['escalate_to_slm']
  → PASS
```

A fail looks the same but with ✗ on the failed criterion and a detail explaining why:

```
  ✗ expected_actions — INCLUDED ['open_expansion_play'] (must_not_include)
```

## Logs

Every eval run writes:

- A `BrainAnalysisLog` row per brain invocation → `prototype/brain_analysis_log.jsonl`
  (so you can re-read what the brain actually said for any failure)
- A `BrainEvalLog` row per overall run → `prototype/brain_eval_log.jsonl`
  (with FK to brain_analysis_id)

To inspect:

```bash
# All eval runs
jq '.eval_run_id, .aggregate' prototype/brain_eval_log.jsonl

# Brain output for a failed fixture
jq 'select(.analysis_id == "<id-from-fixture-result>")' prototype/brain_analysis_log.jsonl
```

## Cost expectation per run

- 3 starter fixtures @ Sonnet ≈ $0.20 per full eval run
- 10 fixtures (when you fill them in) ≈ $0.50–0.70 per run
- Cheaper on Haiku via `ANTHROPIC_MODEL=claude-haiku-4-5-20251001`

## Calibration tips for fixture writing

These come from running the harness on real outputs:

1. **Run the brain manually before writing pass criteria.** Look at what the brain actually says for the target archetype; tune your `should_mention` list to match how the brain phrases things rather than how you think it should.

2. **Loose semantic phrases beat tight verbatim ones.** `"champion"` is better than `"champion departed November 2"`. Brain phrasing varies; your eval shouldn't fail because the brain said "key contact left" instead of "champion departed."

3. **`must_not_include` catches more bugs than `must_include`.** A brain that fabricates wrong actions on a trap case is the failure mode worth testing for.

4. **Soft issues are calibration signals.** When the validator emits soft issues (e.g., "all confidence flags are high_confidence"), that's a calibration item — log it, watch the trend over multiple runs, but don't gate on it.

5. **Stale fixtures are about staleness only.** Set `min_drivers_matched=0` and only check the staleness criteria. If you mix staleness with diagnosis quality you'll get fixtures that fail for the wrong reason.

## When something looks off

If a fixture fails and you don't understand why, drop the corresponding brain output:

```bash
# Most recent brain analysis
tail -1 prototype/brain_analysis_log.jsonl | jq .narrative_output -r
```

Read the actual narrative. Did the brain say something the criteria missed? Tune the criteria. Did the brain hallucinate? File it as a real eval failure and dig into prompt design.
