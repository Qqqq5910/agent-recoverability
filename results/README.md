# results/

Untracked output directory for metrics, figures, and run logs. **Nothing here is
committed** except this README (see `.gitignore`).

## Status

Phase 0: empty. No result has been produced. Any number appearing in this
repository's documentation today is illustrative notation, not a measurement.

## Intended layout

```
results/
  <experiment_id>/
    metrics.json    # AUROC, AUPRC, Brier, ECE, lead time
    predictions.csv # per-prefix predictions, for re-analysis
    figures/
    run.log         # environment, seed, dataset fingerprint, git commit
```

## Rules

- Every result records: git commit, dataset fingerprint, seed, Python version.
- Metrics are reported with uncertainty (bootstrap CI) or not reported at all.
- Negative and null results are kept, not deleted.
- Numbers are promoted into `docs/` only after the experiment is reproducible
  from a committed config.

## TODO

- [ ] TODO: define the `metrics.json` key schema alongside the first baseline.
- [ ] TODO: decide the bootstrap procedure and CI level for reported metrics.
- [ ] TODO: decide whether a small curated results summary is worth committing
      later, and under what provenance requirements.
