"""Strategy-fixture scorer for AGT-903 Strategy Brain.

SCAFFOLD ONLY — no API needed yet. AGT-903 has no runtime; this file maps
strategy_fixtures.py pass_criteria onto stub validator functions, with the
scoring shape parallel to scorer.py (AGT-902) and pipeline_scorer.py
(AGT-901).

Two purposes:
  1. Anchor the AGT-903 output contract in code BEFORE the brain runtime
     exists, so when build starts the validators are the spec-shaped target.
  2. Document, per-criterion, what "passing" means for an option-shaped
     output — distinct from the play-shaped contracts AGT-901/902 enforce.

What's stubbed vs. real:
  - score_strategy_fixture: real shape (matches scorer.score_fixture and
    pipeline_scorer.score_pipeline_fixture), but raises NotImplementedError
    on the brain-runtime call site since agt903.run_for_strategy doesn't
    exist yet.
  - Per-criterion checks: real signatures, NotImplementedError bodies with
    inline docstrings describing what the real check must do. Each cites
    the relevant strategy_fixtures.py field by name.

When AGT-903 prototype lands:
  1. Implement prototype/agt903.py with run_for_strategy(question, ...)
     producing a StrategyRecommendationLog row + BrainAnalysisLog row.
  2. Replace each NotImplementedError body with the real check. The
     pass_criteria-to-validator mapping is already wired below.
  3. Add an entrypoint mirroring run_pipeline_eval.py / run_eval.py.

Reuses scorer.py's CriterionResult, _check_schema_compliance,
_check_citations_resolve, _check_min_citation_count, _check_diagnosis_match,
_check_action_taxonomy where the contract is identical to AGT-902/901.

Adds AGT-903-specific stubs:
  _check_option_count_in_range
  _check_option_count_in_range_when_propose
  _check_risk_classes_present
  _check_risk_classes_present_when_propose
  _check_assumptions_present
  _check_no_point_estimates
  _check_refusal_correctness
  _check_data_staleness_acknowledged
  _check_anti_confirmation_bias
  _check_must_cite_source        (parallels pipeline_scorer's version)
  _check_scope_severity
  _check_tier1_dependencies
  _check_expected_action_type    (single-action variant — AGT-903 produces
                                  one strategic action per memo, not a list)
  _check_expected_action_type_one_of  (for refusal/retrospective fixtures)
"""

from __future__ import annotations

import sys
import time
from dataclasses import dataclass, field
from pathlib import Path

# Same sys.path dance as pipeline_scorer.py — sibling prototype modules.
_PROTOTYPE_DIR = Path(__file__).parent.parent.resolve()
if str(_PROTOTYPE_DIR) not in sys.path:
    sys.path.insert(0, str(_PROTOTYPE_DIR))

# Reused from AGT-902 scorer where contract is identical.
from scorer import (
    CriterionResult,
    _check_schema_compliance,
    _check_citations_resolve,
    _check_action_taxonomy,
    _check_min_citation_count,
    _check_diagnosis_match,
)


# ─────────────────────────────────────────────────────────────────────
# Result containers — parallel to FixtureResult / PipelineFixtureResult
# ─────────────────────────────────────────────────────────────────────

@dataclass
class StrategyFixtureResult:
    fixture_id: str
    fixture: dict
    strategy_recommendation_row: dict
    brain_analysis_row: dict
    # ValidationResult-shaped; concrete type once validation.py grows
    # AGT-903 awareness (option-shape, four-class risk surface, etc.).
    validation: object | None = None
    criterion_results: list[CriterionResult] = field(default_factory=list)
    overall_pass: bool = False
    failed_with_exception: str | None = None
    elapsed_seconds: float = 0.0

    @property
    def hard_failures(self) -> list[CriterionResult]:
        return [c for c in self.criterion_results if not c.passed]


# ─────────────────────────────────────────────────────────────────────
# AGT-903-specific stub validators
#
# Each stub:
#   - real signature (CriterionResult-returning)
#   - real name matching the pass_criteria key in strategy_fixtures.py
#   - docstring describing what passing/failing looks like for an
#     option-shaped output (distinct from AGT-902's play-shaped output)
#   - NotImplementedError body until AGT-903 runtime exists
# ─────────────────────────────────────────────────────────────────────

