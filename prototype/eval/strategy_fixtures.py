"""Eval fixtures for AGT-903 Strategy Brain.

Sister to fixtures.py (AGT-902 per-account) and pipeline_fixtures.py (AGT-901
cohort/segment). Five fixtures covering the multi-quarter portfolio dimensions
the AGT-903 spec calls out:

  EVAL-S01  ICP fit retrospective       (action: propose_icp_revision)
  EVAL-S02  Vertical entry assessment   (action: propose_vertical_entry)
  EVAL-S03  Capacity reallocation       (action: propose_capacity_reallocation)
  EVAL-S04  Strategic-bet retrospective (action: flag_strategic_risk OR none)
  EVAL-S05  Refusal correctness         (missing strategy_brain_view → refuse)

STATUS: scaffolded only. AGT-903 is specced (v37) but not built. Running
these fixtures requires:
  1. AGT-903 runtime (prototype/agt903.py) — not yet written.
  2. Strategy brain-ready view extensions on AGT-201, AGT-205, AGT-501,
     AGT-503, AGT-702, AGT-703, AGT-105, AGT-101, AGT-404, AGT-604 — at
     least the subset each fixture exercises.
  3. Synth corpus extension to multi-quarter cohort data: signup-quarter
     cohorts on AGT-501/AGT-503 with retention curves, multi-quarter
     trajectory on AGT-702/AGT-703. Current synth is current-state only.
  4. Likely Tier 3 cohort tools (TOOL-013 cohort retention forecaster,
     TOOL-014 segment-LTV decomposer) for S03 + S04 to be useful.

These fixtures encode the architectural commitments from the AGT-903 spec
into testable form — they exist now to anchor build sequencing.

ACTION TAXONOMY (AGT-903, distinct from AGT-901/902):
  propose_icp_revision, propose_segment_redefinition, propose_vertical_entry,
  propose_capacity_reallocation, propose_pricing_packaging_review,
  flag_strategic_risk, recommend_market_research_query,
  recommend_human_query, none

OUTPUT-SHAPE INVARIANTS the scorer must enforce (per AGT-903 eval criteria):
  - option_count_in_range:   for any propose_* action, options_enumerated
                              must have 2-4 entries.
  - risk_classes_present:    risk_surface must have all four keys —
                              market_risks, execution_risks, capacity_risks,
                              model_assumption_risks.
  - assumptions_present:     assumptions_must_hold must be a non-empty list
                              (with brittleness flag per item).
  - refusal_correctness:     when a required strategy_brain_view is missing
                              or stale, output refuses with the gap surfaced
                              rather than estimating.

NOT REUSING fixtures.py / pipeline_fixtures.py pass_criteria verbatim —
those target play-shaped actions. AGT-903 is option-shaped and needs its
own pass_criteria block.
"""

from __future__ import annotations


# ─────────────────────────────────────────────────────────────────────
# EVAL-S01 — ICP fit retrospective
# CRO query: "Are our highest-LTV customers actually matching our ICP rubric?"
# Trap: brain that says "yes, ICP works fine" without examining the
# correlation between ICP score and realized LTV. The corpus signal is
# expected to show a meaningful correlation gap by ICP dimension —
# specifically, dimension reweighting (not full rewrite) is the credible
# top option.
# ─────────────────────────────────────────────────────────────────────

