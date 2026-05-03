"""Eval harness fixtures.

Each fixture tests AGT-902 against one corpus account with one question and a
defined set of pass criteria. The eval scorer iterates over FIXTURES, runs the
brain on each, and reports per-criterion pass/fail.

Three starter fixtures are written below. To add the remaining 7, copy the
TEMPLATE at the bottom and fill in:
  - account_selection (which corpus account)
  - question
  - expected_diagnosis (what the brain should catch)
  - expected_actions (what actions are right / wrong)
  - pass_criteria (thresholds)
  - fixture_mutations (optional — for stale-data fixtures only)

Aim for ~3 churn diagnoses, ~2 expansion qualifications, ~2 hand-off briefings,
~1 plan-diagnosis-style question, and 1 more stale fixture (5 stale fixtures
total per the AGT-902 spec catalog). Mix difficulty: a few easy cases, a few
trap cases, all 5 stale.
"""

from __future__ import annotations


# ─────────────────────────────────────────────────────────────────────
# FIXTURE 1 — Easy diagnostic on champion_loss_decliner
# ─────────────────────────────────────────────────────────────────────

EVAL_Q01_CHURN_DIAGNOSIS = {
    "fixture_id": "EVAL-Q01",
    "question_type": "churn_diagnosis",
    "difficulty": "easy",

    "account_selection": {
        "method": "by_archetype",
        "archetype": "champion_loss_decliner",
        "index": 0,
    },

    "question": "Why is this account at renewal risk and what's the play?",

    "expected_diagnosis": {
        "primary_drivers": [
            "champion_departure",
            "usage_decline",
            "non_renewal_decision_documented",
        ],
        "min_drivers_matched": 2,
        "should_mention": [
            "champion",
            "non-renewal",
            "decline",
        ],
        "should_not_mention": [],
    },

    "expected_actions": {
        "must_include_at_least_one_of": [
            "escalate_to_slm",
            "customer_communication",
        ],
        "must_not_include": [
            "open_expansion_play",
        ],
    },

    "pass_criteria": {
        "schema_compliance":           True,
        "citations_resolve":           True,
        "action_taxonomy_compliant":   True,
        "min_citation_count":          10,
        "diagnosis_match_pass":        True,
        "expected_actions_pass":       True,
    },

    "comment": (
        "Easy churn-diagnosis case. Champion-departure inflection is well-documented in "
        "the synthetic conversation log; brain should identify it directly and propose "
        "executive-level intervention rather than expansion."
    ),
}


# ─────────────────────────────────────────────────────────────────────
# FIXTURE 2 — surface_only_adopter renewal positioning (medium difficulty)
# ─────────────────────────────────────────────────────────────────────

EVAL_Q02_SURFACE_ONLY_RENEWAL = {
    "fixture_id": "EVAL-Q02",
    "question_type": "churn_diagnosis",
    "difficulty": "medium",

    "account_selection": {
        "method": "by_archetype",
        "archetype": "surface_only_adopter",
        "index": 0,
    },

    "question": (
        "How is this account positioned for renewal? "
        "What does the renewal team need to know?"
    ),

    "expected_diagnosis": {
        "primary_drivers": [
            "shallow_adoption_depth",
            "competitive_or_pricing_pressure",
            "narrow_roi_justification",
        ],
        # Need both dimensions visible: at least one depth-keyword + one pressure-keyword
        # Implemented as flat list — relies on brain hitting >=2 across the list
        "min_drivers_matched": 2,
        "should_mention": [
            # Depth dimension keywords
            "shallow",
            "limited",
            "narrow",
            "surface",
            "adoption",
            # Pressure dimension keywords
            "pricing",
            "budget",
            "competitive",
            "alternative",
            "evaluation",
        ],
        # Empty: avoid the EVAL-Q05-style false-positive trap where the brain
        # correctly negates a phrase but substring-matching fires anyway.
        # Wrong-direction is captured via expected_actions.must_not_include.
        "should_not_mention": [],
    },

    "expected_actions": {
        # Any retention-flavored action is appropriate here. The teeth of the
        # fixture: brain MUST propose at least one renewal-defense action.
        "must_include_at_least_one_of": [
            "escalate_to_slm",
            "customer_communication",
            "pull_qbr_forward",
            "brief_new_ae_or_csm",
        ],
        # NOTE: previously this had `must_not_include: [open_expansion_play]`
        # to catch naive auto-expansion. Removed after a real run showed the
        # brain proposing a *contingent* expansion play justified by a champion-
        # mentioned Q2 pilot in the conversation log — that's well-reasoned, not
        # auto-expansion. The must_include rule above still ensures retention
        # actions dominate the response.
        "must_not_include": [],
    },

    "pass_criteria": {
        "schema_compliance":           True,
        "citations_resolve":           True,
        "action_taxonomy_compliant":   True,
        "min_citation_count":          15,
        "diagnosis_match_pass":        True,
        "expected_actions_pass":       True,
    },

    "comment": (
        "Tests whether the brain reads adoption depth (from conv_intel) as a renewal "
        "risk despite reassuring surface metrics. The trap: Yellow tier stable + on-time "
        "payments + consistent usage looks fine in isolation. Real risk lives in the "
        "conversation log — narrow feature adoption, competitive evaluation signals, "
        "pricing pressure. Catches: (a) brain that auto-expands on stable usage, "
        "(b) brain that misclassifies as healthy because of payment behavior, "
        "(c) brain that diagnoses on health-score alone without reading conv_intel."
    ),
}


