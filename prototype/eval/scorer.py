"""Scoring logic for AGT-902 eval fixtures.

Each fixture defines pass criteria. The scorer:
  1. Resolves the corpus account from account_selection
  2. Applies any fixture_mutations (e.g., force_stale) via a view_mutation_fn
     handed to agt902.run_for_account
  3. Runs AGT-902 (writes BrainAnalysisLog row)
  4. Runs validation.py (schema/citations/taxonomy/staleness/confidence)
  5. Runs fixture-specific checks (mentions, expected actions, etc.)
  6. Returns a structured FixtureResult

The scorer reuses agt902 + validation modules — no duplicated logic.
"""

from __future__ import annotations

import json
import sys
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

# Allow imports of sibling prototype modules (agt902, validation, brain_analysis_log)
_PROTOTYPE_DIR = Path(__file__).parent.parent.resolve()
if str(_PROTOTYPE_DIR) not in sys.path:
    sys.path.insert(0, str(_PROTOTYPE_DIR))

from agt902 import run_for_account, DEFAULT_QUESTION
from validation import validate_all, ValidationResult
from brain_analysis_log import append_row as append_brain_analysis_row


# ─────────────────────────────────────────────────────────────────────
# Result containers
# ─────────────────────────────────────────────────────────────────────

@dataclass
class CriterionResult:
    name: str
    passed: bool
    detail: str = ""

    def __str__(self) -> str:
        flag = "✓" if self.passed else "✗"
        return f"  {flag} {self.name}" + (f" — {self.detail}" if self.detail else "")


@dataclass
class FixtureResult:
    fixture_id: str
    fixture: dict
    account_id: str
    company_name: str
    archetype_key: str
    brain_analysis_row: dict
    validation: ValidationResult
    criterion_results: list[CriterionResult] = field(default_factory=list)
    overall_pass: bool = False
    elapsed_seconds: float = 0.0
    failed_with_exception: str | None = None

    @property
    def hard_failures(self) -> list[CriterionResult]:
        return [c for c in self.criterion_results if not c.passed]


# ─────────────────────────────────────────────────────────────────────
# Account resolution
# ─────────────────────────────────────────────────────────────────────

def resolve_account_path(corpus_dir: Path, selection: dict) -> Path:
    """Resolve fixture's account_selection into a corpus file path."""
    method = selection["method"]
    files = sorted(p for p in corpus_dir.glob("*.json") if p.name != "ground_truth.json")

    if method == "by_archetype":
        archetype = selection["archetype"]
        index = selection.get("index", 0)
        matches = []
        for path in files:
            with path.open() as f:
                data = json.load(f)
            if data.get("archetype_key") == archetype:
                matches.append(path)
        if not matches:
            raise ValueError(f"No corpus accounts with archetype='{archetype}'")
        if index >= len(matches):
            raise ValueError(
                f"archetype='{archetype}' has {len(matches)} accounts, "
                f"requested index={index}"
            )
        return matches[index]

    if method == "by_uuid_prefix":
        prefix = selection["prefix"].lower()
        for path in files:
            if path.stem.lower().startswith(prefix):
                return path
        raise ValueError(f"No corpus account UUID starts with '{prefix}'")

    if method == "by_company_name":
        name = selection["company_name"].lower()
        for path in files:
            with path.open() as f:
                data = json.load(f)
            if name in data["account"]["company_name"].lower():
                return path
        raise ValueError(f"No corpus account with company_name containing '{name}'")

    raise ValueError(f"Unknown account_selection.method: {method}")


# ─────────────────────────────────────────────────────────────────────
# Fixture mutations (for stale-data fixtures)
# ─────────────────────────────────────────────────────────────────────

