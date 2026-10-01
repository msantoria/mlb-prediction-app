from dataclasses import replace
import datetime as dt

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from mlb_app.final_game_snapshots import FinalGameSnapshot
from mlb_app.simulation.shadow.observed_run_environment_source import (
    CanonicalObservedRunEnvironment,
    source_canonical_observed_run_environment,
)


@pytest.fixture
def session():
    engine = create_engine("sqlite:///:memory:")
    FinalGameSnapshot.__table__.create(engine)
    factory = sessionmaker(bind=engine)
    value = factory()
    try:
        yield value
    finally:
        value.close()
        engine.dispose()


def batter(
    *,
    at_bats=4,
    hits=1,
    doubles=0,
    triples=0,
    home_runs=0,
    walks=0,
    hit_by_pitch=0,
    strikeouts=1,
    stolen_bases=0,
    caught_stealing=0,
):
    return {
        "at_bats": at_bats,
        "hits": hits,
        "doubles": doubles,
        "triples": triples,
        "home_runs": home_runs,
        "walks": walks,
        "hit_by_pitch": hit_by_pitch,
        "strikeouts": strikeouts,
        "stolen_bases": stolen_bases,
        "caught_stealing": caught_stealing,
    }


def payload(
    *,
    away_batters=None,
    home_batters=None,
    away_lob=5,
    home_lob=6,
    away_errors=0,
    home_errors=0,
):
    return {
        "boxscore": {
            "away": {
                "batters": away_batters or [batter()]
            },
            "home": {
                "batters": home_batters or [batter()]
            },
        },
        "linescore": {
            "totals": {
                "away": {
                    "left_on_base": away_lob,
                    "errors": away_errors,
                },
                "home": {
                    "left_on_base": home_lob,
                    "errors": home_errors,
                },
            }
        },
    }


def add_snapshot(
    session,
    *,
    game_pk,
    official_date="2026-08-15",
    away_score=3,
    home_score=2,
    payload_json=None,
    snapshot_version=1,
):
    value = FinalGameSnapshot(
        game_pk=game_pk,
        official_date=dt.date.fromisoformat(official_date),
        status_detail="Final",
        away_score=away_score,
        home_score=home_score,
        payload_json=payload_json or payload(),
        snapshot_version=snapshot_version,
        source="mlb_live_feed",
    )
    session.add(value)
    session.commit()
    return value


def source(session):
    return source_canonical_observed_run_environment(
        session,
        window_start="2026-08-01",
        window_end="2026-08-31",
        through_date="2026-09-01",
    )


def test_sources_observed_run_environment(session):
    add_snapshot(
        session,
        game_pk=1001,
        away_score=3,
        home_score=2,
        payload_json=payload(
            away_batters=[
                batter(
                    at_bats=5,
                    hits=2,
                    doubles=1,
                    walks=1,
                    strikeouts=2,
                )
            ],
            home_batters=[
                batter(
                    at_bats=4,
                    hits=1,
                    home_runs=1,
                    hit_by_pitch=1,
                )
            ],
        ),
    )
    add_snapshot(
        session,
        game_pk=1002,
        official_date="2026-08-16",
        away_score=1,
        home_score=0,
    )

    result = source(session)

    assert isinstance(result, CanonicalObservedRunEnvironment)
    assert result.game_count == 2
    assert result.query_row_count == 2
    assert result.excluded_snapshot_count == 0
    assert result.away_runs.mean == 2.0
    assert result.home_runs.mean == 1.0
    assert result.total_runs.mean == 3.0
    assert len(result.query_digest) == 64
    assert len(result.artifact_digest) == 64
    metrics = dict(result.box_score_metric_means)
    assert metrics["runs_per_game"] == 3.0
    assert metrics["observed_opportunities_per_game"] == 9.5
    assert "plate_appearances_per_game" not in metrics
    assert "reached_on_error_per_game" not in metrics