# ─────────────────────────────────────────────────────────────────────
# FIXTURE 3 — stalled_onboarding diagnosis (structural failure)
# ─────────────────────────────────────────────────────────────────────

EVAL_Q03_STALLED_ONBOARDING = {
    "fixture_id": "EVAL-Q03",
    "question_type": "churn_diagnosis",
    "difficulty": "medium",

    "account_selection": {
        "method": "by_archetype",
        "archetype": "stalled_onboarding",
        "index": 0,
    },

    "question": (
        "This onboarding looks stalled. What's going on and what's the play to "
        "recover or retire?"
    ),

    "expected_diagnosis": {
        "primary_drivers": [
            "structural_blockers_not_just_low_engagement",
            "missing_executive_sponsor_or_project_owner",
            "specific_implementation_or_scope_blocker",
        ],
        # Need >= 3 keywords across the three dimensions to demonstrate the brain
        # diagnosed structurally, not symptomatically
        "min_drivers_matched": 3,
        "should_mention": [
            # Structural diagnosis depth (brain went past "low usage")
            "structural",
            "root cause",
            "compounding",
            # Specific blocker references
            "blocker",
            "blocking",
            "scope",
            "integration",
            "implementation",
            # Sponsor/owner gap
            "sponsor",
            "executive",
            "owner",
            # Process gap
            "next step",
            "showstopper",
            # Recovery vs retire framing
            "recover",
            "retire",
        ],
        "should_not_mention": [],
    },

    "expected_actions": {
        # Recovery requires escalation + structured intervention
        "must_include_at_least_one_of": [
            "escalate_to_slm",
            "customer_communication",
            "brief_new_ae_or_csm",
            "recommend_human_query",
        ],
        # Trap: brain shouldn't propose expansion on a Red account that hasn't activated
        "must_not_include": [
            "open_expansion_play",
        ],
    },

    "pass_criteria": {
        "schema_compliance":           True,
        "citations_resolve":           True,
        "action_taxonomy_compliant":   True,
        # stalled_onboarding accounts have less data (fewer calls, shorter usage history)
        # so citation count threshold is lower than for mature accounts
        "min_citation_count":          12,
        "diagnosis_match_pass":        True,
        "expected_actions_pass":       True,
    },

    "comment": (
        "Tests whether the brain diagnoses STRUCTURAL onboarding failure rather "
        "than symptomatic 'low engagement.' The trap: a naive brain reads 'usage low, "
        "calls neutral-to-negative' and recommends 'more outreach.' The real diagnosis: "
        "no executive sponsor, IT blocking access, unresolved scope/integration "
        "objections, no next step committed across two attempts. Recovery requires "
        "escalation + executive sponsor mapping, not more CSM emails. Catches: "
        "(a) brain that diagnoses symptoms not causes, (b) brain that proposes "
        "engagement-style action when structural intervention is needed, "
        "(c) brain that ignores the not_in_corpus framing and fabricates onboarding data."
    ),
}


# ─────────────────────────────────────────────────────────────────────
# FIXTURE 4 — expansion_ready / real expansion confirmed (inverse of Q05)
# ─────────────────────────────────────────────────────────────────────

