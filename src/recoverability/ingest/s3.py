"""Minimal anonymous reader for a public S3 bucket.

The project core is dependency-free, so this speaks the REST API over
``urllib`` rather than pulling in ``boto3``. Only unauthenticated GET and
ListObjectsV2 are supported, which is all a public artifact bucket needs.
"""

from __future__ import annotations

import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from collections.abc import Iterator
from typing import Final

__all__ = ["ObjectStoreError", "PublicS3Client"]

_NS: Final = {"s3": "http://s3.amazonaws.com/doc/2006-03-01/"}
_USER_AGENT: Final = "agent-recoverability/phase1a (+public-artifact-ingest)"


class ObjectStoreError(RuntimeError):
    """Raised when a listing or download fails."""


class PublicS3Client:
    """Read objects from one public bucket, unauthenticated."""

    def __init__(self, bucket: str, *, endpoint: str | None = None, timeout: float = 60.0) -> None:
        self.bucket = bucket
        self.endpoint = endpoint or f"https://{bucket}.s3.amazonaws.com"
        self.timeout = timeout

    def _get(self, url: str) -> bytes:
        request = urllib.request.Request(url, headers={"User-Agent": _USER_AGENT})
        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as response:
                return response.read()
        except urllib.error.HTTPError as error:  # pragma: no cover - network path
            raise ObjectStoreError(f"HTTP {error.code} for {url}") from error
        except urllib.error.URLError as error:  # pragma: no cover - network path
            raise ObjectStoreError(f"network failure for {url}: {error.reason}") from error

    def list_keys(self, prefix: str, *, page_size: int = 1000) -> Iterator[str]:
        """Yield every key under ``prefix``, following continuation tokens."""
        token: str | None = None
        while True:
            query = {"list-type": "2", "prefix": prefix, "max-keys": str(page_size)}
            if token:
                query["continuation-token"] = token
            url = f"{self.endpoint}/?{urllib.parse.urlencode(query)}"
            try:
                root = ET.fromstring(self._get(url).decode("utf-8"))
            except ET.ParseError as error:
                raise ObjectStoreError(f"unparseable listing for {prefix}") from error

            for node in root.findall("s3:Contents/s3:Key", _NS):
                if node.text:
                    yield node.text

            if root.findtext("s3:IsTruncated", default="false", namespaces=_NS) != "true":
                return
            token = root.findtext("s3:NextContinuationToken", namespaces=_NS)
            if not token:
                return

    def get_object(self, key: str) -> bytes:
        """Download one object by key."""
        return self._get(f"{self.endpoint}/{urllib.parse.quote(key)}")
