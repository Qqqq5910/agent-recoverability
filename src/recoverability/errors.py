"""``error_event_v1``: the frozen observable-error detector for Phases 1-2.

This module is the single normative implementation of "an observable error
event". ``docs/error_event_v1.md`` is its prose specification; the two must be
changed together, and only with a version bump.

Two properties are structural, not conventions:

1. **Blind to the verdict.** Every function here takes only what a step itself
   carries: the command, the action kind, the observation text and the return
   code. No function accepts a ``RunRecord``, a ``final_success`` or a verdict of
   any kind, so a rule cannot be tuned to make the final numbers look better.
   ``tests/test_error_events.py`` asserts this over the signatures.
2. **Precision over recall.** An ambiguous observation becomes ``UNKNOWN``, not
   ``ERROR``. The Phase 1B audit of 102 candidate errors found exactly one
   systematic false-positive class -- ``grep`` exiting 1 because it matched
   nothing -- and this version excludes it by command family rather than by
   reading the output.

The audit that produced these rules is recorded in
``docs/artifacts/phase1b_unknown_audit_summary.json`` and
``docs/phase1b_findings.md``.
"""

from __future__ import annotations

import re
from enum import Enum
from typing import Final

from recoverability.schema import ActionKind, ObservationStatus

__all__ = [
    "ERROR_DETECTOR_VERSION",
    "ErrorFamily",
    "NonzeroVerdict",
    "classify_error",
    "error_family",
    "is_informational_nonzero",
    "split_shell_segments",
]


class NonzeroVerdict(Enum):
    """Who a non-zero exit code belongs to.

    ``UNATTRIBUTABLE`` exists so that the ambiguous case has somewhere to go
    other than ERROR: ``cd tests && grep missing`` exits 1 whether the directory
    was absent or the pattern simply did not match, and error_event_v1 prefers
    UNKNOWN to a guess.
    """

    FAILURE = "failure"
    INFORMATIONAL = "informational"
    UNATTRIBUTABLE = "unattributable"


#: Bumped whenever a rule below changes the classification of any observation.
ERROR_DETECTOR_VERSION: Final = "error_event_v1"


class ErrorFamily:
    """Coarse error families used for descriptive breakdowns.

    Deliberately a small closed set of strings rather than an enum on the step:
    the family is derived from ``error_signature``, so storing it would be
    denormalised state that could drift from the signature.
    """

    TEST_FAILURE: Final = "test_failure"
    PYTHON_EXCEPTION: Final = "python_exception"
    PATCH_FAILURE: Final = "patch_failure"
    TIMEOUT: Final = "timeout"
    HARNESS_FORMAT_ERROR: Final = "harness_format_error"
    COMMAND_FAILURE: Final = "command_failure"
    OTHER: Final = "other"


#: Commands whose non-zero exit is a *negative result*, not a failure.
#:
#: Each entry is justified by the Phase 1B audit: 7 of 9 generic non-zero
#: observations in the smoke sample were ``grep`` exiting 1 on no match. The
#: others in this tuple are the same category of predicate command and are
#: excluded on the same principle, pre-emptively rather than after they bite.
#:
#: Restricted to exit code 1: ``grep`` exits 2 on a real error such as an
#: unreadable file, and that stays an ERROR.
_INFORMATIONAL_NONZERO_HEADS: Final[tuple[str, ...]] = (
    "grep",
    "egrep",
    "fgrep",
    "rg",
    "ag",
    "test",
    "[",
    "diff",
    "cmp",
    "which",
    "command",
    "hash",
)

#: ``git`` subcommands that use exit 1 to report "no difference" / "no match".
_INFORMATIONAL_GIT_SUBCOMMANDS: Final[tuple[str, ...]] = (
    "diff",
    "grep",
    "diff-index",
    "diff-files",
    "diff-tree",
)

#: Text markers for errors the harness reports without a return code. Matched
#: only against observations that carry no usable return code, or return code 0,
#: so a passing test run is never reclassified because its output says "error".
#:
#: A traceback is deliberately absent here. At return code 0 the shell reports
#: that the command succeeded, and an audit of every such observation in the
#: 500-run population found two benign sources: a display command (``cat``,
#: ``sed``, ``nl``, ``ls``) printing a traceback stored in a file, and a script
#: that caught the exception and exited cleanly. Both are handled below.
_TEXT_MARKERS: Final[tuple[tuple[str, str], ...]] = (
    ("patch does not apply", "patch_apply_failed"),
    ("error: patch failed", "patch_apply_failed"),
)

#: A Python traceback. An error event only when the return code agrees; see the
#: return-code-0 branch in :func:`classify_error` for the audited reasoning.
_TRACEBACK_MARKER: Final = "traceback (most recent call last)"

#: Harness timeout reports. Checked ahead of the return-code rule, because a
#: killed command also exits non-zero and the timeout is the more specific fact.
_TIMEOUT_MARKERS: Final[tuple[tuple[str, str], ...]] = (
    ("command timed out", "timeout"),
    ("timed out and has been killed", "timeout"),
)

