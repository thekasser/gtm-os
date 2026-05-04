"""Calibration probes — verify eval-harness rules have teeth.

Run anytime; idempotent and cost-free (no API calls). Each probe constructs
a synthetic brain output that VIOLATES one specific rule, feeds it through
the validator, and asserts the validator caught the violation.

If a probe fails (validator did NOT catch the violation), that means the
harness has a blind spot — investigate the validator immediately.

Why this exists:

The full eval harness only catches what its fixtures happen to exercise. If
a brain regression introduces, say, an off-enum action_type that no fixture
specifically tests, the eval might still pass overall — the harness needs
to PROVE its rules trigger when violated. These probes are the explicit
proof, written once and re-runnable forever.

Probes also serve as documentation: each one is an executable example of
what a violation of a specific rule looks like.

Usage:
    cd prototype
    ../synth/venv/bin/python3 eval/calibration_probes.py

Exit 0 = all probes passed (validator behaving correctly).
Exit 1 = at least one probe failed (validator has a blind spot).
"""

from __future__ import annotations

import sys
from dataclasses import dataclass
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from validation import (
    validate_all,
    validate_action_taxonomy,
    validate_citations,
    Issue,
)
from agt902 import ACTION_TAXONOMY as AGT902_TAXONOMY
from agt901 import ACTION_TAXONOMY as AGT901_TAXONOMY


@dataclass
class ProbeResult:
    name: str
    passed: bool
    detail: str


def _has_issue(issues: list[Issue], category: str, severity: str = "hard") -> bool:
    return any(i.category == category and i.severity == severity for i in issues)


# ─────────────────────────────────────────────────────────────────────
# C1 — action_taxonomy_compliant: invented action_type
# ─────────────────────────────────────────────────────────────────────

def probe_c1_invented_action_type() -> ProbeResult:
    """Brain produces an action_type not in the AGT-902 enum.

    Validator should emit a hard `taxonomy` issue.
    """
    synthetic_brain_output = {
        "narrative_output": "claim [src:1]",
        "sources_read": [
            {"source_index": 1, "table_name": "customer_health",
             "view_name": "account_brain_view", "row_count_consumed": 1}
        ],
        "proposed_actions": [
            {"action_type": "fabricated_action_type_not_in_enum",
             "target": "test", "lever": "test",
             "justification": "test [src:1]", "confidence": "low"},
        ],
        "confidence_flags": [{"claim": "test", "level": "speculation",
                              "supporting_source_indices": [1]}],
        "data_staleness_acknowledged": False,
        "stale_sources": [],
    }
    issues = validate_action_taxonomy(synthetic_brain_output,
                                      taxonomy=AGT902_TAXONOMY)
    caught = _has_issue(issues, "taxonomy", "hard")
    return ProbeResult(
        "C1: invented action_type (AGT-902 enum)",
        passed=caught,
        detail=("validator emitted taxonomy issue as expected"
                if caught else
                f"VALIDATOR BLIND SPOT — issues returned: {issues}"),
    )


def probe_c1b_invented_action_type_pipeline() -> ProbeResult:
    """Same probe against the AGT-901 enum (different action vocabulary)."""
    synthetic_brain_output = {
        "narrative_output": "cohort claim [src:1]",
        "sources_read": [
            {"source_index": 1, "table_name": "segment_rollup",
             "view_name": "pipeline_aggregate", "row_count_consumed": 5}
        ],
        "proposed_actions": [
            # 'open_expansion_play' is in AGT-902 enum but NOT in AGT-901 enum.
            # Validator should treat it as off-enum when AGT-901 taxonomy is
            # passed.
            {"action_type": "open_expansion_play",
             "target": "MM segment", "lever": "AGT-203",
             "justification": "test [src:1]", "confidence": "medium"},
        ],
        "confidence_flags": [],
        "data_staleness_acknowledged": False,
        "stale_sources": [],
    }
    issues = validate_action_taxonomy(synthetic_brain_output,
                                      taxonomy=AGT901_TAXONOMY)
    caught = _has_issue(issues, "taxonomy", "hard")
    return ProbeResult(
        "C1b: AGT-902 action_type leaked into AGT-901 enum",
        passed=caught,
        detail=("validator caught the cross-enum leak"
                if caught else
                f"VALIDATOR BLIND SPOT — taxonomy parameter not enforced; issues: {issues}"),
    )


# ─────────────────────────────────────────────────────────────────────
# C2 — citations_resolve: narrative cites unresolved [src:N]
# ─────────────────────────────────────────────────────────────────────

