import datetime as dt

import pytest
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

from mlb_app.database import StatcastEvent, create_tables, get_engine, get_session
from mlb_app.statcast_event_identity import dedupe_statcast_events
from scripts.repair_statcast_pitch_identity import audit, repair


def _event(**overrides):
    values = {
        "game_date": dt.date(2026, 8, 9),
        "game_pk": 823751,
        "at_bat_number": 1,
        "pitch_number": 1,
        "pitcher_id": 694819,
        "batter_id": 100,
        "pitch_type": "FF",
        "description": "called_strike",
        "release_speed": 101.0,
    }
    values.update(overrides)
    return StatcastEvent(**values)


def test_python_dedupe_prefers_canonical_rows_and_richest_correction():
    poor = _event(id=1, pitch_type="nan", description=None, release_speed=None)
    rich = _event(id=2, events="strikeout")
    legacy = _event(id=3, game_pk=None, at_bat_number=None, pitch_number=None)

    result = dedupe_statcast_events([poor, legacy, rich])

    assert result == [rich]
    assert result[0].events == "strikeout"


def test_repair_removes_duplicates_and_installs_unique_pitch_barrier(tmp_path):
    database_path = tmp_path / "statcast-repair.sqlite"
    engine = get_engine(f"sqlite:///{database_path}")
    create_tables(engine)
    with engine.begin() as connection:
        connection.execute(text("DROP INDEX ux_statcast_events_pitch_identity"))

    Session = get_session(engine)
    with Session() as session:
        session.add_all([
            _event(description=None, release_speed=None),
            _event(events="strikeout"),
            _event(game_pk=None, at_bat_number=None, pitch_number=None),
            _event(game_pk=None, at_bat_number=None, pitch_number=None),
        ])
        session.commit()
        before = audit(session)

    assert before == {
        "total_rows": 4,
        "complete_identity_rows": 2,
        "canonical_pitches": 1,
        "duplicate_complete_rows": 1,
        "incomplete_identity_rows": 2,
        "shadowed_legacy_rows": 2,
    }

    result = repair(engine)

    assert result["after"]["total_rows"] == 1
    assert result["after"]["canonical_pitches"] == 1
    assert result["after"]["duplicate_complete_rows"] == 0
    assert result["unique_index_installed"] is True

    with Session() as session:
        session.add(_event())
        with pytest.raises(IntegrityError):
            session.commit()
