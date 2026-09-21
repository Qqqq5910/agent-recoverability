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
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

__all__ = ["SourceManifestEntry", "sha256_bytes", "write_manifest"]


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


def write_manifest(entries: list[SourceManifestEntry], path: Path) -> None:
    """Write ``entries`` as JSON Lines, sorted for a stable diff."""
    path.parent.mkdir(parents=True, exist_ok=True)
    ordered = sorted(entries, key=lambda entry: (entry.source_id, entry.source_path))
    with path.open("w", encoding="utf-8", newline="\n") as handle:
        for entry in ordered:
            handle.write(json.dumps(entry.to_dict(), ensure_ascii=False, sort_keys=True) + "\n")
