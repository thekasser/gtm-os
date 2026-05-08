# CRO Demo Script — gtm-os

**Goal:** in 12–15 minutes, show a CRO that gtm-os is (a) a coherent architecture, (b) a *working system* that produces real reasoning on real-shaped data, and (c) actually **interactive** at the planning meeting they actually run.

The repo has eight explainer tabs. Click them in **this order**, or you'll tell a worse story:

> Architecture → Brain Outputs → Follow a Lead → **Planning → Forecast & WBR** → (optional) The OS / Connection Map / ICP Scorer Demo

The Planning and Forecast/WBR tabs are new in v37.2 and are sized for a **$400M–$1B ARR business with 80–100 sales reps** across new business and existing.

---

## Pre-flight (do this 5 minutes before the call)

1. Open https://thekasser.github.io/gtm-os/gtm_os_explainer.html in a fresh tab
2. Confirm header reads "v37 · Schema" and meta-stats show **3 agents · 14 tools**
3. Click **Brain Outputs** — confirm the gallery loads (14 cards visible)
4. Click any card — confirm modal opens with `[src:N]` chips visible inline in the narrative
5. Press Esc, click **Follow a Lead** — confirm the timeline loads with the 7-stat header strip
6. Scroll to Day +120 — confirm the amber "🧠 See the actual brain reasoning — EVAL-Q04 →" button is visible
7. Click **Planning** — confirm Quota sub-panel loads with sliders and the per-segment quota card
8. Pull the ARR target slider once — confirm numbers reflow live
9. Click **Forecast & WBR** — confirm the Forecast sub-panel loads with bottoms-up + top-down + commit + plan card
10. Click the WBR sub-tab — confirm five canonical metric cards (Magic Number / R40 / NRR / GRR / CAC Payback) render with current values

If any of those fail, the live Pages build is broken. Stop and ping the engineer (you).

---

## The 12-minute pitch

### 1. Architecture (90 seconds)

> "This is gtm-os. It's three tiers across ten layers. **Forty GTM Services** in L1 through L8 — these are the deterministic backbone. Single-writer-per-table, audit-grade. Quota math, comp payouts, ASC 606, customer health scoring — anything where a CFO or auditor needs an answer that traces to one source. **Three Brain Agents in L9** — operator-invoked, never on cadence, read Tier 1 services but never write canonical data. AGT-901 cohort, AGT-902 per-account, AGT-903 strategy. **Fourteen Specialist Tools** in Tier 3 — narrow LLM functions the brains call for forecasting, adoption pattern recognition, play composition, cohort retention.

> The line is intentional: **brains propose, humans co-define and approve, services execute.** A brain never bypasses an audit gate."

Click into any **L4** or **L5** layer to show the agent cards inside. Don't dwell — click out.

---

### 2. Brain Outputs (3–4 minutes — *the centerpiece*)

> "Most architecture diagrams stop here. This one keeps going. Here are 14 real outputs from the prototype's brain agents."

Click **Brain Outputs**. Talk over the stat strip:

> "Eleven from AGT-902 — that's the per-account brain. Three from AGT-901 — that's the cohort brain. AGT-903 is the strategy brain, specced but not yet built — that one targets multi-quarter portfolio reasoning. Total spend across all of them: a buck-fifty."

Filter to **AGT-902 (account)**. Then click **EVAL-Q04** (Stark Logistics, expansion_qualification). When the modal opens:

> "This is what the brain produced when AGT-503 fired with consumption overage on this account. Notice the structure — it doesn't just answer the question, it cites every numerical claim. Those `[src:5]` chips? Each one resolves to a real source the brain read. Right here it's TOOL-004's output — that's the consumption forecasting tool. The brain called the tool, got back log-linear R²=0.975, and used that to confirm the consumption pattern is structural, not a spike."

Scroll within the modal to **Tool calls made**:

> "Two tools called: TOOL-004 for consumption trajectory, TOOL-008 for adoption pattern. Both succeeded. The brain decided which tools to call based on the question — not pre-programmed."

Scroll to **Proposed actions**:

> "Each proposed action carries its lever — which Tier 1 service executes — its confidence, and a justification that cites sources. Open expansion play, AGT-503 lever, high confidence."

