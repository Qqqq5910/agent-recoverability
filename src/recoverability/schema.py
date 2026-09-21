"""Data schema for agent recoverability research.

Phase 0 scope: **schema only**. This module defines how trajectories, steps and
recoverability labels are represented. It contains no model, no predictor, no
feature extraction and no I/O.

Design rules:

* Standard library only. The core package must stay dependency-free.
* Prefix discipline. A :class:`StepRecord` may only carry information available at
  or before its own ``step_index``. Outcome labels live on :class:`RunRecord`, so
  that a step record can never leak the future by construction.
* Honest missingness. ``None`` means "unknown or not applicable" and is never
  silently coerced to a default. See ``docs/definitions.md``.
* Reserved fields are declared but default to ``None``. They are placeholders for
  later phases and must not be populated with estimated or invented values.

See ``docs/definitions.md`` for the normative meaning of every term used here.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from enum import StrEnum
from typing import Any

__all__ = [
    "SCHEMA_VERSION",
    "ActionKind",
    "InterventionAction",
    "ObservationStatus",
    "RunRecord",
    "SchemaError",
    "StepRecord",
    "TerminationReason",
    "VerdictSource",
]

#: Bumped on any backwards-incompatible change to the record classes.
#:
#: 0.2.0 split the single ``EventType`` axis into orthogonal :class:`ActionKind`
#: and :class:`ObservationStatus`, and separated agent-side termination from the
#: benchmark verdict. This is a breaking change: ``EventType`` is gone.
SCHEMA_VERSION = "0.2.0"


class SchemaError(ValueError):
    """Raised when a record violates a schema invariant."""


class ActionKind(StrEnum):
    """What the agent *did* at a step.

    This axis is orthogonal to :class:`ObservationStatus`: what the agent
    attempted is independent of how it turned out. A ``TEST_RUN`` may end ``OK``
    or ``ERROR``, and so may a ``FILE_EDIT``. Schema 0.1.0 conflated the two on a
    single ``EventType`` enum, which made "a test run that failed" inexpressible.
    """

    COMMAND = "command"
    """A shell command that is not recognisably a test invocation."""

    TEST_RUN = "test_run"
    """A test invocation (pytest, tox, unittest, ...)."""

    FILE_EDIT = "file_edit"
    """An in-place edit of a file (editor command, sed, heredoc write)."""

    PATCH = "patch"
    """Applying or generating a patch/diff (``git apply``, ``patch``)."""

    TOOL_CALL = "tool_call"
    """A structured non-shell tool call exposed by the harness."""

    SUBMIT = "submit"
    """The agent's submission / hand-in action. Not a verdict, see 2.3."""

    OTHER = "other"
    """Recognised action that does not fit the categories above."""

    UNKNOWN = "unknown"
    """Source log did not permit classification. Not a silent default."""


class ObservationStatus(StrEnum):
    """How the observation for a step turned out.

    ``ERROR`` marks an *observable error event* as defined in
    ``docs/definitions.md``. It is a statement about one observation, never a
    judgement about the run: an ``ERROR`` step is perfectly compatible with
    ``final_success=True``, which is exactly the phenomenon H2 is about.
    """

    OK = "ok"
    """The observation carries no machine-identifiable error signal."""

    ERROR = "error"
    """An observable, machine-identifiable error event."""

    UNKNOWN = "unknown"
    """Source log did not permit classification. Not a silent default."""


class TerminationReason(StrEnum):
    """Why the *run* stopped. Agent-side/harness-side, not a benchmark verdict.

    Deliberately distinct from ``RunRecord.final_success``: an agent can
    terminate with ``AGENT_SUBMITTED`` and still be scored as a failure by the
    benchmark. See ``docs/definitions.md``.
    """

    SUCCESS = "success"
    """Harness itself asserts the task was completed successfully."""

    BENCHMARK_FAILURE = "benchmark_failure"
    """Run ended and the benchmark scored it as a failure."""

    AGENT_SUBMITTED = "agent_submitted"
    """The agent chose to submit. Says nothing about correctness."""

    BUDGET_EXHAUSTED = "budget_exhausted"
    """Step / token / cost limit reached before submission."""

    TIMEOUT = "timeout"
    """Wall-clock limit reached."""

    CRASH = "crash"
    """Harness or agent crashed (unhandled exception, container died)."""

    EXTERNAL_INTERRUPTION = "external_interruption"
    """Stopped by something outside the agent-environment loop."""

    UNKNOWN = "unknown"
    """Source log did not permit classification. Not a silent default."""