EVAL_Q04_REAL_EXPANSION_CONFIRMED = {
    "fixture_id": "EVAL-Q04",
    "question_type": "expansion_qualification",
    "difficulty": "medium",

    "account_selection": {
        "method": "by_archetype",
        "archetype": "expansion_ready",
        "index": 0,
    },

    "question": (
        "AGT-503 fired with consumption overage on this account. "
        "Is this real expansion, and what's the play?"
    ),

    "expected_diagnosis": {
        "primary_drivers": [
            "sustained_overage_pattern",
            "qualitative_stakeholder_validation",
            "multi_team_or_executive_engagement",
        ],
        "min_drivers_matched": 3,
        "should_mention": [
            # Sustained-pattern keywords (brain distinguishes from spike)
            "sustained",
            "consistent",
            "structural",
            "monotonic",
            "trajectory",
            # Stakeholder validation keywords (qualitative confirmation in calls)
            "champion",
            "executive",
            "stakeholder",
            "cfo",
            # Quantitative growth language
            "growth",
            "expansion",
            "multi-team",
            "cross-team",
        ],
        "should_not_mention": [],
    },

    "expected_actions": {
        # THE POSITIVE TEST: brain MUST propose expansion when evidence is strong.
        # This is the inverse of EVAL-Q05 — there the brain must NOT propose expansion
        # on a fake signal; here the brain MUST propose expansion on a real signal.
        # Failure to do so = brain too cautious / under-confident.
        "must_include_at_least_one_of": [
            "open_expansion_play",
        ],
        "must_not_include": [],
    },

    "pass_criteria": {
        "schema_compliance":           True,
        "citations_resolve":           True,
        "action_taxonomy_compliant":   True,
        "min_citation_count":          15,
        "diagnosis_match_pass":        True,
        "expected_actions_pass":       True,
    },

    "comment": (
        "Inverse of EVAL-Q05. Tests that the brain is decisive when evidence is "
        "strong, not just when evidence is absent. expansion_ready accounts have "
        "sustained overage, qualitative stakeholder validation in conversation, "
        "and multi-team/executive engagement — all the signals AGT-902 should "
        "confidently act on. The trap: a brain that's been tuned to be cautious "
        "(via prompts emphasizing 'don't fabricate') may become under-confident "
        "even when evidence is strong, defaulting to recommend_human_query and "
        "skipping open_expansion_play. EVAL-Q05 + EVAL-Q04 together calibrate the "
        "brain's confidence: not too quick to expand on spikes (Q05), not too slow "
        "to expand when expansion is real (Q04)."
    ),
}


# ─────────────────────────────────────────────────────────────────────
# FIXTURE 6 — handoff briefing on champion_loss_decliner
# (different question type — synthesis, not just diagnosis)
# ─────────────────────────────────────────────────────────────────────

EVAL_Q06_HANDOFF_BRIEFING = {
    "fixture_id": "EVAL-Q06",
    "question_type": "handoff_briefing",
    "difficulty": "medium",

    "account_selection": {
        "method": "by_archetype",
        "archetype": "champion_loss_decliner",
        "index": 0,
    },

    "question": (
        "A new AE just rotated onto this account today. Brief them on what they're "
        "walking into and what to do first."
    ),

    "expected_diagnosis": {
        "primary_drivers": [
            "champion_departure_pivotal_event",
            "current_state_non_renewal_or_at_risk",
            "competitor_evaluation_in_progress",
        ],
        # Need 3+ keywords across timeline arc + current state + actions
        "min_drivers_matched": 3,
        "should_mention": [
            # Champion-departure framing (required for this archetype)
            "champion",
            "departed",
            "departure",
            # Current state (non-renewal / churn intent confirmed)
            "non-renewal",
            "renewal",
            "intent",
            # Competitive signals
            "competitor",
            "competitive",
            "evaluation",
            # Timeline / structured briefing language
            "timeline",
            "history",
            "arc",
            "story",
            # Recovery / acceptance posture
            "recovery",
            "intervention",
        ],
        "should_not_mention": [],
    },

    "expected_actions": {
        # A handoff briefing should propose at least one concrete next step
        # (not just 'none'). Multiple appropriate options for a churning account.
        "must_include_at_least_one_of": [
            "escalate_to_slm",
            "customer_communication",
            "recommend_human_query",
            "brief_new_ae_or_csm",
        ],
        # No expansion appropriate
        "must_not_include": [
            "open_expansion_play",
        ],
    },

    "pass_criteria": {
        "schema_compliance":           True,
        "citations_resolve":           True,
        "action_taxonomy_compliant":   True,
        # Handoff briefings reference more sources, expect more citations
        "min_citation_count":          20,
        "diagnosis_match_pass":        True,
        "expected_actions_pass":       True,
    },

    "comment": (
        "Tests handoff_briefing question type — a structurally different ask than "
        "churn_diagnosis. The brain has to produce a SYNTHESIS (timeline arc, "
        "current state, what-to-do-first) not just a diagnosis. Reuses the "
        "champion_loss_decliner archetype as EVAL-Q01 but tests a different "
        "synthesis style. Catches: (a) brain that just narrates without structure, "
        "(b) brain that omits the most important context (champion departure as "
        "pivotal event), (c) brain that gives the new AE no concrete next step."
    ),
}