def _check_option_count_in_range(
    strategy_recommendation_row: dict,
    options_required: dict,
) -> CriterionResult:
    """options_enumerated must have min_count..max_count entries.

    Per AGT-903 spec eval criterion "Option completeness >= 90%":
    every propose_* action carries 2-4 viable options with distinct
    hypotheses (not minor variants).

    Reads:
      strategy_recommendation_row["options_enumerated"]: list of dicts
      options_required["min_count"], ["max_count"] from fixture

    Passes when:
      min_count <= len(options_enumerated) <= max_count

    Fails when:
      - options list shorter than min_count (single-answer collapse)
      - options list longer than max_count (over-proliferation)
      - any two options are minor variants of each other (deferred to
        a separate distinctness check; this stub only counts)

    Distinctness future-work: hypothesis-pair embedding similarity
    threshold. Out of scope for v0; eval can rely on human spot-check.
    """
    raise NotImplementedError(
        "Implement once agt903.run_for_strategy returns "
        "StrategyRecommendationLog rows with options_enumerated populated."
    )


def _check_option_count_in_range_when_propose(
    strategy_recommendation_row: dict,
    options_required: dict,
) -> CriterionResult:
    """Same as _check_option_count_in_range but conditional on action_type.

    Per EVAL-S04 fixture: retrospective questions may map to
    flag_strategic_risk / none, which carry no options. The AGT-903 spec
    proposed-action taxonomy table makes this explicit.

    Reads:
      strategy_recommendation_row["proposed_action"]["action_type"]
      strategy_recommendation_row["options_enumerated"]
      options_required["exempt_when_action_type_in"]
      options_required["min_count_when_propose_action"]

    Passes when:
      - action_type in exempt_when_action_type_in (regardless of count), OR
      - action_type is propose_* AND options_enumerated count >= min_count_when_propose_action

    Fails when action_type is propose_* but options is empty/short — that's
    the failure mode the eval criterion "Option completeness" guards.
    """
    raise NotImplementedError(
        "Implement once StrategyRecommendationLog row carries "
        "proposed_action.action_type + options_enumerated."
    )


def _check_risk_classes_present(
    strategy_recommendation_row: dict,
    risk_surface_required: dict,
) -> CriterionResult:
    """risk_surface must contain all four risk classes.

    Per AGT-903 spec eval criterion "Risk-surface coverage >= 90%":
    market_risks, execution_risks, capacity_risks, model_assumption_risks
    must all be present (non-empty lists OR explicit "no_risks_identified"
    sentinel; both are acceptable, silent omission is not).

    Reads:
      strategy_recommendation_row["risk_surface"]: dict with the four keys
      risk_surface_required: fixture dict with True flags per class

    Passes when:
      All four keys present in risk_surface AND each value is either a
      non-empty list of risk dicts OR the literal sentinel
      [{"none_identified": True, "rationale": str}].

    Fails when:
      - any of the four keys missing
      - any key present but value is empty list (silent omission)
      - any risk dict missing required confidence_flag

    Confidence-flag check is included here because AGT-903 spec says
    "each risk carries a confidence flag" — not a separate criterion in
    the fixtures, but enforced here as part of risk-surface integrity.
    """
    raise NotImplementedError(
        "Implement once StrategyRecommendationLog row carries risk_surface "
        "dict with the four required keys per spec."
    )


def _check_risk_classes_present_when_propose(
    strategy_recommendation_row: dict,
    risk_surface_required: dict,
) -> CriterionResult:
    """Same as _check_risk_classes_present but conditional on action_type.

    Per EVAL-S04 fixture risk_surface_required structure: risk surface is
    required when action_type is propose_*; exempt for flag_strategic_risk /
    none / recommend_* (those don't carry the proposal-shape that risk
    surface attaches to).

    Reads:
      strategy_recommendation_row["proposed_action"]["action_type"]
      strategy_recommendation_row["risk_surface"]
      risk_surface_required["required_when_action_type_starts_with"]
      risk_surface_required["all_four_classes"]

    Passes when:
      - action_type does NOT start with required prefix → automatic pass, OR
      - action_type starts with prefix AND all four classes present
        per _check_risk_classes_present semantics
    """
    raise NotImplementedError(
        "Implement once StrategyRecommendationLog row carries proposed_action "
        "+ risk_surface."
    )


