import datetime as dt
from dataclasses import replace

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from mlb_app.database import StatcastEvent
from mlb_app.simulation.events import (
    OutRecord,
    PlayEvent,
)
from mlb_app.simulation.game import (
    CanonicalDefensiveEventAuthorityRecord,
    CanonicalExecutedTrial,
    CanonicalGameConfig,
    CanonicalLineup,
    run_canonical_trials,
    simulate_canonical_game,
)
from mlb_app.simulation.shadow.defensive_trial_evidence import (
    CANONICAL_DEFENSIVE_TRIAL_EVIDENCE_VERSION,
    CanonicalDefensiveTrialEvidence,
    execute_canonical_defensive_trial_evidence,
)


def lineup(side):
    return CanonicalLineup(
        team_side=side,
        player_ids=tuple(
            f"{side}_{index}"
            for index in range(9)
        ),
    )


def out_event(state, batter_id, sequence):
    next_out = state.outs + 1
    fielding_side = (
        "home"
        if state.half == "top"
        else "away"
    )

    return PlayEvent(
        sequence=sequence,
        event_type="out",
        batter_id=batter_id,
        state_before=state,
        state_after=replace(
            state,
            outs=next_out,
            batting_order_index=(
                state.batting_order_index + 1
            ) % 9,
            plate_appearance_number=(
                state.plate_appearance_number + 1
            ),
        ),
        outs_recorded=(
            OutRecord(
                runner_id=batter_id,
                out_number=next_out,
                reason="test_out",
            ),
        ),
        pitcher_id=f"{fielding_side}_pitcher",
    )


def trial_factory(*, include_authority):
    def factory(index):
        def resolver(state, batter_id, sequence):
            return out_event(
                state,
                batter_id,
                sequence,
            )

        game = simulate_canonical_game(
            away_lineup=lineup("away"),
            home_lineup=lineup("home"),
            resolve_plate_appearance=resolver,
            config=CanonicalGameConfig(
                regulation_innings=1,
                max_extra_innings=0,
                automatic_runner_enabled=False,
            ),
        )

        if not include_authority:
            return game

        return CanonicalExecutedTrial(
            game=game,
            defensive_event_authority_records=(
                CanonicalDefensiveEventAuthorityRecord(
                    applied=False,
                    authoritative=False,
                    original_event_type="out",
                    final_event_type="out",
                    blocker=(
                        "defensive_outcome_unchanged"
                    ),
                ),
            ),
        )

    return factory


def batch(*, include_authority=True, simulations=2):
    return run_canonical_trials(
        trial_factory=trial_factory(
            include_authority=include_authority,
        ),
        simulations=simulations,
        model_version="defensive_trial_evidence_test_v1",
    )


@pytest.fixture
def session():
    engine = create_engine("sqlite:///:memory:")
    StatcastEvent.__table__.create(engine)
    factory = sessionmaker(bind=engine)
    value = factory()

    try:
        yield value
    finally:
        value.close()
        engine.dispose()


def add_observed_out(session):
    session.add(
        StatcastEvent(
            game_date=dt.date(2026, 8, 15),
            game_pk=1001,
            at_bat_number=1,
            pitch_number=1,
            pitcher_id=10,
            batter_id=20,
            events="field_out",
        )
    )
    session.commit()


def execute(session, trial_batch):
    return execute_canonical_defensive_trial_evidence(
        session,
        trial_batch=trial_batch,
        window_start="2026-08-01",
        window_end="2026-08-31",
        through_date="2026-09-01",
    )


def test_executes_evidence_from_real_trial_batch(session):
    add_observed_out(session)
    trial_batch = batch(
        include_authority=True,
        simulations=2,
    )

    result = execute(session, trial_batch)

    assert result.status == "ready"
    assert result.ready is True
    assert result.simulation_count == 2
    assert result.authority_observation_count == 2
    assert len(result.authority_digest) == 64
    assert (
        result.database_evidence.evidence
        .backtest.simulation_observation_count
        == 2
    )
    assert (
        result.database_evidence.evidence
        .backtest.total_variation_distance
        == 0.0
    )


