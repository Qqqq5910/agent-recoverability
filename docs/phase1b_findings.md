# Phase 1B findings — error semantics audit and population characterization

Status: complete. No model was trained, no LLM API was called, and no recovery
label was computed. Machine-readable companions:
`docs/artifacts/phase1b_population_summary.json` and
`docs/artifacts/phase1b_unknown_audit_summary.json`.

## 1. Data source

| Field | Value |
| --- | --- |
| Source | `SWE-bench/experiments`, public S3 bucket `swe-bench-submissions` |
| Submission | `bash-only/20250726_mini-v1.0.0_claude-sonnet-4-20250514` |
| Agent | mini-SWE-agent v1.0.0 (bash-only) |
| Model | `claude-4-sonnet-20250514` |
| Benchmark | SWE-bench Verified |
| Verdicts | `per_instance_details.json`, fetched separately from trajectories |
| License | `unverified` — bucket is publicly readable, redistribution terms not confirmed |
| Schema | 0.2.0 |
| Detector | `error_event_v1` |

No raw trajectory text is committed. `data/raw/**` and `data/processed/**` are
gitignored; the repository carries the manifest, the aggregates, the code and a
synthetic fixture.

## 2. Population accounting

Deterministic and blind to outcome: every trajectory joinable to a per-instance
verdict is analysed, ordered by `task_id`. `deterministic_subset` takes
`task_ids` only — a test asserts the signature cannot see a verdict.

| Quantity | n |
| --- | --- |
| Available trajectories | 500 |
| Available verdicts | 500 |
| Joined runs | 500 |
| Missing trajectory | 0 |
| Missing verdict | 0 |
| Malformed | 0 |
| Excluded, external intervention | 0 |
| **Analysed runs** | **500** |

Nothing was dropped, so no exclusion needed a justification and the accounting
reconciles (asserted in the artifact as `reconciles: true`). Total steps 18,586.

The submission publishes 500 trajectories and 500 verdicts with no gaps, so
trajectory availability cannot be correlated with outcome *within* this
submission. It says nothing about which submissions get published at all; see
threats to validity.

## 3. Error detector v1

Frozen in `docs/error_event_v1.md` before the population was fetched. The audit
that produced it ran on the 40-run smoke sample from Phase 1A and never read a
verdict.

The rule that changed: a non-zero exit belonging to a predicate command
(`grep` finding nothing, and the same family of commands) is `OK`, not `ERROR`.
Signatures were also made semantic, replacing `returncode_N`.

Effect on the same 40 runs, which is the honest measure of how wrong the Phase 1A
detector was:

| | Phase 1A | `error_event_v1` |
| --- | --- | --- |
| OK | 1,091 | 1,115 |
| ERROR | 102 | 81 |
| UNKNOWN | 43 | 40 |

**21 of the original 102 ERROR observations were false positives**, about one in
five. 18 became `OK` (attributable predicate non-zero) and 3 became `UNKNOWN`
(the exit could not be attributed to a single command in an `&&` chain). The
detector was made stricter, and this shrank the error count — the direction that
works against finding errors everywhere.

## 4. UNKNOWN audit

Audited over the full 500-run population rather than only the 40-run sample,
which supersedes the original figure of 43. Per-step detail is in the gitignored
`data/processed/phase1b_unknown_audit.jsonl`; no observation text is committed.

| Reason | n |
| --- | --- |
| `missing_returncode_with_text` | 500 |
| `detector_abstained` | 22 |
| **Total** | **522** |

**No parser bugs.** `n_parser_bugs: 0`, `n_fixed_by_parser_change: 0`.

The 500 are exactly one per run, all on the terminal step, 497 of them `submit`.
This is a property of the format: the harness returns the submission instead of
executing a command, so no return code exists. It stays `UNKNOWN` rather than
being assumed `OK`, as Part B required.

The 22 abstentions did carry a return code. The detector declined to rule
because a non-zero exit behind `&&` or `;` could belong either to a predicate
command or to a genuine failure. That is the precision-first policy working, not
a defect.

## 5. Error × final outcome contingency

All 500 analysed runs. "Has ERROR" means at least one `error_event_v1` event.

| | Has ERROR | No ERROR | Total |
| --- | --: | --: | --: |
| `final_success=True` | 232 | 92 | 324 |
| `final_success=False` | 143 | 33 | 176 |
| **Total** | **375** | **125** | **500** |

