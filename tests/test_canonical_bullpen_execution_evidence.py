from mlb_app.simulation.game import (
    CanonicalBullpenRole,
)
from mlb_app.simulation.shadow.execution_factory import (
    _baseline_bullpen,
)


def by_id(values):
    return {
        value.pitcher_id: value
        for value in values
    }


def test_materializes_role_and_handedness_evidence():
    bullpen = by_id(
        _baseline_bullpen(
            ("100", "101", "102", "103"),
            {
                "100": {
                    "typical_role": "closer",
                    "throws": "R",
                },
                101: {
                    "typical_role": "setup",
                    "handedness": "L",
                },
                "102": {
                    "typical_role": "long_reliever",
                    "throws": "L",
                },
                "103": {
                    "typical_role": "middle_reliever",
                    "throws": "R",
                },
            },
        )
    )

    assert bullpen["100"].role is (
        CanonicalBullpenRole.CLOSER
    )
    assert bullpen["101"].role is (
        CanonicalBullpenRole.SETUP
    )
    assert bullpen["102"].role is (
        CanonicalBullpenRole.LONG_RELIEF
    )
    assert bullpen["103"].role is (
        CanonicalBullpenRole.MIDDLE_RELIEF
    )
    assert bullpen["100"].handedness == "R"
    assert bullpen["101"].handedness == "L"


def test_confirmed_planned_role_precedes_typical_role():
    value = _baseline_bullpen(
        ("100",),
        {
            "100": {
                "typical_role": "closer",
                "planned_game_role": "bulk_follower",
                "planned_game_role_status": "confirmed",
            },
        },
    )[0]

    assert value.role is (
        CanonicalBullpenRole.LONG_RELIEF
    )


def test_historical_opener_does_not_claim_today_plan():
    value = _baseline_bullpen(
        ("100",),
        {
            "100": {
                "typical_role": "opener",
                "planned_game_role": None,
                "planned_game_role_status": "unknown",
            },
        },
    )[0]

    assert value.role is (
        CanonicalBullpenRole.MIDDLE_RELIEF
    )


def test_materializes_explicit_workload_evidence():
    value = _baseline_bullpen(
        ("100",),
        {
            "100": {
                "fatigue_index": 0.35,
                "consecutive_days_worked": 3,
                "recent_pitch_count": 27,
                "available": True,
            },
        },
    )[0]

    assert value.fatigue_index == 0.35
    assert value.consecutive_days_worked == 3
    assert value.recent_pitch_count == 27
    assert value.available is True


def test_invalid_or_missing_evidence_is_neutral():
    value = _baseline_bullpen(
        ("100",),
        {
            "100": {
                "typical_role": "unsupported",
                "throws": "X",
                "fatigue_index": 2.0,
                "consecutive_days_worked": -1,
                "recent_pitch_count": "unknown",
                "available": "yes",
            },
        },
    )[0]

    assert value.role is (
        CanonicalBullpenRole.MIDDLE_RELIEF
    )
    assert value.handedness is None
    assert value.fatigue_index == 0.0
    assert value.consecutive_days_worked == 0
    assert value.recent_pitch_count == 0
    assert value.available is True


def test_identity_only_fallback_is_preserved():
    values = _baseline_bullpen(
        ("100", "101"),
    )

    assert tuple(
        value.pitcher_id
        for value in values
    ) == ("100", "101")
    assert all(
        value.role
        is CanonicalBullpenRole.MIDDLE_RELIEF
        for value in values
    )
    assert tuple(
        value.appearance_priority
        for value in values
    ) == (0, 1)