Scroll to **Eval criteria**:

> "And every fixture passes through a hardness check. Schema compliance, citations resolve, action taxonomy compliant, must-cite-tool, etc. The harness has teeth — there's a separate calibration probe that violates each rule and verifies the validator catches it."

Close the modal. Click **EVAL-Q03** (Strickland Analytics, stalled_onboarding).

> "Different account, different question. Same discipline. Notice this one mentions the data is stale — that's the brain's staleness rule firing. If the view it's reading is more than 24 hours old, it has to disclose. That's eval-enforced."

(If asked: "what about the staleness warnings on most cards?" — answer: "the synth corpus is two days old; in production with real Tier 1 freshness this only fires when actually warranted. Q07 and Q10 are the fixtures that explicitly test the staleness rule.")

---

### 3. Follow a Lead (3 minutes — *the "does it actually work" answer*)

Click **Follow a Lead**.

> "The gallery shows breadth — 14 different questions answered. This shows depth. Two synthetic accounts, walked end-to-end through the system. Same starting point — $221K MM/T1 inbound — opposite outcomes. Let me show you the growth arc first."

Use the sub-tab toggle to confirm **Stark Logistics (growth)** is selected. Walk through the timeline aloud. Don't read every step — hit the milestones:

- **Day -120**: AGT-201 scores ICP (78/100, T1), AGT-202 routes to MM AE West.
- **Day -78**: Discovery booked, AGT-305 generates the brief.
- **Day -52**: AGT-403 surfaces the DataDog competitive concern.
- **Day -22**: Closed Won. AGT-801 hands to AGT-802 for billing.
- **Day -8**: Onboarding kickoff, MAP signed, AGT-104 lifts the comp hold.

Then stop at **Day +120** (the first amber-highlighted brain moment):

> "Four months in. Consumption fires at 2.1× baseline. AGT-503 fires the expansion trigger. RevOps doesn't immediately launch a play — they ask the brain first."

Click **🧠 See the actual brain reasoning — EVAL-Q04 →**

> "This is the same brain output we just looked at in the gallery. It's now in context. The brain reads usage history, calls TOOL-004, calls TOOL-008, and concludes: yes, this is real expansion, but the adoption is siloed by team — port operations is using everything, procurement and 3PL aren't. The play isn't 'sell more seats,' it's 'cross-team integration angle.'"

Close the modal. Continue scrolling:

- **Day +132**: RevOps picks up the SalesPlayLibrary draft, edits the cadence (added in-app, tightened target meeting rate), promotes to active. **Volume cap enforced at write.**
- **Day +150**: AGT-302 executes the play. Procurement intro happens. New $145K opp opens.
- **Day +280**: T-90 renewal. AGT-502 ChurnRiskLog tier=low_risk. AGT-603 schedules QBR.
- **Day +330**: Renewal closed at $355K. NRR = 161%.

> "Here's the full loop. Brain proposes. Human co-defines and approves. Service executes. The lineage from the brain proposal is preserved end-to-end — every action, every play, every outcome traces back to which brain run drafted it. That's what makes the cohort retrospective possible."

If time permits, switch the sub-tab to **Massive Dynamic (decline)** for 30 seconds:

> "Same starting point, defensive arc. Champion departs Day +210. Brain catches the inflection at T-90 renewal, recommends SLM intervention, account renews at $180K — contained loss, not churn. This is the shape of the second arc."

---

### 4. Planning workbench (2.5 minutes — *the "yes that's what I do" tab*)

Click **Planning**.

> "Up to here we've shown what the system *did* on real data. This tab is what your planning meeting feels like in this architecture. Three sub-panels: quota, headcount, territory. Sized for a $400M–$1B ARR business with 80–100 reps. Pull a slider — the math respects all the spec guardrails."

Default tab is **Quota**. Talk over the layout:

> "Net-new ARR target sliders, segment mix, ramp factor. Per AGT-101, quota is **bottom-up** — built from eRep capacity, not divided down from a revenue number. Each segment carries an AE quota multiple from spec: SMB 2.9× of OTE, MM 4.0×, Enterprise 5.7×. Pull the ARR target slider — watch the eRep need recompute and the three board scenarios update: base, conservative −15% eRep, stretch +10%."