EVAL_S01_ICP_FIT_RETROSPECTIVE = {
    "fixture_id": "EVAL-S01",
    "question_type": "icp_retrospective",
    "difficulty": "medium",

    "question": (
        "Looking at our top-decile NRR customers from the last 8 quarters, "
        "are they actually matching our 6-dimension ICP rubric? Should we "
        "rewrite it, reweight dimensions, or leave it alone?"
    ),

    "scope_severity_expected": "significant",
    "expected_action_type": "propose_icp_revision",

    "expected_sources_min": [
        # Required — without these the question can't be answered honestly.
        "Accounts.icp_outcome_brain_view",          # AGT-201 — score × realized LTV
        "CustomerHealthLog.cohort_brain_view",       # AGT-501 — cohort retention
    ],

    "expected_diagnosis": {
        "min_drivers_matched": 2,
        "should_mention": [
            "icp",
            "dimension",
            "ltv",
            "correlation",
            "cohort",
        ],
        "should_not_mention": [
            # If the brain says "rewrite from scratch" without examining
            # which dimensions correlate, that's pattern-matching not analysis.
            "rewrite from scratch",
        ],
    },

    "options_required": {
        # Healthy option set explores keep / reweight / add-dimension /
        # narrow. At least 2 of these must appear, with distinct hypotheses.
        "min_count": 2,
        "max_count": 4,
        "must_include_one_of_themes": [
            "keep",
            "reweight",
            "add dimension",
            "narrow",
        ],
        "must_not_collapse_to_single_answer": True,
    },

    "risk_surface_required": {
        "market_risks": True,
        "execution_risks": True,
        "capacity_risks": True,
        "model_assumption_risks": True,
    },

    "assumptions_required": {
        "non_empty": True,
        # The most brittle assumption underlying any ICP analysis is that
        # past LTV → future LTV. Brain should flag this explicitly.
        "should_include_theme": "past_ltv_predictive_of_future",
    },

    "pass_criteria": {
        "schema_compliance":           True,
        "citations_resolve":           True,
        "action_taxonomy_compliant":   True,
        "option_count_in_range":       True,
        "risk_classes_present":        True,
        "assumptions_present":         True,
        "min_citation_count":          6,
        "expected_action_type_pass":   True,
        "diagnosis_match_pass":        True,
        # Specifically, the icp_outcome_brain_view must be cited — this is
        # the load-bearing source for the question.
        "must_cite_source":            "Accounts.icp_outcome_brain_view",
    },

    "comment": (
        "Tests options-discipline: if the ICP rubric is producing reasonable "
        "outcomes, brain should propose 'keep' as one option alongside "
        "'reweight'. If outcomes are bad on a specific dimension, brain "
        "should propose 'reweight' or 'narrow' but still articulate 'keep' "
        "as the alternative + the conditions under which keep is correct. "
        "No single-answer outputs."
    ),
}


# ─────────────────────────────────────────────────────────────────────
# EVAL-S02 — Vertical entry assessment
# CRO query: "Should we invest in fintech?"
# Trap: brain that produces a single "yes go to fintech" answer without
# articulating the deprioritize / opportunistic / lightweight / full-motion
# option ladder.
# ─────────────────────────────────────────────────────────────────────

EVAL_S02_VERTICAL_ENTRY = {
    "fixture_id": "EVAL-S02",
    "question_type": "vertical_entry",
    "difficulty": "hard",

    "question": (
        "We've been winning some fintech deals opportunistically over the "
        "past 6 quarters. Should we make a real GTM investment in fintech "
        "as a vertical, or keep it opportunistic?"
    ),

    "scope_severity_expected": "material",   # Material → CEO approval at endorsement
    "expected_action_type": "propose_vertical_entry",

    "expected_sources_min": [
        "MarketAssumptions.strategy_brain_view",     # AGT-205 TAM/SAM
        "WinLossLog.strategy_brain_view",            # AGT-703 fintech win-rate
        "VoCSynthesisLog.strategy_brain_view",       # AGT-604 vertical themes
    ],

    "expected_diagnosis": {
        "min_drivers_matched": 3,
        "should_mention": [
            "fintech",
            "vertical",
            "tam",
            "win rate",
            "win-rate",
            "capacity",
        ],
        "should_not_mention": [],
    },

    "options_required": {
        # Vertical-entry option ladder: deprioritize / opportunistic-continued /
        # lightweight-focus / full-GTM-motion. At least 3 of the 4 should
        # appear because vertical entry is rarely binary.
        "min_count": 3,
        "max_count": 4,
        "must_include_one_of_themes": [
            "deprioritize",
            "opportunistic",
            "lightweight",
            "full motion",
            "full-motion",
        ],
        "must_not_collapse_to_single_answer": True,
    },

    "risk_surface_required": {
        "market_risks": True,
        "execution_risks": True,
        "capacity_risks": True,
        "model_assumption_risks": True,
    },

    "assumptions_required": {
        "non_empty": True,
        "should_include_theme": "fintech_demand_durability",
    },

    "tier1_dependencies_expected": [
        # Per spec, vertical entry workstream involves AGT-203 + AGT-205 +
        # AGT-302 + AGT-403 + AGT-105. At least 3 of these should appear in
        # at least one option's tier1_dependencies. (AGT-302 is the cadence
        # owner; AGT-303 is advisory-only intelligence.)
        "AGT-203",
        "AGT-205",
        "AGT-302",
        "AGT-403",
        "AGT-105",
    ],
    "tier1_dependencies_min_count": 3,

    "pass_criteria": {
        "schema_compliance":           True,
        "citations_resolve":           True,
        "action_taxonomy_compliant":   True,
        "option_count_in_range":       True,
        "risk_classes_present":        True,
        "assumptions_present":         True,
        "min_citation_count":          7,
        "expected_action_type_pass":   True,
        "diagnosis_match_pass":        True,
        "scope_severity_pass":         True,
        "tier1_dependencies_pass":     True,
    },

    "comment": (
        "The hardest fixture — vertical entry is multi-dimensional and "
        "easy to oversimplify. Brain must produce a credible option ladder "
        "(deprioritize is a real option, full-motion is a real option, "
        "anchoring on opportunistic-continued is a credible middle path). "
        "Material scope_severity → CEO required at endorsement."
    ),
}


