from contextlib import nullcontext
from dataclasses import dataclass

from mlb_app import model_projections


@dataclass
class Side:
    bullpen_pitcher_ids: tuple
    active_roster_records: tuple


@dataclass
class Bullpens:
    away: Side
    home: Side


@dataclass
class Lineups:
    away_player_ids: tuple
    home_player_ids: tuple


def bullpens():
    return Bullpens(
        away=Side(
            bullpen_pitcher_ids=("101", "102"),
            active_roster_records=(
                {
                    "mlb_player_id": 100,
                    "throws": "R",
                },
                {
                    "mlb_player_id": 101,
                    "throws": "L",
                },
                {
                    "mlb_player_id": 102,
                    "throws": "R",
                },
            ),
        ),
        home=Side(
            bullpen_pitcher_ids=("201",),
            active_roster_records=(
                {
                    "mlb_player_id": 200,
                    "throws": "R",
                },
                {
                    "mlb_player_id": 201,
                    "throws": "L",
                },
            ),
        ),
    )


def test_usage_evidence_contains_only_strict_bullpen_members():
    result = (
        model_projections
        ._canonical_matchup_bullpen_usage_evidence(
            bullpen_discovery=bullpens(),
            pitcher_role_evidence={
                "evidence_by_pitcher_id": {
                    "100": {
                        "typical_role": "starter",
                    },
                    "101": {
                        "typical_role": "closer",
                    },
                    "102": {
                        "typical_role":
                            "middle_reliever",
                    },
                    "201": {
                        "typical_role": "setup",
                    },
                },
            },
        )
    )

    assert set(result) == {
        "101",
        "102",
        "201",
    }
    assert result["101"]["typical_role"] == (
        "closer"
    )
    assert result["101"]["throws"] == "L"
    assert result["102"]["throws"] == "R"
    assert result["201"]["throws"] == "L"
    assert "100" not in result


def test_usage_evidence_does_not_fabricate_fatigue():
    result = (
        model_projections
        ._canonical_matchup_bullpen_usage_evidence(
            bullpen_discovery=bullpens(),
            pitcher_role_evidence={
                "evidence_by_pitcher_id": {},
            },
        )
    )

    assert result["101"] == {
        "pitcher_id": "101",
        "throws": "L",
    }
    assert "fatigue_index" not in result["101"]
    assert (
        "consecutive_days_worked"
        not in result["101"]
    )
    assert "recent_pitch_count" not in result["101"]


class Query:
    def __init__(self, rows):
        self.rows = rows
        self.requested_ids = None

    def filter(self, expression):
        self.requested_ids = set(
            expression.right.value
        )
        return self

    def all(self):
        return [
            row
            for row in self.rows
            if row[0] in self.requested_ids
        ]


class Session:
    def __init__(self, rows):
        self.rows = rows
        self.query_count = 0

    def begin_nested(self):
        return nullcontext()

    def query(self, *columns):
        self.query_count += 1
        return Query(self.rows)


def test_confirmed_lineup_handedness_is_loaded_once():
    session = Session([
        (1, "L"),
        (2, "R"),
        (3, "S"),
        (4, "B"),
        (999, "L"),
    ])

    result = (
        model_projections
        ._canonical_matchup_batter_handedness(
            session=session,
            lineup_discovery=Lineups(
                away_player_ids=("1", "2"),
                home_player_ids=("3", "4"),
            ),
        )
    )

    assert result == {
        "1": "L",
        "2": "R",
        "3": "S",
    }
    assert session.query_count == 1
    assert "999" not in result


class FailingSession:
    def begin_nested(self):
        raise RuntimeError("directory unavailable")


def test_handedness_query_failure_fails_soft():
    result = (
        model_projections
        ._canonical_matchup_batter_handedness(
            session=FailingSession(),
            lineup_discovery=Lineups(
                away_player_ids=("1",),
                home_player_ids=("2",),
            ),
        )
    )

    assert result == {}


def test_missing_confirmed_lineups_avoid_database_query():
    session = Session([])

    result = (
        model_projections
        ._canonical_matchup_batter_handedness(
            session=session,
            lineup_discovery=Lineups(
                away_player_ids=(),
                home_player_ids=(),
            ),
        )
    )

    assert result == {}
    assert session.query_count == 0
