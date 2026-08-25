import copy

import pytest

from mlb_app.simulation.shadow.canonical_pitcher_matchup_profile_league_prior import (
    build_canonical_pitcher_matchup_profile_league_priors,
)


def event(
    *,
    event_id,
    pitcher_id,
    game_date="2026-08-22",
    events="field_out",
    description="hit_into_play",
    launch_speed=None,
    launch_angle=None,
):
    return {
        "id": event_id,
        "game_pk": 500,
        "at_bat_number": event_id,
        "pitch_number": 1,
        "pitcher_id": pitcher_id,
        "batter_id": 1000 + event_id,
        "game_date": game_date,
        "events": events,
        "description": description,
        "launch_speed": launch_speed,
        "launch_angle": launch_angle,
        "stand": "R",
    }


def rows():
    return [
        event(
            event_id=1,
            pitcher_id=101,
            events="strikeout",
            description="swinging_strike",
        ),
        event(
            event_id=2,
            pitcher_id=102,
            events="strikeout",
            description="swinging_strike",
        ),
        event(
            event_id=3,
            pitcher_id=102,
            launch_speed=100,
            launch_angle=20,
        ),
        event(
            event_id=4,
            pitcher_id=103,
            launch_speed=90,
            launch_angle=5,
        ),
    ]


def build(values=None, **kwargs):
    return (
        build_canonical_pitcher_matchup_profile_league_priors(
            rows() if values is None else values,
            game_date="2026-08-23",
            excluded_pitcher_id=101,
            metrics=(
                "k_rate",
                "hard_hit_rate_allowed",
                "ground_ball_rate",
            ),
            **kwargs,
        )
    )


def test_excludes_evaluated_pitcher_from_prior():
    result = build()

    k_row = result["diagnostics"][
        "metric_diagnostics"
    ]["k_rate"]

    assert k_row["successes"] == 1
    assert k_row["trials"] == 3
    assert result["league_priors"][
        "k_rate"
    ] == round(1 / 3, 12)
    assert (
        result["diagnostics"][
            "excluded_event_count"
        ]
        == 1
    )


def test_uses_exact_metric_denominators():
    result = build()

    hard_hit = result["diagnostics"][
        "metric_diagnostics"
    ]["hard_hit_rate_allowed"]
    ground_ball = result["diagnostics"][
        "metric_diagnostics"
    ]["ground_ball_rate"]

    assert hard_hit["successes"] == 1
    assert hard_hit["trials"] == 2
    assert ground_ball["successes"] == 1
    assert ground_ball["trials"] == 2


def test_same_day_and_future_events_are_excluded():
    values = rows() + [
        event(
            event_id=5,
            pitcher_id=102,
            game_date="2026-08-23",
            events="strikeout",
        ),
        event(
            event_id=6,
            pitcher_id=102,
            game_date="2026-08-24",
            events="strikeout",
        ),
    ]

    result = build(values)

    assert result["diagnostics"][
        "metric_diagnostics"
    ]["k_rate"]["trials"] == 3


def test_old_events_are_excluded():
    values = rows() + [
        event(
            event_id=7,
            pitcher_id=102,
            game_date="2026-04-01",
            events="strikeout",
        ),
    ]

    result = build(values)

    assert result["diagnostics"][
        "metric_diagnostics"
    ]["k_rate"]["trials"] == 3


def test_missing_metric_evidence_fails_closed():
    result = (
        build_canonical_pitcher_matchup_profile_league_priors(
            [],
            game_date="2026-08-23",
            excluded_pitcher_id=101,
            metrics=("k_rate",),
        )
    )

    assert result["league_priors"] == {}
    assert result["diagnostics"]["status"] == (
        "unavailable"
    )
    assert result["diagnostics"][
        "metric_diagnostics"
    ]["k_rate"]["reasons"] == [
        "league_trials_unavailable"
    ]


def test_rejects_unknown_metric():
    with pytest.raises(
        ValueError,
        match="unknown metrics",
    ):
        build_canonical_pitcher_matchup_profile_league_priors(
            rows(),
            game_date="2026-08-23",
            excluded_pitcher_id=101,
            metrics=("not_a_metric",),
        )


def test_rejects_invalid_excluded_pitcher():
    with pytest.raises(
        ValueError,
        match="must be positive",
    ):
        build_canonical_pitcher_matchup_profile_league_priors(
            rows(),
            game_date="2026-08-23",
            excluded_pitcher_id=0,
        )


def test_result_is_deterministic_and_nonmutating():
    values = rows()
    original = copy.deepcopy(values)

    first = build(values)
    second = build(
        list(reversed(values))
    )

    assert first == second
    assert values == original
    assert (
        first["diagnostics"][
            "production_authority_changed"
        ]
        is False
    )
