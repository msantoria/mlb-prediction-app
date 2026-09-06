"""Source-neutral canonical lineup selection contract."""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
from typing import Any, Dict, Optional, Sequence, Tuple


CANONICAL_SELECTED_LINEUP_VERSION = (
    "canonical_selected_lineup_v1"
)
CANONICAL_LINEUP_SOURCES = frozenset(
    {"confirmed", "projected"}
)


def _normalize_identifier(value: Any) -> Optional[str]:
    if value in (None, "") or isinstance(value, bool):
        return None

    try:
        return str(int(value))
    except (TypeError, ValueError):
        text = str(value).strip()
        return text or None


def _normalize_player_ids(
    values: Any,
) -> Tuple[str, ...]:
    if (
        not isinstance(values, Sequence)
        or isinstance(values, (str, bytes))
    ):
        return ()

    normalized = []

    for value in values:
        identifier = _normalize_identifier(value)

        if identifier is not None:
            normalized.append(identifier)

    return tuple(normalized)


def _stable_digest(payload: Dict[str, Any]) -> str:
    encoded = json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")

    return hashlib.sha256(encoded).hexdigest()


@dataclass(frozen=True)
class CanonicalLineupSideCandidate:
    """One ordered lineup candidate from one source."""

    team_side: str
    player_ids: Tuple[str, ...]
    lineup_source: str
    source_identifier: str
    source_as_of: str
    confidence: str

    def __post_init__(self) -> None:
        if self.team_side not in {"away", "home"}:
            raise ValueError(
                "team_side must be away or home"
            )

        if self.lineup_source not in (
            CANONICAL_LINEUP_SOURCES
        ):
            raise ValueError(
                "unsupported lineup_source"
            )

        if not str(self.source_identifier).strip():
            raise ValueError(
                "source_identifier is required"
            )

        if not str(self.source_as_of).strip():
            raise ValueError(
                "source_as_of is required"
            )

        if not str(self.confidence).strip():
            raise ValueError(
                "confidence is required"
            )

        object.__setattr__(
            self,
            "player_ids",
            _normalize_player_ids(self.player_ids),
        )

    @property
    def blockers(self) -> Tuple[str, ...]:
        blockers = []

        if len(self.player_ids) != 9:
            blockers.append(
                f"{self.lineup_source}_"
                f"{self.team_side}_"
                "lineup_requires_9_players"
            )

        if len(set(self.player_ids)) != len(
            self.player_ids
        ):
            blockers.append(
                f"{self.lineup_source}_"
                f"{self.team_side}_"
                "lineup_has_duplicate_players"
            )

        return tuple(blockers)

    @property
    def ready(self) -> bool:
        return not self.blockers

    @property
    def present(self) -> bool:
        return bool(self.player_ids)


@dataclass(frozen=True)
class CanonicalSelectedLineup:
    """Validated whole-game canonical lineup."""

    game_pk: str
    away_player_ids: Tuple[str, ...]
    home_player_ids: Tuple[str, ...]
    lineup_source: str
    source_identifier: str
    source_as_of: str
    confidence: str
    lineup_digest: str
    schema_version: str = (
        CANONICAL_SELECTED_LINEUP_VERSION
    )

    def __post_init__(self) -> None:
        if self.schema_version != (
            CANONICAL_SELECTED_LINEUP_VERSION
        ):
            raise ValueError(
                "unsupported selected-lineup version"
            )

        if _normalize_identifier(self.game_pk) is None:
            raise ValueError("game_pk is required")

        if self.lineup_source not in (
            CANONICAL_LINEUP_SOURCES
        ):
            raise ValueError(
                "unsupported lineup_source"
            )

        if (
            len(self.away_player_ids) != 9
            or len(set(self.away_player_ids)) != 9
        ):
            raise ValueError(
                "away_player_ids must contain "
                "9 unique players"
            )

        if (
            len(self.home_player_ids) != 9
            or len(set(self.home_player_ids)) != 9
        ):
            raise ValueError(
                "home_player_ids must contain "
                "9 unique players"
            )

    @property
    def ready(self) -> bool:
        return True

    def readiness_matchup_fields(
        self,
    ) -> Dict[str, Any]:
        return {
            "away_lineup": [
                {"player_id": player_id}
                for player_id in self.away_player_ids
            ],
            "home_lineup": [
                {"player_id": player_id}
                for player_id in self.home_player_ids
            ],
            "lineup_source": self.lineup_source,
            "lineup_digest": self.lineup_digest,
        }

    def to_diagnostics(self) -> Dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "status": "ready",
            "ready": True,
            "source": self.lineup_source,
            "lineup_source": self.lineup_source,
            "source_identifier": (
                self.source_identifier
            ),
            "source_as_of": self.source_as_of,
            "confidence": self.confidence,
            "lineup_digest": self.lineup_digest,
            "away": {
                "ready": True,
                "validated_player_count": len(
                    self.away_player_ids
                ),
                "required_player_count": 9,
            },
            "home": {
                "ready": True,
                "validated_player_count": len(
                    self.home_player_ids
                ),
                "required_player_count": 9,
            },
            "player_identifiers_exposed": False,
            "activation_permitted": False,
            "production_authority_changed": False,
            "authoritative_source": "legacy",
        }