def _check_assumptions_present(
    strategy_recommendation_row: dict,
    assumptions_required: dict,
) -> CriterionResult:
    """assumptions_must_hold must be non-empty list with brittleness flags.

    Per AGT-903 spec eval criterion "Assumption-surface honesty >= 90%":
    falsifiable assumptions underlying the analysis must be explicit.

    Reads:
      strategy_recommendation_row["assumptions_must_hold"]: list of
        {assumption: str, brittle: bool, rationale: str}
      assumptions_required["non_empty"]: bool from fixture
      assumptions_required["should_include_theme"]: optional theme keyword

    Passes when:
      - assumptions_must_hold is a non-empty list
      - every entry has the required schema (assumption, brittle,
        rationale all present and non-empty)
      - if should_include_theme is set, at least one assumption text
        contains the theme substring (case-insensitive)

    Fails when:
      - empty list (the most common shortcut — brain proceeds without
        flagging assumptions)
      - missing brittleness flag (per spec all assumptions carry one)
      - theme keyword missing when fixture requires it
    """
    raise NotImplementedError(
        "Implement once StrategyRecommendationLog row carries "
        "assumptions_must_hold with the structured shape."
    )


def _check_no_point_estimates(
    strategy_recommendation_row: dict,
) -> CriterionResult:
    """Per-option projected_impact must be a range, not a point estimate.

    Per EVAL-S03 (capacity_reallocation): "each option carries
    projected_impact_range, NOT a point estimate. Eval enforces."

    Per AGT-903 spec output structure: "each option carries: hypothesis,
    rough projected impact range (not a point estimate)".

    Reads:
      strategy_recommendation_row["options_enumerated"][i]["projected_impact"]

    Passes when, for every option:
      - projected_impact is a dict with ("low", "high") keys, OR
      - projected_impact is a string containing range syntax (e.g., "$1M-$3M",
        "10-30 reps") that parses to (low, high)

    Fails when any option has:
      - projected_impact as a single number / single-value string
      - projected_impact missing entirely
      - low == high (degenerate range — point estimate in disguise)

    Range parsing is permissive (string OR dict shape). Strict shape is
    a future tightening once we see how the brain actually populates this.
    """
    raise NotImplementedError(
        "Implement once StrategyRecommendationLog row schema fixes the "
        "projected_impact field shape."
    )


def _check_refusal_correctness(
    strategy_recommendation_row: dict,
    refusal_correctness_required: dict,
) -> CriterionResult:
    """Brain refuses when required strategy_brain_view is missing/stale.

    Per AGT-903 spec eval criterion "Refusal correctness — 100% hard
    requirement". Per failure-mode table: estimating a Tier 1 metric
    instead of refusing on stale view is a Sev-2 incident.

    Reads:
      strategy_recommendation_row["narrative_output"]
      strategy_recommendation_row["proposed_action"]["action_type"]
      strategy_recommendation_row["data_staleness_acknowledged"]
      strategy_recommendation_row["stale_sources"] OR ["missing_views"]
      refusal_correctness_required["must_acknowledge_gap"]
      refusal_correctness_required["must_not_estimate_elasticity"]
        (or analogous must_not_estimate_X)

    Passes when:
      - data_staleness_acknowledged is True (or missing_views is non-empty), AND
      - narrative explicitly names the gap (substring check on
        narrative_output for the missing view name OR phrase like
        "insufficient data" / "cannot estimate"), AND
      - narrative does NOT contain estimate-shaped phrases (the
        should_not_mention list from EVAL-S05's expected_diagnosis)

    Fails when:
      - brain produces a confident estimate using available proxy views
        (e.g., uses NRR + loss-reasons to back into elasticity)
      - data_staleness_acknowledged is False on a fixture where the
        required view is deliberately missing

    The estimate-detection is the load-bearing check. The fixture
    EVAL-S05 should_not_mention list captures the failure phrasings.
    """
    raise NotImplementedError(
        "Implement once agt903.run_for_strategy supports view_availability "
        "input (which views are present/missing) and the system prompt "
        "enforces refusal-on-missing per spec."
    )


