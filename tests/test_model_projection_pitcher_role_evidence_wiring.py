from copy import deepcopy
from dataclasses import dataclass

import pytest

from mlb_app import model_projections


@dataclass
class Side:
    team_id: str
    active_roster_records: tuple


@dataclass
class Discovery:
    away: Side
    home: Side


class Result:
    def __init__(self, team_id, role):
        pitcher_id = str(team_id * 10 + 1)
        self.role_evidence = {
            "evidence_by_pitcher_id": {
                pitcher_id: {
                    "pitcher_id": pitcher_id,
                    "typical_role": role,
                    "confidence": "high",
                    "source": "test_history",
                    "inference_used": True,
                },
            },
        }
        self._diagnostics = {
            "schema_version":
                "canonical_pitcher_role_"
                "evidence_source_v1",
            "status": "materialized",
            "team_id": str(team_id),
            "as_of_date": "2026-08-15",
            "lookback_days": 60,
            "maximum_final_games": 10,
            "scheduled_final_game_count": 10,
            "fetched_final_game_count": 10,
            "feed_error_count": 0,
            "resolved_typical_role_count": 1,
            "detected_opener_bulk_pair_count": 0,
            "bounded_game_fetch": True,
            "simulation_trial_fetches_performed": 0,
            "planned_role_claimed": False,
            "future_assignment_inferred": False,
            "database_writes_performed": False,
            "production_authority_changed": False,
        }

    def to_diagnostics(self):
        return deepcopy(self._diagnostics)


def discovery():
    return Discovery(
        away=Side(
            team_id="10",
            active_roster_records=({
                "mlb_player_id": 101,
                "player_type": "pitcher",
            },),
        ),
        home=Side(
            team_id="20",
            active_roster_records=({
                "mlb_player_id": 201,
                "player_type": "pitcher",
            },),
        ),
    )


def test_materializes_both_sides_with_shared_cache():
    calls = []
    cache = {}

    def fetcher(**kwargs):
        calls.append(kwargs)
        team_id = int(kwargs["team_id"])
        return Result(
            team_id,
            "closer"
            if team_id == 10
            else "setup",
        )

    result = (
        model_projections
        ._materialize_matchup_pitcher_role_evidence(
            bullpen_discovery=discovery(),
            season=2026,
            as_of="2026-08-15",
            cache=cache,
            fetcher=fetcher,
        )
    )

    assert len(calls) == 2
    assert all(
        call["cache"] is cache
        for call in calls
    )
    assert result["evidence_by_pitcher_id"][
        "101"
    ]["typical_role"] == "closer"
    assert result["evidence_by_pitcher_id"][
        "201"
    ]["typical_role"] == "setup"
    assert result[
        "simulation_trial_fetches_performed"
    ] == 0


def test_source_diagnostics_are_redacted():
    result = (
        model_projections
        ._materialize_matchup_pitcher_role_evidence(
            bullpen_discovery=discovery(),
            season=2026,
            as_of="2026-08-15",
            cache={},
            fetcher=lambda **kwargs: Result(
                int(kwargs["team_id"]),
                "middle_reliever",
            ),
        )
    )

    diagnostics = result[
        "source_diagnostics_by_team_side"
    ]

    assert set(diagnostics) == {
        "away",
        "home",
    }
    assert all(
        row["pitcher_identifiers_exposed"]
        is False
        for row in diagnostics.values()
    )
    assert all(
        "evidence_by_pitcher_id" not in row
        for row in diagnostics.values()
    )


def test_one_side_failure_fails_open():
    def fetcher(**kwargs):
        if str(kwargs["team_id"]) == "10":
            raise RuntimeError("away unavailable")
        return Result(20, "setup")

    result = (
        model_projections
        ._materialize_matchup_pitcher_role_evidence(
            bullpen_discovery=discovery(),
            season=2026,
            as_of="2026-08-15",
            cache={},
            fetcher=fetcher,
        )
    )

    assert set(
        result["evidence_by_pitcher_id"]
    ) == {"201"}
    assert result[
        "source_diagnostics_by_team_side"
    ]["away"]["status"] == "error"
    assert result[
        "source_diagnostics_by_team_side"
    ]["home"]["status"] == "materialized"


def test_rejects_non_dictionary_cache():
    with pytest.raises(
        TypeError,
        match="cache must be a dictionary",
    ):
        (
            model_projections
            ._materialize_matchup_pitcher_role_evidence(
                bullpen_discovery=discovery(),
                season=2026,
                as_of="2026-08-15",
                cache=[],
            )
        )
