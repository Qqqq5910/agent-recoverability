"""Tests for the UNKNOWN-step audit and the offline position description.

The audit exists to separate three things that all surface as an UNKNOWN
observation: a format property (no return code was ever produced), a detector
abstention (a return code existed and the precision-first policy declined to
rule on it), and a parser defect (a return code existed in the raw record and
the adapter failed to extract it). Only the third is a bug.
"""

from __future__ import annotations

import dataclasses
import inspect

import pytest

from recoverability.audit import (
    OFFLINE_ONLY_FIELDS,
    AuditReason,
    audit_unknown_steps,
    offline_first_error_position,
)
from recoverability.schema import (
    ActionKind,
    ObservationStatus,
    RunRecord,
    StepRecord,
    TerminationReason,
    VerdictSource,
)


def make_step(
    *,
    step_index: int = 0,
    action: str = "ls",
    action_kind: ActionKind = ActionKind.COMMAND,
    observation_status: ObservationStatus = ObservationStatus.UNKNOWN,
    returncode: int | None = None,
    error_signature: str | None = None,
) -> StepRecord:
    return StepRecord(
        task_id="astropy__astropy-12907",
        run_id="run-1",
        agent_name="mini-SWE-agent",
        model_name="claude-4-sonnet-20250514",
        step_index=step_index,
        trajectory_length_so_far=step_index + 1,
        action=action,
        action_kind=action_kind,
        observation="",
        observation_status=observation_status,
        error_signature=error_signature,
        returncode=returncode,
    )


def make_run(steps: list[StepRecord], *, final_success: bool | None = True) -> RunRecord:
    return RunRecord(
        task_id="astropy__astropy-12907",
        run_id="run-1",
        agent_name="mini-SWE-agent",
        model_name="claude-4-sonnet-20250514",
        steps=steps,
        final_success=final_success,
        termination_reason=(
            TerminationReason.SUCCESS if final_success else TerminationReason.BENCHMARK_FAILURE
        ),
        verdict_source=VerdictSource.SWE_BENCH_REPORT,
    )


# --- Reason assignment -----------------------------------------------------


def test_no_following_observation_is_not_a_defect():
    run = make_run([make_step()])
    (record,) = audit_unknown_steps(run, raw_observations={0: None})
    assert record.audit_reason is AuditReason.NO_FOLLOWING_OBSERVATION
    assert record.parser_issue is False
    assert record.has_observation_text is False


def test_empty_observation_is_not_a_defect():
    run = make_run([make_step()])
    (record,) = audit_unknown_steps(run, raw_observations={0: "   \n "})
    assert record.audit_reason is AuditReason.EMPTY_OBSERVATION
    assert record.parser_issue is False


def test_terminal_submit_without_a_returncode_is_a_format_property():
    """The expected shape of the final step, not something to call OK."""
    step = make_step(action="echo DONE", action_kind=ActionKind.SUBMIT)
    run = make_run([step])
    (record,) = audit_unknown_steps(run, raw_observations={0: "diff --git a/f b/f"})
    assert record.audit_reason is AuditReason.MISSING_RETURNCODE_WITH_TEXT
    assert record.parser_issue is False
    assert record.is_final_step is True


def test_non_execution_message_is_not_a_defect():
    run = make_run([make_step(action="  ")])
    (record,) = audit_unknown_steps(run, raw_observations={0: "some prose"})
    assert record.audit_reason is AuditReason.NON_EXECUTION_MESSAGE
    assert record.parser_issue is False


def test_returncode_that_never_reached_the_step_is_a_parser_bug():
    """The signal was in the raw record and the adapter missed it."""
    run = make_run([make_step(returncode=None)])
    (record,) = audit_unknown_steps(run, raw_observations={0: "<returncode>1</returncode>\nboom"})
    assert record.audit_reason is AuditReason.UNPARSED_FORMAT_VARIANT
    assert record.parser_issue is True
    assert record.has_returncode_tag is True


