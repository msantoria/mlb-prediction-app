"""Projected-lineup discovery from prior completed games."""

from __future__ import annotations

from dataclasses import dataclass
import datetime as dt
from typing import (
    Any,
    Callable,
    Dict,
    Mapping,
    Optional,
    Sequence,
    Tuple,
)

from .selected_lineup import (
    CanonicalLineupSideCandidate,
    build_canonical_lineup_side_candidate,
)


CANONICAL_PROJECTED_LINEUP_DISCOVERY_VERSION = (
    "canonical_projected_lineup_discovery_v1"
)
PROJECTED_LINEUP_SOURCE = (
    "mlb_previous_completed_game_lineup"
)
PROJECTED_LINEUP_LOOKBACK_DAYS = 7


def _normalize_identifier(value: Any) -> Optional[str]:
    if value in (None, "") or isinstance(value, bool):
        return None

    try:
        return str(int(value))
    except (TypeError, ValueError):
        text = str(value).strip()
        return text or None


def _normalize_target_date(value: Any) -> Optional[str]:
    text = str(value or "").strip()

    if not text:
        return None

    try:
        return dt.date.fromisoformat(text[:10]).isoformat()
    except ValueError:
        return None


def _player_identifier(record: Any) -> Optional[str]:
    if not isinstance(record, Mapping):
        return None

    person = record.get("person")

    if not isinstance(person, Mapping):
        person = {}

    return _normalize_identifier(
        record.get("id")
        or record.get("player_id")
        or record.get("batter_id")
        or record.get("person_id")
        or person.get("id")
    )


def _ordered_player_ids(records: Any) -> Tuple[str, ...]:
    if (
        not isinstance(records, Sequence)
        or isinstance(records, (str, bytes))
    ):
        return ()

    identifiers = []

    for record in records:
        identifier = _player_identifier(record)

        if identifier is not None:
            identifiers.append(identifier)

    return tuple(identifiers)


def _team_side_for_game(
    game: Mapping[str, Any],
    team_id: str,
) -> Optional[str]:
    teams = game.get("teams")

    if not isinstance(teams, Mapping):
        return None

    for side in ("away", "home"):
        side_payload = teams.get(side)

        if not isinstance(side_payload, Mapping):
            continue

        team = side_payload.get("team")

        if not isinstance(team, Mapping):
            continue

        if _normalize_identifier(
            team.get("id")
        ) == team_id:
            return side

    return None


def _completed_game_candidates(
    payload: Mapping[str, Any],
    team_id: str,
) -> Tuple[Tuple[str, str, Tuple[str, ...], int], ...]:
    candidates = []

    dates = payload.get("dates")

    if (
        not isinstance(dates, Sequence)
        or isinstance(dates, (str, bytes))
    ):
        return ()

    for date_record in dates:
        if not isinstance(date_record, Mapping):
            continue

        games = date_record.get("games")

        if (
            not isinstance(games, Sequence)
            or isinstance(games, (str, bytes))
        ):
            continue

        for game in games:
            if not isinstance(game, Mapping):
                continue

            status = game.get("status")

            if not isinstance(status, Mapping):
                status = {}

            if status.get("codedGameState") != "F":
                continue

            game_side = _team_side_for_game(
                game,
                team_id,
            )

            if game_side is None:
                continue

            lineups = game.get("lineups")

            if not isinstance(lineups, Mapping):
                continue

            lineup_key = (
                "awayPlayers"
                if game_side == "away"
                else "homePlayers"
            )
            source_records = lineups.get(lineup_key)
            player_ids = _ordered_player_ids(
                source_records
            )

            if not player_ids:
                continue

            game_pk = _normalize_identifier(
                game.get("gamePk")
                or game.get("game_pk")
            )
            game_date = str(
                game.get("gameDate")
                or date_record.get("date")
                or ""
            ).strip()

            if game_pk is None or not game_date:
                continue

            source_count = (
                len(source_records)
                if isinstance(source_records, Sequence)
                and not isinstance(
                    source_records,
                    (str, bytes),
                )
                else 0
            )

            candidates.append(
                (
                    game_date,
                    game_pk,
                    player_ids,
                    source_count,
                )
            )

    candidates.sort(
        key=lambda item: (item[0], item[1]),
        reverse=True,
    )

    return tuple(candidates)


