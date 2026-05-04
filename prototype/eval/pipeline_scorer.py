"""Pipeline-fixture scorer for AGT-901 Pipeline Brain.

Reuses the existing per-fixture criterion check functions from scorer.py
where possible. Adds:
  - score_pipeline_fixture(fixture, corpus_dir): runs AGT-901 + scores
  - _check_must_cite_source: for pipeline fixtures that require a specific
    rollup table (e.g., "segment_rollup") to appear in sources_read

The pipeline brain takes the WHOLE corpus as input, so there's no per-account
account_path resolution. Otherwise the scoring shape is identical to AGT-902's.
"""

from __future__ import annotations

import sys
import time
from dataclasses import dataclass, field
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from agt901 import run_for_pipeline, ACTION_TAXONOMY as PIPELINE_TAXONOMY
from view_source import default_source
from validation import validate_all, ValidationResult

from scorer import (
    CriterionResult,
    _check_schema_compliance,
    _check_citations_resolve,
    _check_min_citation_count,
    _check_diagnosis_match,
    _check_expected_actions,
)


@dataclass
class PipelineFixtureResult:
    fixture_id: str
    fixture: dict
    brain_analysis_row: dict
    validation: ValidationResult
    criterion_results: list[CriterionResult] = field(default_factory=list)
    overall_pass: bool = False
    failed_with_exception: str | None = None
    elapsed_seconds: float = 0.0


def _check_action_taxonomy_pipeline(validation: ValidationResult) -> CriterionResult:
    """Pipeline-aware action taxonomy check — looks for taxonomy issues only."""
    issues = [i for i in validation.issues if i.category == "taxonomy"]
    return CriterionResult(
        "action_taxonomy_compliant",
        passed=len(issues) == 0,
        detail=(f"{len(validation.issues_by_category['taxonomy']) if hasattr(validation, 'issues_by_category') else len(issues)} taxonomy issues"
                if issues else f"{len(validation.proposed_actions if False else [])} actions all in enum"),
    )


def _check_must_cite_source(brain_output: dict, expected_source: str) -> CriterionResult:
    """Verify a specific rollup-table source appears in sources_read.
    e.g., expected_source='segment_rollup' for a segment-diagnosis fixture."""
    sources = brain_output.get("sources_read", [])
    cited = any(s.get("table_name") == expected_source for s in sources)
    return CriterionResult(
        f"must_cite_source({expected_source})",
        passed=cited,
        detail=(f"found {expected_source} in sources_read" if cited
                else f"sources_read does not include {expected_source}; "
                     f"saw {[s.get('table_name') for s in sources]}"),
    )


def score_pipeline_fixture(fixture: dict, corpus_dir: Path) -> PipelineFixtureResult:
    """Run AGT-901 against the fixture's question + score per criteria."""
    fixture_id = fixture["fixture_id"]
    result = PipelineFixtureResult(
        fixture_id=fixture_id,
        fixture=fixture,
        brain_analysis_row={},
        validation=ValidationResult(),
    )

    t0 = time.time()
    try:
        question = fixture["question"]
        brain_row = run_for_pipeline(corpus_dir, question=question,
                                     invocation_path="eval_run",
                                     source=default_source())
        result.brain_analysis_row = brain_row

        validation_input = {
            "narrative_output":            brain_row["narrative_output"],
            "sources_read":                brain_row["sources_read"],
            "proposed_actions":            brain_row["proposed_actions"],
            "confidence_flags":            brain_row["confidence_flags"],
            "data_staleness_acknowledged": brain_row["data_staleness_acknowledged"],
            "stale_sources":               brain_row["stale_sources"],
            # Dispatch-side ground truth for tool-call cross-check.
            "tool_calls_made":             brain_row.get("tool_calls_made", []),
        }
        # KEY DIFFERENCE FROM AGT-902 SCORER: pass the pipeline taxonomy
        result.validation = validate_all(validation_input, taxonomy=PIPELINE_TAXONOMY)

    except Exception as e:
        result.failed_with_exception = f"{type(e).__name__}: {e}"
        result.elapsed_seconds = time.time() - t0
        return result

    result.elapsed_seconds = time.time() - t0

    pc = fixture.get("pass_criteria", {})

    if pc.get("schema_compliance"):
        result.criterion_results.append(_check_schema_compliance(result.validation))

    if pc.get("citations_resolve"):
        result.criterion_results.append(_check_citations_resolve(result.validation))

    if pc.get("action_taxonomy_compliant"):
        # Reuse the taxonomy issue check — validation already used pipeline taxonomy
        from scorer import _check_action_taxonomy
        result.criterion_results.append(_check_action_taxonomy(result.validation))

    if pc.get("min_citation_count") is not None:
        result.criterion_results.append(
            _check_min_citation_count(brain_row["narrative_output"],
                                      pc["min_citation_count"])
        )

    if pc.get("diagnosis_match_pass"):
        result.criterion_results.append(
            _check_diagnosis_match(brain_row, fixture.get("expected_diagnosis", {}))
        )

    if pc.get("expected_actions_pass"):
        result.criterion_results.append(
            _check_expected_actions(brain_row, fixture.get("expected_actions", {}))
        )

    if pc.get("must_cite_source"):
        result.criterion_results.append(
            _check_must_cite_source(brain_row, pc["must_cite_source"])
        )

    result.overall_pass = all(c.passed for c in result.criterion_results)
    return result