Pull the ARR target slider from $150M up to $250M. Let it land:

> "Now look at the guardrails. Coverage ratio — that's AGT-101's spec-mandated rule that org capacity × full quota has to be at least 85% of the revenue target. Drop the ramp factor below 0.85 and watch it fail — that's the same gate AGT-101 enforces before publishing a quota plan to four-gate approval."

Pull ramp factor down to 0.70:

> "Coverage ratio fails. Ramp distribution flag fires too. AGT-901 commentary at the bottom adapts to the current state and surfaces what AGT-101 would do — block the publish, route to RevOps."

Click the **Headcount** sub-tab:

> "ARR target carries over — same number from the quota panel. AGT-105 reconciles three independent guardrails: Magic Number, Rule of 40, CAC Payback. The most-conservative signal becomes the binding constraint, highlighted in gold. Pull the FCF margin negative and watch R40 flip from 'invest' to 'backfill only' — that becomes the binding constraint and gates net-new hiring."

Pull FCF margin to −0.05:

> "Hiring constrained to backfill only. The underlying math is straight from the spec — you can verify each formula by hovering the metric cards in the WBR tab next."

Click the **Territory** sub-tab:

> "AGT-106. Sixty territories at default — not 1:1 with reps; at this size, named-account reps cover multiple accounts. Equity weighting slider controls whether you're optimizing for account count or ACV potential. Gini coefficient measures imbalance. Workload outlier flag fires per AGT-106's 1.5 SD rule."

Move the equity weighting slider fully to ACV:

> "Watch the Gini recompute against ACV potential and the outlier count update. AGT-106 enforces the routing_eligible gate — LOA, PIP, assignment_active, capacity — strict AND. Reps that fail any one are removed from routing entirely. That's a real gate, not a softer 'preference.'"

---

### 5. Forecast & WBR (1.5 minutes — *the readout*)

Click **Forecast & WBR**.

Default sub-tab is **Forecast**:

> "AGT-402 bottoms-up plus AGT-404 top-down plus rep commit plus FP&APlan target. Three lenses, one decision. Per AGT-402's v23 spec ripple, bottoms-up decomposes into three components — new logo, renewal, and expansion ACV. Expansion ACV is churn-risk-weighted: Low risk gets 80% weight, Medium 50%, High zero. Pull the risk-mix slider and watch the expansion contribution change."

Pull stage calibration to 0.80:

> "Win rates 20% softer than baseline. Plan-pct drops. Rep commit doesn't move because rep commit is sacred per AGT-402 spec — the brain models it separately, never overrides."

Click the **WBR** sub-tab:

> "This is what AGT-704 produces. Five canonical AGT-702 metrics. Hover any card for the formula. NRR target is 110% per AGT-702 spec — never changes. GRR target is 85% — never changes. Magic Number, Rule of 40, CAC Payback. Each carries plan-vs-actual delta and a status color tied to spec thresholds. Below that, AGT-703 win-loss patterns and a brain narrative banner that adapts to the metric state. The narrative is what AGT-704 stitches together for the MBR."

---

### 6. Closing (60 seconds)

> "Five things matter here:
> 1. **The deterministic backbone is sacred.** Quota math, comp, rev rec — all stay deterministic. Auditors and the CFO sleep at night.
> 2. **The brain layer is operator-invoked, not on cadence.** It costs about a buck-fifty per fourteen brain runs. We can run this on demand without exploding token spend.
> 3. **Humans are the safety mechanism.** The brain never executes a play. It drafts, humans curate, the volume cap is enforced at activation. You can't get a runaway agent in this architecture by design.
> 4. **The planning meeting is interactive.** Pulling sliders moves the math through every spec guardrail. This isn't a static deck — this is what running the meeting feels like.
> 5. **Strategy reasoning is specced but build-deferred.** AGT-903 covers the multi-quarter, portfolio-bet questions — ICP rewrites, vertical entry, capacity reallocation. Endorsement requires CRO + CFO + sometimes CEO; endorsement triggers a human-led workstream, never a direct table edit.
>
> The system is ready to test against real data. Here's the migration path."

Open `prototype/PORT_TO_CORPORATE.md` in another tab if they want to dig in.

---

