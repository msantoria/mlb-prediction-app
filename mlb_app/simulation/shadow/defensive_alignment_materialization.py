"""Atomic defensive-alignment materialization from position records."""

from __future__ import annotations

from dataclasses import dataclass
from typing import (
    Any,
    Dict,
    Mapping,
    Optional,
    Sequence,
    Tuple,
)

from mlb_app.simulation.game import (
    CANONICAL_DEFENSIVE_POSITION_ORDER,
    CanonicalDefensiveAlignment,
    CanonicalDefensiveFielder,
    CanonicalDefensivePosition,
)


CANONICAL_DEFENSIVE_ALIGNMENT_MATERIALIZATION_VERSION = (
    "canonical_defensive_alignment_materialization_v1"
)

_POSITION_ALIASES = {
    "2": CanonicalDefensivePosition.CATCHER,
    "c": CanonicalDefensivePosition.CATCHER,
    "catcher": CanonicalDefensivePosition.CATCHER,
    "3": CanonicalDefensivePosition.FIRST_BASE,
    "1b": CanonicalDefensivePosition.FIRST_BASE,
    "first base": CanonicalDefensivePosition.FIRST_BASE,
    "first_base": CanonicalDefensivePosition.FIRST_BASE,
    "4": CanonicalDefensivePosition.SECOND_BASE,
    "2b": CanonicalDefensivePosition.SECOND_BASE,
    "second base": CanonicalDefensivePosition.SECOND_BASE,
    "second_base": CanonicalDefensivePosition.SECOND_BASE,
    "5": CanonicalDefensivePosition.THIRD_BASE,
    "3b": CanonicalDefensivePosition.THIRD_BASE,
    "third base": CanonicalDefensivePosition.THIRD_BASE,
    "third_base": CanonicalDefensivePosition.THIRD_BASE,
    "6": CanonicalDefensivePosition.SHORTSTOP,
    "ss": CanonicalDefensivePosition.SHORTSTOP,
    "shortstop": CanonicalDefensivePosition.SHORTSTOP,
    "7": CanonicalDefensivePosition.LEFT_FIELD,
    "lf": CanonicalDefensivePosition.LEFT_FIELD,
    "left field": CanonicalDefensivePosition.LEFT_FIELD,
    "left_field": CanonicalDefensivePosition.LEFT_FIELD,
    "8": CanonicalDefensivePosition.CENTER_FIELD,
    "cf": CanonicalDefensivePosition.CENTER_FIELD,
    "center field": CanonicalDefensivePosition.CENTER_FIELD,
    "center_field": CanonicalDefensivePosition.CENTER_FIELD,
    "9": CanonicalDefensivePosition.RIGHT_FIELD,
    "rf": CanonicalDefensivePosition.RIGHT_FIELD,
    "right field": CanonicalDefensivePosition.RIGHT_FIELD,
    "right_field": CanonicalDefensivePosition.RIGHT_FIELD,
}


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
    record: Mapping[str, Any],
) -> Optional[str]:
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


def _record_position(
    record: Mapping[str, Any],
) -> Optional[CanonicalDefensivePosition]:
    raw_position = record.get("position")
    raw_code = record.get("position_code")

    if isinstance(raw_position, Mapping):
        raw_code = (
            raw_position.get("code")
            or raw_code
        )
        raw_position = (
            raw_position.get("abbreviation")
            or raw_position.get("name")
        )

    for value in (raw_code, raw_position):
        normalized = str(value or "").strip().lower()

        if normalized in _POSITION_ALIASES:
            return _POSITION_ALIASES[normalized]

    return None


def _selected_player_ids(
    lineups: Any,
    team_side: str,
) -> Tuple[str, ...]:
    values = getattr(
        lineups,
        f"{team_side}_player_ids",
        (),
    )

    return tuple(
        identifier
        for identifier in (
            _normalize_identifier(value)
            for value in tuple(values or ())
        )
        if identifier is not None
    )


def _materialize_side(
    *,
    team_side: str,
    selected_player_ids: Tuple[str, ...],
    records: Any,
    source_identifier: str,
    source_as_of: str,
    confidence: str,
) -> Tuple[
    Optional[CanonicalDefensiveAlignment],
    Tuple[str, ...],
]:
    if (
        not isinstance(records, Sequence)
        or isinstance(records, (str, bytes))
    ):
        return None, (
            f"{team_side}_defensive_records_invalid",
        )

    selected = set(selected_player_ids)
    by_position = {}
    seen_player_ids = set()
    blockers = []

    for record in records:
        if not isinstance(record, Mapping):
            continue

        player_id = _record_identifier(record)
        position = _record_position(record)

        if player_id is None or position is None:
            continue

        if player_id not in selected:
            blockers.append(
                f"{team_side}_defensive_player_"
                "outside_selected_lineup"
            )
            continue

        if position in by_position:
            blockers.append(
                f"{team_side}_duplicate_defensive_position"
            )
            continue

        if player_id in seen_player_ids:
            blockers.append(
                f"{team_side}_duplicate_defensive_player"
            )
            continue

        by_position[position] = player_id
        seen_player_ids.add(player_id)

    missing_positions = tuple(
        position
        for position in CANONICAL_DEFENSIVE_POSITION_ORDER
        if position not in by_position
    )

    if missing_positions:
        blockers.append(
            f"{team_side}_defensive_alignment_"
            "requires_eight_positions"
        )

    blockers = tuple(dict.fromkeys(blockers))

    if blockers:
        return None, blockers

    return (
        CanonicalDefensiveAlignment(
            team_side=team_side,
            fielders=tuple(
                CanonicalDefensiveFielder(
                    position=position,
                    player_id=by_position[position],
                )
                for position in (
                    CANONICAL_DEFENSIVE_POSITION_ORDER
                )
            ),
            source_identifier=source_identifier,
            source_as_of=source_as_of,
            confidence=confidence,
        ),
        (),
    )


