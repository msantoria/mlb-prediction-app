import datetime as dt

from mlb_app.database import StatcastEvent, create_tables, get_engine, get_session
from mlb_app.db_utils import get_batter_leaderboards
from mlb_app.official_player_stats import (
    OFFICIAL_HITTING_SOURCE,
    normalize_official_hitting_splits,
)


def _session():
    engine = get_engine("sqlite:///:memory:")
    create_tables(engine)
    return get_session(engine)()


def _official_payload():
    return {
        "stats": [{
            "splits": [{
                "player": {"id": 202, "fullName": "Correct Batter"},
                "team": {"abbreviation": "CHC"},
                "stat": {
                    "plateAppearances": 400,
                    "atBats": 350,
                    "hits": 100,
                    "doubles": 21,
                    "homeRuns": 27,
                    "rbi": 77,
                    "baseOnBalls": 42,
                    "strikeOuts": 80,
                    "avg": ".286",
                    "slg": ".520",
                },
            }]
        }]
    }


def test_normalizes_official_mlb_hitting_line():
    row = normalize_official_hitting_splits(_official_payload(), 2026)[0]

    assert row["player_id"] == 202
    assert row["pa"] == 400
    assert row["home_runs"] == 27
    assert row["rbi"] == 77
    assert row["iso"] == 0.234
    assert row["source"] == OFFICIAL_HITTING_SOURCE


def test_homepage_counting_boards_use_official_totals_not_local_reconstruction():
    session = _session()
    session.add(StatcastEvent(
        game_date=dt.date(2026, 8, 25),
        game_pk=9001,
        at_bat_number=1,
        pitch_number=1,
        pitcher_id=101,
        batter_id=202,
        events="home_run",
        description="hit_into_play",
        launch_speed=101.0,
        launch_angle=28.0,
    ))
    session.commit()

    official_rows = normalize_official_hitting_splits(_official_payload(), 2026)
    result = get_batter_leaderboards(
        session,
        season=2026,
        min_pa=1,
        min_bbe=1,
        limit=10,
        official_hitting={
            "source": OFFICIAL_HITTING_SOURCE,
            "season": 2026,
            "retrieved_at": "2026-08-25T12:00:00+00:00",
            "rows": official_rows,
        },
    )

    assert result["contract_version"] == "batter_leaderboards_v3"
    assert result["leaderboards"]["home_runs"][0]["value"] == 27
    assert result["leaderboards"]["home_runs"][0]["pa"] == 400
    assert result["leaderboards"]["rbi"][0]["value"] == 77
    assert result["leaderboards"]["avg_exit_velocity"][0]["bbe"] == 1
    assert result["sources"]["counting"] == OFFICIAL_HITTING_SOURCE


def test_missing_official_feed_never_falls_back_to_local_counting_totals(monkeypatch):
    session = _session()
    monkeypatch.setattr("mlb_app.db_utils._latest_batter_names", lambda _session: {202: "Correct Batter"})
    session.add(StatcastEvent(
        game_date=dt.date(2026, 8, 25),
        game_pk=9001,
        at_bat_number=1,
        pitch_number=1,
        pitcher_id=101,
        batter_id=202,
        events="home_run",
        description="hit_into_play",
        launch_speed=101.0,
        launch_angle=28.0,
    ))
    session.commit()

    result = get_batter_leaderboards(
        session,
        season=2026,
        min_pa=1,
        min_bbe=1,
        limit=10,
        official_hitting=None,
    )

    assert "home_runs" not in result["leaderboards"]
    assert result["leaderboards"]["avg_exit_velocity"][0]["value"] == 101.0
    assert result["sources"]["counting"] is None
