from pathlib import Path


MODEL_PROJECTIONS_PATH = Path(
    "mlb_app/model_projections.py"
)


def source():
    return MODEL_PROJECTIONS_PATH.read_text()


def test_discovers_alignment_after_production_lineup_selection():
    value = source()

    selection = value.index(
        "canonical_production_lineup_selection ="
    )
    discovery = value.index(
        "canonical_defensive_alignment_discovery ="
    )
    fallback = value.index(
        "canonical_legacy_fallback_execution ="
    )

    assert selection < discovery < fallback


def test_fallback_execution_receives_materialization():
    value = source()
    start = value.index(
        "canonical_legacy_fallback_execution ="
    )
    end = value.index(
        "canonical_catcher_assignment_discovery =",
        start,
    )
    block = value[start:end]

    assert (
        "defensive_alignment_materialization="
        in block
    )
    assert (
        "canonical_defensive_alignment_discovery"
        in block
    )


def test_paired_execution_receives_same_materialization():
    value = source()
    start = value.index(
        "canonical_live_baserunning_pair ="
    )
    end = value.index(
        "canonical_baserunning_activation =",
        start,
    )
    block = value[start:end]

    assert (
        "defensive_alignment_materialization="
        in block
    )
    assert (
        "canonical_defensive_alignment_discovery"
        in block
    )


def test_alignment_discovery_is_exposed_in_diagnostics():
    value = source()

    assert (
        "canonicalDefensiveAlignmentDiscovery"
        in value
    )
    assert (
        '"canonical_defensive_alignment_discovery"'
        in value
    )
