from __future__ import annotations

import copy
import time
from contextvars import ContextVar
from typing import Any, Dict, List, Optional

from . import ai_data_assistant as core
from . import ai_data_assistant_pipeline as pipeline
from .ai_data_assistant_traces import build_trace_record, write_trace_record
from .daily_odds_models import build_game_models
from .daily_odds_routes import _build_global_prop_candidates, _build_matchup_index, _load_matchups
from .model_projections import build_model_projection_payload as uncached_build_model_projection_payload
from .odds_provider import fetch_draftkings_events
from .shared_payload_cache import clear_shared_payload_cache, env_ttl, get_cache, get_or_set, make_cache_key, set_cache, stable_hash

AI_RESPONSE_TTL_SECONDS = 180

_timing_var: ContextVar[Optional[Dict[str, float]]] = ContextVar("ai_data_assistant_timing", default=None)
_original_projection_builder = uncached_build_model_projection_payload
_patch_applied = False


def _now() -> float:
    return time.perf_counter()


def _ms(start: float) -> int:
    return int(round((_now() - start) * 1000))


def _timing() -> Optional[Dict[str, float]]:
    return _timing_var.get()


def _add_timing(name: str, elapsed_ms: int) -> None:
    timing = _timing()
    if timing is None:
        return
    timing[name] = timing.get(name, 0) + elapsed_ms


def cached_build_model_projection_payload(session, target_date: str) -> Dict[str, Any]:
    # Import lazily: the route graph imports the assistant during startup.
    # User requests consume the same verified artifact as Model Projections.
    # A cache miss must never launch a full canonical slate simulation.
    from .model_projection_routes import get_model_projection_payload

    start = _now()
    payload = get_model_projection_payload(target_date)
    _add_timing("projection_payload_ms", _ms(start))
    return payload


def apply_performance_patch() -> None:
    global _patch_applied
    if _patch_applied:
        return
    core.build_model_projection_payload = cached_build_model_projection_payload
    _patch_applied = True


def _response_cache_key(message: str, date: Optional[str], game_pk: Optional[int], player_id: Optional[int], team_id: Optional[int], use_llm: bool) -> str:
    normalized_message = " ".join((message or "").strip().lower().split())
    payload = {
        "message": normalized_message,
        "date": date,
        "game_pk": game_pk,
        "player_id": player_id,
        "team_id": team_id,
        "use_llm": bool(use_llm),
    }
    return make_cache_key("ai_data_assistant", "response", stable_hash(payload))


def _safe_float(value: Any) -> Optional[float]:
    try:
        if value is None or value == "":
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def _pct(value: Any) -> Optional[str]:
    number = _safe_float(value)
    if number is None:
        return None
    return f"{round(number * 100, 1)}%"


def _canonical_games_from_projection_payload(payload: Dict[str, Any], game_pk: Optional[int] = None, limit: int = 6) -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []
    for game in payload.get("games") or []:
        if game_pk is not None and str(game.get("game_pk")) != str(game_pk):
            continue
        probs = game.get("main_matchup_probabilities") or {}
        context = game.get("canonical_game_context") or (game.get("workspace") or {}).get("canonicalGameContext") or {}
        home_team = (game.get("home_team") or {}).get("name") if isinstance(game.get("home_team"), dict) else game.get("home_team")
        away_team = (game.get("away_team") or {}).get("name") if isinstance(game.get("away_team"), dict) else game.get("away_team")
        home_prob = _safe_float(probs.get("home_win_prob") or game.get("home_win_prob"))
        away_prob = _safe_float(probs.get("away_win_prob") or game.get("away_win_prob"))
        favorite = None
        favorite_probability = None
        if home_prob is not None and away_prob is not None:
            favorite = home_team if home_prob >= away_prob else away_team
            favorite_probability = max(home_prob, away_prob)
        simulation_diag = probs.get("simulation_diagnostic") or (game.get("workspace") or {}).get("sharedSimulationDiagnostics") or {}
        rows.append({
            "game_pk": game.get("game_pk"),
            "label": f"{away_team or 'Away'} @ {home_team or 'Home'}",
            "favorite": favorite,
            "favorite_probability": favorite_probability,
            "home_win_prob": home_prob,
            "away_win_prob": away_prob,
            "model_version": probs.get("model_version") or game.get("model_version"),
            "lineup_status": probs.get("lineup_status") or game.get("lineup_status"),
            "data_confidence": probs.get("data_confidence") or game.get("data_confidence"),
            "missing_inputs": probs.get("missing_inputs") or game.get("missing_inputs") or [],
            "probability_component_keys": sorted((probs.get("probability_components") or game.get("probability_components") or {}).keys()),
            "simulation_role": simulation_diag.get("status") or "diagnostic_only_not_final_probability",
            "simulation_is_final_probability": False,
            "canonical_game_context": context,
        })
        if len(rows) >= limit and game_pk is None:
            break
    return rows


