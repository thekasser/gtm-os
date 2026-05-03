"""Validation for AGT-902 brain output.

Per the AGT-902 + BrainAnalysisLog specs, every brain output must satisfy:
  1. Schema compliance (required fields present)
  2. Source citations resolve (every [src:N] in narrative_output points to a real source)
  3. Action taxonomy (every proposed_action.action_type is in the AGT-902 enum)
  4. Staleness disclosure (when data_staleness_acknowledged=true, narrative must say so)

Returns a list of issues. Empty list = clean output. Issues are categorized by
severity so callers can decide whether to gate (hard fail) or log (soft).
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Literal

from agt902 import ACTION_TAXONOMY


Severity = Literal["hard", "soft"]


@dataclass
class Issue:
    severity: Severity
    category: str
    detail: str

    def __str__(self) -> str:
        return f"[{self.severity.upper()}] {self.category}: {self.detail}"


# ─────────────────────────────────────────────────────────────────────
# Individual validators
# ─────────────────────────────────────────────────────────────────────

REQUIRED_FIELDS = [
    "narrative_output",
    "sources_read",
    "proposed_actions",
    "confidence_flags",
    "data_staleness_acknowledged",
    "stale_sources",
]


STALENESS_PHRASES = [
    "stale",
    "out of date",
    "out-of-date",
    "outdated",
    "last refreshed",
    "data freshness",
    "not fresh",
]


def validate_schema(output: dict) -> list[Issue]:
    issues: list[Issue] = []
    for f in REQUIRED_FIELDS:
        if f not in output:
            issues.append(Issue("hard", "schema", f"missing required field: {f}"))

    if "sources_read" in output and not isinstance(output["sources_read"], list):
        issues.append(Issue("hard", "schema", "sources_read must be a list"))

    if "proposed_actions" in output and not isinstance(output["proposed_actions"], list):
        issues.append(Issue("hard", "schema", "proposed_actions must be a list"))

    if "confidence_flags" in output and not isinstance(output["confidence_flags"], list):
        issues.append(Issue("hard", "schema", "confidence_flags must be a list"))

    if "data_staleness_acknowledged" in output and not isinstance(
        output["data_staleness_acknowledged"], bool
    ):
        issues.append(Issue("hard", "schema", "data_staleness_acknowledged must be bool"))

    return issues


_CITATION_RE = re.compile(r"\[src:(\d+)\]")


def validate_citations(output: dict) -> list[Issue]:
    """Every [src:N] in narrative_output must have a matching source_index in sources_read."""
    issues: list[Issue] = []
    narrative = output.get("narrative_output", "")
    sources = output.get("sources_read", [])
    valid_indices = {s.get("source_index") for s in sources if isinstance(s, dict)}

    cited = [int(m) for m in _CITATION_RE.findall(narrative)]
    if not cited:
        # Soft warning: narrative with no citations is suspicious unless it's purely qualitative
        issues.append(Issue("soft", "citations",
                            "narrative_output has zero source citations — every numerical claim should cite [src:N]"))
        return issues

    for idx in set(cited):
        if idx not in valid_indices:
            issues.append(Issue("hard", "citations",
                                f"narrative cites [src:{idx}] but sources_read has no source_index={idx}"))

    citation_count = len(cited)
    return issues


def validate_action_taxonomy(output: dict,
                             taxonomy: list[str] | None = None) -> list[Issue]:
    """Every proposed_action.action_type must be in the supplied enum.

    Default taxonomy is AGT-902's. AGT-901 (Pipeline Brain) passes its own
    enum (draft_play / flag_coverage_gap / recommend_query_for_human / none).
    """
    issues: list[Issue] = []
    enum = taxonomy if taxonomy is not None else ACTION_TAXONOMY
    actions = output.get("proposed_actions", [])
    for i, action in enumerate(actions):
        if not isinstance(action, dict):
            issues.append(Issue("hard", "taxonomy",
                                f"proposed_actions[{i}] is not an object"))
            continue
        action_type = action.get("action_type")
        if action_type not in enum:
            issues.append(Issue("hard", "taxonomy",
                                f"proposed_actions[{i}].action_type='{action_type}' not in enum: "
                                f"{enum}"))
    return issues


def validate_staleness_disclosure(output: dict) -> list[Issue]:
    """When data_staleness_acknowledged=true, narrative must surface staleness."""
    issues: list[Issue] = []
    if output.get("data_staleness_acknowledged") is True:
        narrative = output.get("narrative_output", "").lower()
        if not any(phrase in narrative for phrase in STALENESS_PHRASES):
            issues.append(Issue("hard", "staleness",
                                f"data_staleness_acknowledged=true but narrative doesn't surface staleness "
                                f"(must contain one of: {STALENESS_PHRASES})"))
    return issues


def validate_confidence_flags(output: dict) -> list[Issue]:
    """Soft check: confidence flag distribution should not be 100% high_confidence."""
    issues: list[Issue] = []
    flags = output.get("confidence_flags", [])
    if not flags:
        issues.append(Issue("soft", "confidence",
                            "no confidence_flags emitted — calibration is unverifiable"))
        return issues

    levels = [f.get("level") for f in flags if isinstance(f, dict)]
    valid_levels = {"high_confidence", "multi_source", "inference", "speculation"}
    invalid = [lv for lv in levels if lv not in valid_levels]
    for lv in invalid:
        issues.append(Issue("hard", "confidence",
                            f"unknown confidence level: '{lv}' (valid: {valid_levels})"))

    if levels and all(lv == "high_confidence" for lv in levels):
        issues.append(Issue("soft", "confidence",
                            "all flags are high_confidence — possibly dishonest calibration"))
    return issues


# ─────────────────────────────────────────────────────────────────────
# Aggregator
# ─────────────────────────────────────────────────────────────────────

@dataclass
class ValidationResult:
    issues: list[Issue] = field(default_factory=list)
    citation_count: int = 0
    proposed_action_count: int = 0
    confidence_flag_count: int = 0

    @property
    def has_hard_failure(self) -> bool:
        return any(i.severity == "hard" for i in self.issues)

    @property
    def has_any_issues(self) -> bool:
        return len(self.issues) > 0


def validate_all(output: dict,
                 taxonomy: list[str] | None = None) -> ValidationResult:
    """Run all validators. Returns a ValidationResult with issues + summary stats.

    `taxonomy` overrides the default (AGT-902) action enum. Pass AGT-901's
    enum when validating pipeline-brain output.
    """
    result = ValidationResult()
    result.issues.extend(validate_schema(output))
    result.issues.extend(validate_citations(output))
    result.issues.extend(validate_action_taxonomy(output, taxonomy=taxonomy))
    result.issues.extend(validate_staleness_disclosure(output))
    result.issues.extend(validate_confidence_flags(output))

    result.citation_count = len(_CITATION_RE.findall(output.get("narrative_output", "")))
    result.proposed_action_count = len(output.get("proposed_actions", []))
    result.confidence_flag_count = len(output.get("confidence_flags", []))
    return result
