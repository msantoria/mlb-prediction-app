from __future__ import annotations

from mlb_app.simulation.shadow import (
    CANONICAL_SHADOW_BULLPEN_DISCOVERY_VERSION,
    discover_canonical_shadow_bullpens,
)


def active_roster(team_id, season, team_name=None):
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
        {
            "mlb_player_id": starter + 3,
            "player_type": "hitter",
        },
    ]


def discovery(**overrides):
    kwargs = {
        "away_team_id": 10,
        "away_team_name": "Away",
        "away_starter_id": 100,
        "home_team_id": 20,
        "home_team_name": "Home",
        "home_starter_id": 200,
        "season": 2026,
        "roster_fetcher": active_roster,
    }
    kwargs.update(overrides)

    return discover_canonical_shadow_bullpens(
        **kwargs
    )


def test_active_roster_pitchers_build_bullpen_candidates():
    result = discovery()

    assert result.status == "ready"
    assert result.ready is True
    assert result.away.bullpen_pitcher_ids == (
        "101",
        "102",
    )
    assert result.home.bullpen_pitcher_ids == (
        "201",
        "202",
    )


def test_scheduled_starters_are_excluded():
    result = discovery()

    assert "100" not in (
        result.away.bullpen_pitcher_ids
    )
    assert "200" not in (
        result.home.bullpen_pitcher_ids
    )


def test_readiness_fields_are_side_specific():
    fields = discovery().readiness_matchup_fields()

    assert len(
        fields["away_bullpen_pitcher_ids"]
    ) == 2
    assert len(
        fields["home_bullpen_pitcher_ids"]
    ) == 2


def test_diagnostics_do_not_expose_pitcher_ids():
    diagnostics = discovery().to_diagnostics()

    assert diagnostics["schema_version"] == (
        CANONICAL_SHADOW_BULLPEN_DISCOVERY_VERSION
    )
    assert diagnostics[
        "pitcher_identifiers_exposed"
    ] is False
    assert diagnostics["away"][
        "validated_pitcher_count"
    ] == 2
    assert "bullpen_pitcher_ids" not in (
        diagnostics["away"]
    )


def test_duplicate_and_non_pitcher_records_are_filtered():
    def roster(team_id, season, team_name=None):
        return [
            {
                "mlb_player_id": 100,
                "player_type": "pitcher",
            },
            {
                "mlb_player_id": 101,
                "player_type": "pitcher",
            },
            {
                "mlb_player_id": 101,
                "player_type": "pitcher",
            },
            {
                "mlb_player_id": 102,
                "player_type": "hitter",
            },
        ]

    result = discovery(
        home_starter_id=100,
        roster_fetcher=roster,
    )

    assert result.away.bullpen_pitcher_ids == (
        "101",
    )
    assert result.home.bullpen_pitcher_ids == (
        "101",
    )


def test_missing_team_id_blocks_only_that_side():
    result = discovery(
        away_team_id=None,
    )

    assert result.status == "partial"
    assert result.away.ready is False
    assert result.away.error_type == (
        "missing_team_id"
    )
    assert result.home.ready is True


def test_missing_starter_id_does_not_treat_roster_as_bullpen():
    result = discovery(
        away_starter_id=None,
    )

    assert result.away.ready is False
    assert result.away.error_type == (
        "missing_starter_id"
    )
    assert (
        "away_bullpen_pitcher_ids"
        not in result.readiness_matchup_fields()
    )


def test_roster_failure_fails_open():
    def failing_roster(
        team_id,
        season,
        team_name=None,
    ):
        raise RuntimeError("roster unavailable")

    result = discovery(
        roster_fetcher=failing_roster,
    )

    assert result.status == "error"
    assert result.ready is False
    assert result.away.error_type == (
        "RuntimeError"
    )
    assert result.readiness_matchup_fields() == {}

def role_evidence(
    status,
    role,
    reason=None,
):
    return {
        "status": status,
        "role": role,
        "source": "pregame_role_evidence_v1",
        "reason": reason,
    }


