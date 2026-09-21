"""Download a small sample of public mini-SWE-agent trajectories and ingest them.

Usage::

    python scripts/ingest_phase1a.py --limit 40

Writes, all gitignored except the manifest and summary:

    data/raw/<source_id>/<instance_id>.traj.json   third-party artifacts
    data/raw/<source_id>/per_instance_details.json benchmark verdicts
    data/source_manifest.jsonl                     provenance (committed)
    data/processed/phase1a_runs.jsonl              parsed runs
    docs/artifacts/phase1a_ingestion_summary.json  aggregate only (committed)

No paid API is called. All inputs are public, unauthenticated artifacts.
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import sys
from collections import Counter
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "src"))

from recoverability.adapters.base import MalformedRecordError  # noqa: E402
from recoverability.adapters.mini_swe_agent import MiniSweAgentAdapter  # noqa: E402
from recoverability.ingest.manifest import (  # noqa: E402
    SourceManifestEntry,
    sha256_bytes,
    write_manifest,
)
from recoverability.ingest.s3 import ObjectStoreError, PublicS3Client  # noqa: E402
from recoverability.ingest.sources import MINI_SWE_AGENT_V1 as SRC  # noqa: E402
from recoverability.ingest.verdicts import fetch_verdicts  # noqa: E402
from recoverability.schema import SCHEMA_VERSION, ActionKind, ObservationStatus  # noqa: E402

SUBMISSION = SRC.submission
BUCKET = SRC.bucket
TRAJ_PREFIX = SRC.traj_prefix
EXPERIMENTS_REPO = SRC.experiments_repo
VERDICT_URL = SRC.verdict_url

SOURCE_ID = SRC.source_id
AGENT_NAME = SRC.agent_name
MODEL_NAME = SRC.model_name
BENCHMARK_SPLIT = SRC.benchmark_split
LICENSE_STATUS = SRC.license_status


def select_keys(client: PublicS3Client, verdicts: dict[str, bool], limit: int) -> list[str]:
    """Pick keys deterministically, balancing resolved and unresolved instances.

    Balancing is selection only: no trajectory or verdict is modified. If the
    source has fewer of one class than requested, the shortfall is accepted
    rather than padded.
    """
    keys = sorted(k for k in client.list_keys(TRAJ_PREFIX) if k.endswith(".traj.json"))

    resolved: list[str] = []
    unresolved: list[str] = []
    unknown: list[str] = []
    for key in keys:
        instance_id = Path(key).name.removesuffix(".traj.json")
        verdict = verdicts.get(instance_id)
        if verdict is True:
            resolved.append(key)
        elif verdict is False:
            unresolved.append(key)
        else:
            unknown.append(key)

    half = limit // 2
    picked = resolved[:half] + unresolved[: limit - half]
    if len(picked) < limit:
        picked += unknown[: limit - len(picked)]
    return sorted(picked)


def build_summary(
    runs: list[Any], manifest: list[SourceManifestEntry], n_malformed: int
) -> dict[str, Any]:
    """Aggregate metadata only. No trajectory text may enter this dict."""
    action_counts: Counter[str] = Counter()
    status_counts: Counter[str] = Counter()
    termination_counts: Counter[str] = Counter()
    error_signatures: Counter[str] = Counter()

    n_steps = 0
    n_runs_with_error = 0
    for run in runs:
        termination_counts[run.termination_reason.value] += 1
        has_error = False
        for step in run.steps:
            n_steps += 1
            action_counts[step.action_kind.value] += 1
            status_counts[step.observation_status.value] += 1
            if step.observation_status is ObservationStatus.ERROR:
                has_error = True
                if step.error_signature:
                    error_signatures[step.error_signature] += 1
        n_runs_with_error += int(has_error)

    return {
        "schema_version": SCHEMA_VERSION,
        "phase": "1A",
        "n_runs": len(runs),
        "n_success": sum(1 for r in runs if r.final_success is True),
        "n_failure": sum(1 for r in runs if r.final_success is False),
        "n_unknown_verdict": sum(1 for r in runs if r.final_success is None),
        "n_steps": n_steps,
        "n_error_observations": status_counts.get(ObservationStatus.ERROR.value, 0),
        "n_test_runs": action_counts.get(ActionKind.TEST_RUN.value, 0),
        "n_runs_with_error": n_runs_with_error,
        "n_malformed_skipped": n_malformed,
        "source_ids": sorted({entry.source_id for entry in manifest}),
        "action_kind_counts": dict(sorted(action_counts.items())),
        "observation_status_counts": dict(sorted(status_counts.items())),
        "termination_reason_counts": dict(sorted(termination_counts.items())),
        "error_signature_counts": dict(sorted(error_signatures.items())),
        "recovery_labels_computed": False,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--limit", type=int, default=40, help="number of runs to ingest")
    parser.add_argument("--offline", action="store_true", help="use only already-cached raw files")
    args = parser.parse_args()

    raw_dir = REPO_ROOT / "data" / "raw" / SOURCE_ID
    raw_dir.mkdir(parents=True, exist_ok=True)
    client = PublicS3Client(BUCKET)

    try:
        verdicts = fetch_verdicts(VERDICT_URL, raw_dir / "per_instance_details.json")
    except (OSError, ValueError) as error:
        print(f"FATAL: could not fetch benchmark verdicts: {error}", file=sys.stderr)
        return 1
    print(f"verdicts: {len(verdicts)} instances")

    if args.offline:
        keys = [
            f"{TRAJ_PREFIX}/{p.name.removesuffix('.traj.json')}/{p.name}"
            for p in sorted(raw_dir.glob("*.traj.json"))
        ][: args.limit]
    else:
        try:
            keys = select_keys(client, verdicts, args.limit)
        except ObjectStoreError as error:
            print(f"FATAL: could not list trajectories: {error}", file=sys.stderr)
            return 1
    print(f"selected {len(keys)} trajectories")

    adapter = MiniSweAgentAdapter(agent_name=AGENT_NAME, model_name=MODEL_NAME)
    now = dt.datetime.now(dt.UTC).isoformat(timespec="seconds")

    runs = []
    manifest: list[SourceManifestEntry] = []
    n_malformed = 0

    for key in keys:
        instance_id = Path(key).name.removesuffix(".traj.json")
        local = raw_dir / f"{instance_id}.traj.json"
        if local.exists():
            payload = local.read_bytes()
        else:
            try:
                payload = client.get_object(key)
            except ObjectStoreError as error:
                print(f"  skip {instance_id}: {error}", file=sys.stderr)
                continue
            local.write_bytes(payload)

        manifest.append(
            SourceManifestEntry(
                source_id=SOURCE_ID,
                source_repository=EXPERIMENTS_REPO,
                source_ref=SUBMISSION,
                source_path=f"s3://{BUCKET}/{key}",
                format="mini-swe-agent traj.json (messages + info)",
                license_status=LICENSE_STATUS,
                agent_name=AGENT_NAME,
                model_name=MODEL_NAME,
                benchmark_split=BENCHMARK_SPLIT,
                sha256=sha256_bytes(payload),
                n_bytes=len(payload),
                downloaded_at=now,
                notes="verdict from experiments/per_instance_details.json",
            )
        )

        try:
            raw = json.loads(payload)
            runs.append(adapter.parse_run(raw, verdict=verdicts.get(instance_id)))
        except (json.JSONDecodeError, MalformedRecordError) as error:
            n_malformed += 1
            print(f"  malformed {instance_id}: {error}", file=sys.stderr)

    if not runs:
        print("FATAL: no runs parsed; refusing to write a summary", file=sys.stderr)
        return 1

    write_manifest(manifest, REPO_ROOT / "data" / "source_manifest.jsonl")

    processed = REPO_ROOT / "data" / "processed" / "phase1a_runs.jsonl"
    processed.parent.mkdir(parents=True, exist_ok=True)
    with processed.open("w", encoding="utf-8", newline="\n") as handle:
        for run in runs:
            handle.write(json.dumps(run.to_json_dict(), ensure_ascii=False) + "\n")

    summary = build_summary(runs, manifest, n_malformed)
    summary_path = REPO_ROOT / "docs" / "artifacts" / "phase1a_ingestion_summary.json"
    summary_path.parent.mkdir(parents=True, exist_ok=True)
    summary_path.write_text(
        json.dumps(summary, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )

    print(json.dumps(summary, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
