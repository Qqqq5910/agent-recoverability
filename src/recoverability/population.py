"""Population accounting for a full-submission ingestion.

The point of this module is that no run disappears quietly. Every trajectory the
source offers ends up in exactly one bucket, and the buckets reconcile against
the starting counts. A percentage computed over a population that was silently
filtered is worse than no percentage, because it looks like evidence.

Selection is deterministic and verdict-blind: the analysis set is the natural
intersection of available trajectories and available verdicts, ordered by
``task_id``. Nothing in this module reads an outcome to decide whether a run is
included, and ``tests/test_population.py`` asserts that over the signatures.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

__all__ = ["ExclusionReason", "PopulationAccounting", "deterministic_subset"]


class ExclusionReason:
    """Why a task_id is not in the analysis set. A closed set, by design."""

    MISSING_TRAJECTORY = "missing_trajectory"
    """The benchmark lists the instance; the submission has no trajectory."""

    MISSING_VERDICT = "missing_verdict"
    """A trajectory exists but no per-instance benchmark verdict does."""

    MALFORMED = "malformed"
    """The trajectory exists and could not be parsed. Never silently skipped."""

    EXTERNAL_INTERRUPTION = "external_interruption"
    """Terminated by something outside the agent, so the outcome is not
    attributable to the agent's behaviour."""

    NOT_IN_SUBSET = "not_in_subset"
    """Excluded by a deterministic, verdict-blind subset rule."""


@dataclass(slots=True)
class PopulationAccounting:
    """A reconciled census of a submission's runs.

    Attributes mirror the accounting required before any proportion is computed.
    ``excluded`` maps a reason to the sorted task_ids it removed, so every
    exclusion is inspectable rather than a number.
    """

    n_benchmark_instances: int = 0
    n_available_verdicts: int = 0
    n_available_trajectories: int = 0
    n_joined_runs: int = 0
    n_analyzed_runs: int = 0
    excluded: dict[str, list[str]] = field(default_factory=dict)
    notes: list[str] = field(default_factory=list)

    def exclude(self, task_id: str, reason: str) -> None:
        self.excluded.setdefault(reason, []).append(task_id)

    def n_excluded(self, reason: str) -> int:
        return len(self.excluded.get(reason, []))

    @property
    def n_excluded_total(self) -> int:
        return sum(len(ids) for ids in self.excluded.values())

    def reconciles(self) -> bool:
        """Whether analysed + excluded-after-join accounts for every join.

        ``missing_trajectory`` and ``missing_verdict`` are excluded *before* the
        join, so they are not part of this identity.
        """
        post_join = (
            self.n_excluded(ExclusionReason.MALFORMED)
            + self.n_excluded(ExclusionReason.EXTERNAL_INTERRUPTION)
            + self.n_excluded(ExclusionReason.NOT_IN_SUBSET)
        )
        return self.n_analyzed_runs + post_join == self.n_joined_runs

    def to_dict(self) -> dict[str, Any]:
        return {
            "n_benchmark_instances": self.n_benchmark_instances,
            "n_available_verdicts": self.n_available_verdicts,
            "n_available_trajectories": self.n_available_trajectories,
            "n_joined_runs": self.n_joined_runs,
            "n_missing_trajectory": self.n_excluded(ExclusionReason.MISSING_TRAJECTORY),
            "n_missing_verdict": self.n_excluded(ExclusionReason.MISSING_VERDICT),
            "n_malformed": self.n_excluded(ExclusionReason.MALFORMED),
            "n_excluded_external_intervention": self.n_excluded(
                ExclusionReason.EXTERNAL_INTERRUPTION
            ),
            "n_excluded_not_in_subset": self.n_excluded(ExclusionReason.NOT_IN_SUBSET),
            "n_analyzed_runs": self.n_analyzed_runs,
            "reconciles": self.reconciles(),
            "excluded_task_ids": {
                reason: sorted(ids) for reason, ids in sorted(self.excluded.items())
            },
            "notes": list(self.notes),
        }


def deterministic_subset(task_ids: list[str], limit: int | None) -> list[str]:
    """The first ``limit`` task_ids in sort order, or all of them.

    Sorted rather than hashed so the subset is reproducible without a seed, and
    ordered by ``task_id`` alone so it cannot correlate with an outcome. Takes
    ids, never runs, so a verdict is not in scope to be consulted.
    """
    ordered = sorted(task_ids)
    if limit is None or limit >= len(ordered):
        return ordered
    return ordered[:limit]