def make_view_mutation_fn(mutations: dict | None) -> Callable[[dict], dict] | None:
    """Build a view_mutation_fn from a fixture's fixture_mutations dict.

    Currently supported mutations:
      force_stale=True       sets view_metadata.is_stale=True
      stale_components=[...] sets view_metadata.stale_components
      stale_age_hours=N      sets last_refresh_timestamp to now-N-hours
    """
    if not mutations:
        return None

    def mutate(view: dict) -> dict:
        if mutations.get("force_stale"):
            view["view_metadata"]["is_stale"] = True
        if mutations.get("stale_components"):
            view["view_metadata"]["stale_components"] = mutations["stale_components"]
        if mutations.get("stale_age_hours") is not None:
            from datetime import timedelta
            now = datetime.now(timezone.utc)
            stale_at = now - timedelta(hours=mutations["stale_age_hours"])
            view["view_metadata"]["last_refresh_timestamp"] = stale_at.isoformat()
            view["view_metadata"]["staleness_threshold_hours"] = mutations.get(
                "staleness_threshold_hours", 24
            )
        return view

    return mutate


# ─────────────────────────────────────────────────────────────────────
# Per-criterion checks
# ─────────────────────────────────────────────────────────────────────

def _check_schema_compliance(validation: ValidationResult) -> CriterionResult:
    schema_issues = [i for i in validation.issues if i.category == "schema" and i.severity == "hard"]
    return CriterionResult(
        "schema_compliance",
        passed=len(schema_issues) == 0,
        detail=f"{len(schema_issues)} schema issues" if schema_issues else "all required fields present",
    )


def _check_citations_resolve(validation: ValidationResult) -> CriterionResult:
    citation_issues = [
        i for i in validation.issues if i.category == "citations" and i.severity == "hard"
    ]
    return CriterionResult(
        "citations_resolve",
        passed=len(citation_issues) == 0,
        detail=(f"{len(citation_issues)} unresolved citations"
                if citation_issues else f"{validation.citation_count} citations all resolve"),
    )


def _check_action_taxonomy(validation: ValidationResult) -> CriterionResult:
    taxonomy_issues = [i for i in validation.issues if i.category == "taxonomy"]
    return CriterionResult(
        "action_taxonomy_compliant",
        passed=len(taxonomy_issues) == 0,
        detail=(f"{len(taxonomy_issues)} non-enum action types"
                if taxonomy_issues else f"{validation.proposed_action_count} actions all in enum"),
    )


def _check_min_citation_count(narrative: str, threshold: int) -> CriterionResult:
    import re
    count = len(re.findall(r"\[src:\d+\]", narrative))
    return CriterionResult(
        f"min_citation_count >= {threshold}",
        passed=count >= threshold,
        detail=f"found {count} citations",
    )


def _check_must_cite_tool(brain_output: dict, tool_name: str) -> CriterionResult:
    """Verify the brain ACTUALLY CALLED the named tool AND cited it.

    Two checks (both required):
      1. tool_calls_made (dispatch-side ground truth) contains the tool
      2. sources_read (brain-authored narrative) contains the tool

    The dual check prevents two failure modes:
      - Brain fabricates a citation in sources_read for a tool it never called.
        Found during calibration probe — when TOOL_DEFINITIONS hides a tool
        but the system prompt still describes it, the brain may cite the tool
        anyway. tool_calls_made would be empty in that case.
      - Brain calls the tool but forgets to cite it in narrative. Less
        dangerous but still wrong — the user can't trace the claim.
    """
    sources = brain_output.get("sources_read", [])
    tool_calls = brain_output.get("tool_calls_made", []) or []

    cited_in_sources = any(s.get("table_name") == tool_name for s in sources)
    actually_called = any(tc.get("tool_name") == tool_name
                          and tc.get("tool_result_status") == "ok"
                          for tc in tool_calls)

    passed = cited_in_sources and actually_called
    if passed:
        detail = f"called and cited {tool_name}"
    elif actually_called and not cited_in_sources:
        detail = (f"tool was called but NOT cited in sources_read — "
                  f"narrative-side citation missing")
    elif cited_in_sources and not actually_called:
        detail = (f"sources_read claims to cite {tool_name} but tool_calls_made "
                  f"shows no successful call — possible fabricated citation. "
                  f"saw tool_calls: {[tc.get('tool_name') for tc in tool_calls]}")
    else:
        detail = (f"tool was neither called nor cited. "
                  f"sources_read: {[s.get('table_name') for s in sources]}, "
                  f"tool_calls_made: {[tc.get('tool_name') for tc in tool_calls]}")

    return CriterionResult(
        f"must_cite_tool({tool_name})",
        passed=passed,
        detail=detail,
    )


