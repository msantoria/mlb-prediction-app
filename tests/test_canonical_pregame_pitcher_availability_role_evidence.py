from datetime import datetime, timezone

import pytest

from mlb_app.simulation.shadow.pregame_pitcher_availability_role_evidence import (
    SCHEMA_VERSION,
    materialize_canonical_pregame_pitcher_evidence,
)


AS_OF = datetime(
    2026,
    8,
    9,
    18,
    0,
    tzinfo=timezone.utc,
)


def run(**overrides):
    values = {
        "team_side": "away",
        "scheduled_starter_id": "100",
        "active_roster_pitcher_ids": (
            "100",
            "101",
            "102",
            "103",
        ),
        "as_of": AS_OF,
        "pitching_plan": None,
        "provider_observations": (),
    }
    values.update(overrides)

    return (
        materialize_canonical_pregame_pitcher_evidence(
            **values
        )
    )


def test_scheduled_starter_is_explicitly_materialized():
    result = run()

    assert result.evidence_by_pitcher_id["100"][
        "status"
    ] == "eligible"
    assert result.evidence_by_pitcher_id["100"][
        "role"
    ] == "starter"
    assert result.evidence_by_pitcher_id["100"][
        "source"
    ] == "canonical_pregame_pitching_plan"
    assert result.planned_pitcher_ids == ("100",)


def test_explicit_opener_and_bulk_roles_are_preserved():
    result = run(
        pitching_plan={
            "planned_sequence": [
                {
                    "pitcher_id": "100",
                    "role": "opener",
                },
                {
                    "pitcher_id": "101",
                    "role": "bulk_follower",
                },
            ],
        },
    )

    assert result.evidence_by_pitcher_id["100"][
        "role"
    ] == "opener"
    assert result.evidence_by_pitcher_id["101"][
        "role"
    ] == "bulk_follower"
    assert result.planned_pitcher_ids == (
        "100",
        "101",
    )


def test_explicit_bullpen_role_is_preserved():
    result = run(
        provider_observations=(
            {
                "pitcher_id": "101",
                "status": "eligible",
                "role": "closer",
                "source": "provider_depth_chart_v1",
                "observed_at": (
                    "2026-08-09T17:30:00+00:00"
                ),
                "reason": "listed_active_closer",
            },
        ),
    )

    evidence = result.evidence_by_pitcher_id["101"]

    assert evidence["status"] == "eligible"
    assert evidence["role"] == "closer"
    assert evidence["source"] == (
        "provider_depth_chart_v1"
    )
    assert evidence["evidence_valid"] is True


def test_explicit_unavailability_is_preserved():
    result = run(
        provider_observations=(
            {
                "pitcher_id": "102",
                "status": "ineligible",
                "role": "long_reliever",
                "source": "provider_game_status_v1",
                "observed_at": (
                    "2026-08-09T17:45:00+00:00"
                ),
                "reason": "injured_list",
            },
        ),
    )

    evidence = result.evidence_by_pitcher_id["102"]

    assert evidence["status"] == "ineligible"
    assert evidence["role"] == "long_reliever"
    assert evidence["reason"] == "injured_list"


def test_missing_evidence_remains_unknown():
    result = run()

    evidence = result.evidence_by_pitcher_id["101"]

    assert evidence["status"] == "unknown"
    assert evidence["role"] == "unknown"
    assert evidence["evidence_valid"] is False
    assert result.diagnostics[
        "unknown_evidence_fails_open"
    ] is True


def test_stale_evidence_becomes_unknown():
    result = run(
        maximum_age_seconds=3600,
        provider_observations=(
            {
                "pitcher_id": "101",
                "status": "eligible",
                "role": "setup",
                "source": "provider_depth_chart_v1",
                "observed_at": (
                    "2026-08-09T15:00:00+00:00"
                ),
            },
        ),
    )

    evidence = result.evidence_by_pitcher_id["101"]

    assert evidence["status"] == "unknown"
    assert evidence["role"] == "unknown"
    assert result.diagnostics[
        "stale_observation_count"
    ] == 1


def test_conflicting_evidence_becomes_unknown():
    result = run(
        provider_observations=(
            {
                "pitcher_id": "101",
                "status": "eligible",
                "role": "closer",
                "source": "provider_one_v1",
                "observed_at": (
                    "2026-08-09T17:30:00+00:00"
                ),
            },
            {
                "pitcher_id": "101",
                "status": "ineligible",
                "role": "closer",
                "source": "provider_two_v1",
                "observed_at": (
                    "2026-08-09T17:45:00+00:00"
                ),
            },
        ),
    )

    evidence = result.evidence_by_pitcher_id["101"]

    assert evidence["status"] == "unknown"
    assert evidence["role"] == "unknown"
    assert evidence["reason"] == (
        "conflicting_provider_evidence"
    )
    assert result.diagnostics[
        "conflicting_pitcher_ids"
    ] == ["101"]


def test_pitching_plan_overrides_provider_evidence():
    result = run(
        pitching_plan={
            "planned_sequence": [
                {
                    "pitcher_id": "101",
                    "role": "bulk_follower",
                },
            ],
        },
        provider_observations=(
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

    evidence = result.evidence_by_pitcher_id["101"]

    assert evidence["status"] == "eligible"
    assert evidence["role"] == "bulk_follower"
    assert evidence["plan_override"] is True


def test_does_not_infer_roles_from_roster_order():
    result = run()

    for pitcher_id in ("101", "102", "103"):
        assert result.evidence_by_pitcher_id[
            pitcher_id
        ]["role"] == "unknown"

    assert result.diagnostics[
        "roster_order_inference_used"
    ] is False
    assert result.diagnostics[
        "workload_inference_used"
    ] is False
    assert result.diagnostics[
        "typical_role_inference_used"
    ] is False


def test_result_is_read_only_and_non_authoritative():
    result = run()

    assert result.schema_version == SCHEMA_VERSION
    assert (
        result.database_writes_performed
        is False
    )
    assert (
        result.production_authority_changed
        is False
    )
    assert result.diagnostics[
        "database_writes_performed"
    ] is False
    assert result.diagnostics[
        "production_authority_changed"
    ] is False


@pytest.mark.parametrize(
    "team_side",
    ("", "neutral", "AWAY"),
)
def test_invalid_team_side_is_rejected(team_side):
    with pytest.raises(
        ValueError,
        match="team_side must be away or home",
    ):
        run(team_side=team_side)


def test_missing_starter_is_rejected():
    with pytest.raises(
        ValueError,
        match="scheduled_starter_id is required",
    ):
        run(scheduled_starter_id=None)


def test_naive_as_of_time_is_rejected():
    with pytest.raises(
        ValueError,
        match=(
            "as_of must be a timezone-aware datetime"
        ),
    ):
        run(as_of=datetime(2026, 8, 9, 18, 0))
