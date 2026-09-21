"""Adapter protocol and the step-level leakage guard.

An adapter turns one harness's raw trajectory, plus an optional benchmark
verdict, into a :class:`~recoverability.schema.RunRecord`. Two rules bind every
adapter:

1. The benchmark verdict lives on the run, never on a step. A step is a prefix
   observation; if the outcome can be read off a step, every downstream
   predictor is trained on the answer.
2. ``extra`` is not an escape hatch. Source metadata that encodes the final
   outcome or the total trajectory length may land in ``RunRecord.extra`` and
   must never be copied into ``StepRecord.extra``.
"""

from __future__ import annotations

import re
from abc import ABC, abstractmethod
from collections.abc import Mapping
from typing import Any

from recoverability.schema import RunRecord, StepRecord

__all__ = [
    "FORBIDDEN_STEP_EXTRA_KEYS",
    "FORBIDDEN_STEP_EXTRA_PATTERNS",
    "AdapterError",
    "MalformedRecordError",
    "SourceAdapter",
    "assert_no_step_leakage",
]


class AdapterError(RuntimeError):
    """Base class for adapter failures."""


class MalformedRecordError(AdapterError):
    """Raised when a raw record cannot be parsed into a run.

    Malformed input is skipped and counted, never silently coerced into a
    partial run: a half-parsed trajectory is worse than a missing one.
    """


#: Keys that must never appear in ``StepRecord.extra``.
FORBIDDEN_STEP_EXTRA_KEYS: frozenset[str] = frozenset(
    {
        "final_success",
        "resolved",
        "success",
        "verdict",
        "verdict_source",
        "termination_reason",
        "exit_status",
        "report",
        "self_recovered_eventually",
        "steps_to_recovery",
        "n_steps",
        "num_steps",
        "total_steps",
        "trajectory_length",
        "total_trajectory_length",
        "submission",
        "model_stats",
    }
)

#: Substrings that flag a leaky ``StepRecord.extra`` key regardless of spelling.
FORBIDDEN_STEP_EXTRA_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"resolv"),
    re.compile(r"final"),
    re.compile(r"total.*step|step.*total"),
    re.compile(r"traj.*len|len.*traj"),
    re.compile(r"verdict"),
)


def assert_no_step_leakage(step: StepRecord) -> None:
    """Raise :class:`AdapterError` if ``step.extra`` leaks future information.

    Checks the flat key set and every nested mapping, since a nested source
    blob is the easiest way to smuggle an outcome past a shallow check.
    """

    def _walk(node: Any, path: str) -> None:
        if not isinstance(node, Mapping):
            return
        for raw_key, value in node.items():
            key = str(raw_key)
            where = f"{path}.{key}" if path else key
            normalized = key.strip().lower()
            if normalized in FORBIDDEN_STEP_EXTRA_KEYS:
                raise AdapterError(
                    f"StepRecord.extra[{where!r}] leaks run-level information; "
                    "put it on RunRecord.extra instead"
                )
            for pattern in FORBIDDEN_STEP_EXTRA_PATTERNS:
                if pattern.search(normalized):
                    raise AdapterError(
                        f"StepRecord.extra[{where!r}] matches leakage pattern "
                        f"{pattern.pattern!r}; put it on RunRecord.extra instead"
                    )
            _walk(value, where)

    _walk(step.extra, "")


class SourceAdapter(ABC):
    """Base class for one trajectory format."""

    #: Stable identifier recorded in the dataset manifest and the summary.
    source_id: str

    @abstractmethod
    def parse_run(
        self,
        raw: Mapping[str, Any],
        *,
        verdict: bool | None = None,
    ) -> RunRecord:
        """Parse one raw trajectory into a run.

        Args:
            raw: The harness artifact, already decoded from JSON.
            verdict: Benchmark outcome, when one is available from a source
                outside the trajectory. ``None`` means unknown, which is a
                first-class value here rather than a failure.

        Raises:
            MalformedRecordError: If ``raw`` cannot be parsed.
        """

    def validate(self, run: RunRecord) -> None:
        """Re-check the leakage guard on an already-constructed run.

        Schema invariants are enforced by ``RunRecord.__post_init__``, so a run
        that exists is already structurally valid; what remains is the
        ``extra`` leakage rule, which the schema cannot know about.
        """
        for step in run.steps:
            assert_no_step_leakage(step)