## If the CRO asks the predictable hard questions

**"Won't the brain hallucinate?"**
> The harness has a `must_cite_tool` rule — every numerical claim cites a source. Hallucinations show up as unresolved `[src:N]` chips and the validator catches them. A standing calibration probe verifies the validator catches them — five probes, all passing. We never trust the brain's narrative; we trust the harness that scores the brain.

**"What about the cost at scale?"**
> Brain calls are operator-invoked, not on cadence. The 14-run sweep cost $1.50. If you ran it 500 times a day across the whole org, that's $50/day, $1,500/month — well under one analyst FTE. AGT-903 strategy queries are heavier per-call (Opus default, multi-quarter context) but rare — annual planning, board prep, mid-year inflection — sized for 10–30 queries/month at ~$300/month budget. All bounded with hard ceilings + 75% budget alerts per tier.

**"How do you stop this from drifting over time?"**
> The 30-question retrospective harness runs quarterly. If accuracy slips, you investigate before promoting any new capability. That's pre-launch gating, not post-hoc cleanup.

**"How long to wire this to our real warehouse?"**
> The prototype already has a `BrainViewSource` interface. Synth source today, warehouse source tomorrow — single subclass + one factory branch, no brain code changes. Phase plan in `prototype/PORT_TO_CORPORATE.md` walks Phase 0 (eval baseline against real accounts) through Phase 5 (brain agents go live). AGT-903 build adds a separate prerequisite — `strategy_brain_view` extensions on ten Tier 1 services, plus the cohort/LTV Tier 3 tools (TOOL-013, TOOL-014).

**"Can a brain accidentally publish bad plays?"**
> No. AGT-901 / AGT-902 write `draft` rows only to SalesPlayLibrary; AGT-903 writes drafts to StrategyRecommendationLog. Each has its own state machine. SalesPlayLibrary requires SLM + RevOps joint approval to transition `under_review → active`; AGT-302 reads only `active` plays. There's also a hard volume cap per segment per quarter — typically 3–8 plays. StrategyRecommendationLog endorsement requires CRO + CFO + (CEO if material) and triggers a human-led workstream, not a direct table edit anywhere.

**"What's actually built vs. just specced?"**
> Built (production-deployed): all 40 L1–L8 services. Prototyped (runtime exists, evals pass, not yet on real data): AGT-901 + AGT-902 brain agents, 4 of the 14 tools (TOOL-003 sales play composer, TOOL-004 consumption forecasting, TOOL-008 adoption pattern recognizer, TOOL-010 champion movement detector). Specced only: AGT-903 strategy brain (build deferred pending strategy_brain_view extensions + Tier 3 cohort tools), 10 of the 14 tools.

**"What's the planning tab actually doing — is it real, or just JS?"**
> Pure JS, deterministic. Every formula is grounded in spec — AE quota multiples from AGT-101 (2.9× / 4.0× / 5.7×), three guardrails from AGT-105 (Magic Number, R40, CAC Payback), Gini-style equity from AGT-106, expansion ACV churn-risk weights from AGT-402 v23 ripple. Phase 2 (deferred, requires AGT-903 build + API budget) replaces the pre-baked brain commentary banners with live AGT-901 / AGT-903 calls, so the brain critiques your slider state in real time.

---

## What NOT to show in a CRO demo

- **The Connection Map tab.** It's accurate but it's a wall of nodes — looks like a static blueprint, doesn't add to the "does it work" story. Keep it for engineering audiences.
- **The OS tab** if time-constrained. It's the full agent-spec catalog — useful for self-service exploration after the call, not for live walkthrough.
- **The ICP Scorer Demo.** It's a deterministic JS recreation of the ICP scoring math. CROs aren't there for math; they're there for "does this work end-to-end." If they specifically ask "how does ICP scoring work," then you can pop into it.
- **The repo source code.** They don't need to see Python. Stay in the explainer.
- **All five Planning + Forecast/WBR sub-panels at once.** Pick one or two slider moments per panel. The point is to show interactivity, not to walk every formula.

---

## Target-profile flex — when the CRO is a consumption-pricing developer-led platform

If the CRO comes from a per-token / per-message / per-API-call platform with multi-tier product mix, **lead with v38 capabilities** rather than the generic walkthrough. The OS is built generic but v38 added the surface they care about.

