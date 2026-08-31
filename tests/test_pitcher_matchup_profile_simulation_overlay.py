from mlb_app.simulation.game import (
    CANONICAL_PA_OUTCOME_ORDER,
    CanonicalLineup,
    CanonicalMatchupInput,
    CanonicalOutcomeProbability,
    CanonicalPitchingPlan,
    CanonicalPlateAppearanceOutcome,
    CanonicalProbabilityArtifact,
    CanonicalProbabilityArtifactRecord,
    CanonicalProbabilityFallbackCatalog,
    CanonicalProbabilityFallbackRecord,
    CanonicalProbabilityFallbackTier,
    CanonicalProbabilityProviderIdentity,
)
from mlb_app.simulation.shadow.pitcher_matchup_profile_simulation_overlay import (
    build_pitcher_matchup_profile_simulation_overlay,
)


def provider():
    return CanonicalProbabilityProviderIdentity(
        provider_name="base-provider",
        provider_version="v1",
        artifact_id="base-artifact",
    )


def probabilities(k_rate=0.20):
    remaining = 1.0 - k_rate
    values = {
        CanonicalPlateAppearanceOutcome.OUT:
            remaining * 0.60,
        CanonicalPlateAppearanceOutcome.SINGLE:
            remaining * 0.15,
        CanonicalPlateAppearanceOutcome.DOUBLE:
            remaining * 0.06,
        CanonicalPlateAppearanceOutcome.TRIPLE:
            remaining * 0.01,
        CanonicalPlateAppearanceOutcome.HOME_RUN:
            remaining * 0.05,
        CanonicalPlateAppearanceOutcome.WALK:
            remaining * 0.08,
        CanonicalPlateAppearanceOutcome.HIT_BY_PITCH:
            remaining * 0.05,
        CanonicalPlateAppearanceOutcome.STRIKEOUT:
            k_rate,
    }
    return tuple(
        CanonicalOutcomeProbability(
            outcome=outcome,
            probability=values[outcome],
        )
        for outcome in CANONICAL_PA_OUTCOME_ORDER
    )


def inputs():
    identity = provider()
    matchup = CanonicalMatchupInput(
        game_pk=1,
        away_lineup=CanonicalLineup(
            team_side="away",
            player_ids=tuple(
                str(value)
                for value in range(1, 10)
            ),
        ),
        home_lineup=CanonicalLineup(
            team_side="home",
            player_ids=tuple(
                str(value)
                for value in range(11, 20)
            ),
        ),
        away_pitching_plan=CanonicalPitchingPlan(
            team_side="away",
            starter_id="100",
            bullpen_pitcher_ids=("101",),
        ),
        home_pitching_plan=CanonicalPitchingPlan(
            team_side="home",
            starter_id="200",
            bullpen_pitcher_ids=("201",),
        ),
        probability_provider=identity,
    )
    artifact = CanonicalProbabilityArtifact(
        provider=identity,
        records=(
            CanonicalProbabilityArtifactRecord(
                batter_id="1",
                pitcher_id="200",
                probabilities=probabilities(),
            ),
            CanonicalProbabilityArtifactRecord(
                batter_id="2",
                pitcher_id="201",
                probabilities=probabilities(0.25),
            ),
        ),
    )
    catalog = CanonicalProbabilityFallbackCatalog(
        provider=identity,
        records=(
            CanonicalProbabilityFallbackRecord(
                tier=CanonicalProbabilityFallbackTier.GLOBAL,
                identity=None,
                probabilities=probabilities(),
            ),
        ),
    )
    return matchup, artifact, catalog


def comparison():
    return {
        "status": "ready",
        "executed": True,
        "production_inputs_unchanged": True,
        "production_authority_changed": False,
        "production_probabilities": {
            "out": 0.65,
            "single": 0.15,
            "double": 0.05,
            "triple": 0.01,
            "home_run": 0.04,
            "walk": 0.07,
            "strikeout": 0.03,
        },
        "shadow_probabilities": {
            "out": 0.64,
            "single": 0.15,
            "double": 0.05,
            "triple": 0.01,
            "home_run": 0.04,
            "walk": 0.07,
            "strikeout": 0.04,
        },
    }


