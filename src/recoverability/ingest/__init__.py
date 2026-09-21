"""Download and ingestion plumbing for public trajectory artifacts.

Nothing here calls a paid API, and nothing here writes third-party data
anywhere but ``data/raw`` and ``data/processed``, both gitignored.
"""

from __future__ import annotations

__all__ = ["ObjectStoreError", "PublicS3Client", "SourceManifestEntry", "write_manifest"]

from recoverability.ingest.manifest import SourceManifestEntry, write_manifest
from recoverability.ingest.s3 import ObjectStoreError, PublicS3Client
