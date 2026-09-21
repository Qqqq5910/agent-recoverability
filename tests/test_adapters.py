"""Tests for the mini-SWE-agent adapter and the shared leakage guard."""

from __future__ import annotations

import dataclasses
import json
from pathlib import Path
from typing import Any

import pytest

from recoverability.adapters.base import (
    AdapterError,
    MalformedRecordError,
    assert_no_step_leakage,
)
from recoverability.adapters.mini_swe_agent import (
    MiniSweAgentAdapter,
    classify_action,
    classify_observation,
)
from recoverability.schema import (
    ActionKind,
    ObservationStatus,
    StepRecord,
    TerminationReason,
    VerdictSource,
)

FIXTURE = Path(__file__).parent / "fixtures" / "mini_swe_agent_synthetic.json"


@pytest.fixture
def raw() -> dict[str, Any]:
    return json.loads(FIXTURE.read_text(encoding="utf-8"))


@pytest.fixture
def adapter() -> MiniSweAgentAdapter:
    return MiniSweAgentAdapter(model_name="claude-4-sonnet-20250514")


# --- Parsing ---------------------------------------------------------------


def test_parses_one_step_per_assistant_action(adapter, raw):
    run = adapter.parse_run(raw, verdict=True)
    assert run.n_steps == 5
    assert [s.step_index for s in run.steps] == [0, 1, 2, 3, 4]
    assert [s.trajectory_length_so_far for s in run.steps] == [1, 2, 3, 4, 5]


def test_action_kinds_are_classified(adapter, raw):
    run = adapter.parse_run(raw, verdict=True)
    assert [s.action_kind for s in run.steps] == [
        ActionKind.COMMAND,
        ActionKind.TEST_RUN,
        ActionKind.FILE_EDIT,
        ActionKind.TEST_RUN,
        ActionKind.SUBMIT,
    ]


def test_returncode_drives_observation_status(adapter, raw):
    run = adapter.parse_run(raw, verdict=True)
    assert [s.observation_status for s in run.steps] == [
        ObservationStatus.OK,
        ObservationStatus.ERROR,
        ObservationStatus.OK,
        ObservationStatus.OK,
        ObservationStatus.OK,
    ]
    assert run.steps[1].error_signature == "returncode_1"


def test_observation_strips_harness_tags(adapter, raw):
    run = adapter.parse_run(raw, verdict=True)
    assert run.steps[0].observation == "pkg\nsetup.py"
    assert "<returncode>" not in run.steps[0].observation


def test_unavailable_fields_stay_none(adapter, raw):
    """Fields the format does not carry are None, never imputed."""
    run = adapter.parse_run(raw, verdict=True)
    for step in run.steps:
        assert step.token_cost is None
        assert step.wall_time is None
        assert step.tool_name is None


# --- The central schema-0.2 claim -----------------------------------------


def test_failed_test_run_is_representable(adapter, raw):
    """A TEST_RUN that fails, in a run the benchmark resolved.

    This is the case schema 0.1 could not express, and the whole point of
    splitting ActionKind from ObservationStatus.
    """
    run = adapter.parse_run(raw, verdict=True)
    failing = run.steps[1]
    assert failing.action_kind is ActionKind.TEST_RUN
    assert failing.observation_status is ObservationStatus.ERROR
    assert run.final_success is True


def test_passing_and_failing_test_runs_coexist(adapter, raw):
    run = adapter.parse_run(raw, verdict=True)
    tests = [s for s in run.steps if s.action_kind is ActionKind.TEST_RUN]
    assert {s.observation_status for s in tests} == {
        ObservationStatus.OK,
        ObservationStatus.ERROR,
    }


# --- Termination / verdict separation -------------------------------------


def test_submitted_and_resolved_is_success(adapter, raw):
    run = adapter.parse_run(raw, verdict=True)
    assert run.termination_reason is TerminationReason.SUCCESS
    assert run.verdict_source is VerdictSource.SWE_BENCH_REPORT


def test_submitted_but_unresolved_is_benchmark_failure(adapter, raw):
    """The agent said done; the benchmark disagreed. The benchmark wins."""
    run = adapter.parse_run(raw, verdict=False)
    assert run.termination_reason is TerminationReason.BENCHMARK_FAILURE
    assert run.final_success is False


def test_agent_submitted_is_not_promoted_without_a_verdict(adapter, raw):
    run = adapter.parse_run(raw, verdict=None)
    assert run.termination_reason is TerminationReason.AGENT_SUBMITTED
    assert run.final_success is None
    assert run.verdict_source is VerdictSource.UNKNOWN


