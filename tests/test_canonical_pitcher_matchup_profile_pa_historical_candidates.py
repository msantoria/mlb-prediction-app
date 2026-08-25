from __future__ import annotations

from copy import deepcopy

import pytest

import mlb_app.simulation.shadow.canonical_pitcher_matchup_profile_pa_historical_candidates as candidate_module
from mlb_app.simulation.shadow.canonical_pitcher_matchup_profile_pa_historical_candidates import (
    materialize_canonical_pitcher_matchup_profile_pa_historical_candidates,
)


def request(**overrides):
    values = {
        "game_pk": 700001,
        "pitcher_id": 101,
        "game_date": "2025-07-01",
    }
    values.update(overrides)
    return values


def candidate(
    pitcher_id,
    game_date,
    *,
    status="ready",
    authority=False,
    authority_changed=False,
):
    return {
        "profile_rates": {
            "k_rate": 0.30,
        },
        "diagnostics": {
            "status": status,
            "pitcher_id": pitcher_id,
            "game_date": str(game_date),
            "cutoff_rule": (
                "events_strictly_before_game_date"
            ),
            "evidence_status": "ready",
            "league_prior_status": "ready",
            "application_status": status,
            "runtime_candidate_digest": (
                f"digest:{pitcher_id}:{game_date}"
            ),
            "production_authority": (
                authority
            ),
            "production_authority_changed": (
                authority_changed
            ),
        },
    }


@pytest.fixture
def builder(monkeypatch):
    calls = []

    def fake(
        events,
        *,
        pitcher_id,
        game_date,
        window_days,
    ):
        calls.append({
            "events_id": id(events),
            "event_count": len(events),
            "pitcher_id": pitcher_id,
            "game_date": game_date,
            "window_days": window_days,
        })
        return candidate(
            pitcher_id,
            game_date,
        )

    monkeypatch.setattr(
        candidate_module,
        "build_canonical_pitcher_matchup_profile_runtime_candidate",
        fake,
    )

    return calls


def materialize(
    requests=None,
    events=None,
    **overrides,
):
    values = {
        "requests": (
            [request()]
            if requests is None
            else requests
        ),
        "window_days": 90,
    }
    values.update(overrides)

    return (
        materialize_canonical_pitcher_matchup_profile_pa_historical_candidates(
            (
                [{"event_id": 1}]
                if events is None
                else events
            ),
            **values,
        )
    )


def test_builds_candidate_by_game_pitcher(
    builder,
):
    result = materialize()

    assert result["diagnostics"]["status"] == "ready"
    assert result["diagnostics"][
        "candidate_count"
    ] == 1
    assert result["diagnostics"][
        "ready_candidate_count"
    ] == 1
    assert set(result["candidates"]) == {
        (700001, 101)
    }
    assert result["candidates"][
        (700001, 101)
    ]["diagnostics"]["status"] == "ready"

    assert builder[0]["pitcher_id"] == 101
    assert builder[0]["window_days"] == 90
    assert builder[0]["game_date"].isoformat() == (
        "2025-07-01"
    )


def test_reuses_one_shared_event_collection(
    builder,
):
    result = materialize(
        requests=[
            request(),
            request(
                game_pk=700002,
                pitcher_id=102,
                game_date="2025-07-02",
            ),
        ],
        events=[
            {"event_id": 1},
            {"event_id": 2},
        ],
    )

    assert result["diagnostics"][
        "candidate_count"
    ] == 2
    assert len(builder) == 2
    assert len({
        call["events_id"]
        for call in builder
    }) == 1
    assert {
        call["event_count"]
        for call in builder
    } == {2}
    assert result["diagnostics"][
        "single_shared_event_collection"
    ] is True
    assert result["diagnostics"][
        "event_collection_reused"
    ] is True


def test_deduplicates_identical_requests(
    builder,
):
    result = materialize(
        requests=[
            request(),
            request(),
        ]
    )

    assert len(builder) == 1
    assert result["diagnostics"][
        "duplicate_request_count"
    ] == 1
    assert result["diagnostics"][
        "candidate_count"
    ] == 1


def test_conflicting_dates_fail_closed(
    builder,
):
    result = materialize(
        requests=[
            request(
                game_date="2025-07-01"
            ),
            request(
                game_date="2025-07-02"
            ),
            request(
                game_date="2025-07-01"
            ),
        ]
    )

    assert builder == []
    assert result["candidates"] == {}
    assert result["diagnostics"][
        "status"
    ] == "unavailable"
    assert result["diagnostics"][
        "rejected_requests"
    ][0]["reason"] == (
        "conflicting_game_pitcher_request"
    )


