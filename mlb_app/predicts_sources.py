"""Batched adapters for MLBGPT's existing durable data, with explicit source dates."""
from collections import defaultdict
from datetime import timedelta
from sqlalchemy import select
from .database import BatterPitchTypeMatchup
from .dashboard_object_models import DashboardPlayerCurrent, DashboardPlayerSnapshot, PlayerTrendSnapshot
from .dashboard_projection_report_query import _player_rows, _projection_profiles
from .final_game_snapshots import FinalGameSnapshot
from .predicts_features import (bounded_pitches, process_windows, expected_arsenal,
                               location_compatibility, workload, exposure, environment, feature, opponent_adjusted)
from .predicts_validation import identity, number, utc, validate_player, asof, FEATURE_VERSION


def _shadow(game):
    shared = game.get("sharedSimulation") or {}
    return ((game.get("diagnostics") or {}).get("canonical_shadow") or
            (shared.get("diagnostics") or {}).get("canonical_shadow") or {})


def collect(session, payload, target_date, captured):
    source_time = utc(payload["predicts_source_generated_at"])
    if captured-source_time > timedelta(hours=6):
        raise ValueError("Projection artifact is stale (older than six hours)")
    games, rejected = {}, []
    for game in payload.get("games") or []:
        try:
            pk = identity(game.get("game_pk"))
            if pk in games:
                raise ValueError("Duplicate game")
            if game.get("game_date", payload.get("date")) != target_date.isoformat():
                raise ValueError("Mismatched game date")
            asof(source_time, captured, game.get("game_time"))
            if str(game.get("status", "")).lower() not in {"preview", "scheduled", "pre-game", "pregame", "warmup"}:
                raise ValueError("Game is not pregame")
            games[pk] = game
        except (ValueError, TypeError) as exc:
            rejected.append({"game_pk": game.get("game_pk"), "reason": str(exc)})
    if not games:
        return {}, rejected
    canonical = _player_rows({"games": list(games.values()), "date": target_date.isoformat()})
    ids = {identity(r["mlb_player_id"]) for r in canonical}
    current = {r.mlb_player_id: r for r in session.query(DashboardPlayerCurrent).filter(
        DashboardPlayerCurrent.updated_at <= captured,
        DashboardPlayerCurrent.promoted_at <= captured)}
    lineups = {}
    for r in session.query(DashboardPlayerSnapshot).filter(
        DashboardPlayerSnapshot.snapshot_date==target_date, DashboardPlayerSnapshot.game_pk.in_(list(games) or [-1]),
        DashboardPlayerSnapshot.generated_at<=captured, DashboardPlayerSnapshot.refreshed_at<=captured,
        DashboardPlayerSnapshot.is_approved.is_(True)).order_by(DashboardPlayerSnapshot.generated_at.desc()):
        lineups.setdefault((r.game_pk,r.mlb_player_id),r)
    arsenal = defaultdict(list)
    for r in session.query(BatterPitchTypeMatchup).filter(
        BatterPitchTypeMatchup.target_date == target_date,
        BatterPitchTypeMatchup.batter_id.in_(ids or [-1]),
        BatterPitchTypeMatchup.date_end < target_date,
        BatterPitchTypeMatchup.refreshed_at <= captured).order_by(BatterPitchTypeMatchup.refreshed_at.desc()):
        if (r.pitches_seen is not None and not 0 <= r.pitches_seen <= 10000) or (r.pa is not None and not 0 <= r.pa <= 1500):
            continue
        key = (r.game_pk, r.batter_id, r.opposing_pitcher_id)
        if not any(old.pitch_type == r.pitch_type for old in arsenal[key]):
            arsenal[key].append(r)
    trends = defaultdict(list)
    for r in session.query(PlayerTrendSnapshot).filter(PlayerTrendSnapshot.player_id.in_(ids or [-1]),
        PlayerTrendSnapshot.as_of_date == target_date, PlayerTrendSnapshot.window_end < target_date,
        PlayerTrendSnapshot.baseline_end < target_date, PlayerTrendSnapshot.generated_at <= captured):
        trends[r.player_id].append({"metric": r.metric, "window_days": r.window_days,
            "current": r.current_value, "baseline": r.baseline_value,
            "sample_size": r.window_sample_size, "baseline_sample_size": r.baseline_sample_size,
            "generated_at": r.generated_at.isoformat()+"Z", "source": r.source})
    hitter_ids = {identity(r["mlb_player_id"]) for r in canonical if r["player_type"] == "batter"}
    pitcher_ids = {identity(r["mlb_player_id"]) for r in canonical if r["player_type"] == "pitcher"}
    pitcher_ids.update(identity(g[f"{side}_pitcher"]["id"]) for g in games.values()
                       for side in ("home", "away") if (g.get(f"{side}_pitcher") or {}).get("id"))
    hitters = bounded_pitches(session, hitter_ids, "batter", target_date)
    pitchers = bounded_pitches(session, pitcher_ids, "pitcher", target_date)
    starts = defaultdict(list)
    # Read only pitcher lines, not large Final payloads/scoring plays for sixty days.
    finals = session.execute(select(
        FinalGameSnapshot.payload_json["boxscore"]["away"]["pitchers"].label("away"),
        FinalGameSnapshot.payload_json["boxscore"]["home"]["pitchers"].label("home"),
    ).where(FinalGameSnapshot.official_date < target_date,
        FinalGameSnapshot.official_date >= target_date-timedelta(days=60),
        FinalGameSnapshot.finalized_at <= captured).order_by(
            FinalGameSnapshot.official_date.desc(), FinalGameSnapshot.game_pk.desc())).mappings()
    for final in finals:
        for side in ("home", "away"):
            appearances = final[side] or []
            if appearances and appearances[0].get("id") in pitcher_ids:
                starts[appearances[0]["id"]].append(appearances[0])
    results = defaultdict(list)
    duplicates = set()
    for raw in canonical:
        try:
            pk, pid = identity(raw["game_pk"]), identity(raw["mlb_player_id"])
            role, side = raw["player_type"], raw["team_side"]
            key = (pk, pid, role)
            if key in duplicates:
                raise ValueError("Duplicate player/game/type")
            duplicates.add(key)
            if side not in {"home", "away"}:
                raise ValueError("Missing canonical team side")
            game = games[pk]
            opposing = "away" if side == "home" else "home"
            team, opponent = game[f"{side}_team"], game[f"{opposing}_team"]
            if identity(raw["team_id"]) != identity(team["id"]):
                raise ValueError("Player attached to wrong team")
            starter = game.get(f"{opposing}_pitcher") or {}
            opponent_id = identity(starter["id"]) if starter.get("id") else None
            profiles = _projection_profiles(game)
            shadow = _shadow(game)
            players = (shadow.get("player_projections") or {}).get("players") or []
            source = next(p for p in players if identity(p.get("mlb_player_id") or p.get("player_id")) == pid and p.get("player_type") == role)
            summaries = source.get("metrics") or {}
            means = {name: number(summary.get("mean")) for name,summary in summaries.items() if isinstance(summary, dict)}
            if role == "batter":
                if means.get("hits") is None and all(means.get(k) is not None for k in ("singles","doubles","triples","home_runs")):
                    means["hits"] = sum(means[k] for k in ("singles","doubles","triples","home_runs"))
                if means.get("total_bases") is None and all(means.get(k) is not None for k in ("singles","doubles","triples","home_runs")):
                    means["total_bases"] = sum(means[k]*w for k,w in (("singles",1),("doubles",2),("triples",3),("home_runs",4)))
            pitch_rows = hitters.get(pid, []) if role == "batter" else pitchers.get(pid, [])
            windows, trend = process_windows(pitch_rows, role)
            own = current.get(pid)
            own_ready = own is not None and captured-own.updated_at <= timedelta(hours=36)
            metrics = {k: getattr(own, k) for k in ("xwoba", "xba", "exit_velocity", "launch_angle", "hard_hit_rate", "barrel_rate", "strikeout_rate", "walk_rate", "iso", "obp", "slg", "plate_appearances", "model_score", "confidence")} if own else {}
            if metrics.get("plate_appearances") is not None and not 0 <= metrics["plate_appearances"] <= 1500:
                own_ready = False
            hand = pitch_rows[0].get("stand") if role == "batter" and pitch_rows else None
            opposing_pitches = pitchers.get(opponent_id, [])
            starter_hand = opposing_pitches[0].get("p_throws") if opposing_pitches else None
            observed_hands = {p.get("stand") for p in pitch_rows if p.get("stand") in {"L", "R"}}
            if (hand == "S" or observed_hands == {"L", "R"}) and starter_hand in {"L", "R"}:
                hand = "L" if starter_hand == "R" else "R"
            arsenal_feature = expected_arsenal(opposing_pitches, arsenal.get((pk,pid,opponent_id), []), hand) if role == "batter" else feature()
            location = location_compatibility(pitch_rows, opposing_pitches, hand) if role == "batter" else feature()
            team_hitters = [p for p in players if p.get("player_type") == "batter" and p.get("team_side") == side]
            pa_values = [number((p.get("metrics", {}).get("plate_appearances") or {}).get("mean")) for p in team_hitters]
            team_pa = sum(pa_values) if len(pa_values)==9 and all(v is not None for v in pa_values) else None
            starter_row = next((p for p in players if p.get("player_type")=="pitcher" and str(p.get("mlb_player_id") or p.get("player_id"))==str(opponent_id)), {})
            starter_bf = number((starter_row.get("metrics", {}).get("batters_faced") or {}).get("mean"))
            pa = means.get("plate_appearances")
            workload_feature = workload(starts.get(pid, [])) if role == "pitcher" else feature()
            env = environment(profiles["environment"])
            bullpen_profile = profiles[f"{opposing}_bullpen"]
            bullpen = feature(number((bullpen_profile.get("bat_missing") or {}).get("k_rate")),
                source="model_projection_bullpen", exposure=exposure(pa, starter_bf, team_pa),
                profile=bullpen_profile, fatigue=None, available_handedness_mix=None)
            lineup = lineups.get((pk,pid))
            if lineup and lineup.team_id != team["id"]:
                raise ValueError("Lineup source belongs to a different team")
            row = {"player_id": pid, "player_name": raw.get("full_name"), "player_type": role,
                "game_pk": pk, "date": target_date.isoformat(), "game_time": game["game_time"],
                "team_id": team["id"], "team": team.get("name"), "opponent_id": opponent["id"],
                "opponent": opponent.get("name"), "team_side": side,
                "opposing_starter_id": opponent_id, "opposing_starter_name": starter.get("name"),
                "starter_handedness": starter_hand, "batting_order": source.get("batting_order") if source.get("batting_order") is not None else (lineup.lineup_position if lineup else None),
                "lineup_status": game.get("lineup_status"), "lineup_confirmed_at": (lineup.generated_at.isoformat()+"Z") if lineup and lineup.lineup_status=="confirmed" else None,
                "baseline": means, "baseline_distributions": summaries,
                "baseline_model_version": (shadow.get("player_projections") or {}).get("model_version") or game.get("model_version"),
                "baseline_authority": {k: (shadow.get("player_projections") or {}).get(k) for k in ("authoritative", "authoritative_source", "run_id", "schema_version")},
                "simulation_count": raw.get("simulation_count"), "artifact_version": payload.get("workspace_contract"),
                "projection_generated_at": source_time.isoformat()+"Z", "feature_version": FEATURE_VERSION,
                "source_timestamps": {"model_projections": source_time.isoformat()+"Z",
                    "dashboard_current": own.updated_at.isoformat()+"Z" if own else None,
                    "statcast_event_cutoff_exclusive": target_date.isoformat()},
                "provenance": "true_point_in_time_snapshot", "current_analytics": metrics,
                "player_trends": trends.get(pid, []), "opportunity_windows": windows,
                "features": {"opportunity": feature(pa if role=="batter" else means.get("batters_faced"),
                    source="model_projections", distribution=summaries.get("plate_appearances" if role=="batter" else "batters_faced")),
                    "process": feature(number(metrics.get("xwoba")) if own_ready else None, n=metrics.get("plate_appearances") or 0,
                        status=None if own_ready else "stale_or_unavailable", source="dashboard_player_current",
                        actual_slg=metrics.get("slg"), actual_obp=metrics.get("obp")),
                    "trend": trend, "arsenal": arsenal_feature, "location": location, "bullpen": bullpen,
                    "environment": env, "workload": workload_feature,
                    "opponent_adjusted_trend": opponent_adjusted(pitch_rows,role,current,captured)}}
            validate_player(row)
            results[pk].append(row)
        except (ValueError, TypeError, KeyError, StopIteration) as exc:
            rejected.append({"game_pk": raw.get("game_pk"), "player_id": raw.get("mlb_player_id"), "reason": str(exc)})
    # Fail the entire game when a row is corrupt; partial lineups cannot silently masquerade as complete slates.
    for rejection in rejected:
        results.pop(rejection["game_pk"], None)
    return results, rejected
