from __future__ import annotations

from copy import deepcopy

import pytest

from mlb_app.simulation.shadow import (
    discover_canonical_shadow_bullpens,
)
from mlb_app.simulation.shadow.canonical_pregame_pitcher_evidence_source_coverage import (
    SCHEMA_VERSION,
    audit_canonical_pregame_pitcher_evidence_source_coverage,
)


AS_OF = "2026-08-09T23:05:00+00:00"


def roster(team_id, season, team_name=None):
    starter = 100 if team_id == 10 else 200

    return [
        {
            "mlb_player_id": starter,
            "player_type": "pitcher",
        },
        {
            "mlb_player_id": starter + 1,
            "player_type": "pitcher",
        },
        {
            "mlb_player_id": starter + 2,
            "player_type": "pitcher",
        },
    ]


def matchup():
    return {
        "game_pk": 123,
        "game_time": AS_OF,
        "away_pitcher_status": "probable",
        "away_pitcher_source": (
            "mlb_stats_probablePitcher"
        ),
        "home_pitcher_status": "probable",
        "home_pitcher_source": (
            "mlb_stats_probablePitcher"
        ),
    }


def discovery(**overrides):
    values = {
        "away_team_id": 10,
        "away_team_name": "Away Team",
        "away_starter_id": 100,
        "home_team_id": 20,
        "home_team_name": "Home Team",
        "home_starter_id": 200,
        "season": 2026,
        "roster_fetcher": roster,
        "pregame_evidence_as_of": AS_OF,
    }
    values.update(overrides)

    return discover_canonical_shadow_bullpens(
        **values
    )


def run(**overrides):
    values = {
        "matchup": matchup(),
        "bullpen_discovery": discovery(),
    }
    values.update(overrides)

    return (
        audit_canonical_pregame_pitcher_evidence_source_coverage(
            **values
        )
    )


def observation(
    pitcher_id,
    *,
    status="eligible",
    role="closer",
    source="provider_depth_chart_v1",
    observed_at="2026-08-09T22:30:00+00:00",
    reason=None,
):
    return {
        "pitcher_id": pitcher_id,
        "status": status,
        "role": role,
        "source": source,
        "observed_at": observed_at,
        "reason": reason,
    }


def test_default_production_sources_show_real_gap():
    result = run()

    assert result["status"] == (
        "coverage_gaps_observed"
    )
    assert result[
        "scheduled_starter_source_coverage_rate"
    ] == 1.0
    assert result[
        "provider_evidence_coverage_rate"
    ] == 0.0
    assert result[
        "explicit_availability_coverage_rate"
    ] == 0.0
    assert result[
        "typical_role_coverage_rate"
    ] == 0.0
    assert result["unknown_evidence_count"] == 4

    assert result["blockers"] == [
        "bullpen_availability_source_incomplete",
        "typical_bullpen_role_source_incomplete",
    ]


def test_explicit_provider_evidence_is_counted():
    source = discovery(
        away_pregame_provider_observations=(
            observation("101", role="closer"),
            observation(
                "102",
                role="long_reliever",
            ),
        ),
        home_pregame_provider_observations=(
            observation("201", role="setup"),
            observation(
                "202",
                role="middle_reliever",
            ),
        ),
    )

    result = run(
        bullpen_discovery=source,
    )

    assert result["status"] == "ready"
    assert result[
        "valid_provider_evidence_count"
    ] == 4
    assert result[
        "provider_evidence_coverage_rate"
    ] == 1.0
    assert result[
        "explicit_availability_coverage_rate"
    ] == 1.0
    assert result[
        "typical_role_coverage_rate"
    ] == 1.0
    assert result["blockers"] == []
    assert result["decision"][
        "provider_integration_ready"
    ] is True
    assert result["decision"][
        "production_activation_allowed"
    ] is False


def test_explicit_unavailability_counts_as_coverage():
    source = discovery(
        away_pregame_provider_observations=(
            observation(
                "101",
                status="ineligible",
                role="long_reliever",
                source="provider_game_status_v1",
                reason="unavailable_after_usage",
            ),
        ),
    )

    result = run(
        bullpen_discovery=source,
    )

    assert result["away"][
        "explicit_availability_count"
    ] == 1
    assert result["away"][
        "typical_role_count"
    ] == 1