def _build_canonical_probability_context(session, context: Dict[str, Any], game_pk: Optional[int] = None) -> Dict[str, Any]:
    date = context.get("date") or core.today()
    start = _now()
    try:
        payload = cached_build_model_projection_payload(session, date)
        _add_timing("canonical_probability_context_ms", _ms(start))
    except Exception as exc:
        return {
            "available": False,
            "date": date,
            "error": str(exc),
            "final_probability_source": "matchups.home_win_prob_and_away_win_prob",
            "simulation_role": "diagnostic_only_not_final_probability",
        }
    games = _canonical_games_from_projection_payload(payload, game_pk=game_pk or context.get("game_pk"))
    return {
        "available": bool(games),
        "date": date,
        "final_probability_source": "matchups.home_win_prob_and_away_win_prob",
        "model_version": "canonical_matchup_win_probability_v2",
        "legacy_model_version": "legacy_matchup_win_probability_v1",
        "simulation_role": "diagnostic_only_not_final_probability",
        "games": games,
        "source_note": "AI Data Assistant treats home_win_prob and away_win_prob as canonical v2. Simulation output is run-distribution and diagnostic context only.",
    }


def _compact_daily_odds_game_model(model: Dict[str, Any], label: str, game_pk: Optional[int]) -> Dict[str, Any]:
    diagnostics = model.get("diagnostics") or {}
    return {
        "game_pk": game_pk,
        "label": label,
        "market": model.get("market"),
        "pick": model.get("pick"),
        "model_probability": _safe_float(model.get("model_probability")),
        "market_implied_probability": _safe_float(model.get("market_implied_probability")),
        "edge": _safe_float(model.get("edge")),
        "expected_value": _safe_float(model.get("expected_value")),
        "confidence_tier": model.get("confidence_tier"),
        "recommendation_status": model.get("recommendation_status"),
        "rejection_reason": model.get("rejection_reason"),
        "drivers": model.get("drivers") or [],
        "canonical_game_context": diagnostics.get("canonical_game_context") or model.get("canonical_game_context"),
    }


def _compact_daily_odds_prop_candidate(candidate: Dict[str, Any]) -> Dict[str, Any]:
    diagnostics = candidate.get("diagnostics") or {}
    return {
        "game_pk": candidate.get("game_pk"),
        "label": f"{candidate.get('away_team') or 'Away'} @ {candidate.get('home_team') or 'Home'}",
        "market": candidate.get("market"),
        "pick": candidate.get("pick"),
        "player_name": candidate.get("player_name"),
        "model_probability": _safe_float(candidate.get("model_probability")),
        "market_implied_probability": _safe_float(candidate.get("market_implied_probability")),
        "edge": _safe_float(candidate.get("edge")),
        "expected_value": _safe_float(candidate.get("expected_value")),
        "confidence_tier": candidate.get("confidence_tier"),
        "data_quality_score": _safe_float(candidate.get("data_quality_score")),
        "recommendation_status": candidate.get("recommendation_status"),
        "rejection_reason": candidate.get("rejection_reason"),
        "usage_weighted_gate": diagnostics.get("usage_weighted_gate"),
        "drivers": candidate.get("drivers") or [],
        "canonical_game_context": diagnostics.get("canonical_game_context") or candidate.get("canonical_game_context"),
    }


