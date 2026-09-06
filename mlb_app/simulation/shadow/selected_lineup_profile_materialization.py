"""Materialize selected projected-lineup hitter profiles."""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
from typing import Any, Callable, Dict, Mapping, Optional

from mlb_app.lineup_profile import (
    build_lineup_offense_inputs,
)


CANONICAL_SELECTED_LINEUP_PROFILE_MATERIALIZATION_VERSION = (
    "canonical_selected_lineup_profile_materialization_v1"
)


def _pitcher_hand(
    matchup: Mapping[str, Any],
    *,
    offense_side: str,
) -> str:
    pitcher_side = (
        "home" if offense_side == "away" else "away"
    )
    hand = str(
        matchup.get(f"{pitcher_side}_pitcher_hand")
        or matchup.get(f"{pitcher_side}_pitcher_throws")
        or ""
    ).strip().upper()

    return "L" if hand == "L" else "R"


def _projected_lineup_records(
    player_ids: Any,
) -> list[Dict[str, Any]]:
    return [
        {
            "batter_id": int(player_id),
            "batting_order": order * 100,
            "lineup_slot": order,
        }
        for order, player_id in enumerate(
            tuple(player_ids or ()),
            start=1,
        )
    ]


@dataclass(frozen=True)
class CanonicalSelectedLineupProfileMaterialization:
    """Atomic projected-lineup profile materialization."""

    away_context: Dict[str, Any]
    home_context: Dict[str, Any]
    status: str = "skipped"
    selected_source: Optional[str] = None
    away_profile_ready: bool = False
    home_profile_ready: bool = False
    away_profile_count: int = 0
    home_profile_count: int = 0
    blocker: Optional[str] = None
    error_type: Optional[str] = None
    error_message: Optional[str] = None
    schema_version: str = (
        CANONICAL_SELECTED_LINEUP_PROFILE_MATERIALIZATION_VERSION
    )

    @property
    def ready(self) -> bool:
        return (
            self.status == "ready"
            and self.away_profile_ready
            and self.home_profile_ready
        )

    def to_diagnostics(self) -> Dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "status": self.status,
            "ready": self.ready,
            "selected_source": self.selected_source,
            "away": {
                "ready": self.away_profile_ready,
                "profile_count": self.away_profile_count,
                "required_profile_count": 9,
            },
            "home": {
                "ready": self.home_profile_ready,
                "profile_count": self.home_profile_count,
                "required_profile_count": 9,
            },
            "blocker": self.blocker,
            "error_type": self.error_type,
            "error_message": self.error_message,
            "atomic_context_replacement": True,
            "player_identifiers_exposed": False,
            "activation_permitted": False,
            "production_authority_changed": False,
            "authoritative_source": "legacy",
        }


