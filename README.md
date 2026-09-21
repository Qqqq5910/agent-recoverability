# agent-recoverability

Estimating **recoverability** of autonomous coding agents: given an unfolding
trajectory, what is the probability that the agent succeeds if left alone?

**Current status: Phase 0 — research specification only.**
No models are trained, no datasets are shipped, no results are claimed.

---

## 1. Problem

Autonomous coding agents (SWE-agent-style loops, IDE agents, CI repair bots) run
for tens to hundreds of steps. During a run they frequently produce *observable
errors*: failing tests, tracebacks, bad patches, wrong file edits, tool misuse.

Today the dominant operational signal is binary and late: the run either ends in
success or it does not. Intermediate errors are treated as either noise (ignored)
or as failure (interrupt / restart). Both are wrong a large fraction of the time,
because agents routinely recover from their own mistakes.

The open problem this repository studies:

> Given an **unfolding** autonomous coding-agent trajectory, can we estimate the
> probability that the agent will succeed if left alone, and eventually estimate
> the **counterfactual value of intervening**?

Formally, the first-stage target is

```
R_t = P(eventual task success | trajectory prefix up to step t, no external intervention)
```

and the longer-term target is the intervention value

```
IV_t(a) = P(success | prefix up to t, intervention = a) - P(success | prefix up to t, continue)
```

## 2. Motivation

- **Interruptions are expensive and often wrong.** Killing a run that would have
  self-recovered wastes the sunk cost of the whole prefix. Letting a doomed run
  continue burns tokens, wall-clock time and reviewer attention.
- **Errors are not failures.** An agent that writes a broken patch and then reads
  the traceback and fixes it has executed a *normal* trajectory, not a failed one.
  Any monitor that fires on "test failed" is measuring the wrong event.
- **Supervision does not scale by watching.** With many concurrent agents, human
  attention has to be *allocated*, which requires a calibrated probability, not a
  binary alarm.
- **Cost/benefit needs a counterfactual.** "Should I step in?" is a decision
  problem. It needs an estimate of what happens if you do *and* if you do not.

## 3. Research questions

- **RQ1 — Predictability.** Can `R_t` be estimated from a partial trajectory
  better than trivial heuristics (progress, error counts) and generic LLM judges?
- **RQ2 — Distinctness.** Is recoverability a different quantity from failure /
  error detection, i.e. do observable errors carry low information about eventual
  success once trajectory context is taken into account?
- **RQ3 — Earliness.** How early in a trajectory does a usable recoverability
  signal appear, and what is the lead time before the point of no return?
- **RQ4 — Intervention value (later phases).** Can counterfactual branching from
  trajectory checkpoints produce usable estimates of `IV_t(a)`?
- **RQ5 — Policy (later phases).** Does a calibrated recoverability-aware
  intervention policy improve the success/cost tradeoff versus always-continue
  and naive error-triggered intervention?

## 4. Hypotheses

- **H1** Recoverability can be predicted from a partial agent trajectory better
  than trivial heuristics and generic LLM judges.
- **H2** Recoverability is distinct from failure detection: an agent can make an
  observable error while still having high probability of autonomous recovery.
- **H3** A calibrated recoverability-aware intervention policy can eventually
  improve the success/cost tradeoff relative to always-continue and naive
  error-triggered intervention.

All three are **stated, not tested**. See `docs/research_spec.md`.

## 5. How this differs from failure detection

| Aspect | Failure detection | Recoverability estimation (this work) |
| --- | --- | --- |
| Question | "Did something go wrong?" | "Will it still end well if untouched?" |
| Target | observable error event at step `t` | `P(eventual success \| prefix_t, continue)` |
| Label source | error present in the step | outcome of the *remaining* trajectory |
| Output | flag | calibrated probability |
| A test failure means | failure | nothing by itself |
| Downstream use | alerting, logging | attention allocation, intervention decisions |
| Counterfactual | not modelled | the eventual goal (`IV_t(a)`) |

An error detector is a function of the present. A recoverability estimator is a
prediction about the future. They can disagree, and the interesting cases are
exactly where they do.

## 6. Planned experimental stages

| Phase | Name | Output |
| --- | --- | --- |
| 1 | Public trajectory ingestion | normalised step records from public agent logs |
| 2 | Recoverability label construction | `final_success`, `self_recovered_eventually`, `steps_to_recovery` |
| 3 | Simple prediction baselines | random / progress / error-count / repeated-signature / LR / GBT / LLM judge |
| 4 | Early prediction | accuracy vs. prefix fraction, early-warning lead time |
| 5 | Counterfactual checkpoint branching | resume-from-checkpoint estimates of `IV_t(a)` |
| 6 | Small Recovery Model | a small trajectory-native predictor, only if Phases 1-4 justify it |

Phase 1 constraints, deliberately: no model training, no paid API calls, no web
UI, no SaaS, no large downloads, no API keys. Details in
`docs/experiment_plan.md`.

## 7. Current status

**Phase 0 / research specification.** This repository currently contains:

- the research spec, definitions, related-work matrix and experiment plan,
- a dependency-free trajectory/label **schema** (`src/recoverability/schema.py`),
- tests for that schema.

There are **no experimental results, no trained models, and no claims of
empirical validation** at this point. Any number appearing in this repository
before Phase 3 is illustrative structure, never a measurement.

## Repository layout

```
docs/          research spec, definitions, novelty matrix, experiment plan
src/           the recoverability package (schema only, for now)
tests/         schema tests
data/          local-only ingested/derived data (git-ignored)
experiments/   experiment configs and runner scripts (Phase 3+)
results/       local-only metric outputs (git-ignored)
```

## Development

```bash
python -m pytest
python -m ruff check .
```

Python >= 3.11. The package itself has no third-party runtime dependencies.

## License

MIT. See `LICENSE`.
