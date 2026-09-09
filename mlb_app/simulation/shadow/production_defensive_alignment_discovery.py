"""Production source adapter for canonical defensive alignments."""

from __future__ import annotations

from dataclasses import dataclass
from typing import (
    Any,
    Callable,
    Dict,
    Mapping,
    Optional,
    Sequence,
    Tuple,
)

from .defensive_alignment_materialization import (
    CanonicalDefensiveAlignmentMaterialization,
    materialize_canonical_defensive_alignments,
)
from .production_lineup_selection import (
    CanonicalProductionLineupSelection,
)


CANONICAL_PRODUCTION_DEFENSIVE_ALIGNMENT_DISCOVERY_VERSION = (
    "canonical_production_defensive_alignment_discovery_v1"
)


def _normalize_identifier(
    value: Any,
) -> Optional[str]:
    if value in (None, "") or isinstance(value, bool):
        return None

    try:
        return str(int(value))
    except (TypeError, ValueError):
        normalized = str(value).strip()
        return normalized or None


def _record_identifier(
    record: Any,
) -> Optional[str]:
    if not isinstance(record, Mapping):
        return None

    person = record.get("person")

    if not isinstance(person, Mapping):
        person = {}

    return _normalize_identifier(
        record.get("batter_id")
        or record.get("player_id")
        or record.get("id")
        or record.get("person_id")
        or person.get("id")
    )


def _record_ids(
    records: Any,
) -> Tuple[str, ...]:
    if (
        not isinstance(records, Sequence)
        or isinstance(records, (str, bytes))
    ):
        return ()

    return tuple(
        identifier
        for identifier in (
            _record_identifier(record)
            for record in records
        )
        if identifier is not None
    )


def _matching_side_records(
    *,
    payload: Mapping[str, Any],
    selected_player_ids: Tuple[str, ...],
) -> Tuple[Any, Optional[str]]:
    selected = set(selected_player_ids)
    matches = []

    for side in ("away", "home"):
        records = payload.get(side) or []
        identifiers = set(_record_ids(records))

        if selected.issubset(identifiers):
            matches.append((side, records))

    if len(matches) != 1:
        return (), None

    return matches[0][1], matches[0][0]


def _blocked_materialization(
    *,
    blocker: str,
    source_identifier: Optional[str] = None,
    source_as_of: Optional[str] = None,
    confidence: Optional[str] = None,
) -> CanonicalDefensiveAlignmentMaterialization:
    return CanonicalDefensiveAlignmentMaterialization(
        blockers=(blocker,),
        source_identifier=source_identifier,
        source_as_of=source_as_of,
        confidence=confidence,
    )


@dataclass(frozen=True)
class CanonicalProductionDefensiveAlignmentDiscovery:
    """Source lookup plus atomic defensive materialization."""

    materialization: (
        CanonicalDefensiveAlignmentMaterialization
    )
    lineup_source: Optional[str] = None
    away_source_game_pk: Optional[str] = None
    home_source_game_pk: Optional[str] = None
    away_source_side: Optional[str] = None
    home_source_side: Optional[str] = None
    error_type: Optional[str] = None
    error_message: Optional[str] = None
    schema_version: str = (
        CANONICAL_PRODUCTION_DEFENSIVE_ALIGNMENT_DISCOVERY_VERSION
    )

    def __post_init__(self) -> None:
        if not isinstance(
            self.materialization,
            CanonicalDefensiveAlignmentMaterialization,
        ):
            raise TypeError(
                "materialization must be canonical"
            )

        if self.schema_version != (
            CANONICAL_PRODUCTION_DEFENSIVE_ALIGNMENT_DISCOVERY_VERSION
        ):
            raise ValueError(
                "unsupported production defensive "
                "alignment discovery version"
            )

    @property
    def ready(self) -> bool:
        return self.materialization.ready

    @property
    def status(self) -> str:
        if self.error_type is not None:
            return "error"

        return "ready" if self.ready else "blocked"

    def to_diagnostics(self) -> Dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "status": self.status,
            "ready": self.ready,
            "lineup_source": self.lineup_source,
            "away_source_game_pk": (
                self.away_source_game_pk
            ),
            "home_source_game_pk": (
                self.home_source_game_pk
            ),
            "away_source_side": self.away_source_side,
            "home_source_side": self.home_source_side,
            "materialization": (
                self.materialization.to_diagnostics()
            ),
            "error_type": self.error_type,
            "error_message": self.error_message,
            "player_identifiers_exposed": False,
            "production_authority_changed": False,
            "authoritative": False,
        }


