from __future__ import annotations

import math
from typing import Any, Dict, List, Optional, Tuple


def _safe_float(value: Any) -> Optional[float]:
    try:
        if value is None or value == "":
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def _clamp(value: float, low: float = 0.0, high: float = 1.0) -> float:
    return max(low, min(high, value))


def _norm(value: Optional[float], baseline: float, scale: float, invert: bool = False) -> Optional[float]:
    if value is None or scale == 0:
        return None
    score = (value - baseline) / scale
    if invert:
        score *= -1
    return _clamp(0.5 + score / 2.0)


def _american_to_implied(price: Any) -> Optional[float]:
    p = _safe_float(price)
    if p is None or p == 0:
        return None
    if p > 0:
        return round(100.0 / (p + 100.0), 4)
    return round(abs(p) / (abs(p) + 100.0), 4)


def _pct(value: Optional[float]) -> Optional[float]:
    if value is None:
        return None
    if value > 1:
        return value / 100.0
    return value


def _get(obj: Dict[str, Any], paths: List[str]) -> Tuple[Optional[Any], Optional[str]]:
    for path in paths:
        cur: Any = obj
        ok = True
        for part in path.split("."):
            if isinstance(cur, dict) and part in cur:
                cur = cur[part]
            else:
                ok = False
                break
        if ok and cur is not None:
            return cur, path
    return None, None


def _feature(features: List[Dict[str, Any]], name: str, value: Any, source: Optional[str], transform: str = "raw") -> Optional[float]:
    numeric = _safe_float(value)
    if numeric is not None:
        features.append({"name": name, "value": numeric, "source": source or "unknown", "transform": transform})
    return numeric


def _score_from_features(values: List[Optional[float]]) -> Tuple[float, int]:
    nums = [v for v in values if v is not None]
    if not nums:
        return 0.5, 0
    return round(sum(nums) / len(nums), 4), len(nums)


def _confidence(used: int, expected: int, model_depth: float = 1.0) -> float:
    if expected <= 0:
        return 0.0
    return round(_clamp((used / expected) * model_depth), 3)


def _selection_label(sel: Dict[str, Any]) -> str:
    base = sel.get("description") or sel.get("name") or "Selection"
    line = sel.get("line")
    return f"{base} {line}" if line is not None else str(base)


def _find_market(event: Dict[str, Any], keys: List[str]) -> Optional[Dict[str, Any]]:
    for market in event.get("markets", []) or []:
        market_key = market.get("market_key") or market.get("market_type") or market.get("market_name")
        if market_key in keys:
            return market
    return None


def _pick_selection_by_team(market: Optional[Dict[str, Any]], team_name: str) -> Optional[Dict[str, Any]]:
    if not market:
        return None
    target = str(team_name or "").lower()
    for sel in market.get("selections", []) or []:
        candidate = str(sel.get("name") or sel.get("team") or "").lower()
        if target and (target in candidate or candidate in target):
            return sel
    return None