# ─────────────────────────────────────────────────────────────────────
# FIXTURE 8 — QBR narrative on ideal_power_user
# (different question type — narrative quality, not diagnosis)
# ─────────────────────────────────────────────────────────────────────

EVAL_Q08_QBR_NARRATIVE = {
    "fixture_id": "EVAL-Q08",
    "question_type": "qbr_narrative",
    "difficulty": "medium",

    "account_selection": {
        "method": "by_archetype",
        "archetype": "ideal_power_user",
        "index": 0,
    },

    "question": (
        "Generate the per-account narrative section for this account's next QBR. "
        "Focus on highlights from the past 90 days, current health and usage "
        "trajectory, anything needing leadership attention, and recommended "
        "discussion topics."
    ),

    "expected_diagnosis": {
        "primary_drivers": [
            "structured_narrative_with_sections",
            "ninety_day_window_anchored",
            "quantified_value_delivered",
        ],
        "min_drivers_matched": 3,
        "should_mention": [
            # Structure markers (brain produces sectioned output)
            "snapshot",
            "highlights",
            "summary",
            "review",
            # Time-anchored framing
            "90 days",
            "trailing",
            "past 90",
            # Health/business context (positive frame)
            "health",
            "trajectory",
            # Value language for QBR audience
            "milestone",
            "achievement",
            "delivered",
            # Discussion / leadership prompts
            "discussion",
            "topic",
            "leadership",
        ],
        "should_not_mention": [],
    },

    "expected_actions": {
        # For an ideal_power_user QBR, the brain should propose
        # expansion or QBR-flow actions, not retention/escalation
        "must_include_at_least_one_of": [
            "open_expansion_play",
            "pull_qbr_forward",
            "customer_communication",
        ],
        # Note: not adding escalate_to_slm to must_not_include because brain
        # might find a real flag in the QBR data and want to escalate. Trust
        # the diagnosis_match check to catch wrong-framing.
        "must_not_include": [],
    },

    "pass_criteria": {
        "schema_compliance":           True,
        "citations_resolve":           True,
        "action_taxonomy_compliant":   True,
        # QBR narratives should be heavily-cited (each claim about the past 90 days
        # should reference data)
        "min_citation_count":          20,
        "diagnosis_match_pass":        True,
        "expected_actions_pass":       True,
    },

    "comment": (
        "Tests qbr_narrative question type — different shape than diagnosis. The "
        "brain has to produce a STRUCTURED, EXECUTIVE-FACING narrative anchored to "
        "the past 90 days, with quantified value delivered, current state, and "
        "discussion-topic recommendations. Catches: (a) brain that produces a "
        "diagnostic-style monologue instead of a structured narrative, (b) brain "
        "that ignores the 90-day window framing and gives a full-contract recap, "
        "(c) brain that fabricates QBR history when not_in_corpus, (d) brain that "
        "frames a healthy account in retention/risk language."
    ),
}


# ─────────────────────────────────────────────────────────────────────
# FIXTURE 9 — seasonal / false-risk diagnosis (the seasonality trap)
# ─────────────────────────────────────────────────────────────────────

