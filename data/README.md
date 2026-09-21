# data/

Local, untracked storage for agent trajectory data. **Nothing in this directory
is committed** except this README (see `.gitignore`).

## Status

Phase 0: empty by design. No dataset has been ingested yet.

## Intended layout

```
data/
  raw/         # verbatim copies of public trajectory logs, one dir per source
  interim/     # parsed into RunRecord/StepRecord JSONL, before labelling
  processed/   # labelled datasets used by experiments
```

## Rules

- Public trajectory logs only. No private, scraped, or user-identifying data.
- Raw files are treated as read-only. Parsing never edits `raw/`.
- Every source directory carries a `SOURCE.md` recording origin URL, license,
  retrieval date, commit/version, and any known caveats.
- No large downloads are automated in Phase 0. Phase 1 adds explicit,
  opt-in fetch scripts with size reported up front.
- No synthetic or hand-written "example" trajectories are mixed into real data.

## TODO

- [ ] TODO: decide the canonical on-disk format (JSONL vs Parquet) in Phase 1.
- [ ] TODO: pick the first trajectory source and write its `SOURCE.md`.
- [ ] TODO: document license compatibility for each source before use.
- [ ] TODO: define a dataset fingerprint (hash + counts) for reproducibility.
