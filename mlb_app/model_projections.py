from __future__ import annotations

from copy import deepcopy

import datetime
import os
from typing import Any, Dict, List, Optional

from sqlalchemy import inspect, text
from sqlalchemy.orm import Session

from mlb_app.database import StatcastEvent
from mlb_app.statcast_event_identity import (
    load_canonical_statcast_events,
)
from mlb_app.simulation.shadow.canonical_pitcher_matchup_profile_runtime_batch import (
    build_canonical_pitcher_matchup_profile_runtime_batch,
)
from mlb_app.simulation.shadow.canonical_pitcher_matchup_profile_source import (
    source_canonical_pitcher_matchup_profile,
)
from mlb_app.simulation.shadow.canonical_pitcher_matchup_profile_pa_activation import (
    APPROVED_CROSS_SEASON_AUDIT_DIGEST,
    APPROVED_ELIGIBILITY_DIGEST,
    APPROVED_HISTORICAL_EVALUATION_DIGEST,
    select_canonical_pitcher_matchup_profile_pa_model,
)
from mlb_app.simulation.shadow.canonical_pitcher_matchup_profile_pa_comparator import (
    compare_canonical_pitcher_matchup_profile_pa_outcomes,
)
from mlb_app.simulation.projections.pitcher_pool_role_reconciliation import (
    reconcile_canonical_pitcher_projection_pool_roles,
)
from mlb_app.simulation.projections.pitcher_projection_authority import (
    apply_canonical_pitcher_projection_authority,
)
from mlb_app.simulation.shadow.canonical_pitcher_projection_activation_readiness import (
    audit_canonical_pitcher_projection_activation_readiness,
)
from mlb_app.simulation.shadow.canonical_pregame_pitcher_evidence_source_coverage import (
    audit_canonical_pregame_pitcher_evidence_source_coverage,
)
from mlb_app.simulation.shadow.canonical_pitcher_projection_pool_and_workload_calibration import (
    audit_canonical_pitcher_projection_pool_and_workload_calibration,
)
from mlb_app.simulation.shadow.canonical_pitcher_role_and_innings_attribution_audit import (
    audit_canonical_pitcher_role_and_innings_attribution,
)
from mlb_app.simulation.shadow.pregame_bullpen_evidence_provider import (
    fetch_canonical_pregame_bullpen_evidence,
)
from mlb_app.simulation.shadow.pitcher_role_evidence_source import (
    fetch_canonical_pitcher_role_evidence_source,
)
from mlb_app.simulation.shadow.production_monitoring_ledger import (
    CANONICAL_BASERUNNING_PRODUCTION_AUTHORITY,
    CanonicalBaserunningProductionMonitoringRecord,
    evaluate_canonical_production_monitoring_eligibility,
    materialize_canonical_baserunning_production_monitoring,
)

from .canonical_game_context import build_canonical_game_context
from .dashboard_object_models import DashboardPlayer
from .db_utils import get_pitch_arsenal_with_fallback, get_team_split
from .matchup_generator import generate_matchups_for_date
from .model_projection_formulas import bullpen_collapse_index, offensive_firepower_score, pitch_identity_disruption_score, pitching_volatility_score, safe_float

from .bullpen_profile import build_bullpen_profile
from .environment_profile import compute_environment_profile
from .team_offense_prior import build_team_offense_prior
from .simulation.pa_outcome_model import build_pa_outcome_probabilities
from .simulation.game_simulator import simulate_game_with_bullpen
from mlb_app.simulation.game_simulation_builder import build_game_simulation as build_shared_game_simulation
from mlb_app.simulation.projections import (
    enrich_canonical_player_projection_rows,
)
from mlb_app.simulation.shadow import (
    CanonicalShadowBaserunningEvidenceDiscovery,
    activate_calibrated_baserunning,
    apply_calibrated_baserunning_production_authority,
    attach_canonical_shadow,
    build_canonical_production_trial_policy,
    build_canonical_shadow_bootstrap_readiness,
    discover_canonical_shadow_bullpens,
    discover_canonical_shadow_exact_artifact,
    discover_canonical_shadow_fallback_catalog,
    discover_canonical_shadow_lineups,
    discover_canonical_shadow_probability_provider,
    discover_confirmed_catcher_assignments,
    execute_live_baserunning_shadow_pair,
    evaluate_canonical_extras_walkoff_activation,
    finalize_canonical_baserunning_production_settlements,
    load_baserunning_production_prior,
    load_canonical_baserunning_production_settlements,
    run_canonical_production_shadow,
    summarize_canonical_baserunning_production_settlements,
)


def _load_production_settlement_diagnostics(
    session: Session,
) -> Dict[str, Any]:
    # Optional settlement storage must never suppress projection games.

    try:
        with session.begin_nested():
            rows = (
                load_canonical_baserunning_production_settlements(
                    session
                )
            )
        summary = (
            summarize_canonical_baserunning_production_settlements(
                rows
            )
        )
        finalization = (
            finalize_canonical_baserunning_production_settlements(
                rows
            ).to_diagnostics()
        )
        summary.update(
            {
                "status": "ready",
                "storage_available": True,
                "error_type": None,
                "error_message": None,
                "_calibration_finalization": finalization,
            }
        )
        return summary
    except Exception as exc:
        summary = (
            summarize_canonical_baserunning_production_settlements(
                ()
            )
        )
        finalization = (
            finalize_canonical_baserunning_production_settlements(
                ()
            ).to_diagnostics()
        )
        summary.update(
            {
                "status": "unavailable",
                "storage_available": False,
                "error_type": exc.__class__.__name__,
                "error_message": str(exc),
                "_calibration_finalization": finalization,
            }
        )
        return summary


def _build_game_state_realism_diagnostics(
    shared_simulation: Any = None,
) -> dict:
    """Layer 6OF guarded diagnostic payload.

    Diagnostic-only wiring for game-state realism features.

    This helper intentionally does not replace or tune final projection
    probabilities. It exposes whether key Layer 6 game-state realism concepts
    are intended to be represented in the Model Projections payload.
    """
    activation = {}

    if isinstance(shared_simulation, dict):
        shared_diagnostics = (
            shared_simulation.get(
                "diagnostics",
                {},
            )
        )
        canonical_shadow = (
            shared_diagnostics.get(
                "canonical_shadow",
                {},
            )
            if isinstance(
                shared_diagnostics,
                dict,
            )
            else {}
        )
        activation = (
            canonical_shadow.get(
                "canonical_extras_walkoff_activation",
                {},
            )
            if isinstance(
                canonical_shadow,
                dict,
            )
            else {}
        )

    activation = (
        activation
        if isinstance(activation, dict)
        else {}
    )
    active = activation.get("active") is True

    return {
        "base_out_state_enabled": True,
        "base_out_transition_model_status": "diagnostic_wired",
        "base_out_simulation_summary": {
            "status": "diagnostic_only",
            "final_probability_replacement": False,
        },
        "runner_advancement_enabled": True,
        "runner_advancement_model_status": "diagnostic_wired",
        "runner_advancement_summary": {
            "status": "diagnostic_only",
            "events": ["single", "double", "ground_ball", "fly_ball"],
            "final_probability_replacement": False,
        },
        "extra_innings_enabled": (
            True if active else None
        ),
        "automatic_runner_enabled": (
            True if active else None
        ),
        "walk_off_enabled": (
            True if active else None
        ),
        "extras_enabled": True,
        "ghost_runner_enabled": True,
        "walkoff_shortening_enabled": True,
        "extras_walkoff_model_status": (
            activation.get(
                "status",
                "canonical_execution_not_available",
            )
        ),
        "extras_walkoff_activation": deepcopy(
            activation
        ),
        "double_play_enabled": True,
        "multi_out_scoring": True,
        "double_play_rate_source": "existing_simulation_transition_logic",
        "double_play_transition_summary": {
            "status": "diagnostic_only",
            "final_probability_replacement": False,
        },
        "sac_fly_enabled": True,
        "sacrifice_fly_scoring": True,
        "sac_fly_rate_source": "existing_simulation_transition_logic",
        "sac_fly_transition_summary": {
            "status": "diagnostic_only",
            "final_probability_replacement": False,
        },
        "stolen_bases": True,
        "stolen_base_model": True,
        "steals_model_status": "canonical_calibrated_active",
        "steals_projection_wiring_status": (
            "canonical_event_driven_production_authority"
        ),
    }


def _obj_to_dict(obj: Any, fields: List[str]) -> Dict[str, Any]:
    return {field: getattr(obj, field, None) for field in fields} if obj is not None else {}


def _arsenal_records_to_dict(records: List[Any]) -> Dict[str, Dict[str, Any]]:
    out: Dict[str, Dict[str, Any]] = {}
    for record in records or []:
        pitch_type = getattr(record, "pitch_type", None) or getattr(record, "pitch_name", None) or "unknown"
        out[pitch_type] = {
            "pitch_type": getattr(record, "pitch_type", None),
            "pitch_name": getattr(record, "pitch_name", None),
            "pitch_count": getattr(record, "pitch_count", None),
            "usage_pct": getattr(record, "usage_pct", None),
            "whiff_pct": getattr(record, "whiff_pct", None),
            "strikeout_pct": getattr(record, "strikeout_pct", None),
            "rv_per_100": getattr(record, "rv_per_100", None),
            "xwoba": getattr(record, "xwoba", None),
            "hard_hit_pct": getattr(record, "hard_hit_pct", None),
        }
    return out


def _team_split_inputs(session: Session, team_id: Optional[int], season: int) -> Dict[str, Any]:
    if not team_id:
        return {"source": "missing_team_id"}
    row = get_team_split(session, int(team_id), season, "vsR") or get_team_split(session, int(team_id), season, "vsL")
    data = _obj_to_dict(row, ["pa", "hits", "doubles", "triples", "home_runs", "walks", "strikeouts", "batting_avg", "on_base_pct", "slugging_pct", "iso", "k_pct", "bb_pct"])
    data.update({
        "team_id": team_id,
        "split": getattr(row, "split", None) if row else None,
        "lineup_source": "team_splits_fallback_not_confirmed_lineup" if row else None,
        "player_count_used": None,
        "sample_blend": {"type": "team_split", "season": season, "split": getattr(row, "split", None)} if row else None,
        "source": "team_splits" if row else "missing_team_splits",
    })
    return data


def _find_column(columns: List[str], aliases: List[str]) -> Optional[str]:
    normalized = {col.lower().replace("_", "").replace("/", ""): col for col in columns}
    for alias in aliases:
        key = alias.lower().replace("_", "").replace("/", "")
        if key in normalized:
            return normalized[key]
    return None


def _bullpen_inputs(session: Session, team_id: Optional[int], team_name: Optional[str]) -> Dict[str, Any]:
    try:
        inspector = inspect(session.bind)
        table_names = set(inspector.get_table_names())
    except Exception:
        return {"source_table": None}
    table = next((name for name in ["bullpen_stats", "team_bullpen_stats", "table_layerseven", "layerseven", "team_pitching_bullpen", "team_pitching_stats"] if name in table_names), None)
    if not table:
        return {"source_table": None}
    try:
        columns = [col["name"] for col in inspector.get_columns(table)]
        team_id_col = _find_column(columns, ["team_id", "teamid", "mlb_team_id"])
        team_name_col = _find_column(columns, ["team_name", "team", "name"])
        era_col = _find_column(columns, ["era", "bullpen_era"])
        bb9_col = _find_column(columns, ["bb_per_9", "bb9", "bb_9", "bb_per_nine", "walks_per_9"])
        whip_col = _find_column(columns, ["whip", "bullpen_whip"])
        if not all([era_col, bb9_col, whip_col]):
            return {"source_table": table}
        where = None
        params: Dict[str, Any] = {}
        if team_id_col and team_id is not None:
            where = f"{team_id_col} = :team_id"
            params["team_id"] = int(team_id)
        elif team_name_col and team_name:
            where = f"lower({team_name_col}) = lower(:team_name)"
            params["team_name"] = team_name
        if not where:
            return {"source_table": table}
        row = session.execute(text(f"SELECT {era_col} AS era, {bb9_col} AS bb_per_9, {whip_col} AS whip FROM {table} WHERE {where} LIMIT 1"), params).mappings().first()
        return {"era": row.get("era"), "bb_per_9": row.get("bb_per_9"), "whip": row.get("whip"), "source_table": table} if row else {"source_table": table}
    except Exception as exc:
        return {"source_table": table, "error": str(exc)}