EVAL_Q09_SEASONAL_FALSE_RISK = {
    "fixture_id": "EVAL-Q09",
    "question_type": "churn_diagnosis",
    "difficulty": "hard",

    "account_selection": {
        "method": "by_archetype",
        "archetype": "seasonal",
        "index": 0,
    },

    "question": (
        "Health has been oscillating in the Yellow band for months. Is this account "
        "at real risk, or is the volatility expected for this customer? "
        "What should we do?"
    ),

    "expected_diagnosis": {
        "primary_drivers": [
            "seasonal_pattern_recognized",
            "counter_signals_indicate_low_risk",
            "structural_oscillation_not_decline",
        ],
        "min_drivers_matched": 2,
        "should_mention": [
            # Seasonal/cyclic pattern recognition (the key insight)
            "seasonal",
            "cyclic",
            "cycle",
            "alternating",
            "repeating",
            "structural",
            # Counter-signal language (why it's not real risk)
            "payment",
            "engagement",
            # Trough/peak / pattern terminology
            "trough",
            "peak",
            "predictable",
        ],
        "should_not_mention": [],
    },

    "expected_actions": {
        # Maintain / monitor / qualify expansion are right; escalation is wrong
        "must_include_at_least_one_of": [
            "customer_communication",
            "recommend_human_query",
            "open_expansion_play",
            "pull_qbr_forward",
        ],
        # THE TRAP: brain that doesn't recognize seasonality might escalate
        # because Yellow + 30d trajectory declining (the trough transition)
        # looks like a churn risk. Escalation here would be wrong.
        "must_not_include": [
            "escalate_to_slm",
        ],
    },

    "pass_criteria": {
        "schema_compliance":           True,
        "citations_resolve":           True,
        "action_taxonomy_compliant":   True,
        "min_citation_count":          15,
        "diagnosis_match_pass":        True,
        "expected_actions_pass":       True,
    },

    "comment": (
        "Tests the seasonality trap. Surface signal: Yellow tier, oscillating, "
        "30-day trajectory declining (the trough transition). A naive brain reads "
        "this as 'declining health, escalate.' Real diagnosis: the account follows "
        "a structurally-repeating quarterly cycle (RetailTech seasonal cadence), "
        "and the current 'declining' trajectory is just the predictable trough. "
        "Counter-signals: clean payment history, positive conversations, multi-year "
        "renewal already negotiated. The brain MUST recognize the cycle, identify "
        "the counter-signals, and refuse to escalate. Catches: brain that diagnoses "
        "on health-score deltas alone without reading the 27-month usage history; "
        "brain that ignores positive counter-signals; brain that escalates on "
        "Yellow-and-declining without considering what 'declining' means in context."
    ),
}


# ─────────────────────────────────────────────────────────────────────
# FIXTURE 10 — Second stale fixture (partial staleness on conv_intel)
# Tests degraded-but-useful output when ONE source is stale, others fresh
# ─────────────────────────────────────────────────────────────────────

EVAL_Q10_STALE_CONV_INTEL = {
    "fixture_id": "EVAL-Q10",
    "question_type": "diagnosis_on_stale_data",
    "difficulty": "stale_fixture",

    "account_selection": {
        "method": "by_archetype",
        "archetype": "champion_loss_decliner",
        "index": 0,
    },

    # Mutate the brain-ready view: force stale ONLY on conversation_intel.
    # Other sources (usage, health, payments) remain fresh.
    # This tests partial-staleness handling — does the brain produce useful
    # output from fresh sources while flagging the stale dimension?
    "fixture_mutations": {
        "force_stale": True,
        "stale_components": ["conversation_intel"],
        "stale_age_hours": 96,    # 4 days stale; threshold is typically 14d for conv,
                                   # but force_stale=True flips is_stale regardless
    },

    "question": "What's the move on this account?",

    "expected_diagnosis": {
        # No diagnosis quality requirements — the test is staleness recognition
        "primary_drivers": [],
        "min_drivers_matched": 0,
        "should_mention": [],
        "should_not_mention": [],
    },

    "expected_actions": {
        "must_include_at_least_one_of": [],
        "must_not_include": [],
    },

    "pass_criteria": {
        "schema_compliance":              True,
        "citations_resolve":              True,
        "action_taxonomy_compliant":      True,
        # THE WHOLE TEST: brain MUST recognize staleness even when only
        # ONE component is stale and the others are fresh
        "data_staleness_acknowledged":    True,
        "narrative_contains_staleness":   True,
    },

    "comment": (
        "Companion to EVAL-Q07 (which tests full-stale on customer_health). "
        "EVAL-Q10 tests PARTIAL staleness — only conversation_intel is stale, "
        "other sources fresh. Tests that the brain still recognizes staleness "
        "when other components are fine, which is harder than the all-stale "
        "case. Per AGT-902 spec: per-component staleness, brain may proceed "
        "with fresh components but MUST surface the specific stale dimension. "
        "Catches: brain that only checks for fully-stale views; brain that "
        "treats any-fresh-source as 'all good' and skips disclosure."
    ),
}