def _check_diagnosis_match(brain_output: dict, expected_diagnosis: dict) -> CriterionResult:
    """Check should_mention phrases (substring, case-insensitive) and should_not_mention."""
    narrative = brain_output["narrative_output"].lower()

    should_mention = [s.lower() for s in expected_diagnosis.get("should_mention", [])]
    should_not_mention = [s.lower() for s in expected_diagnosis.get("should_not_mention", [])]

    matched = [s for s in should_mention if s in narrative]
    bad_matches = [s for s in should_not_mention if s in narrative]

    min_drivers = expected_diagnosis.get("min_drivers_matched", 0)
    # Use should_mention as the proxy for drivers (each should_mention is a conceptual driver keyword)
    drivers_satisfied = len(matched) >= min_drivers if should_mention else True
    no_bad_phrases = len(bad_matches) == 0

    passed = drivers_satisfied and no_bad_phrases
    detail_parts = []
    if should_mention:
        detail_parts.append(f"matched {len(matched)}/{len(should_mention)} should_mention")
    if bad_matches:
        detail_parts.append(f"FOUND should_not_mention: {bad_matches}")

    return CriterionResult(
        "diagnosis_match",
        passed=passed,
        detail=" | ".join(detail_parts) if detail_parts else "no diagnosis phrases configured",
    )


def _check_expected_actions(brain_output: dict, expected_actions: dict) -> CriterionResult:
    actual_action_types = {a.get("action_type") for a in brain_output.get("proposed_actions", [])}

    must_include = expected_actions.get("must_include_at_least_one_of", [])
    must_not_include = expected_actions.get("must_not_include", [])

    inclusion_pass = (
        len(must_include) == 0
        or any(a in actual_action_types for a in must_include)
    )
    exclusion_pass = not any(a in actual_action_types for a in must_not_include)

    passed = inclusion_pass and exclusion_pass

    detail_parts = []
    if must_include:
        matching = [a for a in must_include if a in actual_action_types]
        detail_parts.append(
            f"matched {matching}/{must_include}" if matching
            else f"NONE of {must_include} included"
        )
    bad = [a for a in must_not_include if a in actual_action_types]
    if bad:
        detail_parts.append(f"INCLUDED {bad} (must_not_include)")

    return CriterionResult(
        "expected_actions",
        passed=passed,
        detail=" | ".join(detail_parts) if detail_parts else "no action constraints configured",
    )


def _check_data_staleness_acknowledged(brain_output: dict) -> CriterionResult:
    val = brain_output.get("data_staleness_acknowledged")
    return CriterionResult(
        "data_staleness_acknowledged",
        passed=val is True,
        detail=f"data_staleness_acknowledged={val}",
    )


_STALENESS_PHRASES = ["stale", "out of date", "out-of-date", "outdated",
                      "last refreshed", "data freshness", "not fresh"]


def _check_narrative_contains_staleness(narrative: str) -> CriterionResult:
    lower = narrative.lower()
    found = [p for p in _STALENESS_PHRASES if p in lower]
    return CriterionResult(
        "narrative_contains_staleness",
        passed=len(found) > 0,
        detail=f"found phrases: {found}" if found else "no staleness phrase in narrative",
    )


# ─────────────────────────────────────────────────────────────────────
# Per-fixture orchestration
# ─────────────────────────────────────────────────────────────────────