def _build_daily_odds_diagnostics_context(session, context: Dict[str, Any], game_pk: Optional[int] = None) -> Dict[str, Any]:
    date = context.get("date") or core.today()
    start = _now()
    try:
        matchups, matchup_errors = _load_matchups(date)
        if game_pk is not None:
            matchups = [m for m in matchups if str(m.get("game_pk")) == str(game_pk)]
        matchup_index = _build_matchup_index(matchups)
        events = fetch_draftkings_events(date) or []
        game_models: List[Dict[str, Any]] = []
        for event in events:
            key = f"{(event.get('away_team') or {}).get('name','').lower()}@{(event.get('home_team') or {}).get('name','').lower()}"
            matchup = matchup_index.get(key)
            if not matchup:
                continue
            if game_pk is not None and str(matchup.get("game_pk")) != str(game_pk):
                continue
            models = build_game_models(matchup, event)
            label = f"{matchup.get('away_team_name') or matchup.get('away_team')} @ {matchup.get('home_team_name') or matchup.get('home_team')}"
            for market_name in ("moneyline", "spread", "total"):
                model = models.get(market_name)
                if isinstance(model, dict):
                    game_models.append(_compact_daily_odds_game_model(model, label, matchup.get("game_pk")))
        game_models.sort(key=lambda row: abs(row.get("edge") or 0.0), reverse=True)
        prop_candidates = _build_global_prop_candidates(events, matchup_index, matchups, limit=12)
        if game_pk is not None:
            prop_candidates = [c for c in prop_candidates if str(c.get("game_pk")) == str(game_pk)]
        top_prop_candidates = [_compact_daily_odds_prop_candidate(c) for c in prop_candidates[:6]]
        _add_timing("daily_odds_diagnostics_context_ms", _ms(start))
        return {
            "available": bool(game_models or top_prop_candidates),
            "date": date,
            "top_game_models": game_models[:6],
            "top_prop_candidates": top_prop_candidates,
            "matchup_errors": matchup_errors,
            "event_count": len(events),
            "source_note": "Daily Odds diagnostics include EV, confidence tier, data quality, recommendation status, and optional usage-weighted hitter gate output.",
        }
    except Exception as exc:
        return {
            "available": False,
            "date": date,
            "error": str(exc),
            "top_game_models": [],
            "top_prop_candidates": [],
        }


def _canonical_answer_prefix(canonical_context: Dict[str, Any]) -> str:
    if not canonical_context.get("available"):
        return (
            "Canonical probability note\n"
            "The assistant attempted to load canonical matchup probability v2 context, but it was not available for this query. "
            "Do not treat simulation output as the final side probability.\n"
        )
    games = canonical_context.get("games") or []
    best = games[0] if games else {}
    favorite = best.get("favorite") or "no clear side"
    favorite_prob = _pct(best.get("favorite_probability")) or "missing"
    confidence = best.get("data_confidence") or "unknown"
    lineup = best.get("lineup_status") or "unknown"
    components = ", ".join(best.get("probability_component_keys") or []) or "component diagnostics missing"
    game_context = best.get("canonical_game_context") or {}
    total_runs = game_context.get("projected_total_runs")
    return (
        "Canonical probability note\n"
        f"Final side probability comes from canonical v2 `home_win_prob` and `away_win_prob`, not the simulation diagnostic. "
        f"Top loaded game: {best.get('label') or 'unknown game'}; side lean {favorite} at {favorite_prob}; confidence {confidence}; lineup status {lineup}. "
        f"Components available: {components}."
        + (f" Shared game context projected total: {total_runs}." if total_runs is not None else "")
        + "\n"
    )


