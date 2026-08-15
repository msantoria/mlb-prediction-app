"""Canonical aggregate projection payloads."""

from .aggregator import (
    aggregate_projection_payload,
    summarize_values,
)
from .contracts import (
    CANONICAL_PROJECTION_SCHEMA_VERSION,
    CanonicalProjectionPayload,
    MetricProjection,
    PlayerProjection,
    ProjectionDiagnostics,
    StatisticalSummary,
    TeamProjection,
)
from .pitcher_appearance_history import (
    SCHEMA_VERSION as CANONICAL_PITCHER_APPEARANCE_HISTORY_VERSION,
    materialize_canonical_pitcher_appearance_history,
)
from .pitcher_typical_role_evidence import (
    SCHEMA_VERSION as CANONICAL_PITCHER_TYPICAL_ROLE_EVIDENCE_VERSION,
    materialize_canonical_pitcher_role_evidence,
)

from .serialization import (
    projection_payload_to_dict,
)
from .validation import (
    ProjectionPayloadValidation,
    validate_projection_payload,
)

__all__ = [
    "CANONICAL_PITCHER_APPEARANCE_HISTORY_VERSION",
    "CANONICAL_PITCHER_TYPICAL_ROLE_EVIDENCE_VERSION",
    "materialize_canonical_pitcher_appearance_history",
    "materialize_canonical_pitcher_role_evidence",
    "CANONICAL_PROJECTION_SCHEMA_VERSION",
    "CanonicalProjectionPayload",
    "MetricProjection",
    "PlayerProjection",
    "ProjectionDiagnostics",
    "ProjectionPayloadValidation",
    "StatisticalSummary",
    "TeamProjection",
    "aggregate_projection_payload",
    "projection_payload_to_dict",
    "summarize_values",
    "validate_projection_payload",
    "CANONICAL_PLAYER_PROJECTION_ROWS_VERSION",
    "canonical_player_projection_rows",
    "CANONICAL_PLAYER_IDENTITY_ENRICHMENT_VERSION",
    "enrich_canonical_player_projection_rows",
    "DRAFTKINGS_SLATE_SCHEMA_VERSION",
    "DraftKingsSlate",
    "DraftKingsSlatePlayer",
    "draftkings_slate_to_dict",
    "ingest_draftkings_salary_csv",
    "DRAFTKINGS_PROJECTION_MATCH_SCHEMA_VERSION",
    "match_canonical_projections_to_draftkings",
]

from .player_rows import (
    CANONICAL_PLAYER_PROJECTION_ROWS_VERSION,
    canonical_player_projection_rows,
)

from .player_identity import (
    CANONICAL_PLAYER_IDENTITY_ENRICHMENT_VERSION,
    enrich_canonical_player_projection_rows,
)

from .draftkings_slate import (
    DRAFTKINGS_SLATE_SCHEMA_VERSION,
    DraftKingsSlate,
    DraftKingsSlatePlayer,
    draftkings_slate_to_dict,
    ingest_draftkings_salary_csv,
)

from .draftkings_matching import (
    DRAFTKINGS_PROJECTION_MATCH_SCHEMA_VERSION,
    match_canonical_projections_to_draftkings,
)