def materialize_canonical_selected_lineup_profiles(
    *,
    session: Any,
    matchup: Mapping[str, Any],
    away_context: Mapping[str, Any],
    home_context: Mapping[str, Any],
    lineups: Any,
    season: int,
    profile_builder: Callable[
        ..., Optional[Dict[str, Any]]
    ] = build_lineup_offense_inputs,
) -> CanonicalSelectedLineupProfileMaterialization:
    """
    Build player-level inputs for a projected selection.

    Both sides must produce nine ordered usable hitter rows.
    Otherwise both original contexts are returned unchanged.
    """

    original_away = deepcopy(dict(away_context))
    original_home = deepcopy(dict(home_context))
    selected_source = getattr(
        lineups,
        "lineup_source",
        None,
    )

    if selected_source != "projected":
        return CanonicalSelectedLineupProfileMaterialization(
            away_context=original_away,
            home_context=original_home,
            status="skipped",
            selected_source=selected_source,
            blocker="selected_lineup_is_not_projected",
        )

    game_pk = (
        matchup.get("game_pk")
        or matchup.get("gamePk")
    )

    if not game_pk:
        return CanonicalSelectedLineupProfileMaterialization(
            away_context=original_away,
            home_context=original_home,
            status="blocked",
            selected_source=selected_source,
            blocker="missing_game_pk",
        )

    built: Dict[str, Dict[str, Any]] = {}
    counts: Dict[str, int] = {
        "away": 0,
        "home": 0,
    }

    try:
        for side, context in (
            ("away", original_away),
            ("home", original_home),
        ):
            player_ids = tuple(
                getattr(
                    lineups,
                    f"{side}_player_ids",
                    (),
                )
            )

            if (
                len(player_ids) != 9
                or len(set(player_ids)) != 9
            ):
                return (
                    CanonicalSelectedLineupProfileMaterialization(
                        away_context=original_away,
                        home_context=original_home,
                        status="blocked",
                        selected_source=selected_source,
                        blocker=(
                            f"{side}_selected_lineup_"
                            "requires_9_unique_players"
                        ),
                    )
                )

            fallback = deepcopy(
                dict(
                    context.get("offense_inputs")
                    or {}
                )
            )
            records = _projected_lineup_records(
                player_ids
            )
            profile = profile_builder(
                session=session,
                game_pk=int(game_pk),
                side=side,
                team_id=int(context.get("team_id")),
                season=int(season),
                split=(
                    "vsL"
                    if _pitcher_hand(
                        matchup,
                        offense_side=side,
                    ) == "L"
                    else "vsR"
                ),
                team_fallback=fallback,
                lineups={side: records},
            )

            if not isinstance(profile, dict):
                return (
                    CanonicalSelectedLineupProfileMaterialization(
                        away_context=original_away,
                        home_context=original_home,
                        status="blocked",
                        selected_source=selected_source,
                        blocker=(
                            f"{side}_projected_lineup_"
                            "profiles_unavailable"
                        ),
                        away_profile_ready=(
                            "away" in built
                        ),
                        home_profile_ready=(
                            "home" in built
                        ),
                        away_profile_count=counts["away"],
                        home_profile_count=counts["home"],
                    )
                )

            lineup_rows = profile.get("lineup")

            if not isinstance(lineup_rows, list):
                lineup_rows = []

            counts[side] = len(lineup_rows)

            if len(lineup_rows) != 9:
                return (
                    CanonicalSelectedLineupProfileMaterialization(
                        away_context=original_away,
                        home_context=original_home,
                        status="blocked",
                        selected_source=selected_source,
                        blocker=(
                            f"{side}_projected_lineup_"
                            "requires_9_profiles"
                        ),
                        away_profile_ready=(
                            side == "away"
                            and len(lineup_rows) == 9
                        ),
                        home_profile_ready=(
                            side == "home"
                            and len(lineup_rows) == 9
                        ),
                        away_profile_count=counts["away"],
                        home_profile_count=counts["home"],
                    )
                )

            enriched = deepcopy(profile)
            enriched.update({
                "lineup_source": "projected",
                "lineup_digest": getattr(
                    lineups,
                    "lineup_digest",
                    None,
                ),
                "lineup_confidence": getattr(
                    lineups,
                    "confidence",
                    None,
                ),
                "profile_granularity": (
                    "projected_player_lineup"
                ),
            })
            built[side] = enriched
    except Exception as exc:
        return CanonicalSelectedLineupProfileMaterialization(
            away_context=original_away,
            home_context=original_home,
            status="error",
            selected_source=selected_source,
            blocker="profile_materialization_error",
            error_type=type(exc).__name__,
            error_message=str(exc),
            away_profile_ready=("away" in built),
            home_profile_ready=("home" in built),
            away_profile_count=counts["away"],
            home_profile_count=counts["home"],
        )

    materialized_away = deepcopy(original_away)
    materialized_home = deepcopy(original_home)
    materialized_away["offense_inputs"] = built["away"]
    materialized_home["offense_inputs"] = built["home"]

    return CanonicalSelectedLineupProfileMaterialization(
        away_context=materialized_away,
        home_context=materialized_home,
        status="ready",
        selected_source=selected_source,
        away_profile_ready=True,
        home_profile_ready=True,
        away_profile_count=counts["away"],
        home_profile_count=counts["home"],
    )
