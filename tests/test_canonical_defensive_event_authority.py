import pytest

from mlb_app.simulation.game import (
    CANONICAL_DEFENSIVE_EVENT_AUTHORITY_VERSION,
    CanonicalDefensiveEventAuthorityRecord,
    CanonicalDefensiveEventAuthoritySummary,
    aggregate_canonical_defensive_event_authority,
)


def record(
    *,
    applied,
    original,
    final,
    blocker=None,
):
    return CanonicalDefensiveEventAuthorityRecord(
        applied=applied,
        authoritative=applied,
        original_event_type=original,
        final_event_type=final,
        blocker=blocker,
    )


def test_empty_summary_is_explicit():
    summary = (
        aggregate_canonical_defensive_event_authority(
            ()
        )
    )

    assert summary.observation_count == 0
    assert summary.applied_count == 0
    assert summary.preserved_count == 0
    assert summary.authority_rate == 0.0
    assert summary.original_event_type_counts == ()
    assert (
        summary.applied_original_event_type_counts
        == ()
    )
    assert (
        summary.preserved_original_event_type_counts
        == ()
    )
    assert (
        summary.authority_rate_by_original_event_type
        == ()
    )
    assert summary.event_transition_counts == ()
    assert summary.final_event_type_counts == ()
    assert summary.blocker_counts == ()


def test_aggregates_exact_observed_authority():
    summary = (
        aggregate_canonical_defensive_event_authority(
            (
                record(
                    applied=True,
                    original="single",
                    final="out",
                ),
                record(
                    applied=True,
                    original="out",
                    final="double",
                ),
                record(
                    applied=False,
                    original="single",
                    final="single",
                    blocker="defensive_outcome_unchanged",
                ),
                record(
                    applied=False,
                    original="double",
                    final="double",
                    blocker="defensive_reconciliation_blocked",
                ),
            )
        )
    )

    assert summary.observation_count == 4
    assert summary.applied_count == 2
    assert summary.preserved_count == 2
    assert summary.authority_rate == 0.5
    assert dict(
        summary.original_event_type_counts
    ) == {
        "double": 1,
        "out": 1,
        "single": 2,
    }
    assert dict(
        summary.applied_original_event_type_counts
    ) == {
        "out": 1,
        "single": 1,
    }
    assert dict(
        summary.preserved_original_event_type_counts
    ) == {
        "double": 1,
        "single": 1,
    }
    assert dict(
        summary.authority_rate_by_original_event_type
    ) == {
        "double": 0.0,
        "out": 1.0,
        "single": 0.5,
    }
    assert summary.event_transition_counts == (
        ("double", "double", 1),
        ("out", "double", 1),
        ("single", "out", 1),
        ("single", "single", 1),
    )
    assert dict(summary.final_event_type_counts) == {
        "double": 2,
        "out": 1,
        "single": 1,
    }
    assert dict(summary.blocker_counts) == {
        "defensive_outcome_unchanged": 1,
        "defensive_reconciliation_blocked": 1,
    }


def test_diagnostics_are_json_ready():
    summary = (
        aggregate_canonical_defensive_event_authority(
            (
                record(
                    applied=True,
                    original="out",
                    final="reached_on_error",
                ),
            )
        )
    )

    diagnostics = summary.to_diagnostics()

    assert diagnostics["schema_version"] == (
        CANONICAL_DEFENSIVE_EVENT_AUTHORITY_VERSION
    )
    assert diagnostics["observation_count"] == 1
    assert diagnostics["authority_rate"] == 1.0
    assert diagnostics["original_event_type_counts"] == {
        "out": 1,
    }
    assert diagnostics[
        "applied_original_event_type_counts"
    ] == {
        "out": 1,
    }
    assert diagnostics[
        "preserved_original_event_type_counts"
    ] == {}
    assert diagnostics[
        "authority_rate_by_original_event_type"
    ] == {
        "out": 1.0,
    }
    assert diagnostics["event_transition_counts"] == {
        "out": {
            "reached_on_error": 1,
        },
    }
    assert diagnostics["final_event_type_counts"] == {
        "reached_on_error": 1,
    }


def test_record_requires_fail_closed_blocker():
    with pytest.raises(
        ValueError,
        match="requires a blocker",
    ):
        record(
            applied=False,
            original="single",
            final="single",
        )


def test_record_rejects_false_authority_for_applied_event():
    with pytest.raises(
        ValueError,
        match="must match",
    ):
        CanonicalDefensiveEventAuthorityRecord(
            applied=True,
            authoritative=False,
            original_event_type="single",
            final_event_type="out",
            blocker=None,
        )



def test_summary_rejects_nonreconciling_transition_counts():
    with pytest.raises(
        ValueError,
        match="transition counts must reconcile",
    ):
        CanonicalDefensiveEventAuthoritySummary(
            observation_count=1,
            applied_count=1,
            preserved_count=0,
            authority_rate=1.0,
            original_event_type_counts=(
                ("out", 1),
            ),
            applied_original_event_type_counts=(
                ("out", 1),
            ),
            authority_rate_by_original_event_type=(
                ("out", 1.0),
            ),
            event_transition_counts=(
                ("out", "single", 2),
            ),
            final_event_type_counts=(
                ("single", 1),
            ),
        )
