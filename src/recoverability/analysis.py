"""Descriptive statistics over a population of parsed runs.

Everything here is *descriptive*. No function in this module estimates a causal
effect, and none may be read as one: an association between an observable error
and a final failure is compatible with the error causing the failure, with a
hard task causing both, and with the agent recovering from the error and failing
for an unrelated reason. Phase 1B cannot distinguish these.

Two deliberate absences:

* No model of any kind. Phase 1B is measurement only.
* No recovery label. ``SUCCESS_AFTER_OBSERVED_ERROR`` is a *candidate* count,
  not evidence that a recovery happened; the recovery point is not defined until
  Phase 2 freezes it.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from math import sqrt
from typing import Any

from recoverability.errors import error_family
from recoverability.schema import RunRecord

__all__ = [
    "ContingencyTable",
    "Proportion",
    "contingency_table",
    "error_family_outcomes",
    "proportion",
    "wilson_interval",
]


def wilson_interval(
    successes: int, total: int, z: float = 1.959963984540054
) -> tuple[float, float]:
    """95% Wilson score interval for a binomial proportion.

    Wilson rather than the normal approximation because several cells here are
    small or near 0/1, where the normal interval leaves the unit interval and
    collapses to zero width at the boundary. Standard library only, by design:
    the whole computation is four arithmetic lines and does not justify scipy.

    ``z`` defaults to the two-sided 97.5th percentile of the standard normal.
    Returns ``(0.0, 1.0)`` for an empty denominator, the honest statement that
    no data constrains the proportion.
    """
    if total <= 0:
        return 0.0, 1.0
    p = successes / total
    z2 = z * z
    denominator = 1 + z2 / total
    center = (p + z2 / (2 * total)) / denominator
    half_width = (z * sqrt(p * (1 - p) / total + z2 / (4 * total * total))) / denominator
    return max(0.0, center - half_width), min(1.0, center + half_width)


@dataclass(frozen=True, slots=True)
class Proportion:
    """A proportion that always carries its numerator and denominator.

    Reporting ``30.7%`` without ``42 / 137`` hides the sample size, which is the
    thing a reader needs to judge it. Serialising both is not optional here.
    """

    numerator: int
    denominator: int

    @property
    def value(self) -> float | None:
        """The proportion, or ``None`` when nothing was observed."""
        if self.denominator == 0:
            return None
        return self.numerator / self.denominator

    @property
    def ci95(self) -> tuple[float, float] | None:
        if self.denominator == 0:
            return None
        return wilson_interval(self.numerator, self.denominator)

    def to_dict(self) -> dict[str, Any]:
        ci = self.ci95
        return {
            "numerator": self.numerator,
            "denominator": self.denominator,
            "value": self.value,
            "ci95_lower": None if ci is None else ci[0],
            "ci95_upper": None if ci is None else ci[1],
        }

    def __str__(self) -> str:
        if self.value is None:
            return "0 / 0 (undefined)"
        return f"{self.numerator} / {self.denominator} = {self.value:.1%}"


def proportion(numerator: int, denominator: int) -> Proportion:
    return Proportion(numerator=numerator, denominator=denominator)


@dataclass(frozen=True, slots=True)
class ContingencyTable:
    """Observable error presence against final benchmark outcome.

    Only runs with a benchmark verdict appear. A run whose verdict is unknown
    cannot be placed in either row, and is counted in the population accounting
    instead of being folded into one of these cells.
    """

    success_with_error: int
    success_without_error: int
    failure_with_error: int
    failure_without_error: int

    @property
    def n_success(self) -> int:
        return self.success_with_error + self.success_without_error

    @property
    def n_failure(self) -> int:
        return self.failure_with_error + self.failure_without_error

    @property
    def n_with_error(self) -> int:
        return self.success_with_error + self.failure_with_error

    @property
    def n_without_error(self) -> int:
        return self.success_without_error + self.failure_without_error

    @property
    def total(self) -> int:
        return self.n_success + self.n_failure

    def p_error_given_success(self) -> Proportion:
        return proportion(self.success_with_error, self.n_success)

    def p_error_given_failure(self) -> Proportion:
        return proportion(self.failure_with_error, self.n_failure)

    def p_success_given_error(self) -> Proportion:
        return proportion(self.success_with_error, self.n_with_error)

    def p_success_given_no_error(self) -> Proportion:
        return proportion(self.success_without_error, self.n_without_error)

    def risk_difference(self) -> float | None:
        """P(success | error) - P(success | no error).

        DESCRIPTIVE ASSOCIATION ONLY. This is not a treatment effect: nothing
        was randomised, and error occurrence is plausibly confounded by task
        difficulty. It says how the two conditional rates differ in this
        sample, and nothing about what would happen if an error were prevented.
        """
        with_error = self.p_success_given_error().value
        without_error = self.p_success_given_no_error().value
        if with_error is None or without_error is None:
            return None
        return with_error - without_error

    def to_dict(self) -> dict[str, Any]:
        return {
            "success_with_error": self.success_with_error,
            "success_without_error": self.success_without_error,
            "failure_with_error": self.failure_with_error,
            "failure_without_error": self.failure_without_error,
            "n_success": self.n_success,
            "n_failure": self.n_failure,
            "n_with_error": self.n_with_error,
            "n_without_error": self.n_without_error,
            "total": self.total,
        }


def contingency_table(runs: Iterable[RunRecord]) -> ContingencyTable:
    """Cross observable-error presence with the benchmark verdict.

    Runs without a verdict are skipped; the caller reports them separately.
    """
    cells = Counter[tuple[bool, bool]]()
    for run in runs:
        if run.final_success is None:
            continue
        cells[(run.final_success, run.has_error_event)] += 1
    return ContingencyTable(
        success_with_error=cells[(True, True)],
        success_without_error=cells[(True, False)],
        failure_with_error=cells[(False, True)],
        failure_without_error=cells[(False, False)],
    )


def error_family_outcomes(runs: Sequence[RunRecord]) -> dict[str, dict[str, int]]:
    """Per error family: how many runs contain it, and how they ended.

    A run is counted once per distinct family it contains, so the columns do not
    sum to the population: one run with a test failure and a patch failure
    appears under both. Descriptive only -- no significance test is applied, and
    with families this small none would be interpretable.
    """
    counts: dict[str, dict[str, int]] = {}
    for run in runs:
        families = {
            error_family(step.error_signature)
            for step in run.steps
            if step.error_signature is not None
        }
        for family in sorted(families):
            bucket = counts.setdefault(
                family,
                {"n_runs_with_error_type": 0, "n_success": 0, "n_failure": 0, "n_unknown": 0},
            )
            bucket["n_runs_with_error_type"] += 1
            if run.final_success is True:
                bucket["n_success"] += 1
            elif run.final_success is False:
                bucket["n_failure"] += 1
            else:
                bucket["n_unknown"] += 1
    return dict(sorted(counts.items()))
