import datetime as dt

from mlb_app.database import (
    PitcherAggregate,
    create_tables,
    get_engine,
    get_session,
)
from mlb_app.simulation.shadow.canonical_pitcher_matchup_profile_source import (
    CANONICAL_PITCHER_MATCHUP_PROFILE_SOURCE_VERSION,
    source_canonical_pitcher_matchup_profile,
)


def session():
    engine = get_engine("sqlite:///:memory:")
    create_tables(engine)
    return get_session(engine)()


def aggregate(
    *,
    end_date,
    pitcher_id=101,
    k_pct=0.24,
    bb_pct=0.08,
    hard_hit_pct=0.31,
    xwoba=0.315,
    xba=0.245,
):
    return PitcherAggregate(
        pitcher_id=pitcher_id,
        window="90d",
        end_date=dt.date.fromisoformat(end_date),
        k_pct=k_pct,
        bb_pct=bb_pct,
        hard_hit_pct=hard_hit_pct,
        xwoba=xwoba,
        xba=xba,
    )


def test_selects_latest_strictly_prior_aggregate():
    db = session()
    db.add_all([
        aggregate(
            end_date="2026-08-20",
            k_pct=0.20,
        ),
        aggregate(
            end_date="2026-08-22",
            k_pct=0.27,
        ),
        aggregate(
            end_date="2026-08-23",
            k_pct=0.40,
        ),
        aggregate(
            end_date="2026-08-24",
            k_pct=0.50,
        ),
    ])
    db.commit()

    result = source_canonical_pitcher_matchup_profile(
        db,
        pitcher_id=101,
        game_date="2026-08-23",
    )

    assert result["pitcher_features"]["k_pct"] == 0.27
    assert (
        result["diagnostics"]["selected_end_date"]
        == "2026-08-22"
    )
    assert result["diagnostics"]["days_before_game"] == 1
    assert result["diagnostics"]["status"] == "ready"


def test_matchup_values_remain_authoritative():
    db = session()
    db.add(
        aggregate(
            end_date="2026-08-22",
            k_pct=0.24,
            bb_pct=0.08,
        )
    )
    db.commit()

    result = source_canonical_pitcher_matchup_profile(
        db,
        pitcher_id=101,
        game_date=dt.date(2026, 8, 23),
        matchup_features={
            "k_pct": 0.33,
            "bb_pct": 0.0,
            "custom_field": "preserved",
        },
    )

    features = result["pitcher_features"]
    provenance = result["diagnostics"][
        "field_provenance"
    ]

    assert features["k_pct"] == 0.33
    assert features["bb_pct"] == 0.0
    assert features["hard_hit_pct"] == 0.31
    assert features["custom_field"] == "preserved"
    assert provenance["k_pct"]["source"] == "matchup_payload"
    assert (
        provenance["hard_hit_pct"]["source"]
        == "pitcher_aggregate_90d"
    )


def test_partial_aggregate_reports_missing_fields():
    db = session()
    db.add(
        aggregate(
            end_date="2026-08-22",
            xwoba=None,
            xba=None,
        )
    )
    db.commit()

    result = source_canonical_pitcher_matchup_profile(
        db,
        pitcher_id=101,
        game_date="2026-08-23",
    )

    diagnostics = result["diagnostics"]

    assert diagnostics["status"] == "partial"
    assert diagnostics["missing_fields"] == [
        "xwoba",
        "xba",
    ]


def test_no_prior_evidence_fails_closed():
    db = session()
    db.add(
        aggregate(
            end_date="2026-08-23",
        )
    )
    db.commit()

    result = source_canonical_pitcher_matchup_profile(
        db,
        pitcher_id=101,
        game_date="2026-08-23",
    )

    assert result["pitcher_features"] == {}
    assert (
        result["diagnostics"]["status"]
        == "unavailable"
    )
    assert (
        result["diagnostics"]["selected_end_date"]
        is None
    )


def test_source_is_deterministic_and_does_not_mutate_input():
    db = session()
    db.add(
        aggregate(
            end_date="2026-08-22",
        )
    )
    db.commit()
    supplied = {"k_pct": 0.30}

    first = source_canonical_pitcher_matchup_profile(
        db,
        pitcher_id=101,
        game_date="2026-08-23",
        matchup_features=supplied,
    )
    second = source_canonical_pitcher_matchup_profile(
        db,
        pitcher_id=101,
        game_date="2026-08-23",
        matchup_features=supplied,
    )

    assert first == second
    assert supplied == {"k_pct": 0.30}
    assert (
        first["diagnostics"]["source_digest"]
        == second["diagnostics"]["source_digest"]
    )


def test_version_is_explicit():
    assert (
        CANONICAL_PITCHER_MATCHUP_PROFILE_SOURCE_VERSION
        == "canonical_pitcher_matchup_profile_source_v1"
    )

def test_side_context_uses_cutoff_safe_profile_source(
    monkeypatch,
):
    from mlb_app import model_projections

    db = session()
    db.add_all([
        aggregate(
            end_date="2026-08-22",
            k_pct=0.27,
        ),
        aggregate(
            end_date="2026-08-23",
            k_pct=0.49,
        ),
    ])
    db.commit()

    monkeypatch.setattr(
        model_projections,
        "_projection_offense_inputs",
        lambda **_kwargs: {},
    )
    monkeypatch.setattr(
        model_projections,
        "_bullpen_inputs",
        lambda *_args: {},
    )

    context = model_projections._side_context(
        {
            "away_team_id": 10,
            "away_team_name": "Away",
            "away_pitcher_id": 101,
            "away_pitcher_name": "Pitcher",
            "away_pitcher_features": {
                "bb_pct": 0.07,
            },
        },
        "away",
        db,
        2026,
        dt.date(2026, 8, 23),
    )

    assert (
        context["pitcher_features"]["k_pct"]
        == 0.27
    )
    assert (
        context["pitcher_features"]["bb_pct"]
        == 0.07
    )
    diagnostics = context[
        "pitcher_matchup_profile_source"
    ]
    assert (
        diagnostics["selected_end_date"]
        == "2026-08-22"
    )
    assert (
        diagnostics["field_provenance"]["bb_pct"][
            "source"
        ]
        == "matchup_payload"
    )


def test_side_context_fails_closed_without_pitcher_id(
    monkeypatch,
):
    from mlb_app import model_projections

    db = session()

    monkeypatch.setattr(
        model_projections,
        "_projection_offense_inputs",
        lambda **_kwargs: {},
    )
    monkeypatch.setattr(
        model_projections,
        "_bullpen_inputs",
        lambda *_args: {},
    )

    context = model_projections._side_context(
        {
            "away_team_id": 10,
            "away_team_name": "Away",
        },
        "away",
        db,
        2026,
        dt.date(2026, 8, 23),
    )

    assert (
        context["pitcher_matchup_profile_source"][
            "status"
        ]
        == "unavailable"
    )
    assert (
        context["pitcher_matchup_profile_source"][
            "blockers"
        ]
        == ["missing_pitcher_id"]
    )
