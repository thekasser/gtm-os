"""BrainViewSource — the seam between Tier 1 data and Tier 2 brain views.

Brain runtimes (AGT-901, AGT-902) and Tier 3 tools (TOOL-004, TOOL-008)
should NEVER read corpus files directly. They go through a BrainViewSource.
This makes the prototype source-agnostic: swap synth corpus → real warehouse
without modifying brain code.

Two implementations:

  SynthCorpusSource    Reads per-account JSON files from synth/corpus/.
                       Used for the prototype.

  WarehouseViewSource  Stub — raises NotImplementedError. Documents the
                       interface a corporate-environment implementation
                       would fulfill (queries against the canonical
                       Tier 1 tables: CustomerHealthLog, UsageMeteringLog,
                       PaymentEventLog, ConvIntelligence, etc.).

Adding a new source type means subclassing BrainViewSource and implementing
all abstract methods. Brain runtimes accept the source as a constructor
argument; the eval harness and CLI default to SynthCorpusSource pointed at
the synth corpus directory.
"""

from __future__ import annotations

import json
import os
from abc import ABC, abstractmethod
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterator


# ─────────────────────────────────────────────────────────────────────
# Abstract interface
# ─────────────────────────────────────────────────────────────────────

class BrainViewSource(ABC):
    """The contract every source implementation fulfills.

    Brains and tools depend ONLY on these methods. Any implementation
    that satisfies the contract — synthetic corpus, BigQuery, Snowflake,
    Postgres — is a drop-in.
    """

    # ── Per-account access (used by AGT-902, TOOL-004, TOOL-008) ──

    @abstractmethod
    def load_account_corpus(self, account_id: str) -> dict:
        """Return the per-account composite. Shape matches the synth corpus
        JSON: keys = account, archetype_key, expected_outcome_label,
        usage_metering_log, customer_health_log, payment_event_log,
        conversation_intelligence_log, feature_engagement, summary.

        In a corporate environment, this method joins across the canonical
        Tier 1 tables to produce the same shape on demand.
        """
        raise NotImplementedError

    @abstractmethod
    def account_exists(self, account_id: str) -> bool:
        """Cheap existence check. Used by the eval harness."""
        raise NotImplementedError

    @abstractmethod
    def account_data_freshness(self, account_id: str) -> tuple[bool, str]:
        """Return (is_stale, last_refresh_iso). The brain-ready view extractor
        uses this to populate view_metadata.is_stale.

        is_stale == True means downstream code should surface staleness in
        narrative output and gate decisions on it.
        """
        raise NotImplementedError

    # ── Cross-account access (used by AGT-901 aggregate view) ──

    @abstractmethod
    def iterate_account_ids(self) -> Iterator[str]:
        """Yield all account IDs in scope. Implementations can filter by
        active vs. churned, segment, etc. — for the prototype, this is
        every account in the synth corpus."""
        raise NotImplementedError

    @abstractmethod
    def metadata(self) -> dict:
        """Source identification + corpus-level stats:
        {
          "source_type": "synth_corpus" | "warehouse" | ...,
          "snapshot_date": "YYYY-MM-DD",
          "account_count": int,
          "source_specific_metadata": {...}
        }
        """
        raise NotImplementedError


# ─────────────────────────────────────────────────────────────────────
# Synthetic corpus implementation
# ─────────────────────────────────────────────────────────────────────

class SynthCorpusSource(BrainViewSource):
    """Reads per-account JSON files from a synth corpus directory.

    The default for the prototype. Backed by the corpus that
    `synth/main.py` produces (50 accounts of synthetic Tier 1 telemetry).

    Staleness model: file mtime + a configurable threshold (default 24h).
    The eval harness sometimes mutates the view to force staleness for
    fixture testing (see scorer.make_view_mutation_fn).
    """

    DEFAULT_STALENESS_THRESHOLD_HOURS = 24

    def __init__(self, corpus_dir: Path | str,
                 staleness_threshold_hours: float | None = None):
        self.corpus_dir = Path(corpus_dir)
        if not self.corpus_dir.exists():
            raise FileNotFoundError(f"corpus directory not found: {self.corpus_dir}")
        self.staleness_threshold_hours = (
            staleness_threshold_hours if staleness_threshold_hours is not None
            else self.DEFAULT_STALENESS_THRESHOLD_HOURS
        )
        self._account_paths_cache: dict[str, Path] | None = None

    # ── BrainViewSource impl ────────────────────────────────────

    def load_account_corpus(self, account_id: str) -> dict:
        path = self._account_path(account_id)
        with path.open() as f:
            return json.load(f)

    def account_exists(self, account_id: str) -> bool:
        return self._account_path_or_none(account_id) is not None

    def account_data_freshness(self, account_id: str) -> tuple[bool, str]:
        path = self._account_path(account_id)
        mtime = datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc)
        age_hours = (datetime.now(timezone.utc) - mtime).total_seconds() / 3600
        is_stale = age_hours > self.staleness_threshold_hours
        return is_stale, mtime.isoformat()

    def iterate_account_ids(self) -> Iterator[str]:
        gt_path = self.corpus_dir / "ground_truth.json"
        if gt_path.exists():
            with gt_path.open() as f:
                gt = json.load(f)
            for entry in gt.get("accounts", []):
                yield entry["account_id"]
            return
        # Fallback: scan directory
        for p in self.corpus_dir.glob("*.json"):
            if p.stem == "ground_truth":
                continue
            yield p.stem

    def metadata(self) -> dict:
        gt_path = self.corpus_dir / "ground_truth.json"
        snapshot = "unknown"
        count = 0
        if gt_path.exists():
            with gt_path.open() as f:
                gt = json.load(f)
            snapshot = (gt.get("generated_at", "") or "").split("T")[0] or "unknown"
            count = gt.get("account_count", len(gt.get("accounts", [])))
        return {
            "source_type": "synth_corpus",
            "snapshot_date": snapshot,
            "account_count": count,
            "source_specific_metadata": {
                "corpus_dir": str(self.corpus_dir),
                "staleness_threshold_hours": self.staleness_threshold_hours,
            },
        }

    # ── Path helpers ────────────────────────────────────────────

    def _account_path(self, account_id: str) -> Path:
        path = self._account_path_or_none(account_id)
        if path is None:
            raise FileNotFoundError(
                f"no corpus file for account_id={account_id} in {self.corpus_dir}"
            )
        return path

    def _account_path_or_none(self, account_id: str) -> Path | None:
        # Fast path: <account_id>.json
        direct = self.corpus_dir / f"{account_id}.json"
        if direct.exists():
            return direct
        # Slow path: scan
        if self._account_paths_cache is None:
            self._account_paths_cache = {
                p.stem: p for p in self.corpus_dir.glob("*.json")
                if p.stem != "ground_truth"
            }
        return self._account_paths_cache.get(account_id)


