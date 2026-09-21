# `error_event_v1` — frozen observable-error detector

Status: **frozen** for Phases 1 and 2. Normative implementation:
`src/recoverability/errors.py`. This document and that module must change
together, and only with a version bump.

## What this detects

An **observable error event** is a single step whose observation shows the
environment rejecting or failing the agent's action, judged only from what that
step carries. It is deliberately *not* a claim about the run: a failing test run
is an error event in a run the benchmark later resolves.

## Two structural properties

**Blind to the verdict.** Every function takes only the command, the action
kind, the observation text and the return code. None accepts a `RunRecord`, a
`final_success`, or a verdict of any kind. `tests/test_error_events.py` asserts this
over the signatures, so a rule cannot be tuned until the final table looks
better.

**Precision over recall.** An ambiguous observation becomes `UNKNOWN`, never
`ERROR`. We would rather undercount error events than inflate them, because the
headline quantity of Phase 1B is a conditional probability whose numerator is
exactly this count.

## Decision order

Most structured signal first. The first rule that fires wins.

1. **Harness format error.** The harness reports the model's message was
   malformed. No return code exists, so this needs its own rule. It is a real
   error event: the step produced no environment effect and the agent must
   retry. → `harness_format_error`
2. **Timeout**, checked *ahead* of the return-code rule. A killed command also
   exits non-zero, and `command_failure:python` would hide the more specific
   fact. → `timeout`
3. **Non-zero return code**, attributed to a command segment (below). A
   traceback outranks the attribution problem; then test runs and patch
   operations get semantic signatures; an unattributable exit becomes `UNKNOWN`.
   → `python_exception`, `test_failure:<framework>`, `patch_apply_failed`,
   `command_failure:<family>`
4. **Text markers** for failures the harness reports without a return code, at
   present only patch application. → `patch_apply_failed`
5. **Traceback at return code 0** → `OK`. See below.
6. Otherwise `OK` if a return code said 0, else `UNKNOWN`.

## The informational non-zero rule

A non-zero exit is not always a failure. `grep` finding nothing exits 1. This
was the **one systematic false-positive class** the audit found, and excluding it
by command family (never by reading the output for the word "error") is the only
recall the frozen version gives up on purpose.

The complication is that it is mostly *not* a bare `grep`. It arrives as
`sed -n '...' f.py | grep X` or `cd tests && grep X`, so the exit code must be
attributed to a segment before the rule can apply. `split_shell_segments` is
quote-aware because `grep -n "a\|b" f.py` carries a `|` inside a regex, and
treating that as a pipeline misattributes the code.

- Trailing predicate, single segment or pure pipeline → `INFORMATIONAL` → `OK`.
  In a pipeline the exit status is the last stage's, so the predicate accounts
  for it.
- Trailing predicate behind `&&` or `;` → `UNATTRIBUTABLE` → `UNKNOWN`. An
  earlier segment may have failed and never reached the predicate. Both produce
  exit 1 and nothing in the record distinguishes them.
- Anything else → `FAILURE`.

Restricted to exit code 1: `grep` exits 2 on a real error such as an unreadable
file, and that stays `ERROR`.

Predicate heads: `grep` `egrep` `fgrep` `rg` `ag` `test` `[` `diff` `cmp`
`which` `command` `hash`, plus `git diff|grep|diff-index|diff-files|diff-tree`.
The audit justified `grep`; the rest are the same category of predicate command
and are excluded on the same principle, pre-emptively rather than after they
bite.

## Why a traceback at return code 0 is `OK`

The shell says the command succeeded. An audit of every such observation in the
500-run population found two benign sources, and no third: a display command
(`cat`, `sed`, `nl`, `ls`) printing a traceback stored in a file, and a script
that caught the exception and exited cleanly. Calling these errors would count
successful reads of a log as failures. With no return code at all the traceback
is real output but nothing says the command failed, so the rule abstains.

## Signatures

Low-cardinality by construction. A signature never encodes a file path, line
number, hash, temp directory or timestamp, so two failures of the same tool
collapse to the same string.

| Signature | Meaning |
| --- | --- |
| `test_failure:<framework>` | Test run exited non-zero; `pytest`, `tox`, `runtests`, `manage_py_test`, `unittest`, or `script` for an ad-hoc repro script |
| `python_exception` | Traceback with a non-zero exit |
| `python_syntax_error` | `SyntaxError` / `IndentationError` |
| `python_import_error` | `ImportError` / `ModuleNotFoundError` |
| `patch_apply_failed` | Patch or `git apply` rejected |
| `timeout` | Harness killed the command |
| `harness_format_error` | Harness rejected the model's message |
| `command_failure:<family>` | Everything else; family is the command head, or `git_<subcommand>` |

Families for breakdowns (`error_family`, derived from the signature rather than
stored, so it cannot drift): `test_failure`, `python_exception`,
`patch_failure`, `timeout`, `harness_format_error`, `command_failure`, `other`.

## Known limits

- Tuned against one harness (mini-SWE-agent v1.0.0, bash-only). Its return-code
  envelope is what makes the detector this simple. Phase 1C tests transfer.
- A silent wrong answer at exit 0 is invisible here, by design.
- `UNATTRIBUTABLE` abstentions are a real recall loss: 22 steps in the
  population. Recorded rather than resolved.