class VerdictSource(StrEnum):
    """Provenance of ``RunRecord.final_success``.

    Recorded so that a verdict can always be traced to the artifact that
    produced it. An agent's own claim of "done" is never a verdict.
    """

    SWE_BENCH_REPORT = "swe_bench_report"
    """A SWE-bench evaluation report (``report.json`` or equivalent)."""

    SUBMISSION_RESULTS = "submission_results"
    """Aggregated per-instance results published alongside a submission."""

    HARNESS_ASSERTION = "harness_assertion"
    """The harness itself ran the check and recorded the outcome."""

    UNKNOWN = "unknown"
    """No trustworthy verdict artifact was available."""


class InterventionAction(StrEnum):
    """Reserved intervention vocabulary for Phase 5.

    Not used in Phases 0-4. The concrete action set ``A`` and its cost model are
    still open (see ``docs/research_spec.md`` 2.2).
    """

    CONTINUE = "continue"
    """The null action: let the agent proceed untouched."""

    HINT = "hint"
    ROLLBACK = "rollback"
    MODEL_SWAP = "model_swap"
    RESTART = "restart"
    HANDOFF_HUMAN = "handoff_human"
    ABORT = "abort"


@dataclass(slots=True)
class StepRecord:
    """One action-observation step of a trajectory.

    Invariants enforced in ``__post_init__``:

    * ``step_index`` is zero-based and non-negative.
    * ``trajectory_length_so_far`` equals ``step_index + 1``. It is stored
      explicitly because it is the prefix-safe notion of length; the *total*
      trajectory length is future information and is intentionally absent.
    * ``observation_status == ObservationStatus.ERROR`` requires an
      ``error_signature``, and a non-empty ``error_signature`` requires
      ``observation_status == ObservationStatus.ERROR``.
    * ``action_kind`` and ``observation_status`` are independent: every
      combination is legal, including ``TEST_RUN``/``ERROR`` (tests ran and
      failed) and ``TEST_RUN``/``OK`` (tests ran and passed).
    """

    task_id: str
    run_id: str
    agent_name: str
    model_name: str
    step_index: int
    trajectory_length_so_far: int
    action: str
    observation: str
    action_kind: ActionKind = ActionKind.UNKNOWN
    """What the agent attempted. Never encodes the outcome."""

    observation_status: ObservationStatus = ObservationStatus.UNKNOWN
    """How it turned out. Never encodes what was attempted."""

    tool_name: str | None = None
    error_signature: str | None = None
    returncode: int | None = None
    """Process exit code when the source reports one. ``None`` = not reported."""

    # --- Reserved for later phases. Leave as None; never estimate. -----------
    token_cost: int | None = None
    """Tokens attributable to this step, if the source log reports it."""

    wall_time: float | None = None
    """Seconds spent on this step, if the source log reports it."""

    intervention_action: InterventionAction | None = None
    """Phase 5: the intervention applied *at* this step, if any."""

    counterfactual_success_probability: float | None = None
    """Phase 5: estimated ``P(success | prefix, intervention)``. Never a guess."""

    extra: dict[str, Any] = field(default_factory=dict)
    """Source-specific passthrough fields, kept out of the typed surface."""

    def __post_init__(self) -> None:
        if self.step_index < 0:
            raise SchemaError(f"step_index must be >= 0, got {self.step_index}")
        expected = self.step_index + 1
        if self.trajectory_length_so_far != expected:
            raise SchemaError(
                "trajectory_length_so_far must equal step_index + 1 "
                f"({expected}), got {self.trajectory_length_so_far}"
            )
        has_signature = bool(self.error_signature)
        is_error = self.observation_status is ObservationStatus.ERROR
        if is_error and not has_signature:
            raise SchemaError("observation_status=ERROR requires a non-empty error_signature")
        if has_signature and not is_error:
            raise SchemaError(
                "error_signature is only valid when observation_status=ERROR, got "
                f"observation_status={self.observation_status}"
            )
        if self.token_cost is not None and self.token_cost < 0:
            raise SchemaError(f"token_cost must be >= 0, got {self.token_cost}")
        if self.wall_time is not None and self.wall_time < 0:
            raise SchemaError(f"wall_time must be >= 0, got {self.wall_time}")
        prob = self.counterfactual_success_probability
        if prob is not None and not 0.0 <= prob <= 1.0:
            raise SchemaError(f"counterfactual_success_probability must be in [0, 1], got {prob}")

    @property
    def is_error_event(self) -> bool:
        """Whether this step is an observable error event."""
        return self.observation_status is ObservationStatus.ERROR

    @property
    def is_test_run(self) -> bool:
        """Whether the agent ran tests. Says nothing about pass/fail."""
        return self.action_kind is ActionKind.TEST_RUN

    @classmethod
    def at(cls, step_index: int, **kwargs: Any) -> StepRecord:
        """Construct a step, deriving ``trajectory_length_so_far`` from the index."""
        return cls(step_index=step_index, trajectory_length_so_far=step_index + 1, **kwargs)


