# Porting AGT-902 from synthetic prototype → real corporate data

This doc is the bridge document for moving the prototype into a corporate
environment. Written while the prototype is fresh; reverse-engineering it
later from code alone would lose the rationale.

The prototype is intentionally structured so the **boundary** between
synthetic and real data is one well-defined seam: the **brain-ready view**.
Tier 1 GTM Services produce canonical tables; the view extractor compresses
them into ~5–10K tokens; the brain consumes the view. Swap synthetic for
real at this seam and the rest works without modification.

---

## What MUST change

### 1. Data sources (replace synth/ generators)

| Synthetic source | Real corporate equivalent |
|---|---|
| `synth/usage.py` → UsageMeteringLog | Real product telemetry pipeline → write canonical UsageMeteringLog per the Tier 1 schema. **This is the audit-critical one** — start here. AGT-804 (revenue recognition) reads from this. |
| `synth/health.py` → CustomerHealthLog | AGT-501 daily output. Already a Tier 1 service in the spec; just needs the upstream signals (usage, payment, conv intel) to be real. |
| `synth/payments.py` → PaymentEventLog | Source of truth: billing system (Stripe / Zuora / NetSuite). One adapter per system — most companies will only have one. |
| `synth/conversations.py` → ConvIntelligence | Gong / Chorus / Fireflies / Otter export. AGT-407 ConvIntelligence is already specced for this. **Real transcripts will be 10-50x longer** than the synthetic Haiku-generated summaries. The brain-ready view must summarize aggressively before passing to AGT-902. |
| `synth/feature_engagement.py` → feature_engagement | Product analytics warehouse (Amplitude, Heap, Mixpanel, or in-house). Map your real feature catalog to the 5-category taxonomy (core / advanced / integration / admin / experimental). The category split drives TOOL-008's classification logic — get the categorization right before turning on the tool. |

### 2. Brain-ready view extractor + the **`BrainViewSource` seam**

**The single most important seam to understand before porting** is
`prototype/view_source.py`. It defines the abstract contract every data
source must satisfy for the brains and tools to consume it. The prototype
ships with two implementations:

- **`SynthCorpusSource`** — production-grade for the prototype. Reads JSON
  files from `synth/corpus/`. This is the default.
- **`WarehouseViewSource`** — stub class with `NotImplementedError` on every
  method. Documents the interface a corporate-environment implementation
  fulfills.

To port: subclass `BrainViewSource` and implement these methods:

```python
class WarehouseViewSource(BrainViewSource):
    def load_account_corpus(self, account_id: str) -> dict:
        # SELECT … JOIN across CustomerHealthLog, UsageMeteringLog,
        # PaymentEventLog, ConvIntelligence (filtered by call_owner_role),
        # ExpansionLog, ChurnRiskLog, feature_engagement_telemetry, account
        # → return the same shape the synth corpus JSON provides.
        ...

    def account_exists(self, account_id: str) -> bool: ...
    def account_data_freshness(self, account_id: str) -> tuple[bool, str]: ...
    def iterate_account_ids(self) -> Iterator[str]: ...
    def metadata(self) -> dict: ...
```

Then either:
- Pass an instance to `run_for_account(...)` / `run_for_pipeline(...)` directly, or
- Set `GTM_OS_VIEW_SOURCE=warehouse` and add a branch in
  `view_source.default_source()` to construct it from your config.

**The brain-ready view extractor itself** (`agt902.extract_brain_ready_view`,
`aggregates.extract_pipeline_view`) does NOT need to change when porting.
It already pulls through the source. What you'll re-tune is:

- **Compression budgets per component.** Real conversation transcripts may
  push raw view size over 30K tokens. The brain's accuracy degrades visibly
  past ~20K tokens of view input — measure this with your eval harness.
- **Per-component token caps** as a config knob (currently hardcoded). Add
  this as `view_compression_config.json` so RevOps can tune without code
  changes.

### 3. Tools that re-read corpus files

TOOL-004 and TOOL-008 currently re-read per-account corpus because the
brain-ready view is lossy by design (monthly aggregates only). After the
view-source refactor, both tools pull through `_load_account_corpus(account_id, source=source)`
in `prototype/tools/registry.py`. **No tool code changes when porting** —
the source's `load_account_corpus(account_id)` method is the seam.

Operational notes:
- Cache aggressively at the warehouse layer — TOOL-008 daily-batch use case
  will hit ~100s-1000s of accounts per day; per-call DB roundtrip is fine
  but full table scans per call are not.
- Consider materializing a per-account `account_brain_view` table that the
  source's `load_account_corpus` reads in one query, refreshed nightly.

### 4. ANTHROPIC_API_KEY → corporate Anthropic account

`~/.zshenv` works for prototype. Production needs a service account with:
- Per-environment keys (dev / staging / prod)
- Cost monitoring + budget alerts at 75% of monthly cap (per the eval-cost
  guidance in the original architecture doc)
