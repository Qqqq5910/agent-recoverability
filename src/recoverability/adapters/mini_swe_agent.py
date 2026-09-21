"""Adapter for mini-SWE-agent ``*.traj.json`` artifacts.

Format as observed in the SWE-bench submissions bucket (bash-only,
mini-SWE-agent v1.0.0)::

    {
      "info": {"exit_status": "Submitted",
               "submission": "diff --git ...",
               "model_stats": {"instance_cost": 0.19, "api_calls": 22}},
      "messages": [
        {"role": "system",    "content": "<str>"},
        {"role": "user",      "content": [{"type": "text", "text": "<pr_description>..."}]},
        {"role": "assistant", "content": "THOUGHT: ...\\n\\n```bash\\nls\\n```"},
        {"role": "user",      "content": [
            {"type": "text",
             "text": "<returncode>0</returncode>\\n<output>...</output>"}]}
      ],
      "instance_id": "astropy__astropy-12907"
    }

Two properties make this a good first source: the harness wraps every
observation in a ``<returncode>`` tag, giving a structured error signal that
needs no NLP; and the benchmark verdict is published separately, so it can be
attached at the run level without ever touching a step.

The harness reports why it stopped (``info.exit_status``) independently of
whether the benchmark resolved the instance. This adapter keeps those apart:
``exit_status`` alone determines ``termination_reason``, and the verdict alone
determines ``final_success``.

Notable absences, which stay ``None`` rather than being guessed: per-step
wall-clock time, per-step token cost (only a run-level total exists), and any
tool name (the agent has one tool, bash).
"""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from typing import Any, Final

from recoverability.adapters.base import (
    MalformedRecordError,
    SourceAdapter,
    assert_no_step_leakage,
)
from recoverability.schema import (
    ActionKind,
    ObservationStatus,
    RunRecord,
    StepRecord,
    TerminationReason,
    VerdictSource,
)

__all__ = ["MiniSweAgentAdapter"]

_RETURNCODE_RE: Final = re.compile(r"<returncode>(-?\d+)</returncode>")
_BASH_BLOCK_RE: Final = re.compile(r"```bash\s*\n(.*?)```", re.DOTALL)
_OUTPUT_RE: Final = re.compile(r"<output>\n?(.*?)</output>", re.DOTALL)

#: Sentinel the harness prepends to the final submission command.
_SUBMIT_SENTINEL: Final = "MICRO_SWE_AGENT_FINAL_OUTPUT"

#: ``info.exit_status`` -> termination reason. This is the sole input to
#: ``termination_reason``; the benchmark verdict never appears here. The agent
#: submitting is AGENT_SUBMITTED whether or not the instance resolved, so
#: neither SUCCESS nor BENCHMARK_FAILURE is reachable from this source.
_EXIT_STATUS_TO_TERMINATION: Final[dict[str, TerminationReason]] = {
    "submitted": TerminationReason.AGENT_SUBMITTED,
    "submitted (exit_cost)": TerminationReason.BUDGET_EXHAUSTED,
    "exit_cost": TerminationReason.BUDGET_EXHAUSTED,
    "exit_context": TerminationReason.BUDGET_EXHAUSTED,
    "exit_budget": TerminationReason.BUDGET_EXHAUSTED,
    "limitsexceeded": TerminationReason.BUDGET_EXHAUSTED,
    "exit_format": TerminationReason.CRASH,
    "exit_api": TerminationReason.CRASH,
    "exit_error": TerminationReason.CRASH,
    "exit_environment_error": TerminationReason.CRASH,
    "nonterminatingexception": TerminationReason.CRASH,
    "exit_timeout": TerminationReason.TIMEOUT,
    "timeout": TerminationReason.TIMEOUT,
    "exit_interrupt": TerminationReason.EXTERNAL_INTERRUPTION,
    "keyboardinterrupt": TerminationReason.EXTERNAL_INTERRUPTION,
}

#: Conservative, structured-signal-first error classification. Applied only to
#: an observation that already carries returncode 0, so a passing test run is
#: never reclassified on the strength of the word "error" appearing in output.
_ERROR_MARKERS: Final[tuple[tuple[str, str], ...]] = (
    ("patch does not apply", "patch_apply_failed"),
    ("error: patch failed", "patch_apply_failed"),
    ("traceback (most recent call last)", "python_exception"),
    ("command timed out", "timeout"),
)

