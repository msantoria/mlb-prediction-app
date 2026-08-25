from copy import deepcopy

from mlb_app.simulation.shadow.canonical_pitcher_matchup_profile_pa_comparator import (
    compare_canonical_pitcher_matchup_profile_pa_outcomes,
)


def production_pitcher_profile():
    return {
        "bat_missing": {
            "k_rate": 0.20,
        },
        "command_control": {
            "bb_rate": 0.08,
        },
        "contact_management": {
            "barrel_rate_allowed": 0.10,
            "hard_hit_rate_allowed": 0.40,
            "xba_allowed": 0.250,
        },
    }


def batter_profile():
    return {
        "contact_skill": {
            "k_rate": 0.22,
            "contact_rate": 0.76,
            "hit_skill": 0.290,
        },
        "plate_discipline": {
            "bb_rate": 0.09,
        },
        "power": {
            "iso": 0.180,
            "barrel_rate": 0.09,
            "hard_hit_rate": 0.41,
        },
    }


def environment_profile():
    return {
        "run_environment": {
            "hr_boost_index": 1.0,
            "hit_boost_index": 1.0,
            "run_scoring_index": 1.0,
        },
    }


def ready_candidate():
    return {
        "profile_rates": {
            "k_rate": 0.28,
            "bb_rate": 0.05,
            "barrel_rate_allowed_approx": 0.07,
            "hard_hit_rate_allowed": 0.34,
            "ground_ball_rate": 0.48,
            "line_drive_rate": 0.19,
            "fly_ball_rate": 0.25,
            "popup_rate": 0.08,
            "sweet_spot_rate_allowed": 0.29,
        },
        "diagnostics": {
            "status": "ready",
            "blocked_metrics": {
                "bb_rate": [
                    "cross_season_candidate_instability"
                ],
            },
            "production_authority": False,
            "production_authority_changed": False,
        },
    }


def compare(candidate=None):
    return (
        compare_canonical_pitcher_matchup_profile_pa_outcomes(
            candidate=(
                candidate
                if candidate is not None
                else ready_candidate()
            ),
            production_pitcher_profile=(
                production_pitcher_profile()
            ),
            batter_profile=batter_profile(),
            environment_profile=environment_profile(),
        )
    )


def test_runs_paired_shadow_comparison_without_mutation():
    production = production_pitcher_profile()
    original = deepcopy(production)

    result = (
        compare_canonical_pitcher_matchup_profile_pa_outcomes(
            candidate=ready_candidate(),
            production_pitcher_profile=production,
            batter_profile=batter_profile(),
            environment_profile=environment_profile(),
        )
    )

    assert result["status"] == "ready"
    assert result["executed"] is True
    assert production == original
    assert result["production_inputs_unchanged"] is True
    assert result["shadow_only"] is True
    assert result["production_authority_changed"] is False
    assert (
        result["maximum_absolute_probability_delta"]
        > 0
    )
    assert set(result["probability_deltas"]) == set(
        result["production_probabilities"]
    )
    assert abs(
        result["production_probability_sum"] - 1.0
    ) <= 0.0005
    assert abs(
        result["shadow_probability_sum"] - 1.0
    ) <= 0.0005


def test_maps_only_supported_calibrated_rates():
    result = compare()
    profile = result["candidate_pitcher_profile"]

    assert profile["bat_missing"]["k_rate"] == 0.28
    assert profile["contact_management"][
        "barrel_rate_allowed"
    ] == 0.07
    assert profile["contact_management"][
        "hard_hit_rate_allowed"
    ] == 0.34
    assert result["applied_rates"] == {
        "k_rate": 0.28,
        "barrel_rate_allowed_approx": 0.07,
        "hard_hit_rate_allowed": 0.34,
    }


def test_blocked_walk_rate_remains_production_value():
    result = compare()
    profile = result["candidate_pitcher_profile"]

    assert profile["command_control"]["bb_rate"] == 0.08
    assert result["deferred_rates"]["bb_rate"] == (
        "cross_season_candidate_instability"
    )


def test_unmapped_contact_distribution_is_deferred():
    result = compare()

    assert result["deferred_rates"][
        "ground_ball_rate"
    ] == "pa_outcome_v1_has_no_contact_type_input"
    assert result["deferred_rates"][
        "line_drive_rate"
    ] == "pa_outcome_v1_has_no_contact_type_input"
    assert result["deferred_rates"][
        "sweet_spot_rate_allowed"
    ] == "pa_outcome_v1_has_no_sweet_spot_input"


def test_xba_remains_authoritative_production_input():
    result = compare()

    assert result["candidate_pitcher_profile"][
        "contact_management"
    ]["xba_allowed"] == 0.250


def test_non_ready_candidate_fails_closed():
    candidate = ready_candidate()
    candidate["diagnostics"]["status"] = "blocked"

    result = compare(candidate)

    assert result["status"] == "blocked"
    assert result["executed"] is False
    assert result["production_authority_changed"] is False
    assert "production_probabilities" not in result


def test_invalid_authority_contract_fails_closed():
    candidate = ready_candidate()
    candidate["diagnostics"][
        "production_authority_changed"
    ] = True

    result = compare(candidate)

    assert result["status"] == "blocked"
    assert result["executed"] is False
    assert (
        "candidate_authority_contract_invalid"
        in result["blockers"]
    )


def test_missing_supported_rates_do_not_overwrite_profile():
    candidate = ready_candidate()
    candidate["profile_rates"] = {
        "ground_ball_rate": 0.50,
    }

    result = compare(candidate)

    assert result["status"] == "blocked"
    assert result["executed"] is False
    assert "no_supported_candidate_rates" in (
        result["blockers"]
    )



def test_reconciles_ready_shadow_rounding_residual():
    value = ready_candidate()
    value["profile_rates"].update({
        "k_rate": 0.25,
        "barrel_rate_allowed_approx": 0.08,
        "hard_hit_rate_allowed": 0.36,
    })

    result = compare(value)
    probabilities = result[
        "shadow_probabilities"
    ]

    assert result["status"] == "ready"
    assert result[
        "shadow_probability_sum"
    ] == 1.0
    assert round(
        sum(probabilities.values()),
        12,
    ) == 1.0
    assert probabilities["out"] == 0.4217
