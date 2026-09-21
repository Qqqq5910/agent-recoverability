# Research Specification (Phase 0)

Status: **specification only**. Nothing here has been empirically tested in this
repository. No results are claimed.

---

## 1. Scope

Subject: autonomous **coding** agents operating in an execute-observe loop over a
repository (edit files, run commands, run tests, read output), on tasks with a
programmatic success criterion (benchmark-defined).

Unit of study: a single **run** (one agent, one task, one trajectory).

Out of scope for Phase 0-4: multi-agent orchestration, human-in-the-loop chat
agents, non-coding tool agents, and training any large model.

## 2. Primary quantity

For a run with trajectory `τ = (s_1, s_2, ..., s_T)` and prefix `τ_{1:t}`, the
Phase-1 target is:

```
R_t = P(eventual task success | τ_{1:t}, no external intervention)
```

Notes on the definition:

- **Conditioning is on a prefix only.** The estimator may not see anything after
  step `t`. This is what makes it an online/runtime quantity.
- **"No external intervention"** is part of the conditioning event, not an
  assumption about the data. Runs that received external help are either excluded
  or truncated at the point of intervention (see `docs/definitions.md`).
- **"Eventual"** means at the natural termination of the run under the harness's
  own budget (step limit / cost limit), not "unbounded time".
- `R_t` is a probability, so evaluation is a **calibration** problem as much as a
  ranking problem.

### 2.1 Bounded-horizon extension

```
R_t^(k) = P(task success or recovery within k future steps | τ_{1:t}, continue)
```

`R_t^(k)` is the operationally useful variant: a supervisor cares not only about
whether recovery happens but whether it happens soon enough to be worth waiting
for. `R_t` is the limit of `R_t^(k)` as `k` reaches the harness budget.

TODO: decide whether "recovery within k steps" is defined against the *next*
error event or against eventual success; both are defensible and they differ.
This must be fixed before Phase 2 labelling.

### 2.2 Intervention value

```
IV_t(a) = P(success | τ_{1:t}, intervention = a) - P(success | τ_{1:t}, continue)
```

for an intervention action `a` drawn from an action set `A` (e.g. hint injection,
rollback to an earlier checkpoint, model swap, restart, hand to human, abort).

This is a **counterfactual contrast**: both terms condition on the same prefix
and differ only in what is done next. Estimating it requires either branching
execution from a checkpoint (Phase 5) or an off-policy estimator over logged
interventions. Phases 0-4 do not attempt it.

TODO: define `A` concretely, including the cost of each `a`, before Phase 5.

## 3. Hypotheses

### H1 — Predictability

> Recoverability can be predicted from a partial agent trajectory better than
> trivial heuristics and generic LLM judges.

- Prediction: a model taking `τ_{1:t}` features achieves higher AUROC/AUPRC and
  lower Brier/ECE for `R_t` than (a) random, (b) trajectory-progress heuristics,
  (c) error-count heuristics, (d) a zero-shot LLM judge given the same prefix.
- Falsified if trivial baselines match the learned predictors within confidence
  intervals across tasks and agents.
- Metrics: AUROC, AUPRC, Brier, ECE (see `docs/experiment_plan.md`).

### H2 — Distinctness from failure detection

> Recoverability is distinct from failure detection. An agent can make an
> observable error while still having high probability of autonomous recovery.

- Prediction: conditional on an observable error event at step `t`, the empirical
  rate of eventual success is far from 0 and varies substantially with prefix
  context. An error-detection flag is therefore a weak predictor of `R_t`.
- Concretely: `P(final_success | error event at t)` is neither near 0 nor
  constant across error signatures and trajectory positions.
- Falsified if an error flag alone is a near-sufficient statistic for `R_t`
  (i.e. adding trajectory context yields no measurable improvement).
- TODO: pre-register the threshold that counts as "far from 0" before looking at
  labels, to avoid post-hoc framing.

### H3 — Policy value

> A calibrated recoverability-aware intervention policy can eventually improve
> the success/cost tradeoff relative to always-continue and naive error-triggered
> intervention.

- Prediction: a threshold policy on `R_t` (or a policy maximising `IV_t(a)` net
  of cost) dominates always-continue and "intervene on first error" on a
  success-rate vs. cost frontier.
- Requires Phase 5 machinery. **Not testable with Phase 1-4 artifacts.**
- Falsified if no threshold beats always-continue on the frontier, or if gains
  vanish once intervention cost is charged honestly.

## 4. What would make this work wrong or uninteresting

Stated up front, to keep the project honest:

1. **Label degeneracy.** If almost all runs either succeed or fail immediately,
   `R_t` is trivially predictable from task identity alone and nothing is learned
   about trajectories.
2. **Task-difficulty shortcut.** If `R_t` is fully explained by a static
   task-difficulty prior, the trajectory adds nothing. Phase 3 must include a
   task-prior-only baseline to detect this.
3. **Leakage.** Any feature derived from steps after `t`, or from the final patch,
   invalidates the result. Prefix discipline is enforced in the schema and must be
   enforced in feature extraction.
4. **Harness idiosyncrasy.** If results hold for exactly one agent scaffold, the
   quantity is an artifact of that scaffold, not a property of agents.

## 5. Non-goals for Phase 0

- No model training.
- No paid API calls, no API keys.
- No web UI, no service, no SaaS.
- No large dataset downloads, no committed generated data.
- No fabricated numbers anywhere in docs or code.

## 6. Open TODOs

- TODO(spec): fix the `R_t^(k)` recovery definition (see 2.1).
- TODO(spec): define the intervention action set `A` and per-action cost model.
- TODO(spec): pre-register H2's effect-size threshold.
- TODO(spec): decide the unit of evaluation (per-step, per-run, per-task) and the
  grouping used for cross-validation to avoid task leakage across folds.
- TODO(spec): decide how runs that hit the harness budget without a verdict are
  labelled (failure vs. censored observation).
