from copy import deepcopy

from mlb_app.simulation.shadow.pregame_bullpen_evidence_provider import (
    PAYLOAD_SCHEMA_VERSION,
    fetch_canonical_pregame_bullpen_evidence,
)


AS_OF = "2026-08-09T23:05:00+00:00"


class Response:
    def __init__(
        self,
        payload,
        *,
        error=None,
    ):
        self.payload = payload
        self.error = error

    def raise_for_status(self):
        if self.error is not None:
            raise self.error

    def json(self):
        return deepcopy(self.payload)


def row(
    pitcher_id="101",
    *,
    team_side="away",
    team_id="10",
    status="eligible",
    role="closer",
    observed_at="2026-08-09T22:30:00+00:00",
    reason=None,
    provider_record_id="record-1",
):
    return {
        "pitcher_id": pitcher_id,
        "team_side": team_side,
        "team_id": team_id,
        "status": status,
        "role": role,
        "observed_at": observed_at,
        "reason": reason,
        "provider_record_id":
            provider_record_id,
    }


def payload(*rows):
    return {
        "schema_version": PAYLOAD_SCHEMA_VERSION,
        "observations": list(rows),
    }


def run(
    source_payload=None,
    **overrides,
):
    calls = []

    if source_payload is None:
        source_payload = payload(
            row(),
            row(
                "201",
                team_side="home",
                team_id="20",
                status="ineligible",
                role="long_reliever",
                reason="unavailable_after_usage",
                provider_record_id="record-2",
            ),
        )

    def request_get(
        url,
        *,
        params,
        headers,
        timeout,
    ):
        calls.append({
            "url": url,
            "params": params,
            "headers": headers,
            "timeout": timeout,
        })
        return Response(source_payload)

    values = {
        "game_pk": "123",
        "game_time": AS_OF,
        "away_team_id": "10",
        "home_team_id": "20",
        "endpoint": (
            "https://provider.example/"
            "pregame-bullpen"
        ),
        "provider_name": "structured_provider",
        "api_token": "secret-token",
        "request_get": request_get,
    }
    values.update(overrides)

    return (
        fetch_canonical_pregame_bullpen_evidence(
            **values
        ),
        calls,
    )


def test_provider_not_configured_does_not_request():
    called = False

    def request_get(*args, **kwargs):
        nonlocal called
        called = True
        raise AssertionError(
            "request must not be made"
        )

    result = (
        fetch_canonical_pregame_bullpen_evidence(
            game_pk="123",
            game_time=AS_OF,
            away_team_id="10",
            home_team_id="20",
            endpoint=None,
            provider_name=None,
            request_get=request_get,
        )
    )

    assert result.status == (
        "provider_not_configured"
    )
    assert result.observations == ()
    assert called is False


def test_fetches_structured_observations():
    result, calls = run()

    assert result.status == "observed"
    assert len(result.observations) == 2
    assert len(calls) == 1

    call = calls[0]

    assert call["params"]["game_pk"] == "123"
    assert call["params"][
        "away_team_id"
    ] == "10"
    assert call["headers"][
        "Authorization"
    ] == "Bearer secret-token"
    assert call["timeout"] == 10.0


def test_normalizes_materializer_observation_contract():
    result, _ = run()

    away = result.to_observations(
        team_side="away"
    )
    home = result.to_observations(
        team_side="home"
    )

    assert away == ({
        "pitcher_id": "101",
        "status": "eligible",
        "role": "closer",
        "source": (
            "structured_provider_"
            "pregame_bullpen_v1"
        ),
        "observed_at": (
            "2026-08-09T22:30:00+00:00"
        ),
        "reason": None,
        "provider_record_id": "record-1",
        "team_side": "away",
        "team_id": "10",
    },)

    assert home[0]["status"] == "ineligible"
    assert home[0]["role"] == "long_reliever"


def test_rejects_cross_team_observation():
    result, _ = run(
        source_payload=payload(
            row(team_id="20"),
        )
    )

    assert result.status == "payload_invalid"
    assert result.observations == ()
    assert result.invalid_reason_counts == {
        "team_identity_mismatch": 1,
    }


def test_rejects_unsupported_role_without_inference():
    result, _ = run(
        source_payload=payload(
            row(role="ace"),
        )
    )

    assert result.observations == ()
    assert result.invalid_reason_counts == {
        "typical_role_invalid": 1,
    }


def test_rejects_missing_or_naive_timestamp():
    result, _ = run(
        source_payload=payload(
            row(observed_at=None),
            row(
                "102",
                observed_at=(
                    "2026-08-09T22:30:00"
                ),
                provider_record_id="record-2",
            ),
        )
    )

    assert result.invalid_record_count == 2
    assert result.invalid_reason_counts == {
        "observation_timestamp_invalid": 2,
    }


def test_schema_mismatch_fails_closed():
    result, _ = run(
        source_payload={
            "schema_version": "other",
            "observations": [],
        }
    )

    assert result.status == "schema_mismatch"
    assert result.observations == ()