# ─────────────────────────────────────────────────────────────────────
# FIXTURE 5 — Trap case on spike_then_crash (looks like expansion, isn't)
# ─────────────────────────────────────────────────────────────────────

EVAL_Q05_SPIKE_EXPANSION_QUAL = {
    "fixture_id": "EVAL-Q05",
    "question_type": "expansion_qualification",
    "difficulty": "hard",

    "account_selection": {
        "method": "by_archetype",
        "archetype": "spike_then_crash",
        "index": 0,
    },

    "question": (
        "AGT-503 fired with consumption overage on this account. "
        "Is this real expansion or a one-time spike?"
    ),

    "expected_diagnosis": {
        "primary_drivers": [
            "spike_pattern_recognized",
            "usage_no_longer_elevated",
            "renewal_proximity",
        ],
        "min_drivers_matched": 2,
        # Many ways to express "spike then back to baseline" — broadened after
        # a real run where the brain correctly used "reverted sharply" and
        # "below the contracted commit" instead of "normalized/stabilized".
        # Per eval-pragmatism: loose semantic phrases > tight verbatim ones.
        "should_mention": [
            "spike",
            "normalized",
            "stabilized",
            "baseline",
            "revert",            # reverted, reversion
            "no longer",         # "no longer elevated"
            "one-time",
            "below",             # "below commit", "below baseline"
            "not real expansion",
        ],
        # NOTE: removed "real expansion" — too crude. A brain that says
        # "this is NOT real expansion" correctly is flagged by substring match.
        # The real test of "did the brain go down the wrong path" is captured
        # by must_not_include=[open_expansion_play] in expected_actions below.
        "should_not_mention": [],
    },

    "expected_actions": {
        # The trap: brain MUST NOT auto-open expansion play here
        "must_not_include": [
            "open_expansion_play",
        ],
        "must_include_at_least_one_of": [
            "recommend_human_query",
            "customer_communication",
            "pull_qbr_forward",
        ],
    },

    "pass_criteria": {
        "schema_compliance":           True,
        "citations_resolve":           True,
        "action_taxonomy_compliant":   True,
        "min_citation_count":          10,
        "diagnosis_match_pass":        True,
        "expected_actions_pass":       True,
    },

    "comment": (
        "Trap case. Surface signal (AGT-503 fired on overage) suggests expansion. "
        "Underlying truth: the spike was one-time, usage now back to baseline, "
        "40 days to renewal. A naive brain would propose open_expansion_play and fail. "
        "A good brain reads the trajectory, recognizes the cliff-and-recovery pattern, "
        "and routes to qualification rather than action."
    ),
}


# ─────────────────────────────────────────────────────────────────────
# FIXTURE 3 — Stale fixture (tests hard 100% staleness recognition rule)
# ─────────────────────────────────────────────────────────────────────

EVAL_Q07_STALE_HEALTH_VIEW = {
    "fixture_id": "EVAL-Q07",
    "question_type": "diagnosis_on_stale_data",
    "difficulty": "stale_fixture",

    "account_selection": {
        "method": "by_archetype",
        "archetype": "ideal_power_user",
        "index": 0,
    },

    # Mutate the brain-ready view BEFORE passing to the brain.
    # Forces is_stale=True with a specific stale component.
    "fixture_mutations": {
        "force_stale": True,
        "stale_components": ["customer_health"],
        "stale_age_hours": 48,    # 48h since last refresh; threshold is 24h
    },

    "question": "What's the move on this account?",

    "expected_diagnosis": {
        # Diagnosis quality is irrelevant — the test is staleness recognition only
        "primary_drivers": [],
        "min_drivers_matched": 0,
        "should_mention": [],
        "should_not_mention": [],
    },

    # No specific expected actions — staleness handling can vary
    "expected_actions": {
        "must_include_at_least_one_of": [],
        "must_not_include": [],
    },

    "pass_criteria": {
        "schema_compliance":              True,
        "citations_resolve":              True,
        "action_taxonomy_compliant":      True,
        # THE WHOLE TEST: brain MUST recognize staleness
        "data_staleness_acknowledged":    True,
        "narrative_contains_staleness":   True,
    },

    "comment": (
        "Stale-fixture test. The corpus account's customer_health view is forced to "
        "stale (48h since last refresh, threshold 24h). Brain MUST set "
        "data_staleness_acknowledged=True AND surface staleness in narrative_output. "
        "Per AGT-902 spec, this is a hard 100% requirement — single failure across the "
        "5 stale fixtures fails the entire harness."
    ),
}


