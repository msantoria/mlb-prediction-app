"""Active-roster bullpen discovery for canonical shadow bootstrap inputs."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Dict, Mapping, Optional, Sequence, Tuple

from .canonical_bullpen_eligibility import (
    enforce_canonical_bullpen_eligibility,
)
from .pregame_pitcher_availability_role_evidence import (
    CanonicalPregamePitcherEvidenceMaterialization,
    materialize_canonical_pregame_pitcher_evidence,
)


CANONICAL_SHADOW_BULLPEN_DISCOVERY_VERSION = (
    "canonical_shadow_bullpen_discovery_v1"
)


def _normalize_identifier(value: Any) -> Optional[str]:
    if value in (None, "") or isinstance(value, bool):
        return None

    try:
        parsed = int(value)
        return str(parsed) if parsed > 0 else None
    except (TypeError, ValueError):
        text = str(value).strip()
        return text or None




def _normalize_identifiers(
    values: Any,
) -> Tuple[str, ...]:
    if values is None:
        return ()

    if isinstance(values, (str, bytes)):
        candidates = (values,)
    elif isinstance(values, Sequence):
        candidates = tuple(values)
    else:
        candidates = (values,)

    result = []
    seen = set()

    for candidate in candidates:
        identifier = _normalize_identifier(
            candidate
        )

        if (
            identifier is not None
            and identifier not in seen
        ):
            result.append(identifier)
            seen.add(identifier)

    return tuple(result)


def _pitcher_identifiers(
    records: Any,
    *,
    starter_id: Any,
) -> Tuple[str, ...]:
    if not isinstance(records, Sequence) or isinstance(
        records,
        (str, bytes),
    ):
        return ()

    normalized_starter = _normalize_identifier(
        starter_id
    )
    ordered = []

    for record in records:
        if not isinstance(record, Mapping):
            continue

        player_type = str(
            record.get("player_type") or ""
        ).strip().lower()

        if player_type != "pitcher":
            continue

        identifier = _normalize_identifier(
            record.get("mlb_player_id")
            or record.get("player_id")
            or record.get("pitcher_id")
            or record.get("id")
        )

        if (
            identifier is None
            or identifier == normalized_starter
            or identifier in ordered
        ):
            continue

        ordered.append(identifier)

    return tuple(ordered)


def _active_roster_usage_evidence(
    records: Any,
    *,
    candidate_pitcher_ids: Sequence[str],
) -> Dict[str, Dict[str, Any]]:
    if not isinstance(records, Sequence) or isinstance(
        records,
        (str, bytes),
    ):
        return {}

    candidates = set(candidate_pitcher_ids)
    evidence = {}

    for record in records:
        if not isinstance(record, Mapping):
            continue

        pitcher_id = _normalize_identifier(
            record.get("mlb_player_id")
            or record.get("player_id")
            or record.get("pitcher_id")
            or record.get("id")
        )

        if (
            pitcher_id is None
            or pitcher_id not in candidates
        ):
            continue

        games_pitched = record.get(
            "season_games_pitched"
        )
        games_started = record.get(
            "season_games_started"
        )
        relief_appearances = record.get(
            "season_relief_appearances"
        )

        if (
            isinstance(games_pitched, bool)
            or isinstance(games_started, bool)
            or isinstance(relief_appearances, bool)
        ):
            continue

        try:
            games_pitched = int(games_pitched)
            games_started = int(games_started)
            relief_appearances = int(
                relief_appearances
            )
        except (TypeError, ValueError):
            continue

        if (
            games_pitched <= 0
            or games_started < 0
            or relief_appearances < 0
            or games_started > games_pitched
            or relief_appearances
            != games_pitched - games_started
        ):
            continue

        if relief_appearances > games_started:
            evidence[pitcher_id] = {
                "status": "eligible",
                "role": "reliever",
                "source": (
                    "mlb_stats_active_roster_"
                    "season_pitching"
                ),
                "reason": (
                    "observed_relief_usage_dominant"
                ),
            }
        else:
            evidence[pitcher_id] = {
                "status": "ineligible",
                "role": "probable_starter",
                "source": (
                    "mlb_stats_active_roster_"
                    "season_pitching"
                ),
                "reason": (
                    "observed_start_usage_dominant"
                ),
            }

    return evidence


@dataclass(frozen=True)
class CanonicalShadowBullpenSideDiscovery:
    team_id: Optional[str] = None
    starter_id: Optional[str] = None
    bullpen_pitcher_ids: Tuple[str, ...] = ()
    eligibility: Optional[Dict[str, Any]] = None
    pregame_evidence: Optional[
        CanonicalPregamePitcherEvidenceMaterialization
    ] = None
    source_record_count: int = 0
    status: str = "unavailable"
    error_type: Optional[str] = None
    error_message: Optional[str] = None

    @property
    def ready(self) -> bool:
        return len(self.bullpen_pitcher_ids) > 0

    def readiness_fields(
        self,
        *,
        side: str,
    ) -> Dict[str, Any]:
        if not self.ready:
            return {}

        return {
            f"{side}_bullpen_pitcher_ids": [
                {"pitcher_id": pitcher_id}
                for pitcher_id in self.bullpen_pitcher_ids
            ]
        }

    def to_diagnostics(self) -> Dict[str, Any]:
        return {
            "status": self.status,
            "ready": self.ready,
            "source": "mlb_stats_active_roster",
            "team_id_present": self.team_id is not None,
            "starter_id_present": (
                self.starter_id is not None
            ),
            "source_record_count": (
                self.source_record_count
            ),
            "validated_pitcher_count": len(
                self.bullpen_pitcher_ids
            ),
            "minimum_pitcher_count": 1,
            "eligibility_status": (
                self.eligibility.get("status")
                if self.eligibility is not None
                else None
            ),
            "eligibility_evidence_complete": (
                self.eligibility.get(
                    "eligibility_evidence_complete"
                )
                if self.eligibility is not None
                else False
            ),
            "eligibility_evidence_coverage_rate": (
                self.eligibility.get(
                    "eligibility_evidence_coverage_rate"
                )
                if self.eligibility is not None
                else 0.0
            ),
            "eligible_pitcher_count": (
                self.eligibility.get(
                    "eligible_pitcher_count"
                )
                if self.eligibility is not None
                else len(self.bullpen_pitcher_ids)
            ),
            "excluded_pitcher_count": (
                self.eligibility.get(
                    "excluded_pitcher_count"
                )
                if self.eligibility is not None
                else 0
            ),
            "unknown_role_count": (
                self.eligibility.get(
                    "unknown_role_count"
                )
                if self.eligibility is not None
                else len(self.bullpen_pitcher_ids)
            ),
            "planned_override_count": (
                self.eligibility.get(
                    "planned_override_count"
                )
                if self.eligibility is not None
                else 0
            ),
            "require_explicit_bullpen_membership": (
                self.eligibility.get(
                    "require_explicit_bullpen_membership"
                )
                if self.eligibility is not None
                else True
            ),
            "strict_membership_excluded_count": (
                self.eligibility.get(
                    "strict_membership_excluded_count"
                )
                if self.eligibility is not None
                else 0
            ),
            "starter_like_excluded_count": (
                self.eligibility.get(
                    "starter_like_excluded_count"
                )
                if self.eligibility is not None
                else 0
            ),
            "season_usage_evidence_pitcher_count": (
                self.eligibility.get(
                    "season_usage_evidence_pitcher_count"
                )
                if self.eligibility is not None
                else 0
            ),
            "season_usage_role_classification_used": (
                self.eligibility.get(
                    "season_usage_role_classification_used"
                )
                if self.eligibility is not None
                else False
            ),
            "season_usage_classification_policy": (
                self.eligibility.get(
                    "season_usage_classification_policy"
                )
                if self.eligibility is not None
                else None
            ),
            "unknown_materialized_evidence_"
            "preserves_season_usage": (
                self.eligibility.get(
                    "unknown_materialized_evidence_"
                    "preserves_season_usage"
                )
                if self.eligibility is not None
                else False
            ),
            "evidence_precedence": (
                list(
                    self.eligibility.get(
                        "evidence_precedence"
                    )
                    or []
                )
                if self.eligibility is not None
                else []
            ),
            "pregame_evidence_materialized": (
                self.pregame_evidence is not None
            ),
            "pregame_evidence_status": (
                self.pregame_evidence.diagnostics.get(
                    "status"
                )
                if self.pregame_evidence is not None
                else "unavailable"
            ),
            "pregame_evidence_pitcher_count": (
                self.pregame_evidence.diagnostics.get(
                    "pitcher_count"
                )
                if self.pregame_evidence is not None
                else 0
            ),
            "pregame_evidence_unknown_count": (
                self.pregame_evidence.diagnostics.get(
                    "unknown_pitcher_count"
                )
                if self.pregame_evidence is not None
                else 0
            ),
            "pregame_evidence_conflict_count": (
                self.pregame_evidence.diagnostics.get(
                    "conflicting_pitcher_count"
                )
                if self.pregame_evidence is not None
                else 0
            ),
            "pregame_evidence_stale_count": (
                self.pregame_evidence.diagnostics.get(
                    "stale_observation_count"
                )
                if self.pregame_evidence is not None
                else 0
            ),
            "typical_role_inference_used": False,
            "workload_inference_used": False,
            "roster_order_inference_used": False,
            "exclusion_reason_counts": (
                dict(
                    self.eligibility.get(
                        "exclusion_reason_counts"
                    )
                    or {}
                )
                if self.eligibility is not None
                else {}
            ),
            "error_type": self.error_type,
            "error_message": self.error_message,
            "pitcher_identifiers_exposed": False,
        }


@dataclass(frozen=True)
class CanonicalShadowBullpenDiscovery:
    away: CanonicalShadowBullpenSideDiscovery
    home: CanonicalShadowBullpenSideDiscovery
    discovery_version: str = (
        CANONICAL_SHADOW_BULLPEN_DISCOVERY_VERSION
    )

    def __post_init__(self) -> None:
        if self.discovery_version != (
            CANONICAL_SHADOW_BULLPEN_DISCOVERY_VERSION
        ):
            raise ValueError(
                "unsupported canonical shadow bullpen "
                "discovery version"
            )

    @property
    def ready(self) -> bool:
        return self.away.ready and self.home.ready

    @property
    def status(self) -> str:
        if self.ready:
            return "ready"

        if (
            self.away.status == "error"
            or self.home.status == "error"
        ):
            return "error"

        if self.away.ready or self.home.ready:
            return "partial"

        return "unavailable"

    def readiness_matchup_fields(
        self,
    ) -> Dict[str, Any]:
        fields = {}
        fields.update(
            self.away.readiness_fields(side="away")
        )
        fields.update(
            self.home.readiness_fields(side="home")
        )
        return fields

    def to_diagnostics(self) -> Dict[str, Any]:
        return {
            "schema_version": self.discovery_version,
            "status": self.status,
            "ready": self.ready,
            "source": "mlb_stats_active_roster",
            "away": self.away.to_diagnostics(),
            "home": self.home.to_diagnostics(),
            "pitcher_identifiers_exposed": False,
            "activation_permitted": False,
            "authoritative_source": "legacy",
        }


def _discover_side(
    *,
    team_side: str,
    team_id: Any,
    team_name: Any,
    starter_id: Any,
    season: int,
    roster_fetcher: Callable[..., Sequence[Mapping[str, Any]]],
    eligibility_evidence_by_pitcher_id: Optional[
        Mapping[Any, Any]
    ] = None,
    planned_pitcher_ids: Any = (),
    pregame_evidence_as_of: Any = None,
    pregame_pitching_plan: Optional[
        Mapping[str, Any]
    ] = None,
    pregame_provider_observations: Any = (),
    pregame_maximum_age_seconds: int = 21600,
    require_explicit_bullpen_membership: (
        bool
    ) = False,
) -> CanonicalShadowBullpenSideDiscovery:
    normalized_team = _normalize_identifier(
        team_id
    )
    normalized_starter = _normalize_identifier(
        starter_id
    )

    if normalized_team is None:
        return CanonicalShadowBullpenSideDiscovery(
            starter_id=normalized_starter,
            status="blocked",
            error_type="missing_team_id",
            error_message=(
                "team_id is required for active-roster "
                "bullpen discovery"
            ),
        )

    if normalized_starter is None:
        return CanonicalShadowBullpenSideDiscovery(
            team_id=normalized_team,
            status="blocked",
            error_type="missing_starter_id",
            error_message=(
                "starter_id is required to exclude the "
                "scheduled starter"
            ),
        )

    try:
        records = roster_fetcher(
            int(normalized_team),
            int(season),
            team_name=team_name,
        )
    except Exception as exc:
        return CanonicalShadowBullpenSideDiscovery(
            team_id=normalized_team,
            starter_id=normalized_starter,
            status="error",
            error_type=type(exc).__name__,
            error_message=str(exc),
        )

    if not isinstance(records, Sequence) or isinstance(
        records,
        (str, bytes),
    ):
        return CanonicalShadowBullpenSideDiscovery(
            team_id=normalized_team,
            starter_id=normalized_starter,
            status="blocked",
            error_type="invalid_payload",
            error_message=(
                "active-roster fetcher must return a sequence"
            ),
        )

    pitcher_ids = _pitcher_identifiers(
        records,
        starter_id=normalized_starter,
    )
    pregame_evidence = None
    materialized_evidence_by_pitcher_id = {}
    materialized_planned_pitcher_ids = ()

    if pregame_evidence_as_of is not None:
        pregame_evidence = (
            materialize_canonical_pregame_pitcher_evidence(
                team_side=team_side,
                scheduled_starter_id=(
                    normalized_starter
                ),
                active_roster_pitcher_ids=(
                    (normalized_starter,)
                    + pitcher_ids
                ),
                as_of=pregame_evidence_as_of,
                pitching_plan=pregame_pitching_plan,
                provider_observations=(
                    pregame_provider_observations
                ),
                maximum_age_seconds=(
                    pregame_maximum_age_seconds
                ),
            )
        )
        materialized_evidence_by_pitcher_id = dict(
            pregame_evidence.evidence_by_pitcher_id
        )
        materialized_planned_pitcher_ids = (
            pregame_evidence.planned_pitcher_ids
        )

    season_usage_evidence = (
        _active_roster_usage_evidence(
            records,
            candidate_pitcher_ids=pitcher_ids,
        )
    )
    direct_evidence = (
        dict(eligibility_evidence_by_pitcher_id)
        if isinstance(
            eligibility_evidence_by_pitcher_id,
            Mapping,
        )
        else {}
    )
    combined_evidence = dict(
        season_usage_evidence
    )

    for (
        evidence_pitcher_id,
        materialized_record,
    ) in materialized_evidence_by_pitcher_id.items():
        normalized_evidence_pitcher_id = (
            _normalize_identifier(
                evidence_pitcher_id
            )
        )

        if normalized_evidence_pitcher_id is None:
            continue

        materialized_status = (
            str(
                (
                    materialized_record.get("status")
                    if isinstance(
                        materialized_record,
                        Mapping,
                    )
                    else None
                )
                or "unknown"
            )
            .strip()
            .lower()
        )

        if (
            materialized_status
            in {"eligible", "ineligible"}
            or normalized_evidence_pitcher_id
            not in combined_evidence
        ):
            combined_evidence[
                normalized_evidence_pitcher_id
            ] = materialized_record

    combined_evidence.update(direct_evidence)
    combined_planned_pitcher_ids = tuple(
        dict.fromkeys(
            materialized_planned_pitcher_ids
            + _normalize_identifiers(
                planned_pitcher_ids
            )
        )
    )

    eligibility = (
        enforce_canonical_bullpen_eligibility(
            candidate_pitcher_ids=pitcher_ids,
            starter_id=normalized_starter,
            evidence_by_pitcher_id=(
                combined_evidence or None
            ),
            planned_pitcher_ids=(
                combined_planned_pitcher_ids
            ),
            require_explicit_bullpen_membership=(
                require_explicit_bullpen_membership
            ),
        )
    )
    eligibility[
        "season_usage_evidence_pitcher_count"
    ] = len(season_usage_evidence)
    eligibility[
        "season_usage_role_classification_used"
    ] = bool(season_usage_evidence)
    eligibility[
        "season_usage_classification_policy"
    ] = (
        "relief_appearances_greater_than_starts"
    )
    eligibility[
        "unknown_materialized_evidence_"
        "preserves_season_usage"
    ] = True
    eligibility[
        "evidence_precedence"
    ] = [
        "direct_explicit_evidence",
        "materialized_known_provider_evidence",
        "mlb_stats_season_pitching_usage",
        "materialized_unknown_evidence",
    ]

    eligible_pitcher_ids = tuple(
        eligibility[
            "eligible_bullpen_pitcher_ids"
        ]
    )

    return CanonicalShadowBullpenSideDiscovery(
        team_id=normalized_team,
        starter_id=normalized_starter,
        bullpen_pitcher_ids=(
            eligible_pitcher_ids
        ),
        eligibility=eligibility,
        pregame_evidence=pregame_evidence,
        source_record_count=len(records),
        status=(
            "ready"
            if eligible_pitcher_ids
            else "unavailable"
        ),
    )


def discover_canonical_shadow_bullpens(
    *,
    away_team_id: Any,
    away_team_name: Any,
    away_starter_id: Any,
    home_team_id: Any,
    home_team_name: Any,
    home_starter_id: Any,
    season: int,
    roster_fetcher: Optional[
        Callable[..., Sequence[Mapping[str, Any]]]
    ] = None,
    away_eligibility_evidence_by_pitcher_id: Optional[
        Mapping[Any, Any]
    ] = None,
    home_eligibility_evidence_by_pitcher_id: Optional[
        Mapping[Any, Any]
    ] = None,
    away_planned_pitcher_ids: Any = (),
    home_planned_pitcher_ids: Any = (),
    pregame_evidence_as_of: Any = None,
    away_pregame_pitching_plan: Optional[
        Mapping[str, Any]
    ] = None,
    home_pregame_pitching_plan: Optional[
        Mapping[str, Any]
    ] = None,
    away_pregame_provider_observations: Any = (),
    home_pregame_provider_observations: Any = (),
    pregame_maximum_age_seconds: int = 21600,
    require_explicit_bullpen_membership: (
        bool
    ) = False,
) -> CanonicalShadowBullpenDiscovery:
    """
    Discover active-roster bullpen IDs without activating canonical execution.

    Active-roster pitchers are treated as bootstrap candidates, not proof
    of bullpen membership, game availability, leverage role, or expected
    usage. Production may require explicit bullpen membership; compatibility
    callers retain candidate-discovery behavior unless they opt into it.
    """

    if roster_fetcher is None:
        from mlb_app.dashboard_player_population import (
            fetch_active_roster,
        )

        roster_fetcher = fetch_active_roster

    return CanonicalShadowBullpenDiscovery(
        away=_discover_side(
            team_side="away",
            team_id=away_team_id,
            team_name=away_team_name,
            starter_id=away_starter_id,
            season=season,
            roster_fetcher=roster_fetcher,
            eligibility_evidence_by_pitcher_id=(
                away_eligibility_evidence_by_pitcher_id
            ),
            planned_pitcher_ids=(
                away_planned_pitcher_ids
            ),
            pregame_evidence_as_of=(
                pregame_evidence_as_of
            ),
            pregame_pitching_plan=(
                away_pregame_pitching_plan
            ),
            pregame_provider_observations=(
                away_pregame_provider_observations
            ),
            pregame_maximum_age_seconds=(
                pregame_maximum_age_seconds
            ),
            require_explicit_bullpen_membership=(
                require_explicit_bullpen_membership
            ),
        ),
        home=_discover_side(
            team_side="home",
            team_id=home_team_id,
            team_name=home_team_name,
            starter_id=home_starter_id,
            season=season,
            roster_fetcher=roster_fetcher,
            eligibility_evidence_by_pitcher_id=(
                home_eligibility_evidence_by_pitcher_id
            ),
            planned_pitcher_ids=(
                home_planned_pitcher_ids
            ),
            pregame_evidence_as_of=(
                pregame_evidence_as_of
            ),
            pregame_pitching_plan=(
                home_pregame_pitching_plan
            ),
            pregame_provider_observations=(
                home_pregame_provider_observations
            ),
            pregame_maximum_age_seconds=(
                pregame_maximum_age_seconds
            ),
            require_explicit_bullpen_membership=(
                require_explicit_bullpen_membership
            ),
        ),
    )
