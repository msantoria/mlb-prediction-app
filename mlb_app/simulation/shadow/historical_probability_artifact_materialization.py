"""Materialize historical exact PA artifacts and fallback catalogs."""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
from typing import Any, Dict, Mapping, Tuple

from mlb_app.simulation.game import (
    CanonicalProbabilityArtifact,
    CanonicalProbabilityArtifactRecord,
    CanonicalProbabilityFallbackCatalog,
)
from mlb_app.simulation.pa_outcome_model import (
    build_pa_outcome_probabilities,
)

from .exact_artifact_discovery import (
    _canonical_probabilities,
)
from .fallback_catalog_discovery import (
    discover_canonical_shadow_fallback_catalog,
)
from .historical_lineup_bullpen_source import (
    CanonicalHistoricalLineupBullpenWindow,
)
from .historical_probability_artifact_inventory import (
    HISTORICAL_PROBABILITY_ARTIFACT_SOURCE,
    CanonicalHistoricalProbabilityArtifactRecord,
)
from .historical_probability_statistics_source import (
    CanonicalHistoricalProbabilityGameStatistics,
    CanonicalHistoricalProbabilityPlayerStatistics,
    CanonicalHistoricalProbabilityStatisticsWindow,
)
from .historical_probability_workspace_reconstruction import (
    CanonicalHistoricalPaProbabilityWorkspaceWindow,
    build_historical_probability_offense_profile,
    build_historical_probability_pitcher_profile,
)
from .probability_provider_discovery import (
    discover_canonical_shadow_probability_provider,
)


CANONICAL_HISTORICAL_PROBABILITY_ARTIFACT_MATERIALIZATION_VERSION = (
    "canonical_historical_probability_artifact_materialization_v1"
)