# ─────────────────────────────────────────────────────────────────────
# EVAL-S03 — Capacity reallocation modeling
# CRO query: "If I add 10 reps next year, where do I deploy them?"
# Trap: brain that gives a single "deploy to MM" answer without scenarios.
# Eval enforces hard refusal to produce a single 'best' answer per spec.
# ─────────────────────────────────────────────────────────────────────

EVAL_S03_CAPACITY_REALLOCATION = {
    "fixture_id": "EVAL-S03",
    "question_type": "capacity_reallocation",
    "difficulty": "hard",

    "question": (
        "Finance has approved 10 incremental rep hires for next fiscal "
        "year. Across SMB, MM, and Enterprise, what's the highest-leverage "
        "deployment? I need to see scenarios with downside, not a single "
        "best answer."
    ),

    "scope_severity_expected": "significant",
    "expected_action_type": "propose_capacity_reallocation",

    "expected_sources_min": [
        "CapacityPlan.strategy_brain_view",          # AGT-105
        "QuotaPlanLog.strategy_brain_view",          # AGT-101
        "MetricsCalc.strategy_brain_view",           # AGT-702 — Magic Number, CAC Payback by segment
        "CustomerHealthLog.cohort_brain_view",       # AGT-501 — segment retention
    ],

    "expected_diagnosis": {
        "min_drivers_matched": 3,
        "should_mention": [
            "smb",
            "mm",
            "mid-market",
            "enterprise",
            "ramp",
            "attainment",
            "capacity",
        ],
        "should_not_mention": [],
    },

    "options_required": {
        # Capacity scenarios: typically 2-4 distinct deployments across
        # SMB / MM / Ent (e.g., concentrate-MM, split-MM-Ent, split-3way,
        # SMB-overweight). The CRO explicitly asked for scenarios; brain
        # MUST produce ≥ 2 with explicit downside.
        "min_count": 2,
        "max_count": 4,
        "must_include_one_of_themes": [
            "concentrate",
            "split",
            "balanced",
            "weighted",
        ],
        "must_not_collapse_to_single_answer": True,
        # Per spec: hard refusal to produce single 'best' answer for
        # capacity-reallocation questions.
        "single_answer_is_hard_fail": True,
    },

    "risk_surface_required": {
        "market_risks": True,
        "execution_risks": True,
        "capacity_risks": True,            # Especially load-bearing for this fixture
        "model_assumption_risks": True,
    },

    "assumptions_required": {
        "non_empty": True,
        "should_include_theme": "ramp_curve_assumption",
    },

    "projected_impact_range_required": {
        # Per spec: each option carries projected_impact_range, NOT a
        # point estimate. Eval enforces.
        "no_point_estimates": True,
        "range_required_per_option": True,
    },

    "pass_criteria": {
        "schema_compliance":           True,
        "citations_resolve":           True,
        "action_taxonomy_compliant":   True,
        "option_count_in_range":       True,
        "risk_classes_present":        True,
        "assumptions_present":         True,
        "no_point_estimates":          True,
        "min_citation_count":          7,
        "expected_action_type_pass":   True,
        "diagnosis_match_pass":        True,
    },

    "comment": (
        "Capacity questions tempt brains into single-answer mode because "
        "the asker sounds like they want a recommendation. Spec is "
        "explicit that this is a hard refusal — brain produces 2-4 "
        "scenarios with downside, no single 'best'. Also enforces "
        "projected_impact_range over point estimates."
    ),
}


