# data/

Local, untracked storage for agent trajectory data. **No third-party trajectory
data is committed.** Only this README and `source_manifest.jsonl` are tracked
(see `.gitignore`).

## Status

Phase 1B: the full submission (500 runs) is ingested.
`scripts/ingest_phase1b.py` fetches raw trajectories into `raw/`, parses them
with the frozen `error_event_v1` detector, and writes `processed/` plus the
manifest; nothing it writes under `raw/` or `processed/` is committed. Selection
is a function of `task_id` alone — no run is included or excluded by its
benchmark verdict.

## Layout

```
data/
  raw/                   # verbatim copies of public trajectory logs, per source
  processed/             # parsed RunRecord/StepRecord JSONL, plus audit detail
  source_manifest.jsonl  # committed provenance, one line per fetched artifact
```

Everything under `processed/` stays local: `phase1a_runs.jsonl`,
`phase1b_runs.jsonl`, and `phase1b_unknown_audit.jsonl` (per-step audit reasons,
which is why it carries no observation text even locally). The committable
aggregates derived from them are
`docs/artifacts/phase1a_ingestion_summary.json`,
`docs/artifacts/phase1b_population_summary.json` and
`docs/artifacts/phase1b_unknown_audit_summary.json`.

## Provenance

`source_manifest.jsonl` records, per artifact: `source_id`,
`source_repository`, `source_ref`, `source_path`, `sha256`, `format`,
`license_status`, plus `downloaded_at` and `n_bytes`.

`downloaded_at` is descriptive only. Reproducibility keys off the immutable
fields (`source_repository` + `source_ref` + `source_path` + `sha256`), which is
what `SourceManifestEntry.reproducibility_key()` returns.

`license_status` is `unverified` unless the redistribution terms have actually
been checked. It is never guessed, and `unverified` is why raw artifacts stay
git-ignored regardless of size.

## Rules

- Public trajectory logs only. No private, scraped, or user-identifying data.
- Raw files are treated as read-only. Parsing never edits `raw/`.
- Every source directory carries a `SOURCE.md` recording origin URL, license,
  retrieval date, commit/version, and any known caveats.
- Downloads are explicit and opt-in: fetch scripts are run by hand, never at
  import time, and are bounded by an explicit run count.
- No synthetic or hand-written "example" trajectories are mixed into real data.
  Synthetic fixtures live in `tests/fixtures/` and are only used by tests.

## TODO

- [x] Canonical on-disk format: JSON Lines, no new dependency.
- [x] First source picked and recorded in `source_manifest.jsonl`.
- [x] Dataset fingerprint: per-artifact `sha256` plus aggregate counts in
      `docs/artifacts/phase1a_ingestion_summary.json`.
- [ ] TODO: verify redistribution terms for the first source and replace
      `license_status="unverified"`.
- [x] Full submission ingested without outcome-based sampling (500 runs).
- [ ] TODO: add a second source (classic SWE-agent `.traj`) for Phase 1C.
