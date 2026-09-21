"""Ingest the full submission population and characterize observable errors.

Phase 1B. Unlike Phase 1A, selection here is *not* balanced: the analysis set is
every trajectory that can be joined to a per-instance benchmark verdict, ordered
by ``task_id``. No outcome is consulted to decide what is included.

Usage::

    python scripts/ingest_phase1b.py              # full population
    python scripts/ingest_phase1b.py --offline    # reuse cached raw files
    python scripts/ingest_phase1b.py --limit 200  # deterministic subset

Writes, gitignored:

    data/raw/<source_id>/*.traj.json             third-party artifacts
    data/processed/phase1b_runs.jsonl            parsed runs
    data/processed/phase1b_unknown_audit.jsonl   per-step UNKNOWN audit

Writes, committed (aggregate only, no trajectory text):

    data/source_manifest.jsonl
    docs/artifacts/phase1b_population_summary.json
    docs/artifacts/phase1b_unknown_audit_summary.json

No paid API is called. No model is trained. No recovery label is computed.
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
from recoverability.adapters.mini_swe_agent import (  # noqa: E402
    MiniSweAgentAdapter,
    pair_raw_observations,
)
from recoverability.analysis import (  # noqa: E402
    contingency_table,
    error_family_outcomes,
    proportion,
)
from recoverability.audit import (  # noqa: E402
    AuditReason,
    audit_unknown_steps,
    offline_first_error_position,
)
from recoverability.errors import ERROR_DETECTOR_VERSION  # noqa: E402
from recoverability.ingest.manifest import (  # noqa: E402
    SourceManifestEntry,
    sha256_bytes,
    write_manifest,
)
from recoverability.ingest.s3 import ObjectStoreError, PublicS3Client  # noqa: E402
from recoverability.ingest.sources import MINI_SWE_AGENT_V1 as SRC  # noqa: E402
from recoverability.ingest.verdicts import fetch_verdicts  # noqa: E402
from recoverability.population import (  # noqa: E402
    ExclusionReason,
    PopulationAccounting,
    deterministic_subset,
)
from recoverability.schema import (  # noqa: E402
    SCHEMA_VERSION,
    ActionKind,
    ObservationStatus,
    TerminationReason,
)

#: UNKNOWN steps resolved by fixing the adapter during the Phase 1B audit.
#: The audit found no step where a ``<returncode>`` tag existed in the raw
#: record but failed to reach the StepRecord, so no parser change was needed.
N_FIXED_BY_PARSER_CHANGE = 0


def collect_population(
    *,
    client: PublicS3Client,
    verdicts: dict[str, bool],
    raw_dir: Path,
    offline: bool,
    limit: int | None,
) -> tuple[
    list[Any], dict[str, dict[int, str | None]], list[SourceManifestEntry], PopulationAccounting
]:
    """Fetch and parse the population, accounting for every excluded task_id.

    The join is on ``task_id`` and nothing else. ``verdicts`` is passed only so
    the parsed run can carry its benchmark outcome; it is never read to decide
    membership.
    """
    accounting = PopulationAccounting(n_available_verdicts=len(verdicts))

    if offline:
        available = {p.name.removesuffix(".traj.json") for p in raw_dir.glob("*.traj.json")}
        keys = {i: f"{SRC.traj_prefix}/{i}/{i}.traj.json" for i in sorted(available)}
    else:
        listed = sorted(k for k in client.list_keys(SRC.traj_prefix) if k.endswith(".traj.json"))
        keys = {Path(k).name.removesuffix(".traj.json"): k for k in listed}
    accounting.n_available_trajectories = len(keys)

    # Both directions of the join, so neither gap is invisible.
    for task_id in sorted(set(verdicts) - set(keys)):
        accounting.exclude(task_id, ExclusionReason.MISSING_TRAJECTORY)
    for task_id in sorted(set(keys) - set(verdicts)):
        accounting.exclude(task_id, ExclusionReason.MISSING_VERDICT)

    joined = sorted(set(keys) & set(verdicts))
    accounting.n_joined_runs = len(joined)

    selected = deterministic_subset(joined, limit)
    for task_id in sorted(set(joined) - set(selected)):
        accounting.exclude(task_id, ExclusionReason.NOT_IN_SUBSET)
    if limit is not None and len(selected) < len(joined):
        accounting.notes.append(
            f"deterministic subset: first {len(selected)} task_ids in sort order, "
            "chosen before any verdict was read"
        )

    adapter = MiniSweAgentAdapter(agent_name=SRC.agent_name, model_name=SRC.model_name)
    now = dt.datetime.now(dt.UTC).isoformat(timespec="seconds")

    runs: list[Any] = []
    pairings: dict[str, dict[int, str | None]] = {}
    manifest: list[SourceManifestEntry] = []

    for task_id in selected:
        key = keys[task_id]
        local = raw_dir / f"{task_id}.traj.json"
        if local.exists():
            payload = local.read_bytes()
        elif offline:
            accounting.exclude(task_id, ExclusionReason.MISSING_TRAJECTORY)
            continue
        else:
            try:
                payload = client.get_object(key)
            except ObjectStoreError as error:
                accounting.exclude(task_id, ExclusionReason.MISSING_TRAJECTORY)
                print(f"  fetch failed {task_id}: {error}", file=sys.stderr)
                continue
            local.write_bytes(payload)

        manifest.append(
            SourceManifestEntry(
                source_id=SRC.source_id,
                source_repository=SRC.experiments_repo,
                source_ref=SRC.submission,
                source_path=SRC.s3_uri(key),
                format=SRC.trajectory_format,
                license_status=SRC.license_status,
                agent_name=SRC.agent_name,
                model_name=SRC.model_name,
                benchmark_split=SRC.benchmark_split,
                sha256=sha256_bytes(payload),
                n_bytes=len(payload),
                downloaded_at=now,
                notes="verdict from experiments/per_instance_details.json",
            )
        )

        try:
            raw = json.loads(payload)
            run = adapter.parse_run(raw, verdict=verdicts[task_id])
        except (json.JSONDecodeError, MalformedRecordError) as error:
            accounting.exclude(task_id, ExclusionReason.MALFORMED)
            print(f"  malformed {task_id}: {error}", file=sys.stderr)
            continue

        if run.termination_reason is TerminationReason.EXTERNAL_INTERRUPTION:
            accounting.exclude(task_id, ExclusionReason.EXTERNAL_INTERRUPTION)
            continue

        runs.append(run)
        pairings[task_id] = pair_raw_observations(raw.get("messages", []))

    accounting.n_analyzed_runs = len(runs)
    return runs, pairings, manifest, accounting


def build_unknown_audit(
    runs: list[Any], pairings: dict[str, dict[int, str | None]]
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Audit every UNKNOWN observation. Returns per-step records and aggregate."""
    records: list[dict[str, Any]] = []
    for run in runs:
        audited = audit_unknown_steps(run, raw_observations=pairings.get(run.task_id, {}))
        records.extend(record.to_dict() for record in audited)

    reason_counts = Counter(record["audit_reason"] for record in records)
    action_counts = Counter(record["action_kind"] for record in records)
    n_parser_bugs = sum(1 for record in records if record["parser_issue"])
    n_abstained = reason_counts[AuditReason.DETECTOR_ABSTAINED.value]

    summary = {
        "error_detector_version": ERROR_DETECTOR_VERSION,
        "schema_version": SCHEMA_VERSION,
        "n_unknown_total": len(records),
        "reason_counts": dict(sorted(reason_counts.items())),
        "action_kind_counts": dict(sorted(action_counts.items())),
        "n_parser_bugs": n_parser_bugs,
        "n_detector_abstained": n_abstained,
        "n_structural_unknown": len(records) - n_parser_bugs - n_abstained,
        "n_fixed_by_parser_change": N_FIXED_BY_PARSER_CHANGE,
        "n_on_final_step": sum(1 for record in records if record["is_final_step"]),
        "notes": (
            "An UNKNOWN on the terminal SUBMIT step is a property of the format: "
            "the harness returns the submission instead of executing a command, so "
            "no return code exists. It is left UNKNOWN rather than assumed OK. "
            "A DETECTOR_ABSTAINED step did carry a return code; the detector "
            "declined to rule because the non-zero exit could not be attributed "
            "to a single command. That is the precision-first policy, not a defect."
        ),
    }
    return records, summary


