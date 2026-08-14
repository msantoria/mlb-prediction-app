import pytest

from mlb_app.simulation.shadow.canonical_bullpen_eligibility import (
    enforce_canonical_bullpen_eligibility,
)


def evidence(
    *,
    status,
    role,
    reason=None,
):
    return {
        "status": status,
        "role": role,
        "source": "pregame_role_evidence_v1",
        "reason": reason,
    }


def enforce(**overrides):
    kwargs = {
        "candidate_pitcher_ids": (
            "100",
            "101",
            "102",
            "103",
        ),
        "starter_id": "100",
        "evidence_by_pitcher_id": {
            "101": evidence(
                status="ineligible",
                role="probable_starter",
                reason=(
                    "probable_starter_not_in_plan"
                ),
            ),
            "102": evidence(
                status="eligible",
                role="reliever",
            ),
            "103": evidence(
                status="eligible",
                role="long_reliever",
            ),
        },
    }
    kwargs.update(overrides)

    return (
        enforce_canonical_bullpen_eligibility(
            **kwargs
        )
    )


def record(result, pitcher_id):
    return next(
        value
        for value in result["records"]
        if value["pitcher_id"] == pitcher_id
    )


def test_excludes_scheduled_and_probable_starters():
    result = enforce()

    assert result["status"] == "enforced"
    assert result[
        "eligible_bullpen_pitcher_ids"
    ] == [
        "102",
        "103",
    ]
    assert result["excluded_pitcher_ids"] == [
        "100",
        "101",
    ]
    assert result["exclusion_reason_counts"] == {
        "probable_starter_not_in_plan": 1,
        "scheduled_starter_excluded": 1,
    }


def test_retains_explicitly_eligible_relievers():
    result = enforce()

    reliever = record(result, "102")

    assert reliever["retained"] is True
    assert reliever["pitcher_role"] == (
        "reliever"
    )
    assert reliever["decision_reason"] == (
        "explicitly_eligible"
    )


def test_unknown_evidence_fails_open():
    result = enforce(
        candidate_pitcher_ids=(
            "101",
            "102",
        ),
        starter_id="100",
        evidence_by_pitcher_id=None,
    )

    assert result["status"] == "fallback"
    assert result[
        "eligible_bullpen_pitcher_ids"
    ] == [
        "101",
        "102",
    ]
    assert result["excluded_pitcher_ids"] == []
    assert result[
        "eligibility_evidence_complete"
    ] is False
    assert result[
        "eligibility_evidence_coverage_rate"
    ] == 0.0


def test_planned_bulk_pitcher_overrides_exclusion():
    result = enforce(
        planned_pitcher_ids=("101",),
    )

    bulk = record(result, "101")

    assert bulk["retained"] is True
    assert bulk["planned_pitcher"] is True
    assert bulk["decision_reason"] == (
        "explicit_pitching_plan_override"
    )
    assert result["planned_override_count"] == 1
    assert result[
        "eligible_bullpen_pitcher_ids"
    ] == [
        "101",
        "102",
        "103",
    ]


def test_planned_tandem_pitcher_is_retained():
    result = enforce(
        candidate_pitcher_ids=("101",),
        starter_id="100",
        planned_pitcher_ids=("101",),
        evidence_by_pitcher_id={
            "101": evidence(
                status="ineligible",
                role="probable_starter",
            ),
        },
    )

    assert result[
        "eligible_bullpen_pitcher_ids"
    ] == ["101"]
    assert result["planned_override_count"] == 1


def test_invalid_evidence_fails_open():
    result = enforce(
        candidate_pitcher_ids=("101",),
        starter_id="100",
        evidence_by_pitcher_id={
            "101": {
                "status": "blocked",
                "role": "mystery",
            },
        },
    )

    pitcher = record(result, "101")

    assert pitcher["retained"] is True
    assert pitcher["evidence_valid"] is False
    assert pitcher["decision_reason"] == (
        "invalid_eligibility_evidence"
    )


