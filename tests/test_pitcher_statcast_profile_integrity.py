import datetime as dt

from sqlalchemy import text

from mlb_app.database import PitchArsenal, StatcastEvent, create_tables, get_engine, get_session
from mlb_app.pitcher_leaderboards import _event_samples
from mlb_app.pitcher_profile_store import _event_metrics


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
        "pitch_number": 1,
        "pitcher_id": 694819,
        "batter_id": 100,
        "pitch_type": "FF",
        "description": "hit_into_play",
        "events": "field_out",
        "release_speed": 100.0,
        "release_spin_rate": 2500.0,
        "launch_speed": 100.0,
        "launch_angle": 20.0,
        "estimated_woba_using_speedangle": 0.250,
        "estimated_ba_using_speedangle": 0.200,
    }
    values.update(overrides)
    return StatcastEvent(**values)


def test_pitcher_leaderboard_samples_count_canonical_pitches_not_raw_rows():
    session = _session_with_legacy_duplicates()
    session.add_all([_event(), _event(), _event(game_pk=None, at_bat_number=None, pitch_number=None)])
    session.add(PitchArsenal(season=2026, pitcher_id=694819, pitch_type="FF", pitch_count=1))
    session.commit()

    samples = _event_samples(session, 2026)

    assert samples[694819] == {"pitches": 1, "batted_balls": 1}


def test_pitcher_profile_event_metrics_use_richest_canonical_copy():
    session = _session_with_legacy_duplicates()
    session.add_all([
        _event(
            pitch_type="nan",
            description=None,
            events=None,
            release_speed=None,
            release_spin_rate=None,
            launch_speed=None,
            launch_angle=None,
            estimated_woba_using_speedangle=None,
            estimated_ba_using_speedangle=None,
        ),
        _event(),
        _event(game_pk=None, at_bat_number=None, pitch_number=None, estimated_woba_using_speedangle=0.900),
    ])
    session.commit()

    metrics = _event_metrics(session, 694819, 2026)

    assert metrics["xwoba_allowed"] == 0.25
    assert metrics["xba_allowed"] == 0.2
    assert metrics["hard_hit_pct"] == 1.0
    assert metrics["avg_velocity"] == 100.0
