from datetime import date

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from mlb_app.database import Base
from mlb_app.final_game_snapshots import (
    build_final_game_payload,
    get_final_snapshot,
    list_final_snapshots,
    persist_final_snapshot,
)


def _player(player_id, name, *, batting=None, pitching=None, order=None, substitute=False, position="DH"):
    return {
        "person": {"id": player_id, "fullName": name},
        "position": {"abbreviation": position},
        "battingOrder": order,
        "gameStatus": {"isSubstitute": substitute},
        "stats": {"batting": batting or {}, "pitching": pitching or {}},
        "seasonStats": {
            "batting": {"avg": ".280", "ops": ".850"} if batting else {},
            "pitching": {"era": "3.25"} if pitching else {},
        },
    }


def final_feed():
    away_players = {
        "ID1": _player(1, "Away Starter", batting={"atBats": 4, "hits": 2, "runs": 1, "rbi": 2, "homeRuns": 1, "baseOnBalls": 0, "strikeOuts": 1}, order="100", position="RF"),
        "ID2": _player(2, "Away Pinch Hitter", batting={"atBats": 1, "hits": 1, "runs": 0, "rbi": 1, "homeRuns": 0, "baseOnBalls": 0, "strikeOuts": 0}, order="101", substitute=True, position="PH"),
        "ID10": _player(10, "Away Pitcher", pitching={"inningsPitched": "6.0", "hits": 4, "runs": 2, "earnedRuns": 2, "baseOnBalls": 1, "strikeOuts": 7, "homeRuns": 1, "numberOfPitches": 92, "strikes": 61}),
        "ID11": _player(11, "Away Reliever", pitching={"inningsPitched": "3.0", "hits": 1, "runs": 0, "earnedRuns": 0, "baseOnBalls": 0, "strikeOuts": 4, "homeRuns": 0, "numberOfPitches": 38, "strikes": 27}),
    }
    home_players = {
        "ID3": _player(3, "Home Hitter", batting={"atBats": 4, "hits": 1, "runs": 1, "rbi": 1, "homeRuns": 1, "baseOnBalls": 0, "strikeOuts": 2}, order="100", position="1B"),
        "ID20": _player(20, "Home Pitcher", pitching={"inningsPitched": "5.0", "hits": 6, "runs": 3, "earnedRuns": 3, "baseOnBalls": 2, "strikeOuts": 5, "homeRuns": 1, "numberOfPitches": 86, "strikes": 55}),
        "ID21": _player(21, "Home Relief One", pitching={"inningsPitched": "2.0", "hits": 1, "runs": 0, "earnedRuns": 0, "baseOnBalls": 0, "strikeOuts": 2, "homeRuns": 0, "numberOfPitches": 24, "strikes": 18}),
        "ID22": _player(22, "Home Relief Two", pitching={"inningsPitched": "2.0", "hits": 0, "runs": 0, "earnedRuns": 0, "baseOnBalls": 1, "strikeOuts": 1, "homeRuns": 0, "numberOfPitches": 29, "strikes": 17}),
    }
    return {
        "gameData": {
            "game": {"pk": 777},
            "datetime": {"officialDate": "2026-08-07", "dateTime": "2026-08-07T23:10:00Z"},
            "status": {"abstractGameState": "Final", "detailedState": "Final", "codedGameState": "F"},
            "teams": {
                "away": {"id": 100, "name": "Away Club", "abbreviation": "AWY"},
                "home": {"id": 200, "name": "Home Club", "abbreviation": "HME"},
            },
            "venue": {"name": "Test Park"},
        },
        "liveData": {
            "boxscore": {
                "teams": {
                    "away": {"players": away_players, "batters": [1, 2], "battingOrder": [1, 2], "pitchers": [10, 11]},
                    "home": {"players": home_players, "batters": [3], "battingOrder": [3], "pitchers": [20, 21, 22]},
                }
            },
            "linescore": {
                "teams": {
                    "away": {"runs": 4, "hits": 8, "errors": 0, "leftOnBase": 6},
                    "home": {"runs": 2, "hits": 5, "errors": 1, "leftOnBase": 4},
                },
                "innings": [
                    {"num": 1, "ordinalNum": "1st", "away": {"runs": 1, "hits": 2, "errors": 0}, "home": {"runs": 0, "hits": 0, "errors": 0}},
                    {"num": 9, "ordinalNum": "9th", "away": {"runs": 0, "hits": 0, "errors": 0}, "home": {"runs": 0, "hits": 0, "errors": 0}},
                ],
            },
            "decisions": {
                "winner": {"id": 10, "fullName": "Away Pitcher"},
                "loser": {"id": 20, "fullName": "Home Pitcher"},
                "save": {"id": 11, "fullName": "Away Reliever"},
            },
            "plays": {
                "allPlays": [
                    {
                        "about": {"inning": 1, "halfInning": "top", "isScoringPlay": True},
                        "result": {"event": "Home Run", "description": "Away Starter homered.", "awayScore": 1, "homeScore": 0},
                    }
                ]
            },
        },
    }


def test_final_payload_includes_substitutes_all_relievers_and_summary():
    payload = build_final_game_payload(final_feed())

    assert payload["status"] == "Final"
    assert payload["boxscore"]["away"]["batters"][1]["entry_label"] == "PH"
    assert payload["boxscore"]["away"]["batters"][1]["is_substitute"] is True
    assert [row["name"] for row in payload["boxscore"]["home"]["pitchers"]] == [
        "Home Pitcher", "Home Relief One", "Home Relief Two"
    ]
    assert payload["boxscore"]["away"]["pitchers"][0]["era"] == "3.25"
    assert payload["abs_tracker"]["available"] is False
    assert payload["scoring_plays"][0]["away_score"] == 1
    assert len(payload["summary"].split()) <= 150


def test_final_snapshot_is_idempotent_and_listed_by_official_date():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)

    with Session() as session:
        first = persist_final_snapshot(session, final_feed())
        second = persist_final_snapshot(session, final_feed())
        assert first.id == second.id
        assert get_final_snapshot(session, 777).payload_json["summary"]
        rows = list_final_snapshots(session, date(2026, 8, 7))
        assert [row.game_pk for row in rows] == [777]

