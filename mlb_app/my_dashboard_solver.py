from __future__ import annotations

import datetime as dt
from typing import Any, Callable, Dict, List, Optional, Tuple

from .ai_data_assistant import (
    build_pitcher_lean_context,
    build_stored_365_sweep_context,
    coalesce,
    safe_float,
    score_projection_edges,
)
from .ai_data_assistant_performance import apply_performance_patch, cached_build_model_projection_payload
from .my_dashboard_dataset_runtime import mlb_business_date

SUPPORTED_COMPONENTS = {"hitters", "pitchers", "teams", "totals", "overall_players"}

COMPONENT_TITLES = {
    "hitters": "My Top Hitters Today",
    "pitchers": "My Top Pitchers Today",
    "teams": "My Top Teams Today",
    "totals": "My Top Totals Today",
    "overall_players": "My Top Overall Players Today",
}

CONFIDENCE_ORDER = {"low": 1, "medium": 2, "high": 3}


def today() -> str:
    return mlb_business_date().isoformat()


def confidence_label(value: Any) -> str:
    if isinstance(value, str):
        return value.lower()
    num = safe_float(value)
    if num is None:
        return "low"
    if num >= 0.72:
        return "high"
    if num >= 0.5:
        return "medium"
    return "low"


def rounded(value: Any, digits: int = 3) -> Optional[float]:
    num = safe_float(value)
    return round(num, digits) if num is not None else None


def build_chart_data(metrics: Dict[str, Any]) -> Dict[str, Any]:
    labels: List[str] = []
    values: List[float] = []
    for key, value in metrics.items():
        num = safe_float(value)
        if num is None:
            continue
        labels.append(key)
        values.append(round(num, 3))
    return {"labels": labels[:8], "values": values[:8]}


def dedupe_ranked_items(items: List[Dict[str, Any]], key_fn: Callable[[Dict[str, Any]], str], limit: int = 10) -> List[Dict[str, Any]]:
    best_by_key: Dict[str, Dict[str, Any]] = {}
    for item in items:
        key = key_fn(item)
        if not key:
            continue
        item["dedupe_key"] = key
        existing = best_by_key.get(key)
        if existing is None or (safe_float(item.get("score")) or -999) > (safe_float(existing.get("score")) or -999):
            if existing and existing.get("best_pitch_angles") and item.get("best_pitch_angles"):
                item["best_pitch_angles"] = merge_pitch_angles(existing.get("best_pitch_angles"), item.get("best_pitch_angles"))
            best_by_key[key] = item
        elif item.get("best_pitch_angles") and existing is not None:
            existing["best_pitch_angles"] = merge_pitch_angles(existing.get("best_pitch_angles"), item.get("best_pitch_angles"))
    ranked = sorted(best_by_key.values(), key=lambda row: safe_float(row.get("score")) or -999, reverse=True)[:limit]
    for idx, row in enumerate(ranked, start=1):
        row["rank"] = idx
    return ranked


def merge_pitch_angles(a: Any, b: Any) -> List[Dict[str, Any]]:
    rows = []
    seen = set()
    for angle in list(a or []) + list(b or []):
        if not isinstance(angle, dict):
            continue
        key = angle.get("pitch_type") or angle.get("pitch_name") or angle.get("reason")
        if key in seen:
            continue
        rows.append(angle)
        seen.add(key)
    return sorted(rows, key=lambda row: safe_float(row.get("score")) or -999, reverse=True)[:3]


def projection_payload(session, date: str) -> Dict[str, Any]:
    apply_performance_patch()
    try:
        return cached_build_model_projection_payload(session, date) or {}
    except Exception:
        return {}


