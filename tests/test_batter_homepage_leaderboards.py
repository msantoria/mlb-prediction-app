import datetime as dt

from sqlalchemy import text

from mlb_app.database import StatcastEvent, create_tables, get_engine, get_session
from mlb_app.db_utils import (
    _compute_batter_batted_ball_sql,
    _compute_batter_counting_sql,
    _compute_batter_swing_sql,
)


def _session_with_legacy_duplicates():
    engine = get_engine("sqlite:///:memory:")
    create_tables(engine)
    with engine.begin() as connection:
        connection.execute(text("DROP INDEX ux_statcast_events_pitch_identity"))
    return get_session(engine)()


def _event(at_bat_number, pitch_number, **overrides):
    values = {
        "game_date": dt.date(2026, 8, 24),
        "game_pk": 9001,
        "at_bat_number": at_bat_number,
        "pitch_number": pitch_number,
        "pitcher_id": 101,
        "batter_id": 202,
        "pitch_type": "FF",
        "description": "hit_into_play",
        "events": "field_out",
        "launch_speed": 90.0,
        "launch_angle": 10.0,
    }
    values.update(overrides)
    return StatcastEvent(**values)


def test_batter_homepage_uses_terminal_batted_balls_not_measured_fouls():
    session = _session_with_legacy_duplicates()
    single = _event(
        1,
        3,
        events="single",
        launch_speed=100.0,
        launch_angle=27.0,
    )
    measured_foul = _event(
        1,
        1,
        events=None,
        description="foul",
        launch_speed=110.0,
        launch_angle=20.0,
    )
    reached_on_error = _event(
        2,
        2,
        events="field_error",
        launch_speed=90.0,
        launch_angle=5.0,
    )
    strikeout = _event(
        3,
        4,
        events="strikeout",
        description="swinging_strike",
        launch_speed=None,
        launch_angle=None,
    )
    session.add_all(
        [
            measured_foul,
            single,
            reached_on_error,
            strikeout,
            # Legacy duplicate source rows must not change homepage totals.
            _event(
                1,
                1,
                events=None,
                description="foul",
                launch_speed=110.0,
                launch_angle=20.0,
            ),
            _event(
                1,
                3,
                events="single",
                launch_speed=100.0,
                launch_angle=27.0,
            ),
        ]
    )
    session.commit()

    start = end = dt.date(2026, 8, 24)
    counting = _compute_batter_counting_sql(session, start, end)[0]
    batted = _compute_batter_batted_ball_sql(session, start, end)[0]
    swings = _compute_batter_swing_sql(session, start, end)[0]

    assert counting.pa == 3
    assert counting.ab == 3
    assert counting.hits == 1

    assert batted.bbe == 2
    assert batted.bbe <= counting.pa
    assert round(float(batted.avg_exit_velocity), 1) == 95.0
    assert round(float(batted.max_exit_velocity), 1) == 100.0
    assert batted.hard_hits == 1
    assert batted.barrels == 1

    assert swings.swings == 4
    assert swings.whiffs == 1