def test_budget_exhaustion_survives_a_failed_verdict(adapter, raw):
    raw["info"]["exit_status"] = "exit_cost"
    run = adapter.parse_run(raw, verdict=False)
    assert run.termination_reason is TerminationReason.BUDGET_EXHAUSTED


@pytest.mark.parametrize(
    ("exit_status", "expected"),
    [
        ("exit_timeout", TerminationReason.TIMEOUT),
        ("exit_format", TerminationReason.CRASH),
        ("exit_api", TerminationReason.CRASH),
        ("exit_interrupt", TerminationReason.EXTERNAL_INTERRUPTION),
        ("something_new", TerminationReason.UNKNOWN),
    ],
)
def test_exit_status_mapping(adapter, raw, exit_status, expected):
    raw["info"]["exit_status"] = exit_status
    assert adapter.parse_run(raw, verdict=None).termination_reason is expected


# --- Recovery labels stay unset in Phase 1A -------------------------------


def test_recovery_labels_are_not_computed(adapter, raw):
    run = adapter.parse_run(raw, verdict=True)
    assert run.self_recovered_eventually is None
    assert run.steps_to_recovery is None


# --- Malformed input ------------------------------------------------------


@pytest.mark.parametrize(
    "mutate",
    [
        pytest.param(lambda r: r.pop("instance_id"), id="no_instance_id"),
        pytest.param(lambda r: r.update(instance_id=""), id="empty_instance_id"),
        pytest.param(lambda r: r.update(instance_id=123), id="non_string_instance_id"),
        pytest.param(lambda r: r.pop("messages"), id="no_messages"),
        pytest.param(lambda r: r.update(messages="not a list"), id="messages_not_list"),
        pytest.param(lambda r: r.update(messages=[{"no_role": 1}]), id="message_without_role"),
        pytest.param(lambda r: r.update(info=[]), id="info_not_mapping"),
        pytest.param(
            lambda r: r.update(messages=[{"role": "system", "content": "x"}]),
            id="no_assistant_actions",
        ),
    ],
)
def test_malformed_raw_records_raise(adapter, raw, mutate):
    mutate(raw)
    with pytest.raises(MalformedRecordError):
        adapter.parse_run(raw)


def test_non_mapping_raw_raises(adapter):
    with pytest.raises(MalformedRecordError):
        adapter.parse_run(["not", "a", "mapping"])  # type: ignore[arg-type]


def test_missing_info_is_tolerated(adapter, raw):
    """A trajectory with no info block still parses; the reason is UNKNOWN."""
    raw.pop("info")
    run = adapter.parse_run(raw, verdict=None)
    assert run.termination_reason is TerminationReason.UNKNOWN
    assert run.n_steps == 5


# --- Classifier unit tests ------------------------------------------------


@pytest.mark.parametrize(
    ("command", "expected"),
    [
        ("ls -la", ActionKind.COMMAND),
        ("grep -rn 'foo' src/", ActionKind.COMMAND),
        ("python -m pytest tests/ -q", ActionKind.TEST_RUN),
        ("tox -e py311", ActionKind.TEST_RUN),
        ("python manage.py test app", ActionKind.TEST_RUN),
        ("python test_bug.py", ActionKind.TEST_RUN),
        ("python reproduce_issue.py", ActionKind.TEST_RUN),
        ("cat > f.py <<'EOF'\nx=1\nEOF", ActionKind.FILE_EDIT),
        ("sed -i 's/a/b/' f.py", ActionKind.FILE_EDIT),
        ("git apply /tmp/fix.patch", ActionKind.PATCH),
        ("echo MICRO_SWE_AGENT_FINAL_OUTPUT", ActionKind.SUBMIT),
        ("", ActionKind.UNKNOWN),
    ],
)
def test_classify_action(command, expected):
    assert classify_action(command) is expected


def test_redirect_is_not_mistaken_for_comparison():
    """`>=`, `->` and `2>&1` must not be read as a file write."""
    assert classify_action("python -c 'assert a >= b'") is ActionKind.COMMAND
    assert classify_action("make build 2>&1 | tail") is ActionKind.COMMAND


def test_writing_a_test_file_is_an_edit_not_a_test_run():
    command = "cat > test_thing.py <<'EOF'\nimport pytest\nEOF"
    assert classify_action(command) is ActionKind.FILE_EDIT