def test_verified_probable_starter_is_excluded():
    result = discovery(
        away_eligibility_evidence_by_pitcher_id={
            "101": role_evidence(
                "ineligible",
                "probable_starter",
                "probable_starter_not_in_plan",
            ),
            "102": role_evidence(
                "eligible",
                "reliever",
            ),
        },
    )

    assert result.away.bullpen_pitcher_ids == (
        "102",
    )

    diagnostics = (
        result.away.to_diagnostics()
    )

    assert diagnostics[
        "eligibility_status"
    ] == "enforced"
    assert diagnostics[
        "eligibility_evidence_complete"
    ] is True
    assert diagnostics[
        "excluded_pitcher_count"
    ] == 1
    assert diagnostics[
        "exclusion_reason_counts"
    ] == {
        "probable_starter_not_in_plan": 1,
    }


def test_missing_evidence_preserves_existing_pool():
    result = discovery()

    assert result.away.bullpen_pitcher_ids == (
        "101",
        "102",
    )

    diagnostics = (
        result.away.to_diagnostics()
    )

    assert diagnostics[
        "eligibility_status"
    ] == "fallback"
    assert diagnostics[
        "eligibility_evidence_complete"
    ] is False
    assert diagnostics[
        "eligibility_evidence_coverage_rate"
    ] == 0.0
    assert diagnostics[
        "excluded_pitcher_count"
    ] == 0


def test_planned_bulk_pitcher_overrides_exclusion():
    result = discovery(
        away_eligibility_evidence_by_pitcher_id={
            "101": role_evidence(
                "ineligible",
                "probable_starter",
            ),
            "102": role_evidence(
                "eligible",
                "reliever",
            ),
        },
        away_planned_pitcher_ids=(
            "101",
        ),
    )

    assert result.away.bullpen_pitcher_ids == (
        "101",
        "102",
    )
    assert result.away.to_diagnostics()[
        "planned_override_count"
    ] == 1


def test_invalid_evidence_retains_candidate():
    result = discovery(
        away_eligibility_evidence_by_pitcher_id={
            "101": {
                "status": "blocked",
                "role": "mystery",
            },
        },
    )

    assert "101" in (
        result.away.bullpen_pitcher_ids
    )
    assert result.away.to_diagnostics()[
        "excluded_pitcher_count"
    ] == 0


def test_eligibility_diagnostics_do_not_expose_ids():
    diagnostics = discovery(
        away_eligibility_evidence_by_pitcher_id={
            "101": role_evidence(
                "ineligible",
                "probable_starter",
            ),
        },
    ).to_diagnostics()

    assert (
        "eligible_bullpen_pitcher_ids"
        not in diagnostics["away"]
    )
    assert (
        "excluded_pitcher_ids"
        not in diagnostics["away"]
    )

def test_materialized_pregame_evidence_filters_pool():
    result = discovery(
        pregame_evidence_as_of=(
            "2026-08-09T18:00:00+00:00"
        ),
        away_pregame_provider_observations=(
            {
                "pitcher_id": "101",
                "status": "eligible",
                "role": "closer",
                "source": "provider_depth_chart_v1",
                "observed_at": (
                    "2026-08-09T17:30:00+00:00"
                ),
            },
            {
                "pitcher_id": "102",
                "status": "ineligible",
                "role": "probable_starter",
                "source": "provider_rotation_v1",
                "observed_at": (
                    "2026-08-09T17:30:00+00:00"
                ),
                "reason": (
                    "probable_starter_not_in_plan"
                ),
            },
        ),
    )

    assert result.away.bullpen_pitcher_ids == (
        "101",
    )
    assert result.away.pregame_evidence is not None
    diagnostics = result.away.to_diagnostics()

    assert diagnostics[
        "pregame_evidence_materialized"
    ] is True
    assert diagnostics[
        "pregame_evidence_status"
    ] == "materialized"
    assert diagnostics[
        "pregame_evidence_pitcher_count"
    ] == 3
    assert diagnostics[
        "typical_role_inference_used"
    ] is False


def test_materialized_plan_overrides_ineligibility():
    result = discovery(
        pregame_evidence_as_of=(
            "2026-08-09T18:00:00+00:00"
        ),
        away_pregame_pitching_plan={
            "planned_sequence": [
                {
                    "pitcher_id": "101",
                    "role": "bulk_follower",
                },
            ],
        },
        away_pregame_provider_observations=(
            {
                "pitcher_id": "101",
                "status": "ineligible",
                "role": "probable_starter",
                "source": "provider_rotation_v1",
                "observed_at": (
                    "2026-08-09T17:30:00+00:00"
                ),
            },
        ),
    )

    assert "101" in (
        result.away.bullpen_pitcher_ids
    )
    assert result.away.to_diagnostics()[
        "planned_override_count"
    ] == 1


