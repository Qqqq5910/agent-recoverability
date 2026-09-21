"""Dataset provenance manifest.

The manifest is the one committed record of where third-party data came from.
It holds pointers and checksums, never trajectory content, so it is safe to
commit while the artifacts it describes stay gitignored.

``downloaded_at`` is recorded for auditing only. It is deliberately excluded
from ``reproducibility_key``: a rerun that fetches the same immutable objects
must produce the same key, and a wall-clock timestamp would break that.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from dataclasses import asdict, dataclass, field, replace
from pathlib import Path
from typing import Any

__all__ = ["SourceManifestEntry", "read_manifest", "sha256_bytes", "write_manifest"]


def sha256_bytes(payload: bytes) -> str:
    """Return the hex SHA-256 of ``payload``."""
    return hashlib.sha256(payload).hexdigest()


@dataclass(frozen=True, slots=True)
class SourceManifestEntry:
    """Provenance for one downloaded artifact."""

    source_id: str
    source_repository: str
    source_ref: str
    source_path: str
    format: str
    license_status: str
    agent_name: str
    model_name: str
    benchmark_split: str
    sha256: str | None = None
    n_bytes: int | None = None
    downloaded_at: str | None = None
    notes: str | None = None
    extra: dict[str, Any] = field(default_factory=dict)

    def reproducibility_key(self) -> str:
        """Identity of the artifact, independent of when it was fetched."""
        return "|".join(
            [
                self.source_id,
                self.source_repository,
                self.source_ref,
                self.source_path,
                self.sha256 or "",
            ]
        )

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _key_of(entry: Mapping[str, Any]) -> str:
    """Reproducibility key of a manifest row already parsed from JSON."""
    return "|".join(
        str(entry.get(name) or "")
        for name in (
            "source_id",
            "source_repository",
            "source_ref",
            "source_path",
            "sha256",
        )
    )


def read_manifest(path: Path) -> list[dict[str, Any]]:
    """Read a manifest written by :func:`write_manifest`, or ``[]`` if absent."""
    if not path.exists():
        return []
    with path.open(encoding="utf-8") as handle:
        return [json.loads(line) for line in handle if line.strip()]


def _carry_over_download_times(
    entries: list[SourceManifestEntry], path: Path
) -> list[SourceManifestEntry]:
    """Keep the recorded ``downloaded_at`` for artifacts that have not changed.

    ``downloaded_at`` is provenance, not an experiment input, so re-running
    ingestion over identical bytes should leave the manifest untouched rather
    than producing a 40-line diff that implies the data moved.
    """
    previous = {_key_of(entry): entry.get("downloaded_at") for entry in read_manifest(path)}
    if not previous:
        return entries
    return [
        replace(
            entry,
            downloaded_at=previous.get(entry.reproducibility_key()) or entry.downloaded_at,
        )
        for entry in entries
    ]


def write_manifest(entries: list[SourceManifestEntry], path: Path) -> None:
    """Write ``entries`` as JSON Lines, sorted for a stable diff."""
    path.parent.mkdir(parents=True, exist_ok=True)
    entries = _carry_over_download_times(entries, path)
    ordered = sorted(entries, key=lambda entry: (entry.source_id, entry.source_path))
    with path.open("w", encoding="utf-8", newline="\n") as handle:
        for entry in ordered:
            handle.write(json.dumps(entry.to_dict(), ensure_ascii=False, sort_keys=True) + "\n")
