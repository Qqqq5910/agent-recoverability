"""Source adapters: raw harness artifacts -> :class:`~recoverability.schema.RunRecord`.

Each adapter owns exactly one trajectory format. The schema stays
harness-neutral; anything source-specific goes into ``extra``, subject to the
step-level leakage rule in :mod:`recoverability.adapters.base`.
"""

from recoverability.adapters.base import (
    FORBIDDEN_STEP_EXTRA_KEYS,
    AdapterError,
    MalformedRecordError,
    SourceAdapter,
    assert_no_step_leakage,
)
from recoverability.adapters.mini_swe_agent import MiniSweAgentAdapter

__all__ = [
    "FORBIDDEN_STEP_EXTRA_KEYS",
    "AdapterError",
    "MalformedRecordError",
    "MiniSweAgentAdapter",
    "SourceAdapter",
    "assert_no_step_leakage",
]
