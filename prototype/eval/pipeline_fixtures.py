"""Eval fixtures for AGT-901 Pipeline Brain.

Sister to fixtures.py (which targets AGT-902 Account Brain). Three fixtures
covering the cohort dimensions the prototype can exercise: segment-level
diagnosis, segment expansion ranking, vertical coverage gap.

Cheat sheet from per-account fixtures applies (see ../fixtures.py header):
loose semantic > tight verbatim, must_include catches more bugs than
must_not_include for actions, watch substring traps.

ACTION TAXONOMY (AGT-901, distinct from AGT-902):
  draft_play, flag_coverage_gap, recommend_query_for_human, none
"""

from __future__ import annotations


# ─────────────────────────────────────────────────────────────────────
# EVAL-P01 — SMB segment diagnosis
# Trap: brain that pattern-matches on "SMB at-risk" without explaining WHY.
# The corpus signal: 10/14 SMB accounts at-risk, avg health ~50, no
# expansion-ready, several stalled onboardings.
# ─────────────────────────────────────────────────────────────────────

EVAL_P01_SMB_DIAGNOSIS = {
    "fixture_id": "EVAL-P01",
    "question_type": "cohort_diagnosis",
    "difficulty": "medium",

    "question": (
        "The SMB segment looks weak. What's driving it and what should we do?"
    ),

    "expected_diagnosis": {
        "min_drivers_matched": 2,
        "should_mention": [
            "smb",
            "at risk",
            "at-risk",
            "health",
            "stalled",
            "onboarding",
        ],
        "should_not_mention": [],
    },

    "expected_actions": {
        # Cohort-level actions are the right shape; per-account expansion plays are
        # AGT-902's job. AGT-901 should propose either a remediation play or a
        # human query for further investigation.
        "must_include_at_least_one_of": [
            "draft_play",
            "flag_coverage_gap",
            "recommend_query_for_human",
        ],
        "must_not_include": [],
    },

    "pass_criteria": {
        "schema_compliance":           True,
        "citations_resolve":           True,
        "action_taxonomy_compliant":   True,
        "min_citation_count":          5,
        "diagnosis_match_pass":        True,
        "expected_actions_pass":       True,
        # Cohort claim must cite the segment_rollup specifically
        "must_cite_source":            "segment_rollup",
    },

    "comment": (
        "Tests cohort-level reasoning: does the brain identify the SMB "
        "weakness pattern AND cite it back to segment_rollup, not to a "
        "single account? The corpus has SMB at ~50 avg health vs MM/Ent "
        "at ~80 — pattern should be visible without ambiguity."
    ),
}


# ─────────────────────────────────────────────────────────────────────
# EVAL-P02 — Expansion prioritization across segments
# Tests whether the brain ranks segments by expansion readiness AND
# uses TOOL-004/TOOL-008 for drill-down on top candidates.
# ─────────────────────────────────────────────────────────────────────

EVAL_P02_EXPANSION_RANKING = {
    "fixture_id": "EVAL-P02",
    "question_type": "expansion_prioritization",
    "difficulty": "medium",

    "question": (
        "Which segment is the strongest expansion candidate right now? "
        "Where should the AE team prioritize, and what evidence do you have?"
    ),

    "expected_diagnosis": {
        "min_drivers_matched": 2,
        "should_mention": [
            # Segments that should appear in the analysis
            "mm",
            "mid-market",
            "ent",
            "enterprise",
            # Expansion vocabulary
            "expansion",
            "overage",
            "expansion-ready",
            "consumption",
        ],
        "should_not_mention": [],
    },

    "expected_actions": {
        "must_include_at_least_one_of": [
            "draft_play",
            "recommend_query_for_human",
        ],
        # Coverage-gap is a different question — not the right action here.
        # `none` is wrong because there ARE expansion candidates in the corpus.
        "must_not_include": [
            "none",
        ],
    },

    "pass_criteria": {
        "schema_compliance":           True,
        "citations_resolve":           True,
        "action_taxonomy_compliant":   True,
        "min_citation_count":          5,
        "diagnosis_match_pass":        True,
        "expected_actions_pass":       True,
    },

    "comment": (
        "MM has 12 expansion-ready accounts and Ent has 6 (vs SMB's 0). "
        "Brain should rank MM first (volume) or Ent first (ARR concentration) "
        "and justify. May call TOOL-004/008 to validate top candidates' "
        "expansion signal — not required, but if called, must cite results."
    ),
}


# ─────────────────────────────────────────────────────────────────────
# EVAL-P03 — Vertical coverage gap
# Tests flag_coverage_gap action specifically + vertical_rollup citation.
# ─────────────────────────────────────────────────────────────────────

EVAL_P03_VERTICAL_COVERAGE = {
    "fixture_id": "EVAL-P03",
    "question_type": "coverage_gap",
    "difficulty": "easy",

    "question": (
        "Looking across verticals, are we underweighted anywhere given "
        "where our healthiest accounts are? Where are the coverage gaps?"
    ),

    "expected_diagnosis": {
        "min_drivers_matched": 1,
        "should_mention": [
            "vertical",
            # The corpus distributes accounts across SaaS / FinTech /
            # HealthTech / RetailTech / Other. Brain should call out at least
            # one specific vertical by name.
            "saas",
            "fintech",
            "healthtech",
            "retailtech",
        ],
        "should_not_mention": [],
    },

    "expected_actions": {
        # The whole point of this question is to elicit a coverage-gap action.
        "must_include_at_least_one_of": [
            "flag_coverage_gap",
        ],
        "must_not_include": [],
    },

    "pass_criteria": {
        "schema_compliance":           True,
        "citations_resolve":           True,
        "action_taxonomy_compliant":   True,
        "min_citation_count":          4,
        "diagnosis_match_pass":        True,
        "expected_actions_pass":       True,
        "must_cite_source":            "vertical_rollup",
    },

    "comment": (
        "Direct test of flag_coverage_gap action_type. Question explicitly "
        "asks about underweighting; brain should cite vertical_rollup to "
        "show counts/health by vertical and identify a gap."
    ),
}


PIPELINE_FIXTURES: list[dict] = [
    EVAL_P01_SMB_DIAGNOSIS,
    EVAL_P02_EXPANSION_RANKING,
    EVAL_P03_VERTICAL_COVERAGE,
]