def _sha256(value: Any) -> str:
    return hashlib.sha256(
        json.dumps(
            value,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()


def _identifier(value: Any) -> str:
    if value in (None, "") or isinstance(value, bool):
        raise ValueError("player identifier is required")

    try:
        parsed = int(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(
            "player identifier must be a positive integer"
        ) from exc

    if parsed <= 0:
        raise ValueError(
            "player identifier must be a positive integer"
        )

    return str(parsed)


def _unique(values: Tuple[str, ...]) -> Tuple[str, ...]:
    return tuple(dict.fromkeys(values))


def _record_map(
    game: CanonicalHistoricalProbabilityGameStatistics,
) -> Dict[
    Tuple[str, str],
    CanonicalHistoricalProbabilityPlayerStatistics,
]:
    return {
        value.record_key: value
        for value in game.players
    }


def _counts(
    record: CanonicalHistoricalProbabilityPlayerStatistics,
) -> Dict[str, int]:
    return dict(record.counts)


def _distribution(
    *,
    batter: CanonicalHistoricalProbabilityPlayerStatistics,
    pitcher: CanonicalHistoricalProbabilityPlayerStatistics,
):
    model = build_pa_outcome_probabilities(
        batter_profile=build_historical_probability_offense_profile(
            _counts(batter)
        ),
        pitcher_profile=build_historical_probability_pitcher_profile(
            _counts(pitcher)
        ),
        environment_profile=None,
    )
    result = _canonical_probabilities(
        model.get("probabilities")
    )

    if result is None:
        raise ValueError(
            "historical probability model produced "
            "an invalid canonical distribution"
        )

    return result


@dataclass(frozen=True)
class CanonicalHistoricalProbabilityArtifactGame:
    game_pk: int
    game_date: str
    statistics_snapshot_digest: str
    workspace_digest: str
    exact_artifact: CanonicalProbabilityArtifact
    fallback_catalog: CanonicalProbabilityFallbackCatalog
    possible_matchup_count: int
    zero_sample_matchup_count: int
    digest: str
    materialization_version: str = (
        CANONICAL_HISTORICAL_PROBABILITY_ARTIFACT_MATERIALIZATION_VERSION
    )

    def __post_init__(self) -> None:
        if (
            isinstance(self.game_pk, bool)
            or self.game_pk <= 0
        ):
            raise ValueError("game_pk must be positive")

        if (
            self.exact_artifact.provider
            != self.fallback_catalog.provider
        ):
            raise ValueError(
                "exact artifact and fallback catalog "
                "must use the same provider"
            )

        if self.possible_matchup_count <= 0:
            raise ValueError(
                "possible_matchup_count must be positive"
            )

        if not (
            0
            <= self.zero_sample_matchup_count
            <= self.possible_matchup_count
        ):
            raise ValueError(
                "zero_sample_matchup_count is invalid"
            )

        if len(self.exact_artifact.records) != (
            self.possible_matchup_count
            - self.zero_sample_matchup_count
        ):
            raise ValueError(
                "exact artifact coverage must match "
                "materialized matchup counts"
            )

        for name, value in (
            (
                "statistics_snapshot_digest",
                self.statistics_snapshot_digest,
            ),
            ("workspace_digest", self.workspace_digest),
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

        if self.materialization_version != (
            CANONICAL_HISTORICAL_PROBABILITY_ARTIFACT_MATERIALIZATION_VERSION
        ):
            raise ValueError(
                "unsupported historical probability "
                "artifact materialization version"
            )

    @property
    def provider_identity(self) -> str:
        return self.exact_artifact.provider.identity

    @property
    def exact_record_count(self) -> int:
        return len(self.exact_artifact.records)

    def to_inventory_record(
        self,
    ) -> CanonicalHistoricalProbabilityArtifactRecord:
        return CanonicalHistoricalProbabilityArtifactRecord(
            game_pk=self.game_pk,
            game_date=self.game_date,
            source=HISTORICAL_PROBABILITY_ARTIFACT_SOURCE,
            artifact_as_of_date=self.game_date,
            provider_identity=self.provider_identity,
            exact_artifact_digest=(
                self.exact_artifact.digest
            ),
            fallback_catalog_digest=(
                self.fallback_catalog.digest
            ),
        )

    def to_diagnostics(self) -> Dict[str, Any]:
        return {
            "game_pk": self.game_pk,
            "game_date": self.game_date,
            "ready": True,
            "provider_identity": self.provider_identity,
            "possible_matchup_count": (
                self.possible_matchup_count
            ),
            "exact_record_count": self.exact_record_count,
            "zero_sample_matchup_count": (
                self.zero_sample_matchup_count
            ),
            "fallback_record_count": len(
                self.fallback_catalog.records
            ),
            "exact_artifact_digest": (
                self.exact_artifact.digest
            ),
            "fallback_catalog_digest": (
                self.fallback_catalog.digest
            ),
            "materialization_digest": self.digest,
            "statistics_snapshot_digest": (
                self.statistics_snapshot_digest
            ),
            "workspace_digest": self.workspace_digest,
            "zero_sample_rows_labeled_exact": False,
            "reached_on_error_mapping": (
                "folded_into_canonical_out"
            ),
            "probability_records_exposed": False,
            "historical_replay_executed": False,
            "activation_permitted": False,
            "authoritative_source": "legacy",
        }


@dataclass(frozen=True)
class CanonicalHistoricalProbabilityArtifactWindow:
    observed_window_digest: str
    statistics_window_digest: str
    workspace_window_digest: str
    games: Tuple[
        CanonicalHistoricalProbabilityArtifactGame,
        ...,
    ]
    digest: str
    materialization_version: str = (
        CANONICAL_HISTORICAL_PROBABILITY_ARTIFACT_MATERIALIZATION_VERSION
    )

    def __post_init__(self) -> None:
        if not self.games:
            raise ValueError(
                "games must contain materialized artifacts"
            )

        identities = tuple(
            value.game_pk for value in self.games
        )
        if len(identities) != len(set(identities)):
            raise ValueError(
                "artifact game identifiers must be unique"
            )

        providers = {
            value.provider_identity
            for value in self.games
        }
        if len(providers) != 1:
            raise ValueError(
                "historical artifacts must use one provider"
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
            (
                "workspace_window_digest",
                self.workspace_window_digest,
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

        if self.materialization_version != (
            CANONICAL_HISTORICAL_PROBABILITY_ARTIFACT_MATERIALIZATION_VERSION
        ):
            raise ValueError(
                "unsupported historical probability "
                "artifact window version"
            )

    @property
    def game_count(self) -> int:
        return len(self.games)

    @property
    def provider_identity(self) -> str:
        return self.games[0].provider_identity

    @property
    def exact_record_count(self) -> int:
        return sum(
            value.exact_record_count
            for value in self.games
        )

    @property
    def possible_matchup_count(self) -> int:
        return sum(
            value.possible_matchup_count
            for value in self.games
        )

    @property
    def zero_sample_matchup_count(self) -> int:
        return sum(
            value.zero_sample_matchup_count
            for value in self.games
        )

    def to_inventory_records(
        self,
    ) -> Tuple[
        CanonicalHistoricalProbabilityArtifactRecord,
        ...,
    ]:
        return tuple(
            value.to_inventory_record()
            for value in self.games
        )

    def to_diagnostics(self) -> Dict[str, Any]:
        return {
            "schema_version": self.materialization_version,
            "ready": True,
            "game_count": self.game_count,
            "ready_game_count": self.game_count,
            "provider_identity": self.provider_identity,
            "possible_matchup_count": (
                self.possible_matchup_count
            ),
            "exact_record_count": self.exact_record_count,
            "zero_sample_matchup_count": (
                self.zero_sample_matchup_count
            ),
            "observed_window_digest": (
                self.observed_window_digest
            ),
            "statistics_window_digest": (
                self.statistics_window_digest
            ),
            "workspace_window_digest": (
                self.workspace_window_digest
            ),
            "artifact_window_digest": self.digest,
            "games": tuple(
                value.to_diagnostics()
                for value in self.games
            ),
            "exact_artifacts_built": True,
            "fallback_catalogs_built": True,
            "zero_sample_rows_labeled_exact": False,
            "probability_records_exposed": False,
            "historical_replay_executed": False,
            "historical_replay_permitted": False,
            "production_activation": False,
            "production_authority_changed": False,
            "authoritative_source": "legacy",
        }


def materialize_historical_probability_artifacts(
    *,
    lineup_bullpen: CanonicalHistoricalLineupBullpenWindow,
    statistics: CanonicalHistoricalProbabilityStatisticsWindow,
    workspaces: CanonicalHistoricalPaProbabilityWorkspaceWindow,
    starting_pitcher_ids: Mapping[
        int,
        Tuple[str, str],
    ],
) -> CanonicalHistoricalProbabilityArtifactWindow:
    """Build leakage-safe exact artifacts and global fallbacks."""

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
    if not isinstance(
        workspaces,
        CanonicalHistoricalPaProbabilityWorkspaceWindow,
    ):
        raise TypeError(
            "workspaces must be a "
            "CanonicalHistoricalPaProbabilityWorkspaceWindow"
        )
    if not isinstance(starting_pitcher_ids, Mapping):
        raise TypeError(
            "starting_pitcher_ids must be a mapping"
        )

    if not (
        lineup_bullpen.observed_window_digest
        == statistics.observed_window_digest
        == workspaces.observed_window_digest
    ):
        raise ValueError(
            "observed window digests must match"
        )

    if statistics.digest != workspaces.statistics_window_digest:
        raise ValueError(
            "workspace statistics digest must match statistics"
        )

    rosters = {
        value.game_pk: value
        for value in lineup_bullpen.games
    }
    statistics_games = {
        value.game_pk: value
        for value in statistics.games
    }
    workspace_games = {
        value.game_pk: value
        for value in workspaces.games
    }

    starters = {}
    for raw_game_pk, raw_pair in (
        starting_pitcher_ids.items()
    ):
        if (
            not isinstance(raw_pair, tuple)
            or len(raw_pair) != 2
        ):
            raise TypeError(
                "starter values must be away-home tuples"
            )

        starters[int(raw_game_pk)] = (
            _identifier(raw_pair[0]),
            _identifier(raw_pair[1]),
        )

    if not (
        set(rosters)
        == set(statistics_games)
        == set(workspace_games)
        == set(starters)
    ):
        raise ValueError(
            "rosters, statistics, workspaces, and "
            "starters must exactly cover historical games"
        )

    materialized = []

    for game_pk, roster in sorted(
        rosters.items(),
        key=lambda item: (
            item[1].game_date,
            item[0],
        ),
    ):
        statistics_game = statistics_games[game_pk]
        workspace_game = workspace_games[game_pk]

        if not (
            roster.game_date
            == statistics_game.game_date
            == workspace_game.game_date
        ):
            raise ValueError(
                "historical artifact game dates must match"
            )

        discovery = (
            discover_canonical_shadow_probability_provider(
                workspace=workspace_game.workspace
            )
        )
        if (
            not discovery.ready
            or discovery.provider is None
        ):
            raise ValueError(
                "historical workspace provider is unavailable"
            )

        fallback = (
            discover_canonical_shadow_fallback_catalog(
                workspace=workspace_game.workspace,
                provider=discovery.provider,
            )
        )
        if (
            not fallback.ready
            or fallback.catalog is None
        ):
            raise ValueError(
                "historical fallback catalog is unavailable"
            )

        away_starter, home_starter = starters[game_pk]
        away_pitchers = _unique(
            (
                away_starter,
                *roster.away_bullpen_ids,
            )
        )
        home_pitchers = _unique(
            (
                home_starter,
                *roster.home_bullpen_ids,
            )
        )

        records_by_key = _record_map(statistics_game)
        exact_rows = []
        possible_count = 0
        zero_sample_count = 0

        for batter_ids, pitcher_ids in (
            (
                roster.away_lineup_ids,
                home_pitchers,
            ),
            (
                roster.home_lineup_ids,
                away_pitchers,
            ),
        ):
            for batter_id in batter_ids:
                batter = records_by_key.get(
                    ("hitting", batter_id)
                )
                if batter is None:
                    raise ValueError(
                        "historical statistics missing "
                        "required hitter"
                    )

                for pitcher_id in pitcher_ids:
                    pitcher = records_by_key.get(
                        ("pitching", pitcher_id)
                    )
                    if pitcher is None:
                        raise ValueError(
                            "historical statistics missing "
                            "required pitcher"
                        )

                    possible_count += 1

                    if not (
                        batter.sample_available
                        and pitcher.sample_available
                    ):
                        zero_sample_count += 1
                        continue

                    exact_rows.append(
                        CanonicalProbabilityArtifactRecord(
                            batter_id=batter_id,
                            pitcher_id=pitcher_id,
                            probabilities=_distribution(
                                batter=batter,
                                pitcher=pitcher,
                            ),
                        )
                    )

        artifact = CanonicalProbabilityArtifact(
            provider=discovery.provider,
            records=tuple(exact_rows),
        )

        digest = _sha256(
            {
                "game_pk": game_pk,
                "game_date": roster.game_date,
                "statistics_snapshot_digest": (
                    statistics_game.snapshot_digest
                ),
                "workspace_digest": workspace_game.digest,
                "provider_identity": (
                    discovery.provider.identity
                ),
                "exact_artifact_digest": artifact.digest,
                "fallback_catalog_digest": (
                    fallback.catalog.digest
                ),
                "possible_matchup_count": possible_count,
                "zero_sample_matchup_count": (
                    zero_sample_count
                ),
            }
        )

        materialized.append(
            CanonicalHistoricalProbabilityArtifactGame(
                game_pk=game_pk,
                game_date=roster.game_date,
                statistics_snapshot_digest=(
                    statistics_game.snapshot_digest
                ),
                workspace_digest=workspace_game.digest,
                exact_artifact=artifact,
                fallback_catalog=fallback.catalog,
                possible_matchup_count=possible_count,
                zero_sample_matchup_count=(
                    zero_sample_count
                ),
                digest=digest,
            )
        )

    window_digest = _sha256(
        {
            "observed_window_digest": (
                lineup_bullpen.observed_window_digest
            ),
            "statistics_window_digest": statistics.digest,
            "workspace_window_digest": workspaces.digest,
            "games": [
                {
                    "game_pk": value.game_pk,
                    "digest": value.digest,
                }
                for value in materialized
            ],
        }
    )

    return CanonicalHistoricalProbabilityArtifactWindow(
        observed_window_digest=(
            lineup_bullpen.observed_window_digest
        ),
        statistics_window_digest=statistics.digest,
        workspace_window_digest=workspaces.digest,
        games=tuple(materialized),
        digest=window_digest,
    )