def discover_canonical_production_defensive_alignments(
    *,
    game_pk: Any,
    lineup_selection: CanonicalProductionLineupSelection,
    lineup_fetcher: Optional[
        Callable[[int], Mapping[str, Any]]
    ] = None,
) -> CanonicalProductionDefensiveAlignmentDiscovery:
    """
    Discover position records for the exact selected lineups.

    Confirmed lineups use the current game boxscore. Projected lineups use
    each side's selected prior completed game and are matched by player IDs,
    never by assuming that the team retained its away/home designation.
    """

    if not isinstance(
        lineup_selection,
        CanonicalProductionLineupSelection,
    ):
        raise TypeError(
            "lineup_selection must be a "
            "CanonicalProductionLineupSelection"
        )

    selected = lineup_selection.selection.selected

    if selected is None or not lineup_selection.selection.ready:
        return CanonicalProductionDefensiveAlignmentDiscovery(
            materialization=_blocked_materialization(
                blocker=(
                    "selected_lineup_unavailable_for_"
                    "defensive_alignment"
                ),
            ),
        )

    normalized_game_pk = _normalize_identifier(game_pk)

    if normalized_game_pk is None:
        return CanonicalProductionDefensiveAlignmentDiscovery(
            materialization=_blocked_materialization(
                blocker="missing_game_pk",
            ),
            lineup_source=selected.lineup_source,
        )

    if lineup_fetcher is None:
        from mlb_app.lineup_profile import (
            fetch_boxscore_lineup,
        )

        lineup_fetcher = fetch_boxscore_lineup

    lineup_source = selected.lineup_source

    if lineup_source == "confirmed":
        away_source_game_pk = normalized_game_pk
        home_source_game_pk = normalized_game_pk
    elif lineup_source == "projected":
        away_source_game_pk = _normalize_identifier(
            lineup_selection.projected_away.source_game_pk
        )
        home_source_game_pk = _normalize_identifier(
            lineup_selection.projected_home.source_game_pk
        )

        if (
            away_source_game_pk is None
            or home_source_game_pk is None
        ):
            return (
                CanonicalProductionDefensiveAlignmentDiscovery(
                    materialization=_blocked_materialization(
                        blocker=(
                            "projected_defensive_alignment_"
                            "source_game_unavailable"
                        ),
                        source_as_of=selected.source_as_of,
                        confidence=selected.confidence,
                    ),
                    lineup_source=lineup_source,
                    away_source_game_pk=away_source_game_pk,
                    home_source_game_pk=home_source_game_pk,
                )
            )
    else:
        return CanonicalProductionDefensiveAlignmentDiscovery(
            materialization=_blocked_materialization(
                blocker=(
                    "unsupported_defensive_alignment_"
                    "lineup_source"
                ),
                source_as_of=selected.source_as_of,
                confidence=selected.confidence,
            ),
            lineup_source=lineup_source,
        )

    try:
        payloads = {}

        for source_game_pk in dict.fromkeys(
            (
                away_source_game_pk,
                home_source_game_pk,
            )
        ):
            payload = lineup_fetcher(
                int(source_game_pk)
            )

            if not isinstance(payload, Mapping):
                raise TypeError(
                    "lineup fetcher must return a mapping"
                )

            payloads[source_game_pk] = payload
    except Exception as exc:
        return CanonicalProductionDefensiveAlignmentDiscovery(
            materialization=_blocked_materialization(
                blocker=(
                    "defensive_alignment_source_fetch_error"
                ),
                source_identifier=(
                    "mlb_stats_boxscore:"
                    f"{away_source_game_pk}|"
                    f"{home_source_game_pk}"
                ),
                source_as_of=selected.source_as_of,
                confidence=selected.confidence,
            ),
            lineup_source=lineup_source,
            away_source_game_pk=away_source_game_pk,
            home_source_game_pk=home_source_game_pk,
            error_type=exc.__class__.__name__,
            error_message=str(exc),
        )

    if lineup_source == "confirmed":
        payload = payloads[normalized_game_pk]
        away_records = payload.get("away") or []
        home_records = payload.get("home") or []
        away_source_side = "away"
        home_source_side = "home"
    else:
        away_records, away_source_side = (
            _matching_side_records(
                payload=payloads[away_source_game_pk],
                selected_player_ids=(
                    selected.away_player_ids
                ),
            )
        )
        home_records, home_source_side = (
            _matching_side_records(
                payload=payloads[home_source_game_pk],
                selected_player_ids=(
                    selected.home_player_ids
                ),
            )
        )

        if (
            away_source_side is None
            or home_source_side is None
        ):
            return (
                CanonicalProductionDefensiveAlignmentDiscovery(
                    materialization=_blocked_materialization(
                        blocker=(
                            "projected_defensive_alignment_"
                            "lineup_side_not_matched"
                        ),
                        source_identifier=(
                            "mlb_stats_boxscore:"
                            f"{away_source_game_pk}|"
                            f"{home_source_game_pk}"
                        ),
                        source_as_of=selected.source_as_of,
                        confidence=selected.confidence,
                    ),
                    lineup_source=lineup_source,
                    away_source_game_pk=away_source_game_pk,
                    home_source_game_pk=home_source_game_pk,
                    away_source_side=away_source_side,
                    home_source_side=home_source_side,
                )
            )

    source_identifier = (
        "mlb_stats_boxscore:"
        f"{away_source_game_pk}|"
        f"{home_source_game_pk}"
    )

    materialization = (
        materialize_canonical_defensive_alignments(
            lineups=selected,
            away_records=away_records,
            home_records=home_records,
            source_identifier=source_identifier,
            source_as_of=selected.source_as_of,
            confidence=selected.confidence,
        )
    )

    return CanonicalProductionDefensiveAlignmentDiscovery(
        materialization=materialization,
        lineup_source=lineup_source,
        away_source_game_pk=away_source_game_pk,
        home_source_game_pk=home_source_game_pk,
        away_source_side=away_source_side,
        home_source_side=home_source_side,
    )