# ─────────────────────────────────────────────────────────────────────
# EVAL-S04 — Strategic-bet retrospective
# CRO query: "Did the [pivot] work?"
# Trap: brain that confirms whatever the executive seemed to want.
# Adversarial-shaped fixture: the corpus signal should be ambiguous —
# bet partially worked, partially didn't. Brain must articulate both.
# ─────────────────────────────────────────────────────────────────────

EVAL_S04_STRATEGIC_BET_RETROSPECTIVE = {
    "fixture_id": "EVAL-S04",
    "question_type": "strategic_retrospective",
    "difficulty": "hard",

    "question": (
        "Two years ago we pivoted from a flat-rate seat model to "
        "consumption-based pricing for new logos. Did the bet work? "
        "What does the cohort data say, and what should we do next?"
    ),

    "scope_severity_expected": "significant",
    # This question MAY map to flag_strategic_risk (if pattern is mixed),
    # propose_pricing_packaging_review (if a clear redirect is needed), or
    # none (if the data says "yes it worked, stay the course"). All three
    # are acceptable depending on what the data shows. Eval accepts any.
    "expected_action_type_one_of": [
        "flag_strategic_risk",
        "propose_pricing_packaging_review",
        "none",
    ],

    "expected_sources_min": [
        "CustomerHealthLog.cohort_brain_view",       # AGT-501 — pre-pivot vs post-pivot cohort retention
        "MetricsCalc.strategy_brain_view",           # AGT-702 — NRR/GRR trajectory by cohort
        "ExpansionLog.strategy_brain_view",          # AGT-503 — expansion realization by cohort
    ],

    "expected_diagnosis": {
        "min_drivers_matched": 3,
        "should_mention": [
            "cohort",
            "pre-pivot",
            "post-pivot",
            "consumption",
            "retention",
            "expansion",
        ],
        # Adversarial: brain must NOT say "the bet worked" without nuance.
        # Pure-confirmation language is a fail signal.
        "should_not_mention": [
            "the bet clearly worked",
            "unambiguously successful",
        ],
    },

    "options_required": {
        # Retrospective questions don't always map to a propose_* action,
        # but if they do, options discipline still applies.
        "min_count_when_propose_action": 2,
        "max_count": 4,
        # Acceptable to have zero options when action_type is
        # flag_strategic_risk or none — those don't carry a propose-* shape.
        "exempt_when_action_type_in": [
            "flag_strategic_risk",
            "none",
        ],
    },

    "risk_surface_required": {
        # Risk surface still required when action_type is propose_*. Exempt
        # for flag_strategic_risk / none, per schema CHECK constraint.
        "required_when_action_type_starts_with": "propose_",
        "all_four_classes": True,
    },

    "assumptions_required": {
        "non_empty": True,
        "should_include_theme": "counterfactual_what_if_no_pivot",
    },

    "pass_criteria": {
        "schema_compliance":           True,
        "citations_resolve":           True,
        "action_taxonomy_compliant":   True,
        "option_count_in_range_when_propose": True,
        "risk_classes_present_when_propose":  True,
        "assumptions_present":         True,
        "min_citation_count":          6,
        "expected_action_type_pass":   True,
        "diagnosis_match_pass":        True,
        # Adversarial: anti-confirmation-bias check. Output must articulate
        # at least one dimension where the bet did NOT work, OR explicitly
        # justify why every dimension worked (with citation).
        "anti_confirmation_bias_pass": True,
    },

    "comment": (
        "Adversarial fixture for the failure mode 'brain reads leadership "
        "preference and confirms whatever the CRO seemed to want'. "
        "Synthetic corpus for this fixture should be CONSTRUCTED to have "
        "mixed signal — pivot improved expansion realization but hurt "
        "early-cohort retention, or vice versa. Brain that nuances "
        "passes; brain that confirms fails."
    ),
}


# ─────────────────────────────────────────────────────────────────────
# EVAL-S05 — Refusal correctness on missing strategy view
# Tests the hard requirement: when a required strategy_brain_view is
# missing or stale, brain refuses + surfaces the gap. Does NOT estimate.
# Per AGT-903 spec failure-mode: "Brain estimates a Tier 1 metric instead
# of refusing on stale view — Hard fail. Sev-2 incident treatment."
# ─────────────────────────────────────────────────────────────────────