def _check_data_staleness_acknowledged(
    strategy_recommendation_row: dict,
) -> CriterionResult:
    """The data_staleness_acknowledged flag must be True when sources stale.

    Per AGT-903 spec eval criterion "Staleness recognition — 100% hard"
    and StrategyRecommendationLog schema (from changelog v37):
    data_staleness_acknowledged is a first-class field.

    Reads:
      strategy_recommendation_row["data_staleness_acknowledged"]
      strategy_recommendation_row["stale_sources"]
      strategy_recommendation_row["sources_read"][i]["last_refresh_timestamp"]
      strategy_recommendation_row["sources_read"][i]["staleness_threshold_hours"]

    Passes when:
      - All sources are fresh (within threshold) → field can be either
        value; no claim either way
      - Any source is stale (refresh > threshold ago) → field MUST be True
        AND stale_sources must list the stale source names

    Fails when:
      - Any source stale but data_staleness_acknowledged is False
        (silent staleness — Sev-2 per spec)
      - data_staleness_acknowledged is True but stale_sources is empty
        (acknowledgment without specificity)

    Mostly mirrors AGT-901/902 staleness check; lifted to its own
    function here because EVAL-S05 fixture asserts it as a separate
    pass_criteria key.
    """
    raise NotImplementedError(
        "Implement once StrategyRecommendationLog row carries staleness "
        "fields per the v37 schema doc."
    )


def _check_anti_confirmation_bias(
    strategy_recommendation_row: dict,
    expected_diagnosis: dict,
) -> CriterionResult:
    """For retrospective questions, brain must articulate at least one
    dimension where the bet did NOT work.

    Per EVAL-S04 fixture pass_criteria "anti_confirmation_bias_pass":
    output must articulate at least one dimension where the bet did NOT
    work, OR explicitly justify why every dimension worked (with citation).

    Per AGT-903 spec failure mode "Endorsement rate > 50%": brain reading
    leadership preference is a known failure pattern. This check is the
    eval-side guard.

    Reads:
      strategy_recommendation_row["narrative_output"]
      expected_diagnosis["should_not_mention"] (the
        "the bet clearly worked" / "unambiguously successful" list)

    Passes when:
      - narrative does NOT contain confirmation-shaped phrases AND
      - narrative contains nuance signals: phrases like "however",
        "on the other hand", "where the data is mixed", "did not improve",
        "trade-off" — at least 1 hit
      OR
      - narrative contains explicit per-dimension citation showing
        every dimension genuinely worked (≥ 3 cited dimensions, all
        with positive findings)

    Fails when narrative collapses to single-narrative confirmation OR
    contains any of expected_diagnosis["should_not_mention"] phrases.

    Heuristic-shaped check; will need calibration once we see how
    AGT-903 actually phrases retrospectives. Loose pass criteria
    deliberately — better to catch obvious confirmation-shaped output
    than to false-fail on legitimate single-direction findings.
    """
    raise NotImplementedError(
        "Implement once agt903.run_for_strategy produces narrative_output "
        "and we have a sample to calibrate the nuance-signal heuristic."
    )


def _check_must_cite_source(
    strategy_recommendation_row: dict,
    expected_source: str,
) -> CriterionResult:
    """Verify a specific strategy_brain_view appears in sources_read.

    Mirrors pipeline_scorer._check_must_cite_source. Some AGT-903
    fixtures (EVAL-S01) pin a load-bearing source — e.g.,
    icp_outcome_brain_view for ICP retrospective. Eval enforces that
    the brain actually read the spec-required view, not a substitute.

    Reads:
      strategy_recommendation_row["sources_read"]: list of
        {table_name, view_name, last_refresh_timestamp, row_count_consumed}

    Passes when any sources_read entry has
      view_name == expected_source OR table_name == expected_source

    Fails when neither matches — caller cited substitute views or
    omitted the required one entirely.
    """
    raise NotImplementedError(
        "Implement once StrategyRecommendationLog sources_read shape is "
        "fixed (parallels BrainAnalysisLog sources_read)."
    )