def test_unknown_materialized_evidence_fails_open():
    result = discovery(
        pregame_evidence_as_of=(
            "2026-08-09T18:00:00+00:00"
        ),
    )

    assert result.away.bullpen_pitcher_ids == (
        "101",
        "102",
    )
    assert result.away.to_diagnostics()[
        "pregame_evidence_unknown_count"
    ] == 2


def test_stale_materialized_evidence_fails_open():
    result = discovery(
        pregame_evidence_as_of=(
            "2026-08-09T18:00:00+00:00"
        ),
        pregame_maximum_age_seconds=3600,
        away_pregame_provider_observations=(
            {
                "pitcher_id": "101",
                "status": "ineligible",
                "role": "probable_starter",
                "source": "provider_rotation_v1",
                "observed_at": (
                    "2026-08-09T15:00:00+00:00"
                ),
            },
        ),
    )

    assert "101" in (
        result.away.bullpen_pitcher_ids
    )
    assert result.away.to_diagnostics()[
        "pregame_evidence_stale_count"
    ] == 1


def test_direct_evidence_api_remains_compatible():
    result = discovery(
        pregame_evidence_as_of=(
            "2026-08-09T18:00:00+00:00"
        ),
        away_eligibility_evidence_by_pitcher_id={
            "101": role_evidence(
                "ineligible",
                "probable_starter",
                "direct_evidence_precedence",
            ),
        },
    )

    assert result.away.bullpen_pitcher_ids == (
        "102",
    )
    assert result.away.to_diagnostics()[
        "exclusion_reason_counts"
    ] == {
        "direct_evidence_precedence": 1,
    }

    records = {
        record["pitcher_id"]: record
        for record in result.away.eligibility[
            "records"
        ]
    }

    assert records["102"]["retained"] is True
    assert records["102"][
        "evidence_status"
    ] == "unknown"


def test_strict_membership_requires_explicit_reliever_evidence():
    result = discovery(
        require_explicit_bullpen_membership=True,
    )

    assert result.status == "unavailable"
    assert result.away.bullpen_pitcher_ids == ()
    assert result.home.bullpen_pitcher_ids == ()

    away = result.away.to_diagnostics()
    home = result.home.to_diagnostics()

    assert away[
        "require_explicit_bullpen_membership"
    ] is True
    assert away[
        "strict_membership_excluded_count"
    ] == 2
    assert home[
        "strict_membership_excluded_count"
    ] == 2


def test_strict_membership_retains_only_explicit_bullpen_roles():
    result = discovery(
        require_explicit_bullpen_membership=True,
        away_eligibility_evidence_by_pitcher_id={
            "101": role_evidence(
                "eligible",
                "closer",
                "confirmed_active_bullpen",
            ),
            "102": role_evidence(
                "eligible",
                "probable_starter",
                "confirmed_rotation_member",
            ),
        },
        home_eligibility_evidence_by_pitcher_id={
            "201": role_evidence(
                "eligible",
                "setup",
                "confirmed_active_bullpen",
            ),
            "202": role_evidence(
                "ineligible",
                "starter",
                "confirmed_rotation_member",
            ),
        },
    )

    assert result.status == "ready"
    assert result.away.bullpen_pitcher_ids == (
        "101",
    )
    assert result.home.bullpen_pitcher_ids == (
        "201",
    )

    away_records = {
        row["pitcher_id"]: row
        for row in result.away.eligibility[
            "records"
        ]
    }
    home_records = {
        row["pitcher_id"]: row
        for row in result.home.eligibility[
            "records"
        ]
    }

    assert away_records["101"][
        "decision_reason"
    ] == "explicitly_eligible"
    assert away_records["102"][
        "decision_reason"
    ] == "starter_like_role_excluded"
    assert home_records["202"][
        "retained"
    ] is False