@dataclass(slots=True)
class RunRecord:
    """One complete run: a trajectory plus its outcome labels.

    Outcome labels are deliberately held here rather than on steps, so that any
    prefix-conditioned feature extractor can be handed :meth:`prefix` output
    without access to the future.

    Invariants enforced in ``__post_init__``:

    * all steps share this run's ``run_id`` and ``task_id``,
    * ``step_index`` values are ``0..n-1`` in order,
    * ``self_recovered_eventually`` is ``None`` when no error event occurred, and
      ``True`` requires ``final_success`` to be ``True``,
    * ``steps_to_recovery`` is only set when ``self_recovered_eventually`` is
      ``True``,
    * ``final_success`` is not ``None`` only if ``verdict_source`` is not
      ``UNKNOWN``: a verdict must always be attributable to an artifact.
    """

    task_id: str
    run_id: str
    agent_name: str
    model_name: str
    steps: list[StepRecord] = field(default_factory=list)

    final_success: bool | None = None
    """Benchmark verdict for the run. ``None`` means not yet evaluated.

    Intentionally a separate axis from :attr:`termination_reason`. A run can
    terminate with ``AGENT_SUBMITTED`` and still be scored ``False`` here. The
    agent's own claim that it is "done" must never set this field; only a
    programmatic benchmark artifact may, and :attr:`verdict_source` records which.
    """

    termination_reason: TerminationReason = TerminationReason.UNKNOWN
    """Why the run stopped, from the agent/harness point of view."""

    verdict_source: VerdictSource = VerdictSource.UNKNOWN
    """Where :attr:`final_success` came from. ``UNKNOWN`` requires it be ``None``."""

    self_recovered_eventually: bool | None = None
    """``None`` when no error event occurred: not applicable, not ``False``."""

    steps_to_recovery: int | None = None
    """Steps from the first error event to the recovery point, when recovered."""

    had_external_intervention: bool | None = None
    """Whether the run was externally interfered with. ``None`` = unknown."""

    schema_version: str = SCHEMA_VERSION
    extra: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        for position, step in enumerate(self.steps):
            if step.run_id != self.run_id:
                raise SchemaError(
                    f"step {position} has run_id={step.run_id!r}, expected {self.run_id!r}"
                )
            if step.task_id != self.task_id:
                raise SchemaError(
                    f"step {position} has task_id={step.task_id!r}, expected {self.task_id!r}"
                )
            if step.step_index != position:
                raise SchemaError(
                    f"steps must be contiguous and ordered from 0: position {position} "
                    f"has step_index={step.step_index}"
                )
        if self.final_success is not None and self.verdict_source is VerdictSource.UNKNOWN:
            raise SchemaError(
                "final_success requires a verdict_source other than UNKNOWN; an "
                "agent's own claim of completion is not a verdict"
            )
        if self.self_recovered_eventually is not None and not self.has_error_event:
            raise SchemaError(
                "self_recovered_eventually must be None for runs without an error event"
            )
        if self.self_recovered_eventually is True and self.final_success is not True:
            raise SchemaError("self_recovered_eventually=True requires final_success=True")
        if self.steps_to_recovery is not None:
            if self.self_recovered_eventually is not True:
                raise SchemaError(
                    "steps_to_recovery is only valid when self_recovered_eventually=True"
                )
            if self.steps_to_recovery < 0:
                raise SchemaError(f"steps_to_recovery must be >= 0, got {self.steps_to_recovery}")

    @property
    def n_steps(self) -> int:
        """Total number of steps. Future information; never use in features."""
        return len(self.steps)

    @property
    def has_error_event(self) -> bool:
        """Whether any step is an observable error event."""
        return any(step.is_error_event for step in self.steps)

    @property
    def error_step_indices(self) -> list[int]:
        """Indices of all error events, in order."""
        return [step.step_index for step in self.steps if step.is_error_event]

    @property
    def n_test_runs(self) -> int:
        """Number of steps where the agent ran tests, regardless of outcome."""
        return sum(1 for step in self.steps if step.is_test_run)

    @property
    def n_error_observations(self) -> int:
        """Number of error events in the run."""
        return sum(1 for step in self.steps if step.is_error_event)

    def prefix(self, t: int) -> list[StepRecord]:
        """Return ``τ_{1:t}`` as steps with ``step_index <= t``.

        ``t`` is a zero-based step index. Raises :class:`SchemaError` for a
        negative ``t``; an out-of-range ``t`` simply yields the whole trajectory,
        matching the "everything observed so far" semantics.
        """
        if t < 0:
            raise SchemaError(f"prefix index must be >= 0, got {t}")
        return [step for step in self.steps if step.step_index <= t]

    def to_json_dict(self) -> dict[str, Any]:
        """Return a JSON-serialisable dict for this run, including all steps."""
        return asdict(self)
