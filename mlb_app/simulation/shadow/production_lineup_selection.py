"""Production handoff for canonical lineup selection."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Dict, Mapping, Optional

import requests

from .lineup_discovery import (
    CanonicalShadowLineupDiscovery,
    discover_canonical_shadow_lineups,
)
from .projected_lineup_discovery import (
    CanonicalProjectedLineupDiscovery,
    discover_canonical_projected_lineup,
)
from .selected_lineup import (
    CanonicalSelectedLineupSelection,
    build_canonical_lineup_side_candidate,
    select_canonical_lineup,
)


CANONICAL_PRODUCTION_LINEUP_SELECTION_VERSION = (
    "canonical_production_lineup_selection_v1"
)
MLB_SCHEDULE_URL = (
    "https://statsapi.mlb.com/api/v1/schedule"
)


def fetch_projected_lineup_schedule(
    *,
    team_id: int,
    start_date: str,
    end_date: str,
    request_get: Callable[..., Any] = requests.get,
) -> Mapping[str, Any]:
    """Fetch completed-game lineups for one team."""

    response = request_get(
        MLB_SCHEDULE_URL,
        params={
            "sportId": 1,
            "teamId": int(team_id),
            "startDate": start_date,
            "endDate": end_date,
            "hydrate": "lineups,team",
        },
        timeout=20,
    )
    response.raise_for_status()
    payload = response.json()

    if not isinstance(payload, Mapping):
        raise TypeError(
            "MLB schedule response must be a mapping"
        )

    return payload


def _skipped_projected_discovery(
    *,
    team_side: str,
    team_id: Any,
    target_game_date: Any,
    status: str,
) -> CanonicalProjectedLineupDiscovery:
    return CanonicalProjectedLineupDiscovery(
        team_side=team_side,
        team_id=str(team_id or ""),
        target_game_date=str(target_game_date or ""),
        status=status,
    )


@dataclass(frozen=True)
class CanonicalProductionLineupSelection:
    """Confirmed/projected production selection bundle."""

    confirmed: CanonicalShadowLineupDiscovery
    projected_away: CanonicalProjectedLineupDiscovery
    projected_home: CanonicalProjectedLineupDiscovery
    selection: CanonicalSelectedLineupSelection
    schema_version: str = (
        CANONICAL_PRODUCTION_LINEUP_SELECTION_VERSION
    )

    @property
    def lineups(self) -> Any:
        """
        Return the selected lineup when ready.

        A blocked selection returns confirmed discovery so existing
        fail-closed readiness behavior remains intact.
        """

        return (
            self.selection.selected
            if self.selection.ready
            else self.confirmed
        )

    def to_diagnostics(self) -> Dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "status": (
                "ready"
                if self.selection.ready
                else "blocked"
            ),
            "confirmed": self.confirmed.to_diagnostics(),
            "projected": {
                "away": (
                    self.projected_away.to_diagnostics()
                ),
                "home": (
                    self.projected_home.to_diagnostics()
                ),
            },
            "selection": (
                self.selection.to_diagnostics()
            ),
            "selected_source": (
                self.selection.selected.lineup_source
                if self.selection.selected is not None
                else None
            ),
            "production_authority_changed": False,
            "authoritative_source": "legacy",
        }


def discover_canonical_production_lineup(
    *,
    game_pk: Any,
    away_team_id: Any,
    home_team_id: Any,
    target_game_date: Any,
    confirmed_discovery: Optional[
        CanonicalShadowLineupDiscovery
    ] = None,
    confirmed_lineup_fetcher: Optional[
        Callable[[int], Mapping[str, Any]]
    ] = None,
    schedule_fetcher: Callable[
        ..., Mapping[str, Any]
    ] = fetch_projected_lineup_schedule,
) -> CanonicalProductionLineupSelection:
    """
    Prefer complete confirmed lineups and otherwise use
    complete projected lineups.

    Partial confirmed data never mixes with projected data.
    Projected discovery is skipped unless both confirmed sides
    are absent.
    """

    confirmed = (
        confirmed_discovery
        if confirmed_discovery is not None
        else discover_canonical_shadow_lineups(
            game_pk=game_pk,
            lineup_fetcher=confirmed_lineup_fetcher,
        )
    )

    confirmed_away = (
        build_canonical_lineup_side_candidate(
            team_side="away",
            player_ids=confirmed.away_player_ids,
            lineup_source="confirmed",
            source_identifier=(
                f"mlb_stats_boxscore:{game_pk}"
            ),
            source_as_of=str(
                target_game_date or ""
            ),
            confidence="confirmed",
        )
    )
    confirmed_home = (
        build_canonical_lineup_side_candidate(
            team_side="home",
            player_ids=confirmed.home_player_ids,
            lineup_source="confirmed",
            source_identifier=(
                f"mlb_stats_boxscore:{game_pk}"
            ),
            source_as_of=str(
                target_game_date or ""
            ),
            confidence="confirmed",
        )
    )

    confirmed_present = bool(
        confirmed.away_player_ids
        or confirmed.home_player_ids
    )

    if confirmed_present:
        skipped_status = (
            "skipped_confirmed_ready"
            if confirmed.ready
            else "skipped_confirmed_partial"
        )
        projected_away = _skipped_projected_discovery(
            team_side="away",
            team_id=away_team_id,
            target_game_date=target_game_date,
            status=skipped_status,
        )
        projected_home = _skipped_projected_discovery(
            team_side="home",
            team_id=home_team_id,
            target_game_date=target_game_date,
            status=skipped_status,
        )
    else:
        projected_away = (
            discover_canonical_projected_lineup(
                team_side="away",
                team_id=away_team_id,
                target_game_date=target_game_date,
                schedule_fetcher=schedule_fetcher,
            )
        )
        projected_home = (
            discover_canonical_projected_lineup(
                team_side="home",
                team_id=home_team_id,
                target_game_date=target_game_date,
                schedule_fetcher=schedule_fetcher,
            )
        )

    selection = select_canonical_lineup(
        game_pk=game_pk,
        confirmed_away=confirmed_away,
        confirmed_home=confirmed_home,
        projected_away=projected_away.to_candidate(),
        projected_home=projected_home.to_candidate(),
    )

    return CanonicalProductionLineupSelection(
        confirmed=confirmed,
        projected_away=projected_away,
        projected_home=projected_home,
        selection=selection,
    )