@pytest.mark.parametrize(
    "field,value,reason",
    [
        (
            "game_pk",
            0,
            "game_pk_must_be_positive_integer",
        ),
        (
            "pitcher_id",
            False,
            "pitcher_id_must_be_positive_integer",
        ),
        (
            "game_date",
            "bad-date",
            "game_date_must_be_iso_date",
        ),
    ],
)
def test_rejects_invalid_requests(
    builder,
    field,
    value,
    reason,
):
    result = materialize(
        requests=[
            request(**{field: value}),
        ]
    )

    assert builder == []
    assert result["candidates"] == {}
    assert result["diagnostics"][
        "rejected_requests"
    ][0]["reason"] == reason


def test_valid_requests_survive_invalid_requests(
    builder,
):
    result = materialize(
        requests=[
            request(),
            request(
                game_pk=None,
                pitcher_id=102,
            ),
        ]
    )

    assert len(builder) == 1
    assert result["diagnostics"][
        "status"
    ] == "partial"
    assert result["diagnostics"][
        "candidate_count"
    ] == 1
    assert result["diagnostics"][
        "rejected_request_count"
    ] == 1


def test_partial_candidate_reports_partial(
    monkeypatch,
):
    def fake(
        events,
        *,
        pitcher_id,
        game_date,
        window_days,
    ):
        return candidate(
            pitcher_id,
            game_date,
            status="partial",
        )

    monkeypatch.setattr(
        candidate_module,
        "build_canonical_pitcher_matchup_profile_runtime_candidate",
        fake,
    )

    result = materialize()

    assert result["diagnostics"][
        "status"
    ] == "partial"
    assert result["diagnostics"][
        "partial_candidate_count"
    ] == 1
    assert result["diagnostics"][
        "ready_candidate_count"
    ] == 0


def test_invalid_authority_fails_closed(
    monkeypatch,
):
    def fake(
        events,
        *,
        pitcher_id,
        game_date,
        window_days,
    ):
        return candidate(
            pitcher_id,
            game_date,
            authority=True,
        )

    monkeypatch.setattr(
        candidate_module,
        "build_canonical_pitcher_matchup_profile_runtime_candidate",
        fake,
    )

    result = materialize()

    assert result["candidates"] == {}
    assert result["diagnostics"][
        "rejected_requests"
    ][0]["reason"] == (
        "candidate_authority_contract_invalid"
    )


def test_builder_failure_is_reported(
    monkeypatch,
):
    def fail(*args, **kwargs):
        raise ValueError(
            "synthetic failure"
        )

    monkeypatch.setattr(
        candidate_module,
        "build_canonical_pitcher_matchup_profile_runtime_candidate",
        fail,
    )

    result = materialize()

    assert result["candidates"] == {}
    assert result["diagnostics"][
        "rejected_requests"
    ][0]["reason"] == (
        "candidate_materialization_failed:"
        "synthetic failure"
    )


def test_materialization_is_deterministic(
    builder,
):
    requests = [
        request(
            game_pk=700001,
            pitcher_id=101,
            game_date="2025-07-01",
        ),
        request(
            game_pk=700002,
            pitcher_id=102,
            game_date="2025-07-02",
        ),
    ]

    first = materialize(
        requests=requests
    )
    second = materialize(
        requests=list(
            reversed(requests)
        )
    )

    assert first["candidates"] == (
        second["candidates"]
    )
    assert first["diagnostics"][
        "candidate_records"
    ] == second["diagnostics"][
        "candidate_records"
    ]
    assert first["diagnostics"][
        "candidate_window_digest"
    ] == second["diagnostics"][
        "candidate_window_digest"
    ]


def test_inputs_are_not_mutated(
    builder,
):
    event_rows = [
        {"event_id": 1},
    ]
    request_rows = [
        request(),
    ]
    original_events = deepcopy(
        event_rows
    )
    original_requests = deepcopy(
        request_rows
    )

    materialize(
        events=event_rows,
        requests=request_rows,
    )

    assert event_rows == original_events
    assert request_rows == original_requests


@pytest.mark.parametrize(
    "window_days",
    [
        0,
        -1,
        True,
        1.5,
    ],
)
def test_window_days_must_be_positive_integer(
    window_days,
):
    with pytest.raises(ValueError):
        materialize(
            window_days=window_days
        )


def test_authority_and_cutoff_contracts(
    builder,
):
    diagnostics = materialize()[
        "diagnostics"
    ]

    assert diagnostics["cutoff_rule"] == (
        "events_strictly_before_each_game_date"
    )
    assert diagnostics[
        "candidate_identity"
    ] == "game_pk_pitcher_id"
    assert diagnostics[
        "calibrated_pooled_metrics_only"
    ] is True
    assert diagnostics[
        "segment_parameters_applied"
    ] is False
    assert diagnostics["shadow_only"] is True
    assert diagnostics[
        "production_authority"
    ] is False
    assert diagnostics[
        "production_authority_changed"
    ] is False