@dataclass(frozen=True)
class CanonicalProjectedLineupDiscovery:
    """One side's projected batting-order discovery."""

    team_side: str
    team_id: str
    target_game_date: str
    player_ids: Tuple[str, ...] = ()
    source_game_pk: Optional[str] = None
    source_game_date: Optional[str] = None
    source_record_count: int = 0
    status: str = "unavailable"
    error_type: Optional[str] = None
    error_message: Optional[str] = None
    discovery_version: str = (
        CANONICAL_PROJECTED_LINEUP_DISCOVERY_VERSION
    )

    def __post_init__(self) -> None:
        if self.team_side not in {"away", "home"}:
            raise ValueError(
                "team_side must be away or home"
            )

        if self.discovery_version != (
            CANONICAL_PROJECTED_LINEUP_DISCOVERY_VERSION
        ):
            raise ValueError(
                "unsupported projected-lineup "
                "discovery version"
            )

    @property
    def ready(self) -> bool:
        return (
            len(self.player_ids) == 9
            and len(set(self.player_ids)) == 9
        )

    @property
    def source_identifier(self) -> str:
        suffix = self.source_game_pk or "unavailable"

        return f"{PROJECTED_LINEUP_SOURCE}:{suffix}"

    @property
    def source_as_of(self) -> str:
        return (
            self.source_game_date
            or self.target_game_date
        )

    def to_candidate(
        self,
    ) -> CanonicalLineupSideCandidate:
        return build_canonical_lineup_side_candidate(
            team_side=self.team_side,
            player_ids=self.player_ids,
            lineup_source="projected",
            source_identifier=self.source_identifier,
            source_as_of=self.source_as_of,
            confidence="provisional_previous_lineup",
        )

    def to_diagnostics(self) -> Dict[str, Any]:
        candidate = self.to_candidate()

        return {
            "schema_version": self.discovery_version,
            "status": self.status,
            "ready": self.ready,
            "team_side": self.team_side,
            "source": PROJECTED_LINEUP_SOURCE,
            "source_game_pk": self.source_game_pk,
            "source_game_date": self.source_game_date,
            "source_record_count": (
                self.source_record_count
            ),
            "validated_player_count": len(
                self.player_ids
            ),
            "required_player_count": 9,
            "candidate_blockers": list(
                candidate.blockers
            ),
            "error_type": self.error_type,
            "error_message": self.error_message,
            "roster_fallback_used": False,
            "player_identifiers_exposed": False,
            "activation_permitted": False,
        }


def discover_canonical_projected_lineup(
    *,
    team_side: str,
    team_id: Any,
    target_game_date: Any,
    schedule_fetcher: Callable[..., Mapping[str, Any]],
) -> CanonicalProjectedLineupDiscovery:
    """
    Discover the latest completed-game batting order.

    The fetcher is injected and receives team_id,
    start_date, and end_date keyword arguments.
    """

    if team_side not in {"away", "home"}:
        raise ValueError(
            "team_side must be away or home"
        )

    normalized_team_id = _normalize_identifier(
        team_id
    )
    normalized_date = _normalize_target_date(
        target_game_date
    )

    if normalized_team_id is None:
        return CanonicalProjectedLineupDiscovery(
            team_side=team_side,
            team_id="",
            target_game_date=normalized_date or "",
            status="blocked",
            error_type="missing_team_id",
            error_message=(
                "team_id is required for projected "
                "lineup discovery"
            ),
        )

    if normalized_date is None:
        return CanonicalProjectedLineupDiscovery(
            team_side=team_side,
            team_id=normalized_team_id,
            target_game_date="",
            status="blocked",
            error_type="invalid_target_game_date",
            error_message=(
                "target_game_date must contain "
                "an ISO date"
            ),
        )

    end_date = dt.date.fromisoformat(
        normalized_date
    )
    start_date = (
        end_date
        - dt.timedelta(
            days=PROJECTED_LINEUP_LOOKBACK_DAYS
        )
    )

    try:
        payload = schedule_fetcher(
            team_id=int(normalized_team_id),
            start_date=start_date.isoformat(),
            end_date=end_date.isoformat(),
        )
    except Exception as exc:
        return CanonicalProjectedLineupDiscovery(
            team_side=team_side,
            team_id=normalized_team_id,
            target_game_date=normalized_date,
            status="error",
            error_type=type(exc).__name__,
            error_message=str(exc),
        )

    if not isinstance(payload, Mapping):
        return CanonicalProjectedLineupDiscovery(
            team_side=team_side,
            team_id=normalized_team_id,
            target_game_date=normalized_date,
            status="blocked",
            error_type="invalid_payload",
            error_message=(
                "schedule_fetcher must return "
                "a mapping"
            ),
        )

    candidates = _completed_game_candidates(
        payload,
        normalized_team_id,
    )

    if not candidates:
        return CanonicalProjectedLineupDiscovery(
            team_side=team_side,
            team_id=normalized_team_id,
            target_game_date=normalized_date,
            status="unavailable",
        )

    (
        source_game_date,
        source_game_pk,
        player_ids,
        source_record_count,
    ) = candidates[0]

    candidate = (
        build_canonical_lineup_side_candidate(
            team_side=team_side,
            player_ids=player_ids,
            lineup_source="projected",
            source_identifier=(
                f"{PROJECTED_LINEUP_SOURCE}:"
                f"{source_game_pk}"
            ),
            source_as_of=source_game_date,
            confidence=(
                "provisional_previous_lineup"
            ),
        )
    )

    return CanonicalProjectedLineupDiscovery(
        team_side=team_side,
        team_id=normalized_team_id,
        target_game_date=normalized_date,
        player_ids=player_ids,
        source_game_pk=source_game_pk,
        source_game_date=source_game_date,
        source_record_count=source_record_count,
        status=(
            "ready"
            if candidate.ready
            else "blocked"
        ),
    )