def test_parsed_returncode_left_unknown_is_an_abstention_not_a_bug():
    """The distinction the audit turns on.

    The adapter did extract the return code; the detector declined to attribute
    a non-zero exit in a pipeline to a single command. Counting this as a parser
    defect would have manufactured 22 phantom bugs in the real population.
    """
    run = make_run([make_step(action="cat f | grep x", returncode=1)])
    (record,) = audit_unknown_steps(run, raw_observations={0: "<returncode>1</returncode>\n"})
    assert record.audit_reason is AuditReason.DETECTOR_ABSTAINED
    assert record.parser_issue is False
    assert record.has_returncode_tag is True


def test_only_unknown_steps_are_audited():
    run = make_run(
        [
            make_step(step_index=0, observation_status=ObservationStatus.OK),
            make_step(step_index=1, observation_status=ObservationStatus.UNKNOWN),
            make_step(
                step_index=2,
                observation_status=ObservationStatus.ERROR,
                error_signature="returncode_1",
            ),
        ]
    )
    records = audit_unknown_steps(run, raw_observations={0: "ok", 1: None, 2: "boom"})
    assert [r.step_index for r in records] == [1]


def test_audited_records_carry_no_observation_text():
    """The per-step audit file is gitignored, but it still must not hold text."""
    run = make_run([make_step()])
    (record,) = audit_unknown_steps(run, raw_observations={0: "secret path /home/x/y"})
    assert "secret" not in repr(record)
    assert "secret" not in str(record.to_dict())


# --- Blind to the verdict --------------------------------------------------


def test_audit_signature_takes_no_verdict():
    params = set(inspect.signature(audit_unknown_steps).parameters)
    assert params == {"run", "raw_observations"}


def test_reason_does_not_depend_on_the_run_outcome():
    """Same step structure under three outcomes must give one answer."""
    reasons = {
        audit_unknown_steps(
            make_run([make_step(action="cat f | grep x", returncode=1)], final_success=outcome),
            raw_observations={0: "<returncode>1</returncode>"},
        )[0].audit_reason
        for outcome in (True, False, None)
    }
    assert reasons == {AuditReason.DETECTOR_ABSTAINED}


# --- Offline position description -----------------------------------------


def test_offline_position_is_none_without_an_error():
    run = make_run([make_step(observation_status=ObservationStatus.OK)])
    assert offline_first_error_position(run) is None


def test_offline_position_reports_the_first_error_only():
    run = make_run(
        [
            make_step(step_index=0, observation_status=ObservationStatus.OK),
            make_step(
                step_index=1,
                observation_status=ObservationStatus.ERROR,
                error_signature="returncode_1",
            ),
            make_step(
                step_index=2,
                observation_status=ObservationStatus.ERROR,
                error_signature="returncode_2",
            ),
            make_step(step_index=3, observation_status=ObservationStatus.OK),
        ]
    )
    result = offline_first_error_position(run)
    assert result["first_error_step"] == 1
    assert result["total_steps"] == 4
    assert result["first_error_fraction"] == pytest.approx(0.25)


def test_offline_position_is_labelled_not_prefix_safe():
    """The label is load-bearing: it is what stops this reaching a predictor."""
    result = offline_first_error_position(
        make_run(
            [
                make_step(
                    observation_status=ObservationStatus.ERROR,
                    error_signature="returncode_1",
                )
            ]
        )
    )
    assert result is not None
    future_keys = set(result) - {"first_error_step"}
    assert future_keys <= OFFLINE_ONLY_FIELDS, (
        f"{future_keys - OFFLINE_ONLY_FIELDS} is derived from the total step count "
        "but is not declared offline-only"
    )
    assert "OFFLINE ANALYSIS ONLY" in (offline_first_error_position.__doc__ or "")


def test_no_step_field_carries_an_offline_only_name():
    """The prefix feature surface is StepRecord; no total-derived field may sit on it."""
    step_fields = {f.name for f in dataclasses.fields(StepRecord)}
    assert step_fields & OFFLINE_ONLY_FIELDS == set()
