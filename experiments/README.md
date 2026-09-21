# experiments/

Experiment definitions and runnable entry points. One directory per experiment.

## Status

Phase 0: empty by design. No experiment has been run, so no numbers exist
anywhere in this repository.

## Intended layout

```
experiments/
  <phase>_<short_name>/
    config.yaml     # data slice, split, baseline, metrics, seed
    run.py          # entry point; writes into results/<experiment_id>/
    README.md       # question, setup, what would falsify the hypothesis
```

## Rules

- An experiment declares its hypothesis (H1/H2/H3) and its falsification
  condition *before* it is run.
- Configs are committed; outputs are not (they go to `results/`, untracked).
- Seeds are fixed and recorded. Split definitions are recorded by task ID.
- No API keys. The generic-LLM-judge baseline is deferred and, when it lands,
  stays opt-in, off by default, and documented as a cost.
- Reruns must be possible from the committed config plus a documented dataset
  fingerprint.

## TODO

- [ ] TODO: choose the config format and write the first experiment skeleton.
- [ ] TODO: fix the train/validation/test split policy (task-level, no run-level
      leakage across splits).
- [ ] TODO: decide how to handle multiple runs of the same task by the same agent.