def test_uses_batch_owned_authority_summary(session):
    add_observed_out(session)
    trial_batch = batch(
        include_authority=True,
        simulations=3,
    )
    owned_summary = (
        trial_batch.diagnostics
        .defensive_event_authority
    )

    result = execute(session, trial_batch)

    assert result.authority_observation_count == (
        owned_summary.observation_count
    )
    assert (
        result.database_evidence.evidence
        .backtest.authority_rate
        == owned_summary.authority_rate
    )
    assert (
        result.database_evidence.evidence
        .backtest.blocker_counts
        == owned_summary.blocker_counts
    )


def test_empty_batch_authority_is_unavailable(session):
    add_observed_out(session)
    trial_batch = batch(
        include_authority=False,
        simulations=1,
    )

    result = execute(session, trial_batch)

    assert result.status == "unavailable"
    assert result.ready is False
    assert result.simulation_count == 1
    assert result.authority_observation_count == 0
    assert (
        result.blocker
        == "simulation_distribution_empty"
    )


def test_empty_database_window_is_unavailable(session):
    result = execute(
        session,
        batch(
            include_authority=True,
            simulations=1,
        ),
    )

    assert result.status == "unavailable"
    assert result.ready is False
    assert result.blocker == "database_window_empty"
    assert result.database_evidence.evidence is None


def test_authority_digest_is_deterministic(session):
    add_observed_out(session)
    trial_batch = batch(
        include_authority=True,
        simulations=2,
    )

    first = execute(session, trial_batch)
    second = execute(session, trial_batch)

    assert first.authority_digest == (
        second.authority_digest
    )
    assert first.to_diagnostics() == (
        second.to_diagnostics()
    )


def test_diagnostics_preserve_trial_ownership(session):
    add_observed_out(session)
    result = execute(
        session,
        batch(
            include_authority=True,
            simulations=1,
        ),
    )

    diagnostics = result.to_diagnostics()

    assert diagnostics["schema_version"] == (
        CANONICAL_DEFENSIVE_TRIAL_EVIDENCE_VERSION
    )
    assert diagnostics["trial_batch_consumed"] is True
    assert (
        diagnostics["independent_authority_aggregation"]
        is False
    )
    assert diagnostics["authority_source"] == (
        "trial_batch.diagnostics."
        "defensive_event_authority"
    )
    assert diagnostics["measurement_only"] is True
    assert diagnostics["database_accessed"] is True
    assert diagnostics["database_query_mode"] == "read_only"
    assert diagnostics["network_accessed"] is False
    assert diagnostics["external_fetch_performed"] is False
    assert diagnostics["persistence_performed"] is False
    assert (
        diagnostics["calibration_parameters_selected"]
        is False
    )
    assert diagnostics["activation_permitted"] is False
    assert (
        diagnostics["production_authority_changed"]
        is False
    )


def test_rejects_noncanonical_trial_batch(session):
    with pytest.raises(
        TypeError,
        match="CanonicalTrialBatch",
    ):
        execute_canonical_defensive_trial_evidence(
            session,
            trial_batch=object(),
            window_start="2026-08-01",
            window_end="2026-08-31",
            through_date="2026-09-01",
        )


def test_rejects_invalid_artifact_contract(session):
    add_observed_out(session)
    valid = execute(
        session,
        batch(
            include_authority=True,
            simulations=1,
        ),
    )

    with pytest.raises(
        ValueError,
        match="simulation_count",
    ):
        CanonicalDefensiveTrialEvidence(
            simulation_count=0,
            authority_observation_count=(
                valid.authority_observation_count
            ),
            authority_digest=valid.authority_digest,
            database_evidence=(
                valid.database_evidence
            ),
        )
