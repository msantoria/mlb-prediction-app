"""Reconstruct historical PA probability workspaces."""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
from typing import Any, Dict, Mapping, Tuple

from mlb_app.simulation.pa_outcome_model import (
    build_pa_outcome_probabilities,
)

from .historical_lineup_bullpen_source import (
    CanonicalHistoricalLineupBullpenWindow,
)
from .historical_probability_statistics_source import (
    CanonicalHistoricalProbabilityGameStatistics,
    CanonicalHistoricalProbabilityStatisticsWindow,
)
from .probability_provider_discovery import (
    REQUIRED_WORKSPACE_MODELS,
    discover_canonical_shadow_probability_provider,
)


CANONICAL_HISTORICAL_PA_WORKSPACE_RECONSTRUCTION_VERSION = (
    "canonical_historical_pa_workspace_reconstruction_v1"
)
HISTORICAL_PA_WORKSPACE_ENVIRONMENT_POLICY = (
    "neutral_environment_no_archived_forecast_v1"
)


def _sha256(value: Any) -> str:
    return hashlib.sha256(
        json.dumps(
            value,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()


def _identifier(value: Any) -> str | None:
    if value in (None, "") or isinstance(value, bool):
        return None

    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return None

    return str(parsed) if parsed > 0 else None


def _counts(
    game: CanonicalHistoricalProbabilityGameStatistics,
    *,
    role: str,
    player_ids: Tuple[str, ...],
) -> Dict[str, int]:
    requested = set(player_ids)
    aggregate: Dict[str, int] = {}

    records = {
        value.player_id: value
        for value in game.players
        if value.role == role
    }

    if not requested:
        raise ValueError(
            f"{role} player_ids cannot be empty"
        )

    if not requested.issubset(records):
        raise ValueError(
            f"historical statistics missing required {role} players"
        )

    for player_id in sorted(
        requested,
        key=int,
    ):
        for key, value in records[player_id].counts:
            aggregate[key] = (
                aggregate.get(key, 0)
                + value
            )

    return aggregate


def _rate(
    numerator: int,
    denominator: int,
) -> float | None:
    if denominator <= 0:
        return None
    return numerator / denominator


def build_historical_probability_offense_profile(
    counts: Mapping[str, int],
) -> Dict[str, Any]:
    pa = counts.get("pa", 0)
    ab = counts.get("ab", 0)
    hits = counts.get("hits", 0)
    doubles = counts.get("double", 0)
    triples = counts.get("triple", 0)
    home_runs = counts.get("hr", 0)
    strikeouts = counts.get("k", 0)
    walks = counts.get("bb", 0)

    extra_bases = (
        doubles
        + (2 * triples)
        + (3 * home_runs)
    )

    return {
        "contact_skill": {
            "k_rate": _rate(strikeouts, pa),
            "contact_rate": _rate(
                pa - strikeouts,
                pa,
            ),
            "batting_avg": _rate(hits, ab),
        },
        "plate_discipline": {
            "bb_rate": _rate(walks, pa),
        },
        "power": {
            "iso": _rate(extra_bases, ab),
            "barrel_rate": None,
            "hard_hit_rate": None,
        },
        "historical_sample": {
            "plate_appearances": pa,
            "at_bats": ab,
        },
    }


def build_historical_probability_pitcher_profile(
    counts: Mapping[str, int],
) -> Dict[str, Any]:
    batters_faced = counts.get(
        "batters_faced",
        0,
    )
    at_bats = counts.get("ab", 0)
    hits = counts.get("hits", 0)
    strikeouts = counts.get("k", 0)
    walks = counts.get("bb", 0)

    return {
        "bat_missing": {
            "k_rate": _rate(
                strikeouts,
                batters_faced,
            ),
        },
        "command_control": {
            "bb_rate": _rate(
                walks,
                batters_faced,
            ),
        },
        "contact_management": {
            "xba_allowed": _rate(
                hits,
                at_bats,
            ),
            "barrel_rate_allowed": None,
            "hard_hit_rate_allowed": None,
        },
        "historical_sample": {
            "batters_faced": batters_faced,
            "at_bats": at_bats,
        },
    }


def _model(
    *,
    offense_counts: Mapping[str, int],
    pitcher_counts: Mapping[str, int],
) -> Dict[str, Any]:
    result = build_pa_outcome_probabilities(
        batter_profile=build_historical_probability_offense_profile(
            offense_counts
        ),
        pitcher_profile=build_historical_probability_pitcher_profile(
            pitcher_counts
        ),
        environment_profile=None,
    )

    return {
        **result,
        "historical_environment_policy": (
            HISTORICAL_PA_WORKSPACE_ENVIRONMENT_POLICY
        ),
        "historical_reconstruction": True,
    }


@dataclass(frozen=True)
class CanonicalHistoricalPaProbabilityWorkspaceGame:
    game_pk: int
    game_date: str
    statistics_through_date: str
    statistics_snapshot_digest: str
    workspace: Mapping[str, Mapping[str, Any]]
    provider_identity: str
    digest: str
    reconstruction_version: str = (
        CANONICAL_HISTORICAL_PA_WORKSPACE_RECONSTRUCTION_VERSION
    )

    def __post_init__(self) -> None:
        if (
            isinstance(self.game_pk, bool)
            or self.game_pk <= 0
        ):
            raise ValueError(
                "game_pk must be positive"
            )

        if tuple(self.workspace) != (
            REQUIRED_WORKSPACE_MODELS
        ):
            raise ValueError(
                "workspace must contain all required "
                "PA models in canonical order"
            )

        discovery = (
            discover_canonical_shadow_probability_provider(
                workspace=self.workspace
            )
        )
        if not discovery.ready:
            raise ValueError(
                "historical workspace provider must be ready"
            )
        if (
            discovery.provider is None
            or discovery.provider.identity
            != self.provider_identity
        ):
            raise ValueError(
                "provider_identity must match workspace"
            )

        for name, value in (
            (
                "statistics_snapshot_digest",
                self.statistics_snapshot_digest,
            ),
            ("digest", self.digest),
        ):
            if (
                len(value) != 64
                or any(
                    character not in "0123456789abcdef"
                    for character in value
                )
            ):
                raise ValueError(
                    f"{name} must be a SHA256 digest"
                )

        if self.reconstruction_version != (
            CANONICAL_HISTORICAL_PA_WORKSPACE_RECONSTRUCTION_VERSION
        ):
            raise ValueError(
                "unsupported historical PA workspace "
                "reconstruction version"
            )

    @property
    def model_versions(self) -> Tuple[str, ...]:
        return tuple(
            sorted(
                {
                    str(
                        self.workspace[key][
                            "model_version"
                        ]
                    )
                    for key in REQUIRED_WORKSPACE_MODELS
                }
            )
        )

    def to_diagnostics(self) -> Dict[str, Any]:
        return {
            "game_pk": self.game_pk,
            "game_date": self.game_date,
            "statistics_through_date": (
                self.statistics_through_date
            ),
            "statistics_snapshot_digest": (
                self.statistics_snapshot_digest
            ),
            "workspace_digest": self.digest,
            "ready": True,
            "valid_model_count": len(
                REQUIRED_WORKSPACE_MODELS
            ),
            "required_model_count": len(
                REQUIRED_WORKSPACE_MODELS
            ),
            "model_versions": self.model_versions,
            "provider_identity": (
                self.provider_identity
            ),
            "historical_environment_policy": (
                HISTORICAL_PA_WORKSPACE_ENVIRONMENT_POLICY
            ),
            "probability_records_exposed": False,
            "exact_artifact_built": False,
            "historical_replay_executed": False,
            "activation_permitted": False,
            "authoritative_source": "legacy",
        }


@dataclass(frozen=True)
class CanonicalHistoricalPaProbabilityWorkspaceWindow:
    observed_window_digest: str
    statistics_window_digest: str
    games: Tuple[
        CanonicalHistoricalPaProbabilityWorkspaceGame,
        ...,
    ]
    digest: str
    reconstruction_version: str = (
        CANONICAL_HISTORICAL_PA_WORKSPACE_RECONSTRUCTION_VERSION
    )

    def __post_init__(self) -> None:
        if not self.games:
            raise ValueError(
                "games must contain historical workspaces"
            )

        identities = tuple(
            value.game_pk
            for value in self.games
        )
        if len(identities) != len(set(identities)):
            raise ValueError(
                "workspace game identifiers must be unique"
            )

        providers = {
            value.provider_identity
            for value in self.games
        }
        if len(providers) != 1:
            raise ValueError(
                "historical workspaces must use one provider"
            )

        for name, value in (
            (
                "observed_window_digest",
                self.observed_window_digest,
            ),
            (
                "statistics_window_digest",
                self.statistics_window_digest,
            ),
            ("digest", self.digest),
        ):
            if (
                len(value) != 64
                or any(
                    character not in "0123456789abcdef"
                    for character in value
                )
            ):
                raise ValueError(
                    f"{name} must be a SHA256 digest"
                )

        if self.reconstruction_version != (
            CANONICAL_HISTORICAL_PA_WORKSPACE_RECONSTRUCTION_VERSION
        ):
            raise ValueError(
                "unsupported historical PA workspace window"
            )

    @property
    def game_count(self) -> int:
        return len(self.games)

    @property
    def provider_identity(self) -> str:
        return self.games[0].provider_identity

    @property
    def model_versions(self) -> Tuple[str, ...]:
        return tuple(
            sorted(
                {
                    version
                    for game in self.games
                    for version in game.model_versions
                }
            )
        )

    def to_diagnostics(self) -> Dict[str, Any]:
        return {
            "schema_version": (
                self.reconstruction_version
            ),
            "ready": True,
            "game_count": self.game_count,
            "ready_game_count": self.game_count,
            "provider_identity": (
                self.provider_identity
            ),
            "model_versions": self.model_versions,
            "observed_window_digest": (
                self.observed_window_digest
            ),
            "statistics_window_digest": (
                self.statistics_window_digest
            ),
            "workspace_window_digest": self.digest,
            "historical_environment_policy": (
                HISTORICAL_PA_WORKSPACE_ENVIRONMENT_POLICY
            ),
            "games": tuple(
                value.to_diagnostics()
                for value in self.games
            ),
            "probability_records_exposed": False,
            "exact_artifacts_built": False,
            "fallback_catalogs_built": False,
            "historical_replay_executed": False,
            "production_activation": False,
            "production_authority_changed": False,
            "authoritative_source": "legacy",
        }


def reconstruct_historical_pa_probability_workspaces(
    *,
    lineup_bullpen: CanonicalHistoricalLineupBullpenWindow,
    statistics: CanonicalHistoricalProbabilityStatisticsWindow,
    starting_pitcher_ids: Mapping[
        int,
        Tuple[str, str],
    ],
) -> CanonicalHistoricalPaProbabilityWorkspaceWindow:
    """Build four production-formula PA models for every historical game."""

    if not isinstance(
        lineup_bullpen,
        CanonicalHistoricalLineupBullpenWindow,
    ):
        raise TypeError(
            "lineup_bullpen must be a "
            "CanonicalHistoricalLineupBullpenWindow"
        )
    if not isinstance(
        statistics,
        CanonicalHistoricalProbabilityStatisticsWindow,
    ):
        raise TypeError(
            "statistics must be a "
            "CanonicalHistoricalProbabilityStatisticsWindow"
        )
    if not isinstance(starting_pitcher_ids, Mapping):
        raise TypeError(
            "starting_pitcher_ids must be a mapping"
        )

    if (
        statistics.observed_window_digest
        != lineup_bullpen.observed_window_digest
    ):
        raise ValueError(
            "statistics observed window must match rosters"
        )
    if (
        statistics.lineup_bullpen_window_digest
        != lineup_bullpen.digest
    ):
        raise ValueError(
            "statistics roster window must match rosters"
        )

    rosters = {
        value.game_pk: value
        for value in lineup_bullpen.games
    }
    statistics_games = {
        value.game_pk: value
        for value in statistics.games
    }

    if set(rosters) != set(statistics_games):
        raise ValueError(
            "statistics must exactly cover roster games"
        )

    normalized_starters = {}
    for raw_game_pk, raw_pair in (
        starting_pitcher_ids.items()
    ):
        try:
            game_pk = int(raw_game_pk)
        except (TypeError, ValueError) as exc:
            raise ValueError(
                "starter game identifiers must be integers"
            ) from exc

        if (
            not isinstance(raw_pair, tuple)
            or len(raw_pair) != 2
        ):
            raise TypeError(
                "starter values must be away-home tuples"
            )

        away = _identifier(raw_pair[0])
        home = _identifier(raw_pair[1])
        if away is None or home is None:
            raise ValueError(
                "starter identifiers are required"
            )

        normalized_starters[game_pk] = (
            away,
            home,
        )

    if set(normalized_starters) != set(rosters):
        raise ValueError(
            "starters must exactly cover historical games"
        )

    reconstructed = []

    for game_pk, roster in sorted(
        rosters.items(),
        key=lambda item: (
            item[1].game_date,
            item[0],
        ),
    ):
        statistics_game = statistics_games[game_pk]
        if statistics_game.game_date != roster.game_date:
            raise ValueError(
                "statistics game_date must match roster"
            )

        away_starter, home_starter = (
            normalized_starters[game_pk]
        )

        away_offense = _counts(
            statistics_game,
            role="hitting",
            player_ids=roster.away_lineup_ids,
        )
        home_offense = _counts(
            statistics_game,
            role="hitting",
            player_ids=roster.home_lineup_ids,
        )
        away_starter_counts = _counts(
            statistics_game,
            role="pitching",
            player_ids=(away_starter,),
        )
        home_starter_counts = _counts(
            statistics_game,
            role="pitching",
            player_ids=(home_starter,),
        )
        away_bullpen = _counts(
            statistics_game,
            role="pitching",
            player_ids=roster.away_bullpen_ids,
        )
        home_bullpen = _counts(
            statistics_game,
            role="pitching",
            player_ids=roster.home_bullpen_ids,
        )

        workspace = {
            "awayPAOutcomeModel": _model(
                offense_counts=away_offense,
                pitcher_counts=home_starter_counts,
            ),
            "homePAOutcomeModel": _model(
                offense_counts=home_offense,
                pitcher_counts=away_starter_counts,
            ),
            "awayVsHomeBullpenPAOutcomeModel": _model(
                offense_counts=away_offense,
                pitcher_counts=home_bullpen,
            ),
            "homeVsAwayBullpenPAOutcomeModel": _model(
                offense_counts=home_offense,
                pitcher_counts=away_bullpen,
            ),
        }

        discovery = (
            discover_canonical_shadow_probability_provider(
                workspace=workspace
            )
        )
        if (
            not discovery.ready
            or discovery.provider is None
        ):
            raise ValueError(
                "reconstructed workspace provider "
                "must be ready"
            )

        game_digest = _sha256(
            {
                "game_pk": game_pk,
                "game_date": roster.game_date,
                "statistics_through_date": (
                    statistics_game
                    .statistics_through_date
                ),
                "statistics_snapshot_digest": (
                    statistics_game.snapshot_digest
                ),
                "provider_identity": (
                    discovery.provider.identity
                ),
                "environment_policy": (
                    HISTORICAL_PA_WORKSPACE_ENVIRONMENT_POLICY
                ),
                "workspace": workspace,
            }
        )

        reconstructed.append(
            CanonicalHistoricalPaProbabilityWorkspaceGame(
                game_pk=game_pk,
                game_date=roster.game_date,
                statistics_through_date=(
                    statistics_game
                    .statistics_through_date
                ),
                statistics_snapshot_digest=(
                    statistics_game.snapshot_digest
                ),
                workspace=workspace,
                provider_identity=(
                    discovery.provider.identity
                ),
                digest=game_digest,
            )
        )

    window_digest = _sha256(
        {
            "schema_version": (
                CANONICAL_HISTORICAL_PA_WORKSPACE_RECONSTRUCTION_VERSION
            ),
            "observed_window_digest": (
                lineup_bullpen.observed_window_digest
            ),
            "statistics_window_digest": (
                statistics.digest
            ),
            "games": [
                {
                    "game_pk": value.game_pk,
                    "game_date": value.game_date,
                    "digest": value.digest,
                    "provider_identity": (
                        value.provider_identity
                    ),
                }
                for value in reconstructed
            ],
        }
    )

    return CanonicalHistoricalPaProbabilityWorkspaceWindow(
        observed_window_digest=(
            lineup_bullpen.observed_window_digest
        ),
        statistics_window_digest=statistics.digest,
        games=tuple(reconstructed),
        digest=window_digest,
    )