**The framing sentence:**
> "Tokens-as-product, margin-as-business-model, developer-led funnel. The OS has all of this in v38 — it's not a custom build, it's the spec surface for any consumption-pricing tiered-platform business."

**Tabs to lean into (in this order):**

1. **Architecture → AGT-208 Developer Signal Scorer.** Open the spec card. *"The funnel intake your AEs see today is broken by design — your customers enter as developers months before any sales touch. AGT-208 scores those developers on enterprise-progression signal across 5 dimensions: consumption velocity, production signal (deployment to dedicated infra, p95 latency queries, idempotency keys), enterprise context (corp email domain, multi-developer presence at same domain), commercial intent (pricing-page traffic, billing inquiries, security/compliance docs), stakeholder breadth. Domain-aggregates so 5 mid-score developers at the same org elevate together. Routes to AEs with motion=plg-warm — different cadence than your traditional inbound."*

2. **Architecture → AGT-503 v38 tier-migration play type.** *"Your margin-expansion strategy runs through customers migrating from low-margin tier (e.g., shared/serverless) to higher-margin tier (e.g., dedicated, then bring-your-own-cloud control plane). v38 makes that a first-class expansion motion. AGT-503 fires a tier_migration play with TOOL-015's GP-uplift projection pre-filled, plus a required credible-alternative articulation for the AM. Distinct from ARR-uplift expansion — ARR may stay flat or even dip slightly during a successful migration. The play retires against a different quota measure (GP) — see AGT-101 v38."*

3. **Architecture → AGT-101 + AGT-103 v38 GP-overlay comp.** *"This is the highest-leverage spec change in v38. Your current comp ($X/logo + N% ACV equivalent) actively pushes reps away from the margin-expansion strategy — they optimize for fast logo close on the lowest-margin tier. v38 adds a parallel GP quota with a configurable ARR/GP split (e.g., 60/40 for new-business, 40/60 for AMs running tier-migration). Reps can now retire quota against tier-migration plays even when ARR delta is flat. Anti-gaming guard: high combined attainment with low ARR fires a manual review flag."*

4. **Tools_Index → TOOL-015 Consumption-Margin Decomposer.** *"This is the cognition that makes the rest work. Per-customer GP decomposition into pricing / utilization / backend-cost / tier-mix axes. Refusal-first when backend cost data is incomplete — estimation here would propagate into bad expansion decisions. Generic across consumption businesses; tokens are configuration, not contract."*

5. **Planning tab.** *"The defaults are sized for $400M-$1B ARR with 80-100 reps — but pull the ARR slider up to your target (e.g., $300M net-new for a $1B-by-Y2 trajectory). Watch the eRep math; watch the Magic Number / R40 / CAC Payback guardrails."*

6. **Forecast & WBR tab → WBR.** *"AGT-704 narrative banner is what your weekly readout could feel like — five canonical metrics + adaptive narrative that surfaces what's failing or what's on track."*

**The strategic-question landings (use one or two):**

- *"Tokens are the product, and the GTM motion has to be built around token economics the same way Twilio's was built around message and minute economics. The OS has this — UBB metering, per-customer GP attribution via TOOL-015, GP-overlay comp aligned to it."*
- *"The moat isn't inference speed alone — it's the control plane, the enterprise trust layer, and the switching costs that compound over time. The OS makes BYOC migration and control-plane integration a first-class motion (AGT-503 tier-migration + AGT-602 technical implementation gates) rather than an afterthought."*
- *"You've got 11 whales today and you want 1,000 customers at $250K average. That's a segmentation and capacity planning problem the OS treats as Strategy Brain (AGT-903) territory — propose_segment_redefinition, propose_capacity_reallocation, with multi-quarter cohort views and a CRO + CFO endorsement gate."*

**Hypergrowth ramp framing (if asked about 100-200 rep hiring trajectory):**
The Planning panel handles this in shape but defaults assume reps are already in place. For a 5 → 200 ramp: *"You're not running a capacity-plan in the classic sense — you're running an investment-runway plan with hire-velocity bottlenecks and ramp-overlap risk. The OS has the math (AGT-105 attrition + ramp curves) but the operating mode is different — pre-revenue investment lag, sourcing capacity as the constraint, and territory dilution as you split coverage to absorb new bodies. v38.1 will add an explicit hypergrowth scenario on the Planning panel — for now, anchor the conversation on AGT-105's three guardrails (Magic Number, R40, CAC Payback) and what each one says about how aggressively you can hire."*