def probe_c2_unresolved_citation() -> ProbeResult:
    """Narrative cites [src:99] but sources_read has no source_index 99.

    Validator should emit a hard `citations` issue.
    """
    synthetic_brain_output = {
        "narrative_output": (
            "Account is at risk [src:1]. Renewal in 30 days [src:2]. "
            "Hallucinated factoid [src:99]."
        ),
        "sources_read": [
            {"source_index": 1, "table_name": "customer_health",
             "view_name": "account_brain_view", "row_count_consumed": 1},
            {"source_index": 2, "table_name": "churn_risk",
             "view_name": "account_brain_view", "row_count_consumed": 1},
            # Note: no source_index 99
        ],
        "proposed_actions": [
            {"action_type": "none", "target": "—", "lever": "—",
             "justification": "test [src:1]", "confidence": "high"},
        ],
        "confidence_flags": [{"claim": "test", "level": "high_confidence",
                              "supporting_source_indices": [1]}],
        "data_staleness_acknowledged": False,
        "stale_sources": [],
    }
    issues = validate_citations(synthetic_brain_output)
    caught = _has_issue(issues, "citations", "hard")
    return ProbeResult(
        "C2: unresolved [src:99] citation",
        passed=caught,
        detail=("validator emitted citations issue as expected"
                if caught else
                f"VALIDATOR BLIND SPOT — issues: {issues}"),
    )


def probe_c2b_negative_control_resolved_citations() -> ProbeResult:
    """Negative control: all citations resolve. Validator should be silent
    on the citations rule (no false positives)."""
    synthetic_brain_output = {
        "narrative_output": "Account is at risk [src:1]. Renewal soon [src:2].",
        "sources_read": [
            {"source_index": 1, "table_name": "customer_health",
             "view_name": "account_brain_view", "row_count_consumed": 1},
            {"source_index": 2, "table_name": "churn_risk",
             "view_name": "account_brain_view", "row_count_consumed": 1},
        ],
        "proposed_actions": [],
        "confidence_flags": [],
        "data_staleness_acknowledged": False,
        "stale_sources": [],
    }
    issues = validate_citations(synthetic_brain_output)
    no_false_positive = not _has_issue(issues, "citations", "hard")
    return ProbeResult(
        "C2b: negative control — all citations resolve cleanly",
        passed=no_false_positive,
        detail=("validator silent on resolved citations as expected"
                if no_false_positive else
                f"FALSE POSITIVE — validator complained on valid citations: {issues}"),
    )


# ─────────────────────────────────────────────────────────────────────
# Wiring rule probe — taxonomy default vs. parameterized
# ─────────────────────────────────────────────────────────────────────

def probe_taxonomy_default_is_agt902() -> ProbeResult:
    """When `validate_all` is called without `taxonomy=`, the default is
    AGT-902's enum. Confirms the AGT-902 default is in effect.
    """
    output_with_agt902_action = {
        "narrative_output": "[src:1]",
        "sources_read": [{"source_index": 1, "table_name": "x",
                          "view_name": "v", "row_count_consumed": 1}],
        "proposed_actions": [{"action_type": "open_expansion_play",
                              "target": "x", "lever": "x",
                              "justification": "x [src:1]", "confidence": "low"}],
        "confidence_flags": [],
        "data_staleness_acknowledged": False,
        "stale_sources": [],
    }
    result = validate_all(output_with_agt902_action)  # default taxonomy
    no_taxonomy_issue = not _has_issue(result.issues, "taxonomy", "hard")
    return ProbeResult(
        "Default taxonomy = AGT-902 enum (sanity check)",
        passed=no_taxonomy_issue,
        detail=("default taxonomy matches AGT-902"
                if no_taxonomy_issue else
                f"BLIND SPOT — default taxonomy rejected open_expansion_play: {result.issues}"),
    )


# ─────────────────────────────────────────────────────────────────────
# Driver
# ─────────────────────────────────────────────────────────────────────

PROBES = [
    probe_c1_invented_action_type,
    probe_c1b_invented_action_type_pipeline,
    probe_c2_unresolved_citation,
    probe_c2b_negative_control_resolved_citations,
    probe_taxonomy_default_is_agt902,
]


def main():
    print("=" * 70)
    print("CALIBRATION PROBES — verifying eval-harness rule teeth")
    print("=" * 70)
    print()
    results = []
    for probe in PROBES:
        try:
            r = probe()
        except Exception as e:
            r = ProbeResult(probe.__name__, passed=False,
                            detail=f"PROBE EXCEPTION: {type(e).__name__}: {e}")
        results.append(r)
        marker = "OK" if r.passed else "XX"
        print(f"  {marker}  {r.name}")
        print(f"      {r.detail}")
        print()

    passed = sum(1 for r in results if r.passed)
    total = len(results)
    print("=" * 70)
    print(f"AGGREGATE: {passed}/{total} probes passed")
    if passed < total:
        print()
        print("FAILURES indicate the validator has a blind spot for the named rule.")
        print("Investigate prototype/validation.py and re-run.")
    print("=" * 70)
    sys.exit(0 if passed == total else 1)


if __name__ == "__main__":
    main()