def test_strict_membership_preserves_explicit_plan_override():
    result = discovery(
        require_explicit_bullpen_membership=True,
        away_planned_pitcher_ids=("102",),
        away_eligibility_evidence_by_pitcher_id={
            "102": role_evidence(
                "ineligible",
                "probable_starter",
                "general_rotation_exclusion",
            ),
        },
    )

    assert result.away.bullpen_pitcher_ids == (
        "102",
    )
    assert result.away.eligibility[
        "planned_override_count"
    ] == 1


def test_strict_membership_consumes_materialized_provider_evidence():
    observed_at = "2026-08-09T17:30:00+00:00"

    result = discovery(
        pregame_evidence_as_of=(
            "2026-08-09T18:00:00+00:00"
        ),
        require_explicit_bullpen_membership=True,
        away_pregame_provider_observations=(
            {
                "pitcher_id": "101",
                "status": "eligible",
                "role": "closer",
                "source": "structured_provider",
                "observed_at": observed_at,
            },
            {
                "pitcher_id": "102",
                "status": "eligible",
                "role": "probable_starter",
                "source": "structured_provider",
                "observed_at": observed_at,
            },
        ),
        home_pregame_provider_observations=(
            {
                "pitcher_id": "201",
                "status": "eligible",
                "role": "setup",
                "source": "structured_provider",
                "observed_at": observed_at,
            },
            {
                "pitcher_id": "202",
                "status": "ineligible",
                "role": "starter",
                "source": "structured_provider",
                "observed_at": observed_at,
            },
        ),
    )

    assert result.status == "ready"
    assert result.away.bullpen_pitcher_ids == (
        "101",
    )
    assert result.home.bullpen_pitcher_ids == (
        "201",
    )

    away_records = {
        row["pitcher_id"]: row
        for row in result.away.eligibility[
            "records"
        ]
    }
    home_records = {
        row["pitcher_id"]: row
        for row in result.home.eligibility[
            "records"
        ]
    }

    assert away_records["101"][
        "pitcher_role"
    ] == "closer"
    assert away_records["101"]["retained"] is True

    assert away_records["102"][
        "decision_reason"
    ] == "starter_like_role_excluded"
    assert away_records["102"]["retained"] is False

    assert home_records["201"][
        "pitcher_role"
    ] == "setup"
    assert home_records["201"]["retained"] is True

    assert home_records["202"]["retained"] is False

    assert result.away.pregame_evidence is not None
    assert result.home.pregame_evidence is not None


def test_strict_membership_uses_observed_season_usage():
    def usage_roster(
        team_id,
        season,
        team_name=None,
    ):
        starter = 100 if team_id == 10 else 200

        return [
            {
                "mlb_player_id": starter,
                "player_type": "pitcher",
                "season_games_pitched": 24,
                "season_games_started": 24,
                "season_relief_appearances": 0,
            },
            {
                "mlb_player_id": starter + 1,
                "player_type": "pitcher",
                "season_games_pitched": 45,
                "season_games_started": 0,
                "season_relief_appearances": 45,
            },
            {
                "mlb_player_id": starter + 2,
                "player_type": "pitcher",
                "season_games_pitched": 25,
                "season_games_started": 25,
                "season_relief_appearances": 0,
            },
            {
                "mlb_player_id": starter + 3,
                "player_type": "pitcher",
                "season_games_pitched": 27,
                "season_games_started": 11,
                "season_relief_appearances": 16,
            },
        ]

    result = discovery(
        roster_fetcher=usage_roster,
        require_explicit_bullpen_membership=True,
    )

    assert result.status == "ready"
    assert result.away.bullpen_pitcher_ids == (
        "101",
        "103",
    )
    assert result.home.bullpen_pitcher_ids == (
        "201",
        "203",
    )

    away_records = {
        row["pitcher_id"]: row
        for row in result.away.eligibility[
            "records"
        ]
    }

    assert away_records["101"][
        "decision_reason"
    ] == "explicitly_eligible"
    assert away_records["102"][
        "decision_reason"
    ] == "observed_start_usage_dominant"

    diagnostics = result.away.to_diagnostics()

    assert diagnostics[
        "season_usage_evidence_pitcher_count"
    ] == 3
    assert diagnostics[
        "season_usage_role_classification_used"
    ] is True
    assert diagnostics[
        "season_usage_classification_policy"
    ] == (
        "relief_appearances_greater_than_starts"
    )