Margins sum; no run with a verdict is outside a cell, and no run without one was
folded into a cell (there were none). 1,127 error observations over 3,595 test
runs.

Overall benchmark success rate 324 / 500 = 64.8% (95% CI 60.5–68.9). Run-level
error-event rate 375 / 500 = 75.0% (95% CI 71.0–78.6). Wilson intervals,
standard library only.

| Quantity | Value | 95% CI |
| --- | --- | --- |
| P(error \| success) | 232 / 324 = 71.6% | 66.5–76.2 |
| P(error \| failure) | 143 / 176 = 81.3% | 74.8–86.3 |
| P(success \| error) | 232 / 375 = 61.9% | 56.9–66.6 |
| P(success \| no error) | 92 / 125 = 73.6% | 65.3–80.5 |

Risk difference P(success | error) − P(success | no error) = **−11.7 points**.
This is a **descriptive association**, not a causal effect. Nothing was
randomised and error occurrence is plausibly confounded by task difficulty. The
two confidence intervals overlap.

**The headline number: 71.6% of runs the benchmark resolved contained at least
one observable error event.** Errors are the normal case in successful runs, not
the exception.

## 6. Error-family breakdown

A run is counted once per distinct family it contains, so columns do not sum to
500. Descriptive only; no significance test is applied, and with families this
small none would be interpretable.

| Family | Runs | Success | Failure |
| --- | --: | --: | --: |
| `python_exception` | 313 | 193 | 120 |
| `test_failure` | 179 | 105 | 74 |
| `command_failure` | 35 | 16 | 19 |
| `timeout` | 6 | 3 | 3 |
| `harness_format_error` | 4 | 3 | 1 |
| `patch_failure` | 3 | 2 | 1 |

The two families that dominate are also the two the agent most often survives.
`command_failure` is the only family whose runs fail more often than they
succeed, on 35 runs — too few to lean on.

Positionally, the mean first error arrives at 40.1% of the trajectory (375 runs).
That figure is derived from `total_steps`, which is future information, and is
labelled `OFFLINE ANALYSIS ONLY - NOT PREFIX SAFE` in both the artifact and the
code. A test prevents it from entering the prefix-safe feature surface.

## 7. What this does show

Observable intermediate errors and final task failure are **not** the same event.
232 of 500 runs hit an observable error and were still resolved by the benchmark
— 61.9% of all runs containing an error. A detector that treated "error occurred"
as "run failed" would be wrong about those 232 runs.

The prerequisite for H2 holds: there is a large candidate pool to study, and the
question of what distinguishes the 232 from the 143 is well posed.

## 8. What this does NOT show

**This phase does not establish self-recovery.** It does not show that a
recovery occurred, where it occurred, or that any success was causally related to
the error that preceded it. A run can contain an error, ignore it, and succeed
for unrelated reasons.

It does not show that errors cause failure. It does not prove H2. The −11.7 point
risk difference is an association in one sample with overlapping intervals.

The 232 runs are named `SUCCESS_AFTER_OBSERVED_ERROR` / `recovery_candidate`
throughout, never `self_recovered=True`. `recovery_labels_computed: false` in the
artifact, and `self_recovered_eventually` / `steps_to_recovery` are `None` on
every run, asserted by test.

## 9. Threats to validity

- **One harness, one model, one benchmark.** Every number is conditional on
  mini-SWE-agent v1.0.0 with claude-sonnet-4 on SWE-bench Verified. Phase 1C adds
  a second source to test how much is harness artifact.
- **Publication selection.** The 500 runs are complete within this submission,
  but submissions are published voluntarily; a submission is plausibly published
  because it scored well. 64.8% is this submission's rate, not the agent's.
- **Detector precision over recall.** 522 `UNKNOWN` steps are unclassified, so
  the error rate is a floor. Silent wrong answers at exit 0 are invisible.
- **SWE-bench Verified ceiling.** Tasks are filtered for solvability, so the
  error mix may not resemble open-ended work.
- **Error presence is run-level and binary.** One `grep` failure and forty
  cascading tracebacks both count as "has error".
- **No causal identification.** Task difficulty plausibly drives both error
  occurrence and failure.

## 10. Next step

Phase 1C: ingest a second source (classic SWE-agent `.traj`) under the same
frozen schema and detector, and report how the error rate and family mix move.
That is the test of harness-specific artifact risk. Recovery-point definition
stays frozen until Phase 2; nothing here anticipates it.