def score_fixture(fixture: dict, corpus_dir: Path,
                  brain_log_path: Path) -> FixtureResult:
    """Run AGT-902 on the fixture's account, validate, score per criteria."""
    fixture_id = fixture["fixture_id"]
    account_path = resolve_account_path(corpus_dir, fixture["account_selection"])

    with account_path.open() as f:
        corpus_data = json.load(f)
    company = corpus_data["account"]["company_name"]
    archetype = corpus_data.get("archetype_key", "?")
    account_id = corpus_data["account"]["account_id"]

    result = FixtureResult(
        fixture_id=fixture_id,
        fixture=fixture,
        account_id=account_id,
        company_name=company,
        archetype_key=archetype,
        brain_analysis_row={},
        validation=ValidationResult(),
    )

    t0 = time.time()
    try:
        view_mutation_fn = make_view_mutation_fn(fixture.get("fixture_mutations"))
        question = fixture.get("question", DEFAULT_QUESTION)

        brain_row = run_for_account(
            account_path,
            question=question,
            invocation_path="eval_run",
            view_mutation_fn=view_mutation_fn,
        )
        result.brain_analysis_row = brain_row

        # Persist BrainAnalysisLog for joinability with BrainEvalLog
        append_brain_analysis_row(brain_row, brain_log_path)

        # Build a minimal output dict for validators
        validation_input = {
            "narrative_output":            brain_row["narrative_output"],
            "sources_read":                brain_row["sources_read"],
            "proposed_actions":            brain_row["proposed_actions"],
            "confidence_flags":            brain_row["confidence_flags"],
            "data_staleness_acknowledged": brain_row["data_staleness_acknowledged"],
            "stale_sources":               brain_row["stale_sources"],
            # Dispatch-side ground truth — used by _check_must_cite_tool to
            # cross-check against narrative-side sources_read and catch
            # fabricated citations.
            "tool_calls_made":             brain_row.get("tool_calls_made", []),
        }
        result.validation = validate_all(validation_input)

    except Exception as e:
        result.failed_with_exception = f"{type(e).__name__}: {e}"
        result.elapsed_seconds = time.time() - t0
        result.overall_pass = False
        return result

    result.elapsed_seconds = time.time() - t0

    # ─── Run per-criterion checks ─────────────────────────────────
    pc = fixture["pass_criteria"]
    brain_out = validation_input

    if pc.get("schema_compliance"):
        result.criterion_results.append(_check_schema_compliance(result.validation))

    if pc.get("citations_resolve"):
        result.criterion_results.append(_check_citations_resolve(result.validation))

    if pc.get("action_taxonomy_compliant"):
        result.criterion_results.append(_check_action_taxonomy(result.validation))

    if pc.get("min_citation_count") is not None:
        result.criterion_results.append(
            _check_min_citation_count(brain_out["narrative_output"], pc["min_citation_count"])
        )

    if pc.get("diagnosis_match_pass"):
        result.criterion_results.append(
            _check_diagnosis_match(brain_out, fixture.get("expected_diagnosis", {}))
        )

    if pc.get("expected_actions_pass"):
        result.criterion_results.append(
            _check_expected_actions(brain_out, fixture.get("expected_actions", {}))
        )

    if pc.get("data_staleness_acknowledged"):
        result.criterion_results.append(_check_data_staleness_acknowledged(brain_out))

    if pc.get("narrative_contains_staleness"):
        result.criterion_results.append(
            _check_narrative_contains_staleness(brain_out["narrative_output"])
        )

    if pc.get("must_cite_tool_004"):
        result.criterion_results.append(
            _check_must_cite_tool(brain_out, "tool_004_consumption_forecast")
        )

    if pc.get("must_cite_tool_008"):
        result.criterion_results.append(
            _check_must_cite_tool(brain_out, "tool_008_product_adoption_pattern")
        )

    result.overall_pass = all(c.passed for c in result.criterion_results)
    return result
