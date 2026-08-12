import datetime as dt

from sqlalchemy import text

from mlb_app.batter_data_contract import clean_rolling_by_pa
from mlb_app.database import StatcastEvent, create_tables, get_engine, get_session
from mlb_app.db_utils import (
    get_batter_at_bats,
    get_batter_data_quality,
    get_batter_statcast_profile,
)


def _session_with_legacy_duplicates():
    engine = get_engine("sqlite:///:memory:")
    create_tables(engine)
    with engine.begin() as connection:
        connection.execute(text("DROP INDEX ux_statcast_events_pitch_identity"))
    return get_session(engine)()


def _event(**overrides):
    values = {
        "game_date": dt.date(2026, 8, 9),
        "game_pk": 823751,
        "at_bat_number": 1,
        "pitch_number": 4,
        "pitcher_id": 100,
        "batter_id": 592450,
        "pitch_type": "FF",
        "description": "hit_into_play",
        "events": "home_run",
        "launch_speed": 110.0,
        "launch_angle": 27.0,
    }
    values.update(overrides)
    return StatcastEvent(**values)


def test_batter_profile_and_quality_use_canonical_pitches_not_raw_rows():
    session = _session_with_legacy_duplicates()
    session.add_all(
        [
            _event(description=None, events=None, launch_speed=None, launch_angle=None),
            _event(),
            _event(game_pk=None, at_bat_number=None, pitch_number=None),
            _event(game_pk=None, at_bat_number=None, pitch_number=None),
            _event(
                at_bat_number=2,
                pitch_number=3,
                events="strikeout",
                description="swinging_strike",
                launch_speed=None,
                launch_angle=None,
            ),
        ]
    )
    session.commit()

    profile = get_batter_statcast_profile(
        session,
        592450,
        start_date=dt.date(2026, 5, 12),
        end_date=dt.date(2026, 8, 9),
    )
    quality = get_batter_data_quality(session, 592450)

    assert profile is not None
    assert profile["raw_event_rows"] == 5
    assert profile["canonical_pitch_rows"] == 2
    assert profile["duplicate_rows_removed"] == 3
    assert profile["actual_pa"] == 2
    assert profile["actual_ab"] == 2
    assert profile["hits"] == 1
    assert profile["home_runs"] == 1
    assert profile["strikeouts"] == 1
    assert profile["batting_avg"] == 0.5
    assert profile["avg_exit_velocity"] == 110.0

    assert quality["raw_event_rows"] == 5
    assert quality["total_event_rows"] == 2
    assert quality["terminal_event_rows"] == 2
    assert quality["duplicate_rows_removed"] == 3
    assert quality["source"] == "postgres_statcast_events_canonical_pitch_identity"


def test_batter_rolling_and_ordered_at_bats_page_canonical_plate_appearances():
    session = _session_with_legacy_duplicates()
    duplicates = [_event() for _ in range(20)]
    second_pa = _event(
        at_bat_number=2,
        pitch_number=5,
        events="walk",
        description="ball",
        launch_speed=None,
        launch_angle=None,
    )
    session.add_all([*duplicates, second_pa])
    session.commit()

    rolling = clean_rolling_by_pa(session, 592450, 100)
    total, at_bats = get_batter_at_bats(session, 592450, n=100)

    assert rolling is not None
    assert rolling["actual_pa"] == 2
    assert rolling["hits"] == 1
    assert rolling["walks"] == 1
    assert rolling["duplicate_rows_removed"] == 19
    assert total == 2
    assert len(at_bats) == 2
    assert {(row["game_pk"], row["at_bat_number"]) for row in at_bats} == {
        (823751, 1),
        (823751, 2),
    }
