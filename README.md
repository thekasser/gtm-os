# gtm-os

A modular, spec-driven Go-To-Market Operating System. **Three tiers**, ten layers, two working brain agents, twelve specialist tools — two of which actually run against synthetic GTM data today.

This repo is a working prototype designed to port into a real corporate environment. Synthetic data substitutes for real warehouse tables; the prototype's contracts (brain-ready views, action taxonomies, eval harness) are written to survive the migration unchanged.

## Quick links

- **Architecture explainer**: [gtm_os_explainer.html](https://thekasser.github.io/gtm-os/gtm_os_explainer.html) — rendered DAG of all 40 services + 2 brains + 12 tools, click any layer to drill in
- **Changelog (v25 → present)**: [schema/GTM_OS_Changelog.html](https://thekasser.github.io/gtm-os/schema/GTM_OS_Changelog.html)
- **Tier 3 tool catalog**: [tools/Tools_Index.html](https://thekasser.github.io/gtm-os/tools/Tools_Index.html)
- **Prototype runtime + eval harness**: [`prototype/`](prototype/)
- **SalesPlayLibrary draft viewer**: [`prototype/sales_play_library_viewer.html`](prototype/sales_play_library_viewer.html) — local-only; render brain proposals as reviewable cards (run an eval, then `python3 -m http.server` from `prototype/`)
- **Synthetic data generator**: [`synth/`](synth/)
- **Bridge to corporate**: [`prototype/PORT_TO_CORPORATE.md`](prototype/PORT_TO_CORPORATE.md)

---

## What gtm-os is

A declarative data pipeline with policy-driven gates plus an optional reasoning layer on top. Three categories of artifact, deliberately separated:

### Tier 1 — GTM Services (L1–L8 · 40 services)

Deterministic, scheduled or event-triggered functions. Single-writer-per-table invariant. Audit-grade. The deterministic backbone of the system: quota math, comp payouts, ASC 606 revenue recognition, customer health scoring, churn risk, expansion triggers, etc.

These are **services**, not agents. They have stable I/O contracts, run on cadence or fire on event triggers, and own canonical tables. LLM may be invoked inside a service step (e.g., transcript analysis), but the service's contract is deterministic input → deterministic output table.

### Tier 2 — Brain Agents (L9 · 2 agents)

LLM-native, long-context, ephemeral state. Read Tier 1 services freely; write only to non-canonical logs (`BrainAnalysisLog`, `SalesPlayLibrary` drafts). Operator-invoked, never on cadence. Promotion of any brain proposal to a canonical table requires human approval.

- **AGT-901 Pipeline Brain** — cohort-level reasoning ("why is mid-market commercial soft?"). Action taxonomy: `draft_play / flag_coverage_gap / recommend_query_for_human / none`.
- **AGT-902 Account Brain** — per-account synthesis across health / usage / payments / conversations / expansion / churn. Action taxonomy: `pull_qbr_forward / open_expansion_play / brief_new_ae_or_csm / customer_communication / escalate_to_slm / recommend_human_query / none`.

### Tier 3 — Specialist Tools (12 tools, 3 waves)

Stateless, narrow, callable LLM functions. Not agents — functions an agent (or service) can call. No layer, no schema ownership, no cadence. Logged for audit but not authoritative.

Three are operational in the prototype: **TOOL-003 Sales Play Composer** (called by the SalesPlayLibrary writer to enrich brain-drafted plays), **TOOL-004 Consumption Forecasting**, and **TOOL-008 Product Adoption Pattern Recognizer** (TOOL-004 + TOOL-008 wired into both brain runtimes via Anthropic tool-use). The other nine are specced in [tools/Tools_Index.html](https://thekasser.github.io/gtm-os/tools/Tools_Index.html).

### The contract between tiers

1. Tier 1 never depends on Tier 2. If brains are offline, the canonical pipeline still runs.
2. Tier 2 reads Tier 1 freely; writes only to non-canonical logs. Promotion to canonical = human approval gate.
3. Tier 3 is stateless. Called, returns, done. Logged for audit; not authoritative.
4. Brain outputs always carry source-trace metadata — every numerical claim cites the Tier 1 table and timestamp it came from.

---

## Status

| Component | Status | Notes |
|---|---|---|
| 40 GTM Services (L1–L8) | **Built** | Specs in [`specs/`](specs/) |
| AGT-901 Pipeline Brain (L9) | **Prototyped** | 3-fixture eval at 3/3 pass, ~$0.32/run |
| AGT-902 Account Brain (L9) | **Prototyped** | 11-fixture eval at 11/11 pass, ~$1.21/run |
| TOOL-003 Sales Play Composer | **Prototyped** | Called by SalesPlayLibrary writer to enrich draft cadence + criteria |
| TOOL-004 Consumption Forecasting | **Prototyped** | Wired into AGT-902 + AGT-901 |
| TOOL-008 Product Adoption Pattern | **Prototyped** | Wired into AGT-902 + AGT-901 |
| TOOL-001, 002, 005…007, 009…012 | **Specced** | Awaiting corpus extension or dependent service |

Three statuses, used consistently across [explainer](https://thekasser.github.io/gtm-os/gtm_os_explainer.html), [changelog](https://thekasser.github.io/gtm-os/schema/GTM_OS_Changelog.html), and [Tools_Index](https://thekasser.github.io/gtm-os/tools/Tools_Index.html):

- **Specced** — design only
- **Prototyped** — runtime exists, evals pass, not yet wired to canonical Tier 1 tables in production
- **Built** — production-deployed

---

## Repository layout

```
gtm-os/
├── gtm_os_explainer.html        Architecture explainer (interactive DAG)
├── specs/                       40 GTM Service specs + 2 Brain Agent specs
├── tools/                       Tier 3 tool catalog (12 specs + index)
├── schema/                      Production schemas + changelog
│   ├── GTM_OS_Changelog.html
│   ├── BrainAnalysisLog_Schema.html
│   ├── SalesPlayLibrary_Schema.html
│   ├── BrainEvalLog_Schema.html
│   ├── Brain_Ready_Views_Contract.html
│   └── UsageMeteringLog_Production_Schema.html
├── eval/                        Brain eval harness + question catalog (architecture docs)
├── synth/                       Synthetic data generator (substrate for the prototype)
│   ├── archetypes.py            8 account archetypes (ideal_power_user, activating, ...)
│   ├── main.py                  Corpus orchestrator (50 accounts, daily Tier 1 telemetry)
│   ├── usage.py / health.py / payments.py / feature_engagement.py / conversations.py
│   └── README.md
└── prototype/                   Working brain runtimes + eval harness
    ├── agt901.py / agt902.py    Brain runtimes
    ├── aggregates.py            Cross-account view extractor (AGT-901)
    ├── tools/                   TOOL-004, TOOL-008, registry
    ├── eval/                    Fixtures, scorers, runners
    ├── PORT_TO_CORPORATE.md     Bridge document for migration
    └── README.md
```

---

## Running the prototype

Synthetic data + Anthropic API key required. The prototype runs against `synth/corpus/` (excluded from git — regenerate locally).

```bash
# 1. Generate synthetic corpus (no API needed)
cd synth
python3 main.py                                  # 50 accounts → corpus/

# 2. Generate conversation summaries (Haiku, ~$1-3 one-time, cached)
export ANTHROPIC_API_KEY=sk-ant-...
python3 conversations.py

# 3. Run the brain runtimes
cd ..
prototype/run.sh --account "Pendant Logistics" --question "How is this account positioned for renewal?"
prototype/run_agt901.sh --question "Which segment is the strongest expansion candidate?"

# 4. Run the eval harnesses
prototype/run_eval.sh --quiet                    # AGT-902, 11 fixtures, ~$1.20
prototype/run_pipeline_eval.sh --quiet           # AGT-901, 3 fixtures, ~$0.32
```

See [`prototype/README.md`](prototype/README.md) for the full runner reference and [`synth/README.md`](synth/README.md) for the data generator.

---

## Design principles

1. **Practitioner realism** — every service maps to how GTM actually works in a B2B SaaS or usage-based-business context.
2. **Human-in-the-loop** — qualitative decisions and brain proposals always require human approval before reaching canonical state.
3. **Schema coherence** — single write owner per table. Load-bearing constraint that makes audit trails recoverable and refactors safe.

---

## Status of this repo

Solo prototype, designed to port. The synthetic data layer and prototype runtimes are stand-ins for real product telemetry, conversation intelligence, and warehouse reads in a corporate environment. Architecture, contracts, and eval discipline are written to survive that migration unchanged. See [`prototype/PORT_TO_CORPORATE.md`](prototype/PORT_TO_CORPORATE.md) for the migration plan.
