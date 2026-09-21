"""Structural audit of ``ObservationStatus.UNKNOWN`` steps.

An UNKNOWN observation is either a genuine property of the source format or a
gap in the parser, and the two demand opposite responses. This module decides
which, from the raw message structure only -- never from the outcome, and never
by guessing what the status "should" have been.

Also here: the offline descriptive statistics that need the *total* trajectory
length. They live behind an explicit naming convention because total length is
future information.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from enum import StrEnum
from typing import Any

from recoverability.schema import ObservationStatus, RunRecord, StepRecord

__all__ = [
    "OFFLINE_ONLY_FIELDS",
    "AuditReason",
    "UnknownAuditRecord",
    "audit_unknown_steps",
    "offline_first_error_position",
]


class AuditReason(StrEnum):
    """Why a step's observation status could not be determined.

    Assigned from message structure alone. ``parser_issue`` on the record, not
    this enum, says whether the reason is a defect.
    """

    NO_FOLLOWING_OBSERVATION = "no_following_observation"
    """No user message followed the action: the run ended on it."""

    EMPTY_OBSERVATION = "empty_observation"
    """A following message existed but carried no text."""

    MISSING_RETURNCODE_WITH_TEXT = "missing_returncode_with_text"
    """Observation text present, no ``<returncode>`` tag, no other signal.

    The expected shape for the terminal SUBMIT step: the harness hands back the
    submission rather than executing another command, so there is no exit code.
    This is a property of the format, not a defect.
    """

    UNPARSED_FORMAT_VARIANT = "unparsed_format_variant"
    """A ``<returncode>`` tag is present in the raw text but did not reach the step.

    The one reason that is always a parser bug: the signal exists in the raw
    record and the adapter failed to extract it.
    """

    DETECTOR_ABSTAINED = "detector_abstained"
    """The return code reached the step and the detector declined to rule on it.

    Not a defect but the precision-first policy working as specified: a
    non-zero exit that cannot be attributed to a single command (a pipeline or
    ``&&`` chain ending in a predicate such as ``grep``) is left UNKNOWN rather
    than counted as an error. See :mod:`recoverability.errors`.
    """

    NON_EXECUTION_MESSAGE = "non_execution_message"
    """The assistant message contained no command, so nothing was executed."""

    OTHER = "other"
    """Structure did not match any category above."""


#: Names that carry total-trajectory-length information. Any feature builder
#: must reject these; ``tests/test_audit.py`` enforces that.
OFFLINE_ONLY_FIELDS: frozenset[str] = frozenset(
    {
        "first_error_fraction",
        "total_steps",
        "n_steps",
        "trajectory_length",
    }
)


@dataclass(slots=True)
class UnknownAuditRecord:
    """One audited UNKNOWN step. Carries no observation text by construction."""

    task_id: str
    step_index: int
    action_kind: str
    audit_reason: AuditReason
    has_observation_text: bool
    has_returncode_tag: bool
    is_final_step: bool
    parser_issue: bool

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def audit_unknown_steps(
    run: RunRecord,
    *,
    raw_observations: dict[int, str | None],
) -> list[UnknownAuditRecord]:
    """Audit every UNKNOWN step in ``run``.

    Args:
        run: The parsed run. Only its steps are read; the verdict is not
            consulted and could not change any decision here.
        raw_observations: ``step_index`` -> the raw observation text that
            followed the action, or ``None`` when no user message followed.
            Supplied by the caller because only the adapter can pair messages.

    Returns:
        One record per UNKNOWN step, in step order.
    """
    records: list[UnknownAuditRecord] = []
    last_index = len(run.steps) - 1
    for step in run.steps:
        if step.observation_status is not ObservationStatus.UNKNOWN:
            continue
        raw = raw_observations.get(step.step_index)
        reason, parser_issue = _classify_unknown(step, raw)
        records.append(
            UnknownAuditRecord(
                task_id=step.task_id,
                step_index=step.step_index,
                action_kind=step.action_kind.value,
                audit_reason=reason,
                has_observation_text=bool(raw and raw.strip()),
                has_returncode_tag=bool(raw and "<returncode>" in raw),
                is_final_step=step.step_index == last_index,
                parser_issue=parser_issue,
            )
        )
    return records


def _classify_unknown(step: StepRecord, raw: str | None) -> tuple[AuditReason, bool]:
    """Return the audit reason and whether it indicates a parser defect."""
    if raw is None:
        return AuditReason.NO_FOLLOWING_OBSERVATION, False
    if not raw.strip():
        return AuditReason.EMPTY_OBSERVATION, False
    if "<returncode>" in raw:
        if step.returncode is not None:
            # Parsed fine; the detector declined to rule. Policy, not defect.
            return AuditReason.DETECTOR_ABSTAINED, False
        # The structured signal was there and the adapter did not extract it.
        return AuditReason.UNPARSED_FORMAT_VARIANT, True
    if not step.action.strip():
        return AuditReason.NON_EXECUTION_MESSAGE, False
    return AuditReason.MISSING_RETURNCODE_WITH_TEXT, False


def offline_first_error_position(run: RunRecord) -> dict[str, Any] | None:
    """First-error position for a run, for offline description only.

    OFFLINE ANALYSIS ONLY -- NOT PREFIX SAFE. ``first_error_fraction`` divides
    by the total number of steps, which is not knowable at step ``t``. It may
    appear in a summary artifact or a memo and must never reach a feature
    extractor for ``R_t``. See :data:`OFFLINE_ONLY_FIELDS`.

    Returns ``None`` for a run with no error event.
    """
    indices = run.error_step_indices
    if not indices:
        return None
    total = run.n_steps
    first = indices[0]
    return {
        "first_error_step": first,
        "total_steps": total,
        "first_error_fraction": (first / total) if total else None,
    }
