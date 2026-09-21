# Definitions

Normative vocabulary for this project. Where a definition is provisional, it is
marked **v1** and the open question is recorded as a TODO.

---

## trajectory

The ordered sequence of steps produced by one agent on one task in one run:

```
τ = (s_1, ..., s_T),  s_t = (action_t, observation_t, metadata_t)
```

A **step** is one action-observation pair: the agent emits an action (tool call,
command, patch, message) and the environment returns an observation (stdout,
diff result, test report, error text). `T` is the terminal index, reached by a
success verdict, an explicit give-up, or exhaustion of the harness budget.

The trajectory is the *observable* record. Hidden model state, sampled
reasoning tokens that the harness discards, and anything not logged are not part
of it. Recoverability is defined on what a supervisor could actually see.

## trajectory prefix

`τ_{1:t} = (s_1, ..., s_t)` for `1 <= t <= T`.

Every prediction target in this project conditions on a prefix and nothing else.
Using any information from `s_{t+1}, ..., s_T` (including the final patch, the
final verdict, or `trajectory_length` of the full run) is **leakage**.

Note the trap: total trajectory length is a function of the future. The schema
therefore exposes `trajectory_length_so_far` (= `step_index + 1`) and never a
total length on step records.

## error event

An observable, machine-identifiable indication at step `t` that something went
wrong in the agent's own execution. **v1** candidates:

- non-zero exit code from a command the agent issued,
- test failure reported by the harness's test runner,
- interpreter traceback / compile error in the observation,
- tool-call schema violation or rejected/invalid action,
- patch application failure,
- timeout of an agent-issued command.

An error event is a property of a single step's observation. It is *not* a
judgement about the run.

Explicit non-criteria for v1: an agent's own natural-language self-doubt ("this
might be wrong") is not an error event; slow progress is not an error event.

TODO(def): finalise the error-event taxonomy and the detector for each type per
supported harness; record per-harness detection rules in Phase 1.

## error signature

A normalised, comparable identifier for *what kind of* error occurred, used to
detect repetition. **v1**: a tuple-derived string such as
`(error_type, normalised_message_head, tool_name)`, with paths, line numbers,
hashes, temp dirs and timestamps stripped.

Two steps sharing an error signature are treated as the same error recurring.
This is the basis of the repeated-error-signature baseline.

TODO(def): specify the normalisation function precisely; it materially affects
the "repeated error" baseline and must be frozen before Phase 3.

## self recovery

**v1 definition.** After an identifiable error event at step `t`, the *same*
agent continues execution and eventually reaches benchmark-defined task success,
with **no** external human help, **no** model replacement, **no** environment
reset, and **no** human-authored patch at any point after `t`.

Consequences that are intended:

- Recovery is credited to the agent, not the supervisor.
- Fixing the error by a different route (rewriting the approach, abandoning the
  broken file, re-deriving the patch) still counts as recovery. The criterion is
  the task outcome, not repair of the specific artifact.
- Recovery is only defined relative to a preceding error event. A run with no
  error events is a success or failure, not a "recovery".

**A test failure does not automatically equal an unrecoverable failure.** Running
tests and seeing them fail is a normal, often necessary, information-gathering
step in a coding trajectory. Treating it as terminal is precisely the error this
project argues against.

## eventual recovery

Self recovery with no bound on the number of remaining steps, other than the
harness's own budget. This is the label used for `R_t`.
`self_recovered_eventually` in the schema records it.

## recovery horizon

The bound `k` in `R_t^(k)`: recovery counted only if it occurs within `k` steps
after `t`. `steps_to_recovery` in the schema records the observed distance, so
any `k` can be applied post hoc without relabelling.

TODO(def): fix what "recovery occurred at step `t + j`" means operationally
(first error-free step, first passing test run, or task success). Open in
`research_spec.md` 2.1.

## external intervention

Any change to the run that does not originate from the agent's own policy acting
on its own observations. **v1** includes:

- human message, hint, instruction or correction injected mid-run,
- human-authored patch or manual file edit,
- swapping the underlying model or scaffold mid-run,
- environment reset, checkpoint rollback, or restart,
- forced abort / early termination,
- automated supervisor actions from an outer control loop.