def _check_scope_severity(
    strategy_recommendation_row: dict,
    expected_severity: str,
) -> CriterionResult:
    """scope_severity must match fixture expectation.

    Per StrategyRecommendationLog schema (changelog v37):
    scope_severity in (routine, significant, material). Material
    triggers CEO endorsement requirement.

    Reads:
      strategy_recommendation_row["scope_severity"]
      expected_severity: from fixture (e.g., "significant", "material")

    Passes when actual matches expected exactly.

    Fails when:
      - missing field
      - mismatched severity (especially: brain claims "routine" on a
        material-scope question, lowering the human-approval bar)

    EVAL-S02 expects "material" on vertical entry; brain should not
    downgrade to "significant" or "routine" since vertical entry has
    cross-functional motion-build scope.
    """
    raise NotImplementedError(
        "Implement once scope_severity field lands in "
        "StrategyRecommendationLog row."
    )


def _check_tier1_dependencies(
    strategy_recommendation_row: dict,
    expected_dependencies: list[str],
    min_count: int,
) -> CriterionResult:
    """Per-option tier1_dependencies must include expected services.

    Per EVAL-S02 fixture tier1_dependencies_expected: at least
    min_count of the listed agents (AGT-203, AGT-205, AGT-302,
    AGT-403, AGT-105 for vertical entry) should appear in at least
    one option's tier1_dependencies list.

    Per AGT-903 spec proposed-action taxonomy: every action maps to
    a downstream human-led workstream involving named Tier 1 services.

    Reads:
      strategy_recommendation_row["options_enumerated"][i]["tier1_dependencies"]
      expected_dependencies: list of agent IDs from fixture
      min_count: how many of the expected must appear

    Passes when union(tier1_dependencies across options) ∩
    expected_dependencies has size >= min_count.

    Fails when too few of the expected services appear — signal that
    brain is proposing actions without grounding them in the right
    downstream workstreams.
    """
    raise NotImplementedError(
        "Implement once StrategyRecommendationLog options_enumerated "
        "carries tier1_dependencies field per spec."
    )


def _check_expected_action_type(
    strategy_recommendation_row: dict,
    expected_action_type: str,
) -> CriterionResult:
    """Single-action variant: AGT-903 produces ONE strategic action per
    memo, not a list (unlike AGT-901/902 which produce action lists).

    Per AGT-903 spec output structure: each StrategyRecommendationLog
    row has one proposed_action with one action_type from the AGT-903
    taxonomy. The options-shape is on options_enumerated, not on
    proposed_action.

    Reads:
      strategy_recommendation_row["proposed_action"]["action_type"]
      expected_action_type: from fixture

    Passes when actual == expected.

    Fails when:
      - missing proposed_action
      - action_type is from AGT-901/902 taxonomy (e.g., open_play —
        wrong taxonomy, hard fail per spec)
      - action_type mismatched (e.g., propose_segment_redefinition
        when fixture expected propose_icp_revision)

    Distinct from scorer._check_expected_actions, which expects a list.
    """
    raise NotImplementedError(
        "Implement once StrategyRecommendationLog row carries "
        "proposed_action.action_type."
    )


def _check_expected_action_type_one_of(
    strategy_recommendation_row: dict,
    expected_action_types: list[str],
) -> CriterionResult:
    """Action type matches any value in expected_action_types list.

    Per EVAL-S04 / EVAL-S05 fixtures: some questions legitimately have
    multiple acceptable action_type outcomes depending on what the
    data shows.
      - EVAL-S04: flag_strategic_risk / propose_pricing_packaging_review /
        none all acceptable
      - EVAL-S05: recommend_market_research_query /
        recommend_human_query / flag_strategic_risk all acceptable

    Reads:
      strategy_recommendation_row["proposed_action"]["action_type"]
      expected_action_types: list from fixture's
        expected_action_type_one_of field

    Passes when actual in expected list.

    Fails when actual outside the list — including when action_type
    is from AGT-901/902 taxonomy (cross-taxonomy violation).
    """
    raise NotImplementedError(
        "Implement once StrategyRecommendationLog row carries "
        "proposed_action.action_type."
    )


# ─────────────────────────────────────────────────────────────────────
# pass_criteria → validator dispatch
#
# Centralized mapping so the entrypoint can iterate fixture pass_criteria
# keys without per-fixture special-casing. Mirrors the implicit dispatch
# pattern in scorer.score_fixture, but explicit here because AGT-903
# has more conditional checks (when_propose, one_of variants).
# ─────────────────────────────────────────────────────────────────────