def test_provider_error_is_diagnostic():
    def request_get(*args, **kwargs):
        raise TimeoutError("provider timeout")

    result = (
        fetch_canonical_pregame_bullpen_evidence(
            game_pk="123",
            game_time=AS_OF,
            away_team_id="10",
            home_team_id="20",
            endpoint="https://provider.example",
            provider_name="structured_provider",
            request_get=request_get,
        )
    )

    assert result.status == "provider_error"
    assert result.error_type == "TimeoutError"
    assert result.observations == ()


def test_invalid_request_context_does_not_request():
    called = False

    def request_get(*args, **kwargs):
        nonlocal called
        called = True
        raise AssertionError(
            "request must not be made"
        )

    result = (
        fetch_canonical_pregame_bullpen_evidence(
            game_pk=None,
            game_time=AS_OF,
            away_team_id="10",
            home_team_id="20",
            endpoint="https://provider.example",
            provider_name="structured_provider",
            request_get=request_get,
        )
    )

    assert result.status == (
        "request_context_invalid"
    )
    assert called is False


def test_diagnostics_redact_identifiers_and_payload():
    result, _ = run()
    diagnostics = result.to_diagnostics()

    assert diagnostics[
        "valid_observation_count"
    ] == 2
    assert diagnostics[
        "away_observation_count"
    ] == 1
    assert diagnostics[
        "home_observation_count"
    ] == 1
    assert diagnostics[
        "pitcher_identifiers_exposed"
    ] is False
    assert diagnostics[
        "raw_provider_payload_exposed"
    ] is False
    assert diagnostics[
        "availability_inference_used"
    ] is False
    assert diagnostics[
        "typical_role_inference_used"
    ] is False
    assert diagnostics[
        "database_writes_performed"
    ] is False
    assert diagnostics[
        "production_authority_changed"
    ] is False


def test_observations_and_diagnostics_are_defensive():
    result, _ = run()

    observations = result.to_observations(
        team_side="away"
    )
    observations[0]["status"] = "changed"

    assert result.observations[0][
        "status"
    ] == "eligible"

    diagnostics = result.to_diagnostics()
    diagnostics[
        "invalid_reason_counts"
    ]["changed"] = 1

    assert "changed" not in (
        result.invalid_reason_counts or {}
    )


def test_output_order_is_deterministic():
    result, _ = run(
        source_payload=payload(
            row(
                "202",
                team_side="home",
                team_id="20",
                role="setup",
                provider_record_id="record-3",
            ),
            row(
                "102",
                role="middle_reliever",
                provider_record_id="record-2",
            ),
            row(),
        )
    )

    assert [
        (
            observation["team_side"],
            observation["pitcher_id"],
        )
        for observation in result.observations
    ] == [
        ("away", "101"),
        ("away", "102"),
        ("home", "202"),
    ]
def test_provider_observations_close_materialized_coverage_gap():
    from mlb_app.simulation.shadow import (
        discover_canonical_shadow_bullpens,
    )
    from mlb_app.simulation.shadow.canonical_pregame_pitcher_evidence_source_coverage import (
        audit_canonical_pregame_pitcher_evidence_source_coverage,
    )

    provider_result, _ = run(
        source_payload=payload(
            row(
                "101",
                role="closer",
            ),
            row(
                "102",
                role="long_reliever",
                provider_record_id="record-2",
            ),
            row(
                "201",
                team_side="home",
                team_id="20",
                role="setup",
                provider_record_id="record-3",
            ),
            row(
                "202",
                team_side="home",
                team_id="20",
                role="middle_reliever",
                provider_record_id="record-4",
            ),
        )
    )

    def roster(
        team_id,
        season,
        team_name=None,
    ):
        starter = (
            100
            if int(team_id) == 10
            else 200
        )

        return [
            {
                "mlb_player_id": starter,
                "player_type": "pitcher",
            },
            {
                "mlb_player_id": starter + 1,
                "player_type": "pitcher",
            },
            {
                "mlb_player_id": starter + 2,
                "player_type": "pitcher",
            },
        ]

    discovery = discover_canonical_shadow_bullpens(
        away_team_id=10,
        away_team_name="Away",
        away_starter_id=100,
        home_team_id=20,
        home_team_name="Home",
        home_starter_id=200,
        season=2026,
        roster_fetcher=roster,
        pregame_evidence_as_of=AS_OF,
        away_pregame_provider_observations=(
            provider_result.to_observations(
                team_side="away"
            )
        ),
        home_pregame_provider_observations=(
            provider_result.to_observations(
                team_side="home"
            )
        ),
    )

    coverage = (
        audit_canonical_pregame_pitcher_evidence_source_coverage(
            matchup={
                "game_pk": 123,
                "game_time": AS_OF,
                "away_pitcher_status":
                    "probable",
                "away_pitcher_source": (
                    "mlb_stats_probablePitcher"
                ),
                "home_pitcher_status":
                    "probable",
                "home_pitcher_source": (
                    "mlb_stats_probablePitcher"
                ),
            },
            bullpen_discovery=discovery,
        )
    )

    assert provider_result.status == "observed"
    assert discovery.away.pregame_evidence is not None
    assert discovery.home.pregame_evidence is not None

    assert coverage["status"] == "ready"
    assert coverage["blockers"] == []
    assert coverage[
        "provider_evidence_coverage_rate"
    ] == 1.0
    assert coverage[
        "explicit_availability_coverage_rate"
    ] == 1.0
    assert coverage[
        "typical_role_coverage_rate"
    ] == 1.0
    assert coverage["decision"][
        "provider_integration_ready"
    ] is True
    assert coverage["decision"][
        "production_activation_allowed"
    ] is False
    assert coverage[
        "production_authority_changed"
    ] is False