def _best_price_selection(market: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    if not market:
        return None
    priced = []
    for sel in market.get("selections", []) or []:
        implied = _american_to_implied(sel.get("price"))
        if implied is not None:
            priced.append((implied, sel))
    if not priced:
        return None
    priced.sort(key=lambda x: x[0])
    return priced[0][1]


def _market_hold(market: Optional[Dict[str, Any]]) -> Optional[float]:
    if not market:
        return None
    probs = [_american_to_implied(sel.get("price")) for sel in market.get("selections", []) or []]
    probs = [p for p in probs if p is not None]
    if len(probs) < 2:
        return None
    return round(max(0.0, sum(probs) - 1.0), 4)


def _model_output(model: str, market: str, pick: str, score: float, model_probability: Optional[float], market_probability: Optional[float], features: List[Dict[str, Any]], missing: List[str], drivers: List[str]) -> Dict[str, Any]:
    used = len(features)
    expected = used + len(missing)
    edge = None
    if model_probability is not None and market_probability is not None:
        edge = round(model_probability - market_probability, 4)
    return {
        "model": model,
        "market": market,
        "pick": pick,
        "score": round(score, 4),
        "model_probability": round(model_probability, 4) if model_probability is not None else None,
        "market_implied_probability": round(market_probability, 4) if market_probability is not None else None,
        "edge": edge,
        "confidence": _confidence(used, expected if expected else 1),
        "features_used": features,
        "missing_inputs": missing,
        "drivers": drivers,
        "available": used >= 3,
    }


def _game_context(matchup: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "away_team": matchup.get("away_team_name") or matchup.get("away_team") or matchup.get("away_name"),
        "home_team": matchup.get("home_team_name") or matchup.get("home_team") or matchup.get("home_name"),
        "game_pk": matchup.get("game_pk"),
    }


def build_game_models(matchup: Dict[str, Any], event: Dict[str, Any]) -> Dict[str, Any]:
    ctx = _game_context(matchup)
    moneyline = _find_market(event, ["h2h"])
    spread = _find_market(event, ["spreads"])
    total = _find_market(event, ["totals"])
    return {
        "game_pk": ctx.get("game_pk"),
        "event_id": event.get("event_id"),
        "moneyline": build_moneyline_model(matchup, moneyline, ctx),
        "spread": build_spread_model(matchup, spread, ctx),
        "total": build_total_model(matchup, total, ctx),
    }


def build_moneyline_model(matchup: Dict[str, Any], market: Optional[Dict[str, Any]], ctx: Dict[str, Any]) -> Dict[str, Any]:
    features: List[Dict[str, Any]] = []
    missing: List[str] = []
    drivers: List[str] = []

    home_prob_raw, home_prob_src = _get(matchup, ["home_win_probability", "home_win_prob", "probabilities.home", "prediction.home_win_probability"])
    away_prob_raw, away_prob_src = _get(matchup, ["away_win_probability", "away_win_prob", "probabilities.away", "prediction.away_win_probability"])
    home_prob = _feature(features, "home_internal_win_probability", home_prob_raw, home_prob_src)
    away_prob = _feature(features, "away_internal_win_probability", away_prob_raw, away_prob_src)
    if home_prob is None:
        missing.append("home_internal_win_probability")
    if away_prob is None:
        missing.append("away_internal_win_probability")

    home_pitch_raw, home_pitch_src = _get(matchup, ["home_pitcher_score", "home_pitcher_rating", "home_pitcher_xwoba", "home_pitcher_era", "home_pitcher_stats.xwoba"])
    away_pitch_raw, away_pitch_src = _get(matchup, ["away_pitcher_score", "away_pitcher_rating", "away_pitcher_xwoba", "away_pitcher_era", "away_pitcher_stats.xwoba"])
    home_pitch = _feature(features, "home_pitcher_quality", home_pitch_raw, home_pitch_src)
    away_pitch = _feature(features, "away_pitcher_quality", away_pitch_raw, away_pitch_src)
    if home_pitch is None:
        missing.append("home_pitcher_quality")
    if away_pitch is None:
        missing.append("away_pitcher_quality")

    home_off_raw, home_off_src = _get(matchup, ["home_offense_score", "home_team_strength", "home_hitting_score", "home_team_stats.ops"])
    away_off_raw, away_off_src = _get(matchup, ["away_offense_score", "away_team_strength", "away_hitting_score", "away_team_stats.ops"])
    home_off = _feature(features, "home_offense_strength", home_off_raw, home_off_src)
    away_off = _feature(features, "away_offense_strength", away_off_raw, away_off_src)
    if home_off is None:
        missing.append("home_offense_strength")
    if away_off is None:
        missing.append("away_offense_strength")

    home_sel = _pick_selection_by_team(market, ctx.get("home_team") or "")
    away_sel = _pick_selection_by_team(market, ctx.get("away_team") or "")
    home_market = _american_to_implied(home_sel.get("price") if home_sel else None)
    away_market = _american_to_implied(away_sel.get("price") if away_sel else None)
    if home_market is not None:
        features.append({"name": "home_market_implied_probability", "value": home_market, "source": "draftkings.h2h.home", "transform": "american_to_implied"})
    else:
        missing.append("home_market_implied_probability")
    if away_market is not None:
        features.append({"name": "away_market_implied_probability", "value": away_market, "source": "draftkings.h2h.away", "transform": "american_to_implied"})
    else:
        missing.append("away_market_implied_probability")

    signals = []
    if home_prob is not None and away_prob is not None:
        signals.append(_clamp(0.5 + (home_prob - away_prob) / 2.0))
        drivers.append("internal win probability gap")
    if home_off is not None and away_off is not None:
        signals.append(_clamp(0.5 + (home_off - away_off) / 2.0))
        drivers.append("team offense gap")
    if home_pitch is not None and away_pitch is not None:
        signals.append(_clamp(0.5 + (home_pitch - away_pitch) / 2.0))
        drivers.append("starting pitcher gap")
    model_home_prob, used_signal_count = _score_from_features(signals)
    pick_home = model_home_prob >= 0.5
    pick = ctx.get("home_team") if pick_home else ctx.get("away_team")
    market_prob = home_market if pick_home else away_market
    return _model_output("moneyline_real_v1", "moneyline", str(pick or "No pick"), model_home_prob, model_home_prob if pick_home else round(1 - model_home_prob, 4), market_prob, features, missing, drivers)


def build_spread_model(matchup: Dict[str, Any], market: Optional[Dict[str, Any]], ctx: Dict[str, Any]) -> Dict[str, Any]:
    features: List[Dict[str, Any]] = []
    missing: List[str] = []
    drivers: List[str] = []
    home_runs_raw, home_runs_src = _get(matchup, ["home_projected_runs", "home_runs_projected", "projection.home_runs", "home_score_projection"])
    away_runs_raw, away_runs_src = _get(matchup, ["away_projected_runs", "away_runs_projected", "projection.away_runs", "away_score_projection"])
    home_runs = _feature(features, "home_projected_runs", home_runs_raw, home_runs_src)
    away_runs = _feature(features, "away_projected_runs", away_runs_raw, away_runs_src)
    if home_runs is None:
        missing.append("home_projected_runs")
    if away_runs is None:
        missing.append("away_projected_runs")

    home_off_raw, home_off_src = _get(matchup, ["home_offense_score", "home_team_strength", "home_hitting_score", "home_team_stats.ops"])
    away_off_raw, away_off_src = _get(matchup, ["away_offense_score", "away_team_strength", "away_hitting_score", "away_team_stats.ops"])
    home_off = _feature(features, "home_offense_strength", home_off_raw, home_off_src)
    away_off = _feature(features, "away_offense_strength", away_off_raw, away_off_src)
    if home_off is None:
        missing.append("home_offense_strength")
    if away_off is None:
        missing.append("away_offense_strength")

    home_pitch_raw, home_pitch_src = _get(matchup, ["home_pitcher_volatility", "home_pitcher_xwoba", "home_pitcher_hard_hit_pct", "home_pitcher_stats.xwoba"])
    away_pitch_raw, away_pitch_src = _get(matchup, ["away_pitcher_volatility", "away_pitcher_xwoba", "away_pitcher_hard_hit_pct", "away_pitcher_stats.xwoba"])
    home_pitch_risk = _feature(features, "home_pitcher_run_risk", home_pitch_raw, home_pitch_src)
    away_pitch_risk = _feature(features, "away_pitcher_run_risk", away_pitch_raw, away_pitch_src)
    if home_pitch_risk is None:
        missing.append("home_pitcher_run_risk")
    if away_pitch_risk is None:
        missing.append("away_pitcher_run_risk")

    if home_runs is not None and away_runs is not None:
        run_diff = home_runs - away_runs
        drivers.append("projected run differential")
    else:
        pieces = []
        if home_off is not None and away_off is not None:
            pieces.append(home_off - away_off)
            drivers.append("offense differential proxy")
        if home_pitch_risk is not None and away_pitch_risk is not None:
            pieces.append(away_pitch_risk - home_pitch_risk)
            drivers.append("pitcher run-risk proxy")
        run_diff = sum(pieces) if pieces else 0.0
    home_sel = _pick_selection_by_team(market, ctx.get("home_team") or "")
    away_sel = _pick_selection_by_team(market, ctx.get("away_team") or "")
    home_line = _safe_float(home_sel.get("line") if home_sel else None)
    away_line = _safe_float(away_sel.get("line") if away_sel else None)
    home_market = _american_to_implied(home_sel.get("price") if home_sel else None)
    away_market = _american_to_implied(away_sel.get("price") if away_sel else None)
    if home_line is None:
        missing.append("home_spread_line")
    else:
        features.append({"name": "home_spread_line", "value": home_line, "source": "draftkings.spreads.home", "transform": "raw"})
    if away_line is None:
        missing.append("away_spread_line")
    else:
        features.append({"name": "away_spread_line", "value": away_line, "source": "draftkings.spreads.away", "transform": "raw"})
    if home_market is not None:
        features.append({"name": "home_spread_implied_probability", "value": home_market, "source": "draftkings.spreads.home", "transform": "american_to_implied"})
    if away_market is not None:
        features.append({"name": "away_spread_implied_probability", "value": away_market, "source": "draftkings.spreads.away", "transform": "american_to_implied"})
    pick_home = run_diff + (home_line or 0) > 0
    pick = f"{ctx.get('home_team')} {home_line}" if pick_home else f"{ctx.get('away_team')} {away_line}"
    model_prob = _clamp(0.5 + abs(run_diff) / 6.0)
    market_prob = home_market if pick_home else away_market
    return _model_output("spread_real_v1", "spread", pick, run_diff, model_prob, market_prob, features, missing, drivers)


def build_total_model(matchup: Dict[str, Any], market: Optional[Dict[str, Any]], ctx: Dict[str, Any]) -> Dict[str, Any]:
    features: List[Dict[str, Any]] = []
    missing: List[str] = []
    drivers: List[str] = []
    temp_raw, temp_src = _get(matchup, ["weather.temp_f", "weather.temp", "temp_f"])
    temp = _feature(features, "temperature_f", temp_raw, temp_src)
    if temp is None:
        missing.append("temperature_f")
    wind_raw, wind_src = _get(matchup, ["weather.wind_speed", "wind_speed"])
    wind = _feature(features, "wind_speed", wind_raw, wind_src)
    if wind is None:
        missing.append("wind_speed")
    home_off_raw, home_off_src = _get(matchup, ["home_offense_score", "home_team_strength", "home_hitting_score", "home_team_stats.ops"])
    away_off_raw, away_off_src = _get(matchup, ["away_offense_score", "away_team_strength", "away_hitting_score", "away_team_stats.ops"])
    home_off = _feature(features, "home_offense_strength", home_off_raw, home_off_src)
    away_off = _feature(features, "away_offense_strength", away_off_raw, away_off_src)
    if home_off is None:
        missing.append("home_offense_strength")
    if away_off is None:
        missing.append("away_offense_strength")
    home_pitch_raw, home_pitch_src = _get(matchup, ["home_pitcher_run_prevention", "home_pitcher_xwoba", "home_pitcher_era", "home_pitcher_stats.xwoba"])
    away_pitch_raw, away_pitch_src = _get(matchup, ["away_pitcher_run_prevention", "away_pitcher_xwoba", "away_pitcher_era", "away_pitcher_stats.xwoba"])
    home_pitch = _feature(features, "home_pitcher_run_prevention", home_pitch_raw, home_pitch_src)
    away_pitch = _feature(features, "away_pitcher_run_prevention", away_pitch_raw, away_pitch_src)
    if home_pitch is None:
        missing.append("home_pitcher_run_prevention")
    if away_pitch is None:
        missing.append("away_pitcher_run_prevention")

    total_sel = None
    over_sel = None
    under_sel = None
    if market:
        for sel in market.get("selections", []) or []:
            name = str(sel.get("name") or "").lower()
            if "over" in name:
                over_sel = sel
            elif "under" in name:
                under_sel = sel
        total_sel = over_sel or under_sel or (market.get("selections") or [None])[0]
    market_total = _safe_float(total_sel.get("line") if total_sel else None)
    over_prob = _american_to_implied(over_sel.get("price") if over_sel else None)
    under_prob = _american_to_implied(under_sel.get("price") if under_sel else None)
    if market_total is not None:
        features.append({"name": "market_total", "value": market_total, "source": "draftkings.totals.line", "transform": "raw"})
    else:
        missing.append("market_total")
    if over_prob is not None:
        features.append({"name": "over_implied_probability", "value": over_prob, "source": "draftkings.totals.over", "transform": "american_to_implied"})
    else:
        missing.append("over_implied_probability")
    if under_prob is not None:
        features.append({"name": "under_implied_probability", "value": under_prob, "source": "draftkings.totals.under", "transform": "american_to_implied"})
    else:
        missing.append("under_implied_probability")

    env = 0.0
    if temp is not None:
        env += (temp - 70.0) / 25.0
        drivers.append("temperature run environment")
    if wind is not None:
        env += wind / 30.0
        drivers.append("wind run environment")
    if home_off is not None and away_off is not None:
        env += (home_off + away_off - 1.0)
        drivers.append("combined offense")
    if home_pitch is not None and away_pitch is not None:
        env -= (home_pitch + away_pitch - 1.0)
        drivers.append("starting pitcher suppression")
    projected_total = (market_total if market_total is not None else 8.5) + env
    pick_over = projected_total >= (market_total if market_total is not None else 8.5)
    pick = f"Over {market_total}" if pick_over else f"Under {market_total}"
    model_prob = _clamp(0.5 + abs(projected_total - (market_total or 8.5)) / 5.0)
    market_prob = over_prob if pick_over else under_prob
    return _model_output("total_real_v1", "total", pick, projected_total, model_prob, market_prob, features, missing, drivers)


def build_prop_models(matchup: Dict[str, Any], prop_markets: List[Dict[str, Any]], market_filter: Optional[str] = None) -> Dict[str, Any]:
    candidates: List[Dict[str, Any]] = []
    for market in prop_markets or []:
        market_name = str(market.get("market_name") or market.get("market_key") or "prop")
        if market_filter and market_filter != "all" and market_filter != market_name:
            continue
        for sel in market.get("selections", []) or []:
            implied = _american_to_implied(sel.get("price"))
            line = _safe_float(sel.get("line"))
            score = (1 - implied) if implied is not None else 0.0
            if line is not None:
                score += min(0.25, abs(line) / 20.0)
            candidates.append({
                "model": "prop_real_v1",
                "market": market_name,
                "pick": _selection_label(sel),
                "score": round(score, 4),
                "model_probability": None,
                "market_implied_probability": implied,
                "edge": None,
                "confidence": 0.35 if implied is not None else 0.1,
                "features_used": [
                    {"name": "prop_price", "value": sel.get("price"), "source": "draftkings.props.price", "transform": "american"},
                    {"name": "prop_line", "value": line, "source": "draftkings.props.line", "transform": "raw"},
                ],
                "missing_inputs": ["player_statcast_context", "opponent_matchup_context", "lineup_role_context"],
                "drivers": ["market price", "prop line"],
                "available": implied is not None,
            })
    candidates.sort(key=lambda row: row.get("score") or 0, reverse=True)
    return {"top_candidates": candidates[:3], "candidate_count": len(candidates)}
