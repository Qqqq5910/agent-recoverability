"""agent-recoverability: estimating recoverability of autonomous coding agents.

Phase 0 exposes the data schema only. No models, no predictors, no I/O.
See ``docs/research_spec.md`` for the research specification.
"""

from recoverability.schema import (
    SCHEMA_VERSION,
    EventType,
    InterventionAction,
    RunRecord,
    SchemaError,
    StepRecord,
)

__version__ = "0.0.0"

__all__ = [
    "SCHEMA_VERSION",
    "EventType",
    "InterventionAction",
    "RunRecord",
    "SchemaError",
    "StepRecord",
    "__version__",
]