#: Substrings that mark a command as a test invocation.
_TEST_MARKERS: Final = (
    "pytest",
    "py.test",
    "unittest",
    "runtests",
    "tox",
    "nosetests",
    "manage.py test",
)

#: Agents routinely write an ad-hoc reproduction script and run it. The
#: filename is a structured signal, so matching it is not string-sniffing the
#: output: ``python test_bug.py`` and ``python reproduce_issue.py`` are test
#: runs even though no test framework is named.
_TEST_SCRIPT_RE: Final = re.compile(
    r"\b(?:python[\d.]*|py)\b[^|;&]*?\b(?:test|tests|repro\w*|verify)\w*\.py\b"
)


def _message_text(content: Any) -> str:
    """Flatten a message body, which is either a string or content blocks."""
    if isinstance(content, str):
        return content
    if isinstance(content, Sequence):
        parts = [
            block.get("text", "")
            for block in content
            if isinstance(block, Mapping) and block.get("type") in (None, "text")
        ]
        return "".join(parts)
    return ""


def classify_action(command: str) -> ActionKind:
    """Classify a bash command into an :class:`ActionKind`.

    Ordered most specific first: the submission command is also a ``git`` call,
    and a heredoc that writes a test file is an edit rather than a test run.
    """
    if not command.strip():
        return ActionKind.UNKNOWN
    lowered = command.lower()

    if _SUBMIT_SENTINEL.lower() in lowered:
        return ActionKind.SUBMIT
    if "git apply" in lowered or lowered.startswith("patch ") or " patch -p" in lowered:
        return ActionKind.PATCH
    if any(
        marker in lowered
        for marker in ("<<'eof'", '<<"eof"', "<<eof", "tee ", "str_replace", "sed -i")
    ):
        return ActionKind.FILE_EDIT
    if ">" in command and not any(op in command for op in (">=", "->", "2>&1", ">>&")):
        return ActionKind.FILE_EDIT
    if any(marker in lowered for marker in _TEST_MARKERS):
        return ActionKind.TEST_RUN
    if _TEST_SCRIPT_RE.search(lowered):
        return ActionKind.TEST_RUN
    return ActionKind.COMMAND


def classify_observation(
    observation: str, returncode: int | None
) -> tuple[ObservationStatus, str | None]:
    """Classify an observation, preferring the structured return code.

    Returns the status and, for an error, a short signature. A failing test run
    is an ERROR observation; that is a statement about this step, not about how
    the run ends.
    """
    if returncode is None:
        if not observation.strip():
            return ObservationStatus.UNKNOWN, None
        lowered = observation.lower()
        for marker, signature in _ERROR_MARKERS:
            if marker in lowered:
                return ObservationStatus.ERROR, signature
        return ObservationStatus.UNKNOWN, None

    if returncode != 0:
        return ObservationStatus.ERROR, f"returncode_{returncode}"

    lowered = observation.lower()
    for marker, signature in _ERROR_MARKERS:
        if marker in lowered:
            return ObservationStatus.ERROR, signature
    return ObservationStatus.OK, None


