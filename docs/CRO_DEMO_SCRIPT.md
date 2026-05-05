# CRO Demo Script — gtm-os

**Goal:** in 8–12 minutes, show a CRO that gtm-os is (a) a coherent architecture and (b) a *working system* that produces real reasoning on real-shaped data.

The repo has six explainer tabs. Click them in **this order**, or you'll tell a worse story:

> Architecture → Brain Outputs → Follow a Lead → (optional) The OS / Connection Map / ICP Scorer Demo

---

## Pre-flight (do this 5 minutes before the call)

1. Open https://thekasser.github.io/gtm-os/gtm_os_explainer.html in a fresh tab
2. Click **Brain Outputs** — confirm the gallery loads (14 cards visible)
3. Click any card — confirm modal opens with `[src:N]` chips visible inline in the narrative
4. Press Esc to close, click **Follow a Lead** — confirm the timeline loads with the 7-stat header strip
5. Scroll to Day +120 — confirm the amber "🧠 See the actual brain reasoning — EVAL-Q04 →" button is visible
6. Click it — confirm modal opens with EVAL-Q04 brain output

If any of those fail, the live Pages build is broken. Stop and ping the engineer (you).

---

## The 8-minute pitch

### 1. Architecture (90 seconds)

> "This is gtm-os. It's three tiers across ten layers. **Forty GTM Services** in L1 through L8 — these are the deterministic backbone. Single-writer-per-table, audit-grade. Quota math, comp payouts, ASC 606, customer health scoring — anything where a CFO or auditor needs an answer that traces to one source. **Two Brain Agents in L9** — operator-invoked, never on cadence, read Tier 1 services but never write canonical data. **Twelve Specialist Tools** in Tier 3 — narrow LLM functions the brains call for forecasting, adoption pattern recognition, play composition.

> The line is intentional: **brains propose, humans co-define and approve, services execute.** A brain never bypasses an audit gate."

Click into any **L4** or **L5** layer to show the agent cards inside. Don't dwell — click out.

---

### 2. Brain Outputs (3–4 minutes — *the centerpiece*)

> "Most architecture diagrams stop here. This one keeps going. Here are 14 real outputs from the prototype's brain agents."

Click **Brain Outputs**. Talk over the stat strip:

> "Eleven from AGT-902 — that's the per-account brain. Three from AGT-901 — that's the cohort brain. Total spend across all of them: a buck-fifty. Each card is a question someone might actually ask the system."

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

> "The gallery shows breadth — 14 different questions answered. This shows depth. One synthetic account, MM/FinTech, walked end-to-end through the system from inbound lead to renewal. Stark Logistics — 14-month contract starting at $221K, ends at $355K, 161% NRR."

Walk through the timeline aloud. Don't read every step — hit the milestones:

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

---

### 4. Closing (60 seconds)

> "Three things matter here:
> 1. **The deterministic backbone is sacred.** Quota math, comp, rev rec — all stay deterministic. Auditors and the CFO sleep at night.
> 2. **The brain layer is operator-invoked, not on cadence.** It costs about a buck-fifty per fourteen brain runs. We can run this on demand without exploding token spend.
> 3. **Humans are the safety mechanism.** The brain never executes a play. It drafts, humans curate, the volume cap is enforced at activation. You can't get a runaway agent in this architecture by design.
>
> The system is ready to test against real data. Here's the migration path."

Open `prototype/PORT_TO_CORPORATE.md` in another tab if they want to dig in.

---

## If the CRO asks the predictable hard questions

**"Won't the brain hallucinate?"**
> The harness has a `must_cite_tool` rule — every numerical claim cites a source. Hallucinations show up as unresolved `[src:N]` chips and the validator catches them. A standing calibration probe verifies the validator catches them — five probes, all passing. We never trust the brain's narrative; we trust the harness that scores the brain.

**"What about the cost at scale?"**
> Brain calls are operator-invoked, not on cadence. The 14-run sweep cost $1.50. If you ran it 500 times a day across the whole org, that's $50/day, $1,500/month — well under one analyst FTE. And it's bounded with hard ceilings + 75% budget alerts per tier.

**"How do you stop this from drifting over time?"**
> The 30-question retrospective harness runs quarterly. If accuracy slips, you investigate before promoting any new capability. That's pre-launch gating, not post-hoc cleanup.

**"How long to wire this to our real warehouse?"**
> The prototype already has a `BrainViewSource` interface. Synth source today, warehouse source tomorrow — single subclass + one factory branch, no brain code changes. Phase plan in `prototype/PORT_TO_CORPORATE.md` walks Phase 0 (eval baseline against real accounts) through Phase 5 (brain agents go live).

**"Can a brain accidentally publish bad plays?"**
> No. Brains write `draft` rows only. The state machine requires SLM + RevOps joint approval to transition `under_review → active`. AGT-302 reads only `active` plays. There's also a hard volume cap per segment per quarter — typically 3-8 plays. Brains can't proliferate plays even if they wanted to.

**"What's actually built vs. just specced?"**
> Built (production-deployed): all 40 L1-L8 services. Prototyped (runtime exists, evals pass, not yet on real data): both brain agents, 3 of the 12 tools (TOOL-003 sales play composer, TOOL-004 consumption forecasting, TOOL-008 adoption pattern recognizer). Specced only: the other 9 tools.

---

## What NOT to show in a CRO demo

- **The Connection Map tab.** It's accurate but it's a wall of nodes — looks like a static blueprint, doesn't add to the "does it work" story. Keep it for engineering audiences.
- **The OS tab** if time-constrained. It's the full agent-spec catalog — useful for self-service exploration after the call, not for live walkthrough.
- **The ICP Scorer Demo.** It's a deterministic JS recreation of the ICP scoring math. CROs aren't there for math; they're there for "does this work end-to-end." If they specifically ask "how does ICP scoring work," then you can pop into it.
- **The repo source code.** They don't need to see Python. Stay in the explainer.

---

## Talking points if they go quiet

- "This started as a spec exercise. The point of the brain prototype is to validate that the contracts hold under real reasoning load — not to ship a product."
- "Every fixture you saw in the gallery is captured verbatim from `prototype/brain_analysis_log.jsonl` — these aren't hand-curated demo answers, they're whatever the eval harness produced last."
- "The synth corpus has 8 archetypes — power user, activating, surface_only, champion_loss_decliner, expansion_ready, spike_then_crash, seasonal, stalled_onboarding. Brain handles all of them. That's the breadth answer."
