"""Tests for the ingestion plumbing: manifest, summary, and the S3 listing parser.

Network access is never exercised here; the HTTP layer is stubbed.
"""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest

from recoverability.ingest.manifest import SourceManifestEntry, sha256_bytes, write_manifest
from recoverability.ingest.s3 import ObjectStoreError, PublicS3Client
from recoverability.schema import SCHEMA_VERSION

REPO_ROOT = Path(__file__).resolve().parents[1]


def _load_script():
    """Import scripts/ingest_phase1a.py, which is not an installed module."""
    path = REPO_ROOT / "scripts" / "ingest_phase1a.py"
    spec = importlib.util.spec_from_file_location("ingest_phase1a", path)
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    sys.modules["ingest_phase1a"] = module
    spec.loader.exec_module(module)
    return module


# --- Manifest -------------------------------------------------------------


def _entry(**overrides) -> SourceManifestEntry:
    base = dict(
        source_id="src",
        source_repository="https://github.com/example/repo",
        source_ref="submission-ref",
        source_path="s3://bucket/a.traj.json",
        format="traj.json",
        license_status="unverified",
        agent_name="mini-SWE-agent",
        model_name="m",
        benchmark_split="SWE-bench_Verified",
        sha256="deadbeef",
    )
    base.update(overrides)
    return SourceManifestEntry(**base)


def test_manifest_round_trips(tmp_path):
    path = tmp_path / "source_manifest.jsonl"
    write_manifest([_entry(source_path="s3://bucket/b.json"), _entry()], path)
    lines = path.read_text(encoding="utf-8").strip().split("\n")
    assert len(lines) == 2
    first = json.loads(lines[0])
    assert first["source_path"] == "s3://bucket/a.traj.json"
    assert first["license_status"] == "unverified"


def test_manifest_order_is_stable(tmp_path):
    a, b = tmp_path / "a.jsonl", tmp_path / "b.jsonl"
    e1, e2 = _entry(source_path="s3://x/1"), _entry(source_path="s3://x/2")
    write_manifest([e1, e2], a)
    write_manifest([e2, e1], b)
    assert a.read_text(encoding="utf-8") == b.read_text(encoding="utf-8")


def test_reproducibility_key_ignores_download_time():
    """A rerun that fetches identical bytes must produce an identical key."""
    assert (
        _entry(downloaded_at="2026-01-01T00:00:00+00:00").reproducibility_key()
        == _entry(downloaded_at="2026-09-21T12:00:00+00:00").reproducibility_key()
    )


def test_reproducibility_key_tracks_content():
    assert _entry(sha256="aaa").reproducibility_key() != _entry(sha256="bbb").reproducibility_key()


def test_sha256_is_stable():
    assert sha256_bytes(b"abc") == sha256_bytes(b"abc")
    assert sha256_bytes(b"abc") != sha256_bytes(b"abd")


def test_license_status_is_not_guessed():
    """Phase 1A records 'unverified' rather than asserting a license."""
    module = _load_script()
    assert module.LICENSE_STATUS == "unverified"


# --- S3 listing parser ----------------------------------------------------

_PAGE_1 = """<?xml version="1.0" encoding="UTF-8"?>
<ListBucketResult xmlns="http://s3.amazonaws.com/doc/2006-03-01/">
  <IsTruncated>true</IsTruncated>
  <NextContinuationToken>tok</NextContinuationToken>
  <Contents><Key>p/a.traj.json</Key></Contents>
  <Contents><Key>p/b.traj.json</Key></Contents>
</ListBucketResult>"""

_PAGE_2 = """<?xml version="1.0" encoding="UTF-8"?>
<ListBucketResult xmlns="http://s3.amazonaws.com/doc/2006-03-01/">
  <IsTruncated>false</IsTruncated>
  <Contents><Key>p/c.traj.json</Key></Contents>
</ListBucketResult>"""


def test_listing_follows_continuation_tokens(monkeypatch):
    pages = iter([_PAGE_1.encode(), _PAGE_2.encode()])
    seen: list[str] = []

    def fake_get(self, url: str) -> bytes:
        seen.append(url)
        return next(pages)

    monkeypatch.setattr(PublicS3Client, "_get", fake_get)
    keys = list(PublicS3Client("bucket").list_keys("p/"))
    assert keys == ["p/a.traj.json", "p/b.traj.json", "p/c.traj.json"]
    assert "continuation-token=tok" in seen[1]


def test_unparseable_listing_raises(monkeypatch):
    monkeypatch.setattr(PublicS3Client, "_get", lambda self, url: b"<not xml")
    with pytest.raises(ObjectStoreError):
        list(PublicS3Client("bucket").list_keys("p/"))


# --- Summary --------------------------------------------------------------


@pytest.fixture
def runs():
    module = _load_script()
    from recoverability.adapters.mini_swe_agent import MiniSweAgentAdapter

    raw = json.loads(
        (Path(__file__).parent / "fixtures" / "mini_swe_agent_synthetic.json").read_text("utf-8")
    )
    adapter = MiniSweAgentAdapter()
    return module, [adapter.parse_run(raw, verdict=True), adapter.parse_run(raw, verdict=False)]


def test_summary_counts_are_aggregate(runs):
    module, parsed = runs
    summary = module.build_summary(parsed, [_entry()], n_malformed=2)
    assert summary["n_runs"] == 2
    assert summary["n_success"] == 1
    assert summary["n_failure"] == 1
    assert summary["n_unknown_verdict"] == 0
    assert summary["n_steps"] == 10
    assert summary["n_test_runs"] == 4
    assert summary["n_error_observations"] == 2
    assert summary["n_runs_with_error"] == 2
    assert summary["n_malformed_skipped"] == 2
    assert summary["schema_version"] == SCHEMA_VERSION
    assert summary["recovery_labels_computed"] is False


def test_summary_contains_no_trajectory_text(runs):
    """The summary is committed, so it must carry no raw observation text."""
    module, parsed = runs
    blob = json.dumps(module.build_summary(parsed, [_entry()], n_malformed=0))
    for forbidden in ("pkg\nsetup.py", "diff --git", "1 failed, 2 passed", "THOUGHT"):
        assert forbidden not in blob
    assert "instance_id" not in blob
    assert "synthetic__pkg-0001" not in blob


def test_summary_is_json_serialisable(runs):
    module, parsed = runs
    json.dumps(module.build_summary(parsed, [_entry()], n_malformed=0))


# --- Committed artifacts --------------------------------------------------


def test_committed_summary_matches_schema_version():
    """If the real summary exists, it must not be stale w.r.t. the schema."""
    path = REPO_ROOT / "docs" / "artifacts" / "phase1a_ingestion_summary.json"
    if not path.exists():
        pytest.skip("ingestion has not been run in this checkout")
    summary = json.loads(path.read_text(encoding="utf-8"))
    assert summary["schema_version"] == SCHEMA_VERSION
    assert summary["recovery_labels_computed"] is False
    assert summary["n_runs"] >= 20


def test_processed_runs_are_not_committed():
    """data/processed must stay out of git."""
    import subprocess

    result = subprocess.run(
        ["git", "ls-files", "data/processed", "data/raw"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.stdout.strip() == ""