class MiniSweAgentAdapter(SourceAdapter):
    """Parse mini-SWE-agent trajectories into :class:`RunRecord` objects."""

    source_id = "mini_swe_agent_v1_swebench_verified"

    def __init__(
        self,
        *,
        agent_name: str = "mini-SWE-agent",
        model_name: str = "unknown",
        source_id: str | None = None,
    ) -> None:
        self.agent_name = agent_name
        self.model_name = model_name
        if source_id is not None:
            self.source_id = source_id

    def parse_run(
        self,
        raw: Mapping[str, Any],
        *,
        verdict: bool | None = None,
    ) -> RunRecord:
        if not isinstance(raw, Mapping):
            raise MalformedRecordError(f"expected a mapping, got {type(raw).__name__}")

        task_id = raw.get("instance_id")
        if not isinstance(task_id, str) or not task_id:
            raise MalformedRecordError("missing or non-string 'instance_id'")

        messages = raw.get("messages")
        if not isinstance(messages, Sequence) or isinstance(messages, (str, bytes)):
            raise MalformedRecordError(f"{task_id}: 'messages' must be a list")
        for message in messages:
            if not isinstance(message, Mapping) or "role" not in message:
                raise MalformedRecordError(f"{task_id}: malformed message entry")

        info = raw.get("info")
        if info is not None and not isinstance(info, Mapping):
            raise MalformedRecordError(f"{task_id}: 'info' must be a mapping")
        info = info or {}

        steps = self._build_steps(task_id, messages)
        if not steps:
            raise MalformedRecordError(f"{task_id}: no assistant actions found")

        # Two independent dimensions: why the harness stopped, and what the
        # benchmark judged. Neither is allowed to rewrite the other.
        termination_reason = self._termination_reason(info)
        verdict_source = (
            VerdictSource.SWE_BENCH_REPORT if verdict is not None else VerdictSource.UNKNOWN
        )

        run = RunRecord(
            task_id=task_id,
            run_id=f"{self.source_id}/{task_id}",
            agent_name=self.agent_name,
            model_name=self.model_name,
            steps=steps,
            final_success=verdict,
            termination_reason=termination_reason,
            verdict_source=verdict_source,
            # Phase 1A: recovery labels are not computed. The recovery-point
            # definition is frozen in Phase 2; guessing now would bake in an
            # unreviewed definition.
            self_recovered_eventually=None,
            steps_to_recovery=None,
            had_external_intervention=False,
            extra=self._run_extra(info),
        )
        self.validate(run)
        return run

    def _build_steps(self, task_id: str, messages: Sequence[Any]) -> list[StepRecord]:
        """Pair each assistant action with the observation that followed it."""
        steps: list[StepRecord] = []
        for index, message in enumerate(messages):
            if message.get("role") != "assistant":
                continue

            text = _message_text(message.get("content"))
            block = _BASH_BLOCK_RE.search(text)
            command = block.group(1).strip() if block else ""

            observation_raw = ""
            for follower in messages[index + 1 :]:
                if follower.get("role") == "assistant":
                    break
                if follower.get("role") == "user":
                    observation_raw = _message_text(follower.get("content"))
                    break

            returncode_match = _RETURNCODE_RE.search(observation_raw)
            returncode = int(returncode_match.group(1)) if returncode_match else None
            output_match = _OUTPUT_RE.search(observation_raw)
            observation = (output_match.group(1) if output_match else observation_raw).strip()

            action_kind = classify_action(command)
            status, signature = classify_observation(observation, returncode)

            step_index = len(steps)
            step = StepRecord.at(
                step_index,
                task_id=task_id,
                run_id=f"{self.source_id}/{task_id}",
                agent_name=self.agent_name,
                model_name=self.model_name,
                action=command or text.strip(),
                observation=observation,
                action_kind=action_kind,
                observation_status=status,
                error_signature=signature,
                returncode=returncode,
                # tool_name, token_cost and wall_time are not recoverable
                # per-step from this format; left None rather than imputed.
            )
            assert_no_step_leakage(step)
            steps.append(step)
        return steps

    def _termination_reason(self, info: Mapping[str, Any]) -> TerminationReason:
        """Why did this run stop? Answered from the harness alone.

        ``info.exit_status`` is the harness's own account of why it stopped, so
        it is the only input. The benchmark verdict is a separate dimension and
        deliberately not consulted: a run that submitted and was then judged
        unresolved still terminated by submitting. Collapsing the two would
        destroy exactly the distinction this study is about.
        """
        raw_status = info.get("exit_status")
        status = raw_status.strip().lower() if isinstance(raw_status, str) else ""
        return _EXIT_STATUS_TO_TERMINATION.get(status, TerminationReason.UNKNOWN)

    def _run_extra(self, info: Mapping[str, Any]) -> dict[str, Any]:
        """Run-level passthrough. Outcome-bearing keys are legal only here."""
        extra: dict[str, Any] = {"source_id": self.source_id}
        if isinstance(info.get("exit_status"), str):
            extra["raw_exit_status"] = info["exit_status"]
        stats = info.get("model_stats")
        if isinstance(stats, Mapping):
            if isinstance(stats.get("api_calls"), (int, float)):
                extra["api_calls"] = stats["api_calls"]
            if isinstance(stats.get("instance_cost"), (int, float)):
                extra["instance_cost_usd"] = stats["instance_cost"]
        extra["has_submission"] = bool(info.get("submission"))
        return extra
