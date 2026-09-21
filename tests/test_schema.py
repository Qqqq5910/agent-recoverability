"""Tests for the Phase 0 data schema.

Standard library + pytest only. No data files, no network, no API keys.
"""

from __future__ import annotations

import dataclasses

import pytest

from recoverability import __version__
from recoverability.schema import (
    SCHEMA_VERSION,
    EventType,
    InterventionAction,
    RunRecord,
    SchemaError,
    StepRecord,
)


def make_step(step_index: int = 0, **overrides: object) -> StepRecord:
    """Build a valid step, overridable per test."""
    kwargs: dict[str, object] = {
        "task_id": "task-1",
        "run_id": "run-1",
        "agent_name": "demo-agent",
        "model_name": "demo-model",
        "action": "run pytest",
        "observation": "ok",
        "event_type": EventType.ACTION,
    }
    kwargs.update(overrides)
    return StepRecord.at(step_index, **kwargs)  # type: ignore[arg-type]


def make_error_step(step_index: int, signature: str = "AssertionError|test_x") -> StepRecord:
    return make_step(step_index, event_type=EventType.ERROR, error_signature=signature)


def make_run(steps: list[StepRecord] | None = None, **overrides: object) -> RunRecord:
    kwargs: dict[str, object] = {
        "task_id": "task-1",
        "run_id": "run-1",
        "agent_name": "demo-agent",
        "model_name": "demo-model",
        "steps": steps if steps is not None else [make_step(0)],
    }
    kwargs.update(overrides)
    return RunRecord(**kwargs)  # type: ignore[arg-type]


# --- StepRecord ------------------------------------------------------------


def test_step_record_minimal_fields() -> None:
    step = make_step(0)
    assert step.task_id == "task-1"
    assert step.step_index == 0
    assert step.trajectory_length_so_far == 1
    assert step.tool_name is None
    assert step.error_signature is None
    assert step.is_error_event is False


def test_step_at_derives_prefix_length() -> None:
    assert make_step(7).trajectory_length_so_far == 8


def test_step_rejects_negative_index() -> None:
    with pytest.raises(SchemaError, match="step_index must be >= 0"):
        make_step(-1)


def test_step_rejects_inconsistent_prefix_length() -> None:
    with pytest.raises(SchemaError, match="trajectory_length_so_far"):
        StepRecord(
            task_id="task-1",
            run_id="run-1",
            agent_name="demo-agent",
            model_name="demo-model",
            step_index=3,
            trajectory_length_so_far=10,
            action="a",
            observation="o",
        )


def test_step_has_no_total_trajectory_length_field() -> None:
    """Total length is future information and must not exist on a step."""
    names = {f.name for f in dataclasses.fields(StepRecord)}
    assert "trajectory_length" not in names
    assert "total_steps" not in names
    assert "final_success" not in names
    assert "self_recovered_eventually" not in names


def test_error_event_requires_signature() -> None:
    with pytest.raises(SchemaError, match="requires a non-empty error_signature"):
        make_step(0, event_type=EventType.ERROR)


def test_signature_requires_error_event() -> None:
    with pytest.raises(SchemaError, match="only valid when event_type=ERROR"):
        make_step(0, event_type=EventType.ACTION, error_signature="Boom")


def test_error_event_roundtrip() -> None:
    step = make_error_step(2, "ImportError|no module named x")
    assert step.is_error_event is True
    assert step.error_signature == "ImportError|no module named x"


def test_default_event_type_is_unknown_not_action() -> None:
    step = StepRecord.at(
        0,
        task_id="t",
        run_id="r",
        agent_name="a",
        model_name="m",
        action="a",
        observation="o",
    )
    assert step.event_type is EventType.UNKNOWN


# --- RunRecord -------------------------------------------------------------


def test_run_record_defaults() -> None:
    run = make_run()
    assert run.final_success is None
    assert run.self_recovered_eventually is None
    assert run.steps_to_recovery is None
    assert run.had_external_intervention is None
    assert run.schema_version == SCHEMA_VERSION
    assert run.n_steps == 1
    assert run.has_error_event is False
    assert run.error_step_indices == []


def test_run_rejects_step_from_other_run() -> None:
    foreign = make_step(0, run_id="run-2")
    with pytest.raises(SchemaError, match="expected 'run-1'"):
        make_run([foreign])


def test_run_rejects_step_from_other_task() -> None:
    foreign = make_step(0, task_id="task-9")
    with pytest.raises(SchemaError, match="task_id"):
        make_run([foreign])


def test_run_rejects_non_contiguous_steps() -> None:
    with pytest.raises(SchemaError, match="contiguous and ordered"):
        make_run([make_step(0), make_step(2)])


def test_run_rejects_unordered_steps() -> None:
    with pytest.raises(SchemaError, match="contiguous and ordered"):
        make_run([make_step(1), make_step(0)])


def test_error_step_indices_reported_in_order() -> None:
    run = make_run([make_step(0), make_error_step(1), make_step(2), make_error_step(3)])
    assert run.has_error_event is True
    assert run.error_step_indices == [1, 3]


