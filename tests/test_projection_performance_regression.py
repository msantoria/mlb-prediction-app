from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from dataclasses import replace
from threading import Event
from types import SimpleNamespace

import pytest

from mlb_app import model_projection_routes as routes
from mlb_app.model_projection_transport import compact_projection_payload
from mlb_app.shared_payload_cache import clear_shared_payload_cache
from test_canonical_probability_artifact_adapter import artifact, record
from test_canonical_probability_diagnostics_shadow_serialization import diagnostics_snapshot
from test_canonical_probability_fallback_policy import catalog
from mlb_app.simulation.shadow.probability_serialization import probability_resolution_diagnostics_to_dict


def test_transport_bounds_only_debug_rows_and_preserves_complete_results():
    payload = {
        "games": [{"canonical_outcomes": {"simulation_count": 1000},
                   "players": list(range(300)),
                   "diagnostics": {
                       "schema_version": "canonical_probability_diagnostics_shadow_v1",
                       "summary": {"total_resolutions": 5000},
                       "tier_usage": [{"tier": "exact_matchup", "count": 5000}],
                       "observations": [{"sequence": n} for n in range(5000)],
                   },
                   "audit": {
                       "schema_version": "canonical_pitcher_appearance_sequence_audit_v1",
                       "appearance_count": 2000, "anomaly_counts": {"example": 10},
                       "records": list(range(2000)), "trials": list(range(1000)),
                   }}],
        "report": {"schema_version": "other", "records": list(range(2000))},
    }
    original = deepcopy(payload)
    result = compact_projection_payload(payload)
    assert payload == original
    game = result["games"][0]
    assert game["players"] == payload["games"][0]["players"]
    assert game["canonical_outcomes"] == {"simulation_count": 1000}
    assert len(game["diagnostics"]["observations"]) == 100
    assert game["diagnostics"]["summary"] == {"total_resolutions": 5000}
    assert game["audit"]["anomaly_counts"] == {"example": 10}
    assert len(game["audit"]["records"]) == len(game["audit"]["trials"]) == 100
    assert result["report"] == payload["report"]
    assert compact_projection_payload(result) == result


def test_source_serializer_preserves_summary_when_observations_omitted():
    diagnostics = diagnostics_snapshot()
    full = probability_resolution_diagnostics_to_dict(diagnostics)
    bounded = probability_resolution_diagnostics_to_dict(diagnostics, observation_limit=0)
    assert bounded["observations"] == []
    assert bounded["summary"] == full["summary"]
    assert bounded["tier_usage"] == full["tier_usage"]
    assert bounded["observation_transport"]["total_count"] == len(full["observations"])
    assert compact_projection_payload(bounded)["diagnostic_row_transport"]["observations"]["total_count"] == len(full["observations"])


@pytest.mark.parametrize("value", [artifact(records=(record(),)), catalog()])
def test_immutable_digest_hashes_once_and_replacement_recomputes(value, monkeypatch):
    import hashlib
    original = hashlib.sha256
    calls = []
    def count(*args, **kwargs):
        calls.append(1)
        return original(*args, **kwargs)
    monkeypatch.setattr(hashlib, "sha256", count)
    expected = type(value).digest.func(value)
    calls.clear()
    assert [value.digest for _ in range(100)] == [expected] * 100
    assert len(calls) == 1
    replacement = replace(value, provider=replace(value.provider, artifact_id="changed"))
    assert replacement.digest != value.digest
    assert len(calls) == 2


def test_durable_projection_is_promoted_to_memory_without_rebuilding(monkeypatch):
    clear_shared_payload_cache()
    reads = []
    class Session:
        def __enter__(self):
            reads.append(1)
            return self
        def __exit__(self, *_): pass
        def query(self, *_): return self
        def filter(self, *_): return self
        def first(self):
            return SimpleNamespace(payload_json={"date": "2026-09-11", "games": []}, updated_at=None)
    monkeypatch.setattr(routes, "_session_factory", lambda: Session)
    monkeypatch.setattr(routes, "_build_uncached_projection_payload", lambda *_: pytest.fail("request rebuilt projections"))
    first = routes.get_model_projection_payload("2026-09-11")
    first["games"].append({"mutation": True})
    second = routes.get_model_projection_payload("2026-09-11")
    assert second["games"] == []
    assert second["data_status"] == "ready"
    assert len(reads) == 1
    clear_shared_payload_cache()


def test_assistant_and_dashboard_projection_loader_only_reads_artifact(monkeypatch):
    from mlb_app import ai_data_assistant_performance as assistant
    from mlb_app import my_dashboard_solver as solver
    calls = []
    payload = {"games": [], "data_status": "not_ready", "date": "2026-09-11"}
    monkeypatch.setattr(routes, "get_model_projection_payload", lambda date: calls.append(date) or payload)
    monkeypatch.setattr(assistant, "_original_projection_builder", lambda *_: pytest.fail("request rebuilt projections"))
    assert assistant.cached_build_model_projection_payload(None, "2026-09-11") == payload
    assert solver.projection_payload(None, "2026-09-11") == payload
    assert calls == ["2026-09-11", "2026-09-11"]


def test_overlapping_snapshot_rejected_and_lock_released_after_failure(monkeypatch):
    entered, release = Event(), Event()
    def build(_):
        entered.set()
        assert release.wait(5)
        raise ValueError("failed build")
    monkeypatch.setattr(routes, "_warm_model_projection_payload", build)
    with ThreadPoolExecutor(max_workers=1) as pool:
        future = pool.submit(routes.warm_model_projection_payload, "2026-09-11")
        try:
            assert entered.wait(5)
            with pytest.raises(routes.HTTPException) as error:
                routes.snapshot_model_projections("2026-09-11")
            assert error.value.status_code == 409
        finally:
            release.set()
        with pytest.raises(ValueError): future.result()
    monkeypatch.setattr(routes, "_warm_model_projection_payload", lambda date: {"warmed": True})
    assert routes.warm_model_projection_payload("2026-09-11")["warmed"] is True
