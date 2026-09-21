"""agent-recoverability: estimating recoverability of autonomous coding agents.

Phase 1A exposes the data schema and source adapters. No models, no predictors,
no recovery labelling. See ``docs/research_spec.md`` for the research spec.
"""

from recoverability.schema import (
    SCHEMA_VERSION,
    ActionKind,
    InterventionAction,
    ObservationStatus,
    RunRecord,
    SchemaError,
    StepRecord,
    TerminationReason,
    VerdictSource,
)

__version__ = "0.0.0"

__all__ = [
    "SCHEMA_VERSION",
    "ActionKind",
    "InterventionAction",
    "ObservationStatus",
    "RunRecord",
    "SchemaError",
    "StepRecord",
    "TerminationReason",
    "VerdictSource",
    "__version__",
]
