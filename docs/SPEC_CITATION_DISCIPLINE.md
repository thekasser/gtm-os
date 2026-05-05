# Spec citation discipline

A short rule + checklist for anyone (human or AI) writing narrative content about gtm-os that cites specific values from the architecture specs.

## The rule

**Read the spec before quoting it.**

Specifically: any narrative that quotes a *spec value* — SLA threshold, dimension count, scoring weight, score-to-tier mapping, schema field name, action-taxonomy enum value — must be grounded in the actual `specs/AGT-NNN_*.html` source, not in working memory or "what feels right for GTM."

## Why this exists

In v35, a narrative file (`eval/samples/follow_a_lead.json`) cited a "3-business-day SLA" for a hot T1 inbound lead. The actual AGT-202 spec says T1 = 2 hours. The drift wasn't malicious — the narrative was hand-typed from architectural intuition, not from grep-on-spec. A CRO caught it in the first walkthrough.

The audit that followed found:
- **The 40 GTM Service specs are the source of truth.** They're correct.
- **The explainer's deterministic simulator** (`routeLead()`) was correct — it cites the spec table values directly.
- **The brain narratives** (`eval/samples/brain_outputs.json` from real prototype runs) were clean — they only cite `sources_read` table names, not spec values.
- **Hand-authored narratives are the vulnerability.** They have no validator, no reference check, and no enforced grounding to source.

## What counts as a "spec value"

Things you must NOT quote from memory:

- **SLAs / time thresholds**: "T1 SLA is 2 hours", "QBR scheduled 90 days before renewal", "renewal-proximity multiplier kicks in at 90 days"
- **Dimension counts**: "9-dimension health score" (it's actually 7 + payment modifier per AGT-501), "6-dimension ICP" (correct per AGT-201), "4-tier approval"
- **Score thresholds**: "T1 ≥ 80", "Green ≥ 80", "Magic Number target 0.8"
- **Schema field names**: column names, log-table names, enum values
- **Action taxonomy enums**: each brain has its own taxonomy; the values are exact
- **Service ownership**: "AGT-503 Expansion Trigger", "AGT-302 Cadence Coordinator" — get the AGT-ID right, get what it owns right

Things that are safe to write without grep-on-spec:

- **Architectural framing**: tier structure, single-writer-per-table, brain proposes → human approves. These are stable.
- **Layer descriptions**: L1 = sales planning, L8 = revenue ops. Stable.
- **General GTM concepts**: "champion-loss risk", "consumption overage", "QBR cadence" without quoting specific numbers.

## The checklist

Before writing any narrative content about gtm-os:

1. **Identify spec-value claims.** Anything that sounds like "X has Y at Z threshold" — flag it.
2. **Grep the relevant spec.**
   ```bash
   grep -i "<your-claim>" specs/AGT-NNN_*.html
   ```
3. **Cite the spec by ID.** Example narrative pattern: "AGT-202 routes T1 leads with a 2-hour SLA (per AGT-202 spec — T1 ≥ 80, T2 60-79 = 24hr, T3 < 60 = 72hr)."
4. **If you're proposing a spec change**, do it in two steps:
   a. Edit the spec HTML first (it's the source of truth)
   b. Then update narrative + simulator + changelog to match
   
   Never skip step (a). Narrative-only "fixes" to spec values create drift, not corrections.

## Files governed by this rule

These files contain spec-value claims and require grep-on-spec discipline:

- **`gtm_os_explainer.html`** — architectural hero copy + simulator JS. The simulator's scoring functions (`scoreICP`, `routeLead`, etc.) are the most-cited spec content.
- **`eval/samples/follow_a_lead*.json`** — narrative walkthroughs. These cite SLAs, service ownerships, threshold language.
- **`eval/samples/brain_outputs.json`** — generated, not hand-written. Already clean (validator-enforced).
- **`README.md`** + **`prototype/README.md`** + **`schema/GTM_OS_Changelog.html`** — citing spec content in user-facing docs.
- **`prototype/PORT_TO_CORPORATE.md`** — references service-by-service migration. Spec-cite as you go.

These files are exempt:

- **`prototype/agt901.py`** + **`prototype/agt902.py`** — system prompts cite the action taxonomy from their own enums. Source of truth for those enums.
- **`prototype/eval/fixtures.py`** — test cases, not narrative.
- **`synth/*.py`** — generates synthetic data, doesn't quote spec.

## How to fix existing drift

If you find a narrative that cites a spec value, verify against the spec:

```bash
# Example: verify a SLA claim in a narrative
grep -n "SLA" specs/AGT-202_Lead_Router.html

# Example: verify dimension count claim
grep -n "dimension" specs/AGT-501_Customer_Health_Monitor.html
```

If they don't match: the narrative is wrong (assume the spec is right, since the spec drives the simulator and the prototype runtimes). Edit the narrative, commit with a `fix:` prefix.

If the spec itself is wrong: edit the spec first, then update the narrative + simulator + changelog. Use `feat:` or `update:` prefix.

## Standing audit

The audit run on 2026-05-04 (against v35.1) verified:

- 14 brain output samples — **0 spec drift** found
- All `proposed_actions[].lever` references correct (AGT-302, AGT-203, AGT-503, AGT-603, AGT-504, AGT-501, AGT-902 — all match spec ownership)
- Only spec-drift found was in `eval/samples/follow_a_lead.json` (the SLA value), now fixed

If you make material changes to narrative-citing files, re-run a quick spot-check: extract any "X-hour", "X-dimension", "AGT-XXX does Y" claims, grep them against `specs/`. Add findings to a future audit dated entry below.

| Date | Auditor | Files audited | Drift found | Status |
|------|---------|---------------|-------------|--------|
| 2026-05-04 | Claude (CRO-pivot pre-flight) | brain_outputs.json, follow_a_lead.json | T1 SLA in follow_a_lead.json | Fixed in 8727a21 |
| 2026-05-05 | Claude (v37 self-audit, post-AGT-903 spec) | specs/AGT-903_Strategy_Brain.html, schema/StrategyRecommendationLog_Schema.html, schema/GTM_OS_Changelog.html (v36→v37 entry), prototype/eval/strategy_fixtures.py | (a) AGT-303 mis-attributed as "cadence design" in 3 places — AGT-303 is Cadence Intelligence (advisory only, all changes through AGT-302); cadence orchestration belongs to AGT-302. (b) Strategy brain-ready view names inconsistent: fixtures used flat (`metrics_strategy_brain_view`), spec used dotted (`MetricsCalc.strategy_brain_view`); AGT-901/902 convention is dotted. Also surfaced BrainAnalysisLog gaps (no writer_agent_id enum entry for AGT-903, invocation_path missing AGT-903 paths, action_type CHECK referenced AGT-902 only, speculation threshold needed AGT-903 exception) — filled in same pass. | All fixed in this session (uncommitted at audit time) |