def test_unconfigured_provider_preserves_empty_observation_contract():
    result = (
        fetch_canonical_pregame_bullpen_evidence(
            game_pk="123",
            game_time=AS_OF,
            away_team_id="10",
            home_team_id="20",
            endpoint=None,
            provider_name=None,
        )
    )

    assert result.status == (
        "provider_not_configured"
    )
    assert result.to_observations(
        team_side="away"
    ) == ()
    assert result.to_observations(
        team_side="home"
    ) == ()

    diagnostics = result.to_diagnostics()

    assert diagnostics[
        "valid_observation_count"
    ] == 0
    assert diagnostics[
        "availability_inference_used"
    ] is False
    assert diagnostics[
        "typical_role_inference_used"
    ] is False
    assert diagnostics[
        "production_authority_changed"
    ] is False


def test_public_shadow_provider_contract():
    from mlb_app.simulation.shadow import (
        CANONICAL_PREGAME_BULLPEN_PROVIDER_PAYLOAD_VERSION,
        CANONICAL_PREGAME_BULLPEN_PROVIDER_VERSION,
        CanonicalPregameBullpenEvidenceProviderResult,
        fetch_canonical_pregame_bullpen_evidence as public_fetch,
    )

    assert (
        CANONICAL_PREGAME_BULLPEN_PROVIDER_PAYLOAD_VERSION
        == PAYLOAD_SCHEMA_VERSION
    )
    assert (
        CANONICAL_PREGAME_BULLPEN_PROVIDER_VERSION
        == (
            "canonical_pregame_bullpen_"
            "evidence_provider_v1"
        )
    )
    assert public_fetch is (
        fetch_canonical_pregame_bullpen_evidence
    )
    assert (
        CanonicalPregameBullpenEvidenceProviderResult
        is not None
    )
def test_production_adapter_passes_explicit_configuration_and_context():
    from mlb_app import model_projections

    calls = []
    sentinel = object()

    def fetcher(**kwargs):
        calls.append(kwargs)
        return sentinel

    result = (
        model_projections
        ._fetch_configured_pregame_bullpen_evidence(
            matchup={
                "game_pk": 123,
                "game_time": AS_OF,
            },
            away_team_id=10,
            home_team_id=20,
            environment={
                "MLB_PREGAME_BULLPEN_EVIDENCE_URL":
                    "https://provider.example/evidence",
                "MLB_PREGAME_BULLPEN_EVIDENCE_PROVIDER":
                    "structured_provider",
                "MLB_PREGAME_BULLPEN_EVIDENCE_TOKEN":
                    "secret-token",
            },
            fetcher=fetcher,
        )
    )

    assert result is sentinel
    assert calls == [{
        "game_pk": 123,
        "game_time": AS_OF,
        "away_team_id": 10,
        "home_team_id": 20,
        "endpoint": (
            "https://provider.example/evidence"
        ),
        "provider_name": "structured_provider",
        "api_token": "secret-token",
    }]


def test_production_adapter_unconfigured_environment_is_inert():
    from mlb_app import model_projections

    calls = []

    def fetcher(**kwargs):
        calls.append(kwargs)

        return (
            fetch_canonical_pregame_bullpen_evidence(
                request_get=(
                    lambda *args, **kwargs:
                    (_ for _ in ()).throw(
                        AssertionError(
                            "network request must not occur"
                        )
                    )
                ),
                **kwargs,
            )
        )

    result = (
        model_projections
        ._fetch_configured_pregame_bullpen_evidence(
            matchup={
                "gamePk": 123,
                "game_time": AS_OF,
            },
            away_team_id=10,
            home_team_id=20,
            environment={},
            fetcher=fetcher,
        )
    )

    assert len(calls) == 1
    assert calls[0]["endpoint"] is None
    assert calls[0]["provider_name"] is None
    assert calls[0]["api_token"] is None

    assert result.status == (
        "provider_not_configured"
    )
    assert result.observations == ()
    assert result.to_diagnostics()[
        "production_authority_changed"
    ] is False


def test_production_adapter_rejects_non_mapping_matchup():
    from mlb_app import model_projections

    try:
        (
            model_projections
            ._fetch_configured_pregame_bullpen_evidence(
                matchup=object(),
                away_team_id=10,
                home_team_id=20,
                environment={},
            )
        )
    except TypeError as exc:
        assert str(exc) == (
            "matchup must be a dictionary"
        )
    else:
        raise AssertionError(
            "expected TypeError"
        )