# ─────────────────────────────────────────────────────────────────────
# Master fixture list — all fixtures the scorer will iterate over
# ─────────────────────────────────────────────────────────────────────

# ─────────────────────────────────────────────────────────────────────
# FIXTURE 11 — TOOL-008 Product Adoption Pattern Recognizer exercise
# expansion_ready archetype is siloed_by_team in feature engagement —
# real expansion candidate IF cross-team rollout, but champion-loss risk
# if the active team's owner leaves. The brain must distinguish these by
# calling TOOL-008 to inspect feature-level adoption, not just volume.
# ─────────────────────────────────────────────────────────────────────

EVAL_Q11_SILOED_EXPANSION = {
    "fixture_id": "EVAL-Q11",
    "question_type": "expansion_qualification",
    "difficulty": "medium",

    "account_selection": {
        "method": "by_archetype",
        "archetype": "expansion_ready",
        "index": 0,
    },

    "question": (
        "Consumption overage fired on this account, but I want to know whether "
        "the depth of adoption supports a real cross-team expansion play, or "
        "whether usage is concentrated in one team. What's the feature-engagement "
        "picture and what's the right play?"
    ),

    "expected_diagnosis": {
        "primary_drivers": [
            "siloed_or_concentrated_adoption",
            "cross_team_expansion_opportunity",
            "champion_loss_risk_if_concentrated",
        ],
        "min_drivers_matched": 1,
        # Depth/concentration vocabulary the brain should land on after seeing
        # TOOL-008's output. Loose semantic — any of these counts.
        "should_mention": [
            "concentrat",            # concentrated, concentration
            "siloed",
            "single team",
            "one team",
            "cross-team",
            "feature",
        ],
        "should_not_mention": [],
    },

    "expected_actions": {
        "must_include_at_least_one_of": [
            "open_expansion_play",
            "customer_communication",
            "recommend_human_query",
        ],
        # Pure churn-side actions are wrong here — the account is still
        # green-health with growing consumption.
        "must_not_include": [
            "escalate_to_slm",
        ],
    },

    "pass_criteria": {
        "schema_compliance":           True,
        "citations_resolve":           True,
        "action_taxonomy_compliant":   True,
        "min_citation_count":          8,
        "diagnosis_match_pass":        True,
        "expected_actions_pass":       True,
        # The teeth: brain MUST cite tool_008 in sources_read to pass.
        # Without this rule the brain could answer from view alone.
        "must_cite_tool_008":          True,
    },

    "comment": (
        "Forces the brain to call TOOL-008 and reason about feature-level adoption "
        "concentration. Volume-only reasoning (TOOL-004 alone) would mislead — "
        "consumption is up, but if it's all one team, the expansion play and the "
        "champion-loss-risk caveat are intertwined. This fixture validates that "
        "the brain integrates feature-engagement context, not just volume signals."
    ),
}


FIXTURES: list[dict] = [
    EVAL_Q01_CHURN_DIAGNOSIS,
    EVAL_Q02_SURFACE_ONLY_RENEWAL,
    EVAL_Q03_STALLED_ONBOARDING,
    EVAL_Q04_REAL_EXPANSION_CONFIRMED,
    EVAL_Q05_SPIKE_EXPANSION_QUAL,
    EVAL_Q06_HANDOFF_BRIEFING,
    EVAL_Q07_STALE_HEALTH_VIEW,
    EVAL_Q08_QBR_NARRATIVE,
    EVAL_Q09_SEASONAL_FALSE_RISK,
    EVAL_Q10_STALE_CONV_INTEL,
    EVAL_Q11_SILOED_EXPANSION,
]


# ─────────────────────────────────────────────────────────────────────
# TEMPLATE — copy this dict and fill in for each new fixture
# ─────────────────────────────────────────────────────────────────────

