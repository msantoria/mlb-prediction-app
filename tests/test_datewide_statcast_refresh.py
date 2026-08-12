from __future__ import annotations

import datetime as dt

import pandas as pd

from mlb_app.database import StatcastEvent, create_tables, get_engine, get_session
from mlb_app import etl


def _session_factory(tmp_path):
    db_path = tmp_path / "statcast_refresh_test.db"
    engine = get_engine(f"sqlite:///{db_path}")
    create_tables(engine)
    return get_session(engine)


def _sample_statcast_df() -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "game_date": "2026-05-18",
                "game_pk": 777001,
                "at_bat_number": 1,
                "pitch_number": 1,
                "inning": 1,
                "inning_topbot": "Top",
                "outs_when_up": 0,
                "home_team": "CHC",
                "away_team": "STL",
                "pitcher": 1001,
                "batter": 2001,
                "pitch_type": "FF",
                "release_speed": 95.4,
                "release_spin_rate": 2300,
                "pfx_x": -0.4,
                "pfx_z": 1.3,
                "plate_x": 0.2,
                "plate_z": 2.4,
                "balls": 0,
                "strikes": 0,
                "events": None,
                "description": "called_strike",
                "launch_speed": None,
                "launch_angle": None,
                "estimated_woba_using_speedangle": None,
                "estimated_ba_using_speedangle": None,
                "stand": "R",
                "p_throws": "R",
            },
            {
                "game_date": "2026-05-18",
                "game_pk": 777001,
                "at_bat_number": 1,
                "pitch_number": 2,
                "inning": 1,
                "inning_topbot": "Top",
                "outs_when_up": 0,
                "home_team": "CHC",
                "away_team": "STL",
                "pitcher": 1001,
                "batter": 2001,
                "pitch_type": "SL",
                "release_speed": 86.2,
                "release_spin_rate": 2550,
                "pfx_x": 0.7,
                "pfx_z": 0.2,
                "plate_x": -0.1,
                "plate_z": 1.9,
                "balls": 0,
                "strikes": 1,
                "events": "single",
                "description": "hit_into_play",
                "launch_speed": 101.0,
                "launch_angle": 14.0,
                "estimated_woba_using_speedangle": 0.72,
                "estimated_ba_using_speedangle": 0.68,
                "stand": "R",
                "p_throws": "R",
            },
        ]
    )


def test_refresh_statcast_events_for_date_is_idempotent(monkeypatch, tmp_path):
    Session = _session_factory(tmp_path)
    monkeypatch.setattr(etl, "fetch_statcast_all_events", lambda start, end: _sample_statcast_df())

    with Session() as session:
        first = etl.refresh_statcast_events_for_date(session, "2026-05-18")
        assert first["rows_returned"] == 2
        assert first["inserted"] == 2
        assert first["updated"] == 0
        assert first["noop"] == 0
        assert session.query(StatcastEvent).count() == 2

        second = etl.refresh_statcast_events_for_date(session, "2026-05-18")
        assert second["rows_returned"] == 2
        assert second["inserted"] == 0
        assert second["updated"] == 0
        assert second["noop"] == 2
        assert session.query(StatcastEvent).count() == 2


def test_refresh_statcast_events_for_date_updates_existing_non_null_values(monkeypatch, tmp_path):
    Session = _session_factory(tmp_path)
    base_df = _sample_statcast_df()
    updated_df = _sample_statcast_df()
    updated_df.loc[0, "release_speed"] = 96.1
    updated_df.loc[0, "events"] = "strikeout"

    responses = iter([base_df, updated_df])
    monkeypatch.setattr(etl, "fetch_statcast_all_events", lambda start, end: next(responses))

    with Session() as session:
        first = etl.refresh_statcast_events_for_date(session, "2026-05-18")
        second = etl.refresh_statcast_events_for_date(session, "2026-05-18")

        assert first["inserted"] == 2
        assert second["inserted"] == 0
        assert second["updated"] == 1
        assert session.query(StatcastEvent).count() == 2

        row = (
            session.query(StatcastEvent)
            .filter(
                StatcastEvent.game_pk == 777001,
                StatcastEvent.at_bat_number == 1,
                StatcastEvent.pitch_number == 1,
                StatcastEvent.pitcher_id == 1001,
                StatcastEvent.batter_id == 2001,
            )
            .first()
        )
        assert row is not None
        assert row.release_speed == 96.1
        assert row.events == "strikeout"


def test_refresh_collapses_duplicate_pitch_identities_inside_one_source_batch(monkeypatch, tmp_path):
    Session = _session_factory(tmp_path)
    duplicated = pd.concat([_sample_statcast_df(), _sample_statcast_df().iloc[[0]]], ignore_index=True)
    monkeypatch.setattr(etl, "fetch_statcast_all_events", lambda start, end: duplicated)

    with Session() as session:
        result = etl.refresh_statcast_events_for_date(session, "2026-05-18")

        assert result["rows_returned"] == 3
        assert result["input_duplicates"] == 1
        assert result["inserted"] == 2
        assert session.query(StatcastEvent).count() == 2


def test_recompute_recent_aggregates_from_events_creates_pitcher_and_batter_90d_rows(monkeypatch, tmp_path):
    Session = _session_factory(tmp_path)
    monkeypatch.setattr(etl, "fetch_statcast_all_events", lambda start, end: _sample_statcast_df())

    with Session() as session:
        etl.refresh_statcast_events_for_date(session, "2026-05-18")
        summary = etl.recompute_recent_aggregates_from_events(
            session,
            end_date=dt.date(2026, 5, 18),
            pitcher_ids=[1001],
            batter_ids=[2001],
            refresh_pitch_arsenal=False,
        )

        assert summary["pitcher_aggregates_refreshed"] == 1
        assert summary["batter_aggregates_refreshed"] == 1
        assert summary["pitch_arsenal_pitchers_refreshed"] == 0