@dataclass(frozen=True)
class CanonicalDefensiveAlignmentMaterialization:
    """Both-side alignment materialization or atomic blockers."""

    away_alignment: Optional[
        CanonicalDefensiveAlignment
    ] = None
    home_alignment: Optional[
        CanonicalDefensiveAlignment
    ] = None
    blockers: Tuple[str, ...] = ()
    source_identifier: Optional[str] = None
    source_as_of: Optional[str] = None
    confidence: Optional[str] = None
    schema_version: str = (
        CANONICAL_DEFENSIVE_ALIGNMENT_MATERIALIZATION_VERSION
    )

    def __post_init__(self) -> None:
        if self.schema_version != (
            CANONICAL_DEFENSIVE_ALIGNMENT_MATERIALIZATION_VERSION
        ):
            raise ValueError(
                "unsupported defensive alignment "
                "materialization version"
            )

        alignments_present = (
            self.away_alignment is not None
            or self.home_alignment is not None
        )

        if alignments_present and (
            self.away_alignment is None
            or self.home_alignment is None
        ):
            raise ValueError(
                "defensive alignments must be atomic"
            )

        if self.ready and self.blockers:
            raise ValueError(
                "ready materialization cannot contain blockers"
            )

        if not self.ready and not self.blockers:
            raise ValueError(
                "blocked materialization requires blockers"
            )

    @property
    def ready(self) -> bool:
        return (
            self.away_alignment is not None
            and self.home_alignment is not None
        )

    @property
    def status(self) -> str:
        return "ready" if self.ready else "blocked"

    def alignment_for(
        self,
        team_side: str,
    ) -> Optional[CanonicalDefensiveAlignment]:
        if team_side == "away":
            return self.away_alignment

        if team_side == "home":
            return self.home_alignment

        raise ValueError(
            "team_side must be away or home"
        )

    def to_diagnostics(self) -> Dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "status": self.status,
            "ready": self.ready,
            "source_identifier": self.source_identifier,
            "source_as_of": self.source_as_of,
            "confidence": self.confidence,
            "away": (
                self.away_alignment.to_diagnostics()
                if self.away_alignment is not None
                else None
            ),
            "home": (
                self.home_alignment.to_diagnostics()
                if self.home_alignment is not None
                else None
            ),
            "blockers": list(self.blockers),
            "atomic": True,
            "production_authority_changed": False,
            "authoritative": False,
        }


def materialize_canonical_defensive_alignments(
    *,
    lineups: Any,
    away_records: Any,
    home_records: Any,
    source_identifier: Any,
    source_as_of: Any,
    confidence: Any,
) -> CanonicalDefensiveAlignmentMaterialization:
    """Materialize both selected-lineup alignments atomically."""

    normalized_source = str(
        source_identifier or ""
    ).strip()
    normalized_as_of = str(
        source_as_of or ""
    ).strip()
    normalized_confidence = str(
        confidence or ""
    ).strip()

    metadata_blockers = []

    if not normalized_source:
        metadata_blockers.append(
            "defensive_alignment_source_identifier_required"
        )

    if not normalized_as_of:
        metadata_blockers.append(
            "defensive_alignment_source_as_of_required"
        )

    if not normalized_confidence:
        metadata_blockers.append(
            "defensive_alignment_confidence_required"
        )

    away_player_ids = _selected_player_ids(
        lineups,
        "away",
    )
    home_player_ids = _selected_player_ids(
        lineups,
        "home",
    )

    if (
        len(away_player_ids) != 9
        or len(set(away_player_ids)) != 9
    ):
        metadata_blockers.append(
            "away_selected_lineup_requires_nine_players"
        )

    if (
        len(home_player_ids) != 9
        or len(set(home_player_ids)) != 9
    ):
        metadata_blockers.append(
            "home_selected_lineup_requires_nine_players"
        )

    if metadata_blockers:
        return CanonicalDefensiveAlignmentMaterialization(
            blockers=tuple(
                dict.fromkeys(metadata_blockers)
            ),
            source_identifier=normalized_source or None,
            source_as_of=normalized_as_of or None,
            confidence=normalized_confidence or None,
        )

    away_alignment, away_blockers = (
        _materialize_side(
            team_side="away",
            selected_player_ids=away_player_ids,
            records=away_records,
            source_identifier=normalized_source,
            source_as_of=normalized_as_of,
            confidence=normalized_confidence,
        )
    )
    home_alignment, home_blockers = (
        _materialize_side(
            team_side="home",
            selected_player_ids=home_player_ids,
            records=home_records,
            source_identifier=normalized_source,
            source_as_of=normalized_as_of,
            confidence=normalized_confidence,
        )
    )

    blockers = tuple(
        dict.fromkeys(
            (*away_blockers, *home_blockers)
        )
    )

    if blockers:
        return CanonicalDefensiveAlignmentMaterialization(
            blockers=blockers,
            source_identifier=normalized_source,
            source_as_of=normalized_as_of,
            confidence=normalized_confidence,
        )

    return CanonicalDefensiveAlignmentMaterialization(
        away_alignment=away_alignment,
        home_alignment=home_alignment,
        source_identifier=normalized_source,
        source_as_of=normalized_as_of,
        confidence=normalized_confidence,
    )
