import pytest

from mlb_app.simulation.game import (
    CanonicalDefensiveEventAuthorityRecord,
    aggregate_canonical_defensive_event_authority,
)
from mlb_app.simulation.shadow import (
    CANONICAL_DEFENSIVE_DISTRIBUTION_EVIDENCE_VERSION,
    CanonicalDefensiveDistributionEvidence,
    execute_canonical_defensive_distribution_evidence,
)


def row(
    *,
    at_bat_number,
    events,
    game_date="2026-08-15",
    game_pk=1001,
):
    return {
        "game_date": game_date,
        "game_pk": game_pk,
        "at_bat_number": at_bat_number,
        "events": events,
    }


def record(original, final):
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


def summary(*records):
    return aggregate_canonical_defensive_event_authority(
        records
    )


def execute(rows, authority_summary):
    return execute_canonical_defensive_distribution_evidence(
        rows,
        summary=authority_summary,
        window_start="2026-08-01",
        window_end="2026-08-31",
        through_date="2026-09-01",
    )


def test_executes_ready_defensive_distribution_evidence():
    result = execute(
        [
            row(at_bat_number=1, events="single"),
            row(at_bat_number=2, events="field_out"),
        ],
        summary(
            record("single", "single"),
            record("out", "out"),
        ),
    )

    assert result.status == "ready"
    assert result.ready is True
    assert result.source is not None
    assert result.backtest is not None
    assert result.backtest.total_variation_distance == 0.0
    assert result.blocker is None
    assert result.error is None
    assert len(result.artifact_digest) == 64


def test_empty_simulation_is_unavailable_not_error():
    result = execute(
        [
            row(at_bat_number=1, events="field_out"),
        ],
        summary(),
    )

    assert result.status == "unavailable"
    assert result.ready is False
    assert result.source is not None
    assert result.backtest is not None
    assert result.blocker == "simulation_distribution_empty"
    assert result.error is None
    assert len(result.artifact_digest) == 64


def test_invalid_source_window_is_error_without_partial_results():
    result = execute_canonical_defensive_distribution_evidence(
        [
            row(at_bat_number=1, events="single"),
        ],
        summary=summary(record("single", "single")),
        window_start="2026-08-31",
        window_end="2026-08-01",
        through_date="2026-09-01",
    )

    assert result.status == "error"
    assert result.ready is False
    assert result.source is None
    assert result.backtest is None
    assert result.artifact_digest == ""
    assert result.blocker is None
    assert "ValueError" in result.error
    assert "must not precede" in result.error


def test_evidence_digest_is_input_order_independent():
    rows = [
        row(at_bat_number=1, events="single"),
        row(at_bat_number=2, events="field_out"),
    ]
    authority_summary = summary(
        record("single", "single"),
        record("out", "out"),
    )

    first = execute(rows, authority_summary)
    second = execute(
        list(reversed(rows)),
        authority_summary,
    )

    assert first.artifact_digest == second.artifact_digest
    assert first.to_diagnostics() == second.to_diagnostics()


def test_diagnostics_are_measurement_only():
    result = execute(
        [
            row(at_bat_number=1, events="field_out"),
        ],
        summary(record("out", "out")),
    )

    diagnostics = result.to_diagnostics()

    assert diagnostics["schema_version"] == (
        CANONICAL_DEFENSIVE_DISTRIBUTION_EVIDENCE_VERSION
    )
    assert diagnostics["measurement_only"] is True
    assert diagnostics["database_accessed"] is False
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


def test_rejects_invalid_ready_artifact_contract():
    with pytest.raises(
        ValueError,
        match="requires source and backtest",
    ):
        CanonicalDefensiveDistributionEvidence(
            status="ready",
            window_start="2026-08-01",
            window_end="2026-08-31",
            through_date="2026-09-01",
        )