#: The harness's own complaint that the model's message was malformed. This is
#: an observable error event: the step produced no environment effect and the
#: agent must retry. It has no return code, which is why it needs its own rule.
_FORMAT_ERROR_RE: Final = re.compile(
    r"please always provide exactly one action in triple backticks", re.IGNORECASE
)

#: Interpreter-level failures that appear with a non-zero return code. Used to
#: give a semantic signature instead of a bare ``returncode_N``.
_INTERPRETER_MARKERS: Final[tuple[tuple[str, str], ...]] = (
    (_TRACEBACK_MARKER, "python_exception"),
    ("syntaxerror", "python_syntax_error"),
    ("indentationerror", "python_syntax_error"),
    ("modulenotfounderror", "python_import_error"),
    ("importerror", "python_import_error"),
)


def _command_head(command: str) -> str:
    """First bare word of a command, ignoring env-var assignments."""
    for token in command.strip().split():
        if "=" in token and not token.startswith("-"):
            continue
        return token.rsplit("/", 1)[-1].lower()
    return ""


#: Test frameworks, longest-first so ``py.test`` is not shadowed by ``pytest``.
#: Used to name the framework in a ``test_failure:`` signature, where the bare
#: interpreter (``python -m pytest`` -> ``python``) would say nothing useful.
_TEST_FRAMEWORKS: Final[tuple[str, ...]] = (
    "nosetests",
    "runtests",
    "manage.py test",
    "py.test",
    "unittest",
    "pytest",
    "tox",
)


def _test_framework(command: str) -> str:
    """Which test runner this command invokes, for a test-failure signature."""
    lowered = command.lower()
    for framework in _TEST_FRAMEWORKS:
        if framework in lowered:
            return re.sub(r"[^a-z0-9]+", "_", framework).strip("_")
    return "script"


def _command_family(command: str) -> str:
    """Stable, low-cardinality family for a command failure signature.

    Never includes a path, line number, temp directory, hash or timestamp: two
    failures of the same tool must collapse to the same signature.
    """
    head = _command_head(command)
    if not head:
        return "unknown"
    if head == "git":
        tokens = [t for t in command.strip().split()[1:] if not t.startswith("-")]
        return f"git_{tokens[0].lower()}" if tokens else "git"
    return re.sub(r"[^a-z0-9_]+", "_", head).strip("_") or "unknown"


def split_shell_segments(command: str) -> list[tuple[str, str]]:
    """Split ``command`` on unquoted ``&&``, ``||``, ``;`` and ``|``.

    Returns ``(separator_before, segment)`` pairs, the first separator empty.
    Quote-aware on purpose: an agent's ``grep -n "a\\|b" f.py`` carries a ``|``
    inside a quoted regex, and treating that as a pipeline misattributes the
    exit code. Backslash escapes and both quote styles are respected.
    """
    segments: list[tuple[str, str]] = []
    separator = ""
    current: list[str] = []
    quote: str | None = None
    index = 0
    while index < len(command):
        char = command[index]
        if quote is not None:
            current.append(char)
            if char == "\\" and quote == '"' and index + 1 < len(command):
                current.append(command[index + 1])
                index += 2
                continue
            if char == quote:
                quote = None
            index += 1
            continue
        if char in "'\"":
            quote = char
            current.append(char)
            index += 1
            continue
        if char == "\\" and index + 1 < len(command):
            current.append(char)
            current.append(command[index + 1])
            index += 2
            continue
        matched = next((op for op in ("&&", "||", ";", "|") if command.startswith(op, index)), None)
        if matched is not None:
            segments.append((separator, "".join(current).strip()))
            separator = matched
            current = []
            index += len(matched)
            continue
        current.append(char)
        index += 1
    segments.append((separator, "".join(current).strip()))
    return [(sep, seg) for sep, seg in segments if seg]


def _is_informational_head(segment: str) -> bool:
    """Whether ``segment``'s command is a predicate whose exit 1 means "no match"."""
    head = _command_head(segment)
    if head == "git":
        tokens = [t for t in segment.split()[1:] if not t.startswith("-")]
        return bool(tokens) and tokens[0].lower() in _INFORMATIONAL_GIT_SUBCOMMANDS
    return head in _INFORMATIONAL_NONZERO_HEADS


def is_informational_nonzero(command: str, returncode: int | None) -> NonzeroVerdict:
    """Attribute a non-zero exit to the command that produced it.

    ``grep`` finding nothing exits 1 and is not an error. This was the one
    systematic false-positive class the Phase 1B audit found, and it is mostly
    *not* a bare ``grep``: it arrives as ``sed -n '...' f.py | grep X`` or
    ``cd tests && grep X``. So the exit code has to be attributed to a segment
    before the predicate rule can be applied.

    Returns:
        ``INFORMATIONAL`` when the exit code provably belongs to a predicate
        command, ``UNATTRIBUTABLE`` when it may belong to either a predicate or
        a genuine failure, and ``FAILURE`` otherwise. Only exit code 1
        qualifies: ``grep`` exits 2 on a real error such as an unreadable file.
    """
    if returncode != 1:
        return NonzeroVerdict.FAILURE
    segments = split_shell_segments(command)
    if not segments:
        return NonzeroVerdict.FAILURE
    if not _is_informational_head(segments[-1][1]):
        return NonzeroVerdict.FAILURE
    if len(segments) == 1:
        return NonzeroVerdict.INFORMATIONAL
    # In a pipeline the exit status is the last stage's, so a trailing predicate
    # accounts for it. In an && / ; chain an earlier segment may have failed
    # instead and never reached the predicate; both produce exit 1, and nothing
    # in the record distinguishes them.
    if all(separator == "|" for separator, _ in segments[1:]):
        return NonzeroVerdict.INFORMATIONAL
    return NonzeroVerdict.UNATTRIBUTABLE


