from copy import deepcopy

import pytest

from mlb_app.simulation.projections.pitcher_projection_authority import (
    CANONICAL_PITCHER_PROJECTION_AUTHORITY_VERSION,
    CANONICAL_PITCHER_PROJECTION_SOURCE,
    CANONICAL_PITCHER_PROJECTIONS_ENABLED_ENV,
    apply_canonical_pitcher_projection_authority,
    canonical_pitcher_projections_enabled,
)


def projection_rows():
    return {
        "schema_version":
            "canonical_player_projection_rows_v1",
        "simulation_count": 100,
        "authoritative": False,
        "authoritative_source": "legacy",
        "players": [
            {
                "player_id": "batter_1",
                "player_type": "batter",
                "team_side": "away",
                "metrics": {
                    "plate_appearances": {
                        "mean": 4.4,
                    },
                },
            },
            {
                "player_id": "100",
                "player_type": "pitcher",
                "team_side": "away",
                "pitcher_role": "starter",
                "pitcher_role_resolution_status":
                    "resolved",
                "metrics": {
                    "batters_faced": {
                        "mean": 29.0,
                    },
                    "outs_recorded": {
                        "minimum": 3.0,
                        "p10": 9.0,
                        "median": 17.0,
                        "mean": 16.0,
                        "p90": 21.0,
                        "maximum": 24.0,
                    },
                },
            },
            {
                "player_id": "101",
                "player_type": "pitcher",
                "team_side": "away",
                "pitcher_role": "reliever",
                "pitcher_role_resolution_status":
                    "resolved",
                "metrics": {
                    "outs_recorded": {
                        "minimum": 0.0,
                        "p10": 1.0,
                        "median": 3.0,
                        "mean": 3.0,
                        "p90": 5.0,
                        "maximum": 8.0,
                    },
                },
            },
        ],
    }


def readiness():
    return {
        "schema_version": (
            "canonical_pitcher_projection_"
            "activation_readiness_v1"
        ),
        "status": "ready",
        "audited": True,
        "blockers": [],
        "decision": {
            "pitcher_projection_activation_allowed":
                True,
            "production_activation_allowed":
                True,
        },
        "database_writes_performed": False,
        "production_authority_changed": False,
    }


def row(result, player_id):
    return next(
        value
        for value in result["players"]
        if value["player_id"] == player_id
    )


def test_ready_projection_activates_pitcher_rows_only():
    result = (
        apply_canonical_pitcher_projection_authority(
            projection_rows=projection_rows(),
            readiness=readiness(),
            enabled=True,
        )
    )

    authority = result[
        "pitcher_projection_authority"
    ]

    assert authority["schema_version"] == (
        CANONICAL_PITCHER_PROJECTION_AUTHORITY_VERSION
    )
    assert authority["status"] == "activated"
    assert authority[
        "production_activation"
    ] is True
    assert authority[
        "production_authority_changed"
    ] is True
    assert authority[
        "authoritative_source"
    ] == CANONICAL_PITCHER_PROJECTION_SOURCE
    assert authority["activated_pitcher_ids"] == [
        "100",
        "101",
    ]

    starter = row(result, "100")
    reliever = row(result, "101")
    batter = row(result, "batter_1")

    assert starter["authoritative"] is True
    assert reliever["authoritative"] is True
    assert starter[
        "authoritative_source"
    ] == CANONICAL_PITCHER_PROJECTION_SOURCE
    assert reliever[
        "authoritative_source"
    ] == CANONICAL_PITCHER_PROJECTION_SOURCE

    assert batter["authoritative"] is False
    assert batter[
        "authoritative_source"
    ] == "legacy"

    assert result[
        "pitcher_projections_authoritative"
    ] is True
    assert result[
        "batter_projections_authoritative"
    ] is False
    assert result["authority_scope"] == "mixed"
    assert result["authoritative"] is False
    assert result[
        "authoritative_source"
    ] == "mixed"


def test_blocked_readiness_falls_back_to_legacy():
    blocked = readiness()
    blocked["status"] = "blocked"
    blocked["blockers"] = [
        "appearance_sequence_anomalies",
    ]
    blocked["decision"][
        "production_activation_allowed"
    ] = False

    result = (
        apply_canonical_pitcher_projection_authority(
            projection_rows=projection_rows(),
            readiness=blocked,
            enabled=True,
        )
    )

    authority = result[
        "pitcher_projection_authority"
    ]

    assert authority["status"] == "fallback"
    assert authority[
        "production_activation"
    ] is False
    assert authority["fallback_reason"] == (
        "pitcher_projection_readiness_blocked"
    )
    assert row(
        result,
        "100",
    )["authoritative"] is False
    assert result[
        "authoritative_source"
    ] == "legacy"