Routine harness behaviour that is part of the agent loop (retry on transient
network error, standard tool error message, budget accounting) is **not** an
intervention.

Data discipline: a run containing an external intervention cannot provide
"continue" labels past the intervention point. Such runs are either excluded from
Phase 2 labelling or truncated at the intervention step, and the reason recorded.

## task success

The benchmark's own verdict for the task, evaluated by the harness, not by a
model or a human judgement. For SWE-bench-style tasks this is the held-out test
suite passing (fail-to-pass plus pass-to-pass). Recorded as `final_success`.

The definition is delegated on purpose: recoverability should not inherit a
custom success notion that differs from the community benchmark's.

An agent declaring itself finished is **not** task success. The two live on
independent axes and neither may be derived from the other:

- `termination_reason` — the **observed reason the run stopped**, read only from
  what the agent or harness reports (for mini-SWE-agent, `info.exit_status`).
- `final_success` — the **benchmark outcome**, read only from a trusted
  benchmark artifact, with `verdict_source` recording which one.

A benchmark verdict never changes `termination_reason`, and a stop reason never
implies a verdict. A run that submitted cleanly but failed evaluation is
`termination_reason=AGENT_SUBMITTED` with `final_success=False`; one that
submitted and resolved is *also* `AGENT_SUBMITTED`, with `final_success=True`.
The stop reason is identical in both because the agent stopped the same way.

`TerminationReason.SUCCESS` and `BENCHMARK_FAILURE` exist only for sources whose
harness itself declares such a state as its stop condition. They are not a place
to restate `final_success`, and the mini-SWE-agent adapter never emits them.

Where a verdict is absent, `final_success` stays `None` and is never promoted
from the agent's own claim.

TODO(def): for each ingested source, record exactly which verdict field is used
as `final_success`, and whether partial credit exists (it must be reduced to a
boolean explicitly, never implicitly).

## action kind vs observation status

Schema 0.2.0 splits what the agent *did* from what *came back*. These are
orthogonal: `ActionKind.TEST_RUN` with `ObservationStatus.ERROR` is a failing
test, which is an ordinary and frequent event inside runs that go on to succeed.
Collapsing the two (schema 0.1.0's single `EventType`) made that state
inexpressible and would have biased the dataset against exactly the phenomenon
this project studies.

`error_signature` is a property of one observation, tied to
`observation_status=ERROR`, and says nothing about how the run ends.

## recoverability

The probability that a run ends in task success given only the prefix and given
that no external intervention occurs:

```
R_t = P(task success | τ_{1:t}, no external intervention)
```

Recoverability is a property of a *(prefix, agent, environment)* triple, not of
an error. The same error signature can have very different recoverability in
different prefixes; that variation is what H2 asserts.

Two things recoverability is **not**:

- not a measure of whether an error occurred (that is error detection),
- not a post-hoc explanation of why a finished run failed (that is failure
  analysis).

## intervention value

For an intervention action `a`:

```
IV_t(a) = P(success | τ_{1:t}, intervention = a) - P(success | τ_{1:t}, continue)
```

The causal contrast between intervening with `a` and doing nothing, from the same
prefix. Positive `IV_t(a)` means `a` helps; near-zero means the intervention is
unnecessary (the agent would have recovered anyway); negative means the
intervention is harmful.

Cost is deliberately excluded from `IV_t(a)` and handled separately in the policy
objective, so that benefit and price stay separable.

TODO(def): define the action set `A` and the cost model; decide whether `IV` is
estimated by checkpoint branching (Phase 5) or an off-policy estimator.

---

## Derived label vocabulary (used by the schema)

| Term | Field | Meaning |
| --- | --- | --- |
| eventual success | `final_success` | benchmark verdict for the whole run |
| eventual recovery | `self_recovered_eventually` | an error event occurred and the run still succeeded without intervention |
| recovery distance | `steps_to_recovery` | steps from the error event to the recovery point |
| error identity | `error_signature` | normalised error kind, for repetition detection |

`self_recovered_eventually` is undefined (`None`) for runs with no error event.
That is a genuine "not applicable", not a missing value, and must not be imputed
to `False`.