def normalize_filter_payload(filters: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    if not isinstance(filters, dict):
        return {}
    normalized: Dict[str, Any] = {}
    for key in [
        "search_text",
        "team",
        "opponent",
        "category",
        "entity_type",
        "player_type",
        "pitch_type",
        "pitch_name",
        "source",
    ]:
        value = filters.get(key)
        if value not in (None, ""):
            normalized[key] = str(value).strip()
    for key in ["confidence", "min_confidence"]:
        value = filters.get(key)
        if value not in (None, ""):
            normalized["min_confidence"] = str(value).strip().lower()
    for key in ["min_score", "max_score"]:
        value = safe_float(filters.get(key))
        if value is not None:
            normalized[key] = value
    metrics = filters.get("metrics") if isinstance(filters.get("metrics"), dict) else {}
    normalized_metrics: Dict[str, Dict[str, float]] = {}
    for metric, rules in metrics.items():
        if not isinstance(rules, dict):
            continue
        entry: Dict[str, float] = {}
        min_value = safe_float(rules.get("min"))
        max_value = safe_float(rules.get("max"))
        if min_value is not None:
            entry["min"] = min_value
        if max_value is not None:
            entry["max"] = max_value
        if entry:
            normalized_metrics[str(metric)] = entry
    if normalized_metrics:
        normalized["metrics"] = normalized_metrics
    weights = filters.get("weights") if isinstance(filters.get("weights"), dict) else {}
    normalized_weights: Dict[str, float] = {}
    for metric, value in weights.items():
        weight = safe_float(value)
        if weight is None:
            continue
        normalized_weights[str(metric)] = max(0.0, min(2.0, weight))
    if normalized_weights:
        normalized["weights"] = normalized_weights
    return normalized


def text_blob(item: Dict[str, Any]) -> str:
    parts = [
        item.get("entity_name"),
        item.get("team"),
        item.get("opponent"),
        item.get("primary_reason"),
        item.get("category"),
        item.get("entity_type"),
        item.get("player_type"),
        item.get("pitch_type"),
        item.get("pitch_name"),
        item.get("source"),
    ]
    parts.extend(item.get("reasoning") or [])
    for angle in item.get("best_pitch_angles") or []:
        if isinstance(angle, dict):
            parts.extend([angle.get("pitch_type"), angle.get("pitch_name"), angle.get("reason")])
    return " ".join(str(part) for part in parts if part not in (None, "")).lower()


def passes_basic_filters(item: Dict[str, Any], filters: Dict[str, Any]) -> bool:
    score = safe_float(item.get("score"))
    if filters.get("min_score") is not None and (score is None or score < filters["min_score"]):
        return False
    if filters.get("max_score") is not None and (score is None or score > filters["max_score"]):
        return False
    min_conf = filters.get("min_confidence")
    if min_conf and CONFIDENCE_ORDER.get(confidence_label(item.get("confidence")), 0) < CONFIDENCE_ORDER.get(min_conf, 0):
        return False
    for key in ["team", "opponent", "source"]:
        value = filters.get(key)
        if value and value.lower() not in str(item.get(key) or "").lower():
            return False
    for key in ["category", "entity_type", "player_type"]:
        value = filters.get(key)
        if value and str(item.get(key) or "").lower() != value.lower():
            return False
    pitch_filter = filters.get("pitch_type") or filters.get("pitch_name")
    if pitch_filter:
        pitch_blob = f"{item.get('pitch_type') or ''} {item.get('pitch_name') or ''}".lower()
        if pitch_filter.lower() not in pitch_blob:
            return False
    search = filters.get("search_text")
    if search and search.lower() not in text_blob(item):
        return False
    return True


def passes_metric_filters(item: Dict[str, Any], metric_filters: Dict[str, Dict[str, float]], warnings: List[str]) -> bool:
    metrics = item.get("metrics") or {}
    for metric, rules in metric_filters.items():
        if metric not in metrics or safe_float(metrics.get(metric)) is None:
            return False
        value = safe_float(metrics.get(metric))
        if rules.get("min") is not None and value < rules["min"]:
            return False
        if rules.get("max") is not None and value > rules["max"]:
            return False
    return True


def normalize_metric_for_weight(metric_name: str, metric_value: Any) -> float:
    value = safe_float(metric_value)
    if value is None:
        return 0.0
    name = metric_name.lower()
    if "ev" in name or "velocity" in name:
        return max(-1.0, min(1.0, (value - 88.0) / 12.0))
    if "la" in name or "launch angle" in name:
        return max(-1.0, min(1.0, 1.0 - abs(value - 16.0) / 25.0))
    if "pitches seen" in name or name == "pa":
        return max(-1.0, min(1.0, value / 60.0))
    if "total" in name:
        return max(-1.0, min(1.0, (value - 8.5) / 4.0))
    if "score" in name or "edge" in name or "diff" in name:
        return max(-1.0, min(1.0, value))
    if "bb" in name:
        return max(-1.0, min(1.0, (0.085 - value) * 8.0))
    if "allowed" in name and ("xwoba" in name or "hardhit" in name):
        return max(-1.0, min(1.0, (0.34 - value) * 5.0))
    return max(-1.0, min(1.0, value))


def apply_weight_overrides(item: Dict[str, Any], weights: Dict[str, float]) -> Dict[str, Any]:
    if not weights:
        return item
    updated = dict(item)
    metrics = updated.get("metrics") or {}
    base_score = safe_float(updated.get("base_score"))
    if base_score is None:
        base_score = safe_float(updated.get("score")) or 0.0
    adjusted = base_score
    explanations: List[str] = []
    for metric_name, weight in weights.items():
        if metric_name not in metrics:
            continue
        normalized_metric = normalize_metric_for_weight(metric_name, metrics.get(metric_name))
        adjusted += normalized_metric * (weight - 1.0) * 0.25
        if abs(weight - 1.0) >= 0.01:
            verb = "emphasized" if weight > 1.0 else "deemphasized"
            explanations.append(f"{metric_name} {verb} at {round(weight, 2)}")
    updated["base_score"] = rounded(base_score)
    updated["adjusted_score"] = rounded(adjusted)
    updated["score"] = rounded(adjusted)
    updated["weight_explanation"] = explanations
    return updated


def available_filters_for_component(component: str, items: Optional[List[Dict[str, Any]]] = None) -> Dict[str, Any]:
    metric_names = set()
    categories = set()
    player_types = set()
    teams = set()
    opponents = set()
    pitch_types = set()
    for item in items or []:
        metric_names.update((item.get("metrics") or {}).keys())
        if item.get("category"):
            categories.add(item.get("category"))
        if item.get("player_type"):
            player_types.add(item.get("player_type"))
        if item.get("team"):
            teams.add(str(item.get("team")))
        if item.get("opponent"):
            opponents.add(str(item.get("opponent")))
        if item.get("pitch_type") or item.get("pitch_name"):
            pitch_types.add(str(item.get("pitch_name") or item.get("pitch_type")))
    default_metrics = {
        "hitters": ["xwOBA", "xBA", "EV", "LA", "HardHit", "Usage", "Pitcher xwOBA", "Pitches Seen", "PA"],
        "pitchers": ["K%", "BB%", "xwOBA Allowed", "HardHit Allowed", "Opp K%", "Opp ISO", "Score"],
        "teams": ["Edge Score", "Win Edge", "Run Diff", "ISO", "OBP", "SLG"],
        "totals": ["Projected Total", "Raw Total", "Run Index", "Score"],
        "overall_players": sorted(metric_names) or ["Score"],
    }
    metrics = sorted(metric_names) if metric_names else default_metrics.get(component, [])
    component_defaults = {
        "hitters": {
            "basic": ["search_text", "team", "opponent", "min_confidence", "min_score", "max_score", "pitch_type", "source", "entity_type", "player_type"],
            "suggested_metric_filters": ["EV", "LA", "Pitches Seen", "xwOBA", "HardHit", "Usage"],
            "suggested_weight_metrics": ["EV", "LA", "Pitches Seen", "xwOBA", "Usage"],
        },
        "pitchers": {
            "basic": ["search_text", "team", "opponent", "min_confidence", "min_score", "max_score", "source", "category", "entity_type", "player_type"],
            "suggested_metric_filters": ["K%", "xwOBA Allowed", "HardHit Allowed", "Opp K%", "Score"],
            "suggested_weight_metrics": ["K%", "xwOBA Allowed", "HardHit Allowed", "Score"],
        },
        "teams": {
            "basic": ["search_text", "team", "opponent", "min_confidence", "min_score", "max_score", "source", "category", "entity_type", "player_type"],
            "suggested_metric_filters": ["Edge Score", "Win Edge", "Run Diff", "ISO", "OBP"],
            "suggested_weight_metrics": ["Edge Score", "Win Edge", "Run Diff", "ISO"],
        },
        "totals": {
            "basic": ["search_text", "min_confidence", "min_score", "max_score", "source", "category", "entity_type", "player_type"],
            "suggested_metric_filters": ["Projected Total", "Raw Total", "Run Index", "Score"],
            "suggested_weight_metrics": ["Projected Total", "Run Index", "Score"],
        },
        "overall_players": {
            "basic": ["search_text", "team", "opponent", "min_confidence", "min_score", "max_score", "source", "entity_type", "player_type"],
            "suggested_metric_filters": metrics[:6],
            "suggested_weight_metrics": metrics[:5],
        },
    }
    defaults = component_defaults.get(component, {"basic": [], "suggested_metric_filters": [], "suggested_weight_metrics": []})
    return {
        "basic": defaults["basic"],
        "metrics": metrics,
        "weights": metrics,
        "categories": sorted(categories),
        "player_types": sorted(player_types),
        "teams": sorted(teams)[:50],
        "opponents": sorted(opponents)[:50],
        "pitch_types": sorted(pitch_types),
        "suggested_metric_filters": defaults["suggested_metric_filters"],
        "suggested_weight_metrics": defaults["suggested_weight_metrics"],
    }


def apply_dashboard_filters(items: List[Dict[str, Any]], filters: Optional[Dict[str, Any]]) -> Tuple[List[Dict[str, Any]], Dict[str, Any], List[str], int, int]:
    normalized = normalize_filter_payload(filters)
    warnings: List[str] = []
    before = len(items)
    metric_filters = normalized.get("metrics") or {}
    weights = normalized.get("weights") or {}
    known_metrics = {metric for item in items for metric in (item.get("metrics") or {}).keys()}
    for metric in metric_filters.keys():
        if metric not in known_metrics:
            warnings.append(f"No items had metric {metric}")
    filtered: List[Dict[str, Any]] = []
    for item in items:
        if not passes_basic_filters(item, normalized):
            continue
        if metric_filters and not passes_metric_filters(item, metric_filters, warnings):
            continue
        filtered.append(apply_weight_overrides(item, weights))
    after = len(filtered)
    if before and after == 0 and normalized:
        warnings.append("Active filters removed all items")
    return filtered, normalized, warnings, before, after


def finalize_component_response(date: str, component: str, candidates: List[Dict[str, Any]], key_fn: Callable[[Dict[str, Any]], str], data_quality: Any = None, missing_data: Any = None, filters: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    deduped_pool = dedupe_ranked_items(candidates, key_fn, limit=100)
    filtered, filters_applied, warnings, before, after = apply_dashboard_filters(deduped_pool, filters)
    final_items = dedupe_ranked_items(filtered, key_fn, limit=10)
    response = build_response(date, component, final_items, data_quality, missing_data)
    response.update({
        "filters_applied": filters_applied,
        "available_filters": available_filters_for_component(component, deduped_pool),
        "result_count_before_filters": before,
        "result_count_after_filters": after,
        "filter_warnings": warnings,
    })
    return response


def solve_top_hitters(session, date: str, filters: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    context = build_stored_365_sweep_context(session, date)
    candidates: List[Dict[str, Any]] = []
    for row in context.get("top_matchups") or []:
        hitter_id = row.get("batter_id")
        if not hitter_id:
            continue
        metrics = {
            "xwOBA": rounded(row.get("hitter_xwoba")),
            "xBA": rounded(row.get("hitter_xba")),
            "EV": rounded(row.get("hitter_avg_ev"), 1),
            "LA": rounded(row.get("hitter_avg_la"), 1),
            "HardHit": rounded(row.get("hitter_hard_hit_pct")),
            "Usage": rounded(row.get("pitcher_usage_pct")),
            "Pitcher xwOBA": rounded(row.get("pitcher_xwoba_allowed")),
            "Pitches Seen": rounded(row.get("pitches_seen"), 0),
            "PA": rounded(row.get("pa"), 0),
        }
        pitch_label = row.get("pitch_name") or row.get("pitch_type") or "pitch"
        pitches_seen = row.get("pitches_seen")
        team_value = coalesce(row.get("batter_team_name"), row.get("batter_team"), row.get("batter_team_id"))
        candidates.append({
            "entity_type": "hitter",
            "player_type": "hitter",
            "category": "pitch_type_matchup",
            "entity_id": str(hitter_id),
            "entity_name": row.get("batter_name") or f"Batter {hitter_id}",
            "team": str(team_value) if team_value is not None else None,
            "opponent": row.get("opposing_pitcher_name") or row.get("opposing_pitcher_id"),
            "game_pk": row.get("game_pk"),
            "score": rounded(row.get("rank_score")),
            "base_score": rounded(row.get("rank_score")),
            "confidence": row.get("confidence_tier") or confidence_label(row.get("confidence")),
            "pitch_type": row.get("pitch_type"),
            "pitch_name": row.get("pitch_name"),
            "sample_size": row.get("sample_size"),
            "primary_reason": f"Best pitch angle: {pitch_label} with hitter xwOBA {metrics.get('xwOBA')}, EV {metrics.get('EV')}, LA {metrics.get('LA')}, and {pitches_seen or 0} pitches seen.",
            "reasoning": [
                f"Pitch angle: {pitch_label}",
                f"Pitcher usage: {metrics.get('Usage')}",
                f"Hitter xwOBA/xBA: {metrics.get('xwOBA')} / {metrics.get('xBA')}",
                f"Batted-ball quality: EV {metrics.get('EV')}, LA {metrics.get('LA')}, HardHit {metrics.get('HardHit')}",
                f"Pitch exposure: {metrics.get('Pitches Seen')} pitches seen, {metrics.get('PA')} PA",
                f"Pitcher allowed profile: xwOBA {metrics.get('Pitcher xwOBA')}",
            ],
            "metrics": metrics,
            "chart_data": build_chart_data(metrics),
            "source": "batter_pitch_type_matchups + model_projection_pitch_arsenal",
            "missing_data": row.get("missing_inputs") or [],
            "best_pitch_angles": [{"pitch_type": row.get("pitch_type"), "pitch_name": row.get("pitch_name"), "score": rounded(row.get("rank_score")), "reason": f"{pitch_label}: xwOBA {metrics.get('xwOBA')}, EV {metrics.get('EV')}, LA {metrics.get('LA')}, pitches seen {metrics.get('Pitches Seen')}, usage {metrics.get('Usage')}"}],
        })
    return finalize_component_response(date, "hitters", candidates, lambda row: f"hitter:{row.get('entity_id')}:{date}", context.get("data_quality"), context.get("missing_data"), filters)


def solve_top_pitchers(session, date: str, filters: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    context = build_pitcher_lean_context(session, date)
    candidates: List[Dict[str, Any]] = []
    for row in context.get("pitcher_leans") or []:
        pitcher_id = row.get("pitcher_id")
        if not pitcher_id:
            continue
        profile = row.get("pitcher_profile") or {}
        opp = row.get("opponent_offense") or {}
        metrics = {"K%": rounded(profile.get("k_pct")), "BB%": rounded(profile.get("bb_pct")), "xwOBA Allowed": rounded(profile.get("xwoba_allowed")), "HardHit Allowed": rounded(profile.get("hard_hit_allowed")), "Opp K%": rounded(opp.get("k_pct")), "Opp ISO": rounded(opp.get("iso")), "Score": rounded(row.get("score"))}
        candidates.append({
            "entity_type": "pitcher", "entity_id": str(pitcher_id), "entity_name": row.get("pitcher_name") or f"Pitcher {pitcher_id}", "team": row.get("team"), "opponent": row.get("opponent"), "game_pk": row.get("game_pk"), "score": rounded(row.get("score")), "base_score": rounded(row.get("score")), "confidence": row.get("confidence_tier") or confidence_label(row.get("confidence")), "category": row.get("category"), "primary_reason": ", ".join(row.get("reasons") or []) or "Model projection pitcher context created this lean.", "reasoning": row.get("reasons") or [], "metrics": metrics, "chart_data": build_chart_data(metrics), "source": "model_projections + ai_data_assistant_pitcher_lean_context", "missing_data": row.get("missing_inputs") or []
        })
    return finalize_component_response(date, "pitchers", candidates, lambda row: f"pitcher:{row.get('entity_id')}:{date}", context.get("data_quality"), context.get("missing_data"), filters)


def solve_top_teams(session, date: str, filters: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    payload = projection_payload(session, date)
    edges = score_projection_edges(payload) if payload else []
    candidates: List[Dict[str, Any]] = []
    for edge in edges:
        for side in ("away", "home"):
            signals = edge.get(f"{side}_signals") or {}
            team_id = signals.get("team_id")
            team_name = signals.get("team_name")
            if not team_id and not team_name:
                continue
            favorite_bonus = 0.2 if edge.get("model_favorite_side") == side else 0.0
            offense = signals.get("offense") or {}
            metrics = {"Edge Score": rounded((safe_float(edge.get("score")) or 0) + favorite_bonus), "Win Edge": rounded(edge.get("win_probability_edge")), "Run Diff": rounded(edge.get("expected_run_differential")), "ISO": rounded(offense.get("iso")), "OBP": rounded(offense.get("obp")), "SLG": rounded(offense.get("slg"))}
            score = (safe_float(edge.get("score")) or 0) + favorite_bonus + ((safe_float(offense.get("iso")) or 0) * 0.6)
            candidates.append({
                "entity_type": "team", "entity_id": str(team_id or team_name), "entity_name": team_name or f"Team {team_id}", "team": team_name, "opponent": signals.get("opponent_team"), "game_pk": edge.get("game_pk"), "score": rounded(score), "base_score": rounded(score), "confidence": edge.get("confidence_tier") or confidence_label(edge.get("confidence")), "primary_reason": f"Model edge context: win edge {metrics.get('Win Edge')}, run diff {metrics.get('Run Diff')}, ISO {metrics.get('ISO')}.", "reasoning": edge.get("why") or [], "metrics": metrics, "chart_data": build_chart_data(metrics), "source": "model_projections", "missing_data": edge.get("missing_inputs") or []
            })
    return finalize_component_response(date, "teams", candidates, lambda row: f"team:{row.get('entity_id')}:{date}", {"projection_games": len(payload.get("games") or [])}, payload.get("errors") or [], filters)


def solve_top_totals(session, date: str, filters: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    payload = projection_payload(session, date)
    edges = score_projection_edges(payload) if payload else []
    candidates: List[Dict[str, Any]] = []
    for edge in edges:
        game_pk = edge.get("game_pk")
        total = edge.get("total_projection") or {}
        projected_total = safe_float(total.get("total_expected_runs"))
        run_index = safe_float(total.get("run_scoring_index"))
        raw_total = safe_float(total.get("raw_total_expected_runs"))
        if projected_total is None and run_index is None:
            continue
        total_gap = abs((projected_total or 8.5) - 8.5)
        raw_gap = abs(projected_total - raw_total) if projected_total is not None and raw_total is not None else 0
        score = total_gap + (abs((run_index or 1.0) - 1.0) * 2.5) - min(0.5, raw_gap * 0.1)
        angle = "over_watchlist" if projected_total is not None and projected_total >= 8.8 else "under_watchlist" if projected_total is not None and projected_total <= 7.6 else "data_limited"
        metrics = {"Projected Total": rounded(projected_total), "Raw Total": rounded(raw_total), "Run Index": rounded(run_index), "Score": rounded(score)}
        candidates.append({
            "entity_type": "game_total", "entity_id": str(game_pk), "entity_name": edge.get("label"), "team": None, "opponent": None, "game_pk": game_pk, "score": rounded(score), "base_score": rounded(score), "confidence": edge.get("confidence_tier") or confidence_label(edge.get("confidence")), "category": angle, "primary_reason": f"{angle}: projected total {metrics.get('Projected Total')} with run index {metrics.get('Run Index')}. No sportsbook total is assumed.", "reasoning": [f"Projected total: {metrics.get('Projected Total')}", f"Raw total: {metrics.get('Raw Total')}", f"Run-scoring index: {metrics.get('Run Index')}", f"Environment label: {total.get('environment_label') or 'not labeled'}", "This is a model total watchlist only, not a priced market edge."], "metrics": metrics, "chart_data": build_chart_data(metrics), "source": "model_projections.total_projection", "missing_data": edge.get("missing_inputs") or []
        })
    return finalize_component_response(date, "totals", candidates, lambda row: f"game_total:{row.get('game_pk')}:{date}", {"projection_games": len(payload.get("games") or [])}, payload.get("errors") or [], filters)


def solve_top_overall_players(session, date: str, filters: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    hitters = solve_top_hitters(session, date, None).get("items") or []
    pitchers = solve_top_pitchers(session, date, None).get("items") or []
    candidates: List[Dict[str, Any]] = []
    for row in hitters + pitchers:
        entity_id = row.get("entity_id")
        if not entity_id:
            continue
        adjusted = dict(row)
        adjusted["entity_type"] = "player"
        adjusted["player_type"] = row.get("entity_type")
        adjusted["score"] = rounded((safe_float(row.get("score")) or 0) + (0.08 if row.get("confidence") == "high" else 0))
        adjusted["base_score"] = adjusted["score"]
        adjusted["source"] = f"overall_players:{row.get('source')}"
        candidates.append(adjusted)
    return finalize_component_response(date, "overall_players", candidates, lambda row: f"player:{row.get('entity_id')}:{date}", {"hitter_candidates": len(hitters), "pitcher_candidates": len(pitchers)}, [], filters)


def build_response(date: str, component: str, items: List[Dict[str, Any]], data_quality: Any = None, missing_data: Any = None) -> Dict[str, Any]:
    return {"date": date, "component": component, "title": COMPONENT_TITLES.get(component, component), "items": items[:10], "data_quality": data_quality or {}, "missing_data": missing_data or [], "generated_at": dt.datetime.utcnow().isoformat(timespec="seconds") + "Z"}


def build_dashboard_solver_payload(session, date: Optional[str], component: str, filters: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    target_date = (date or today())[:10]
    normalized = (component or "").strip().lower()
    if normalized not in SUPPORTED_COMPONENTS:
        return {"date": target_date, "component": normalized, "title": "Unsupported dashboard component", "items": [], "filters_applied": normalize_filter_payload(filters), "available_filters": available_filters_for_component(normalized, []), "result_count_before_filters": 0, "result_count_after_filters": 0, "filter_warnings": [f"Unsupported component: {component}"], "data_quality": {"supported_components": sorted(SUPPORTED_COMPONENTS)}, "missing_data": [f"Unsupported component: {component}"], "generated_at": dt.datetime.utcnow().isoformat(timespec="seconds") + "Z"}
    if normalized == "hitters":
        return solve_top_hitters(session, target_date, filters)
    if normalized == "pitchers":
        return solve_top_pitchers(session, target_date, filters)
    if normalized == "teams":
        return solve_top_teams(session, target_date, filters)
    if normalized == "totals":
        return solve_top_totals(session, target_date, filters)
    return solve_top_overall_players(session, target_date, filters)
