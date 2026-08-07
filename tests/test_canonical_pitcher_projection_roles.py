from copy import deepcopy

from mlb_app.simulation.projections.pitcher_role_enrichment import (
    CANONICAL_PITCHER_PROJECTION_ROLE_ENRICHMENT_VERSION,
    enrich_canonical_pitcher_projection_roles,
)


def payload():
    return {
        "schema_version":
            "canonical_player_projection_rows_v1",
        "players": [
            {
                "player_id": "batter_1",
                "player_type": "batter",
                "team_side": "away",
                "metrics": {},
            },
            {
                "player_id": "100",
                "player_type": "pitcher",
                "team_side": "away",
                "metrics": {},
            },
            {
                "player_id": "101",
                "player_type": "pitcher",
                "team_side": "away",
                "metrics": {},
            },
            {
                "player_id": "200",
                "player_type": "pitcher",
                "team_side": "home",
                "metrics": {},
            },
        ],
    }


def record(
    pitcher_id,
    role,
    *,
    team_side="away",
    trial_index=0,
):
    return {
        "trial_index": trial_index,
        "team_side": team_side,
        "pitcher_id": pitcher_id,
        "planned_role": role,
    }


def test_attaches_same_run_canonical_roles():
    source = payload()

    result = (
        enrich_canonical_pitcher_projection_roles(
            payload=source,
            appearance_audit={
                "records": [
                    record("100", "opener"),
                    record(
                        "101",
                        "bulk_follower",
                    ),
                    record(
                        "200",
                        "starter",
                        team_side="home",
                    ),
                ],
            },
        )
    )

    pitchers = {
        row["player_id"]: row
        for row in result["players"]
        if row["player_type"] == "pitcher"
    }

    assert pitchers["100"]["pitcher_role"] == (
        "opener"
    )
    assert pitchers["101"]["pitcher_role"] == (
        "bulk_follower"
    )
    assert pitchers["200"]["pitcher_role"] == (
        "starter"
    )

    assert result[
        "pitcher_role_enrichment_applied"
    ] is True
    assert result["pitcher_role_enrichment"][
        "schema_version"
    ] == (
        CANONICAL_PITCHER_PROJECTION_ROLE_ENRICHMENT_VERSION
    )
    assert result["pitcher_role_enrichment"][
        "inference_used"
    ] is False


def test_missing_role_evidence_remains_explicit():
    result = (
        enrich_canonical_pitcher_projection_roles(
            payload=payload(),
            appearance_audit={
                "records": [
                    record("100", "opener"),
                ],
            },
        )
    )

    pitcher = next(
        row
        for row in result["players"]
        if row["player_id"] == "101"
    )

    assert pitcher["pitcher_role"] is None
    assert pitcher[
        "pitcher_role_resolution_status"
    ] == "missing"


def test_conflicting_roles_are_not_inferred():
    result = (
        enrich_canonical_pitcher_projection_roles(
            payload=payload(),
            appearance_audit={
                "records": [
                    record("100", "starter"),
                    record(
                        "100",
                        "opener",
                        trial_index=1,
                    ),
                ],
            },
        )
    )

    pitcher = next(
        row
        for row in result["players"]
        if row["player_id"] == "100"
    )

    assert pitcher["pitcher_role"] is None
    assert pitcher[
        "pitcher_role_resolution_status"
    ] == "conflicting"
    assert result["pitcher_role_enrichment"][
        "conflicting_pitcher_count"
    ] == 1


def test_enrichment_does_not_mutate_inputs():
    source = payload()
    original = deepcopy(source)

    enrich_canonical_pitcher_projection_roles(
        payload=source,
        appearance_audit={
            "records": [
                record("100", "starter"),
            ],
        },
    )

    assert source == original