@pytest.mark.parametrize(
    ("observation", "returncode", "status"),
    [
        ("all good", 0, ObservationStatus.OK),
        ("1 failed", 1, ObservationStatus.ERROR),
        ("", None, ObservationStatus.UNKNOWN),
        ("some text", None, ObservationStatus.UNKNOWN),
    ],
)
def test_classify_observation(observation, returncode, status):
    assert classify_observation(observation, returncode)[0] is status


def test_the_word_error_alone_is_not_an_error():
    """Conservative by design: a passing run that prints 'error' stays OK."""
    status, signature = classify_observation("test_error_handling PASSED\n3 passed, 0 errors", 0)
    assert status is ObservationStatus.OK
    assert signature is None


def test_structured_markers_are_errors_even_at_returncode_zero():
    status, signature = classify_observation("error: patch failed: core.py:1", 0)
    assert status is ObservationStatus.ERROR
    assert signature == "patch_apply_failed"


def test_error_status_always_carries_a_signature():
    status, signature = classify_observation("boom", 7)
    assert status is ObservationStatus.ERROR
    assert signature


# --- Leakage guard --------------------------------------------------------


def _step(**extra: Any) -> StepRecord:
    return StepRecord.at(
        0,
        task_id="t",
        run_id="r",
        agent_name="a",
        model_name="m",
        action="ls",
        observation="ok",
        extra=extra,
    )


@pytest.mark.parametrize(
    "key",
    [
        "final_success",
        "resolved",
        "verdict",
        "verdict_source",
        "termination_reason",
        "exit_status",
        "total_steps",
        "n_steps",
        "trajectory_length",
        "self_recovered_eventually",
        "steps_to_recovery",
        "FINAL_SUCCESS",
        "  resolved  ",
        "is_resolved",
        "final_patch",
        "step_total",
    ],
)
def test_forbidden_step_extra_keys_are_rejected(key):
    with pytest.raises(AdapterError):
        assert_no_step_leakage(_step(**{key: "anything"}))


def test_nested_leakage_is_caught():
    with pytest.raises(AdapterError):
        assert_no_step_leakage(_step(source={"meta": {"resolved": True}}))


def test_benign_step_extra_is_allowed():
    assert_no_step_leakage(_step(source_id="x", raw_message_index=4, cwd="/repo"))


def test_adapter_never_leaks_run_outcome_into_steps(adapter, raw):
    """The fixture's info carries `resolved` and `total_steps` on purpose."""
    run = adapter.parse_run(raw, verdict=True)
    for step in run.steps:
        assert_no_step_leakage(step)
        flat = json.dumps(step.extra).lower()
        assert "resolved" not in flat
        assert "total_steps" not in flat


def test_run_extra_may_carry_source_metadata(adapter, raw):
    """What is banned on a step is legal on the run."""
    run = adapter.parse_run(raw, verdict=True)
    assert run.extra["raw_exit_status"] == "Submitted"
    assert run.extra["api_calls"] == 5
    assert run.extra["has_submission"] is True


def test_adapter_validate_rejects_a_tampered_step(adapter, raw):
    run = adapter.parse_run(raw, verdict=True)
    run.steps[2].extra["final_success"] = True
    with pytest.raises(AdapterError):
        adapter.validate(run)


# --- Prefix safety --------------------------------------------------------


def test_prefix_carries_no_future_information(adapter, raw):
    """Every prefix of the parsed run is indistinguishable from a live run.

    ``prefix(t)`` is inclusive of the zero-based index ``t``, so it holds
    ``t + 1`` steps.
    """
    run = adapter.parse_run(raw, verdict=True)
    for t in range(run.n_steps):
        prefix = run.prefix(t)
        assert len(prefix) == t + 1
        assert prefix[-1].trajectory_length_so_far == t + 1
        for step in prefix:
            assert step.step_index <= t
            assert not hasattr(step, "final_success")
            assert_no_step_leakage(step)


def test_no_step_field_reveals_total_length(adapter, raw):
    """A step knows how far it has come, never how far the run will go.

    ``StepRecord`` is slotted, so field values come from ``dataclasses.fields``.
    ``returncode`` is excluded: it is an observed process exit code that may
    equal the run length by coincidence, not a length signal.
    """
    run = adapter.parse_run(raw, verdict=True)
    total = run.n_steps
    assert total > 1, "fixture must be long enough for this test to mean anything"
    ignored = {"returncode"}
    for step in run.steps[:-1]:
        for field in dataclasses.fields(step):
            if field.name in ignored:
                continue
            value = getattr(step, field.name)
            if isinstance(value, bool) or not isinstance(value, int):
                continue
            assert value != total, f"{field.name} on step {step.step_index} equals n_steps"
