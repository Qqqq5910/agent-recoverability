"""Tests for ``error_event_v1``: the frozen Phase 1B error detector.

Every case in the informational-non-zero section is a command shape taken from
the real Phase 1B audit, not an invented example.
"""

from __future__ import annotations

import inspect

import pytest

from recoverability import errors as errors_module
from recoverability.errors import (
    ERROR_DETECTOR_VERSION,
    ErrorFamily,
    NonzeroVerdict,
    classify_error,
    error_family,
    is_informational_nonzero,
    split_shell_segments,
)
from recoverability.schema import ActionKind, ObservationStatus


def classify(command: str, returncode: int | None, *, observation: str = "", **kwargs):
    return classify_error(
        command=command,
        action_kind=kwargs.pop("action_kind", ActionKind.COMMAND),
        observation=observation,
        returncode=returncode,
        **kwargs,
    )


# --- Detector identity -----------------------------------------------------


def test_detector_version_is_frozen():
    assert ERROR_DETECTOR_VERSION == "error_event_v1"


# --- The blindness invariant (Part D) --------------------------------------


def test_classify_error_signature_takes_no_verdict():
    """The detector cannot consult the outcome, because it cannot receive it."""
    params = set(inspect.signature(classify_error).parameters)
    assert params == {
        "command",
        "action_kind",
        "observation",
        "returncode",
        "raw_observation",
    }


def test_detector_module_cannot_reach_run_level_outcome():
    """The detector imports no run-level type, so it has nothing to peek at.

    Checked structurally rather than by scanning for words: ``NonzeroVerdict``
    is a legitimate local name, so a substring search gives false alarms.
    """
    reachable = vars(errors_module)
    for name in ("RunRecord", "TerminationReason", "VerdictSource"):
        assert name not in reachable


@pytest.mark.parametrize(
    "forbidden", ["final_success", "resolved", "termination_reason", "n_steps"]
)
def test_no_detector_function_accepts_an_outcome_argument(forbidden):
    for _, func in inspect.getmembers(errors_module, inspect.isfunction):
        if func.__module__ != errors_module.__name__:
            continue
        assert forbidden not in inspect.signature(func).parameters


def test_verdict_bearing_call_is_rejected():
    """Passing the outcome in is a TypeError, not a silently ignored kwarg."""
    with pytest.raises(TypeError):
        classify_error(
            command="ls",
            action_kind=ActionKind.COMMAND,
            observation="",
            returncode=1,
            final_success=True,  # type: ignore[call-arg]
        )


# --- Quote-aware segmentation ---------------------------------------------


def test_quoted_pipe_is_not_a_pipeline():
    """``grep -n "a\\|b" f.py`` is one command; the ``|`` is inside the regex."""
    assert split_shell_segments(r'grep -n "a\|b" f.py') == [("", r'grep -n "a\|b" f.py')]


def test_single_quoted_operators_are_not_separators():
    assert split_shell_segments("echo 'a && b'") == [("", "echo 'a && b'")]


def test_pipeline_separators_are_recorded():
    assert split_shell_segments("cat f | grep x") == [("", "cat f"), ("|", "grep x")]


def test_chain_separators_are_distinguished_from_pipes():
    assert split_shell_segments("cd t && grep x") == [("", "cd t"), ("&&", "grep x")]


# --- Informational non-zero (Part E findings) ------------------------------


@pytest.mark.parametrize(
    "command",
    [
        "grep -rn 'missing' src/",
        r'grep -n -A 5 "test.*values\|multiple.*list" tests/test_qs.py',
        'grep -n "as_sql" ./x.py | grep -B 10 "ResolvedOuterRef"',
        "sed -n '/class X/,/def copy/p' f.py | grep -A 15 '__len__'",
        "git diff --quiet",
        "test -f missing.txt",
    ],
)
def test_predicate_nonzero_is_not_an_error(command):
    """Exit 1 that provably belongs to a predicate command is a negative result."""
    assert is_informational_nonzero(command, 1) is NonzeroVerdict.INFORMATIONAL
    status, signature = classify(command, 1)
    assert status is ObservationStatus.OK
    assert signature is None


@pytest.mark.parametrize(
    "command",
    [
        "cd tests && grep -n 'def test' migrations/test_operations.py",
        "pwd && grep -rn foo .",
        "cd lib; grep -n bar baz.py",
    ],
)
def test_unattributable_nonzero_is_unknown_not_error(command):
    """``cd x && grep y`` exits 1 for either reason, so neither is asserted."""
    assert is_informational_nonzero(command, 1) is NonzeroVerdict.UNATTRIBUTABLE
    status, signature = classify(command, 1)
    assert status is ObservationStatus.UNKNOWN
    assert signature is None