def classify_error(
    *,
    command: str,
    action_kind: ActionKind,
    observation: str,
    returncode: int | None,
    raw_observation: str | None = None,
) -> tuple[ObservationStatus, str | None]:
    """Classify one observation. The whole of ``error_event_v1``.

    Takes only prefix-visible inputs: no run, no verdict, no total step count.
    Returns the status and, for an error, a low-cardinality signature.

    Args:
        command: The command the agent issued.
        action_kind: Its classified kind.
        observation: The command's output, envelope tags already stripped.
        returncode: Exit code, or ``None`` when the format carried none.
        raw_observation: The observation *before* tag stripping, when the caller
            has it. Some harness-level failures -- a timeout, a malformed
            action -- are reported outside the ``<output>`` tag, so they are
            invisible in ``observation`` alone. Defaults to ``observation``.

    Priority, most structured signal first:

    1. Harness format error (no return code, unambiguous harness text).
    2. Timeout, ahead of the return-code rule: a killed command also exits
       non-zero, and the timeout is the more specific fact.
    3. Non-zero return code, attributed via :func:`is_informational_nonzero`.
       An exit that provably belongs to a predicate command is ``OK``; one that
       cannot be attributed is ``UNKNOWN``, never ``ERROR``.
    4. Text markers for failures the harness reports without a return code.
    5. A traceback alongside return code 0 is ``OK``: the command succeeded, so
       it either printed a traceback it had stored or caught the exception.
    6. Otherwise ``OK`` when a return code said 0, else ``UNKNOWN``.
    """
    envelope = observation if raw_observation is None else raw_observation
    lowered = f"{observation}\n{envelope}".lower()

    if _FORMAT_ERROR_RE.search(envelope):
        return ObservationStatus.ERROR, "harness_format_error"

    # Before the return-code rule: a killed command exits non-zero, and
    # "command_failure:python" would hide the fact that it was a timeout.
    for marker, signature in _TIMEOUT_MARKERS:
        if marker in lowered:
            return ObservationStatus.ERROR, signature

    if returncode is not None and returncode != 0:
        verdict = is_informational_nonzero(command, returncode)
        if verdict is NonzeroVerdict.INFORMATIONAL:
            return ObservationStatus.OK, None
        # An interpreter traceback is a real failure whichever segment produced
        # it, so it outranks the attribution problem.
        for marker, signature in _INTERPRETER_MARKERS:
            if marker in lowered:
                return ObservationStatus.ERROR, signature
        if action_kind is ActionKind.TEST_RUN:
            return ObservationStatus.ERROR, f"test_failure:{_test_framework(command)}"
        if action_kind is ActionKind.PATCH:
            return ObservationStatus.ERROR, "patch_apply_failed"
        if verdict is NonzeroVerdict.UNATTRIBUTABLE:
            return ObservationStatus.UNKNOWN, None
        return ObservationStatus.ERROR, f"command_failure:{_command_family(command)}"

    for marker, signature in _TEXT_MARKERS:
        if marker in lowered:
            return ObservationStatus.ERROR, signature

    if _TRACEBACK_MARKER in lowered:
        # Return code 0, so the shell says the command succeeded. Either it only
        # printed a traceback stored in a file, or a script caught the exception
        # and exited cleanly. Neither is an error event in this step; claiming
        # otherwise inflates the error rate with successful reads of a log.
        if returncode == 0:
            return ObservationStatus.OK, None
        # No return code at all: the traceback is real output, but nothing says
        # whether the command failed. Under the precision-first rule, abstain.
        return ObservationStatus.UNKNOWN, None

    if returncode == 0:
        return ObservationStatus.OK, None
    return ObservationStatus.UNKNOWN, None


def error_family(error_signature: str | None) -> str:
    """Map a signature to its coarse :class:`ErrorFamily` string."""
    if not error_signature:
        return ErrorFamily.OTHER
    if error_signature.startswith("test_failure"):
        return ErrorFamily.TEST_FAILURE
    if error_signature.startswith("command_failure"):
        return ErrorFamily.COMMAND_FAILURE
    if error_signature.startswith("python_"):
        return ErrorFamily.PYTHON_EXCEPTION
    if error_signature.startswith("patch_"):
        return ErrorFamily.PATCH_FAILURE
    if error_signature == "timeout":
        return ErrorFamily.TIMEOUT
    if error_signature == "harness_format_error":
        return ErrorFamily.HARNESS_FORMAT_ERROR
    return ErrorFamily.OTHER
