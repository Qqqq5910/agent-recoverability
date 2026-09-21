# Experiment Plan

Phased plan. **Phase 1B (current) produces descriptive statistics only** — no
predictive numbers, no trained model, no recovery label. Each phase lists its entry
condition, deliverable and exit criterion, so the project can be stopped or
redirected on evidence rather than momentum.

Hard constraints for Phases 1-4: no model training beyond small classical models,
no paid API calls, no API keys, no web UI, no SaaS, no large downloads, no
committed generated data.

---

## Phase 1 — Public trajectory ingestion

**Goal.** Turn publicly available agent run logs into normalised `StepRecord`s
(see `src/recoverability/schema.py`) without loss of the fields needed for
labelling.

### Phase 1A — Schema hardening + first source

Status: **schema 0.2.0 frozen for ingestion; one real source parsing.**

Done in 1A:

- Split the schema's single `EventType` into orthogonal `ActionKind` and
  `ObservationStatus`, so a failing test run is expressible (schema 0.2.0).
- Added `termination_reason` and `verdict_source` alongside `final_success`, so
  "the agent said done" and "the benchmark says passed" stay distinct.
  `termination_reason` is the observed reason the run stopped (from the harness
  alone); `final_success` is the benchmark outcome (from a benchmark artifact
  alone). Neither is derived from the other.
- Built the adapter layer (`src/recoverability/adapters/`) with
  `MiniSweAgentAdapter` as the first real adapter; source-specific fields go to
  `extra` rather than widening the schema.
- Ingested a small real sample to a git-ignored JSONL, with a committable
  aggregate summary under `docs/artifacts/` and provenance in
  `data/source_manifest.jsonl`.
- Strengthened prefix-leakage tests, including that `StepRecord.extra` cannot be
  used as a back door for run-level outcome.

Deliberately **not** done in 1A: recovery labels, feature engineering, any
model, any paid API call.

Exit criterion for 1A: one real source parses end to end, the summary contains
both successful and failed runs, and the full test suite plus ruff pass. **Met.**

### Phase 1B — Error semantics audit + population characterization (current)

Status: **`error_event_v1` frozen; 500-run population described.**

Done in 1B:

- Audited every `UNKNOWN` observation by raw message structure, without guessing
  a status. No parser bug was found: the dominant case is the terminal `SUBMIT`
  step, which the harness answers with the submission instead of a return code,
  so it has no return code to read.
- Audited all 102 `ERROR` observations from the 1A sample and found 21 false
  positives, all predicate commands whose non-zero exit is a negative result
  rather than a failure. The detector was tightened, which *reduced* the error
  count.
- Froze the detector as `error_event_v1` (`docs/error_event_v1.md`), blind to the
  benchmark verdict by construction: no function accepts a `RunRecord` or a
  verdict, asserted over the signatures by test.
- Upgraded `error_signature` from `returncode_N` to semantic, path-free and
  timestamp-free signatures, so same-cause failures collapse.
- Ingested the full submission (500 runs) with selection a function of `task_id`
  alone, then reported the 2×2 error-by-outcome table with Wilson intervals in
  `docs/phase1b_findings.md` and
  `docs/artifacts/phase1b_population_summary.json`.

Deliberately **not** done in 1B: recovery labels, any model, any second source,
any causal claim.

Exit criterion for 1B: the detector is frozen before the population is fetched,
the population accounting reconciles with nothing silently dropped, and every
committed proportion carries its numerator and denominator. **Met.**

### Phase 1C — Second source and round-trip guarantees

Remaining work items:

- Inventory public sources of coding-agent trajectories with benchmark verdicts
  (agent scaffold logs, benchmark leaderboard artifacts, released run dumps).
- One adapter per source, mapping raw logs to the schema. Adapters must be pure
  functions over local files; no network access at import time.
- Record per-source provenance: agent, model, harness version, benchmark, license,
  and whether interventions could have occurred.
- Re-run the frozen `error_event_v1` over the second source and report how the
  error rate and family mix move. A large shift is evidence that the Phase 1B
  numbers are harness artifact rather than agent behaviour.

Deliverable: `recoverability/adapters/<source>.py` + a provenance table in
`data/README.md` and machine-readable provenance in
`data/source_manifest.jsonl`. Data itself stays local and git-ignored.

Exit criterion: at least two independent sources ingest into an identical schema,
and a round-trip test proves no required field is silently dropped.

TODO(p1): add the second source (classic SWE-agent `.traj`) to satisfy the
two-source exit criterion and to test harness-specific artifact risk.
TODO(p1): confirm licenses permit derivative labelling; the first source is
recorded as `unverified` until its redistribution terms are checked, rather than
guessed.
TODO(p1): decide storage format (JSONL vs. Parquet) and whether a dependency is
justified for it.

## Phase 2 — Recoverability label construction

**Goal.** Derive `final_success`, `self_recovered_eventually`, `steps_to_recovery`
per run and per error event, following `docs/definitions.md`.

Work items:

- Apply the benchmark verdict as `final_success` (no model-judged success).
- Detect error events; assign signatures; locate recovery points.
- Exclude or truncate runs with external intervention, with reasons logged.
- Report label distribution: base rates, error-event frequency, recovery-distance
  distribution, censoring rate.

Exit criterion: labels are non-degenerate (both classes materially present at
mid-trajectory prefixes) and the labelling script is deterministic and re-runnable
from raw logs.