def test_recovery_label_is_none_when_no_error_event() -> None:
    """Not applicable is not False: a clean run has no recovery label."""
    with pytest.raises(SchemaError, match="must be None for runs without an error event"):
        make_run([make_step(0)], final_success=True, self_recovered_eventually=True)


def test_recovery_requires_final_success() -> None:
    with pytest.raises(SchemaError, match="requires final_success=True"):
        make_run([make_error_step(0)], final_success=False, self_recovered_eventually=True)


def test_recovered_run_is_valid() -> None:
    run = make_run(
        [make_error_step(0), make_step(1), make_step(2)],
        final_success=True,
        self_recovered_eventually=True,
        steps_to_recovery=2,
        had_external_intervention=False,
    )
    assert run.self_recovered_eventually is True
    assert run.steps_to_recovery == 2


def test_failed_run_after_error_is_valid() -> None:
    run = make_run(
        [make_error_step(0), make_error_step(1)],
        final_success=False,
        self_recovered_eventually=False,
    )
    assert run.final_success is False
    assert run.self_recovered_eventually is False
    assert run.steps_to_recovery is None


def test_steps_to_recovery_requires_recovery() -> None:
    with pytest.raises(SchemaError, match="only valid when self_recovered_eventually=True"):
        make_run(
            [make_error_step(0)],
            final_success=False,
            self_recovered_eventually=False,
            steps_to_recovery=3,
        )


def test_steps_to_recovery_must_be_non_negative() -> None:
    with pytest.raises(SchemaError, match="steps_to_recovery must be >= 0"):
        make_run(
            [make_error_step(0)],
            final_success=True,
            self_recovered_eventually=True,
            steps_to_recovery=-1,
        )


def test_test_failure_alone_does_not_imply_unrecoverable() -> None:
    """H2 in schema form: an error event coexists with eventual success."""
    run = make_run(
        [
            make_step(0, event_type=EventType.TEST_RUN),
            make_error_step(1, "AssertionError|test_alpha"),
            make_step(2),
            make_step(3, event_type=EventType.TERMINAL),
        ],
        final_success=True,
        self_recovered_eventually=True,
        steps_to_recovery=2,
    )
    assert run.has_error_event is True
    assert run.final_success is True


# --- prefix discipline ------------------------------------------------------


def test_prefix_returns_only_past_steps() -> None:
    run = make_run([make_step(0), make_error_step(1), make_step(2)])
    assert [s.step_index for s in run.prefix(1)] == [0, 1]


def test_prefix_at_zero_returns_first_step_only() -> None:
    run = make_run([make_step(0), make_step(1)])
    assert [s.step_index for s in run.prefix(0)] == [0]


def test_prefix_beyond_end_returns_whole_trajectory() -> None:
    run = make_run([make_step(0), make_step(1)])
    assert len(run.prefix(99)) == 2


def test_prefix_rejects_negative_index() -> None:
    with pytest.raises(SchemaError, match="prefix index must be >= 0"):
        make_run().prefix(-1)


def test_prefix_is_unchanged_when_future_steps_are_appended() -> None:
    """Leakage guard: a prefix must not depend on what happens later."""
    early = make_run([make_step(0), make_step(1)])
    late = make_run([make_step(0), make_step(1), make_error_step(2), make_step(3)])
    assert early.prefix(1) == late.prefix(1)


# --- enums and versioning ---------------------------------------------------


def test_event_type_values_are_stable_strings() -> None:
    assert EventType.ERROR == "error"
    assert EventType("unknown") is EventType.UNKNOWN


def test_intervention_includes_null_action() -> None:
    assert InterventionAction.CONTINUE == "continue"


def test_schema_version_is_declared() -> None:
    assert SCHEMA_VERSION
    assert isinstance(__version__, str)


@pytest.mark.parametrize(
    ("field_name", "bad_value", "message"),
    [
        ("token_cost", -1, "token_cost must be >= 0"),
        ("wall_time", -0.5, "wall_time must be >= 0"),
        ("counterfactual_success_probability", 1.5, r"must be in \[0, 1\]"),
        ("counterfactual_success_probability", -0.1, r"must be in \[0, 1\]"),
    ],
)
def test_step_numeric_bounds(field_name: str, bad_value: float, message: str) -> None:
    with pytest.raises(SchemaError, match=message):
        make_step(0, **{field_name: bad_value})


def test_reserved_fields_default_to_none() -> None:
    step = make_step(0)
    assert step.token_cost is None
    assert step.wall_time is None
    assert step.intervention_action is None
    assert step.counterfactual_success_probability is None
    assert step.extra == {}


def test_reserved_intervention_field_accepts_enum() -> None:
    step = make_step(0, intervention_action=InterventionAction.HINT)
    assert step.intervention_action is InterventionAction.HINT


def test_extra_dicts_are_not_shared_between_instances() -> None:
    first, second = make_step(0), make_step(1)
    first.extra["source"] = "adapter-a"
    assert second.extra == {}
