"""Fetch per-instance benchmark verdicts, cached on disk.

The verdict is the only authority on whether a run succeeded. It is fetched
separately from the trajectory and joined at the run level, so a verdict can
never reach a :class:`~recoverability.schema.StepRecord`.
"""

from __future__ import annotations

import json
import urllib.request
from pathlib import Path

__all__ = ["fetch_verdicts"]

_USER_AGENT = "agent-recoverability (research ingestion)"


def fetch_verdicts(url: str, cache: Path, *, offline: bool = False) -> dict[str, bool]:
    """Return ``task_id -> resolved``, caching the raw payload at ``cache``.

    Only entries with a genuine boolean ``resolved`` are kept: an instance whose
    verdict is missing or malformed is left absent rather than defaulted to
    ``False``, so the caller counts it as a missing verdict instead of silently
    treating an unknown outcome as a failure.
    """
    if cache.exists():
        payload = cache.read_bytes()
    elif offline:
        raise FileNotFoundError(f"no cached verdicts at {cache} and --offline was given")
    else:
        request = urllib.request.Request(url, headers={"User-Agent": _USER_AGENT})
        with urllib.request.urlopen(request, timeout=120) as response:
            payload = response.read()
        cache.parent.mkdir(parents=True, exist_ok=True)
        cache.write_bytes(payload)

    details = json.loads(payload)
    if not isinstance(details, dict):
        raise ValueError(f"expected a JSON object of instances, got {type(details).__name__}")

    verdicts: dict[str, bool] = {}
    for instance_id, record in details.items():
        resolved = record.get("resolved") if isinstance(record, dict) else None
        if isinstance(resolved, bool):
            verdicts[str(instance_id)] = resolved
    return verdicts