def test_excludes_incomplete_snapshot_without_hiding_query(session):
    add_snapshot(session, game_pk=2001)
    add_snapshot(
        session,
        game_pk=2002,
        official_date="2026-08-16",
        away_score=None,
    )

    result = source(session)

    assert result.game_count == 1
    assert result.query_row_count == 2
    assert result.excluded_snapshot_count == 1
    assert dict(result.snapshot_version_counts) == {"1": 1}


def test_source_is_deterministic_and_read_only(session):
    add_snapshot(session, game_pk=3001)
    before = session.query(FinalGameSnapshot).count()

    first = source(session)
    second = source(session)

    assert first == second
    assert first.query_digest == second.query_digest
    assert first.artifact_digest == second.artifact_digest
    assert session.query(FinalGameSnapshot).count() == before


def test_diagnostics_are_measurement_only(session):
    add_snapshot(session, game_pk=4001)

    diagnostics = source(session).to_diagnostics()

    assert diagnostics["status"] == "ready"
    assert diagnostics["ready"] is True
    assert diagnostics["score_source"] == (
        "final_game_snapshots"
    )
    assert diagnostics["box_score_source"] == (
        "final_game_snapshots.payload_json"
    )
    assert diagnostics["database_accessed"] is True
    assert diagnostics["database_query_mode"] == "read_only"
    assert diagnostics["network_accessed"] is False
    assert diagnostics["external_fetch_performed"] is False
    assert diagnostics["persistence_performed"] is False
    assert diagnostics["measurement_only"] is True
    assert diagnostics["calibration_parameters_selected"] is False
    assert diagnostics["activation_permitted"] is False
    assert diagnostics["production_authority_changed"] is False


def test_observed_rates_use_explicit_available_denominator(session):
    add_snapshot(
        session,
        game_pk=5001,
        away_score=3,
        home_score=2,
    )

    result = source(session)
    rates = dict(result.scoring_rates)
    thresholds = dict(result.total_threshold_rates)

    assert rates["hit_rate_per_observed_opportunity"] == 0.25
    assert rates["known_reach_rate_per_observed_opportunity"] == 0.25
    assert "hit_rate_per_pa" not in rates
    assert thresholds["total_runs_5_or_fewer_rate"] == 1.0
    assert thresholds["total_runs_6_or_fewer_rate"] == 1.0
    assert thresholds["total_runs_9_or_more_rate"] == 0.0


def test_rejects_empty_or_fully_incomplete_window(session):
    with pytest.raises(
        ValueError,
        match="no final game snapshots",
    ):
        source(session)

    add_snapshot(
        session,
        game_pk=6001,
        away_score=None,
    )

    with pytest.raises(
        ValueError,
        match="no complete final game snapshots",
    ):
        source(session)


def test_rejects_invalid_window_bounds(session):
    with pytest.raises(
        ValueError,
        match="must not precede",
    ):
        source_canonical_observed_run_environment(
            session,
            window_start="2026-08-31",
            window_end="2026-08-01",
            through_date="2026-09-01",
        )

    with pytest.raises(
        ValueError,
        match="must not exceed",
    ):
        source_canonical_observed_run_environment(
            session,
            window_start="2026-08-01",
            window_end="2026-09-02",
            through_date="2026-09-01",
        )


def test_digests_change_when_observed_rows_change(session):
    add_snapshot(session, game_pk=7001)
    first = source(session)

    add_snapshot(
        session,
        game_pk=7002,
        official_date="2026-08-16",
        away_score=8,
        home_score=7,
    )
    second = source(session)

    assert first.query_digest != second.query_digest
    assert first.artifact_digest != second.artifact_digest
    assert first.source_identifier != second.source_identifier


def test_rejects_invalid_observed_artifact_contract(session):
    add_snapshot(session, game_pk=8001)
    valid = source(session)

    with pytest.raises(
        ValueError,
        match="artifact_digest",
    ):
        replace(valid, artifact_digest="invalid")

    with pytest.raises(
        ValueError,
        match="excluded snapshot count must reconcile",
    ):
        replace(valid, excluded_snapshot_count=1)
