from dataclasses import dataclass

from mlb_app.simulation.shadow import (
    materialize_canonical_selected_lineup_profiles,
)


@dataclass(frozen=True)
class Selected:
    away_player_ids: tuple[str, ...]
    home_player_ids: tuple[str, ...]
    lineup_source: str = "projected"
    lineup_digest: str = "digest"
    confidence: str = "provisional"


def _players(start):
    return tuple(
        str(start + offset)
        for offset in range(9)
    )


def _context(team_id):
    return {
        "team_id": team_id,
        "offense_inputs": {
            "source": "team_split",
            "marker": team_id,
        },
    }


def _profile(side, lineups):
    rows = lineups[side]
    return {
        "source": "lineup_profiles",
        "lineup": [
            {
                "batter_id": row["batter_id"],
                "simulation_inputs": {
                    "single": 0.15,
                },
                "has_player_split": True,
            }
            for row in rows
        ],
    }


def test_materializes_both_projected_sides_atomically():
    calls = []

    def builder(**kwargs):
        calls.append(kwargs)
        return _profile(
            kwargs["side"],
            kwargs["lineups"],
        )

    result = (
        materialize_canonical_selected_lineup_profiles(
            session=object(),
            matchup={
                "game_pk": 822848,
                "home_pitcher_hand": "L",
                "away_pitcher_hand": "R",
            },
            away_context=_context(10),
            home_context=_context(20),
            lineups=Selected(
                away_player_ids=_players(100),
                home_player_ids=_players(200),
            ),
            season=2026,
            profile_builder=builder,
        )
    )

    assert result.ready is True
    assert [call["side"] for call in calls] == [
        "away",
        "home",
    ]
    assert calls[0]["split"] == "vsL"
    assert calls[1]["split"] == "vsR"
    assert calls[0]["team_id"] == 10
    assert calls[1]["team_id"] == 20
    assert [
        row["batter_id"]
        for row in calls[0]["lineups"]["away"]
    ] == list(range(100, 109))
    assert result.away_context[
        "offense_inputs"
    ]["lineup_source"] == "projected"
    assert result.home_context[
        "offense_inputs"
    ]["lineup_digest"] == "digest"


def test_one_failed_side_preserves_both_contexts():
    away = _context(10)
    home = _context(20)

    def builder(**kwargs):
        if kwargs["side"] == "home":
            return None
        return _profile(
            kwargs["side"],
            kwargs["lineups"],
        )

    result = (
        materialize_canonical_selected_lineup_profiles(
            session=object(),
            matchup={"game_pk": 822848},
            away_context=away,
            home_context=home,
            lineups=Selected(
                away_player_ids=_players(100),
                home_player_ids=_players(200),
            ),
            season=2026,
            profile_builder=builder,
        )
    )

    assert result.ready is False
    assert result.blocker == (
        "home_projected_lineup_profiles_unavailable"
    )
    assert result.away_context == away
    assert result.home_context == home


def test_confirmed_selection_is_not_rebuilt():
    calls = []

    result = (
        materialize_canonical_selected_lineup_profiles(
            session=object(),
            matchup={"game_pk": 822848},
            away_context=_context(10),
            home_context=_context(20),
            lineups=Selected(
                away_player_ids=_players(100),
                home_player_ids=_players(200),
                lineup_source="confirmed",
            ),
            season=2026,
            profile_builder=lambda **kwargs: calls.append(
                kwargs
            ),
        )
    )

    assert calls == []
    assert result.status == "skipped"
    assert result.blocker == (
        "selected_lineup_is_not_projected"
    )


def test_diagnostics_redact_player_identifiers():
    result = (
        materialize_canonical_selected_lineup_profiles(
            session=object(),
            matchup={"game_pk": 822848},
            away_context=_context(10),
            home_context=_context(20),
            lineups=Selected(
                away_player_ids=_players(100),
                home_player_ids=_players(200),
            ),
            season=2026,
            profile_builder=lambda **kwargs: _profile(
                kwargs["side"],
                kwargs["lineups"],
            ),
        )
    )

    diagnostics = result.to_diagnostics()
    rendered = str(diagnostics)

    assert diagnostics["ready"] is True
    assert diagnostics[
        "atomic_context_replacement"
    ] is True
    assert diagnostics[
        "player_identifiers_exposed"
    ] is False
    assert "100" not in rendered
    assert "200" not in rendered