- Prompt-caching enabled at the API call level (currently brain calls do
  benefit from cache but it's automatic; verify the API headers)

### 5. Eval fixtures

The 11 synthetic fixtures (EVAL-Q01–Q11) are tuned to the synth archetypes.
**Don't keep them as-is in production.** Pattern to follow:
- Pick 30 historical accounts with known retrospective outcomes (the eval
  harness scaling guidance from the architecture doc)
- Manually construct expected_diagnosis / expected_actions per account
  based on what your team actually said about that account at the time
- The synthetic fixture cheat sheet (`prototype/eval/fixtures.py` header)
  applies — loose semantic > tight verbatim, must_not_include catches more
  bugs, watch for substring traps

---

## What SHOULDN'T change

### Keep these prototype patterns as-is in corporate

1. **Multi-turn tool-use loop** (`call_brain` in agt902.py) — works for any
   tool count.
2. **System-prompt + ACTION_TAXONOMY enum** — the action vocabulary is
   product-agnostic. Add new action types when you wire new playbooks
   (e.g., `open_dev_persona_play` if you add TOOL-002).
3. **Validation rules** (schema, citations resolve, action enum, staleness
   disclosure, confidence flags) — these are universal.
4. **BrainAnalysisLog schema** — append-only audit log; same shape works in
   corporate. Just point the writer at a real persistent store (Postgres
   table, BigQuery, etc.) instead of `prototype/brain_analysis_log.jsonl`.
5. **The 8 archetypes as "test segments"** — don't run the corpus
   generator in prod, but the archetype concept (deeply_integrated,
   activating, surface_only, declining, etc.) translates directly to
   account categorization. TOOL-008's classification mirrors archetypes.

---

## Migration sequence (recommended)

Per the architecture doc's "build sequence" guidance — L8 first, brain second.

### Phase 0: Set up the eval harness against real data (week 1)
- 30 historical accounts manually annotated with expected diagnosis/actions
- Run the existing prototype against them (point it at JSON exports of
  the real account data)
- Establish baseline: how many of the 30 does the prototype get right?
- This is your **regression baseline** for everything that follows.

### Phase 1: UsageMeteringLog as production schema (week 2-3)
- Wire your real product telemetry to write canonical UsageMeteringLog
- Validate: TOOL-004 against real consumption returns sensible patterns
- Reconcile: monthly aggregates match what AGT-804 (rev rec) expects

### Phase 2: ConvIntelligence (week 4-5)
- Connect Gong/Chorus/Fireflies pipeline → ConvIntelligenceLog
- Long-transcript handling: brain-ready view summarizer must compress
  hard (1 transcript ≈ 5-15K tokens raw; need to drop to <1K per call)
- Re-run Phase 0 baseline and check accuracy delta

### Phase 3: CustomerHealthLog + ChurnRisk + ExpansionSignal (week 6-8)
- Standard Tier 1 services per spec. Most are already specified.

### Phase 4: feature_engagement_telemetry + TOOL-008 (week 9-10)
- Map real feature catalog to 5-category taxonomy
- Smoke-test TOOL-008 against retrospective accounts
- Validate: known siloed-by-team accounts classify correctly; known
  power users classify as deeply_integrated

### Phase 5: Brain Agents go live (week 11+)
- Initial scope: read-only diagnostic queries from RevOps + sales leaders
- Co-definition workflow per the architecture doc — brain proposes,
  humans curate, action taxonomy stays the same
- Cohort-level retrospective starts immediately so you have signal by
  end of Q1

---

## Risks worth flagging early

1. **Real conversation transcripts will blow the view budget.**
   Synthetic summaries are ~200 tokens; real Gong transcripts are 5-15K.
   The brain-ready view extractor needs aggressive summarization OR the
   brain calls a Tier 3 transcript-summarizer tool on demand. Decide
   before Phase 2.

2. **Feature taxonomy mapping is judgment-heavy.**
   "What's a core feature vs. an advanced feature?" is a real product
   question. Get product + RevOps aligned on the categorization before
   wiring TOOL-008. Wrong categories → tool produces wrong patterns →
   brain narratives are wrong with high confidence (worst failure mode).

3. **PII handling in BrainAnalysisLog.**
   The synthetic log is fine for prototype, but real BrainAnalysisLog
   will contain customer-identifiable narrative. Decide retention policy
   + access control + redaction-on-export before Phase 5 goes live.

4. **API cost monitoring before scale.**
   Per the architecture doc: hard ceilings with alerting at 75% of
   monthly budget, per tier. Set this BEFORE turning on daily batches.
   The most common early mistake is leaving a debug loop running over a
   weekend.

5. **The handoff rule for retiring a tool.**
   Calibration probe finding (May 2026): pulling a tool requires
   coordinated updates to (a) tool registry schema, (b) tool handler,
   (c) system prompt description. Pulling only the schema is leaky — the
   brain emits tool_use calls based on system-prompt context, dispatch
   still finds the handler, and the result is a hallucinated success.
   Add a "tool retirement checklist" to runbook before scale.

---

## Files to read first when porting

In rough order of how load-bearing they are:

1. `prototype/agt902.py` — brain runtime, system prompt, view extractor
2. `prototype/tools/registry.py` — tool dispatch + corpus augmentation
3. `prototype/eval/scorer.py` — validation rules
4. `prototype/eval/fixtures.py` — fixture format + cheat sheet
5. `prototype/validation.py` — issue dataclass + validators
6. `synth/feature_engagement.py` — feature taxonomy (becomes mapping doc)
7. `synth/archetypes.py` — segment definitions (becomes mental model)

The synth/ generators (`usage.py`, `health.py`, `payments.py`,
`conversations.py`) are throwaway in corporate — they generate fake data
that real Tier 1 services replace. Do not port them.
