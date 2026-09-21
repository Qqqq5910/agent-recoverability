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

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any

__all__ = [
    "SCHEMA_VERSION",
    "EventType",
    "InterventionAction",
    "RunRecord",
    "SchemaError",
    "StepRecord",
]

#: Bumped on any backwards-incompatible change to the record classes.
SCHEMA_VERSION = "0.1.0"


class SchemaError(ValueError):
    """Raised when a record violates a schema invariant."""


class EventType(StrEnum):
    """Classification of what happened at a single step.

    ``ERROR`` marks an *observable error event* as defined in
    ``docs/definitions.md``; it is a statement about one observation, not a
    judgement about the run. The taxonomy is deliberately coarse in v1 and is
    expected to gain members as Phase 1 adapters are written.
    """

    ACTION = "action"
    """A normal action with no error in its observation."""

    ERROR = "error"
    """An observable, machine-identifiable error event."""

    TEST_RUN = "test_run"
    """The agent ran tests. Orthogonal to whether they passed."""

    TERMINAL = "terminal"
    """The final step of the run (verdict, give-up, or budget exhaustion)."""

    OTHER = "other"
    """Recognised step that does not fit the categories above."""

    UNKNOWN = "unknown"
    """Source log did not permit classification. Not a silent default."""


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
    * ``event_type == EventType.ERROR`` requires an ``error_signature``, and a
      non-empty ``error_signature`` requires ``event_type == EventType.ERROR``.
    """

    task_id: str
    run_id: str
    agent_name: str
    model_name: str
    step_index: int
    trajectory_length_so_far: int
    action: str
    observation: str
    event_type: EventType = EventType.UNKNOWN
    tool_name: str | None = None
    error_signature: str | None = None

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
        is_error = self.event_type is EventType.ERROR
        if is_error and not has_signature:
            raise SchemaError("event_type=ERROR requires a non-empty error_signature")
        if has_signature and not is_error:
            raise SchemaError(
                "error_signature is only valid when event_type=ERROR, got "
                f"event_type={self.event_type}"
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
        return self.event_type is EventType.ERROR

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
      ``True``.
    """

    task_id: str
    run_id: str
    agent_name: str
    model_name: str
    steps: list[StepRecord] = field(default_factory=list)

    final_success: bool | None = None
    """Benchmark verdict for the run. ``None`` means not yet evaluated."""

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

    def prefix(self, t: int) -> list[StepRecord]:
        """Return ``τ_{1:t}`` as steps with ``step_index <= t``.

        ``t`` is a zero-based step index. Raises :class:`SchemaError` for a
        negative ``t``; an out-of-range ``t`` simply yields the whole trajectory,
        matching the "everything observed so far" semantics.
        """
        if t < 0:
            raise SchemaError(f"prefix index must be >= 0, got {t}")
        return [step for step in self.steps if step.step_index <= t]