def activation():
    return {
        "activated": True,
        "model": {
            "probabilities": (
                comparison()["shadow_probabilities"]
            ),
        },
        "diagnostics": {
            "status": "activated",
            "activation_executed": True,
            "activation_status": (
                "production_candidate_activated"
            ),
            "production_authority_changed": True,
        },
    }


def payload():
    return {
        "activation": activation(),
        "comparison": comparison(),
    }


def build(payloads=None):
    matchup, artifact, catalog = inputs()
    result = (
        build_pitcher_matchup_profile_simulation_overlay(
            matchup_input=matchup,
            exact_artifact=artifact,
            fallback_catalog=catalog,
            activation_payloads_by_pitcher_id=(
                {"200": payload()}
                if payloads is None
                else payloads
            ),
        )
    )
    return result, matchup, artifact, catalog


def test_overlays_only_activated_starter_rows():
    result, _, artifact, _ = build()

    assert result["status"] == "ready"
    assert result["overlay_applied"] is True
    assert result["eligible_pitcher_count"] == 1
    assert result["overlaid_matchup_count"] == 1
    assert result["preserved_matchup_count"] == 1

    overlaid = result["exact_artifact"].record_for(
        batter_id="1",
        pitcher_id="200",
    )
    original = artifact.record_for(
        batter_id="1",
        pitcher_id="200",
    )
    bullpen = result["exact_artifact"].record_for(
        batter_id="2",
        pitcher_id="201",
    )

    assert overlaid.probabilities != original.probabilities
    assert (
        bullpen.probabilities
        == artifact.record_for(
            batter_id="2",
            pitcher_id="201",
        ).probabilities
    )


def test_preserves_hbp_mass_when_no_clamping_occurs():
    result, _, artifact, _ = build()
    overlaid = result["exact_artifact"].record_for(
        batter_id="1",
        pitcher_id="200",
    )
    original = artifact.record_for(
        batter_id="1",
        pitcher_id="200",
    )

    def hbp(record):
        return next(
            point.probability
            for point in record.probabilities
            if point.outcome
            is CanonicalPlateAppearanceOutcome.HIT_BY_PITCH
        )

    assert hbp(overlaid) == hbp(original)


def test_rebinds_all_provider_identities():
    result, _, _, _ = build()
    identity = result[
        "matchup_input"
    ].probability_provider

    assert result["exact_artifact"].provider == identity
    assert result["fallback_catalog"].provider == identity
    assert result["simulation_inputs_changed"] is True
    assert (
        result["production_authority_changed"]
        is False
    )


def test_blocked_activation_preserves_original_inputs():
    blocked = payload()
    blocked["activation"]["activated"] = False
    result, matchup, artifact, catalog = build(
        {"200": blocked}
    )

    assert result["status"] == "fallback"
    assert result["overlay_applied"] is False
    assert result["matchup_input"] is matchup
    assert result["exact_artifact"] is artifact
    assert result["fallback_catalog"] is catalog


def test_bullpen_activation_payload_is_ignored():
    result, matchup, artifact, catalog = build(
        {"201": payload()}
    )

    assert result["status"] == "fallback"
    assert (
        "no_eligible_activated_starters"
        in result["blockers"]
    )
    assert result["matchup_input"] is matchup
    assert result["exact_artifact"] is artifact
    assert result["fallback_catalog"] is catalog


def test_overlay_is_deterministic_and_nonmutating():
    first, _, original, _ = build()
    second, _, _, _ = build()

    assert (
        first["overlay_provider_identity"]
        == second["overlay_provider_identity"]
    )
    assert (
        first["exact_artifact"].digest
        == second["exact_artifact"].digest
    )
    assert original.record_for(
        batter_id="1",
        pitcher_id="200",
    ).probabilities == probabilities()