**No customer naming.** The OS is generic. Whether the CRO leads an AI inference platform, a comms API, a payments processor, or a usage-priced data platform — the same v38 capabilities apply. Frame it as a class of company, not a specific company.

---

## v38.5 control-axis insight — when their product has multi-tier control levels

Some developer-led platforms organize their product around three control tiers — *fully managed* (give me an API and let me ship), *off-the-shelf workflows* (cookbook-style paths, e.g. SFT / DPO / GRPO), *low-level control* (custom Python loop, forward / forward_backward / optim_step). Different customers want different levels; the same customer's needs evolve as their ML team matures.

**The structural insight:** segmentation isn't firmographic — it's *level of control / technical sophistication*. Three sub-businesses sharing infrastructure: fully_managed competes against hyperscaler bundle (large TAM, low margin), off_the_shelf competes against workflow AI (mid TAM, mid margin), low_level_control competes against self-hosted vLLM + frontier-model-provider direct (small TAM, highest margin, deepest moat).

**Lead with v38.5 capabilities** when the CRO describes a product surface like this:

1. **AGT-201 v38.5 `gtm_motion_class`.** *"Your sales motion shape differs by control tier. The OS classifies each account on the control axis (managed / off-shelf / low-level) parallel to the firmographic T1/T2/T3 tier — and routes to AE pools designed for that motion. T1-fit + low_level_control gets paired with AGT-602 from week 1; T1-fit + fully_managed gets a demo-led short-cycle pool. The same customer can be both — sales motion matches buying motion, not generic firmographic match."*

2. **AGT-503 v38.5 two-axis tier-migration.** *"v38 modeled tier-migration on the margin axis (shared → dedicated → BYOC). v38.5 recognizes a parallel control axis (managed → off-shelf → low-level) that drives a distinct motion. Customer might be on shared infrastructure (low margin) AND fully managed (control axis) — two independent expansion paths. The OS treats each axis as a first-class motion with its own play type, its own technical-prerequisite gate, its own credible_alternative pre-fill."*

3. **AGT-205 v38.5 control-tier breakdown.** *"TAM/SAM is now a 2D matrix — product-family × control-tier — because each control_tier is a different sub-business with different competitive dynamics, different ARPU, different GM. Sizing them as one number obscures the strategic question. AGT-903 capacity-reallocation queries return per-control-tier rep allocation recommendations against this matrix."*

**The strategic-question landing:**
- *"Your three control tiers have very different competitive dynamics — fully_managed competes against AWS Bedrock procurement-friction, low_level_control competes against open-source vLLM. Same go-to-market motion across all three is a strategic mistake. The OS makes that visible at AGT-205 sizing time, drives motion-match at AGT-202 routing time, and incentivizes both axes of expansion at AGT-101 v38 + AGT-503 v38.5."*

---

## Talking points if they go quiet

- "This started as a spec exercise. The point of the brain prototype is to validate that the contracts hold under real reasoning load — not to ship a product."
- "Every fixture you saw in the gallery is captured verbatim from `prototype/brain_analysis_log.jsonl` — these aren't hand-curated demo answers, they're whatever the eval harness produced last."
- "The synth corpus has 8 archetypes — power user, activating, surface_only, champion_loss_decliner, expansion_ready, spike_then_crash, seasonal, stalled_onboarding. Brain handles all of them. That's the breadth answer."
- "The Planning tab is sized for your scale — $400M–$1B ARR, 80–100 reps. Default sliders are net-new ARR, not total revenue, because that's what reps actually work against. If your numbers are different, pull the sliders to match."
- "The third brain — AGT-903 — is the most architecturally interesting part of v37. Strategy reasoning has the highest stakes (ICP, vertical entry, capacity bets) but also the longest feedback loop. Endorsement triggers a human-led workstream, not a table edit. That's a deliberate design — strategic decisions stay with humans even after AI recommends."
