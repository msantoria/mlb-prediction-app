from dataclasses import replace
from types import SimpleNamespace

import pytest

from mlb_app.simulation.events import (
    Base,
    GameState,
    RunnerAdvancementResult,
    RunnerMovement,
    build_play_event,
)
from mlb_app.simulation.game.defensive_event_rematerialization import (
    CANONICAL_DEFENSIVE_EVENT_REMATERIALIZATION_VERSION,
    rematerialize_canonical_defensive_event,
)
from mlb_app.simulation.game.defensive_outcome_reconciliation import (
    CanonicalReconciledBattedBallOutcome,
)


def original_single(state=GameState()):
    event = build_play_event(
        sequence=0,
        event_type="single",
        batter_id="batter",
        state_before=state,
        runner_movements=(
            RunnerMovement(
                runner_id="batter",
                start_base=Base.HOME,
                end_base=Base.FIRST,
            ),
        ),
    )
    return replace(event, pitcher_id="pitcher")


def reconciliation(
    outcome,
    *,
    ready=True,
    requires=True,
    error_fielder_id=None,
):
    return SimpleNamespace(
        ready=ready,
        requires_event_rematerialization=requires,
        reconciled_outcome=outcome,
        error_fielder_id=error_fielder_id,
    )


def test_blocked_reconciliation_preserves_original_event():
    event = original_single()
    advancement = RunnerAdvancementResult(
        movements=event.runner_movements,
    )

    result = rematerialize_canonical_defensive_event(
        original_event=event,
        original_advancement=advancement,
        reconciliation=reconciliation(
            None,
            ready=False,
        ),
        context=object(),
        advancement_seed=123,
    )

    assert result.event is event
    assert result.advancement is advancement
    assert result.applied is False
    assert result.authoritative is False
    assert result.blocker == "defensive_reconciliation_blocked"


def test_unchanged_reconciliation_preserves_original_event():
    event = original_single()
    advancement = RunnerAdvancementResult(
        movements=event.runner_movements,
    )

    result = rematerialize_canonical_defensive_event(
        original_event=event,
        original_advancement=advancement,
        reconciliation=reconciliation(
            CanonicalReconciledBattedBallOutcome.SINGLE,
            requires=False,
        ),
        context=object(),
        advancement_seed=123,
    )

    assert result.event is event
    assert result.applied is False
    assert result.blocker == "defensive_outcome_unchanged"


def test_converted_out_rebuilds_state_and_out_record():
    state = GameState(
        outs=1,
        bases=("runner_1", None, None),
    )
    event = original_single(state)
    advancement = RunnerAdvancementResult(
        movements=event.runner_movements,
    )

    result = rematerialize_canonical_defensive_event(
        original_event=event,
        original_advancement=advancement,
        reconciliation=reconciliation(
            CanonicalReconciledBattedBallOutcome.OUT,
        ),
        context=object(),
        advancement_seed=123,
    )

    assert result.applied is True
    assert result.authoritative is True
    assert result.event.event_type == "out"
    assert result.event.state_after.outs == 2
    assert result.event.state_after.first == "runner_1"
    assert result.event.outs_recorded[0].runner_id == "batter"
    assert (
        result.event.outs_recorded[0].reason
        == "defensive_converted_out"
    )
    assert result.event.pitcher_id == "pitcher"


def test_fielding_error_uses_resolved_fielder_identity():
    event = original_single()
    advancement = RunnerAdvancementResult(
        movements=event.runner_movements,
    )

    result = rematerialize_canonical_defensive_event(
        original_event=event,
        original_advancement=advancement,
        reconciliation=reconciliation(
            CanonicalReconciledBattedBallOutcome.REACHED_ON_ERROR,
            error_fielder_id="shortstop",
        ),
        context=object(),
        advancement_seed=123,
    )

    assert result.event.event_type == "reached_on_error"
    assert result.event.state_after.first == "batter"
    assert (
        result.event.attribution.error_fielder_id
        == "shortstop"
    )
    assert result.event.attribution.error_type.value == "fielding"
    assert result.event.attribution.rbi_count == 0
    assert result.event.pitcher_id == "pitcher"


def test_ready_error_without_fielder_fails_closed():
    event = original_single()
    advancement = RunnerAdvancementResult(
        movements=event.runner_movements,
    )

    with pytest.raises(
        ValueError,
        match="requires fielder identity",
    ):
        rematerialize_canonical_defensive_event(
            original_event=event,
            original_advancement=advancement,
            reconciliation=reconciliation(
                CanonicalReconciledBattedBallOutcome
                .REACHED_ON_ERROR,
            ),
            context=object(),
            advancement_seed=123,
        )


def test_hit_rematerialization_uses_reconciled_hit_type(
    monkeypatch,
):
    event = original_single()
    original_advancement = RunnerAdvancementResult(
        movements=event.runner_movements,
    )
    sampled_advancement = RunnerAdvancementResult(
        movements=(
            RunnerMovement(
                runner_id="batter",
                start_base=Base.HOME,
                end_base=Base.SECOND,
            ),
        ),
    )
    captured = {}

    class StubSampler:
        def __init__(self, *, rng):
            captured["rng"] = rng

        def sample(self, **kwargs):
            captured.update(kwargs)
            return sampled_advancement

    monkeypatch.setattr(
        "mlb_app.simulation.game."
        "defensive_event_rematerialization."
        "BaselineRunnerAdvancementSampler",
        StubSampler,
    )

    result = rematerialize_canonical_defensive_event(
        original_event=event,
        original_advancement=original_advancement,
        reconciliation=reconciliation(
            CanonicalReconciledBattedBallOutcome.DOUBLE,
        ),
        context=object(),
        advancement_seed=456,
    )

    assert result.event.event_type == "double"
    assert result.event.state_after.second == "batter"
    assert captured["primary_outcome"] == "double"
    assert captured["state"] == event.state_before
    assert captured["batter_id"] == "batter"
    assert result.advancement is sampled_advancement


def test_diagnostics_expose_event_authority():
    event = original_single()
    advancement = RunnerAdvancementResult(
        movements=event.runner_movements,
    )

    result = rematerialize_canonical_defensive_event(
        original_event=event,
        original_advancement=advancement,
        reconciliation=reconciliation(
            CanonicalReconciledBattedBallOutcome.OUT,
        ),
        context=object(),
        advancement_seed=123,
    )

    diagnostics = result.to_diagnostics()

    assert diagnostics["schema_version"] == (
        CANONICAL_DEFENSIVE_EVENT_REMATERIALIZATION_VERSION
    )
    assert diagnostics["status"] == "applied"
    assert diagnostics["authoritative"] is True
    assert diagnostics["original_event_type"] == "single"
    assert diagnostics["final_event_type"] == "out"