@pytest.mark.parametrize(
    "command",
    ["ls -la _build/", "cat ./django/db/router.py", "python debug_issue.py", "mkdir /x/y"],
)
def test_genuine_command_failure_stays_an_error(command):
    """A failing ``ls`` or ``cat`` means the path is wrong. That is observable."""
    assert is_informational_nonzero(command, 1) is NonzeroVerdict.FAILURE
    status, signature = classify(command, 1)
    assert status is ObservationStatus.ERROR
    assert signature is not None


def test_grep_exit_two_is_a_real_error():
    """``grep`` exits 2 on an unreadable file, which is not a negative result."""
    assert is_informational_nonzero("grep -rn foo /root", 2) is NonzeroVerdict.FAILURE
    status, _ = classify("grep -rn foo /root", 2)
    assert status is ObservationStatus.ERROR


def test_informational_rule_does_not_apply_to_zero_exit():
    assert is_informational_nonzero("grep -rn foo .", 0) is NonzeroVerdict.FAILURE


# --- Structured error precedence ------------------------------------------


def test_timeout_outranks_the_return_code():
    status, signature = classify(
        "python -m pytest tests/",
        124,
        observation="command timed out and has been killed",
        action_kind=ActionKind.TEST_RUN,
    )
    assert (status, signature) == (ObservationStatus.ERROR, "timeout")


def test_traceback_outranks_unattributable_attribution():
    """A traceback is a real failure whichever chain segment produced it."""
    status, signature = classify(
        "cd src && grep -n x f.py",
        1,
        observation="Traceback (most recent call last):\n  File ...\nValueError",
    )
    assert (status, signature) == (ObservationStatus.ERROR, "python_exception")


_TRACEBACK = "Traceback (most recent call last):\n  File ...\nValueError: boom"


def test_traceback_at_returncode_zero_is_not_an_error():
    """The shell said the command succeeded; the traceback is quoted text.

    Auditing every such observation in the 500-run population found only two
    sources: a display command printing a traceback stored in a file, and a
    script that caught the exception and exited cleanly.
    """
    status, signature = classify("cat debug.log", 0, observation=_TRACEBACK)
    assert (status, signature) == (ObservationStatus.OK, None)


def test_script_that_catches_its_exception_is_not_an_error():
    status, signature = classify("python repro.py", 0, observation=_TRACEBACK)
    assert (status, signature) == (ObservationStatus.OK, None)


def test_traceback_without_a_return_code_abstains():
    """Real output, but nothing says the command failed, so abstain."""
    status, signature = classify("python repro.py", None, observation=_TRACEBACK)
    assert (status, signature) == (ObservationStatus.UNKNOWN, None)


def test_traceback_with_a_nonzero_return_code_is_still_an_error():
    status, signature = classify("python repro.py", 1, observation=_TRACEBACK)
    assert (status, signature) == (ObservationStatus.ERROR, "python_exception")


def test_failing_test_run_is_an_error_with_a_framework_signature():
    status, signature = classify("python -m pytest tests/ -q", 1, action_kind=ActionKind.TEST_RUN)
    assert (status, signature) == (ObservationStatus.ERROR, "test_failure:pytest")


def test_harness_format_error_needs_no_return_code():
    status, signature = classify(
        "",
        None,
        observation="Please always provide exactly one action in triple backticks",
    )
    assert (status, signature) == (ObservationStatus.ERROR, "harness_format_error")


def test_word_error_in_passing_output_is_not_an_error():
    """No NLP: a passing test whose output mentions errors stays OK."""
    status, signature = classify(
        "python -m pytest tests/ -q",
        0,
        observation="10 passed. test_error_handling PASSED",
        action_kind=ActionKind.TEST_RUN,
    )
    assert (status, signature) == (ObservationStatus.OK, None)


def test_missing_returncode_with_no_marker_is_unknown():
    status, signature = classify("ls", None, observation="some output")
    assert (status, signature) == (ObservationStatus.UNKNOWN, None)


# --- Signatures are low-cardinality (Part G) ------------------------------


@pytest.mark.parametrize(
    ("signature", "expected"),
    [
        ("test_failure:pytest", ErrorFamily.TEST_FAILURE),
        ("python_exception", ErrorFamily.PYTHON_EXCEPTION),
        ("python_syntax_error", ErrorFamily.PYTHON_EXCEPTION),
        ("patch_apply_failed", ErrorFamily.PATCH_FAILURE),
        ("timeout", ErrorFamily.TIMEOUT),
        ("command_failure:grep", ErrorFamily.COMMAND_FAILURE),
    ],
)
def test_signatures_map_to_families(signature, expected):
    assert error_family(signature) == expected


@pytest.mark.parametrize(
    "command",
    [
        "python /tmp/tmp8f3k2/test_bug.py",
        "python /home/user/repro_2024_01_02.py",
    ],
)
def test_signatures_carry_no_paths_or_timestamps(command):
    """Same error, different temp dir, must merge to one signature."""
    _, signature = classify(command, 1, action_kind=ActionKind.TEST_RUN)
    assert signature == "test_failure:script"
    for fragment in ("/tmp", "tmp8f3k2", "2024", ".py", "/home"):
        assert fragment not in signature