def test_error_readiness_falls_back_to_legacy():
    failed = readiness()
    failed["status"] = "error"
    failed["audited"] = False

    result = (
        apply_canonical_pitcher_projection_authority(
            projection_rows=projection_rows(),
            readiness=failed,
            enabled=True,
        )
    )

    assert result[
        "pitcher_projection_authority"
    ]["fallback_reason"] == (
        "pitcher_projection_readiness_blocked"
    )


def test_rollback_flag_disables_activation():
    result = (
        apply_canonical_pitcher_projection_authority(
            projection_rows=projection_rows(),
            readiness=readiness(),
            enabled=False,
        )
    )

    authority = result[
        "pitcher_projection_authority"
    ]

    assert authority[
        "activation_requested"
    ] is False
    assert authority["fallback_reason"] == (
        "rollback_flag_disabled"
    )
    assert authority[
        "production_authority_changed"
    ] is False


@pytest.mark.parametrize(
    ("value", "expected"),
    (
        (True, True),
        (False, False),
        ("true", True),
        ("1", True),
        ("yes", True),
        ("false", False),
        ("0", False),
        ("off", False),
        ("", False),
    ),
)
def test_activation_flag_values(
    value,
    expected,
):
    assert (
        canonical_pitcher_projections_enabled(
            value
        )
        is expected
    )


def test_activation_flag_reads_environment(
    monkeypatch,
):
    monkeypatch.setenv(
        CANONICAL_PITCHER_PROJECTIONS_ENABLED_ENV,
        "false",
    )

    assert (
        canonical_pitcher_projections_enabled()
        is False
    )

    monkeypatch.setenv(
        CANONICAL_PITCHER_PROJECTIONS_ENABLED_ENV,
        "true",
    )

    assert (
        canonical_pitcher_projections_enabled()
        is True
    )


def test_missing_pitcher_rows_falls_back():
    projections = projection_rows()
    projections["players"] = [
        projections["players"][0],
    ]

    result = (
        apply_canonical_pitcher_projection_authority(
            projection_rows=projections,
            readiness=readiness(),
            enabled=True,
        )
    )

    authority = result[
        "pitcher_projection_authority"
    ]

    assert authority["fallback_reason"] == (
        "pitcher_projection_rows_unavailable"
    )
    assert authority[
        "production_activation"
    ] is False


def test_more_than_twenty_seven_batters_remains_valid():
    projections = projection_rows()
    projections["players"][1]["metrics"][
        "batters_faced"
    ]["mean"] = 31.0

    result = (
        apply_canonical_pitcher_projection_authority(
            projection_rows=projections,
            readiness=readiness(),
            enabled=True,
        )
    )

    assert row(
        result,
        "100",
    )["authoritative"] is True
    assert row(
        result,
        "100",
    )["metrics"]["batters_faced"]["mean"] == (
        31.0
    )


def test_activation_does_not_mutate_inputs():
    projections = projection_rows()
    gate = readiness()
    original_projections = deepcopy(
        projections
    )
    original_gate = deepcopy(gate)

    apply_canonical_pitcher_projection_authority(
        projection_rows=projections,
        readiness=gate,
        enabled=True,
    )

    assert projections == original_projections
    assert gate == original_gate


def test_activation_preserves_projection_values():
    projections = projection_rows()

    result = (
        apply_canonical_pitcher_projection_authority(
            projection_rows=projections,
            readiness=readiness(),
            enabled=True,
        )
    )

    assert row(
        result,
        "100",
    )["metrics"] == row(
        projections,
        "100",
    )["metrics"]

    assert row(
        result,
        "batter_1",
    )["metrics"] == row(
        projections,
        "batter_1",
    )["metrics"]


def test_no_database_writes_are_performed():
    result = (
        apply_canonical_pitcher_projection_authority(
            projection_rows=projection_rows(),
            readiness=readiness(),
            enabled=True,
        )
    )

    assert result[
        "pitcher_projection_authority"
    ]["database_writes_performed"] is False


def test_rejects_invalid_inputs():
    with pytest.raises(
        TypeError,
        match="projection_rows",
    ):
        apply_canonical_pitcher_projection_authority(
            projection_rows=object(),
            readiness=readiness(),
        )

    with pytest.raises(
        TypeError,
        match="readiness",
    ):
        apply_canonical_pitcher_projection_authority(
            projection_rows=projection_rows(),
            readiness=object(),
        )

    malformed = projection_rows()
    malformed["players"] = object()

    with pytest.raises(
        TypeError,
        match="players",
    ):
        apply_canonical_pitcher_projection_authority(
            projection_rows=malformed,
            readiness=readiness(),
        )