def test_provider_evidence_overrides_season_usage():
    def usage_roster(
        team_id,
        season,
        team_name=None,
    ):
        starter = 100 if team_id == 10 else 200

        return [
            {
                "mlb_player_id": starter,
                "player_type": "pitcher",
            },
            {
                "mlb_player_id": starter + 1,
                "player_type": "pitcher",
                "season_games_pitched": 20,
                "season_games_started": 20,
                "season_relief_appearances": 0,
            },
        ]

    result = discovery(
        roster_fetcher=usage_roster,
        require_explicit_bullpen_membership=True,
        away_eligibility_evidence_by_pitcher_id={
            "101": role_evidence(
                "eligible",
                "long_reliever",
                "provider_override",
            ),
        },
    )

    assert result.away.bullpen_pitcher_ids == (
        "101",
    )
    assert result.away.eligibility["records"][0][
        "evidence_source"
    ] == "pregame_role_evidence_v1"


def test_materialized_unknown_preserves_season_usage_evidence():
    def usage_roster(
        team_id,
        season,
        team_name=None,
    ):
        starter = 100 if team_id == 10 else 200

        return [
            {
                "mlb_player_id": starter,
                "player_type": "pitcher",
                "season_games_pitched": 20,
                "season_games_started": 20,
                "season_relief_appearances": 0,
            },
            {
                "mlb_player_id": starter + 1,
                "player_type": "pitcher",
                "season_games_pitched": 40,
                "season_games_started": 0,
                "season_relief_appearances": 40,
            },
            {
                "mlb_player_id": starter + 2,
                "player_type": "pitcher",
                "season_games_pitched": 22,
                "season_games_started": 22,
                "season_relief_appearances": 0,
            },
        ]

    result = discovery(
        roster_fetcher=usage_roster,
        pregame_evidence_as_of=(
            "2026-08-09T18:00:00+00:00"
        ),
        require_explicit_bullpen_membership=True,
    )

    assert result.status == "ready"
    assert result.away.bullpen_pitcher_ids == (
        "101",
    )
    assert result.home.bullpen_pitcher_ids == (
        "201",
    )

    away_records = {
        row["pitcher_id"]: row
        for row in result.away.eligibility[
            "records"
        ]
    }

    assert away_records["101"][
        "evidence_source"
    ] == (
        "mlb_stats_active_roster_"
        "season_pitching"
    )
    assert away_records["102"][
        "decision_reason"
    ] == "observed_start_usage_dominant"

    diagnostics = result.away.to_diagnostics()

    assert diagnostics[
        "unknown_materialized_evidence_"
        "preserves_season_usage"
    ] is True
    assert diagnostics["evidence_precedence"] == [
        "direct_explicit_evidence",
        "materialized_known_provider_evidence",
        "mlb_stats_season_pitching_usage",
        "materialized_unknown_evidence",
    ]


def test_known_materialized_provider_evidence_overrides_usage():
    def usage_roster(
        team_id,
        season,
        team_name=None,
    ):
        starter = 100 if team_id == 10 else 200

        return [
            {
                "mlb_player_id": starter,
                "player_type": "pitcher",
            },
            {
                "mlb_player_id": starter + 1,
                "player_type": "pitcher",
                "season_games_pitched": 30,
                "season_games_started": 30,
                "season_relief_appearances": 0,
            },
        ]

    observed_at = "2026-08-09T17:30:00+00:00"

    result = discovery(
        roster_fetcher=usage_roster,
        pregame_evidence_as_of=(
            "2026-08-09T18:00:00+00:00"
        ),
        require_explicit_bullpen_membership=True,
        away_pregame_provider_observations=(
            {
                "pitcher_id": "101",
                "status": "eligible",
                "role": "long_reliever",
                "source": "structured_provider",
                "observed_at": observed_at,
            },
        ),
    )

    assert result.away.bullpen_pitcher_ids == (
        "101",
    )

    record = result.away.eligibility[
        "records"
    ][0]

    assert record["evidence_source"] == (
        "structured_provider"
    )
    assert record["pitcher_role"] == (
        "long_reliever"
    )