# ─────────────────────────────────────────────────────────────────────
# Warehouse stub — what a corporate-env implementation looks like
# ─────────────────────────────────────────────────────────────────────

class WarehouseViewSource(BrainViewSource):
    """Stub implementation showing the shape of a corporate-warehouse source.

    All methods raise NotImplementedError. A real implementation joins the
    canonical Tier 1 tables (CustomerHealthLog, UsageMeteringLog,
    PaymentEventLog, ConvIntelligence, ExpansionLog, ChurnRiskLog, etc.) to
    produce the same per-account composite shape that SynthCorpusSource
    returns.

    Connection config (db host, credentials, etc.) is implementation-specific
    and passed via the constructor.

    See prototype/PORT_TO_CORPORATE.md for the full migration plan.
    """

    def __init__(self, connection_config: dict):
        self.connection_config = connection_config
        # In a real implementation: connect to warehouse, validate access, etc.

    def load_account_corpus(self, account_id: str) -> dict:
        # Real impl: SELECT … JOIN across CustomerHealthLog, UsageMeteringLog,
        # PaymentEventLog, ConvIntelligence_with_call_owner_role_filter,
        # ExpansionLog, ChurnRiskLog, feature_engagement_telemetry, account
        # → compose into the same shape SynthCorpusSource returns.
        # Cache aggressively at the warehouse layer; brain calls hit this often.
        raise NotImplementedError(
            "Implement a real warehouse query — join Tier 1 tables into the "
            "per-account composite shape. See prototype/PORT_TO_CORPORATE.md."
        )

    def account_exists(self, account_id: str) -> bool:
        # Real impl: SELECT 1 FROM Accounts WHERE account_id = ? LIMIT 1
        raise NotImplementedError

    def account_data_freshness(self, account_id: str) -> tuple[bool, str]:
        # Real impl: max(updated_at) across the per-account joined tables.
        # Brain-ready view extractor uses this to set view_metadata.is_stale.
        raise NotImplementedError

    def iterate_account_ids(self) -> Iterator[str]:
        # Real impl: SELECT account_id FROM Accounts WHERE active = TRUE.
        # Filter by segment / status / cohort definition the cohort brain
        # is operating on.
        raise NotImplementedError

    def metadata(self) -> dict:
        # Real impl: warehouse identification + Tier 1 table freshness summary.
        raise NotImplementedError


# ─────────────────────────────────────────────────────────────────────
# Factory — what the brain runtime / CLI calls to get a default source
# ─────────────────────────────────────────────────────────────────────

def default_source() -> BrainViewSource:
    """Return the default source for the prototype: SynthCorpusSource pointed
    at the synth corpus directory.

    Override via env var GTM_OS_VIEW_SOURCE — currently only "synth" is
    supported, but the env knob is the place to wire in a warehouse source
    once one is built.
    """
    source_type = os.environ.get("GTM_OS_VIEW_SOURCE", "synth")
    if source_type == "synth":
        corpus_dir = os.environ.get(
            "GTM_OS_CORPUS_DIR",
            str(Path(__file__).parent.parent / "synth" / "corpus"),
        )
        return SynthCorpusSource(corpus_dir)
    # Future:
    # if source_type == "warehouse":
    #     return WarehouseViewSource(connection_config=load_warehouse_config())
    raise ValueError(
        f"unknown GTM_OS_VIEW_SOURCE: {source_type!r} "
        f"(known: 'synth')"
    )
