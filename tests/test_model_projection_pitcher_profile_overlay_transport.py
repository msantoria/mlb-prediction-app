from mlb_app import model_projections


def activation(activated):
    return {
        "activated": activated,
        "model": {
            "probabilities": {},
        },
        "diagnostics": {
            "status": (
                "activated"
                if activated
                else "blocked"
            ),
        },
    }


def comparison(side):
    return {
        "status": "ready",
        "side": side,
    }


def build(
    *,
    away_pitcher_id="100",
    home_pitcher_id="200",
    away_activated=True,
    home_activated=True,
):
    away_activation = activation(
        away_activated
    )
    home_activation = activation(
        home_activated
    )
    away_comparison = comparison(
        "away_offense_vs_home_starter"
    )
    home_comparison = comparison(
        "home_offense_vs_away_starter"
    )

    result = (
        model_projections
        ._pitcher_profile_overlay_payloads_by_pitcher_id(
            away_pitcher_id=away_pitcher_id,
            home_pitcher_id=home_pitcher_id,
            away_vs_home_activation=(
                away_activation
            ),
            away_vs_home_comparison=(
                away_comparison
            ),
            home_vs_away_activation=(
                home_activation
            ),
            home_vs_away_comparison=(
                home_comparison
            ),
        )
    )

    return (
        result,
        away_activation,
        home_activation,
        away_comparison,
        home_comparison,
    )


def test_maps_each_activation_to_opposing_starter():
    (
        result,
        away_activation,
        home_activation,
        away_comparison,
        home_comparison,
    ) = build()

    assert result == {
        "200": {
            "activation": away_activation,
            "comparison": away_comparison,
        },
        "100": {
            "activation": home_activation,
            "comparison": home_comparison,
        },
    }


def test_omits_blocked_activation():
    result, _, _, _, _ = build(
        away_activated=False,
    )

    assert set(result) == {"100"}


def test_omits_missing_or_boolean_pitcher_ids():
    result, _, _, _, _ = build(
        away_pitcher_id=True,
        home_pitcher_id=None,
    )

    assert result == {}


def test_transport_is_deterministic():
    first, _, _, _, _ = build()
    second, _, _, _, _ = build()

    assert first == second