@dataclass(frozen=True)
class CanonicalSelectedLineupSelection:
    """Ready selection or explicit fail-closed blockers."""

    selected: Optional[CanonicalSelectedLineup]
    blockers: Tuple[str, ...] = ()
    schema_version: str = (
        CANONICAL_SELECTED_LINEUP_VERSION
    )

    @property
    def ready(self) -> bool:
        return (
            self.selected is not None
            and not self.blockers
        )

    def to_diagnostics(self) -> Dict[str, Any]:
        selected = self.selected

        return {
            "schema_version": self.schema_version,
            "status": (
                "ready" if self.ready else "blocked"
            ),
            "ready": self.ready,
            "lineup_source": (
                selected.lineup_source
                if selected
                else None
            ),
            "source_identifier": (
                selected.source_identifier
                if selected
                else None
            ),
            "source_as_of": (
                selected.source_as_of
                if selected
                else None
            ),
            "confidence": (
                selected.confidence
                if selected
                else None
            ),
            "lineup_digest": (
                selected.lineup_digest
                if selected
                else None
            ),
            "blockers": list(self.blockers),
            "player_identifiers_exposed": False,
            "activation_permitted": False,
        }


def build_canonical_lineup_side_candidate(
    *,
    team_side: str,
    player_ids: Any,
    lineup_source: str,
    source_identifier: str,
    source_as_of: str,
    confidence: str,
) -> CanonicalLineupSideCandidate:
    return CanonicalLineupSideCandidate(
        team_side=team_side,
        player_ids=_normalize_player_ids(
            player_ids
        ),
        lineup_source=lineup_source,
        source_identifier=source_identifier,
        source_as_of=source_as_of,
        confidence=confidence,
    )


def _select_candidate_pair(
    *,
    game_pk: str,
    away: CanonicalLineupSideCandidate,
    home: CanonicalLineupSideCandidate,
) -> CanonicalSelectedLineupSelection:
    blockers = tuple(
        (*away.blockers, *home.blockers)
    )

    if blockers:
        return CanonicalSelectedLineupSelection(
            selected=None,
            blockers=blockers,
        )

    source_identifier = (
        f"{away.source_identifier}|"
        f"{home.source_identifier}"
    )
    source_as_of = max(
        away.source_as_of,
        home.source_as_of,
    )
    confidence = (
        "confirmed"
        if away.lineup_source == "confirmed"
        else "provisional"
    )

    digest_payload = {
        "schema_version": (
            CANONICAL_SELECTED_LINEUP_VERSION
        ),
        "game_pk": game_pk,
        "away_player_ids": away.player_ids,
        "home_player_ids": home.player_ids,
        "lineup_source": away.lineup_source,
        "source_identifier": source_identifier,
        "source_as_of": source_as_of,
        "confidence": confidence,
    }

    selected = CanonicalSelectedLineup(
        **digest_payload,
        lineup_digest=_stable_digest(
            digest_payload
        ),
    )

    return CanonicalSelectedLineupSelection(
        selected=selected,
    )


def select_canonical_lineup(
    *,
    game_pk: Any,
    confirmed_away: CanonicalLineupSideCandidate,
    confirmed_home: CanonicalLineupSideCandidate,
    projected_away: CanonicalLineupSideCandidate,
    projected_home: CanonicalLineupSideCandidate,
) -> CanonicalSelectedLineupSelection:
    """
    Select complete confirmed lineups, otherwise
    complete projected lineups.

    Any partial confirmed state blocks selection so
    projected and confirmed sides are never mixed.
    """

    identifier = _normalize_identifier(game_pk)

    if identifier is None:
        return CanonicalSelectedLineupSelection(
            selected=None,
            blockers=("missing_game_pk",),
        )

    candidates = (
        confirmed_away,
        confirmed_home,
        projected_away,
        projected_home,
    )
    expected_assignments = (
        ("away", "confirmed"),
        ("home", "confirmed"),
        ("away", "projected"),
        ("home", "projected"),
    )

    actual_assignments = tuple(
        (
            candidate.team_side,
            candidate.lineup_source,
        )
        for candidate in candidates
    )

    if actual_assignments != expected_assignments:
        raise ValueError(
            "candidate side/source assignments "
            "are invalid"
        )

    if (
        confirmed_away.ready
        and confirmed_home.ready
    ):
        return _select_candidate_pair(
            game_pk=identifier,
            away=confirmed_away,
            home=confirmed_home,
        )

    if (
        confirmed_away.present
        or confirmed_home.present
    ):
        blockers = [
            "mixed_or_partial_confirmed_lineups"
        ]
        blockers.extend(confirmed_away.blockers)
        blockers.extend(confirmed_home.blockers)

        return CanonicalSelectedLineupSelection(
            selected=None,
            blockers=tuple(
                dict.fromkeys(blockers)
            ),
        )

    return _select_candidate_pair(
        game_pk=identifier,
        away=projected_away,
        home=projected_home,
    )