def build_population_summary(
    runs: list[Any],
    accounting: PopulationAccounting,
    manifest: list[SourceManifestEntry],
) -> dict[str, Any]:
    """Aggregate-only Phase 1B summary. No trajectory text may enter this dict."""
    table = contingency_table(runs)

    action_counts: Counter[str] = Counter()
    status_counts: Counter[str] = Counter()
    termination_counts: Counter[str] = Counter()
    signature_counts: Counter[str] = Counter()
    n_steps = 0
    first_error_fractions: list[float] = []

    for run in runs:
        termination_counts[run.termination_reason.value] += 1
        for step in run.steps:
            n_steps += 1
            action_counts[step.action_kind.value] += 1
            status_counts[step.observation_status.value] += 1
            if step.error_signature:
                signature_counts[step.error_signature] += 1
        position = offline_first_error_position(run)
        if position and position["first_error_fraction"] is not None:
            first_error_fractions.append(position["first_error_fraction"])

    n_with_error = sum(1 for run in runs if run.has_error_event)
    n_verdict_known = sum(1 for run in runs if run.final_success is not None)

    return {
        "phase": "1B",
        "schema_version": SCHEMA_VERSION,
        "error_detector_version": ERROR_DETECTOR_VERSION,
        "source_id": SRC.source_id,
        "source_ref": SRC.submission,
        "agent_name": SRC.agent_name,
        "model_name": SRC.model_name,
        "benchmark_split": SRC.benchmark_split,
        "license_status": SRC.license_status,
        "n_manifest_entries": len(manifest),
        "selection": {
            "balanced_by_outcome": False,
            "ordering": "task_id ascending",
            "rule": "every trajectory joinable to a per-instance benchmark verdict",
        },
        "population": accounting.to_dict(),
        "outcomes": {
            "n_success": table.n_success,
            "n_failure": table.n_failure,
            "n_unknown_verdict": len(runs) - n_verdict_known,
            "benchmark_success_rate": proportion(table.n_success, n_verdict_known).to_dict(),
        },
        "steps": {
            "n_steps": n_steps,
            "action_kind_counts": dict(sorted(action_counts.items())),
            "observation_status_counts": dict(sorted(status_counts.items())),
            "termination_reason_counts": dict(sorted(termination_counts.items())),
        },
        "error_presence": {
            "n_runs_with_error": n_with_error,
            "n_runs_without_error": len(runs) - n_with_error,
            "run_level_error_rate": proportion(n_with_error, len(runs)).to_dict(),
            "n_error_observations": status_counts.get(ObservationStatus.ERROR.value, 0),
            "n_test_runs": action_counts.get(ActionKind.TEST_RUN.value, 0),
        },
        "contingency_table": table.to_dict(),
        "proportions": {
            "p_error_given_success": table.p_error_given_success().to_dict(),
            "p_error_given_failure": table.p_error_given_failure().to_dict(),
            "p_success_given_error": table.p_success_given_error().to_dict(),
            "p_success_given_no_error": table.p_success_given_no_error().to_dict(),
            "risk_difference_descriptive_only": table.risk_difference(),
            "interval_method": "Wilson score, 95%",
        },
        "error_signature_counts": dict(sorted(signature_counts.items())),
        "error_family_counts": error_family_outcomes(runs),
        "offline_descriptive": {
            "_warning": "OFFLINE ANALYSIS ONLY - NOT PREFIX SAFE",
            "n_runs_with_first_error_position": len(first_error_fractions),
            "mean_first_error_fraction": (
                sum(first_error_fractions) / len(first_error_fractions)
                if first_error_fractions
                else None
            ),
        },
        "recovery_candidates": {
            "n_success_after_observed_error": table.success_with_error,
            "label": "SUCCESS_AFTER_OBSERVED_ERROR",
            "note": (
                "A candidate pool only. This count does not assert that a recovery "
                "occurred, where it occurred, or that the success was related to the "
                "error. The recovery point is not defined until Phase 2."
            ),
        },
        "recovery_labels_computed": False,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="deterministic subset size (default: the full joined population)",
    )
    parser.add_argument("--offline", action="store_true", help="use only already-cached raw files")
    args = parser.parse_args()

    raw_dir = REPO_ROOT / "data" / "raw" / SRC.source_id
    raw_dir.mkdir(parents=True, exist_ok=True)

    try:
        verdicts = fetch_verdicts(
            SRC.verdict_url, raw_dir / "per_instance_details.json", offline=args.offline
        )
    except (OSError, ValueError) as error:
        print(f"FATAL: could not fetch benchmark verdicts: {error}", file=sys.stderr)
        return 1
    print(f"verdicts available: {len(verdicts)}")

    try:
        runs, pairings, manifest, accounting = collect_population(
            client=PublicS3Client(SRC.bucket),
            verdicts=verdicts,
            raw_dir=raw_dir,
            offline=args.offline,
            limit=args.limit,
        )
    except ObjectStoreError as error:
        print(f"FATAL: could not list trajectories: {error}", file=sys.stderr)
        return 1

    if not runs:
        print("FATAL: no runs parsed; refusing to write a summary", file=sys.stderr)
        return 1
    if not accounting.reconciles():
        print("FATAL: population accounting does not reconcile", file=sys.stderr)
        return 1

    processed_dir = REPO_ROOT / "data" / "processed"
    processed_dir.mkdir(parents=True, exist_ok=True)
    with (processed_dir / "phase1b_runs.jsonl").open("w", encoding="utf-8", newline="\n") as handle:
        for run in runs:
            handle.write(json.dumps(run.to_json_dict(), ensure_ascii=False) + "\n")

    audit_records, audit_summary = build_unknown_audit(runs, pairings)
    audit_path = processed_dir / "phase1b_unknown_audit.jsonl"
    with audit_path.open("w", encoding="utf-8", newline="\n") as handle:
        for record in audit_records:
            handle.write(json.dumps(record, ensure_ascii=False, sort_keys=True) + "\n")

    if manifest:
        write_manifest(manifest, REPO_ROOT / "data" / "source_manifest.jsonl")

    artifacts = REPO_ROOT / "docs" / "artifacts"
    artifacts.mkdir(parents=True, exist_ok=True)
    summary = build_population_summary(runs, accounting, manifest)
    for name, payload in (
        ("phase1b_population_summary.json", summary),
        ("phase1b_unknown_audit_summary.json", audit_summary),
    ):
        (artifacts / name).write_text(
            json.dumps(payload, indent=2, ensure_ascii=False, sort_keys=True) + "\n",
            encoding="utf-8",
        )

    table = summary["contingency_table"]
    print(
        f"\nanalyzed {accounting.n_analyzed_runs} runs "
        f"({table['n_success']} success / {table['n_failure']} failure)\n"
        f"  with error:    success {table['success_with_error']:4d}  "
        f"failure {table['failure_with_error']:4d}\n"
        f"  without error: success {table['success_without_error']:4d}  "
        f"failure {table['failure_without_error']:4d}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