TODO(p2): resolve the open definitional questions in `research_spec.md` 2.1 and
`definitions.md` before freezing labels.
TODO(p2): manual audit of a random sample of labelled error events, to check the
detector against human reading. Sample size to be fixed in advance.

## Phase 3 — Simple prediction baselines

**Goal.** Establish how much of `R_t` is explainable with trivial signals, before
anything clever is attempted.

Baselines, in increasing order of information used:

| Baseline | Signal | Purpose |
| --- | --- | --- |
| `random` | none | sanity floor |
| `task_prior` | task identity only | detects the task-difficulty shortcut |
| `trajectory_progress` | `step_index`, budget fraction consumed | "how far along" heuristic |
| `error_count` | count of error events so far | the naive failure-detection view |
| `repeated_error_signature` | recurrence of the same signature | the "stuck in a loop" heuristic |
| `logistic_regression` | hand-built prefix features | linear learned baseline |
| `gradient_boosted_trees` | same features | non-linear learned baseline |
| `generic_llm_judge` | prefix text, zero-shot prompt | "can a general model just tell?" |

Rules:

- Features are computed from the prefix only. A leakage test asserts no feature
  changes when future steps are appended.
- Cross-validation is grouped by task (and by repository where applicable) so no
  task appears in both train and test.
- The LLM-judge baseline is deferred to the end of Phase 3 and, given the
  no-paid-API constraint, must run on a locally hosted model or be marked as not
  yet evaluated. Never estimated, never fabricated.

Metrics: **AUROC**, **AUPRC**, **Brier score**, **Expected Calibration Error**.
Report with confidence intervals over grouped folds, plus base rates. AUPRC and
base rate always reported together, since AUPRC is not comparable across
different class balances.

Exit criterion (bears on H1/H2): a clear statement of whether any predictor beats
`trajectory_progress` and `error_count` outside confidence intervals.

## Phase 4 — Early prediction

**Goal.** Quantify how early `R_t` becomes usable.

- Evaluate all Phase-3 predictors at prefix fractions (e.g. 10%, 25%, 50%, 75%)
  and at fixed step offsets, reporting metric-vs-prefix curves.
- Define and measure **early-warning lead time**: steps between the first time a
  predictor's `R_t` crosses a threshold and the run's actual failure point, for
  runs that did fail. Report the full distribution, plus the false-alarm rate at
  the same threshold; lead time without false-alarm rate is meaningless.
- Identify a "point of no return", if one exists, as the prefix position after
  which no recovery is observed in the data.

Exit criterion: lead-time distribution at a stated false-alarm budget, for the
best Phase-3 predictor.

TODO(p4): define lead time against *which* failure point (last error event,
terminal step, or last recoverable step) and freeze it before measuring.

## Phase 5 — Counterfactual checkpoint branching

**Goal.** First empirical estimates of `IV_t(a)`.

- Requires a harness that can **resume from a checkpoint** at step `t`, so that
  multiple continuations share an identical prefix.
- For selected prefixes, run `continue` and each intervention `a` several times to
  estimate both terms of the contrast. Repetition is mandatory because agent
  continuations are stochastic.
- Intervention set `A`, per-action cost, and repetition count must be fixed before
  any run.

Additional metrics introduced here:

- task success rate
- average agent steps
- token / API cost
- false intervention rate (intervened where `IV_t(a) <= 0`)
- unnecessary intervention rate (intervened where the agent would have recovered)

Exit criterion: `IV_t(a)` estimates with uncertainty for at least one
non-trivial `a`, on prefixes where recoverability is genuinely uncertain.

This phase costs compute and breaks the "no expensive execution" constraint of
earlier phases. It must not start before Phases 3-4 justify it.

TODO(p5): confirm which public harness supports deterministic checkpoint resume.
TODO(p5): power analysis for the repetition count, given expected effect sizes.

## Phase 6 — Small Recovery Model

**Goal.** A small trajectory-native predictor of `R_t`, only if Phases 3-4 show
that structure beyond hand-built features is being left on the table.

- Small means small: a compact sequence model over step embeddings, trainable on
  commodity hardware. No large-model training, no fine-tuning of frontier models.
- Must beat every Phase-3 baseline on the same grouped folds, on both ranking and
  calibration, to be worth keeping.

Entry condition: a measured gap between the best classical baseline and an
information-theoretic ceiling estimate. Absent that gap, Phase 6 is skipped.

TODO(p6): define the ceiling estimate procedure.

---

## Evaluation discipline (applies to all phases)

- Metrics reported with grouped cross-validation and confidence intervals.
- Base rates always reported alongside AUPRC.
- Calibration (Brier, ECE) treated as first-class, not an afterthought, since the
  intended use is a decision threshold.
- Leakage tests are part of the test suite, not a manual check.
- Negative results are published in `results/` with the same prominence as
  positive ones.
- Every reported number is reproducible from a committed config plus a local data
  build; no hand-copied numbers.

## Cross-phase TODOs

- TODO(eval): pick the confidence-interval method (bootstrap over task groups is
  the default candidate).
- TODO(eval): define the results file format so `results/` stays machine-readable.
- TODO(infra): add CI running pytest and ruff once the repository is public.
- TODO(infra): decide whether classical baselines justify a scikit-learn
  dependency, and keep it out of the core package if so.