# Maps a pass_criteria key from strategy_fixtures.py to the validator that
# implements it. Two-level keys (when_propose) fall through to the same
# validators with a conditional wrapper inside the validator.
PASS_CRITERIA_DISPATCH: dict[str, str] = {
    "schema_compliance":                    "_check_schema_compliance",
    "citations_resolve":                    "_check_citations_resolve",
    "action_taxonomy_compliant":            "_check_action_taxonomy",
    "min_citation_count":                   "_check_min_citation_count",
    "diagnosis_match_pass":                 "_check_diagnosis_match",

    "option_count_in_range":                "_check_option_count_in_range",
    "option_count_in_range_when_propose":   "_check_option_count_in_range_when_propose",
    "risk_classes_present":                 "_check_risk_classes_present",
    "risk_classes_present_when_propose":    "_check_risk_classes_present_when_propose",
    "assumptions_present":                  "_check_assumptions_present",
    "no_point_estimates":                   "_check_no_point_estimates",
    "refusal_correctness_pass":             "_check_refusal_correctness",
    "data_staleness_acknowledged":          "_check_data_staleness_acknowledged",
    "anti_confirmation_bias_pass":          "_check_anti_confirmation_bias",
    "must_cite_source":                     "_check_must_cite_source",
    "scope_severity_pass":                  "_check_scope_severity",
    "tier1_dependencies_pass":              "_check_tier1_dependencies",
    "expected_action_type_pass":            "_check_expected_action_type",
}


# ─────────────────────────────────────────────────────────────────────
# Entrypoint — score_strategy_fixture
# ─────────────────────────────────────────────────────────────────────

def score_strategy_fixture(fixture: dict) -> StrategyFixtureResult:
    """Run AGT-903 against the fixture and score against pass_criteria.

    Shape parallel to scorer.score_fixture (AGT-902) and
    pipeline_scorer.score_pipeline_fixture (AGT-901).

    Status: scaffold only. Raises NotImplementedError until:
      1. prototype/agt903.py implements run_for_strategy
      2. The per-criterion stubs above are filled in
      3. Strategy brain-ready views ship on the 10 Tier 1 services per
         the v37 contract obligation (otherwise AGT-903 will refuse on
         every fixture)
    """
    fixture_id = fixture["fixture_id"]
    result = StrategyFixtureResult(
        fixture_id=fixture_id,
        fixture=fixture,
        strategy_recommendation_row={},
        brain_analysis_row={},
    )

    t0 = time.time()
    try:
        # When agt903.py exists:
        #   from agt903 import run_for_strategy
        #   strat_row, brain_row = run_for_strategy(
        #       question=fixture["question"],
        #       view_availability=fixture.get("view_availability"),
        #       comparison_mode=fixture.get("comparison_mode"),
        #       invocation_path="strategy_eval_run",
        #       source=default_source(),
        #   )
        #   result.strategy_recommendation_row = strat_row
        #   result.brain_analysis_row = brain_row
        raise NotImplementedError(
            "AGT-903 runtime (prototype/agt903.py) not yet implemented. "
            "This scorer is a scaffold; pass_criteria → validator mapping "
            "is wired in PASS_CRITERIA_DISPATCH but each validator stub "
            "raises until AGT-903 produces StrategyRecommendationLog rows."
        )

        # Future shape, not reachable yet:
        #
        # for criterion_key, criterion_value in fixture.get("pass_criteria", {}).items():
        #     validator_name = PASS_CRITERIA_DISPATCH.get(criterion_key)
        #     if validator_name is None:
        #         continue  # unknown criterion — log and skip
        #     validator = globals()[validator_name]
        #     # Each validator's call signature varies; dispatch on
        #     # criterion_key shape rather than blindly calling.
        #     # See the per-criterion stubs above.
        #     ...
        #
        # result.overall_pass = all(c.passed for c in result.criterion_results)

    except NotImplementedError as e:
        result.failed_with_exception = str(e)
        result.overall_pass = False
    except Exception as e:
        result.failed_with_exception = f"{type(e).__name__}: {e}"
        result.overall_pass = False
    finally:
        result.elapsed_seconds = time.time() - t0

    return result
