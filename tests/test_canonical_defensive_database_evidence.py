import datetime as dt

import pytest
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker

from mlb_app.database import StatcastEvent
from mlb_app.simulation.game import (
    CanonicalDefensiveEventAuthorityRecord,
    aggregate_canonical_defensive_event_authority,
)
from mlb_app.simulation.shadow import (
    CANONICAL_DEFENSIVE_DATABASE_EVIDENCE_VERSION,
    CanonicalDefensiveDatabaseEvidence,
    execute_canonical_defensive_database_evidence,
)


def authority_record(original, final):
    return CanonicalDefensiveEventAuthorityRecord(
        applied=original != final,
        authoritative=original != final,
        original_event_type=original,
        final_event_type=final,
        blocker=(
            None
            if original != final
            else "defensive_outcome_unchanged"
        ),
    )


def authority_summary(*records):
    return aggregate_canonical_defensive_event_authority(
        records
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


def add_event(
    session,
    *,
    game_date="2026-08-15",
    game_pk=1001,
    at_bat_number=1,
    pitch_number=1,
    events="single",
):
    session.add(
        StatcastEvent(
            game_date=dt.date.fromisoformat(game_date),
            game_pk=game_pk,
            at_bat_number=at_bat_number,
            pitch_number=pitch_number,
            pitcher_id=10,
            batter_id=20,
            events=events,
        )
    )
    session.commit()


def execute(session, summary):
    return execute_canonical_defensive_database_evidence(
        session,
        summary=summary,
        window_start="2026-08-01",
        window_end="2026-08-31",
        through_date="2026-09-01",
    )


def test_executes_ready_database_evidence(session):
    add_event(
        session,
        at_bat_number=1,
        events="single",
    )
    add_event(
        session,
        at_bat_number=2,
        events="field_out",
    )

    result = execute(
        session,
        authority_summary(
            authority_record("single", "single"),
            authority_record("out", "out"),
        ),
    )

    assert result.status == "ready"
    assert result.ready is True
    assert result.query_row_count == 2
    assert len(result.query_digest) == 64
    assert result.evidence is not None
    assert result.evidence.ready is True
    assert (
        result.evidence.backtest.total_variation_distance
        == 0.0
    )


def test_query_is_bounded_and_uses_terminal_rows(session):
    add_event(
        session,
        game_date="2026-07-31",
        at_bat_number=1,
        events="double",
    )
    add_event(
        session,
        game_date="2026-08-15",
        at_bat_number=2,
        pitch_number=1,
        events=None,
    )
    add_event(
        session,
        game_date="2026-08-15",
        at_bat_number=2,
        pitch_number=2,
        events="single",
    )
    add_event(
        session,
        game_date="2026-09-01",
        at_bat_number=3,
        events="triple",
    )

    result = execute(
        session,
        authority_summary(
            authority_record("single", "single"),
        ),
    )

    assert result.status == "ready"
    assert result.query_row_count == 1
    assert (
        result.evidence.source.source_row_count
        == 1
    )
    assert (
        result.evidence.source.observed.observation_count
        == 1
    )


def test_empty_database_window_is_unavailable(session):
    result = execute(
        session,
        authority_summary(
            authority_record("out", "out"),
        ),
    )

    assert result.status == "unavailable"
    assert result.ready is False
    assert result.query_row_count == 0
    assert result.blocker == "database_window_empty"
    assert result.evidence is None
    assert result.error is None
    assert len(result.query_digest) == 64


def test_empty_simulation_summary_is_unavailable(session):
    add_event(
        session,
        at_bat_number=1,
        events="field_out",
    )

    result = execute(
        session,
        authority_summary(),
    )

    assert result.status == "unavailable"
    assert result.query_row_count == 1
    assert result.blocker == "simulation_distribution_empty"
    assert result.evidence is not None
    assert result.evidence.status == "unavailable"


def test_conflicting_terminal_rows_fail_closed(session):
    add_event(
        session,
        at_bat_number=1,
        pitch_number=1,
        events="single",
    )
    add_event(
        session,
        at_bat_number=1,
        pitch_number=2,
        events="double",
    )

    result = execute(
        session,
        authority_summary(
            authority_record("single", "single"),
        ),
    )

    assert result.status == "error"
    assert result.ready is False
    assert result.evidence is not None
    assert result.evidence.status == "error"
    assert "conflicting terminal" in result.error


def test_database_execution_is_read_only(session):
    add_event(
        session,
        at_bat_number=1,
        events="single",
    )
    before = session.query(StatcastEvent).count()

    result = execute(
        session,
        authority_summary(
            authority_record("single", "single"),
        ),
    )

    after = session.query(StatcastEvent).count()

    assert result.status == "ready"
    assert before == after == 1
    assert tuple(session.new) == ()
    assert tuple(session.dirty) == ()
    assert tuple(session.deleted) == ()


def test_query_selects_only_required_columns(session):
    add_event(
        session,
        at_bat_number=1,
        events="single",
    )
    statements = []

    @event.listens_for(
        session.get_bind(),
        "before_cursor_execute",
    )
    def capture(
        connection,
        cursor,
        statement,
        parameters,
        context,
        executemany,
    ):
        statements.append(statement)

    result = execute(
        session,
        authority_summary(
            authority_record("single", "single"),
        ),
    )

    event.remove(
        session.get_bind(),
        "before_cursor_execute",
        capture,
    )

    assert result.status == "ready"
    query = next(
        statement
        for statement in statements
        if "FROM statcast_events" in statement
    )
    selected = query.split("FROM statcast_events", 1)[0]
    assert "game_date" in selected
    assert "game_pk" in selected
    assert "at_bat_number" in selected
    assert "events" in selected
    assert "pitcher_id" not in selected
    assert "batter_id" not in selected


def test_query_digest_is_deterministic(session):
    add_event(
        session,
        at_bat_number=2,
        events="field_out",
    )
    add_event(
        session,
        at_bat_number=1,
        events="single",
    )
    summary = authority_summary(
        authority_record("single", "single"),
        authority_record("out", "out"),
    )

    first = execute(session, summary)
    second = execute(session, summary)

    assert first.query_digest == second.query_digest
    assert first.to_diagnostics() == second.to_diagnostics()


def test_invalid_window_returns_error_without_query(session):
    statements = []

    @event.listens_for(
        session.get_bind(),
        "before_cursor_execute",
    )
    def capture(
        connection,
        cursor,
        statement,
        parameters,
        context,
        executemany,
    ):
        statements.append(statement)

    result = (
        execute_canonical_defensive_database_evidence(
            session,
            summary=authority_summary(),
            window_start="2026-08-31",
            window_end="2026-08-01",
            through_date="2026-09-01",
        )
    )

    event.remove(
        session.get_bind(),
        "before_cursor_execute",
        capture,
    )

    assert result.status == "error"
    assert result.query_row_count == 0
    assert "must not precede" in result.error
    assert statements == []


def test_diagnostics_disclose_database_boundary(session):
    add_event(
        session,
        at_bat_number=1,
        events="field_out",
    )

    result = execute(
        session,
        authority_summary(
            authority_record("out", "out"),
        ),
    )
    diagnostics = result.to_diagnostics()

    assert diagnostics["schema_version"] == (
        CANONICAL_DEFENSIVE_DATABASE_EVIDENCE_VERSION
    )
    assert diagnostics["measurement_only"] is True
    assert diagnostics["database_accessed"] is True
    assert diagnostics["database_query_performed"] is True
    assert diagnostics["database_query_mode"] == "read_only"
    assert diagnostics["queried_columns"] == [
        "game_date",
        "game_pk",
        "at_bat_number",
        "events",
    ]
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


def test_rejects_invalid_ready_contract():
    with pytest.raises(
        ValueError,
        match="requires query rows",
    ):
        CanonicalDefensiveDatabaseEvidence(
            status="ready",
            window_start="2026-08-01",
            window_end="2026-08-31",
            through_date="2026-09-01",
            query_row_count=0,
            query_digest="a" * 64,
        )