def _daily_odds_answer_prefix(daily_odds_context: Dict[str, Any]) -> str:
    if not daily_odds_context.get("available"):
        return (
            "Daily Odds note\n"
            "Daily Odds diagnostics were not available for this query.\n"
        )
    game_models = daily_odds_context.get("top_game_models") or []
    prop_candidates = daily_odds_context.get("top_prop_candidates") or []
    lead_game = game_models[0] if game_models else {}
    lead_prop = prop_candidates[0] if prop_candidates else {}
    game_line = ""
    if lead_game:
        context = lead_game.get("canonical_game_context") or {}
        context_prob_gap = context.get("probability_gap")
        game_line = (
            f"Top game model: {lead_game.get('label')} | {lead_game.get('market')} | {lead_game.get('pick')} | "
            f"edge {_pct(lead_game.get('edge')) or lead_game.get('edge')} | EV {lead_game.get('expected_value')} | "
            f"tier {lead_game.get('confidence_tier') or 'unknown'} | status {lead_game.get('recommendation_status') or 'unknown'}."
            + (f" Shared game context gap: {context_prob_gap}." if context_prob_gap is not None else "")
            + " "
        )
    prop_line = ""
    if lead_prop:
        gate = lead_prop.get("usage_weighted_gate") or {}
        gate_status = gate.get("final_pitcher_vs_hitter_recommendation_status") or gate.get("status")
        prop_line = (
            f"Top prop candidate: {lead_prop.get('player_name') or 'unknown player'} | {lead_prop.get('market')} | {lead_prop.get('pick')} | "
            f"EV {lead_prop.get('expected_value')} | tier {lead_prop.get('confidence_tier') or 'unknown'} | "
            f"status {lead_prop.get('recommendation_status') or 'unknown'}"
            + (f" | usage gate {gate_status}." if gate_status else ".")
        )
    return "Daily Odds note\n" + game_line + prop_line + "\n"


def _merge_warning_lists(result: Dict[str, Any], extra_warnings: List[str]) -> None:
    warnings = list(result.get("warnings") or [])
    for warning in extra_warnings:
        if warning and warning not in warnings:
            warnings.append(warning)
    result["warnings"] = warnings[:20]


def _enrich_result_with_canonical_context(result: Dict[str, Any], canonical_context: Dict[str, Any], daily_odds_context: Dict[str, Any]) -> Dict[str, Any]:
    enriched = copy.deepcopy(result)
    enriched["canonical_probability_context"] = canonical_context
    enriched["daily_odds_diagnostics_context"] = daily_odds_context
    sources = list(enriched.get("sources_used") or enriched.get("data_used") or [])
    for source in ["canonical_matchup_probability_v2", "matchups.home_win_prob_and_away_win_prob", "daily_odds_models", "canonical_game_context_v1"]:
        if source not in sources:
            sources.append(source)
    enriched["sources_used"] = sources
    enriched["data_used"] = sources
    enriched.setdefault("data_quality", {})
    if isinstance(enriched["data_quality"], dict):
        enriched["data_quality"]["canonical_probability"] = {
            "available": canonical_context.get("available"),
            "final_probability_source": canonical_context.get("final_probability_source"),
            "simulation_role": canonical_context.get("simulation_role"),
            "games_loaded": len(canonical_context.get("games") or []),
        }
        enriched["data_quality"]["daily_odds_diagnostics"] = {
            "available": daily_odds_context.get("available"),
            "game_model_count": len(daily_odds_context.get("top_game_models") or []),
            "prop_candidate_count": len(daily_odds_context.get("top_prop_candidates") or []),
        }
    note = _canonical_answer_prefix(canonical_context) + _daily_odds_answer_prefix(daily_odds_context)
    answer = enriched.get("answer") or ""
    if "Canonical probability note" not in answer:
        enriched["answer"] = note + "\n" + answer
    confidence_note = enriched.get("confidence_note") or ""
    canonical_note = " Canonical v2 is the final side probability; simulations are diagnostic/run-distribution context only. Daily Odds diagnostics include EV, confidence tier, recommendation status, optional hitter-usage gate output, and shared game context."
    if canonical_note.strip() not in confidence_note:
        enriched["confidence_note"] = confidence_note + canonical_note
    extra_warnings: List[str] = []
    if canonical_context.get("error"):
        extra_warnings.append(f"canonical_probability_context: {canonical_context.get('error')}")
    if daily_odds_context.get("error"):
        extra_warnings.append(f"daily_odds_diagnostics: {daily_odds_context.get('error')}")
    _merge_warning_lists(enriched, extra_warnings)
    return enriched