def test_normalizes_and_deduplicates_ids():
    result = enforce(
        candidate_pitcher_ids=(
            101,
            "101",
            None,
            102,
            "102",
        ),
        starter_id=100,
        evidence_by_pitcher_id=None,
    )

    assert result["candidate_pitcher_ids"] == [
        "101",
        "102",
    ]
    assert result[
        "eligible_bullpen_pitcher_ids"
    ] == [
        "101",
        "102",
    ]


def test_evidence_completeness_reconciles():
    result = enforce(
        candidate_pitcher_ids=(
            "101",
            "102",
        ),
        starter_id="100",
        evidence_by_pitcher_id={
            "101": evidence(
                status="ineligible",
                role="probable_starter",
            ),
            "102": evidence(
                status="eligible",
                role="reliever",
            ),
        },
    )

    assert result[
        "eligibility_evidence_complete"
    ] is True
    assert result[
        "eligibility_evidence_coverage_rate"
    ] == 1.0


def test_is_read_only_and_non_authoritative():
    result = enforce()

    assert (
        result["database_writes_performed"]
        is False
    )
    assert (
        result["production_authority_changed"]
        is False
    )
    assert result["decision"][
        "production_activation_allowed"
    ] is False
    assert result["safety_checks"][
        "unknown_evidence_fails_open"
    ] is True


def test_rejects_invalid_evidence_container():
    with pytest.raises(
        TypeError,
        match="evidence_by_pitcher_id",
    ):
        enforce(
            evidence_by_pitcher_id=object(),
        )


def test_strict_membership_excludes_unknown_candidates():
    result = enforce(
        candidate_pitcher_ids=(
            "101",
            "102",
        ),
        starter_id="100",
        evidence_by_pitcher_id=None,
        require_explicit_bullpen_membership=True,
    )

    assert result[
        "eligible_bullpen_pitcher_ids"
    ] == []
    assert result["excluded_pitcher_ids"] == [
        "101",
        "102",
    ]
    assert result[
        "strict_membership_excluded_count"
    ] == 2
    assert result[
        "require_explicit_bullpen_membership"
    ] is True
    assert result["safety_checks"][
        "unknown_evidence_fails_closed"
    ] is True


def test_strict_membership_retains_explicit_relievers():
    result = enforce(
        require_explicit_bullpen_membership=True,
    )

    assert result[
        "eligible_bullpen_pitcher_ids"
    ] == [
        "102",
        "103",
    ]
    assert record(result, "102")[
        "decision_reason"
    ] == "explicitly_eligible"


@pytest.mark.parametrize(
    "role",
    [
        "starter",
        "probable_starter",
    ],
)
def test_strict_membership_excludes_starter_like_roles(
    role,
):
    result = enforce(
        candidate_pitcher_ids=("101",),
        starter_id="100",
        evidence_by_pitcher_id={
            "101": evidence(
                status="eligible",
                role=role,
            ),
        },
        require_explicit_bullpen_membership=True,
    )

    assert result[
        "eligible_bullpen_pitcher_ids"
    ] == []
    assert result["excluded_pitcher_ids"] == [
        "101",
    ]
    assert record(result, "101")[
        "decision_reason"
    ] == "starter_like_role_excluded"
    assert result[
        "starter_like_excluded_count"
    ] == 1


def test_strict_membership_preserves_planned_bulk_pitcher():
    result = enforce(
        candidate_pitcher_ids=("101",),
        starter_id="100",
        planned_pitcher_ids=("101",),
        evidence_by_pitcher_id={
            "101": evidence(
                status="ineligible",
                role="probable_starter",
            ),
        },
        require_explicit_bullpen_membership=True,
    )

    assert result[
        "eligible_bullpen_pitcher_ids"
    ] == ["101"]
    assert record(result, "101")[
        "decision_reason"
    ] == "explicit_pitching_plan_override"


def test_strict_membership_rejects_non_boolean_mode():
    with pytest.raises(TypeError):
        enforce(
            require_explicit_bullpen_membership=(
                "yes"
            ),
        )