def test_stale_evidence_is_reported_not_accepted():
    source = discovery(
        pregame_maximum_age_seconds=3600,
        away_pregame_provider_observations=(
            observation(
                "101",
                observed_at=(
                    "2026-08-09T20:00:00+00:00"
                ),
            ),
        ),
    )

    result = run(
        bullpen_discovery=source,
    )

    assert result["stale_observation_count"] == 1
    assert (
        "stale_pregame_evidence_observed"
        in result["blockers"]
    )
    assert result[
        "valid_provider_evidence_count"
    ] == 0


def test_conflicting_evidence_is_reported():
    source = discovery(
        away_pregame_provider_observations=(
            observation(
                "101",
                status="eligible",
            ),
            observation(
                "101",
                status="ineligible",
            ),
        ),
    )

    result = run(
        bullpen_discovery=source,
    )

    assert result[
        "conflicting_pitcher_count"
    ] == 1
    assert (
        "conflicting_pregame_evidence_observed"
        in result["blockers"]
    )


def test_missing_starter_source_is_reported():
    source_matchup = matchup()
    source_matchup[
        "away_pitcher_source"
    ] = None

    result = run(
        matchup=source_matchup,
    )

    assert result[
        "scheduled_starter_source_valid_count"
    ] == 1
    assert result[
        "scheduled_starter_source_coverage_rate"
    ] == 0.5
    assert (
        "scheduled_starter_source_incomplete"
        in result["blockers"]
    )


def test_active_roster_is_not_availability_evidence():
    result = run()

    capabilities = result[
        "source_capabilities"
    ]["mlb_stats_active_roster"]

    assert capabilities[
        "active_roster_membership_supported"
    ] is True
    assert capabilities[
        "game_availability_supported"
    ] is False
    assert capabilities[
        "typical_bullpen_role_supported"
    ] is False


def test_audit_does_not_mutate_inputs():
    source_matchup = matchup()
    source_discovery = discovery()

    before_matchup = deepcopy(source_matchup)
    before_diagnostics = deepcopy(
        source_discovery.to_diagnostics()
    )
    before_away_pool = (
        source_discovery
        .away
        .bullpen_pitcher_ids
    )
    before_home_pool = (
        source_discovery
        .home
        .bullpen_pitcher_ids
    )

    run(
        matchup=source_matchup,
        bullpen_discovery=source_discovery,
    )

    assert source_matchup == before_matchup
    assert (
        source_discovery.to_diagnostics()
        == before_diagnostics
    )
    assert (
        source_discovery
        .away
        .bullpen_pitcher_ids
        == before_away_pool
    )
    assert (
        source_discovery
        .home
        .bullpen_pitcher_ids
        == before_home_pool
    )


def test_reports_schema_interpretation_and_safety():
    result = run()

    assert result["schema_version"] == (
        SCHEMA_VERSION
    )
    assert result["audited"] is True
    assert result["interpretation"][
        "active_roster_membership_is_not_game_availability"
    ] is True
    assert result["interpretation"][
        "news_keywords_are_not_structured_evidence"
    ] is True
    assert result["interpretation"][
        "simulation_usage_is_not_pregame_evidence"
    ] is True
    assert result["safety_checks"][
        "pitcher_pools_unchanged"
    ] is True
    assert result["safety_checks"][
        "game_probabilities_unchanged"
    ] is True
    assert result[
        "database_writes_performed"
    ] is False
    assert result[
        "production_authority_changed"
    ] is False


@pytest.mark.parametrize(
    "invalid_matchup",
    (None, [], "matchup"),
)
def test_invalid_matchup_is_rejected(
    invalid_matchup,
):
    with pytest.raises(
        TypeError,
        match="matchup must be a mapping",
    ):
        run(matchup=invalid_matchup)


def test_invalid_discovery_is_rejected():
    with pytest.raises(
        TypeError,
        match=(
            "bullpen_discovery must be a canonical"
        ),
    ):
        run(bullpen_discovery={})