def _build_ai_data_assistant_response_uncached(
    session,
    message: str,
    date: Optional[str] = None,
    game_pk: Optional[int] = None,
    player_id: Optional[int] = None,
    team_id: Optional[int] = None,
    use_llm: bool = False,
) -> Dict[str, Any]:
    context_start = _now()
    packet = pipeline.build_assistant_packet(
        session=session,
        message=message,
        date=date,
        game_pk=game_pk,
        player_id=player_id,
        team_id=team_id,
    )
    timing = _timing()
    if timing is not None:
        timing["context_build_ms"] = _ms(context_start)

    canonical_context = _build_canonical_probability_context(session, packet, game_pk=game_pk)
    daily_odds_context = _build_daily_odds_diagnostics_context(session, packet, game_pk=game_pk)

    deterministic = pipeline.render_structured_response(message, packet)

    answer_start = _now()
    result = pipeline.answer_with_optional_llm_structured(message, packet, use_llm=use_llm)
    if timing is not None:
        timing["answer_render_ms"] = _ms(answer_start)
        timing["llm_requested"] = 1 if use_llm else 0

    result = _enrich_result_with_canonical_context(result, canonical_context, daily_odds_context)

    trace_status: Dict[str, Any] = {"logged": False, "reason": "unattempted"}
    try:
        trace_record = build_trace_record(
            message=message,
            intent=result.get("intent") or packet.get("intent") or "unknown",
            packet_preview=result.get("context_preview") or pipeline.compact_packet_preview(packet),
            deterministic_answer=deterministic.get("answer") or "",
            llm_answer=result.get("llm_answer"),
            structured_response={
                "intent": result.get("intent"),
                "answer": result.get("answer"),
                "primary_recommendations": result.get("primary_recommendations"),
                "watchlist": result.get("watchlist"),
                "data_used": result.get("data_used"),
                "missing_data": result.get("missing_data"),
                "warnings": result.get("warnings"),
                "confidence_note": result.get("confidence_note"),
            },
        )
        trace_status = write_trace_record(trace_record)
    except Exception as exc:
        trace_status = {"logged": False, "reason": f"trace_logging_failed: {exc}"}
    result["trace_logging"] = trace_status
    return result


def build_ai_data_assistant_response(
    session,
    message: str,
    date: Optional[str] = None,
    game_pk: Optional[int] = None,
    player_id: Optional[int] = None,
    team_id: Optional[int] = None,
    use_llm: bool = False,
) -> Dict[str, Any]:
    apply_performance_patch()
    total_start = _now()
    timing: Dict[str, float] = {}
    token = _timing_var.set(timing)
    cache_key = _response_cache_key(message, date, game_pk, player_id, team_id, use_llm)
    ttl_seconds = env_ttl("AI_DATA_ASSISTANT_RESPONSE_CACHE_TTL_SECONDS")
    try:
        cached = get_cache(cache_key, ttl_seconds)
        if cached is not None:
            cached.setdefault("timing", {})
            cached["timing"].update({"response_cache_hit": 1, "total_ms": _ms(total_start)})
            cached["cache_status"] = "response_cache_hit"
            cached.setdefault("cache_key", cache_key)
            cached.setdefault("ttl_seconds", ttl_seconds)
            return cached

        result = get_or_set(
            cache_key,
            ttl_seconds,
            lambda: _build_ai_data_assistant_response_uncached(
                session=session,
                message=message,
                date=date,
                game_pk=game_pk,
                player_id=player_id,
                team_id=team_id,
                use_llm=use_llm,
            ),
        )
        result["timing"] = dict(timing)
        result["timing"]["total_ms"] = _ms(total_start)
        result["cache_status"] = "miss"
        result.setdefault("cache_key", cache_key)
        result.setdefault("ttl_seconds", ttl_seconds)
        return result
    finally:
        _timing_var.reset(token)


def clear_ai_data_assistant_caches() -> Dict[str, Any]:
    ai_response = clear_shared_payload_cache("ai_data_assistant:response")
    model_projection = clear_shared_payload_cache("model_projection:full")
    return {
        "cleared": True,
        "shared_cache": {
            "ai_data_assistant_response": ai_response,
            "model_projection": model_projection,
        },
    }