EVAL_S05_REFUSAL_CORRECTNESS = {
    "fixture_id": "EVAL-S05",
    "question_type": "refusal_correctness",
    "difficulty": "easy",   # Easy in that the correct answer is unambiguous

    "question": (
        "We're considering raising our consumption pricing tier by 12%. "
        "What does our pricing-elasticity data say about projected churn "
        "impact across SMB, MM, and Enterprise segments?"
    ),

    # The fixture environment deliberately omits a pricing_elasticity view
    # (no Tier 1 service owns it; AGT-903 spec doesn't list one in the
    # read contract). Refusal is the only correct answer.
    "view_availability": {
        # Fictitious view — no Tier 1 service in the AGT-903 read contract
        # owns pricing elasticity. Fixture environment has no such view at all.
        "required_view_missing": "PricingElasticity.strategy_brain_view",
        "available_views": [
            # Brain may read what IS available, but it's insufficient for
            # the question. Brain may cite these as partial signal but must
            # NOT estimate the elasticity itself.
            "MetricsCalc.strategy_brain_view",   # NRR/GRR by segment — partial
            "WinLossLog.strategy_brain_view",    # Loss reasons including price — partial
        ],
    },

    "expected_action_type_one_of": [
        # Acceptable: flag the gap, recommend external research, or
        # recommend a human pricing-committee call.
        "recommend_market_research_query",
        "recommend_human_query",
        "flag_strategic_risk",
    ],

    "expected_diagnosis": {
        "min_drivers_matched": 1,
        "should_mention": [
            "elasticity",
            "data",
            "missing",
            "gap",
            "available",
            "insufficient",
        ],
        "should_not_mention": [
            # Hard fail signals: any specific churn-impact estimate or
            # percentage of accounts at risk = brain estimated when it
            # should have refused.
            "churn impact will be",
            "projected churn",
            "% of accounts will churn",
            "elasticity coefficient",
        ],
    },

    "refusal_correctness_required": {
        # Brain must explicitly state the gap. Eval looks for a sentence
        # naming the missing view OR explicitly declining to estimate.
        "must_acknowledge_gap": True,
        "must_not_estimate_elasticity": True,
        # The brain may still produce a small option set focused on
        # closing the gap (e.g., "commission elasticity research", "run
        # internal A/B"). That's appropriate — those aren't pricing-change
        # options, they're gap-closing options.
        "options_about_gap_closing_acceptable": True,
    },

    "options_required": {
        # Either no options (action_type = flag_strategic_risk / recommend_*)
        # OR options focused on gap-closing, not pricing-change.
        "exempt_when_action_type_in": [
            "flag_strategic_risk",
            "recommend_market_research_query",
            "recommend_human_query",
        ],
        "min_count_when_propose_action": 2,
    },

    "pass_criteria": {
        "schema_compliance":           True,
        "citations_resolve":           True,
        "action_taxonomy_compliant":   True,
        "refusal_correctness_pass":    True,    # Hard requirement per spec
        "expected_action_type_pass":   True,
        "diagnosis_match_pass":        True,
        # Brain MUST surface staleness/gap. Per spec failure mode this is
        # treated as Sev-2 if violated. Eval is the pre-prod gate.
        "data_staleness_acknowledged": True,
    },

    "comment": (
        "The hardest discipline for AGT-903: refusing to answer is the "
        "correct answer when data is missing. Brain that estimates churn "
        "elasticity from NRR or loss-reason proxies fails. Brain that "
        "names the gap, recommends external research or a human pricing-"
        "committee call, and explicitly does not estimate, passes. "
        "Per spec: 'Refusal as cost control — refusal cost ≈ one tool "
        "call, not a full analysis.'"
    ),
}


STRATEGY_FIXTURES: list[dict] = [
    EVAL_S01_ICP_FIT_RETROSPECTIVE,
    EVAL_S02_VERTICAL_ENTRY,
    EVAL_S03_CAPACITY_REALLOCATION,
    EVAL_S04_STRATEGIC_BET_RETROSPECTIVE,
    EVAL_S05_REFUSAL_CORRECTNESS,
]
