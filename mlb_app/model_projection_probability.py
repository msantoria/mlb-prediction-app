from __future__ import annotations

import datetime
from typing import Any, Dict, Optional


def _safe_float(value: Any) -> Optional[float]:
    try:
        if value is None or value == "":
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def _first_dict(*values: Any) -> Dict[str, Any]:
    for value in values:
        if isinstance(value, dict) and value:
            return value
    return {}


def _derived_outputs(shared_simulation: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    if not isinstance(shared_simulation, dict):
        return {}
    outputs = shared_simulation.get("derived_outputs")
    return outputs if isinstance(outputs, dict) else {}


def select_model_projection_simulation(shared_simulation: Optional[Dict[str, Any]]) -> tuple[Dict[str, Any], Optional[str]]:
    """Select the Model Projections simulation output used for displayed win probability.

    This mirrors the frontend ModelProjectionsPage behavior: prefer bullpen-adjusted
    game simulation, then fall back to the base game simulation. It does not use
    canonical matchup probability unless the caller explicitly falls back later.
    """
    outputs = _derived_outputs(shared_simulation)
    bullpen_adjusted = outputs.get("bullpen_adjusted_game_simulation")
    if isinstance(bullpen_adjusted, dict) and bullpen_adjusted:
        return bullpen_adjusted, "sharedSimulation.derived_outputs.bullpen_adjusted_game_simulation"
    game_simulation = outputs.get("game_simulation")
    if isinstance(game_simulation, dict) and game_simulation:
        return game_simulation, "sharedSimulation.derived_outputs.game_simulation"
    return {}, None


def build_model_projection_probability(
    *,
    game_pk: Any = None,
    date: Optional[str] = None,
    shared_simulation: Optional[Dict[str, Any]] = None,
    matchup: Optional[Dict[str, Any]] = None,
    generated_at: Optional[str] = None,
) -> Dict[str, Any]:
    """Build the normalized displayed/default win-probability contract.

    Primary source: Model Projections shared derived simulation output.
    Fallback source: canonical matchup fields, explicitly marked as fallback.
    """
    matchup = matchup or {}
    selected_sim, source_path = select_model_projection_simulation(shared_simulation)
    home_prob = _safe_float(selected_sim.get("home_win_probability"))
    away_prob = _safe_float(selected_sim.get("away_win_probability"))
    if home_prob is not None and away_prob is not None and source_path:
        source_meta = _first_dict(selected_sim.get("metadata"), selected_sim.get("meta"))
        model_version = selected_sim.get("model_version") or source_meta.get("model_version") or source_meta.get("simulation_model_version")
        return {
            "home_win_probability": home_prob,
            "away_win_probability": away_prob,
            "home_win_prob": home_prob,
            "away_win_prob": away_prob,
            "source": "model_projections",
            "source_path": source_path,
            "model_version": model_version or "model_projections_shared_simulation",
            "generated_at": generated_at or datetime.datetime.utcnow().isoformat(timespec="seconds") + "Z",
            "game_pk": game_pk,
            "date": date,
            "fallback_source": None,
            "is_fallback": False,
        }

    canonical_home = _safe_float(matchup.get("home_win_prob"))
    if canonical_home is None:
        canonical_home = _safe_float(matchup.get("home_win_probability"))
    canonical_away = _safe_float(matchup.get("away_win_prob"))
    if canonical_away is None:
        canonical_away = _safe_float(matchup.get("away_win_probability"))
    missing_reason = "sharedSimulation derived outputs missing"
    if source_path and (home_prob is None or away_prob is None):
        missing_reason = "sharedSimulation derived outputs missing home/away win probability"
    return {
        "home_win_probability": canonical_home,
        "away_win_probability": canonical_away,
        "home_win_prob": canonical_home,
        "away_win_prob": canonical_away,
        "source": "fallback:canonical_matchup_win_probability_v2",
        "source_path": None,
        "model_version": matchup.get("model_version") or "canonical_matchup_win_probability_v2",
        "generated_at": generated_at or datetime.datetime.utcnow().isoformat(timespec="seconds") + "Z",
        "game_pk": game_pk,
        "date": date,
        "fallback_source": "canonical_matchup_win_probability_v2",
        "is_fallback": True,
        "missing_model_projection_reason": missing_reason,
    }


__all__ = [
    "build_model_projection_probability",
    "select_model_projection_simulation",
]
