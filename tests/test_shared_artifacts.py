from __future__ import annotations

from mlb_app.model_projection_routes import _apply_projection_probability_contract, _attach_projection_artifact_metadata, _projection_cache_key
from mlb_app.schedule_calendar import build_schedule_calendar_snapshot, get_or_build_schedule_calendar_snapshot
from mlb_app.shared_artifacts import (
    MODEL_PROJECTION_WORKSPACE_VERSION,
    ARTIFACT_SCHEMA_VERSION,
    artifact_key,
    attach_artifact_metadata,
    artifact_metadata,
    matchups_date_key,
    model_projection_date_key,
    model_projection_probability_key,
    payload_input_hash,
    schedule_calendar_key,
    simulation_key,
)
from mlb_app.shared_payload_cache import clear_shared_payload_cache


def _schedule(_date: str):
    return [
        {
            "_game_pk": 123,
            "_game_date": "2026-07-09T19:05:00Z",
            "_venue": "Test Park",
            "_status": "Preview",
            "home": {"team": {"id": 1, "name": "Home Club"}},
            "away": {"team": {"id": 2, "name": "Away Club"}},
        }
    ]


def test_artifact_keys_are_separated_by_type_and_model_contract() -> None:
    date = "2026-07-09"

    keys = {
        schedule_calendar_key(date),
        matchups_date_key(date),
        model_projection_date_key(date),
        model_projection_probability_key(date=date, game_pk=123, model_version="v1", input_hash="abc"),
        simulation_key(date=date, game_pk=123, simulation_count=3000, input_hash="abc"),
    }

    assert len(keys) == 5
    assert schedule_calendar_key(date).startswith(f"artifact:{ARTIFACT_SCHEMA_VERSION}:schedule_calendar")
    assert model_projection_date_key(date).startswith(f"artifact:{ARTIFACT_SCHEMA_VERSION}:model_projection_date")
    assert (
        MODEL_PROJECTION_WORKSPACE_VERSION
        in model_projection_date_key(date)
    )
    assert (
        "probability_contract_v1"
        not in model_projection_date_key(date)
    )


def test_unknown_artifact_type_raises() -> None:
    try:
        artifact_key("not_real", "2026-07-09")
    except ValueError as exc:
        assert "Unknown artifact type" in str(exc)
    else:
        raise AssertionError("Expected unknown artifact type to raise")


def test_attach_artifact_metadata_preserves_payload_and_adds_artifact_block() -> None:
    payload = {"date": "2026-07-09", "games": []}
    metadata = artifact_metadata(
        artifact_type="model_projection_date",
        cache_key=model_projection_date_key("2026-07-09"),
        source_route="/models/projections",
        source_builder="test_builder",
        model_version="model_projection_probability_v1",
        probability_source="model_projections",
    )

    updated = attach_artifact_metadata(payload, metadata)

    assert updated["date"] == "2026-07-09"
    assert updated["artifact"]["artifact_type"] == "model_projection_date"
    assert updated["artifact"]["cache_key"] == model_projection_date_key("2026-07-09")
    assert updated["artifact"]["source_route"] == "/models/projections"
    assert updated["artifact"]["probability_source"] == "model_projections"


def test_schedule_calendar_snapshot_uses_shared_artifact_metadata() -> None:
    payload = build_schedule_calendar_snapshot("2026-07-09", fetcher=_schedule)

    assert payload["cache_key"] == schedule_calendar_key("2026-07-09")
    assert payload["artifact"]["artifact_schema_version"] == ARTIFACT_SCHEMA_VERSION
    assert payload["artifact"]["artifact_type"] == "schedule_calendar"
    assert payload["artifact"]["source_route"] == "/matchups/calendar/schedule"
    assert payload["heavy_matchup_generation"] is False


def test_schedule_calendar_artifact_cache_reuse_has_metadata() -> None:
    clear_shared_payload_cache("artifact")

    first = get_or_build_schedule_calendar_snapshot("2026-07-09", fetcher=_schedule, ttl_seconds=300)
    second = get_or_build_schedule_calendar_snapshot("2026-07-09", fetcher=_schedule, ttl_seconds=300)

    assert first["artifact"]["cache_key"] == schedule_calendar_key("2026-07-09")
    assert second["cache_hit"] is True
    assert second["artifact"]["artifact_type"] == "schedule_calendar"


def test_projection_payload_receives_date_artifact_metadata() -> None:
    payload = {"date": "2026-07-09", "games": []}

    updated = _attach_projection_artifact_metadata(payload, "2026-07-09")

    assert updated["cache_key"] == _projection_cache_key("2026-07-09")
    assert updated["artifact"]["artifact_type"] == "model_projection_date"
    assert updated["artifact"]["source_route"] == "/models/projections"
    assert updated["artifact"]["probability_source"] == "model_projections"


def test_projection_probability_artifact_metadata_is_attached_to_game_probability() -> None:
    payload = {
        "date": "2026-07-09",
        "games": [
            {
                "game_pk": 123,
                "game_date": "2026-07-09",
                "home_win_prob": 0.51,
                "away_win_prob": 0.49,
                "sharedSimulation": {
                    "derived_outputs": {
                        "bullpen_adjusted_game_simulation": {
                            "home_win_probability": 0.64,
                            "away_win_probability": 0.36,
                            "model_version": "bullpen_adjusted_v1",
                        }
                    }
                },
            }
        ],
    }

    updated = _apply_projection_probability_contract(payload, "2026-07-09")
    probability = updated["games"][0]["model_projection_probability"]
    expected_hash = payload_input_hash({
        "game_pk": 123,
        "date": "2026-07-09",
        "source_path": "sharedSimulation.derived_outputs.bullpen_adjusted_game_simulation",
        "home_win_probability": 0.64,
        "away_win_probability": 0.36,
    })
    expected_key = model_projection_probability_key(
        date="2026-07-09",
        game_pk=123,
        model_version="bullpen_adjusted_v1",
        input_hash=expected_hash,
    )

    assert probability["artifact"]["artifact_type"] == "model_projection_probability"
    assert probability["artifact"]["cache_key"] == expected_key
    assert probability["artifact"]["input_hash"] == expected_hash
    assert updated["games"][0]["probability_cache_key"] == expected_key


def test_projection_workspace_version_changes_cache_namespace() -> None:
    date = "2026-07-09"

    key = model_projection_date_key(date)

    assert key.endswith(
        f"{MODEL_PROJECTION_WORKSPACE_VERSION}:{date}"
    )


def test_model_projection_workspace_v6_invalidates_prior_environment_payload_cache():
    date = "2026-08-16"

    key = model_projection_date_key(date)

    assert MODEL_PROJECTION_WORKSPACE_VERSION == (
        "model_projection_workspace_v6"
    )
    assert key.endswith(
        "model_projection_workspace_v6:"
        + date
    )
    assert (
        "model_projection_workspace_v3"
        not in key
    )
