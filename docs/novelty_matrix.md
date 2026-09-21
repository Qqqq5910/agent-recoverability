# Novelty Matrix / Related Work

**Epistemic status: unverified placeholders.** The rows below are reserved slots
for work that has been *named* to us as potentially related. Nothing in this table
has been read and verified against a primary source inside this repository. No
reported results are reproduced here, and none are invented.

Rule for this file: a cell is either (a) a claim traceable to a primary source
that a contributor has actually read, with a link, or (b) `TODO`. There is no
third option. Do not fill cells from titles, abstracts, or hearsay.

---

## Matrix

| Work | Setting | Input | Prediction target | Runtime or training-time | Post-failure or online | Counterfactual intervention estimation | Difference from our work |
| --- | --- | --- | --- | --- | --- | --- | --- |
| **AgentForesight** | TODO | TODO | TODO | TODO | TODO | TODO | TODO — confirm whether it predicts eventual success from a prefix or forecasts next-step errors |
| **Recovery-Bench** | TODO | TODO | TODO | TODO | TODO | TODO | TODO — confirm whether it is a benchmark of recovery *ability* (given a broken state) rather than a predictor of recovery *probability* |
| **ERR / "Recoverability Has a Law"** | TODO | TODO | TODO | TODO | TODO | TODO | TODO — confirm whether the claimed regularity is descriptive/aggregate rather than a per-trajectory runtime estimate |
| **RAIL / Recoverability-aware Rollout Intervention Learning** | TODO | TODO | TODO | TODO | TODO | TODO | TODO — confirm whether interventions are learned during training/rollouts rather than estimated as a deployment-time counterfactual |
| **Recoverability as a System Primitive** | TODO | TODO | TODO | TODO | TODO | TODO | TODO — confirm whether it is a systems/position framing rather than an empirical estimator |
| **This work (agent-recoverability)** | autonomous coding agents on benchmark tasks with programmatic verdicts | trajectory **prefix** only (`τ_{1:t}`), no future information | `R_t = P(eventual success \| prefix, continue)`; later `R_t^(k)` and `IV_t(a)` | runtime estimation; training only of small predictors in later phases | **online**, mid-trajectory | planned (Phase 5, checkpoint branching); **not** attempted in Phases 0-4 | — |

## Column semantics

- **Setting** — agent type, task domain, how success is decided.
- **Input** — exactly what the method sees: full trajectory, prefix, final state,
  static task description, code diff.
- **Prediction target** — the quantity estimated, as a formula where possible.
- **Runtime or training-time** — is the method used during a live run, or offline
  to improve an agent?
- **Post-failure or online** — does it analyse a finished/failed run, or estimate
  mid-flight?
- **Counterfactual intervention estimation** — does it estimate what *would*
  happen under an alternative action, or only score the observed trajectory?
- **Difference from our work** — the specific axis of non-overlap, written as a
  falsifiable statement, not as a marketing claim.

## Neighbouring literature to survey (also unverified here)

Categories, not claims. Each needs the same treatment as the rows above.

- LLM/agent **failure taxonomies** and post-hoc failure attribution.
- **Process reward models** and step-level verifiers for reasoning traces.
- **Value functions / critics** over agent states in RL-style agent training.
- **Early-exit and abstention** work: knowing when to stop or defer.
- **Uncertainty calibration** for LLM outputs (Brier/ECE methodology).
- **Learning to defer / human-AI handoff** policies, which is the decision-theory
  side of `IV_t(a)`.
- **Off-policy evaluation** for estimating counterfactual policy value from logs.

## Positioning claim (to be defended, not assumed)

The intended contribution is the combination of: (1) a **prefix-conditioned**,
(2) **calibrated probability** of (3) **eventual benchmark success under
non-intervention**, for (4) **coding agents**, evaluated (5) **online at arbitrary
`t`**, with (6) an explicit path to **counterfactual intervention value**.

If any existing work covers that combination, this project should either narrow
its claim or become a replication and extension. Resolving that is the first
Phase-0 literature task.

## TODOs

- TODO(rw): locate and read a primary source for each placeholder row; record
  venue, year, link, and artifact availability.
- TODO(rw): for each row, fill every cell or explicitly mark it "not applicable".
- TODO(rw): flag any row whose work already subsumes the positioning claim above.
- TODO(rw): add a `related_work.bib` once at least one source is verified.
- TODO(rw): record which related works release usable trajectory data, since that
  feeds Phase 1 ingestion.