TEMPLATE_FIXTURE = {
    "fixture_id": "EVAL-Q??",                 # use sequential IDs
    "question_type": "?????",                  # one of: churn_diagnosis, expansion_qualification,
                                               #         handoff_briefing, plan_diagnosis,
                                               #         coverage_gap, play_retrospective,
                                               #         qbr_narrative, diagnosis_on_stale_data
    "difficulty": "?????",                     # easy | medium | hard | stale_fixture

    "account_selection": {
        "method": "by_archetype",              # or "by_company_name" or "by_uuid_prefix"
        "archetype": "??????",                 # one of the 8 archetype keys (see synth/archetypes.py)
        "index": 0,                            # if multiple accounts match, take this one
    },

    "question": "?????",

    "expected_diagnosis": {
        "primary_drivers": [
            # 1-3 short snake_case identifiers describing what the brain MUST identify.
            # These are conceptual labels for what you'll look for in the narrative.
            # The scorer checks via should_mention phrases below — primary_drivers is for
            # human readability and review.
        ],
        "min_drivers_matched": 1,              # 0 if diagnosis quality isn't the test (e.g. stale fixtures)
        "should_mention": [
            # phrases (semantic, lowercased, substring match) that MUST appear in narrative.
            # Pick ~2-4 keywords that capture the right concept without over-constraining
            # the brain's wording. e.g., "champion" not "John departed in November."
        ],
        "should_not_mention": [
            # phrases that, if present, indicate the brain went down the wrong path.
            # Example: for spike_then_crash, "real expansion" appearing without qualification.
        ],
    },

    "expected_actions": {
        "must_include_at_least_one_of": [
            # action_type values from the AGT-902 enum that are appropriate for this case.
            # Empty list = don't check (any actions are fine).
        ],
        "must_not_include": [
            # action_type values that indicate the brain went down the wrong path.
            # Example: for spike_then_crash, "open_expansion_play" without qualification.
        ],
    },

    # Optional. Only present for stale-data fixtures.
    # "fixture_mutations": {
    #     "force_stale": True,
    #     "stale_components": ["usage_metering"],   # which component to mark stale
    #     "stale_age_hours": 96,                     # how stale (helps brain articulate)
    # },

    "pass_criteria": {
        # Hard checks (always required for any fixture):
        "schema_compliance":           True,
        "citations_resolve":           True,
        "action_taxonomy_compliant":   True,

        # Optional thresholds (omit to skip):
        "min_citation_count":          10,         # how many [src:N] citations required
        "diagnosis_match_pass":        True,        # min_drivers_matched satisfied
        "expected_actions_pass":       True,        # must_include / must_not_include satisfied

        # For stale fixtures only:
        # "data_staleness_acknowledged":    True,
        # "narrative_contains_staleness":   True,
    },

    "comment": "Short note: what makes this a good fixture, what trap it tests, etc.",
}


# ─────────────────────────────────────────────────────────────────────
# How to write a good fixture (cheat sheet)
# ─────────────────────────────────────────────────────────────────────
#
# 1. PICK A STORY YOU CAN ARTICULATE IN ONE SENTENCE.
#    Bad:  "Test the brain on Northwind."
#    Good: "Test that the brain reads renewal_proximity context over the
#           surface usage signal when both seem to point opposite directions."
#
# 2. PICK should_mention KEYWORDS THAT ARE SEMANTIC, NOT VERBATIM.
#    Bad:  should_mention=["John Smith departed November 2"]
#    Good: should_mention=["champion", "non-renewal"]
#    Tighter keywords = false negatives. Looser keywords = false positives.
#    The brain should be allowed to phrase things its way.
#
# 3. KNOW WHAT'S WRONG, NOT JUST WHAT'S RIGHT.
#    must_not_include and should_not_mention are usually MORE valuable than
#    the positive lists. They catch a brain that's pattern-matching surface
#    signals.
#
# 4. STALE FIXTURES ARE ABOUT STALENESS, NOT DIAGNOSIS.
#    For stale fixtures, set min_drivers_matched=0 and only check the
#    staleness pass criteria. Mixing staleness test with diagnosis test
#    creates a fixture that fails for the wrong reason.
#
# 5. CALIBRATE WITH THE EXISTING BRAIN OUTPUT FIRST.
#    Before adding a fixture to FIXTURES, run AGT-902 manually on the
#    target account. Read the narrative. Ask: would my proposed
#    should_mention list match this output? If not, refine the list.
#
# 6. AIM FOR DISTRIBUTION:
#    - 3 churn diagnoses (different archetypes hitting churn)
#    - 2 expansion qualifications (one trap, one real)
#    - 2 hand-off briefings or handoff-style queries
#    - 1 plan diagnosis or coverage gap
#    - 5 stale fixtures (some on each component: health, usage, conv,
#      composite, payments)
#
# 7. WRITE 2-3, RUN THE EVAL, ITERATE.
#    Don't write all 7 in one sitting. Write 2-3, run the eval, see what
#    passes/fails, refine your should_mention lists, then write the next 2-3.