def _probability_model_card(model_name: str, score: Optional[float], inputs: Dict[str, Any], formula: str, steps: List[str], notes: List[str], confidence: str = "low") -> Dict[str, Any]:
    missing = [key for key, value in inputs.items() if value is None]
    return {
        "model_name": model_name,
        "status": "calculated" if score is not None and not missing else "partial" if score is not None else "missing_inputs",
        "score": round(float(score), 3) if score is not None else None,
        "formula": formula,
        "inputs": inputs,
        "calculation_steps": steps,
        "missing_inputs": missing,
        "data_confidence": confidence,
        "source_notes": notes,
    }


def _team_offense_prior_pa_model(team_id: Optional[int], team_name: Optional[str], opposing_pitcher_profile: Optional[Dict[str, Any]], environment_profile: Dict[str, Any], offense_profile: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    if not offense_profile:
        offense_profile = build_team_offense_prior(team_id=team_id, team_name=team_name)

    return build_pa_outcome_probabilities(
        batter_profile=offense_profile,
        pitcher_profile=opposing_pitcher_profile or {},
        environment_profile=environment_profile,
    )


def _weather_context(value: Any) -> Dict[str, Any]:
    if isinstance(value, dict):
        return value
    if isinstance(value, str) and value.strip():
        return {"wind": value}
    return {}


def _normalize_rate(value: Any) -> Optional[float]:
    rate = safe_float(value)
    if rate is None:
        return None
    if rate > 1.0:
        return round(rate / 100.0, 4)
    return round(rate, 4)


def _rate_from_count(numerator: Any, denominator: Any) -> Optional[float]:
    num = safe_float(numerator)
    den = safe_float(denominator)
    if num is None or den is None or den <= 0:
        return None
    return round(num / den, 4)


def _choose_count_derived_rate(raw_rate: Any, numerator: Any, denominator: Any, plausible_low: float, plausible_high: float) -> tuple[Optional[float], str]:
    normalized = _normalize_rate(raw_rate)
    derived = _rate_from_count(numerator, denominator)

    if derived is not None and plausible_low <= derived <= plausible_high:
        return derived, "derived_from_count_totals"

    if normalized is not None and plausible_low <= normalized <= plausible_high:
        return normalized, "normalized_source_rate"

    if normalized is not None:
        return normalized, "normalized_source_rate_outside_expected_range"

    return None, "missing_rate"


def _pitcher_workspace_profile(team: Dict[str, Any]) -> Dict[str, Any]:
    features = team.get("pitcher_features") or {}
    arsenal = team.get("pitch_arsenal") or {}

    k_rate, k_rate_source = _choose_count_derived_rate(features.get("k_pct"), features.get("strikeouts"), features.get("pa"), plausible_low=0.08, plausible_high=0.45)
    bb_rate, bb_rate_source = _choose_count_derived_rate(features.get("bb_pct"), features.get("walks"), features.get("pa"), plausible_low=0.015, plausible_high=0.20)
    hard_hit = _normalize_rate(features.get("hard_hit_pct"))
    xwoba = safe_float(features.get("xwoba"))
    xba = safe_float(features.get("xba"))

    rate_source_notes = {
        "k_rate_source": k_rate_source,
        "bb_rate_source": bb_rate_source,
        "hard_hit_rate_source": "normalized_from_pitcher_features.hard_hit_pct" if hard_hit is not None else "missing_pitcher_features.hard_hit_pct",
        "raw_k_pct": safe_float(features.get("k_pct")),
        "raw_bb_pct": safe_float(features.get("bb_pct")),
        "pa": safe_float(features.get("pa")),
        "strikeouts": safe_float(features.get("strikeouts")),
        "walks": safe_float(features.get("walks")),
    }

    return {
        "metadata": {
            "source_type": "model_projection_pitcher_features",
            "generated_from": "model_projections._pitcher_workspace_profile",
            "data_confidence": "medium" if features else "low",
            "pitcher_id": team.get("pitcher_id"),
            "pitcher_name": team.get("pitcher_name"),
            "pitch_arsenal_source": team.get("pitch_arsenal_source"),
            "profile_granularity": "probable_pitcher",
            "sample_window": features.get("source_window"),
            "sample_size": safe_float(features.get("pa")),
            "sample_blend_policy": "selected_source_window",
            "rate_source_notes": rate_source_notes,
        },
        "bat_missing": {"k_rate": k_rate, "whiff_rate": None, "csw_rate": None},
        "command_control": {"bb_rate": bb_rate, "zone_rate": None, "first_pitch_strike_rate": None},
        "contact_management": {
            "hard_hit_rate_allowed": hard_hit,
            "xwoba_allowed": xwoba,
            "xba_allowed": xba,
            "avg_exit_velocity_allowed": safe_float(features.get("avg_exit_velocity")),
            "avg_launch_angle_allowed": safe_float(features.get("avg_launch_angle")),
        },
        "arsenal": {"pitch_mix": arsenal, "avg_velocity": safe_float(features.get("avg_velocity")), "avg_spin_rate": safe_float(features.get("avg_spin_rate"))},
    }


def _offense_workspace_profile(team: Dict[str, Any]) -> Dict[str, Any]:
    inputs = team.get("offense_inputs") or {}

    k_rate, k_rate_source = _choose_count_derived_rate(inputs.get("k_pct"), inputs.get("strikeouts"), inputs.get("pa"), plausible_low=0.10, plausible_high=0.40)
    bb_rate, bb_rate_source = _choose_count_derived_rate(inputs.get("bb_pct"), inputs.get("walks"), inputs.get("pa"), plausible_low=0.03, plausible_high=0.18)

    profile = {
        "metadata": {
            "source_type": inputs.get("source") or "team_split_or_prior",
            "generated_from": "model_projections._offense_workspace_profile",
            "data_confidence": "low",
            "team_id": team.get("team_id"),
            "team_name": team.get("team_name"),
            "lineup_source": inputs.get("lineup_source"),
            "profile_granularity": inputs.get("profile_granularity") or "team_offense",
            "sample_blend": inputs.get("sample_blend"),
            "sample_window": (
                f"season={inputs.get('season')};"
                f"split={inputs.get('split')}"
                if inputs.get("season")
                else None
            ),
            "sample_size": safe_float(inputs.get("pa")),
            "sample_blend_policy": (
                (inputs.get("sample_blend") or {}).get("type")
            ),
            "rate_source_notes": {
                "k_rate_source": k_rate_source,
                "bb_rate_source": bb_rate_source,
                "raw_k_pct": safe_float(inputs.get("k_pct")),
                "raw_bb_pct": safe_float(inputs.get("bb_pct")),
                "pa": safe_float(inputs.get("pa")),
                "strikeouts": safe_float(inputs.get("strikeouts")),
                "walks": safe_float(inputs.get("walks")),
            },
        },
        "contact_skill": {"k_rate": k_rate, "batting_avg": safe_float(inputs.get("batting_avg")), "contact_rate": None},
        "plate_discipline": {"bb_rate": bb_rate, "on_base_pct": safe_float(inputs.get("on_base_pct"))},
        "power": {"iso": safe_float(inputs.get("iso")), "slugging_pct": safe_float(inputs.get("slugging_pct")), "home_runs": safe_float(inputs.get("home_runs")), "doubles": safe_float(inputs.get("doubles")), "triples": safe_float(inputs.get("triples"))},
        "run_creation": {"pa": safe_float(inputs.get("pa")), "hits": safe_float(inputs.get("hits")), "walks": safe_float(inputs.get("walks")), "strikeouts": safe_float(inputs.get("strikeouts"))},
    }

    for passthrough_key in (
        "lineup_handedness_mix",
        "lineup_handedness_mix_source",
        "lineup_handedness_coverage_rate",
        "lineup_handedness_counts",
        "lineup_handedness_player_count",
        "lineup_handedness_unavailable_reason",
    ):
        if passthrough_key in inputs:
            profile[passthrough_key] = inputs.get(passthrough_key)

    return profile


def _matchup_workspace_analysis(offense_team: Dict[str, Any], opposing_pitcher: Dict[str, Any]) -> Dict[str, Any]:
    offense_inputs = offense_team.get("offense_inputs") or {}
    pitcher_features = opposing_pitcher.get("pitcher_features") or {}
    arsenal = opposing_pitcher.get("pitch_arsenal") or {}

    offense_k, _ = _choose_count_derived_rate(offense_inputs.get("k_pct"), offense_inputs.get("strikeouts"), offense_inputs.get("pa"), plausible_low=0.10, plausible_high=0.40)
    offense_bb, _ = _choose_count_derived_rate(offense_inputs.get("bb_pct"), offense_inputs.get("walks"), offense_inputs.get("pa"), plausible_low=0.03, plausible_high=0.18)
    pitcher_k, _ = _choose_count_derived_rate(pitcher_features.get("k_pct"), pitcher_features.get("strikeouts"), pitcher_features.get("pa"), plausible_low=0.08, plausible_high=0.45)
    pitcher_bb, _ = _choose_count_derived_rate(pitcher_features.get("bb_pct"), pitcher_features.get("walks"), pitcher_features.get("pa"), plausible_low=0.015, plausible_high=0.20)

    pitch_edges = []
    for pitch_type, row in (arsenal or {}).items():
        if not isinstance(row, dict):
            continue
        pitch_edges.append({
            "pitch_type": pitch_type,
            "usage_pct": safe_float(row.get("usage_pct")),
            "whiff_pct": safe_float(row.get("whiff_pct")),
            "xwoba": safe_float(row.get("xwoba")),
            "hard_hit_pct": safe_float(row.get("hard_hit_pct")),
        })

    biggest_edge = None
    if pitch_edges:
        biggest_edge = max(pitch_edges, key=lambda row: (row.get("usage_pct") or 0) + (row.get("whiff_pct") or 0)).get("pitch_type")

    return {
        "metadata": {
            "source_type": "model_projection_workspace_matchup",
            "generated_from": "model_projections._matchup_workspace_analysis",
            "data_confidence": "medium" if arsenal else "low",
            "offense_team_id": offense_team.get("team_id"),
            "offense_team_name": offense_team.get("team_name"),
            "opposing_pitcher_id": opposing_pitcher.get("pitcher_id"),
            "opposing_pitcher_name": opposing_pitcher.get("pitcher_name"),
        },
        "summary": {
            "status": "partial",
            "note": "Model Projections workspace uses production pitcher/team inputs and conservative offense priors.",
            "biggest_edge": biggest_edge,
            "confidence": 0.5 if arsenal else 0.25,
        },
        "plate_discipline_matchup": {"offense_k_rate": offense_k, "offense_bb_rate": offense_bb, "pitcher_k_rate": pitcher_k, "pitcher_bb_rate": pitcher_bb},
        "arsenal_matchup": {"pitch_edges": pitch_edges, "biggest_edge": biggest_edge, "pitch_count_used": len(pitch_edges)},
    }


def _build_projection_simulation_cards(matchup: Dict[str, Any], away: Dict[str, Any], home: Dict[str, Any]) -> Dict[str, List[Dict[str, Any]]]:
    away_team_id = away.get("team_id")
    home_team_id = home.get("team_id")
    away_team_name = away.get("team_name")
    home_team_name = home.get("team_name")

    environment_profile = compute_environment_profile({
        "game_pk": matchup.get("game_pk"),
        "game_date": matchup.get("game_date"),
        "venue_name": matchup.get("venue"),
        "weather": _weather_context(matchup.get("weather")),
        "park_factor": matchup.get("park_factor"),
        "home_team": home_team_name,
        "away_team": away_team_name,
    })

    away_pitcher_profile = {}
    home_pitcher_profile = {}
    away_bullpen_profile = build_bullpen_profile(team_id=away_team_id, team_name=away_team_name)
    home_bullpen_profile = build_bullpen_profile(team_id=home_team_id, team_name=home_team_name)

    away_offense_profile = build_team_offense_prior(
        team_id=away_team_id,
        team_name=away_team_name,
    )
    home_offense_profile = build_team_offense_prior(
        team_id=home_team_id,
        team_name=home_team_name,
    )

    away_vs_home_starter_pa = _team_offense_prior_pa_model(
        away_team_id,
        away_team_name,
        home_pitcher_profile,
        environment_profile,
        offense_profile=away_offense_profile,
    )
    home_vs_away_starter_pa = _team_offense_prior_pa_model(
        home_team_id,
        home_team_name,
        away_pitcher_profile,
        environment_profile,
        offense_profile=home_offense_profile,
    )

    away_vs_home_pitcher_profile_shadow = (
        compare_canonical_pitcher_matchup_profile_pa_outcomes(
            candidate=(
                home.get(
                    "pitcher_matchup_profile_candidate"
                )
                or {}
            ),
            production_pitcher_profile=(
                home_pitcher_profile
            ),
            batter_profile=away_offense_profile,
            environment_profile=environment_profile,
        )
    )
    home_vs_away_pitcher_profile_shadow = (
        compare_canonical_pitcher_matchup_profile_pa_outcomes(
            candidate=(
                away.get(
                    "pitcher_matchup_profile_candidate"
                )
                or {}
            ),
            production_pitcher_profile=(
                away_pitcher_profile
            ),
            batter_profile=home_offense_profile,
            environment_profile=environment_profile,
        )
    )

    pitcher_profile_pa_activation_requested = (
        os.getenv(
            "MLB_ENABLE_CANONICAL_PITCHER_MATCHUP_PROFILE_PA",
            "",
        )
        .strip()
        .lower()
        in {"1", "true", "yes", "on"}
    )
    away_vs_home_pitcher_profile_activation = (
        select_canonical_pitcher_matchup_profile_pa_model(
            production_model=(
                away_vs_home_starter_pa
            ),
            comparison=(
                away_vs_home_pitcher_profile_shadow
            ),
            activation_requested=(
                pitcher_profile_pa_activation_requested
            ),
            eligibility_digest=(
                APPROVED_ELIGIBILITY_DIGEST
            ),
            historical_evaluation_digest=(
                APPROVED_HISTORICAL_EVALUATION_DIGEST
            ),
            cross_season_audit_digest=(
                APPROVED_CROSS_SEASON_AUDIT_DIGEST
            ),
        )
    )
    home_vs_away_pitcher_profile_activation = (
        select_canonical_pitcher_matchup_profile_pa_model(
            production_model=(
                home_vs_away_starter_pa
            ),
            comparison=(
                home_vs_away_pitcher_profile_shadow
            ),
            activation_requested=(
                pitcher_profile_pa_activation_requested
            ),
            eligibility_digest=(
                APPROVED_ELIGIBILITY_DIGEST
            ),
            historical_evaluation_digest=(
                APPROVED_HISTORICAL_EVALUATION_DIGEST
            ),
            cross_season_audit_digest=(
                APPROVED_CROSS_SEASON_AUDIT_DIGEST
            ),
        )
    )
    away_vs_home_starter_pa = (
        away_vs_home_pitcher_profile_activation[
            "model"
        ]
    )
    home_vs_away_starter_pa = (
        home_vs_away_pitcher_profile_activation[
            "model"
        ]
    )

    away_vs_home_bullpen_pa = _team_offense_prior_pa_model(away_team_id, away_team_name, home_bullpen_profile, environment_profile)
    home_vs_away_bullpen_pa = _team_offense_prior_pa_model(home_team_id, home_team_name, away_bullpen_profile, environment_profile)

    sim = simulate_game_with_bullpen(
        away_starter_probabilities=away_vs_home_starter_pa.get("probabilities") or {},
        home_starter_probabilities=home_vs_away_starter_pa.get("probabilities") or {},
        away_bullpen_probabilities=away_vs_home_bullpen_pa.get("probabilities") or {},
        home_bullpen_probabilities=home_vs_away_bullpen_pa.get("probabilities") or {},
        simulations=3000,
        seed=42,
        innings=9,
        starter_innings=5,
        away_starter_quality=0.0,
        home_starter_quality=0.0,
        dynamic_starter_exit=True,
    )

    total_probs = sim.get("calibrated_total_probabilities") or sim.get("total_probabilities") or {}
    team_total_probs = sim.get("calibrated_team_total_probabilities") or sim.get("team_total_probabilities") or {}

    away_card = _probability_model_card(
        model_name="Diagnostic Simulation: Away Team Run Projection",
        score=sim.get("away_expected_runs"),
        formula="Diagnostic team offense prior PA probabilities + opponent starter/bullpen profiles + environment + dynamic starter exit",
        inputs={
            "expected_runs": sim.get("away_expected_runs"),
            "raw_expected_runs": sim.get("raw_away_expected_runs"),
            "diagnostic_win_probability": sim.get("away_win_probability"),
            "team_3_plus_runs": team_total_probs.get("away_3_plus"),
            "team_4_plus_runs": team_total_probs.get("away_4_plus"),
            "team_5_plus_runs": team_total_probs.get("away_5_plus"),
            "offense_source": "team_offense_prior",
            "opposing_bullpen_quality": (home_bullpen_profile.get("metadata") or {}).get("bullpen_quality_label"),
            "run_environment_index": (environment_profile.get("run_environment") or {}).get("run_scoring_index"),
        },
        steps=[
            "Build conservative team offense prior because Model Projections is game-level.",
            "Convert offense, opponent starter prior, bullpen prior, and environment into PA probabilities.",
            "Simulate regulation games with starter-to-bullpen transition and calibrated run distribution.",
        ],
        notes=[
            "Diagnostic only: canonical home_win_prob/away_win_prob from /matchups are the final app-wide side probabilities.",
            "This simulation remains useful for run distribution, totals context, and debugging.",
        ],
        confidence="low",
    )

    home_card = _probability_model_card(
        model_name="Diagnostic Simulation: Home Team Run Projection",
        score=sim.get("home_expected_runs"),
        formula="Diagnostic team offense prior PA probabilities + opponent starter/bullpen profiles + environment + dynamic starter exit",
        inputs={
            "expected_runs": sim.get("home_expected_runs"),
            "raw_expected_runs": sim.get("raw_home_expected_runs"),
            "diagnostic_win_probability": sim.get("home_win_probability"),
            "team_3_plus_runs": team_total_probs.get("home_3_plus"),
            "team_4_plus_runs": team_total_probs.get("home_4_plus"),
            "team_5_plus_runs": team_total_probs.get("home_5_plus"),
            "offense_source": "team_offense_prior",
            "opposing_bullpen_quality": (away_bullpen_profile.get("metadata") or {}).get("bullpen_quality_label"),
            "run_environment_index": (environment_profile.get("run_environment") or {}).get("run_scoring_index"),
        },
        steps=[
            "Build conservative team offense prior because Model Projections is game-level.",
            "Convert offense, opponent starter prior, bullpen prior, and environment into PA probabilities.",
            "Simulate regulation games with starter-to-bullpen transition and calibrated run distribution.",
        ],
        notes=[
            "Diagnostic only: canonical home_win_prob/away_win_prob from /matchups are the final app-wide side probabilities.",
            "This simulation remains useful for run distribution, totals context, and debugging.",
        ],
        confidence="low",
    )

    game_total_card = _probability_model_card(
        model_name="Diagnostic Simulation: Game Total Projection",
        score=sim.get("total_expected_runs"),
        formula="Monte Carlo total runs from away/home PA distributions, bullpen priors, environment, and calibrated distribution",
        inputs={
            "total_expected_runs": sim.get("total_expected_runs"),
            "raw_total_expected_runs": sim.get("raw_total_expected_runs"),
            "over_6_5": total_probs.get("over_6.5"),
            "over_7_5": total_probs.get("over_7.5"),
            "over_8_5": total_probs.get("over_8.5"),
            "over_9_5": total_probs.get("over_9.5"),
            "under_7_5": total_probs.get("under_7.5"),
            "under_8_5": total_probs.get("under_8.5"),
            "under_9_5": total_probs.get("under_9.5"),
            "tie_after_regulation": sim.get("tie_after_regulation_probability"),
            "environment_label": (environment_profile.get("run_environment") or {}).get("scoring_environment_label"),
        },
        steps=[
            "Generate PA outcome probabilities for each offense against starter and bullpen contexts.",
            "Run full-game simulation with dynamic starter exit and bullpen transition.",
            "Apply existing game-simulation calibration to expected runs and probability distribution.",
        ],
        notes=[
            "Totals simulation is diagnostic and does not override canonical side probabilities.",
            "Confidence is low until lineup-level and starter-profile inputs are connected directly into this endpoint.",
        ],
        confidence="low",
    )

    workspace = {
        "environmentProfile": environment_profile,
        "awayPitcherProfile": _pitcher_workspace_profile(away),
        "homePitcherProfile": _pitcher_workspace_profile(home),
        "awayOffenseProfile": _offense_workspace_profile(away),
        "homeOffenseProfile": _offense_workspace_profile(home),
        "awayBullpenProfile": away_bullpen_profile,
        "homeBullpenProfile": home_bullpen_profile,
        "awayPAOutcomeModel": away_vs_home_starter_pa,
        "homePAOutcomeModel": home_vs_away_starter_pa,
        "pitcherMatchupProfilePAShadowComparisons": {
            "awayOffenseVsHomeStarter": (
                away_vs_home_pitcher_profile_shadow
            ),
            "homeOffenseVsAwayStarter": (
                home_vs_away_pitcher_profile_shadow
            ),
            "comparison_role": (
                "production_activation_source"
                if pitcher_profile_pa_activation_requested
                else "paired_shadow_diagnostic_only"
            ),
            "simulation_inputs_changed": (
                away_vs_home_pitcher_profile_activation[
                    "activated"
                ]
                or home_vs_away_pitcher_profile_activation[
                    "activated"
                ]
            ),
            "final_probabilities_changed": False,
            "production_authority": (
                away_vs_home_pitcher_profile_activation[
                    "activated"
                ]
                or home_vs_away_pitcher_profile_activation[
                    "activated"
                ]
            ),
            "production_authority_changed": (
                away_vs_home_pitcher_profile_activation[
                    "activated"
                ]
                or home_vs_away_pitcher_profile_activation[
                    "activated"
                ]
            ),
        },
        "pitcherMatchupProfilePAActivation": {
            "requested": (
                pitcher_profile_pa_activation_requested
            ),
            "awayOffenseVsHomeStarter": (
                away_vs_home_pitcher_profile_activation[
                    "diagnostics"
                ]
            ),
            "homeOffenseVsAwayStarter": (
                home_vs_away_pitcher_profile_activation[
                    "diagnostics"
                ]
            ),
            "simulation_inputs_changed": (
                away_vs_home_pitcher_profile_activation[
                    "activated"
                ]
                or home_vs_away_pitcher_profile_activation[
                    "activated"
                ]
            ),
            "final_side_probabilities_changed": False,
            "final_side_probability_source": (
                "matchups.canonical_matchup_win_probability_v2"
            ),
        },
        "awayVsHomeBullpenPAOutcomeModel": away_vs_home_bullpen_pa,
        "homeVsAwayBullpenPAOutcomeModel": home_vs_away_bullpen_pa,
        "awayMatchupAnalysis": _matchup_workspace_analysis(away, home),
        "homeMatchupAnalysis": _matchup_workspace_analysis(home, away),
        "bullpenAdjustedGameSimulation": sim,
        "simulationDiagnostics": {
            "status": "diagnostic_only",
            "not_final_probability": True,
            "final_probability_source": "matchups.home_win_prob_and_away_win_prob",
            "simulation_model_version": sim.get("model_version"),
            "away_diagnostic_win_probability": sim.get("away_win_probability"),
            "home_diagnostic_win_probability": sim.get("home_win_probability"),
            "away_expected_runs": sim.get("away_expected_runs"),
            "home_expected_runs": sim.get("home_expected_runs"),
            "total_expected_runs": sim.get("total_expected_runs"),
        },
        "debug_marker": "SIM_CONTRACT_V1_DIAGNOSTIC_ONLY",
        "simulationContract": {
            "source_builder": "model_projections._build_projection_simulation_cards",
            "probability_role": "diagnostic_only_not_final_side_probability",
            "final_probability_source": "matchups.canonical_matchup_win_probability_v2",
            "away_offense_source": ((away.get("offense_inputs") or {}).get("source")),
            "home_offense_source": ((home.get("offense_inputs") or {}).get("source")),
            "away_lineup_available": bool(matchup.get("away_lineup") or matchup.get("awayLineup") or matchup.get("away_projected_lineup")),
            "home_lineup_available": bool(matchup.get("home_lineup") or matchup.get("homeLineup") or matchup.get("home_projected_lineup")),
            "away_matchup_keys": sorted([k for k in matchup.keys() if "lineup" in str(k).lower() or "offense" in str(k).lower()]),
            "game_pk": matchup.get("game_pk"),
            "simulation_model_version": sim.get("model_version"),
            "simulation_count": sim.get("simulations") or (sim.get("metadata") or {}).get("simulation_count"),
            "seed": (sim.get("metadata") or {}).get("seed"),
            "dynamic_starter_exit": (sim.get("metadata") or {}).get("dynamic_starter_exit"),
            "away_starter_pa_model_version": (away_vs_home_starter_pa or {}).get("model_version"),
            "home_starter_pa_model_version": (home_vs_away_starter_pa or {}).get("model_version"),
            "away_bullpen_pa_model_version": (away_vs_home_bullpen_pa or {}).get("model_version"),
            "home_bullpen_pa_model_version": (home_vs_away_bullpen_pa or {}).get("model_version"),
        },
        "awayStarterPAOutcomeModel": away_vs_home_starter_pa,
        "homeStarterPAOutcomeModel": home_vs_away_starter_pa,
        "awayBullpenPAOutcomeModel": away_vs_home_bullpen_pa,
        "homeBullpenPAOutcomeModel": home_vs_away_bullpen_pa,
        "metadata": {
            "workspace_version": "model_projection_workspace_v1",
            "generated_from": "model_projections._build_projection_simulation_cards",
            "data_confidence": "low",
            "notes": [
                "Workspace is generated from production model projection inputs.",
                "Lineup-level detail is not fully wired here yet; team offense priors are used where necessary.",
                "Simulation outputs are diagnostic only; canonical /matchups probabilities are the final side probabilities.",
            ],
        },
    }

    return {"away": [away_card, game_total_card], "home": [home_card], "workspace": workspace}


def _projection_offense_inputs(
    *,
    matchup: Dict[str, Any],
    side: str,
    session: Session,
    team_id: Optional[int],
    season: int,
) -> Dict[str, Any]:
    """
    Preserve confirmed player-level offense inputs from matchup generation.

    Exact canonical batter-pitcher artifact discovery requires the individual
    confirmed-lineup rows retained under ``lineup``. Team splits remain the
    fail-open fallback when confirmed player-level inputs are unavailable.
    """

    candidate = matchup.get(
        f"{side}_offense_inputs"
    )

    if isinstance(candidate, dict):
        lineup = candidate.get("lineup")

        if (
            isinstance(lineup, list)
            and len(lineup) > 0
        ):
            return candidate

    return _team_split_inputs(
        session,
        team_id,
        season,
    )


def _materialize_pitcher_matchup_profile_runtime_batch(
    *,
    session: Session,
    matchups: List[Dict[str, Any]],
    game_date: Any,
    event_loader: Any = None,
    batch_builder: Any = None,
) -> Dict[str, Any]:
    """Load terminal evidence once and build all shadow candidates."""
    event_loader = (
        event_loader
        or load_canonical_statcast_events
    )
    batch_builder = (
        batch_builder
        or build_canonical_pitcher_matchup_profile_runtime_batch
    )

    pitcher_ids = tuple(sorted({
        int(pitcher_id)
        for matchup in matchups
        if isinstance(matchup, dict)
        for side in ("away", "home")
        for pitcher_id in [
            matchup.get(
                f"{side}_pitcher_id"
            )
        ]
        if pitcher_id not in (
            None,
            0,
            "",
        )
    }))

    if not pitcher_ids:
        return {
            "candidates": {},
            "diagnostics": {
                "status": "unavailable",
                "blockers": [
                    "no_probable_pitcher_ids",
                ],
                "single_terminal_event_load": False,
                "production_authority": False,
                "production_authority_changed": False,
            },
        }

    window_start = (
        game_date
        - datetime.timedelta(days=90)
    )

    try:
        events, identity = event_loader(
            session,
            StatcastEvent.game_date
            >= window_start,
            StatcastEvent.game_date
            < game_date,
            StatcastEvent.events.isnot(None),
            order_by=(
                StatcastEvent.game_date,
                StatcastEvent.game_pk,
                StatcastEvent.at_bat_number,
                StatcastEvent.pitch_number,
                StatcastEvent.id,
            ),
        )
        result = batch_builder(
            events,
            pitcher_ids=pitcher_ids,
            game_date=game_date,
            window_days=90,
        )

        diagnostics = dict(
            result.get("diagnostics") or {}
        )
        diagnostics.update({
            "single_terminal_event_load": True,
            "terminal_event_count": len(events),
            "identity_diagnostics": dict(
                identity or {}
            ),
            "production_authority": False,
            "production_authority_changed": False,
        })

        return {
            "candidates": dict(
                result.get("candidates") or {}
            ),
            "diagnostics": diagnostics,
        }
    except Exception as exc:
        return {
            "candidates": {},
            "diagnostics": {
                "status": "error",
                "blockers": [
                    "runtime_candidate_batch_failed",
                ],
                "error_type": type(exc).__name__,
                "error": str(exc),
                "single_terminal_event_load": True,
                "production_authority": False,
                "production_authority_changed": False,
            },
        }


def _side_context(
    matchup: Dict[str, Any],
    side: str,
    session: Session,
    season: int,
    game_date: Any,
    pitcher_matchup_profile_candidates: Optional[
        Dict[str, Any]
    ] = None,
    pitcher_matchup_profile_batch_diagnostics: Optional[
        Dict[str, Any]
    ] = None,
) -> Dict[str, Any]:
    pitcher_id = matchup.get(f"{side}_pitcher_id")
    supplied_pitcher_features = (
        matchup.get(f"{side}_pitcher_features")
        or {}
    )
    if not isinstance(
        supplied_pitcher_features,
        dict,
    ):
        supplied_pitcher_features = {}

    if pitcher_id:
        pitcher_profile_source = (
            source_canonical_pitcher_matchup_profile(
                session,
                pitcher_id=int(pitcher_id),
                game_date=game_date,
                matchup_features=(
                    supplied_pitcher_features
                ),
            )
        )
        pitcher_features = (
            pitcher_profile_source[
                "pitcher_features"
            ]
        )
        pitcher_profile_diagnostics = (
            pitcher_profile_source[
                "diagnostics"
            ]
        )
    else:
        pitcher_features = dict(
            supplied_pitcher_features
        )
        pitcher_profile_diagnostics = {
            "schema_version": (
                "canonical_pitcher_matchup_"
                "profile_source_v1"
            ),
            "status": "unavailable",
            "pitcher_id": None,
            "game_date": str(game_date),
            "cutoff_rule": (
                "aggregate_end_date_strictly_"
                "before_game_date"
            ),
            "selected_window": None,
            "selected_end_date": None,
            "days_before_game": None,
            "populated_fields": [],
            "missing_fields": [
                "k_pct",
                "bb_pct",
                "hard_hit_pct",
                "xwoba",
                "xba",
            ],
            "field_provenance": {},
            "source_digest": None,
            "blockers": [
                "missing_pitcher_id",
            ],
        }

    candidate_key = (
        str(int(pitcher_id))
        if pitcher_id
        else None
    )
    pitcher_matchup_profile_candidate = (
        (
            pitcher_matchup_profile_candidates
            or {}
        ).get(candidate_key)
        if candidate_key is not None
        else None
    )

    if not isinstance(
        pitcher_matchup_profile_candidate,
        dict,
    ):
        pitcher_matchup_profile_candidate = {
            "profile_rates": {},
            "diagnostics": {
                "status": "unavailable",
                "pitcher_id": (
                    int(pitcher_id)
                    if pitcher_id
                    else None
                ),
                "blockers": [
                    (
                        "runtime_candidate_unavailable"
                        if pitcher_id
                        else "missing_pitcher_id"
                    ),
                ],
                "production_authority": False,
                "production_authority_changed": False,
                "activation_status": (
                    "shadow_candidate_unavailable"
                ),
            },
        }

    arsenal = matchup.get(
        f"{side}_pitch_arsenal"
    ) or {}
    arsenal_source = (
        "matchup_generator"
        if arsenal
        else "missing_pitch_arsenal"
    )
    if not arsenal and pitcher_id:
        records, arsenal_season = (
            get_pitch_arsenal_with_fallback(
                session,
                int(pitcher_id),
                season,
            )
        )
        arsenal = _arsenal_records_to_dict(
            records
        )
        arsenal_source = (
            f"pitch_arsenal_fallback_{arsenal_season}"
            if arsenal
            else "missing_pitch_arsenal"
        )

    team_id = matchup.get(f"{side}_team_id")
    team_name = matchup.get(
        f"{side}_team_name"
    )
    ctx = {
        "side": side,
        "team_id": team_id,
        "team_name": team_name,
        "pitcher_id": pitcher_id,
        "pitcher_name": matchup.get(
            f"{side}_pitcher_name"
        ),
        "pitcher_features": pitcher_features,
        "pitcher_matchup_profile_source": (
            pitcher_profile_diagnostics
        ),
        "pitcher_matchup_profile_candidate": (
            pitcher_matchup_profile_candidate
        ),
        "pitcher_matchup_profile_runtime_batch": (
            dict(
                pitcher_matchup_profile_batch_diagnostics
                or {}
            )
        ),
        "pitch_arsenal": arsenal,
        "pitch_arsenal_source": arsenal_source,
        "offense_inputs": _projection_offense_inputs(
            matchup=matchup,
            side=side,
            session=session,
            team_id=team_id,
            season=season,
        ),
        "bullpen_inputs": _bullpen_inputs(
            session,
            team_id,
            team_name,
        ),
    }
    ctx["models"] = [
        pitching_volatility_score(ctx["pitcher_features"], ctx["pitch_arsenal"]),
        offensive_firepower_score(ctx["offense_inputs"]),
        bullpen_collapse_index(ctx["bullpen_inputs"]),
        pitch_identity_disruption_score(ctx["pitch_arsenal"], hitter_pitch_rows=[]),
    ]
    return ctx


def _canonical_probability_payload(matchup: Dict[str, Any], projection_sim: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    home_prob = safe_float(matchup.get("home_win_prob"))
    away_prob = safe_float(matchup.get("away_win_prob"))
    legacy_home = safe_float(matchup.get("legacy_home_win_prob"))
    legacy_away = safe_float(matchup.get("legacy_away_win_prob"))
    return {
        "away_win_prob": away_prob,
        "home_win_prob": home_prob,
        "away_win_probability": away_prob,
        "home_win_probability": home_prob,
        "source": "matchups.canonical_matchup_win_probability_v2",
        "model_version": matchup.get("model_version") or "canonical_matchup_win_probability_v2",
        "legacy_model_version": matchup.get("legacy_model_version") or "legacy_matchup_win_probability_v1",
        "legacy_away_win_prob": legacy_away,
        "legacy_home_win_prob": legacy_home,
        "lineup_status": matchup.get("lineup_status"),
        "data_confidence": matchup.get("data_confidence"),
        "missing_inputs": matchup.get("missing_inputs") or [],
        "probability_components": matchup.get("probability_components") or {},
        "pitcher_overview": matchup.get("pitcher_overview") or {},
        "batter_vs_arsenal_summary": matchup.get("batter_vs_arsenal_summary") or {},
        "simulation_diagnostic": {
            "status": "diagnostic_only_not_final_probability",
            "away_win_probability": (projection_sim or {}).get("away_win_probability"),
            "home_win_probability": (projection_sim or {}).get("home_win_probability"),
            "model_version": (projection_sim or {}).get("model_version"),
        } if projection_sim else None,
    }




def _materialize_matchup_pitcher_role_evidence(
    *,
    bullpen_discovery: Any,
    season: int,
    as_of: Any,
    cache: Dict[Any, Any],
    fetcher: Any = None,
    maximum_final_games: int = 10,
) -> Dict[str, Any]:
    """Materialize historical typical roles once per team/date."""

    if fetcher is None:
        fetcher = (
            fetch_canonical_pitcher_role_evidence_source
        )

    if not isinstance(cache, dict):
        raise TypeError("cache must be a dictionary")

    evidence_by_pitcher_id: Dict[str, Any] = {}
    diagnostics_by_side: Dict[str, Any] = {}

    for team_side in ("away", "home"):
        side = getattr(
            bullpen_discovery,
            team_side,
            None,
        )

        try:
            result = fetcher(
                team_id=getattr(
                    side,
                    "team_id",
                    None,
                ),
                season=season,
                as_of=as_of,
                active_roster_records=getattr(
                    side,
                    "active_roster_records",
                    (),
                ),
                maximum_final_games=(
                    maximum_final_games
                ),
                cache=cache,
            )
        except Exception as exc:
            diagnostics_by_side[team_side] = {
                "schema_version": (
                    "canonical_pitcher_role_"
                    "evidence_source_v1"
                ),
                "status": "error",
                "team_side": team_side,
                "error_type":
                    exc.__class__.__name__,
                "error_message": str(exc),
                "pitcher_identifiers_exposed":
                    False,
                "planned_role_claimed": False,
                "future_assignment_inferred":
                    False,
                "database_writes_performed":
                    False,
                "production_authority_changed":
                    False,
            }
            continue

        role_evidence = getattr(
            result,
            "role_evidence",
            {},
        )
        side_evidence = (
            role_evidence.get(
                "evidence_by_pitcher_id",
                {},
            )
            if isinstance(role_evidence, dict)
            else {}
        )

        if isinstance(side_evidence, dict):
            for pitcher_id, record in (
                side_evidence.items()
            ):
                normalized_id = str(
                    pitcher_id
                ).strip()

                if (
                    normalized_id
                    and isinstance(record, dict)
                ):
                    evidence_by_pitcher_id[
                        normalized_id
                    ] = deepcopy(record)

        diagnostics = result.to_diagnostics()
        allowed_keys = (
            "schema_version",
            "status",
            "team_id",
            "as_of_date",
            "lookback_days",
            "maximum_final_games",
            "scheduled_final_game_count",
            "fetched_final_game_count",
            "feed_error_count",
            "resolved_typical_role_count",
            "detected_opener_bulk_pair_count",
            "bounded_game_fetch",
            "simulation_trial_fetches_performed",
            "planned_role_claimed",
            "future_assignment_inferred",
            "database_writes_performed",
            "production_authority_changed",
        )

        diagnostics_by_side[team_side] = {
            key: deepcopy(diagnostics.get(key))
            for key in allowed_keys
        }
        diagnostics_by_side[team_side].update({
            "team_side": team_side,
            "pitcher_identifiers_exposed": False,
        })

    return {
        "schema_version": (
            "canonical_matchup_pitcher_role_"
            "evidence_v1"
        ),
        "status": (
            "materialized"
            if evidence_by_pitcher_id
            else "unavailable"
        ),
        "evidence_by_pitcher_id":
            evidence_by_pitcher_id,
        "source_diagnostics_by_team_side":
            diagnostics_by_side,
        "explicit_pregame_roles_take_precedence":
            True,
        "historical_role_never_claims_today_plan":
            True,
        "simulation_trial_fetches_performed": 0,
        "database_writes_performed": False,
        "production_authority_changed": False,
    }


def _canonical_matchup_bullpen_usage_evidence(
    *,
    bullpen_discovery: Any,
    pitcher_role_evidence: Any,
) -> Dict[str, Dict[str, Any]]:
    """
    Merge canonical role evidence with private roster throwing hand.

    Only pitchers already admitted to the strict canonical bullpen
    membership are returned. Missing usage or fatigue evidence remains
    absent and therefore neutral inside the simulation.
    """

    role_records = (
        pitcher_role_evidence.get(
            "evidence_by_pitcher_id",
            {},
        )
        if isinstance(
            pitcher_role_evidence,
            dict,
        )
        else {}
    )

    evidence: Dict[str, Dict[str, Any]] = {}

    for team_side in ("away", "home"):
        side = getattr(
            bullpen_discovery,
            team_side,
            None,
        )
        eligible_ids = {
            str(value).strip()
            for value in getattr(
                side,
                "bullpen_pitcher_ids",
                (),
            )
            if str(value).strip()
        }

        roster_by_id: Dict[str, Dict[str, Any]] = {}

        for raw_record in getattr(
            side,
            "active_roster_records",
            (),
        ):
            if not isinstance(raw_record, dict):
                try:
                    raw_record = dict(raw_record)
                except Exception:
                    continue

            raw_identifier = (
                raw_record.get("mlb_player_id")
                or raw_record.get("player_id")
                or raw_record.get("pitcher_id")
                or raw_record.get("person_id")
                or raw_record.get("id")
            )
            identifier = str(
                raw_identifier or ""
            ).strip()

            if identifier in eligible_ids:
                roster_by_id[identifier] = dict(
                    raw_record
                )

        for pitcher_id in sorted(eligible_ids):
            role_record = role_records.get(
                pitcher_id,
                {},
            )
            record = (
                deepcopy(role_record)
                if isinstance(role_record, dict)
                else {}
            )
            record["pitcher_id"] = pitcher_id

            roster_record = roster_by_id.get(
                pitcher_id,
                {},
            )
            throwing_hand = str(
                roster_record.get("throws")
                or roster_record.get("handedness")
                or ""
            ).strip().upper()

            if throwing_hand in {"L", "R"}:
                record["throws"] = throwing_hand

            evidence[pitcher_id] = record

    return evidence


def _canonical_matchup_batter_handedness(
    *,
    session: Session,
    lineup_discovery: Any,
) -> Dict[str, str]:
    """
    Read confirmed-lineup batter handedness once before simulation.

    Failure is intentionally soft: missing directory rows produce neutral
    matchup selection rather than suppressing the projection game.
    """

    identifiers = {
        str(value).strip()
        for value in (
            tuple(
                getattr(
                    lineup_discovery,
                    "away_player_ids",
                    (),
                )
            )
            + tuple(
                getattr(
                    lineup_discovery,
                    "home_player_ids",
                    (),
                )
            )
        )
        if str(value).strip()
    }

    integer_ids = []

    for identifier in sorted(identifiers):
        try:
            integer_ids.append(int(identifier))
        except (TypeError, ValueError):
            continue

    if not integer_ids:
        return {}

    try:
        with session.begin_nested():
            rows = (
                session.query(
                    DashboardPlayer.mlb_player_id,
                    DashboardPlayer.bats,
                )
                .filter(
                    DashboardPlayer.mlb_player_id.in_(
                        integer_ids
                    )
                )
                .all()
            )
    except Exception:
        return {}

    handedness: Dict[str, str] = {}

    for player_id, bats in rows:
        normalized_hand = str(
            bats or ""
        ).strip().upper()

        if normalized_hand in {"L", "R", "S"}:
            handedness[str(player_id)] = (
                normalized_hand
            )

    return handedness


def _canonical_pitcher_pool_audit_input(
    bullpen_discovery: Any,
) -> Dict[str, Any]:
    """
    Preserve private same-process eligibility evidence for 6TA.

    CanonicalShadowBullpenDiscovery.to_diagnostics() deliberately
    redacts pitcher identifiers and record-level evidence. This
    adapter is consumed only by the read-only projection audit and
    does not alter or publish the underlying discovery object.
    """

    result: Dict[str, Any] = {}

    for team_side in ("away", "home"):
        side = getattr(
            bullpen_discovery,
            team_side,
            None,
        )

        if side is None:
            result[team_side] = {}
            continue

        eligibility = getattr(
            side,
            "eligibility",
            None,
        )

        result[team_side] = {
            "starter_id": getattr(
                side,
                "starter_id",
                None,
            ),
            "bullpen_pitcher_ids": list(
                getattr(
                    side,
                    "bullpen_pitcher_ids",
                    (),
                )
                or ()
            ),
            "eligibility": (
                deepcopy(eligibility)
                if isinstance(
                    eligibility,
                    dict,
                )
                else {}
            ),
        }

    return result


def _attach_production_shadow_comparison(
    *,
    legacy_result: Dict[str, Any],
    production_execution: Any,
    bullpen_discovery: Any = None,
    pregame_pitcher_evidence_source_coverage: Any = None,
    pitcher_role_evidence: Any = None,
) -> Dict[str, Any]:
    """
    Attach executed canonical material to the existing shadow comparator.

    Blocked or unavailable production executions leave the legacy payload
    unchanged. Successful comparisons remain diagnostic-only and preserve
    legacy authority.
    """

    if not isinstance(legacy_result, dict):
        raise TypeError(
            "legacy_result must be a dictionary"
        )

    material = getattr(
        production_execution,
        "material",
        None,
    )

    if material is None:
        return legacy_result

    result = attach_canonical_shadow(
        legacy_result=legacy_result,
        enabled=True,
        canonical_payload=(
            material.canonical_payload
        ),
        probability_resolution_diagnostics=(
            material
            .probability_resolution_diagnostics
        ),
        canonical_shadow_execution_inputs=(
            material
            .canonical_shadow_execution_inputs
        ),
        pitcher_appearance_sequence_audit=(
            material
            .pitcher_appearance_sequence_audit
        ),
    )

    shadow = (
        result
        .get("diagnostics", {})
        .get("canonical_shadow", {})
    )

    extras_walkoff_activation = (
        evaluate_canonical_extras_walkoff_activation(
            canonical_payload=(
                material.canonical_payload
            ),
            execution_inputs=(
                material
                .canonical_shadow_execution_inputs
            ),
        )
    )
    shadow[
        "canonical_extras_walkoff_activation"
    ] = (
        extras_walkoff_activation.to_diagnostics()
    )

    if isinstance(
        pregame_pitcher_evidence_source_coverage,
        dict,
    ):
        source_coverage = deepcopy(
            pregame_pitcher_evidence_source_coverage
        )
    else:
        source_coverage = {
            "schema_version": (
                "canonical_pregame_pitcher_evidence_"
                "source_coverage_v1"
            ),
            "status": "unavailable",
            "audited": False,
            "blockers": [
                "pregame_pitcher_evidence_source_"
                "coverage_unavailable",
            ],
            "decision": {
                "provider_integration_ready": False,
                "production_activation_allowed": False,
                "recommended_next_slice": (
                    "source_canonical_pregame_"
                    "bullpen_evidence"
                ),
            },
            "database_writes_performed": False,
            "production_authority_changed": False,
        }

    shadow[
        "pregame_pitcher_evidence_source_coverage"
    ] = source_coverage

    try:
        reconciled_projection_rows = (
            reconcile_canonical_pitcher_projection_pool_roles(
                payload=shadow[
                    "player_projections"
                ],
                appearance_audit=(
                    material
                    .pitcher_appearance_sequence_audit
                ),
                bullpen_discovery=(
                    bullpen_discovery
                    if isinstance(
                        bullpen_discovery,
                        dict,
                    )
                    else {}
                ),
                pitcher_role_evidence=(
                    pitcher_role_evidence
                    if isinstance(
                        pitcher_role_evidence,
                        dict,
                    )
                    else {}
                ),
            )
        )
    except Exception as exc:
        pool_role_reconciliation = {
            "schema_version": (
                "canonical_pitcher_projection_"
                "pool_role_reconciliation_v1"
            ),
            "status": "error",
            "error_type": (
                exc.__class__.__name__
            ),
            "error_message": str(exc),
            "typical_role_inference_used": False,
            "unknown_evidence_fails_open": True,
            "projection_rows_preserved": True,
            "database_writes_performed": False,
            "production_authority_changed": False,
        }
    else:
        shadow["player_projections"] = (
            reconciled_projection_rows
        )
        pool_role_reconciliation = (
            reconciled_projection_rows[
                "pitcher_pool_role_reconciliation"
            ]
        )

    shadow[
        "pitcher_projection_pool_role_reconciliation"
    ] = pool_role_reconciliation

    role_source_diagnostics = (
        pitcher_role_evidence.get(
            "source_diagnostics_by_team_side",
            {},
        )
        if isinstance(
            pitcher_role_evidence,
            dict,
        )
        else {}
    )
    shadow[
        "pitcher_role_evidence_source"
    ] = deepcopy(
        role_source_diagnostics
        if isinstance(
            role_source_diagnostics,
            dict,
        )
        else {}
    )

    try:
        appearance_audit = (
            material
            .pitcher_appearance_sequence_audit
        )
        pitching_plans = appearance_audit[
            "pitching_plans"
        ]

        role_and_innings_audit = (
            audit_canonical_pitcher_role_and_innings_attribution(
                projection_payload=(
                    material.canonical_payload
                ),
                away_pitching_plan=(
                    pitching_plans["away"]
                ),
                home_pitching_plan=(
                    pitching_plans["home"]
                ),
            )
        )

        readiness = (
            audit_canonical_pitcher_projection_activation_readiness(
                projection_rows=shadow[
                    "player_projections"
                ],
                appearance_audit=appearance_audit,
                role_and_innings_audit=(
                    role_and_innings_audit
                ),
            )
        )
    except Exception as exc:
        readiness = {
            "schema_version": (
                "canonical_pitcher_projection_"
                "activation_readiness_v1"
            ),
            "status": "error",
            "audited": False,
            "blockers": [
                "readiness_audit_error",
            ],
            "error_type": (
                exc.__class__.__name__
            ),
            "error_message": str(exc),
            "decision": {
                "pitcher_projection_activation_allowed":
                    False,
                "production_activation_allowed":
                    False,
                "recommended_next_slice": (
                    "resolve_canonical_pitcher_"
                    "projection_readiness_blockers"
                ),
            },
            "database_writes_performed": False,
            "production_authority_changed": False,
        }

    shadow[
        "pitcher_projection_activation_readiness"
    ] = readiness

    try:
        activated_projection_rows = (
            apply_canonical_pitcher_projection_authority(
                projection_rows=shadow[
                    "player_projections"
                ],
                readiness=readiness,
            )
        )
    except Exception as exc:
        authority = {
            "schema_version": (
                "canonical_pitcher_projection_"
                "authority_v1"
            ),
            "status": "error",
            "activation_requested": True,
            "readiness_allows_activation":
                False,
            "production_activation": False,
            "fallback_used": True,
            "fallback_reason": (
                "authority_application_error"
            ),
            "error_type": (
                exc.__class__.__name__
            ),
            "error_message": str(exc),
            "authority_scope": (
                "pitcher_rows_only"
            ),
            "database_writes_performed":
                False,
            "production_authority_changed":
                False,
            "authoritative_source": "legacy",
        }
    else:
        shadow["player_projections"] = (
            activated_projection_rows
        )
        authority = (
            activated_projection_rows[
                "pitcher_projection_authority"
            ]
        )

    shadow[
        "pitcher_projection_authority"
    ] = authority

    try:
        pool_and_workload_audit = (
            audit_canonical_pitcher_projection_pool_and_workload_calibration(
                projections=shadow[
                    "player_projections"
                ],
                appearance_audit=(
                    material
                    .pitcher_appearance_sequence_audit
                ),
                bullpen_discovery=(
                    bullpen_discovery
                    if isinstance(
                        bullpen_discovery,
                        dict,
                    )
                    else {}
                ),
            )
        )
    except Exception as exc:
        pool_and_workload_audit = {
            "schema_version": (
                "canonical_pitcher_projection_"
                "pool_and_workload_calibration_v1"
            ),
            "status": "error",
            "audited": False,
            "blockers": [
                "pool_and_workload_audit_error",
            ],
            "error_type": (
                exc.__class__.__name__
            ),
            "error_message": str(exc),
            "safety_checks": {
                "projection_values_unchanged": True,
                "pitcher_pools_unchanged": True,
                "pitching_plans_unchanged": True,
                "event_streams_unchanged": True,
                "database_writes_performed":
                    False,
                "production_authority_changed":
                    False,
            },
            "decision": {
                "pitcher_pool_change_allowed":
                    False,
                "workload_calibration_change_allowed":
                    False,
                "production_activation_allowed":
                    False,
                "recommended_next_slice": (
                    "resolve_canonical_pitcher_"
                    "projection_pool_audit_error"
                ),
            },
            "database_writes_performed": False,
            "production_authority_changed": False,
        }

    shadow[
        "pitcher_projection_pool_and_"
        "workload_calibration"
    ] = pool_and_workload_audit

    return result


def _enrich_game_workspace_player_projections(
    *,
    session: Session,
    shared_simulation: Dict[str, Any],
) -> Dict[str, Any]:
    """
    Enrich attached same-run canonical player rows.

    This function never reruns simulation, changes projection values, or
    changes legacy production authority. Missing or malformed shadow
    projection material fails open and leaves the game payload usable.
    """

    if not isinstance(shared_simulation, dict):
        return shared_simulation

    diagnostics = shared_simulation.get(
        "diagnostics"
    )

    if not isinstance(diagnostics, dict):
        return shared_simulation

    shadow = diagnostics.get(
        "canonical_shadow"
    )

    if not isinstance(shadow, dict):
        return shared_simulation

    player_projections = shadow.get(
        "player_projections"
    )

    if not isinstance(player_projections, dict):
        return shared_simulation

    try:
        shadow["player_projections"] = (
            enrich_canonical_player_projection_rows(
                session=session,
                payload=player_projections,
            )
        )
    except Exception as exc:
        identity_diagnostics = (
            player_projections.setdefault(
                "identity_enrichment",
                {},
            )
        )

        if not isinstance(
            identity_diagnostics,
            dict,
        ):
            identity_diagnostics = {}
            player_projections[
                "identity_enrichment"
            ] = identity_diagnostics

        identity_diagnostics.update(
            {
                "schema_version": (
                    "canonical_player_identity_enrichment_v1"
                ),
                "status": "error",
                "error_type": (
                    exc.__class__.__name__
                ),
                "error_message": str(exc),
                "source": (
                    "dashboard_player_current"
                ),
                "authoritative_source": (
                    "legacy"
                ),
            }
        )

    return shared_simulation


def _fetch_configured_pregame_bullpen_evidence(
    *,
    matchup: Dict[str, Any],
    away_team_id: Any,
    home_team_id: Any,
    environment: Any = None,
    fetcher: Any = None,
) -> Any:
    if not isinstance(matchup, dict):
        raise TypeError(
            "matchup must be a dictionary"
        )

    if environment is None:
        environment = os.environ

    if fetcher is None:
        fetcher = (
            fetch_canonical_pregame_bullpen_evidence
        )

    return fetcher(
        game_pk=(
            matchup.get("game_pk")
            or matchup.get("gamePk")
        ),
        game_time=matchup.get("game_time"),
        away_team_id=away_team_id,
        home_team_id=home_team_id,
        endpoint=environment.get(
            "MLB_PREGAME_BULLPEN_EVIDENCE_URL"
        ),
        provider_name=environment.get(
            "MLB_PREGAME_BULLPEN_"
            "EVIDENCE_PROVIDER"
        ),
        api_token=environment.get(
            "MLB_PREGAME_BULLPEN_"
            "EVIDENCE_TOKEN"
        ),
    )


def build_model_projection_payload(
    session: Session,
    target_date: str,
    *,
    canonical_shadow_context_observer: Optional[
        Any
    ] = None,
) -> Dict[str, Any]:
    if (
        canonical_shadow_context_observer
        is not None
        and not callable(
            canonical_shadow_context_observer
        )
    ):
        raise TypeError(
            "canonical_shadow_context_observer "
            "must be callable or None"
        )

    try:
        date_obj = datetime.datetime.strptime(target_date, "%Y-%m-%d").date()
    except ValueError as exc:
        raise ValueError("date must be YYYY-MM-DD") from exc
    matchups = generate_matchups_for_date(session, target_date)
    pitcher_matchup_profile_runtime_batch = (
        _materialize_pitcher_matchup_profile_runtime_batch(
            session=session,
            matchups=matchups,
            game_date=date_obj,
        )
    )
    pitcher_matchup_profile_candidates = (
        pitcher_matchup_profile_runtime_batch.get(
            "candidates",
            {},
        )
    )
    pitcher_matchup_profile_batch_diagnostics = (
        pitcher_matchup_profile_runtime_batch.get(
            "diagnostics",
            {},
        )
    )
    games: List[Dict[str, Any]] = []
    errors: List[Dict[str, Any]] = []
    pitcher_role_evidence_source_cache: Dict[
        Any,
        Any,
    ] = {}

    for matchup in matchups:
        try:
            away = _side_context(
                matchup,
                "away",
                session,
                date_obj.year,
                date_obj,
                pitcher_matchup_profile_candidates,
                pitcher_matchup_profile_batch_diagnostics,
            )
            home = _side_context(
                matchup,
                "home",
                session,
                date_obj.year,
                date_obj,
                pitcher_matchup_profile_candidates,
                pitcher_matchup_profile_batch_diagnostics,
            )
            simulation_cards = _build_projection_simulation_cards(matchup, away, home)
            away["models"].extend(simulation_cards.get("away", []))
            home["models"].extend(simulation_cards.get("home", []))
            workspace = simulation_cards.get("workspace") or {}

            game_pk = (
                matchup.get("game_pk")
                or matchup.get("gamePk")
            )

            canonical_shadow_lineup_discovery = (
                discover_canonical_shadow_lineups(
                    game_pk=game_pk,
                )
            )

            canonical_pregame_bullpen_provider = (
                _fetch_configured_pregame_bullpen_evidence(
                    matchup=matchup,
                    away_team_id=away.get(
                        "team_id"
                    ),
                    home_team_id=home.get(
                        "team_id"
                    ),
                )
            )

            away_provider_observations = (
                tuple(
                    matchup.get(
                        "away_pregame_pitcher_"
                        "observations"
                    )
                    or ()
                )
                + canonical_pregame_bullpen_provider
                .to_observations(
                    team_side="away"
                )
            )
            home_provider_observations = (
                tuple(
                    matchup.get(
                        "home_pregame_pitcher_"
                        "observations"
                    )
                    or ()
                )
                + canonical_pregame_bullpen_provider
                .to_observations(
                    team_side="home"
                )
            )

            canonical_shadow_bullpen_discovery = (
                discover_canonical_shadow_bullpens(
                    away_team_id=away.get("team_id"),
                    away_team_name=away.get("team_name"),
                    away_starter_id=away.get("pitcher_id"),
                    home_team_id=home.get("team_id"),
                    home_team_name=home.get("team_name"),
                    home_starter_id=home.get("pitcher_id"),
                    season=date_obj.year,
                    pregame_evidence_as_of=(
                        matchup.get("game_time")
                    ),
                    away_pregame_pitching_plan=(
                        matchup.get(
                            "away_pregame_pitching_plan"
                        )
                    ),
                    home_pregame_pitching_plan=(
                        matchup.get(
                            "home_pregame_pitching_plan"
                        )
                    ),
                    away_pregame_provider_observations=(
                        away_provider_observations
                    ),
                    home_pregame_provider_observations=(
                        home_provider_observations
                    ),
                    require_explicit_bullpen_membership=(
                        True
                    ),
                )
            )

            canonical_pitcher_role_evidence = (
                _materialize_matchup_pitcher_role_evidence(
                    bullpen_discovery=(
                        canonical_shadow_bullpen_discovery
                    ),
                    season=date_obj.year,
                    as_of=(
                        matchup.get("game_time")
                        or target_date
                    ),
                    cache=(
                        pitcher_role_evidence_source_cache
                    ),
                    maximum_final_games=10,
                )
            )

            canonical_pitcher_usage_evidence = (
                _canonical_matchup_bullpen_usage_evidence(
                    bullpen_discovery=(
                        canonical_shadow_bullpen_discovery
                    ),
                    pitcher_role_evidence=(
                        canonical_pitcher_role_evidence
                    ),
                )
            )
            canonical_batter_handedness = (
                _canonical_matchup_batter_handedness(
                    session=session,
                    lineup_discovery=(
                        canonical_shadow_lineup_discovery
                    ),
                )
            )

            canonical_readiness_matchup = dict(
                matchup
            )
            canonical_readiness_matchup.update(
                canonical_shadow_lineup_discovery
                .readiness_matchup_fields()
            )
            canonical_readiness_matchup.update(
                canonical_shadow_bullpen_discovery
                .readiness_matchup_fields()
            )

            canonical_shadow_probability_provider_discovery = (
                discover_canonical_shadow_probability_provider(
                    workspace=workspace,
                )
            )

            canonical_shadow_fallback_catalog_discovery = (
                discover_canonical_shadow_fallback_catalog(
                    workspace=workspace,
                    provider=(
                        canonical_shadow_probability_provider_discovery
                        .provider
                    ),
                )
            )

            canonical_shadow_exact_artifact_discovery = (
                discover_canonical_shadow_exact_artifact(
                    away_context=away,
                    home_context=home,
                    workspace=workspace,
                    provider=(
                        canonical_shadow_probability_provider_discovery
                        .provider
                    ),
                )
            )

            canonical_readiness_workspace = dict(
                workspace
            )
            canonical_readiness_workspace.update(
                canonical_shadow_probability_provider_discovery
                .readiness_workspace_fields()
            )
            canonical_readiness_workspace.update(
                canonical_shadow_fallback_catalog_discovery
                .readiness_workspace_fields()
            )
            canonical_readiness_workspace.update(
                canonical_shadow_exact_artifact_discovery
                .readiness_workspace_fields()
            )

            canonical_shadow_bootstrap_readiness = (
                build_canonical_shadow_bootstrap_readiness(
                    game_pk=game_pk,
                    matchup=canonical_readiness_matchup,
                    away_context=away,
                    home_context=home,
                    workspace=canonical_readiness_workspace,
                )
            )

            if (
                canonical_shadow_context_observer
                is not None
            ):
                canonical_shadow_context_observer({
                    "game_pk": game_pk,
                    "game_date": str(
                        matchup.get("game_date")
                        or target_date
                    ),
                    "season": date_obj.year,
                    "matchup": matchup,
                    "away_context": away,
                    "home_context": home,
                    "workspace": workspace,
                    "lineups": (
                        canonical_shadow_lineup_discovery
                    ),
                    "bullpens": (
                        canonical_shadow_bullpen_discovery
                    ),
                    "provider_discovery": (
                        canonical_shadow_probability_provider_discovery
                    ),
                    "exact_artifact_discovery": (
                        canonical_shadow_exact_artifact_discovery
                    ),
                    "fallback_catalog_discovery": (
                        canonical_shadow_fallback_catalog_discovery
                    ),
                    "bootstrap_readiness": (
                        canonical_shadow_bootstrap_readiness
                    ),
                    "bootstrap_ready": bool(
                        canonical_shadow_bootstrap_readiness
                        .get("ready")
                    ),
                    "pitcher_hands_by_id": {
                        str(
                            away.get("pitcher_id")
                        ): (
                            matchup.get(
                                "away_pitcher_hand"
                            )
                            or matchup.get(
                                "away_pitcher_throws"
                            )
                        ),
                        str(
                            home.get("pitcher_id")
                        ): (
                            matchup.get(
                                "home_pitcher_hand"
                            )
                            or matchup.get(
                                "home_pitcher_throws"
                            )
                        ),
                    },
                    "pitcher_profiles_by_id": {
                        str(
                            away.get("pitcher_id")
                        ): dict(
                            workspace.get(
                                "awayPitcherProfile"
                            )
                            or {}
                        ),
                        str(
                            home.get("pitcher_id")
                        ): dict(
                            workspace.get(
                                "homePitcherProfile"
                            )
                            or {}
                        ),
                    },
                    "environment_profile": dict(
                        workspace.get(
                            "environmentProfile"
                        )
                        or {}
                    ),
                })

            canonical_legacy_fallback_execution = (
                run_canonical_production_shadow(
                    game_pk=game_pk,
                    lineups=(
                        canonical_shadow_lineup_discovery
                    ),
                    bullpens=(
                        canonical_shadow_bullpen_discovery
                    ),
                    provider_discovery=(
                        canonical_shadow_probability_provider_discovery
                    ),
                    exact_artifact_discovery=(
                        canonical_shadow_exact_artifact_discovery
                    ),
                    fallback_catalog_discovery=(
                        canonical_shadow_fallback_catalog_discovery
                    ),
                    bootstrap_ready=bool(
                        canonical_shadow_bootstrap_readiness
                        .get("ready")
                    ),
                    pitcher_usage_evidence_by_id=(
                        canonical_pitcher_usage_evidence
                    ),
                    batter_handedness_by_id=(
                        canonical_batter_handedness
                    ),
                )
            )

            canonical_catcher_assignment_discovery = (
                discover_confirmed_catcher_assignments(
                    game_pk=game_pk,
                )
            )

            try:
                production_prior = (
                    load_baserunning_production_prior()
                )

                if not (
                    canonical_catcher_assignment_discovery
                    .ready
                ):
                    raise ValueError(
                        "confirmed catcher assignments "
                        "are unavailable"
                    )

                catcher_ids = {
                    value.team_side: value.catcher_id
                    for value in (
                        canonical_catcher_assignment_discovery
                        .assignments
                    )
                }

                required_runner_ids = tuple(
                    dict.fromkeys(
                        (
                            canonical_shadow_lineup_discovery
                            .away_player_ids
                        )
                        + (
                            canonical_shadow_lineup_discovery
                            .home_player_ids
                        )
                    )
                )

                required_pitcher_ids = tuple(
                    dict.fromkeys(
                        (
                            canonical_shadow_bullpen_discovery
                            .away
                            .starter_id,
                        )
                        + (
                            canonical_shadow_bullpen_discovery
                            .away
                            .bullpen_pitcher_ids
                        )
                        + (
                            canonical_shadow_bullpen_discovery
                            .home
                            .starter_id,
                        )
                        + (
                            canonical_shadow_bullpen_discovery
                            .home
                            .bullpen_pitcher_ids
                        )
                    )
                )

                canonical_baserunning_evidence_discovery = (
                    production_prior.discover_matchup(
                        required_runner_ids=(
                            required_runner_ids
                        ),
                        required_pitcher_ids=(
                            required_pitcher_ids
                        ),
                        away_catcher_id=(
                            catcher_ids["away"]
                        ),
                        home_catcher_id=(
                            catcher_ids["home"]
                        ),
                        allow_fallback_profiles=True,
                    )
                )
            except Exception as baserunning_exc:
                canonical_baserunning_evidence_discovery = (
                    CanonicalShadowBaserunningEvidenceDiscovery(
                        status="error",
                        error_message=str(
                            baserunning_exc
                        ),
                    )
                )

            canonical_production_trial_policy = (
                build_canonical_production_trial_policy()
            )

            canonical_live_baserunning_pair = (
                execute_live_baserunning_shadow_pair(
                    game_pk=game_pk,
                    game_date=str(
                        matchup.get("game_date")
                        or target_date
                    ),
                    lineups=(
                        canonical_shadow_lineup_discovery
                    ),
                    bullpens=(
                        canonical_shadow_bullpen_discovery
                    ),
                    provider_discovery=(
                        canonical_shadow_probability_provider_discovery
                    ),
                    exact_artifact_discovery=(
                        canonical_shadow_exact_artifact_discovery
                    ),
                    fallback_catalog_discovery=(
                        canonical_shadow_fallback_catalog_discovery
                    ),
                    bootstrap_ready=bool(
                        canonical_shadow_bootstrap_readiness
                        .get("ready")
                    ),
                    baserunning_evidence_discovery=(
                        canonical_baserunning_evidence_discovery
                    ),
                    simulation_count=(
                        canonical_production_trial_policy
                        .simulation_count
                    ),
                )
            )

            canonical_baserunning_activation = (
                activate_calibrated_baserunning(
                    fallback_execution=(
                        canonical_legacy_fallback_execution
                    ),
                    paired_execution=(
                        canonical_live_baserunning_pair
                    ),
                )
            )

            canonical_production_shadow_execution = (
                canonical_baserunning_activation
                .production_execution
            )

            workspace[
                "canonicalShadowLineupDiscovery"
            ] = (
                canonical_shadow_lineup_discovery
                .to_diagnostics()
            )

            workspace[
                "canonicalShadowBullpenDiscovery"
            ] = (
                canonical_shadow_bullpen_discovery
                .to_diagnostics()
            )

            workspace[
                "canonicalPregameBullpenEvidenceProvider"
            ] = (
                canonical_pregame_bullpen_provider
                .to_diagnostics()
            )

            workspace[
                "canonicalShadowProbabilityProviderDiscovery"
            ] = (
                canonical_shadow_probability_provider_discovery
                .to_diagnostics()
            )

            workspace[
                "canonicalShadowFallbackCatalogDiscovery"
            ] = (
                canonical_shadow_fallback_catalog_discovery
                .to_diagnostics()
            )

            workspace[
                "canonicalShadowExactArtifactDiscovery"
            ] = (
                canonical_shadow_exact_artifact_discovery
                .to_diagnostics()
            )

            workspace[
                "canonicalProductionTrialPolicy"
            ] = (
                canonical_production_trial_policy
                .to_diagnostics()
            )

            workspace[
                "canonicalShadowProductionExecution"
            ] = (
                canonical_production_shadow_execution
                .to_diagnostics()
            )

            workspace[
                "canonicalShadowBootstrapReadiness"
            ] = canonical_shadow_bootstrap_readiness

            try:
                shared_simulation = build_shared_game_simulation(
                    game_pk=matchup.get("game_pk") or matchup.get("gamePk"),
                    config={
                        "date": target_date,
                        "simulation_count": 3000,
                        "seed": 42,
                        "starter_exit_enabled": True,
                        "source_route": "/models/projections",
                        "matchup": {"raw": matchup, "game_date": matchup.get("game_date") or target_date},
                    },
                )
            except Exception as shared_exc:
                shared_simulation = {"status": "error", "error": str(shared_exc), "meta": {"game_pk": matchup.get("game_pk") or matchup.get("gamePk"), "source_route": "/models/projections"}}

            try:
                pregame_pitcher_evidence_source_coverage = (
                    audit_canonical_pregame_pitcher_evidence_source_coverage(
                        matchup=matchup,
                        bullpen_discovery=(
                            canonical_shadow_bullpen_discovery
                        ),
                    )
                )
            except Exception as source_coverage_exc:
                pregame_pitcher_evidence_source_coverage = {
                    "schema_version": (
                        "canonical_pregame_pitcher_"
                        "evidence_source_coverage_v1"
                    ),
                    "status": "error",
                    "audited": False,
                    "blockers": [
                        "source_coverage_audit_error",
                    ],
                    "error_type": (
                        source_coverage_exc
                        .__class__.__name__
                    ),
                    "error_message": str(
                        source_coverage_exc
                    ),
                    "decision": {
                        "provider_integration_ready":
                            False,
                        "production_activation_allowed":
                            False,
                        "recommended_next_slice": (
                            "source_canonical_pregame_"
                            "bullpen_evidence"
                        ),
                    },
                    "database_writes_performed": False,
                    "production_authority_changed": False,
                }

            shared_simulation = (
                _attach_production_shadow_comparison(
                    legacy_result=shared_simulation,
                    production_execution=(
                        canonical_production_shadow_execution
                    ),
                    bullpen_discovery=(
                        _canonical_pitcher_pool_audit_input(
                            canonical_shadow_bullpen_discovery
                        )
                    ),
                    pregame_pitcher_evidence_source_coverage=(
                        pregame_pitcher_evidence_source_coverage
                    ),
                    pitcher_role_evidence=(
                        canonical_pitcher_role_evidence
                    ),
                )
            )

            shared_simulation = (
                apply_calibrated_baserunning_production_authority(
                    legacy_result=shared_simulation,
                    activation=(
                        canonical_baserunning_activation
                    ),
                )
            )

            if isinstance(shared_simulation, dict):
                baserunning_diagnostics = (
                    shared_simulation.setdefault(
                        "diagnostics",
                        {},
                    )
                )

                if isinstance(
                    baserunning_diagnostics,
                    dict,
                ):
                    baserunning_diagnostics[
                        "canonical_catcher_assignment_discovery"
                    ] = (
                        canonical_catcher_assignment_discovery
                        .to_diagnostics()
                    )
                    baserunning_diagnostics[
                        "canonical_baserunning_evidence_discovery"
                    ] = (
                        canonical_baserunning_evidence_discovery
                        .to_diagnostics()
                    )
                    baserunning_diagnostics[
                        "canonical_live_baserunning_shadow"
                    ] = (
                        canonical_live_baserunning_pair
                        .to_diagnostics()
                    )

            shared_simulation = (
                _enrich_game_workspace_player_projections(
                    session=session,
                    shared_simulation=shared_simulation,
                )
            )

            activation_diagnostics = (
                canonical_baserunning_activation
                .to_diagnostics()
            )
            observation = (
                canonical_live_baserunning_pair
                .observation
            )
            observation_diagnostics = (
                observation.to_diagnostics()
            )
            shared_meta = (
                shared_simulation.get("meta", {})
                if isinstance(shared_simulation, dict)
                else {}
            )
            if not isinstance(shared_meta, dict):
                shared_meta = {}

            monitoring_eligibility = (
                evaluate_canonical_production_monitoring_eligibility(
                    game_date=str(
                        matchup.get("game_date")
                        or target_date
                    ),
                    game_status=str(
                        matchup.get("status") or ""
                    ),
                    activation_requested=bool(
                        activation_diagnostics.get(
                            "activation_requested"
                        )
                    ),
                    production_activation=bool(
                        activation_diagnostics.get(
                            "production_activation"
                        )
                    ),
                    selected_execution=str(
                        activation_diagnostics.get(
                            "selected_execution"
                        )
                        or ""
                    ),
                    observation_ready=(
                        observation.ready
                    ),
                    input_parity_verified=(
                        observation.input_parity_verified
                    ),
                    seed_parity_verified=(
                        observation.seed_parity_verified
                    ),
                    authoritative_source=str(
                        shared_meta.get(
                            "authoritative_source"
                        )
                        or ""
                    ),
                )
            )

            monitoring_record = None
            if monitoring_eligibility["eligible"]:
                monitoring_record = (
                    CanonicalBaserunningProductionMonitoringRecord(
                        game_pk=game_pk,
                        game_date=str(
                            matchup.get("game_date")
                            or target_date
                        ),
                        canonical_run_id=str(
                            shared_meta.get(
                                "canonical_run_id"
                            )
                        ),
                        observation_digest=(
                            observation.digest
                        ),
                        paired_context_digest=(
                            observation
                            .paired_context_digest
                        ),
                        calibrated_transform_digest=(
                            observation
                            .calibrated_transform_digest
                        ),
                        simulation_count=int(
                            shared_meta.get(
                                "simulation_count"
                            )
                        ),
                        status=observation.status,
                        ready=observation.ready,
                        production_activation=True,
                        authoritative_source=(
                            CANONICAL_BASERUNNING_PRODUCTION_AUTHORITY
                        ),
                        payload={
                            "observation": (
                                observation_diagnostics
                            ),
                            "activation": (
                                activation_diagnostics
                            ),
                            "production_execution": (
                                canonical_production_shadow_execution
                                .to_diagnostics()
                            ),
                            "trial_policy": (
                                canonical_production_trial_policy
                                .to_diagnostics()
                            ),
                            "evidence_discovery": (
                                canonical_baserunning_evidence_discovery
                                .to_diagnostics()
                            ),
                        },
                    )
                )

            production_monitoring = (
                materialize_canonical_baserunning_production_monitoring(
                    session,
                    eligibility=monitoring_eligibility,
                    record=monitoring_record,
                )
            )
            settlement_summary = (
                _load_production_settlement_diagnostics(
                    session
                )
            )
            calibration_finalization = (
                settlement_summary.pop(
                    "_calibration_finalization"
                )
            )
            production_monitoring[
                "settlement"
            ] = settlement_summary
            production_monitoring[
                "calibration_finalization"
            ] = calibration_finalization
            workspace[
                "canonicalBaserunningProductionMonitoring"
            ] = production_monitoring

            if isinstance(shared_simulation, dict):
                monitoring_diagnostics = (
                    shared_simulation.setdefault(
                        "diagnostics",
                        {},
                    )
                )
                if isinstance(
                    monitoring_diagnostics,
                    dict,
                ):
                    monitoring_diagnostics[
                        "canonical_baserunning_"
                        "production_monitoring"
                    ] = production_monitoring

            if isinstance(shared_simulation, dict):
                shared_diagnostics = (
                    shared_simulation.setdefault(
                        "diagnostics",
                        {},
                    )
                )

                if not isinstance(
                    shared_diagnostics,
                    dict,
                ):
                    shared_diagnostics = {
                        "legacy_diagnostics": (
                            shared_diagnostics
                        )
                    }
                    shared_simulation[
                        "diagnostics"
                    ] = shared_diagnostics

                shared_diagnostics[
                    "canonical_shadow_lineup_discovery"
                ] = (
                    canonical_shadow_lineup_discovery
                    .to_diagnostics()
                )

                shared_diagnostics[
                    "canonical_shadow_bullpen_discovery"
                ] = (
                    canonical_shadow_bullpen_discovery
                    .to_diagnostics()
                )

                shared_diagnostics[
                    "canonical_shadow_probability_provider_discovery"
                ] = (
                    canonical_shadow_probability_provider_discovery
                    .to_diagnostics()
                )

                shared_diagnostics[
                    "canonical_shadow_fallback_catalog_discovery"
                ] = (
                    canonical_shadow_fallback_catalog_discovery
                    .to_diagnostics()
                )

                shared_diagnostics[
                    "canonical_shadow_exact_artifact_discovery"
                ] = (
                    canonical_shadow_exact_artifact_discovery
                    .to_diagnostics()
                )

                shared_diagnostics[
                    "canonical_shadow_production_execution"
                ] = (
                    canonical_production_shadow_execution
                    .to_diagnostics()
                )

                shared_diagnostics[
                    "canonical_shadow_bootstrap_readiness"
                ] = canonical_shadow_bootstrap_readiness

            shared_outputs = shared_simulation.get("derived_outputs", {}) if isinstance(shared_simulation, dict) else {}
            shared_game_sim = shared_outputs.get("game_simulation", {}) or {}
            shared_bullpen_sim = shared_outputs.get("bullpen_adjusted_game_simulation", {}) or {}
            projection_sim = shared_bullpen_sim or shared_game_sim
            canonical_probabilities = _canonical_probability_payload(matchup, projection_sim=projection_sim)
            canonical_game_context = build_canonical_game_context(matchup, projection_sim=projection_sim)
            workspace["canonicalMatchupProbability"] = canonical_probabilities
            workspace["canonicalGameContext"] = canonical_game_context
            workspace["sharedSimulationDiagnostics"] = {
                "status": "diagnostic_only_not_final_probability",
                "source": "sharedSimulation.derived_outputs",
                "selected_simulation_model_version": projection_sim.get("model_version") if isinstance(projection_sim, dict) else None,
                "away_diagnostic_win_probability": projection_sim.get("away_win_probability") if isinstance(projection_sim, dict) else None,
                "home_diagnostic_win_probability": projection_sim.get("home_win_probability") if isinstance(projection_sim, dict) else None,
            }

            games.append({
                "game_pk": matchup.get("game_pk"),
                "game_state_realism": (
                    _build_game_state_realism_diagnostics(
                        shared_simulation
                    )
                ),
                "canonical_shadow_lineup_discovery": (
                    canonical_shadow_lineup_discovery
                    .to_diagnostics()
                ),
                "canonical_shadow_bullpen_discovery": (
                    canonical_shadow_bullpen_discovery
                    .to_diagnostics()
                ),
                "canonical_shadow_probability_provider_discovery": (
                    canonical_shadow_probability_provider_discovery
                    .to_diagnostics()
                ),
                "canonical_shadow_fallback_catalog_discovery": (
                    canonical_shadow_fallback_catalog_discovery
                    .to_diagnostics()
                ),
                "canonical_shadow_exact_artifact_discovery": (
                    canonical_shadow_exact_artifact_discovery
                    .to_diagnostics()
                ),
                "canonical_shadow_production_execution": (
                    canonical_production_shadow_execution
                    .to_diagnostics()
                ),
                "canonical_catcher_assignment_discovery": (
                    canonical_catcher_assignment_discovery
                    .to_diagnostics()
                ),
                "canonical_baserunning_evidence_discovery": (
                    canonical_baserunning_evidence_discovery
                    .to_diagnostics()
                ),
                "canonical_live_baserunning_shadow": (
                    canonical_live_baserunning_pair
                    .to_diagnostics()
                ),
                "canonical_baserunning_activation": (
                    canonical_baserunning_activation
                    .to_diagnostics()
                ),
                "canonical_shadow_bootstrap_readiness": (
                    canonical_shadow_bootstrap_readiness
                ),
                "sharedSimulation": shared_simulation,
                "game_date": matchup.get("game_date") or target_date,
                "game_time": matchup.get("game_time"),
                "status": matchup.get("status"),
                "venue": matchup.get("venue"),
                "weather": matchup.get("weather"),
                "away_team": {"id": away.get("team_id"), "name": away.get("team_name")},
                "home_team": {"id": home.get("team_id"), "name": home.get("team_name")},
                "away_pitcher": {"id": away.get("pitcher_id"), "name": away.get("pitcher_name")},
                "home_pitcher": {"id": home.get("pitcher_id"), "name": home.get("pitcher_name")},
                "away_win_prob": canonical_probabilities.get("away_win_prob"),
                "home_win_prob": canonical_probabilities.get("home_win_prob"),
                "away_win_probability": canonical_probabilities.get("away_win_probability"),
                "home_win_probability": canonical_probabilities.get("home_win_probability"),
                "model_version": canonical_probabilities.get("model_version"),
                "legacy_model_version": canonical_probabilities.get("legacy_model_version"),
                "legacy_away_win_prob": canonical_probabilities.get("legacy_away_win_prob"),
                "legacy_home_win_prob": canonical_probabilities.get("legacy_home_win_prob"),
                "probability_components": canonical_probabilities.get("probability_components"),
                "lineup_status": canonical_probabilities.get("lineup_status"),
                "data_confidence": canonical_probabilities.get("data_confidence"),
                "missing_inputs": canonical_probabilities.get("missing_inputs"),
                "pitcher_overview": canonical_probabilities.get("pitcher_overview"),
                "batter_vs_arsenal_summary": canonical_probabilities.get("batter_vs_arsenal_summary"),
                "main_matchup_probabilities": canonical_probabilities,
                "canonical_game_context": canonical_game_context,
                "teams": {"away": away, "home": home},
                "workspace": workspace,
            })
        except Exception as exc:
            errors.append({"game_pk": matchup.get("game_pk"), "error": str(exc)})
    return {
        "date": target_date,
        "count": len(games),
        "games": games,
        "errors": errors,
        "source_notes": [
            "Daily games are loaded through main generate_matchups_for_date.",
            "home_win_prob and away_win_prob are canonical v2 from /matchups.",
            "Simulation outputs remain available as diagnostics and do not define final side probability.",
            "Missing inputs are returned explicitly and are not fabricated.",
            "canonical_game_context is the shared game-level object for side, projected runs, pitcher/team components, and data-quality context.",
        ],
    }
