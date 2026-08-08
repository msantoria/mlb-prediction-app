"""
FastAPI application for the MLB prediction engine.

Endpoints:
    GET  /health
    GET  /matchups?date=YYYY-MM-DD
    GET  /matchup/{game_pk}              Full detail: pitchers, lineup, splits, game log
    GET  /matchup/{game_pk}/competitive  Lineup-level competitive matchup matrix
    GET  /pitcher/{id}                   Aggregate + arsenal
    GET  /pitcher/{id}/rolling           L15G-L150G rolling stats
    GET  /pitcher/{id}/game-log          Recent game-by-game appearances
    GET  /batter/{id}                    Aggregate + platoon splits (multi-season)
    GET  /batter/{id}/rolling            L10-L1000 AB rolling stats
    GET  /batter/{id}/splits             Multi-season vsL/vsR splits
    GET  /batter/{id}/at-bats            Chronological at-bat session
    GET  /standings                      MLB AL/NL standings
    GET  /lineup/{team_id}               Day-of lineup from MLB Stats API
    GET  /players/search                 Search players by name
    GET  /players/all                    All active MLB players for a season
    GET  /team/{team_id}/roster          Full roster for a team
    POST /predict                        Score a specific pitcher vs batter
    GET  /live/scoreboard                Today's games: scores, status, weather, probable pitchers
    GET  /live/game/{pk}                 Current play state: batter, pitcher, count, runners, pitch sequence
    GET  /live/game/{pk}/boxscore        In-game pitcher lines + batter lines (AB/H/R/RBI/K)
    GET  /live/game/{pk}/plays           Recent play-by-play with hit data (exit velo, distance)
    GET  /live/game/{pk}/linescore       Inning-by-inning runs/hits/errors + game decisions
    GET  /final                          Durable completed-game snapshots for one MLB date
    GET  /final/game/{pk}                Immutable full box score, summary, and scoring plays
"""

from __future__ import annotations

import datetime
import os
import re
import time
import subprocess
from typing import Any, Dict, List, Optional, Tuple

import requests as _req

try:
    from fastapi import BackgroundTasks, FastAPI, HTTPException, Query
    from fastapi.middleware.cors import CORSMiddleware
    from fastapi.staticfiles import StaticFiles
    from pydantic import BaseModel

    _FASTAPI = True
except ImportError:
    FastAPI = None
    BackgroundTasks = None
    HTTPException = Exception
    CORSMiddleware = None
    StaticFiles = None
    BaseModel = object
    Query = None
    _FASTAPI = False

from .database import (
    StatcastEvent,
    BatterPitchTypeMatchup,
    get_engine,
    create_tables,
    get_session,
)
from .matchup_generator import generate_matchups_for_date
from .db_utils import (
    get_pitcher_aggregate,
    get_pitcher_aggregate_with_fallback,
    get_batter_aggregate,
    get_batter_aggregate_with_fallback,
    get_pitch_arsenal,
    get_pitch_arsenal_with_fallback,
    get_player_split,
    get_player_splits_multi_season,
    get_team_split,
    get_pitcher_rolling_by_games,
    get_batter_rolling_by_games,
    get_batter_rolling_by_abs,
    get_batter_at_bats,
    get_pitcher_game_log,
    get_pitcher_multi_season,
    get_batter_multi_season,
)
from .scoring import compute_win_probability, score_individual_matchup, get_park_factor
from .statcast_utils import fetch_pitch_arsenal_leaderboard
from .hitting_matchups import build_batter_pitch_type_summary
from .odds_provider import (
    fetch_draftkings_odds,
    fetch_draftkings_event_odds,
    fetch_draftkings_events,
)

from .batter_routes import router as batter_router
from .offense_profile_aggregation import build_projected_lineup_offense_profile
from .environment_profile import compute_environment_profile
from .bullpen_profile import build_bullpen_profile
from .pitcher_profile import compute_pitcher_profile
from .matchup_analysis import build_matchup_analysis
from .simulation.inning_simulator import simulate_half_innings
from .matchup_workspace_builder import (
    build_lineup_pa_outcome_model,
    build_bullpen_pa_outcome_model,
    build_game_simulation,
    build_bullpen_adjusted_game_simulation,
)
from mlb_app.simulation.game_simulation_builder import build_game_simulation as build_shared_game_simulation
from .draftkings_projection_routes import (
    router as draftkings_projection_router,
)
from .daily_odds_routes import router as daily_odds_router
from .simulation.inning_simulator import simulate_half_innings
from .model_projection_routes import router as model_projection_router
from .ai_data_assistant_routes import router as ai_data_assistant_router
from .news_routes import router as news_router
from .starting_pitcher_arsenal_refresh import refresh_starting_pitcher_arsenal
from .pitcher_profile_store import (
    get_pitcher_profile_overview,
    get_pitcher_profile_arsenal,
    get_pitcher_profile_recent_games,
    serialize_pitcher_profile_overview,
    serialize_pitcher_profile_arsenal,
    serialize_pitcher_profile_recent_games,
)
from .sportsbook_routes import router as sportsbook_router
from .model_tracker_routes import router as model_tracker_router
from .admin_routes import router as admin_router
from .final_game_snapshots import (
    FinalGameSnapshot,
    build_game_boxscore_payload,
    get_final_snapshot,
    is_final_feed,
    is_final_status,
    list_final_snapshots,
    persist_final_snapshot,
    serialize_snapshot,
)

MLB_STATS_BASE = "https://statsapi.mlb.com/api/v1"
MLB_LIVE_FEED_BASE = "https://statsapi.mlb.com/api/v1.1/game"

MATCHUP_SNAPSHOT_CACHE: Dict[str, List[Dict[str, Any]]] = {}
LIVE_CACHE: Dict[str, Dict[str, Any]] = {}

HIT_EVENTS = {"single", "double", "triple", "home_run"}

OUTCOME_EVENTS = {
    "single",
    "double",
    "triple",
    "home_run",
    "strikeout",
    "strikeout_double_play",
    "walk",
    "intent_walk",
    "hit_by_pitch",
    "field_out",
    "force_out",
    "double_play",
    "grounded_into_double_play",
    "fielders_choice",
    "fielders_choice_out",
    "sac_fly",
    "sac_bunt",
    "catcher_interf",
    "catcher_interference",
}

NON_AB_EVENTS = {
    "walk",
    "intent_walk",
    "hit_by_pitch",
    "sac_bunt",
    "sac_fly",
    "catcher_interf",
    "catcher_interference",
}

STRIKEOUT_EVENTS = {"strikeout", "strikeout_double_play"}
WALK_EVENTS = {"walk", "intent_walk", "hit_by_pitch"}


def _get_session():
    db_url = os.getenv("DATABASE_URL", "sqlite:///mlb.db")
    engine = get_engine(db_url)
    create_tables(engine)
    return get_session(engine)


def _safe_float(val) -> Optional[float]:
    try:
        return float(val) if val is not None else None
    except (TypeError, ValueError):
        return None


def _safe_int(val) -> Optional[int]:
    try:
        return int(val) if val is not None else None
    except (TypeError, ValueError):
        return None


def _average(values: List[Optional[float]], digits: int = 3) -> Optional[float]:
    nums = [v for v in values if v is not None]
    if not nums:
        return None
    return round(sum(nums) / len(nums), digits)


def _normalize_pitch_label(pitch_type: Optional[str], pitch_name: Optional[str]) -> str:
    return pitch_name or pitch_type or "Unknown"


def _normalize_rate(value: Optional[float]) -> Optional[float]:
    if value is None:
        return None
    if value > 1:
        return round(value / 100.0, 4)
    return round(value, 4)


def _build_date_window() -> Dict[str, str]:
    today = datetime.date.today()
    return {
        "yesterday": (today - datetime.timedelta(days=1)).isoformat(),
        "today": today.isoformat(),
        "tomorrow": (today + datetime.timedelta(days=1)).isoformat(),
    }


def _extract_weather(game: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    weather = game.get("weather") or {}
    condition = weather.get("condition")
    temp = weather.get("temp")
    wind = weather.get("wind")

    if condition is None and temp is None and wind is None:
        return None

    return {
        "condition": condition,
        "temp_f": temp,
        "wind": wind,
    }


def _live_cache_get(key: str) -> Optional[Any]:
    entry = LIVE_CACHE.get(key)
    if entry and time.time() < entry["expires_at"]:
        return entry["data"]
    return None


def _live_cache_set(key: str, data: Any, ttl: int = 30) -> None:
    LIVE_CACHE[key] = {
        "data": data,
        "expires_at": time.time() + ttl,
    }


def _request_json(url: str, params: Optional[Dict[str, Any]] = None, timeout: int = 20) -> Dict[str, Any]:
    resp = _req.get(url, params=params, timeout=timeout)
    resp.raise_for_status()
    return resp.json()


def _fetch_team_splits_live(team_id: int, season: int) -> Dict[str, Any]:
    """Fetch vsL/vsR team hitting splits directly from MLB Stats API."""
    result = {"vsL": None, "vsR": None}

    for sit_code, key in [("vl", "vsL"), ("vr", "vsR")]:
        try:
            data = _request_json(
                f"{MLB_STATS_BASE}/teams/{team_id}/stats",
                params={
                    "stats": "statSplits",
                    "group": "hitting",
                    "season": season,
                    "sitCodes": sit_code,
                },
                timeout=15,
            )
            stats = data.get("stats", [])
            splits = stats[0].get("splits", []) if stats else []
            if not splits:
                continue

            stat = splits[0].get("stat", {})
            pa = stat.get("plateAppearances") or 0
            k = stat.get("strikeOuts") or 0
            bb = stat.get("baseOnBalls") or 0

            result[key] = {
                "pa": pa,
                "batting_avg": _safe_float(stat.get("avg")),
                "on_base_pct": _safe_float(stat.get("obp")),
                "slugging_pct": _safe_float(stat.get("slg")),
                "home_runs": stat.get("homeRuns"),
                "k_pct": round(k / pa, 3) if pa > 0 else None,
                "bb_pct": round(bb / pa, 3) if pa > 0 else None,
            }
        except Exception:
            continue

    return result


def _fetch_live_pitch_arsenal(pitcher_id: int, current_season: int) -> Tuple[List[Dict[str, Any]], Optional[int]]:
    """Fallback arsenal from Savant leaderboard if DB does not yet have rows."""
    season_candidates = [current_season, current_season - 1, current_season - 2]

    for season in season_candidates:
        try:
            df = fetch_pitch_arsenal_leaderboard(season, min_pitches=1)
            if df is None or df.empty:
                continue

            pid_col = next((c for c in ["pitcher", "player_id", "mlbam_id"] if c in df.columns), None)
            if not pid_col:
                continue

            rows = df[df[pid_col].astype(str) == str(pitcher_id)]
            if rows.empty:
                continue

            arsenal_rows: List[Dict[str, Any]] = []
            for _, row in rows.iterrows():
                pitch_type = row.get("pitch_type")
                if not pitch_type:
                    continue

                arsenal_rows.append(
                    {
                        "pitch_type": pitch_type,
                        "pitch_name": row.get("pitch_name"),
                        "usage_pct": _normalize_rate(_safe_float(row.get("pitch_usage") or row.get("usage_pct"))),
                        "whiff_pct": _normalize_rate(_safe_float(row.get("whiff_percent") or row.get("whiff_pct"))),
                        "strikeout_pct": _normalize_rate(_safe_float(row.get("k_percent") or row.get("strikeout_pct"))),
                        "rv_per_100": _safe_float(row.get("run_value_per_100") or row.get("rv_per_100")),
                        "xwoba": _safe_float(row.get("est_woba") or row.get("xwoba")),
                        "hard_hit_pct": _normalize_rate(_safe_float(row.get("hard_hit_percent") or row.get("hard_hit_pct"))),
                    }
                )

            arsenal_rows.sort(key=lambda r: r.get("usage_pct") or 0, reverse=True)
            if arsenal_rows:
                return arsenal_rows, season
        except Exception:
            continue

    return [], None


def _normalize_arsenal_to_dicts(raw_arsenal) -> List[Dict[str, Any]]:
    return [
        {
            "pitch_type": r.pitch_type,
            "pitch_name": r.pitch_name,
            "pitch_count": r.pitch_count,
            "usage_pct": _normalize_rate(r.usage_pct),
            "whiff_pct": _normalize_rate(r.whiff_pct),
            "strikeout_pct": _normalize_rate(r.strikeout_pct),
            "rv_per_100": r.rv_per_100,
            "xwoba": r.xwoba,
            "hard_hit_pct": _normalize_rate(r.hard_hit_pct),
        }
        for r in raw_arsenal
    ]


def _dedupe_statcast_events(events: List[StatcastEvent]) -> List[StatcastEvent]:
    """
    Remove duplicate Statcast pitch rows before any matchup or player stat calculation.

    Primary key uses MLB pitch identity when available:
        game_pk + at_bat_number + pitch_number + pitcher_id + batter_id + pitch_type

    Fallback key is intentionally conservative for older rows missing game ordering fields.
    """
    seen = set()
    deduped: List[StatcastEvent] = []

    for event in events:
        if (
            event.game_pk is not None
            and event.at_bat_number is not None
            and event.pitch_number is not None
        ):
            key = (
                event.game_pk,
                event.at_bat_number,
                event.pitch_number,
                event.pitcher_id,
                event.batter_id,
                event.pitch_type,
            )
        else:
            key = (
                event.game_date,
                event.pitcher_id,
                event.batter_id,
                event.pitch_type,
                event.events,
                event.release_speed,
                event.release_spin_rate,
                event.launch_speed,
                event.launch_angle,
                event.balls,
                event.strikes,
                event.inning,
                event.inning_topbot,
                event.outs_when_up,
            )

        if key in seen:
            continue

        seen.add(key)
        deduped.append(event)

    return deduped


def _terminal_events(events: List[StatcastEvent]) -> List[StatcastEvent]:
    return [event for event in events if event.events and event.events in OUTCOME_EVENTS]


def _official_ab_events(events: List[StatcastEvent]) -> List[StatcastEvent]:
    return [event for event in events if event.events and event.events not in NON_AB_EVENTS]


def _batting_avg_from_terminal_events(events: List[StatcastEvent]) -> Optional[float]:
    terminal = _terminal_events(_dedupe_statcast_events(events))
    if not terminal:
        return None

    ab_events = _official_ab_events(terminal)
    ab = len(ab_events)
    if ab == 0:
        return None

    hits = sum(1 for event in terminal if event.events in HIT_EVENTS)
    return round(hits / ab, 3)


def _statcast_batting_avg(events: List[StatcastEvent]) -> Optional[float]:
    return _batting_avg_from_terminal_events(events)


def _summarize_batter_events(events_raw: List[StatcastEvent]) -> Dict[str, Any]:
    events = _dedupe_statcast_events(events_raw)
    terminal = _terminal_events(events)

    pa = len(terminal)
    ab_events = _official_ab_events(terminal)
    ab = len(ab_events)

    hits = sum(1 for event in terminal if event.events in HIT_EVENTS)
    strikeouts = sum(1 for event in terminal if event.events in STRIKEOUT_EVENTS)
    walks = sum(1 for event in terminal if event.events in WALK_EVENTS)
    home_runs = sum(1 for event in terminal if event.events == "home_run")

    ev_vals = [event.launch_speed for event in terminal if event.launch_speed is not None]
    la_vals = [event.launch_angle for event in terminal if event.launch_angle is not None]
    xwoba_vals = [
        getattr(event, "estimated_woba_using_speedangle", None)
        for event in terminal
        if getattr(event, "estimated_woba_using_speedangle", None) is not None
    ]
    xba_vals = [
        getattr(event, "estimated_ba_using_speedangle", None)
        for event in terminal
        if getattr(event, "estimated_ba_using_speedangle", None) is not None
    ]

    hard_hits = sum(1 for value in ev_vals if value >= 95)
    barrels = sum(
        1
        for event in terminal
        if event.launch_speed is not None
        and event.launch_angle is not None
        and event.launch_speed >= 98
        and 8 <= event.launch_angle <= 50
    )

    return {
        "raw_rows": len(events_raw),
        "deduped_rows": len(events),
        "duplicate_rows_removed": max(len(events_raw) - len(events), 0),
        "pa": pa,
        "ab": ab,
        "hits": hits,
        "strikeouts": strikeouts,
        "walks": walks,
        "hr": home_runs,
        "batting_avg": round(hits / ab, 3) if ab else None,
        "k_pct": round(strikeouts / pa, 3) if pa else None,
        "bb_pct": round(walks / pa, 3) if pa else None,
        "avg_exit_velocity": round(sum(ev_vals) / len(ev_vals), 1) if ev_vals else None,
        "max_exit_velocity": round(max(ev_vals), 1) if ev_vals else None,
        "avg_launch_angle": round(sum(la_vals) / len(la_vals), 1) if la_vals else None,
        "hard_hit_pct": round(hard_hits / len(ev_vals), 3) if ev_vals else None,
        "barrel_pct": round(barrels / pa, 3) if pa else None,
        "batted_ball_count": len(ev_vals),
        "hard_hit_count": hard_hits,
        "xwoba": round(sum(xwoba_vals) / len(xwoba_vals), 3) if xwoba_vals else None,
        "xba": round(sum(xba_vals) / len(xba_vals), 3) if xba_vals else None,
    }


def _edge_score_from_components(
    batter_ba: Optional[float],
    batter_xwoba: Optional[float],
    pitcher_xwoba: Optional[float],
    pitcher_hard_hit_pct: Optional[float],
    usage_pct: Optional[float],
) -> float:
    score = 0.0

    if batter_ba is not None:
        score += (batter_ba - 0.245) * 4.0

    if batter_xwoba is not None:
        score += (batter_xwoba - 0.320) * 5.0

    if pitcher_xwoba is not None:
        score -= (pitcher_xwoba - 0.320) * 5.0

    if pitcher_hard_hit_pct is not None:
        score -= (pitcher_hard_hit_pct - 0.35) * 2.0

    if usage_pct is not None:
        score *= max(0.35, min(1.0, usage_pct))

    return round(score, 3)


def _confidence_from_sample(pa: int, usage_pct: Optional[float]) -> float:
    pa_component = min(1.0, pa / 12.0)
    usage_component = min(1.0, max(0.25, usage_pct or 0.0))
    return round(min(1.0, pa_component * usage_component + (0.25 if pa >= 3 else 0.0)), 3)


def _stored_batter_pitch_type_summary(
    session,
    batter_id: int,
    opposing_pitcher_id: int,
    pitch_type: Optional[str],
    target_date: Optional[str] = None,
) -> Optional[Dict[str, Any]]:
    """
    Preferred Batter vs Arsenal source from the restored hittingMatchups table.

    Exact target_date is preferred when present. If the exact target date is
    missing, this intentionally falls back to the latest row for
    batter + opposing pitcher + pitch type so the cards do not drop back to
    tiny live Statcast fallback samples.
    """
    if not batter_id or not opposing_pitcher_id or not pitch_type:
        return None

    base_query = session.query(BatterPitchTypeMatchup).filter(
        BatterPitchTypeMatchup.batter_id == batter_id,
        BatterPitchTypeMatchup.opposing_pitcher_id == opposing_pitcher_id,
        BatterPitchTypeMatchup.pitch_type == pitch_type,
    )

    record = None

    if target_date:
        try:
            parsed_date = datetime.date.fromisoformat(str(target_date)[:10])
            record = (
                base_query.filter(BatterPitchTypeMatchup.target_date == parsed_date)
                .order_by(
                    BatterPitchTypeMatchup.refreshed_at.desc().nullslast(),
                    BatterPitchTypeMatchup.id.desc(),
                )
                .first()
            )
        except Exception:
            record = None

    if record is None:
        record = (
            base_query.order_by(
                BatterPitchTypeMatchup.target_date.desc().nullslast(),
                BatterPitchTypeMatchup.refreshed_at.desc().nullslast(),
                BatterPitchTypeMatchup.id.desc(),
            )
            .first()
        )

    if not record:
        return None

    avg_ev = record.avg_exit_velocity if record.avg_exit_velocity is not None else record.avg_ev
    avg_la = record.avg_launch_angle if record.avg_launch_angle is not None else record.avg_la
    hard_hit_pct = record.hard_hit_pct if record.hard_hit_pct is not None else record.hardhit_pct

    return {
        "source": "batter_pitch_type_matchups",
        "row_source": record.source,
        "target_date": record.target_date.isoformat() if record.target_date else None,
        "date_start": record.date_start.isoformat() if record.date_start else None,
        "date_end": record.date_end.isoformat() if record.date_end else None,
        "days_back": record.days_back,
        "refreshed_at": record.refreshed_at.isoformat() if record.refreshed_at else None,
        "raw_rows": record.raw_rows,
        "deduped_rows": record.deduped_rows,
        "duplicate_rows_removed": record.duplicate_rows_removed,
        "pitches_seen": record.pitches_seen,
        "swings": record.swings,
        "whiffs": record.whiffs,
        "strikeouts": record.strikeouts,
        "putaway_swings": record.putaway_swings,
        "two_strike_pitches": record.two_strike_pitches,
        "pa": record.pa,
        "pa_ended": record.pa_ended,
        "ab": record.ab,
        "hits": record.hits,
        "batting_avg": record.batting_avg,
        "xwoba": record.xwoba,
        "xba": record.xba,
        "avg_ev": avg_ev,
        "avg_exit_velocity": avg_ev,
        "avg_la": avg_la,
        "avg_launch_angle": avg_la,
        "batted_ball_count": record.batted_ball_count,
        "hard_hit_count": record.hard_hit_count,
        "whiff_pct": _normalize_rate(record.whiff_pct),
        "k_pct": _normalize_rate(record.k_pct),
        "putaway_pct": _normalize_rate(record.putaway_pct),
        "hardhit_pct": _normalize_rate(hard_hit_pct),
        "hard_hit_pct": _normalize_rate(hard_hit_pct),
        "sample_size": record.pitches_seen or record.pa_ended or record.pa or 0,
    }


def _player_vs_pitch_type_summary(
    session,
    batter_id: int,
    pitch_type: Optional[str],
    since_year: int = 2024,
) -> Dict[str, Any]:
    """How a batter performs vs a pitch type across all pitchers since since_year."""
    start_date = datetime.date(since_year, 1, 1)

    events_raw = (
        session.query(StatcastEvent)
        .filter(
            StatcastEvent.batter_id == batter_id,
            StatcastEvent.pitch_type == pitch_type,
            StatcastEvent.game_date >= start_date,
        )
        .all()
    )

    summary = _summarize_batter_events(events_raw)
    summary["date_start"] = start_date.isoformat()

    event_dates = [event.game_date for event in _dedupe_statcast_events(events_raw) if event.game_date]
    summary["date_end"] = max(event_dates).isoformat() if event_dates else None

    return summary


def _head_to_head_summary(session, batter_id: int, pitcher_id: int, season: int) -> Dict[str, Any]:
    events_raw = (
        session.query(StatcastEvent)
        .filter(
            StatcastEvent.batter_id == batter_id,
            StatcastEvent.pitcher_id == pitcher_id,
            StatcastEvent.game_date >= datetime.date(season, 1, 1),
        )
        .all()
    )

    summary = _summarize_batter_events(events_raw)

    return {
        "pa": summary["pa"],
        "ab": summary["ab"],
        "hits": summary["hits"],
        "batting_avg": summary["batting_avg"],
        "xwoba": summary["xwoba"],
        "xba": summary.get("xba"),
        "avg_exit_velocity": summary["avg_exit_velocity"],
        "avg_launch_angle": summary["avg_launch_angle"],
        "raw_rows": summary["raw_rows"],
        "deduped_rows": summary["deduped_rows"],
        "duplicate_rows_removed": summary["duplicate_rows_removed"],
    }


def _build_competitive_matchup(
    session,
    batter_id: int,
    batter_name: str,
    batting_order: int,
    opposing_pitcher_id: int,
    season: int,
    _preloaded_arsenal: Optional[List[Dict[str, Any]]] = None,
    _preloaded_arsenal_season: Optional[int] = None,
    target_date: Optional[str] = None,
) -> Dict[str, Any]:
    if _preloaded_arsenal is not None:
        arsenal_list = _preloaded_arsenal
        arsenal_season = _preloaded_arsenal_season
    else:
        raw_arsenal, arsenal_season = get_pitch_arsenal_with_fallback(session, opposing_pitcher_id, season)
        arsenal_list = _normalize_arsenal_to_dicts(raw_arsenal)

        if not arsenal_list:
            live_arsenal, live_season = _fetch_live_pitch_arsenal(opposing_pitcher_id, season)
            arsenal_list = live_arsenal
            arsenal_season = live_season

    head_to_head = _head_to_head_summary(session, batter_id, opposing_pitcher_id, season)

    pitch_type_matrix: List[Dict[str, Any]] = []
    for pitch in arsenal_list:
        pitch_type = pitch.get("pitch_type")

        batter_vs_type = _stored_batter_pitch_type_summary(
            session=session,
            batter_id=batter_id,
            opposing_pitcher_id=opposing_pitcher_id,
            pitch_type=pitch_type,
            target_date=target_date,
        )

        if batter_vs_type is None:
            batter_vs_type = {
                "source": "missing_batter_pitch_type_matchups",
                "aggregation_source": "raw_statcast_events",
                "lookup_level": None,
                "requested_opposing_pitcher_id": opposing_pitcher_id,
                "stored_opposing_pitcher_id": None,
                "pitch_type": pitch_type,
                "pitches_seen": 0,
                "swings": 0,
                "whiffs": 0,
                "strikeouts": 0,
                "pa": 0,
                "pa_ended": 0,
                "ab": 0,
                "hits": 0,
                "batting_avg": None,
                "xwoba": None,
                "xba": None,
                "avg_exit_velocity": None,
                "avg_launch_angle": None,
                "whiff_pct": None,
                "k_pct": None,
                "putaway_pct": None,
                "hard_hit_pct": None,
                "sample_size": 0,
            }

        pa = batter_vs_type.get("pa_ended") or batter_vs_type.get("pa") or batter_vs_type.get("sample_size") or 0

        edge_score = _edge_score_from_components(
            batter_ba=batter_vs_type.get("batting_avg"),
            batter_xwoba=batter_vs_type.get("xwoba"),
            pitcher_xwoba=pitch.get("xwoba"),
            pitcher_hard_hit_pct=pitch.get("hard_hit_pct"),
            usage_pct=pitch.get("usage_pct"),
        )

        confidence = _confidence_from_sample(pa, pitch.get("usage_pct"))

        pitch_type_matrix.append(
            {
                "pitch_type": _normalize_pitch_label(pitch.get("pitch_type"), pitch.get("pitch_name")),
                "raw_pitch_type": pitch.get("pitch_type"),
                "pitcher_usage_pct": pitch.get("usage_pct") or 0.0,
                "pitcher_pitch_count": pitch.get("pitch_count"),
                "pitcher_whiff_pct": pitch.get("whiff_pct"),
                "pitcher_strikeout_pct": pitch.get("strikeout_pct"),
                "pitcher_xwoba": pitch.get("xwoba"),
                "pitcher_hard_hit_pct": pitch.get("hard_hit_pct"),
                "batter_vs_type": batter_vs_type,
                "edge_score": edge_score,
                "confidence": confidence,
            }
        )

    pitch_type_matrix.sort(key=lambda row: row["pitcher_usage_pct"], reverse=True)

    biggest_edge = max(pitch_type_matrix, key=lambda row: row["edge_score"], default=None)
    biggest_weakness = min(pitch_type_matrix, key=lambda row: row["edge_score"], default=None)

    return {
        "batter_id": batter_id,
        "batter_name": batter_name,
        "batting_order": batting_order,
        "matchup": {
            "head_to_head": head_to_head,
            "arsenal_season": arsenal_season,
            "pitch_type_matrix": pitch_type_matrix,
            "summary": {
                "biggest_edge": biggest_edge["pitch_type"] if biggest_edge and biggest_edge["edge_score"] > 0 else None,
                "biggest_weakness": biggest_weakness["pitch_type"] if biggest_weakness and biggest_weakness["edge_score"] < 0 else None,
            },
        },
    }

def _fetch_batter_live_data(player_id: int, season: int) -> Dict[str, Any]:
    """Fetch player info, season stats, vsL/vsR splits, and year-by-year from MLB Stats API."""
    out: Dict[str, Any] = {
        "player_info": None,
        "season_stats": None,
        "splits": {"vsL": None, "vsR": None},
        "year_by_year": [],
    }

    try:
        data = _request_json(
            f"{MLB_STATS_BASE}/people/{player_id}",
            params={"hydrate": "currentTeam"},
            timeout=10,
        )
        people = data.get("people") or []
        if people:
            player = people[0]
            out["player_info"] = {
                "name": player.get("fullName"),
                "position": (player.get("primaryPosition") or {}).get("abbreviation"),
                "team": (player.get("currentTeam") or {}).get("name"),
                "bats": (player.get("batSide") or {}).get("code"),
                "throws": (player.get("pitchHand") or {}).get("code"),
                "birth_date": player.get("birthDate"),
                "mlb_debut": player.get("mlbDebutDate"),
            }
    except Exception:
        pass

    def _parse_stat(stat: Dict[str, Any]) -> Dict[str, Any]:
        pa = stat.get("plateAppearances") or 0
        k = stat.get("strikeOuts") or 0
        bb = stat.get("baseOnBalls") or 0

        return {
            "g": stat.get("gamesPlayed"),
            "ab": stat.get("atBats"),
            "pa": pa,
            "r": stat.get("runs"),
            "h": stat.get("hits"),
            "doubles": stat.get("doubles"),
            "triples": stat.get("triples"),
            "hr": stat.get("homeRuns"),
            "rbi": stat.get("rbi"),
            "sb": stat.get("stolenBases"),
            "bb": bb,
            "k": k,
            "batting_avg": _safe_float(stat.get("avg")),
            "on_base_pct": _safe_float(stat.get("obp")),
            "slugging_pct": _safe_float(stat.get("slg")),
            "ops": _safe_float(stat.get("ops")),
            "k_pct": round(k / pa, 3) if pa > 0 else None,
            "bb_pct": round(bb / pa, 3) if pa > 0 else None,
            "home_runs": stat.get("homeRuns"),
        }

    try:
        data = _request_json(
            f"{MLB_STATS_BASE}/people/{player_id}/stats",
            params={
                "stats": "season",
                "group": "hitting",
                "season": season,
            },
            timeout=10,
        )
        splits = (data.get("stats") or [{}])[0].get("splits", [])
        if splits:
            out["season_stats"] = _parse_stat(splits[0].get("stat", {}))
    except Exception:
        pass

    for sit_code, key in [("vl", "vsL"), ("vr", "vsR")]:
        try:
            data = _request_json(
                f"{MLB_STATS_BASE}/people/{player_id}/stats",
                params={
                    "stats": "statSplits",
                    "group": "hitting",
                    "season": season,
                    "sitCodes": sit_code,
                },
                timeout=10,
            )
            splits = (data.get("stats") or [{}])[0].get("splits", [])
            if splits:
                out["splits"][key] = _parse_stat(splits[0].get("stat", {}))
        except Exception:
            pass

    try:
        data = _request_json(
            f"{MLB_STATS_BASE}/people/{player_id}/stats",
            params={
                "stats": "yearByYear",
                "group": "hitting",
            },
            timeout=15,
        )
        splits = (data.get("stats") or [{}])[0].get("splits", [])
        for split in splits:
            year = split.get("season")
            if not year:
                continue
            row = _parse_stat(split.get("stat", {}))
            row["season"] = year
            out["year_by_year"].append(row)

        out["year_by_year"].sort(key=lambda row: row["season"], reverse=True)
    except Exception:
        pass

    return out


def _compute_batter_statcast(session, batter_id: int, since_year: int = 2024) -> Optional[Dict[str, Any]]:
    start_date = datetime.date(since_year, 1, 1)

    events_raw = (
        session.query(StatcastEvent)
        .filter(
            StatcastEvent.batter_id == batter_id,
            StatcastEvent.game_date >= start_date,
        )
        .all()
    )

    summary = _summarize_batter_events(events_raw)
    if summary["pa"] == 0:
        return None

    event_dates = [event.game_date for event in _dedupe_statcast_events(events_raw) if event.game_date]

    return {
        "pa": summary["pa"],
        "ab": summary["ab"],
        "hits": summary["hits"],
        "batting_avg": summary["batting_avg"],
        "k_pct": summary["k_pct"],
        "bb_pct": summary["bb_pct"],
        "hr": summary["hr"],
        "avg_exit_velocity": summary["avg_exit_velocity"],
        "max_exit_velocity": summary["max_exit_velocity"],
        "avg_launch_angle": summary["avg_launch_angle"],
        "hard_hit_pct": summary["hard_hit_pct"],
        "barrel_pct": summary["barrel_pct"],
        "xwoba": summary.get("xwoba"),
        "xba": summary.get("xba"),
        "batted_ball_count": summary["batted_ball_count"],
        "hard_hit_count": summary["hard_hit_count"],
        "raw_rows": summary["raw_rows"],
        "deduped_rows": summary["deduped_rows"],
        "duplicate_rows_removed": summary["duplicate_rows_removed"],
        "data_window": f"Since {since_year}",
        "date_start": start_date.isoformat(),
        "date_end": max(event_dates).isoformat() if event_dates else None,
        "sample_size": summary["pa"],
    }


def _fetch_roster_as_lineup(team_id: int, season: int) -> List[Dict[str, Any]]:
    try:
        data = _request_json(
            f"{MLB_STATS_BASE}/teams/{team_id}/roster",
            params={
                "rosterType": "active",
                "season": season,
            },
            timeout=15,
        )

        lineup = []
        for row in data.get("roster", []):
            position = row.get("position") or {}
            person = row.get("person") or {}

            if position.get("type", "").lower() == "pitcher":
                continue

            player_id = person.get("id")
            if not player_id:
                continue

            lineup.append(
                {
                    "id": player_id,
                    "fullName": person.get("fullName"),
                    "primaryPosition": {
                        "abbreviation": position.get("abbreviation"),
                    },
                }
            )

        return lineup
    except Exception:
        return []


def _game_date_candidates(game_date_iso: str) -> List[str]:
    candidates: List[str] = []

    if game_date_iso:
        try:
            utc_dt = datetime.datetime.fromisoformat(game_date_iso.replace("Z", "+00:00"))
            for offset_hours in (0, -4, -5, -6, -7, -8):
                candidate = (utc_dt + datetime.timedelta(hours=offset_hours)).date().isoformat()
                if candidate not in candidates:
                    candidates.append(candidate)
        except Exception:
            pass

    today = datetime.date.today().isoformat()
    if today not in candidates:
        candidates.append(today)

    return candidates


def _fetch_previous_completed_game_lineup(team_id: int, game_date_iso: str) -> List[Dict[str, Any]]:
    for candidate_date in _game_date_candidates(game_date_iso):
        try:
            start_date = (
                datetime.date.fromisoformat(candidate_date) - datetime.timedelta(days=7)
            ).isoformat()

            data = _request_json(
                f"{MLB_STATS_BASE}/schedule",
                params={
                    "startDate": start_date,
                    "endDate": candidate_date,
                    "teamId": team_id,
                    "hydrate": "lineups",
                    "sportId": 1,
                },
                timeout=15,
            )

            completed_games: List[Dict[str, Any]] = []
            for date_row in data.get("dates", []) or []:
                for game in date_row.get("games", []) or []:
                    status = (game.get("status") or {}).get("codedGameState")
                    if status == "F":
                        completed_games.append(game)

            completed_games.sort(key=lambda game: game.get("gameDate") or "", reverse=True)

            for game in completed_games:
                teams = game.get("teams", {})
                for side in ("home", "away"):
                    team = teams.get(side, {}).get("team", {})
                    if team.get("id") != team_id:
                        continue

                    lineup_key = "homePlayers" if side == "home" else "awayPlayers"
                    players = (game.get("lineups") or {}).get(lineup_key) or []
                    if players:
                        return players
        except Exception:
            continue

    return []


def _fetch_live_feed(game_pk: int) -> Optional[Dict[str, Any]]:
    """Fetch and TTL-cache the full MLB live feed for a single game.

    The live page needs near-real-time state, so this cache is intentionally
    short. The v1.1 feed is the primary source. The v1 path is kept as a
    fallback so one endpoint failure does not make the whole Live tab look
    empty.
    """
    cache_key = f"feed:{game_pk}"
    cached = _live_cache_get(cache_key)
    if cached is not None:
        return cached

    urls = [
        f"{MLB_LIVE_FEED_BASE}/{game_pk}/feed/live",
        f"{MLB_STATS_BASE}/game/{game_pk}/feed/live",
    ]

    for url in urls:
        try:
            data = _request_json(url, timeout=15)
            status = ((data.get("gameData") or {}).get("status") or {}).get("abstractGameState")
            ttl = 5 if status == "Live" else 20
            _live_cache_set(cache_key, data, ttl=ttl)
            return data
        except Exception:
            continue

    return None


def _snapshot_final_game(game_pk: int) -> Dict[str, Any]:
    """Persist one final feed without allowing snapshot failures to affect Live."""

    Session = _get_session()
    with Session() as session:
        existing = get_final_snapshot(session, game_pk)
        if existing is not None:
            return {"game_pk": game_pk, "status": "existing"}

    feed = _fetch_live_feed(game_pk)
    if feed is None:
        return {"game_pk": game_pk, "status": "unavailable"}
    if not is_final_feed(feed):
        return {"game_pk": game_pk, "status": "not_final"}

    try:
        with Session() as session:
            snapshot = persist_final_snapshot(session, feed)
            return {
                "game_pk": game_pk,
                "status": "snapshotted",
                "official_date": snapshot.official_date.isoformat(),
            }
    except Exception as exc:
        # Live and Final reads remain available even if persistence is
        # temporarily unavailable. The next request can retry safely.
        return {"game_pk": game_pk, "status": "error", "error": type(exc).__name__}


def _hydrate_final_snapshots_for_date(target_date: str) -> Dict[str, Any]:
    """Find completed games for a date and fill only missing snapshots."""

    try:
        schedule = _request_json(
            f"{MLB_STATS_BASE}/schedule",
            params={"sportId": 1, "date": target_date},
            timeout=15,
        )
    except Exception as exc:
        return {
            "attempted": 0,
            "snapshotted": 0,
            "errors": [{"status": "schedule_error", "error": type(exc).__name__}],
        }

    final_game_pks = []
    for date_entry in schedule.get("dates", []):
        for game in date_entry.get("games", []):
            game_pk = game.get("gamePk")
            if game_pk and is_final_status(game.get("status")):
                final_game_pks.append(int(game_pk))

    Session = _get_session()
    with Session() as session:
        existing = {
            value for (value,) in session.query(FinalGameSnapshot.game_pk)
            .filter(FinalGameSnapshot.game_pk.in_(final_game_pks or [-1]))
            .all()
        }

    results = [_snapshot_final_game(game_pk) for game_pk in final_game_pks if game_pk not in existing]
    return {
        "attempted": len(results),
        "snapshotted": sum(result.get("status") == "snapshotted" for result in results),
        "errors": [result for result in results if result.get("status") == "error"],
    }


def _person_payload(person: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    if not person or not person.get("id"):
        return None
    return {
        "id": person.get("id"),
        "name": person.get("fullName") or person.get("name"),
        "link": person.get("link"),
    }


def _runner_payload(runner: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    if not runner:
        return None
    if isinstance(runner, dict) and runner.get("id"):
        return _person_payload(runner)
    if isinstance(runner, dict) and runner.get("fullName"):
        return _person_payload(runner)
    return runner


def _pitch_event_payload(event: Dict[str, Any]) -> Dict[str, Any]:
    pitch_data = event.get("pitchData") or {}
    hit_data = event.get("hitData") or {}
    details = event.get("details") or {}
    breaks = pitch_data.get("breaks") or {}
    coordinates = pitch_data.get("coordinates") or {}

    return {
        "index": event.get("index"),
        "is_pitch": bool(event.get("isPitch")),
        "is_in_play": bool(event.get("isInPlay")),
        "is_strike": bool(event.get("isStrike")),
        "is_ball": bool(event.get("isBall")),
        "pitch_type": (details.get("type") or {}).get("description"),
        "pitch_code": (details.get("type") or {}).get("code"),
        "call": (details.get("call") or {}).get("description"),
        "call_code": (details.get("call") or {}).get("code"),
        "description": details.get("description"),
        "speed_mph": pitch_data.get("startSpeed"),
        "end_speed_mph": pitch_data.get("endSpeed"),
        "zone": pitch_data.get("zone"),
        "spin_rate": breaks.get("spinRate"),
        "induced_vert_break": breaks.get("breakVerticalInduced"),
        "horizontal_break": breaks.get("breakHorizontal"),
        "plate_x": coordinates.get("pX"),
        "plate_z": coordinates.get("pZ"),
        "hit": {
            "launch_speed": hit_data.get("launchSpeed"),
            "launch_angle": hit_data.get("launchAngle"),
            "total_distance": hit_data.get("totalDistance"),
            "trajectory": hit_data.get("trajectory"),
            "hardness": hit_data.get("hardness"),
            "location": hit_data.get("location"),
        } if hit_data else None,
    }


def _select_live_current_play(live_data: Dict[str, Any]) -> Dict[str, Any]:
    plays = (live_data.get("plays") or {})
    current_play = plays.get("currentPlay") or {}
    if current_play:
        return current_play

    all_plays = plays.get("allPlays") or []
    if all_plays:
        return all_plays[-1]

    return {}


def _live_play_payload(play: Dict[str, Any]) -> Dict[str, Any]:
    matchup = play.get("matchup") or {}
    result = play.get("result") or {}
    about = play.get("about") or {}
    count = play.get("count") or {}
    events = play.get("playEvents") or []
    pitch_events = [_pitch_event_payload(event) for event in events if event.get("isPitch")]

    last_pitch = pitch_events[-1] if pitch_events else None
    last_hit = next((pitch.get("hit") for pitch in reversed(pitch_events) if pitch.get("hit")), None)

    return {
        "at_bat_index": about.get("atBatIndex"),
        "inning": about.get("inning"),
        "half_inning": about.get("halfInning"),
        "is_top_inning": about.get("isTopInning"),
        "has_review": about.get("hasReview"),
        "is_scoring_play": about.get("isScoringPlay"),
        "event": result.get("event"),
        "event_type": result.get("eventType"),
        "description": result.get("description"),
        "rbi": result.get("rbi"),
        "away_score": result.get("awayScore"),
        "home_score": result.get("homeScore"),
        "count": {
            "balls": count.get("balls"),
            "strikes": count.get("strikes"),
            "outs": count.get("outs"),
        },
        "batter": _person_payload(matchup.get("batter")),
        "pitcher": _person_payload(matchup.get("pitcher")),
        "bat_side": (matchup.get("batSide") or {}).get("code"),
        "pitch_hand": (matchup.get("pitchHand") or {}).get("code"),
        "last_pitch": last_pitch,
        "last_hit": last_hit,
        "pitch_sequence": pitch_events,
    }


def _hitter_pitch_type_statcast_summary(
    session,
    batter_id: int,
    pitch_type: Optional[str],
    days_back: int = 3650,
) -> Dict[str, Any]:
    """Dynamic hitter-vs-pitch-type summary independent of the opposing pitcher.

    This is the correct Batter vs Arsenal hierarchy:
        pitcher arsenal = pitcher_id + season + pitch_type
        hitter split    = batter_id + pitch_type

    The UI combines those two independent datasets in the pitch cards. It does
    not need a pre-materialized batter + pitcher + pitch_type row.
    """
    if not batter_id or not pitch_type:
        return {
            "source": "hitter_pitch_type_statcast_365",
            "pitch_type": pitch_type,
            "pitches_seen": 0,
            "swings": 0,
            "whiffs": 0,
            "pa": 0,
            "pa_ended": 0,
            "sample_size": 0,
        }

    try:
        summary = build_batter_pitch_type_summary(
            session=session,
            batter_id=batter_id,
            pitch_type=pitch_type,
            days_back=days_back,
        )
        summary["source"] = f"hitter_pitch_type_statcast_{days_back}"
        summary["sample_size"] = summary.get("pitches_seen") or summary.get("pa_ended") or summary.get("pa") or 0
        return summary
    except Exception:
        # Keep the card alive even if the richer pitch-level summary fails.
        since_year = max(2024, datetime.date.today().year - 1)
        fallback = _player_vs_pitch_type_summary(
            session=session,
            batter_id=batter_id,
            pitch_type=pitch_type,
            since_year=since_year,
        )
        fallback["source"] = "terminal_statcast_pitch_type_fallback"
        fallback["pitches_seen"] = fallback.get("raw_rows") or fallback.get("pa") or 0
        fallback["swings"] = fallback.get("swings") or 0
        fallback["whiffs"] = fallback.get("whiffs") or 0
        fallback["pa_ended"] = fallback.get("pa") or 0
        fallback["sample_size"] = fallback.get("pitches_seen") or fallback.get("pa") or 0
        return fallback


def _lineup_player_payload(player: Dict[str, Any], batting_order: Optional[int] = None) -> Dict[str, Any]:
    payload = {
        "id": player.get("id"),
        "name": player.get("fullName"),
        "position": (player.get("primaryPosition") or {}).get("abbreviation"),
    }

    if batting_order is not None:
        payload["batting_order"] = batting_order

    return payload


def _extract_lineups_for_game(
    game: Dict[str, Any],
    home_team_id: Optional[int],
    away_team_id: Optional[int],
    season: int,
    game_date_iso: str,
) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]], Optional[str], Optional[str]]:
    lineups = game.get("lineups") or {}

    home_lineup_raw = lineups.get("homePlayers", []) or []
    away_lineup_raw = lineups.get("awayPlayers", []) or []

    home_lineup_source = "official" if home_lineup_raw else None
    away_lineup_source = "official" if away_lineup_raw else None

    if not home_lineup_raw and home_team_id:
        previous = _fetch_previous_completed_game_lineup(home_team_id, game_date_iso)
        if previous:
            home_lineup_raw = previous
            home_lineup_source = "projected"
        else:
            home_lineup_raw = _fetch_roster_as_lineup(home_team_id, season)
            home_lineup_source = "roster" if home_lineup_raw else None

    if not away_lineup_raw and away_team_id:
        previous = _fetch_previous_completed_game_lineup(away_team_id, game_date_iso)
        if previous:
            away_lineup_raw = previous
            away_lineup_source = "projected"
        else:
            away_lineup_raw = _fetch_roster_as_lineup(away_team_id, season)
            away_lineup_source = "roster" if away_lineup_raw else None

    return home_lineup_raw, away_lineup_raw, home_lineup_source, away_lineup_source


def _game_from_schedule(game_pk: int, hydrate: str) -> Dict[str, Any]:
    data = _request_json(
        f"{MLB_STATS_BASE}/schedule",
        params={
            "gamePk": game_pk,
            "hydrate": hydrate,
        },
        timeout=20,
    )

    dates = data.get("dates", [])
    if not dates or not dates[0].get("games"):
        raise HTTPException(status_code=404, detail=f"Game {game_pk} not found")

    return dates[0]["games"][0]


class PredictRequest(BaseModel):
    pitcher_id: int
    batter_id: int
    season: Optional[int] = None
    pitcher_throws: str = "R"



def compute_pitcher_profile(aggregate):
    """
    Compatibility helper for matchup detail PA outcome modeling.

    The matchup route expects a pitcher profile dict. Some branches referenced
    compute_pitcher_profile without defining it. This function normalizes the
    aggregate pitcher stats into the profile shape expected by
    build_pa_outcome_probabilities.
    """
    aggregate = aggregate or {}

    def first(*keys):
        for key in keys:
            value = aggregate.get(key)
            if value is not None:
                return value
        return None

    return {
        "metadata": {
            "source_type": "pitcher_detail_aggregate",
            "generated_from": "mlb_app.app.compute_pitcher_profile",
            "data_confidence": "medium" if aggregate else "low",
        },
        "bat_missing": {
            "k_rate": first("k_rate", "k_pct", "strikeout_rate", "strikeout_pct"),
            "whiff_rate": first("whiff_rate", "whiff_pct"),
            "csw_rate": first("csw_rate", "csw_pct"),
        },
        "command_control": {
            "bb_rate": first("bb_rate", "bb_pct", "walk_rate", "walk_pct"),
            "zone_rate": first("zone_rate", "zone_pct"),
            "first_pitch_strike_rate": first("first_pitch_strike_rate", "first_pitch_strike_pct"),
        },
        "contact_management": {
            "hard_hit_rate_allowed": first("hard_hit_rate_allowed", "hard_hit_pct", "hard_hit_rate"),
            "xwoba_allowed": first("xwoba_allowed", "xwoba"),
            "xba_allowed": first("xba_allowed", "xba"),
            "avg_exit_velocity_allowed": first("avg_exit_velocity_allowed", "avg_exit_velocity"),
            "avg_launch_angle_allowed": first("avg_launch_angle_allowed", "avg_launch_angle"),
        },
        "arsenal": {
            "pitch_mix": first("pitch_mix", "arsenal", "pitch_arsenal") or {},
            "avg_velocity": first("avg_velocity", "velocity"),
            "avg_spin_rate": first("avg_spin_rate", "spin_rate"),
        },
    }


def create_app():
    if not _FASTAPI:
        return None

    app = FastAPI(
        title="MLB Prediction API",
        version="0.5.2",
        description="Statcast-powered daily matchup predictions",
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=["https://mlbgpt.com", "https://www.mlbgpt.com"],
        allow_origin_regex=r"https://.*\.up\.railway\.app",
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    app.include_router(
        draftkings_projection_router
    )
    app.include_router(batter_router)
    app.include_router(daily_odds_router)
    app.include_router(model_projection_router)
    app.include_router(ai_data_assistant_router)
    app.include_router(news_router)
    app.include_router(model_tracker_router)
    app.include_router(sportsbook_router)
    app.include_router(admin_router)

    @app.get("/health")
    def health():
        return {"status": "ok", "version": "0.5.2"}

    @app.get("/odds/draftkings/pregame")
    def draftkings_pregame_odds(
        date: Optional[str] = None,
        raw: bool = False,
        league: Optional[str] = None,
        market_types: Optional[str] = None,
        state: Optional[str] = None,
    ) -> Dict[str, Any]:
        parsed_market_types = (
            [market.strip() for market in market_types.split(",") if market.strip()]
            if market_types
            else None
        )

        return fetch_draftkings_odds(
            scope="pregame",
            date=date,
            raw=raw,
            league=league,
            market_types=parsed_market_types,
            state=state,
        )

    @app.get("/odds/draftkings/live")
    def draftkings_live_odds(
        raw: bool = False,
        league: Optional[str] = None,
        market_types: Optional[str] = None,
        state: Optional[str] = None,
    ) -> Dict[str, Any]:
        parsed_market_types = (
            [market.strip() for market in market_types.split(",") if market.strip()]
            if market_types
            else None
        )

        return fetch_draftkings_odds(
            scope="live",
            raw=raw,
            league=league,
            market_types=parsed_market_types,
            state=state,
        )

    @app.get("/odds/draftkings/game/{game_pk}")
    def draftkings_game_odds(
        game_pk: int,
        date: Optional[str] = None,
        raw: bool = False,
    ) -> Dict[str, Any]:
        return fetch_draftkings_odds(
            scope="pregame",
            game_pk=game_pk,
            date=date,
            raw=raw,
        )

    @app.get("/odds/draftkings/props/{game_pk}")
    def draftkings_game_props(
        game_pk: int,
        date: Optional[str] = None,
        raw: bool = False,
    ) -> Dict[str, Any]:
        return fetch_draftkings_odds(
            scope="pregame",
            game_pk=game_pk,
            props_only=True,
            date=date,
            raw=raw,
        )

    @app.get("/odds/draftkings/events")
    def draftkings_events(
        date: Optional[str] = None,
        raw: bool = False,
    ) -> Dict[str, Any]:
        return fetch_draftkings_events(
            date=date,
            raw=raw,
        )

    @app.get("/odds/draftkings/event/{event_id}")
    def draftkings_event_odds(
        event_id: str,
        raw: bool = False,
    ) -> Dict[str, Any]:
        return fetch_draftkings_event_odds(
            event_id=event_id,
            props_only=False,
            raw=raw,
        )

    @app.get("/odds/draftkings/event/{event_id}/props")
    def draftkings_event_props(
        event_id: str,
        raw: bool = False,
    ) -> Dict[str, Any]:
        return fetch_draftkings_event_odds(
            event_id=event_id,
            props_only=True,
            raw=raw,
        )

    @app.get("/odds/draftkings/debug")
    def draftkings_debug_odds(
        date: Optional[str] = None,
        league: Optional[str] = None,
        market_types: Optional[str] = None,
        live_only: Optional[bool] = None,
        state: Optional[str] = None,
    ) -> Dict[str, Any]:
        parsed_market_types = (
            [market.strip() for market in market_types.split(",") if market.strip()]
            if market_types
            else None
        )

        return fetch_draftkings_odds(
            scope="debug",
            date=date,
            raw=True,
            league=league,
            market_types=parsed_market_types,
            live_only=live_only,
            state=state,
        )


    @app.get("/debug/routes")
    def debug_routes() -> Dict[str, Any]:
        """Return mounted route visibility for deployment diagnostics."""
        route_paths = sorted(
            {
                getattr(route, "path", "")
                for route in app.routes
                if getattr(route, "path", "")
            }
        )

        try:
            git_sha = subprocess.check_output(
                ["git", "rev-parse", "--short", "HEAD"],
                stderr=subprocess.DEVNULL,
                text=True,
            ).strip()
        except Exception:
            git_sha = os.getenv("RAILWAY_GIT_COMMIT_SHA") or os.getenv("GIT_SHA")

        return {
            "status": "ok",
            "version": "0.5.2",
            "git_sha": git_sha,
            "route_count": len(route_paths),
            "has_models_projections": "/models/projections" in route_paths,
            "has_matchups": "/matchups" in route_paths,
            "has_daily_odds": any(route.startswith("/daily-odds") for route in route_paths),
            "routes": route_paths,
        }

    @app.get("/matchups")
    def list_matchups(date: Optional[str] = None) -> List[Dict[str, Any]]:
        if not date:
            date = datetime.date.today().isoformat()

        Session = _get_session()
        with Session() as session:
            try:
                return generate_matchups_for_date(session, date)
            except Exception as exc:
                raise HTTPException(status_code=500, detail=str(exc))

    @app.get("/matchups/calendar")
    def matchup_calendar() -> Dict[str, Any]:
        dates = _build_date_window()

        Session = _get_session()
        with Session() as session:
            payload: Dict[str, Any] = {}

            for key, date_value in dates.items():
                if date_value not in MATCHUP_SNAPSHOT_CACHE:
                    MATCHUP_SNAPSHOT_CACHE[date_value] = generate_matchups_for_date(session, date_value)

                payload[key] = {
                    "date": date_value,
                    "count": len(MATCHUP_SNAPSHOT_CACHE[date_value]),
                    "games": MATCHUP_SNAPSHOT_CACHE[date_value],
                }

            return payload

    @app.post("/matchups/snapshot/{date_str}")
    def snapshot_matchups(date_str: str) -> Dict[str, Any]:
        Session = _get_session()

        with Session() as session:
            try:
                MATCHUP_SNAPSHOT_CACHE[date_str] = generate_matchups_for_date(session, date_str)
            except Exception as exc:
                raise HTTPException(status_code=500, detail=str(exc))

        return {
            "date": date_str,
            "games_cached": len(MATCHUP_SNAPSHOT_CACHE[date_str]),
        }

    @app.post("/ai/ask")
    def ai_ask(payload: Dict[str, Any]) -> Dict[str, Any]:
        question = str(payload.get("question", "")).strip()
        if not question:
            raise HTTPException(status_code=400, detail="Question is required")

        ql = question.lower()
        dates = _build_date_window()

        Session = _get_session()
        with Session() as session:
            if "today" in ql or "matchup" in ql:
                games = generate_matchups_for_date(session, dates["today"])
                return {
                    "answer": f"There are {len(games)} scheduled games for {dates['today']}.",
                    "sources": ["/matchups", f"/matchups?date={dates['today']}"],
                    "data": {
                        "date": dates["today"],
                        "games": games[:8],
                    },
                }

            if "yesterday" in ql:
                games = MATCHUP_SNAPSHOT_CACHE.get(dates["yesterday"]) or generate_matchups_for_date(
                    session,
                    dates["yesterday"],
                )
                MATCHUP_SNAPSHOT_CACHE[dates["yesterday"]] = games

                return {
                    "answer": f"Loaded {len(games)} games for yesterday ({dates['yesterday']}).",
                    "sources": ["/matchups/calendar", f"/matchups?date={dates['yesterday']}"],
                    "data": {
                        "date": dates["yesterday"],
                        "games": games[:8],
                    },
                }

            if "weather" in ql:
                games = generate_matchups_for_date(session, dates["today"])
                weather_games = [game for game in games if game.get("weather")]

                return {
                    "answer": f"Found weather data for {len(weather_games)} of {len(games)} games today.",
                    "sources": [f"/matchups?date={dates['today']}"],
                    "data": weather_games[:10],
                }

            team_match = re.search(r"team\s+(\d+)", ql)
            if team_match:
                team_id = int(team_match.group(1))
                team = get_team(team_id)

                return {
                    "answer": f"Team {team_id} standing and split profile loaded.",
                    "sources": [f"/team/{team_id}", "/standings"],
                    "data": team,
                }

        return {
            "answer": "I can currently answer questions about today/yesterday matchups, weather, and team IDs.",
            "sources": ["/matchups", "/team/{team_id}", "/standings"],
            "data": None,
        }

    @app.get("/matchup/{game_pk}")
    def get_matchup_detail(game_pk: int) -> Dict[str, Any]:
        try:
            game = _game_from_schedule(
                game_pk,
                hydrate="probablePitcher,team,linescore,lineups,decisions,weather",
            )
        except HTTPException:
            raise
        except Exception as exc:
            raise HTTPException(status_code=502, detail=f"MLB API error: {exc}")

        teams = game.get("teams", {})
        home = teams.get("home", {})
        away = teams.get("away", {})

        home_team = home.get("team", {})
        away_team = away.get("team", {})

        home_team_id = home_team.get("id")
        away_team_id = away_team.get("id")

        home_pitcher = home.get("probablePitcher", {}) or {}
        away_pitcher = away.get("probablePitcher", {}) or {}

        home_pitcher_id = home_pitcher.get("id")
        away_pitcher_id = away_pitcher.get("id")

        game_date_iso = game.get("gameDate", "")
        venue_name = (game.get("venue") or {}).get("name")
        season = int(game_date_iso[:4]) if game_date_iso else datetime.date.today().year

        home_lineup_raw, away_lineup_raw, home_lineup_source, away_lineup_source = _extract_lineups_for_game(
            game=game,
            home_team_id=home_team_id,
            away_team_id=away_team_id,
            season=season,
            game_date_iso=game_date_iso,
        )
        home_record = home.get("leagueRecord", {}) or {}
        away_record = away.get("leagueRecord", {}) or {}

        Session = _get_session()
        with Session() as session:

            def pitcher_detail(pid: Optional[int]) -> Dict[str, Any]:
                if not pid:
                    return {
                        "aggregate": None,
                        "arsenal": [],
                        "arsenal_season": None,
                        "game_log": [],
                        "profile_overview": None,
                        "profile_arsenal": [],
                        "profile_recent_games": [],
                    }

                agg, data_source = get_pitcher_aggregate_with_fallback(session, pid, season)

                try:
                    arsenal_rows = refresh_starting_pitcher_arsenal(
                        session=session,
                        pitcher_id=pid,
                        season=season,
                        target_date=game_date_iso,
                        window_days=365,
                    )
                    arsenal_season = season if arsenal_rows else None
                except Exception:
                    arsenal_rows = []
                    arsenal_season = None

                if not arsenal_rows:
                    arsenal, arsenal_season = get_pitch_arsenal_with_fallback(session, pid, season)
                    arsenal_rows = _normalize_arsenal_to_dicts(arsenal)

                if not arsenal_rows:
                    live_arsenal, live_season = _fetch_live_pitch_arsenal(pid, season)
                    if live_arsenal:
                        arsenal_rows = live_arsenal
                        arsenal_season = live_season

                game_log = get_pitcher_game_log(session, pid, 5)

                profile_overview_row = get_pitcher_profile_overview(session, pid, season)
                profile_arsenal_rows = get_pitcher_profile_arsenal(session, pid, season)
                profile_recent_game_rows = get_pitcher_profile_recent_games(session, pid, limit=5)

                return {
                    "aggregate": {
                        "data_source": data_source,
                        "avg_velocity": agg.avg_velocity if agg else None,
                        "avg_spin_rate": agg.avg_spin_rate if agg else None,
                        "hard_hit_pct": agg.hard_hit_pct if agg else None,
                        "k_pct": agg.k_pct if agg else None,
                        "bb_pct": agg.bb_pct if agg else None,
                        "xwoba": agg.xwoba if agg else None,
                        "xba": agg.xba if agg else None,
                        "avg_horiz_break": agg.avg_horiz_break if agg else None,
                        "avg_vert_break": agg.avg_vert_break if agg else None,
                    },
                    "arsenal": arsenal_rows,
                    "arsenal_season": arsenal_season,
                    "game_log": game_log,
                    "profile_overview": serialize_pitcher_profile_overview(profile_overview_row),
                    "profile_arsenal": serialize_pitcher_profile_arsenal(profile_arsenal_rows),
                    "profile_recent_games": serialize_pitcher_profile_recent_games(profile_recent_game_rows),
                }
            def team_splits(team_id: Optional[int]) -> Dict[str, Any]:
                if not team_id:
                    return {"vsL": None, "vsR": None}

                vs_l = get_team_split(session, team_id, season, "vsL")
                vs_r = get_team_split(session, team_id, season, "vsR")

                def split_dict(split):
                    if not split:
                        return None

                    return {
                        "pa": split.pa,
                        "batting_avg": split.batting_avg,
                        "on_base_pct": split.on_base_pct,
                        "slugging_pct": split.slugging_pct,
                        "k_pct": split.k_pct,
                        "bb_pct": split.bb_pct,
                        "home_runs": split.home_runs,
                    }

                db_result = {
                    "vsL": split_dict(vs_l),
                    "vsR": split_dict(vs_r),
                }

                both_missing = not db_result["vsL"] and not db_result["vsR"]
                identical = (
                    db_result["vsL"]
                    and db_result["vsR"]
                    and db_result["vsL"].get("batting_avg") == db_result["vsR"].get("batting_avg")
                    and db_result["vsL"].get("pa") == db_result["vsR"].get("pa")
                )

                if both_missing or identical:
                    live = _fetch_team_splits_live(team_id, season)
                    if live["vsL"] or live["vsR"]:
                        return live

                return db_result

            home_win_prob = None
            away_win_prob = None

            if home_pitcher_id and away_pitcher_id and home_team_id and away_team_id:
                home_win_prob, away_win_prob = compute_win_probability(
                    session,
                    home_pitcher_id=home_pitcher_id,
                    away_pitcher_id=away_pitcher_id,
                    home_team_id=home_team_id,
                    away_team_id=away_team_id,
                    season=season,
                )

            home_pitcher_detail = pitcher_detail(home_pitcher_id)
            away_pitcher_detail = pitcher_detail(away_pitcher_id)
            home_team_splits = team_splits(home_team_id)
            away_team_splits = team_splits(away_team_id)

            home_pitcher_hand = None
            away_pitcher_hand = None

            game_date_obj = (
                datetime.date.fromisoformat(game_date_iso[:10])
                if game_date_iso
                else datetime.date.today()
            )

            home_lineup = [_lineup_player_payload(player) for player in home_lineup_raw]
            away_lineup = [_lineup_player_payload(player) for player in away_lineup_raw]

            home_projected_lineup_offense_profile = build_projected_lineup_offense_profile(
                lineup=home_lineup,
                season=season,
                pitcher_hand=away_pitcher_hand,
                lineup_source=home_lineup_source or ("official" if home_lineup else "missing"),
                target_date=game_date_obj,
            )
            away_projected_lineup_offense_profile = build_projected_lineup_offense_profile(
                lineup=away_lineup,
                season=season,
                pitcher_hand=home_pitcher_hand,
                lineup_source=away_lineup_source or ("official" if away_lineup else "missing"),
                target_date=game_date_obj,
            )

            environment_profile = compute_environment_profile(
                {
                    "game_pk": game_pk,
                    "game_date": game_date_iso,
                    "venue_name": venue_name,
                    "weather": _extract_weather(game),
                    "park_factor": get_park_factor(venue_name),
                    "home_team": home_team.get("name"),
                    "away_team": away_team.get("name"),
                }
            )

            home_pitcher_profile = compute_pitcher_profile(home_pitcher_detail.get("aggregate") or {})
            away_pitcher_profile = compute_pitcher_profile(away_pitcher_detail.get("aggregate") or {})

            home_matchup_analysis = build_matchup_analysis(
                pitcher_id=away_pitcher_id,
                pitcher_name=away_pitcher.get("fullName"),
                pitcher_hand=away_pitcher_hand,
                lineup=home_lineup,
                lineup_source=home_lineup_source or ("official" if home_lineup else "missing"),
                arsenal_rows=away_pitcher_detail.get("arsenal") or [],
            )
            away_matchup_analysis = build_matchup_analysis(
                pitcher_id=home_pitcher_id,
                pitcher_name=home_pitcher.get("fullName"),
                pitcher_hand=home_pitcher_hand,
                lineup=away_lineup,
                lineup_source=away_lineup_source or ("official" if away_lineup else "missing"),
                arsenal_rows=home_pitcher_detail.get("arsenal") or [],
            )

            home_pa_outcome_model = build_lineup_pa_outcome_model(
                lineup=home_lineup,
                lineup_profile=home_projected_lineup_offense_profile,
                opposing_pitcher_profile=away_pitcher_profile,
                environment_profile=environment_profile,
                side_label="home_offense",
            )
            away_pa_outcome_model = build_lineup_pa_outcome_model(
                lineup=away_lineup,
                lineup_profile=away_projected_lineup_offense_profile,
                opposing_pitcher_profile=home_pitcher_profile,
                environment_profile=environment_profile,
                side_label="away_offense",
            )

            home_half_inning_simulation = simulate_half_innings(
                probabilities=home_pa_outcome_model.get("lineup_average_probabilities") or {},
                simulations=5000,
                seed=42,
            )
            away_half_inning_simulation = simulate_half_innings(
                probabilities=away_pa_outcome_model.get("lineup_average_probabilities") or {},
                simulations=5000,
                seed=42,
            )

            home_bullpen_profile = build_bullpen_profile(
                team_id=home_team_id,
                team_name=home_team.get("name"),
            )
            away_bullpen_profile = build_bullpen_profile(
                team_id=away_team_id,
                team_name=away_team.get("name"),
            )

            away_vs_home_bullpen_pa_outcome_model = build_bullpen_pa_outcome_model(
                lineup_profile=away_projected_lineup_offense_profile,
                bullpen_profile=home_bullpen_profile,
                environment_profile=environment_profile,
                side_label="away_offense_vs_home_bullpen",
            )
            home_vs_away_bullpen_pa_outcome_model = build_bullpen_pa_outcome_model(
                lineup_profile=home_projected_lineup_offense_profile,
                bullpen_profile=away_bullpen_profile,
                environment_profile=environment_profile,
                side_label="home_offense_vs_away_bullpen",
            )

            game_simulation = build_game_simulation(
                away_pa=away_pa_outcome_model,
                home_pa=home_pa_outcome_model,
            )
            bullpen_adjusted_game_simulation = build_bullpen_adjusted_game_simulation(
                away_sp=away_pa_outcome_model,
                home_sp=home_pa_outcome_model,
                away_bp=away_vs_home_bullpen_pa_outcome_model,
                home_bp=home_vs_away_bullpen_pa_outcome_model,
            )
            shared_matchup_input = {
                "game_pk": game_pk,
                "game_date": game_date_iso,

                "away_team_id": away_team_id,
                "home_team_id": home_team_id,

                "away_team_name": away_team.get("name"),
                "home_team_name": home_team.get("name"),

                "away_pitcher_id": away_pitcher_id,
                "home_pitcher_id": home_pitcher_id,

                "away_pitcher_name": away_pitcher.get("fullName"),
                "home_pitcher_name": home_pitcher.get("fullName"),

                "venue": {"name": venue_name},
                "weather": game.get("weather") or {},
            }

            try:
                shared_game_simulation = build_shared_game_simulation(
                    game_pk=game_pk,
                    config={
                        "matchup": {
                            "raw": shared_matchup_input,
                            "game_date": game_date_iso,
                        },
                        "simulation_count": 5000,
                        "seed": 42,
                        "starter_exit_enabled": True,
                    }
                )
            except Exception as shared_sim_exc:
                shared_game_simulation = {
                    "status": "error",
                    "error": str(shared_sim_exc),
                    "meta": {
                        "game_pk": game_pk,
                        "model_version": "shared-simulation-v1",
                        "source_builder": "mlb_app.simulation.game_simulation_builder",
                        "source_route": "/matchup/{game_pk}",
                    },
                }

            return {
                "game_pk": game_pk,
                "game_date": game_date_iso,
                "venue": venue_name,
                "status": (game.get("status") or {}).get("detailedState"),
                "weather": _extract_weather(game),
                "park_factor": get_park_factor(venue_name),
                "home_win_prob": home_win_prob,
                "away_win_prob": away_win_prob,
                "homePitcherProfile": home_pitcher_profile,
                "awayPitcherProfile": away_pitcher_profile,
                "homeProjectedLineupOffenseProfile": home_projected_lineup_offense_profile,
                "awayProjectedLineupOffenseProfile": away_projected_lineup_offense_profile,
                "environmentProfile": environment_profile,
                "homeMatchupAnalysis": home_matchup_analysis,
                "awayMatchupAnalysis": away_matchup_analysis,
                "homePAOutcomeModel": home_pa_outcome_model,
                "awayPAOutcomeModel": away_pa_outcome_model,
                "homeHalfInningSimulation": home_half_inning_simulation,
                "awayHalfInningSimulation": away_half_inning_simulation,
                "gameSimulation": game_simulation,
                "bullpenAdjustedGameSimulation": bullpen_adjusted_game_simulation,
                "sharedGameSimulation": shared_game_simulation,
                "awayVsHomeBullpenPAOutcomeModel": away_vs_home_bullpen_pa_outcome_model,
                "homeVsAwayBullpenPAOutcomeModel": home_vs_away_bullpen_pa_outcome_model,
                "homeBullpenProfile": home_bullpen_profile,
                "awayBullpenProfile": away_bullpen_profile,
                "home_team": {
                    "id": home_team_id,
                    "name": home_team.get("name"),
                    "record": f"{home_record.get('wins', 0)}-{home_record.get('losses', 0)}" if home_record else None,
                    "pitcher_id": home_pitcher_id,
                    "pitcher_name": home_pitcher.get("fullName"),
                    **home_pitcher_detail,
                    "splits": home_team_splits,
                    "lineup_source": home_lineup_source,
                    "lineup": home_lineup,
                },
                "away_team": {
                    "id": away_team_id,
                    "name": away_team.get("name"),
                    "record": f"{away_record.get('wins', 0)}-{away_record.get('losses', 0)}" if away_record else None,
                    "pitcher_id": away_pitcher_id,
                    "pitcher_name": away_pitcher.get("fullName"),
                    **away_pitcher_detail,
                    "splits": away_team_splits,
                    "lineup_source": away_lineup_source,
                    "lineup": away_lineup,
                },
            }

    @app.get("/matchup/{game_pk}/competitive")
    def get_competitive_analysis(game_pk: int) -> Dict[str, Any]:
        try:
            game = _game_from_schedule(
                game_pk,
                hydrate="probablePitcher,team,lineups,weather",
            )
        except HTTPException:
            raise
        except Exception as exc:
            raise HTTPException(status_code=502, detail=f"MLB API error: {exc}")

        teams = game.get("teams", {})
        home = teams.get("home", {})
        away = teams.get("away", {})

        home_team = home.get("team", {})
        away_team = away.get("team", {})

        home_team_id = home_team.get("id")
        away_team_id = away_team.get("id")

        home_team_name = home_team.get("name")
        away_team_name = away_team.get("name")

        home_pitcher_id = (home.get("probablePitcher") or {}).get("id")
        away_pitcher_id = (away.get("probablePitcher") or {}).get("id")

        game_date_iso = game.get("gameDate", "")
        season = int(game_date_iso[:4]) if game_date_iso else datetime.date.today().year

        home_lineup_raw, away_lineup_raw, home_lineup_source, away_lineup_source = _extract_lineups_for_game(
            game=game,
            home_team_id=home_team_id,
            away_team_id=away_team_id,
            season=season,
            game_date_iso=game_date_iso,
        )

        Session = _get_session()
        with Session() as session:

            def load_pitcher_arsenal(pitcher_id: Optional[int]) -> Tuple[List[Dict[str, Any]], Optional[int]]:
                if not pitcher_id:
                    return [], None

                raw, arsenal_season = get_pitch_arsenal_with_fallback(session, pitcher_id, season)
                arsenal_rows = _normalize_arsenal_to_dicts(raw)

                if not arsenal_rows:
                    live_rows, live_season = _fetch_live_pitch_arsenal(pitcher_id, season)
                    return live_rows, live_season

                return arsenal_rows, arsenal_season

            home_arsenal, home_arsenal_season = load_pitcher_arsenal(home_pitcher_id)
            away_arsenal, away_arsenal_season = load_pitcher_arsenal(away_pitcher_id)

            game_date_str = game_date_iso[:10] if game_date_iso else None

            away_lineup_matchups = [
                _build_competitive_matchup(
                    session=session,
                    batter_id=player.get("id"),
                    batter_name=player.get("fullName") or f"Batter #{player.get('id')}",
                    batting_order=index + 1,
                    opposing_pitcher_id=home_pitcher_id,
                    season=season,
                    _preloaded_arsenal=home_arsenal,
                    _preloaded_arsenal_season=home_arsenal_season,
                    target_date=game_date_str,
                )
                for index, player in enumerate(away_lineup_raw)
                if player.get("id") and home_pitcher_id
            ]

            home_lineup_matchups = [
                _build_competitive_matchup(
                    session=session,
                    batter_id=player.get("id"),
                    batter_name=player.get("fullName") or f"Batter #{player.get('id')}",
                    batting_order=index + 1,
                    opposing_pitcher_id=away_pitcher_id,
                    season=season,
                    _preloaded_arsenal=away_arsenal,
                    _preloaded_arsenal_season=away_arsenal_season,
                    target_date=game_date_str,
                )
                for index, player in enumerate(home_lineup_raw)
                if player.get("id") and away_pitcher_id
            ]

        return {
            "game_pk": game_pk,
            "game_date": game_date_iso,
            "away_team": away_team_name,
            "home_team": home_team_name,
            "away_pitcher_id": away_pitcher_id,
            "home_pitcher_id": home_pitcher_id,
            "away_lineup_source": away_lineup_source,
            "home_lineup_source": home_lineup_source,
            "away_lineup_matchups": away_lineup_matchups,
            "home_lineup_matchups": home_lineup_matchups,
        }

    @app.get("/pitcher/{player_id}")
    def get_pitcher(player_id: int) -> Dict[str, Any]:
        season = datetime.date.today().year

        Session = _get_session()
        with Session() as session:
            agg, data_source = get_pitcher_aggregate_with_fallback(session, player_id, season)
            arsenal, arsenal_season = get_pitch_arsenal_with_fallback(session, player_id, season)

            arsenal_rows = _normalize_arsenal_to_dicts(arsenal)
            if not arsenal_rows:
                live_arsenal, live_season = _fetch_live_pitch_arsenal(player_id, season)
                if live_arsenal:
                    arsenal_rows = live_arsenal
                    arsenal_season = live_season

            multi = get_pitcher_multi_season(session, player_id, [season, season - 1, season - 2, season - 3])
            game_log = get_pitcher_game_log(session, player_id, 10)

            profile_overview_row = get_pitcher_profile_overview(session, player_id, season)
            profile_arsenal_rows = get_pitcher_profile_arsenal(session, player_id, season)
            profile_recent_game_rows = get_pitcher_profile_recent_games(session, player_id, limit=10)

            if not agg and not arsenal_rows and not profile_overview_row and not profile_arsenal_rows:
                player_name = None

                try:
                    data = _request_json(
                        f"{MLB_STATS_BASE}/people/{player_id}",
                        params={"hydrate": "currentTeam"},
                        timeout=10,
                    )
                    people = data.get("people", [])
                    if people:
                        player_name = people[0].get("fullName")
                except Exception:
                    pass

                return {
                    "player_id": player_id,
                    "player_name": player_name,
                    "data_source": None,
                    "aggregate": None,
                    "arsenal": [],
                    "arsenal_season": None,
                    "multi_season": [],
                    "game_log": [],
                    "profile_overview": None,
                    "profile_arsenal": [],
                    "profile_recent_games": [],
                    "no_data": True,
                }

            return {
                "player_id": player_id,
                "data_source": data_source,
                "aggregate": {
                    column.name: getattr(agg, column.name)
                    for column in agg.__table__.columns
                } if agg else None,
                "arsenal": arsenal_rows,
                "arsenal_season": arsenal_season,
                "multi_season": multi,
                "game_log": game_log,
                "profile_overview": serialize_pitcher_profile_overview(profile_overview_row),
                "profile_arsenal": serialize_pitcher_profile_arsenal(profile_arsenal_rows),
                "profile_recent_games": serialize_pitcher_profile_recent_games(profile_recent_game_rows),
            }

    @app.get("/pitcher/{player_id}/rolling")
    def pitcher_rolling(
        player_id: int,
        windows: str = Query("15,30,60,90,120,150"),
    ) -> Dict[str, Any]:
        sizes = [int(window) for window in windows.split(",") if window.strip().isdigit()]

        Session = _get_session()
        with Session() as session:
            result = []
            for size in sizes:
                stats = get_pitcher_rolling_by_games(session, player_id, size)
                result.append(
                    {
                        "window": f"L{size}G",
                        "n_requested": size,
                        "stats": stats,
                    }
                )

            return {
                "player_id": player_id,
                "windows": result,
            }

    @app.get("/pitcher/{player_id}/game-log")
    def pitcher_game_log(player_id: int, n: int = 10) -> Dict[str, Any]:
        Session = _get_session()
        with Session() as session:
            return {
                "player_id": player_id,
                "game_log": get_pitcher_game_log(session, player_id, n),
            }

    @app.get("/batter/{player_id}")
    def get_batter(player_id: int) -> Dict[str, Any]:
        season = datetime.date.today().year

        Session = _get_session()
        with Session() as session:
            agg, data_source = get_batter_aggregate_with_fallback(session, player_id, season)
            split_l = get_player_split(session, player_id, season, "vsL")
            split_r = get_player_split(session, player_id, season, "vsR")
            multi = get_batter_multi_season(session, player_id, [season, season - 1, season - 2, season - 3])
            split_seasons = get_player_splits_multi_season(session, player_id, [season, season - 1, season - 2, season - 3])
            statcast = _compute_batter_statcast(session, player_id, since_year=2024)

        live = _fetch_batter_live_data(player_id, season)

        def split_dict(split):
            if not split:
                return None

            return {
                "pa": split.pa,
                "batting_avg": split.batting_avg,
                "on_base_pct": split.on_base_pct,
                "slugging_pct": split.slugging_pct,
                "iso": split.iso,
                "k_pct": split.k_pct,
                "bb_pct": split.bb_pct,
                "home_runs": split.home_runs,
            }

        db_vs_l = split_dict(split_l)
        db_vs_r = split_dict(split_r)

        splits = {"vsL": db_vs_l, "vsR": db_vs_r} if db_vs_l or db_vs_r else live["splits"]

        return {
            "player_id": player_id,
            "player_info": live["player_info"],
            "data_source": data_source,
            "aggregate": {
                column.name: getattr(agg, column.name)
                for column in agg.__table__.columns
            } if agg else None,
            "statcast": statcast,
            "season_stats": live["season_stats"],
            "splits": splits,
            "year_by_year": live["year_by_year"],
            "multi_season": multi,
            "split_seasons": split_seasons,
        }

    @app.get("/batter/{player_id}/rolling")
    def batter_rolling(
        player_id: int,
        windows: str = Query("10,25,50,100,200,400,1000"),
        type: str = Query("abs"),
    ) -> Dict[str, Any]:
        sizes = [int(window) for window in windows.split(",") if window.strip().isdigit()]

        Session = _get_session()
        with Session() as session:
            result = []

            for size in sizes:
                if type == "games":
                    stats = get_batter_rolling_by_games(session, player_id, size)
                    label = f"L{size}G"
                else:
                    stats = get_batter_rolling_by_abs(session, player_id, size)
                    label = f"L{size}"

                result.append(
                    {
                        "window": label,
                        "n_requested": size,
                        "stats": stats,
                    }
                )

            return {
                "player_id": player_id,
                "type": type,
                "windows": result,
            }

    @app.get("/batter/{player_id}/at-bats")
    def batter_at_bats(
        player_id: int,
        n: int = Query(50, le=500),
        offset: int = Query(0, ge=0),
    ) -> Dict[str, Any]:
        Session = _get_session()
        with Session() as session:
            total, rows = get_batter_at_bats(session, player_id, n, offset)

            return {
                "player_id": player_id,
                "total_abs": total,
                "n": n,
                "offset": offset,
                "at_bats": rows,
            }

    @app.get("/batter/{player_id}/splits")
    def batter_splits(player_id: int) -> Dict[str, Any]:
        season = datetime.date.today().year
        seasons = [season, season - 1, season - 2, season - 3]

        Session = _get_session()
        with Session() as session:
            return {
                "player_id": player_id,
                "seasons": get_player_splits_multi_season(session, player_id, seasons),
            }

    @app.get("/players/search")
    def search_players(name: str) -> List[Dict[str, Any]]:
        try:
            data = _request_json(
                f"{MLB_STATS_BASE}/people/search",
                params={
                    "sportId": 1,
                    "names": name,
                },
                timeout=20,
            )
        except Exception as exc:
            raise HTTPException(status_code=502, detail=f"MLB API error: {exc}")

        results = []
        for player in data.get("people", []):
            position_type = ((player.get("primaryPosition") or {}).get("type") or "").lower()
            results.append(
                {
                    "id": player.get("id"),
                    "name": player.get("fullName"),
                    "team": (player.get("currentTeam") or {}).get("name"),
                    "position_type": "Pitcher" if position_type == "pitcher" else "Batter",
                }
            )

        return results

    @app.get("/players/all")
    def get_all_players(season: Optional[int] = None) -> List[Dict[str, Any]]:
        if not season:
            season = datetime.date.today().year

        try:
            data = _request_json(
                f"{MLB_STATS_BASE}/sports/1/players",
                params={"season": season},
                timeout=30,
            )
        except Exception as exc:
            raise HTTPException(status_code=502, detail=f"MLB API error: {exc}")

        players = []
        for player in data.get("people", []):
            position = player.get("primaryPosition") or {}
            position_type = (position.get("type") or "").lower()

            players.append(
                {
                    "id": player.get("id"),
                    "name": player.get("fullName"),
                    "position_type": "Pitcher" if position_type == "pitcher" else "Batter",
                    "position": position.get("abbreviation"),
                    "team": (player.get("currentTeam") or {}).get("name"),
                    "active": player.get("active"),
                }
            )

        return players

    @app.get("/team/{team_id}/roster")
    def get_team_roster(team_id: int, season: Optional[int] = None) -> Dict[str, Any]:
        if not season:
            season = datetime.date.today().year

        try:
            data = _request_json(
                f"{MLB_STATS_BASE}/teams/{team_id}/roster",
                params={
                    "rosterType": "active",
                    "season": season,
                },
                timeout=20,
            )
        except Exception as exc:
            raise HTTPException(status_code=502, detail=f"MLB API error: {exc}")

        roster = []
        for row in data.get("roster", []):
            person = row.get("person") or {}
            position = row.get("position") or {}
            status = row.get("status") or {}

            roster.append(
                {
                    "id": person.get("id"),
                    "name": person.get("fullName"),
                    "position": position.get("abbreviation"),
                    "status": status.get("description"),
                }
            )

        return {
            "team_id": team_id,
            "season": season,
            "roster": roster,
        }

    @app.get("/standings")
    def get_standings(season: Optional[int] = None) -> List[Dict[str, Any]]:
        if not season:
            season = datetime.date.today().year

        try:
            data = _request_json(
                f"{MLB_STATS_BASE}/standings",
                params={
                    "leagueId": "103,104",
                    "season": season,
                    "standingsTypes": "regularSeason",
                    "hydrate": "team,division,league,record",
                },
                timeout=20,
            )
        except Exception as exc:
            raise HTTPException(status_code=502, detail=f"MLB API error: {exc}")

        return data.get("records", [])

    @app.get("/lineup/{team_id}")
    def get_team_lineup(team_id: int, date: Optional[str] = None) -> Dict[str, Any]:
        if not date:
            date = datetime.date.today().isoformat()

        try:
            data = _request_json(
                f"{MLB_STATS_BASE}/schedule",
                params={
                    "sportId": 1,
                    "date": date,
                    "teamId": team_id,
                    "hydrate": "lineups,probablePitcher,team",
                },
                timeout=20,
            )
        except Exception as exc:
            raise HTTPException(status_code=502, detail=f"MLB API error: {exc}")

        dates = data.get("dates", [])
        if not dates or not dates[0].get("games"):
            return {
                "team_id": team_id,
                "date": date,
                "lineup": [],
                "probable_pitcher": None,
            }

        game = dates[0]["games"][0]
        teams = game.get("teams", {})

        side = "home" if teams.get("home", {}).get("team", {}).get("id") == team_id else "away"
        lineup_raw = (game.get("lineups") or {}).get(f"{side}Players", []) or []
        pitcher = teams.get(side, {}).get("probablePitcher", {}) or {}

        return {
            "team_id": team_id,
            "date": date,
            "game_pk": game.get("gamePk"),
            "probable_pitcher": {
                "id": pitcher.get("id"),
                "name": pitcher.get("fullName"),
            } if pitcher.get("id") else None,
            "lineup": [
                {
                    "batting_order": index + 1,
                    "id": player.get("id"),
                    "name": player.get("fullName"),
                }
                for index, player in enumerate(lineup_raw)
            ],
        }

    @app.get("/team/{team_id}")
    def get_team(team_id: int, season: Optional[int] = None) -> Dict[str, Any]:
        if not season:
            season = datetime.date.today().year

        Session = _get_session()
        with Session() as session:
            vs_l = get_team_split(session, team_id, season, "vsL")
            vs_r = get_team_split(session, team_id, season, "vsR")

            def split_dict(split):
                if not split:
                    return None

                return {
                    "pa": split.pa,
                    "batting_avg": split.batting_avg,
                    "on_base_pct": split.on_base_pct,
                    "slugging_pct": split.slugging_pct,
                    "k_pct": split.k_pct,
                    "bb_pct": split.bb_pct,
                    "home_runs": split.home_runs,
                }

            db_vs_l = split_dict(vs_l)
            db_vs_r = split_dict(vs_r)

            both_missing = not db_vs_l and not db_vs_r
            identical = (
                db_vs_l
                and db_vs_r
                and db_vs_l.get("batting_avg") == db_vs_r.get("batting_avg")
                and db_vs_l.get("pa") == db_vs_r.get("pa")
            )

            splits = _fetch_team_splits_live(team_id, season) if both_missing or identical else {
                "vsL": db_vs_l,
                "vsR": db_vs_r,
            }

        team_standing = None
        try:
            standings_data = _request_json(
                f"{MLB_STATS_BASE}/standings",
                params={
                    "leagueId": "103,104",
                    "season": season,
                    "standingsTypes": "regularSeason",
                    "hydrate": "team,division,record",
                },
                timeout=15,
            )

            for division_record in standings_data.get("records", []):
                for team_record in division_record.get("teamRecords", []):
                    team = team_record.get("team") or {}
                    if team.get("id") != team_id:
                        continue

                    team_standing = {
                        "team_name": team.get("name"),
                        "wins": team_record.get("wins"),
                        "losses": team_record.get("losses"),
                        "pct": team_record.get("winningPercentage"),
                        "games_back": team_record.get("gamesBack"),
                        "division": (division_record.get("division") or {}).get("nameShort"),
                        "streak": (team_record.get("streak") or {}).get("streakCode"),
                    }
                    break

                if team_standing:
                    break
        except Exception:
            pass

        return {
            "team_id": team_id,
            "season": season,
            "standing": team_standing,
            "splits": splits,
        }

    @app.post("/predict")
    def predict_matchup(req: PredictRequest) -> Dict[str, Any]:
        season = req.season or datetime.date.today().year

        Session = _get_session()
        with Session() as session:
            result = score_individual_matchup(
                session,
                pitcher_id=req.pitcher_id,
                batter_id=req.batter_id,
                season=season,
                pitcher_throws=req.pitcher_throws,
            )

        return {
            "pitcher_id": req.pitcher_id,
            "batter_id": req.batter_id,
            **result,
        }

    @app.get("/live/scoreboard")
    def live_scoreboard(background_tasks: BackgroundTasks, date: Optional[str] = None) -> Dict[str, Any]:
        """Today's games: scores, status, inning, weather, probable pitchers, decisions."""
        target_date = date or datetime.date.today().isoformat()
        cache_key = f"scoreboard:{target_date}"
        cached = _live_cache_get(cache_key)

        if cached is not None:
            for game in cached.get("games", []):
                if game.get("status_abstract") == "Final" and game.get("game_pk"):
                    background_tasks.add_task(_snapshot_final_game, int(game["game_pk"]))
            return cached

        try:
            data = _request_json(
                f"{MLB_STATS_BASE}/schedule",
                params={
                    "sportId": 1,
                    "date": target_date,
                    "hydrate": "linescore,decisions,probablePitcher,weather,flags",
                },
                timeout=15,
            )
        except Exception as exc:
            raise HTTPException(status_code=502, detail=f"MLB API error: {exc}")

        games = []
        for date_entry in data.get("dates", []):
            for game in date_entry.get("games", []):
                status = game.get("status", {})
                teams = game.get("teams", {})

                away = teams.get("away", {})
                home = teams.get("home", {})

                away_team = away.get("team", {})
                home_team = home.get("team", {})

                linescore = game.get("linescore", {})

                away_probable = away.get("probablePitcher") or {}
                home_probable = home.get("probablePitcher") or {}

                decisions = game.get("decisions") or {}
                winner = decisions.get("winner") or {}
                loser = decisions.get("loser") or {}
                save = decisions.get("save") or {}

                games.append(
                    {
                        "game_pk": game.get("gamePk"),
                        "game_datetime": game.get("gameDate"),
                        "venue": (game.get("venue") or {}).get("name"),
                        "status_code": status.get("statusCode"),
                        "status_abstract": status.get("abstractGameState"),
                        "status_detail": status.get("detailedState"),
                        "inning": linescore.get("currentInning"),
                        "inning_state": linescore.get("inningState"),
                        "outs": linescore.get("outs"),
                        "away": {
                            "team_id": away_team.get("id"),
                            "name": away_team.get("name"),
                            "abbreviation": away_team.get("abbreviation"),
                            "score": away.get("score"),
                            "probable_pitcher": {
                                "id": away_probable.get("id"),
                                "name": away_probable.get("fullName"),
                            } if away_probable.get("id") else None,
                        },
                        "home": {
                            "team_id": home_team.get("id"),
                            "name": home_team.get("name"),
                            "abbreviation": home_team.get("abbreviation"),
                            "score": home.get("score"),
                            "probable_pitcher": {
                                "id": home_probable.get("id"),
                                "name": home_probable.get("fullName"),
                            } if home_probable.get("id") else None,
                        },
                        "weather": _extract_weather(game),
                        "decisions": {
                            "winner": {
                                "id": winner.get("id"),
                                "name": winner.get("fullName"),
                            } if winner.get("id") else None,
                            "loser": {
                                "id": loser.get("id"),
                                "name": loser.get("fullName"),
                            } if loser.get("id") else None,
                            "save": {
                                "id": save.get("id"),
                                "name": save.get("fullName"),
                            } if save.get("id") else None,
                        },
                    }
                )

        result = {
            "date": target_date,
            "game_count": len(games),
            "games": games,
        }

        is_live = any(game["status_abstract"] == "Live" for game in games)
        _live_cache_set(cache_key, result, ttl=8 if is_live else 60)

        # Finalization is intentionally outside the response path. The Live
        # scoreboard remains fast while each terminal game becomes a durable,
        # immutable Final snapshot in the background.
        for game in games:
            if game.get("status_abstract") == "Final" and game.get("game_pk"):
                background_tasks.add_task(_snapshot_final_game, int(game["game_pk"]))

        return result

    @app.get("/final")
    def final_scoreboard(
        date: Optional[str] = None,
        hydrate: bool = Query(True),
    ) -> Dict[str, Any]:
        """Completed-game snapshots for one MLB date; defaults to yesterday."""

        target_date = date or (datetime.date.today() - datetime.timedelta(days=1)).isoformat()
        try:
            parsed_date = datetime.date.fromisoformat(target_date)
        except ValueError:
            raise HTTPException(status_code=400, detail="date must be YYYY-MM-DD")

        hydration = {"attempted": 0, "snapshotted": 0, "errors": []}
        if hydrate:
            hydration = _hydrate_final_snapshots_for_date(target_date)

        Session = _get_session()
        with Session() as session:
            snapshots = list_final_snapshots(session, parsed_date)
            games = [serialize_snapshot(snapshot, include_payload=False) for snapshot in snapshots]

        return {
            "date": target_date,
            "game_count": len(games),
            "games": games,
            "snapshot_status": hydration,
            "source": "final_game_snapshots",
        }

    @app.get("/final/game/{game_pk}")
    def final_game(game_pk: int) -> Dict[str, Any]:
        """One immutable, complete final-game snapshot."""

        Session = _get_session()
        with Session() as session:
            snapshot = get_final_snapshot(session, game_pk)
            if snapshot is not None:
                return serialize_snapshot(snapshot)

        result = _snapshot_final_game(game_pk)
        if result.get("status") not in {"snapshotted", "existing"}:
            raise HTTPException(status_code=404, detail="Final snapshot is not available for this game")

        with Session() as session:
            snapshot = get_final_snapshot(session, game_pk)
            if snapshot is None:
                raise HTTPException(status_code=404, detail="Final snapshot is not available for this game")
            return serialize_snapshot(snapshot)

    @app.get("/live/game/{game_pk}")
    def live_game_state(game_pk: int) -> Dict[str, Any]:
        """Current live game state with current/last play, count, runners, and pitch sequence."""
        feed = _fetch_live_feed(game_pk)
        if feed is None:
            raise HTTPException(status_code=502, detail="Could not fetch live game feed")

        game_data = feed.get("gameData", {}) or {}
        live_data = feed.get("liveData", {}) or {}

        status = game_data.get("status", {}) or {}
        teams = game_data.get("teams", {}) or {}
        datetime_data = game_data.get("datetime", {}) or {}
        linescore = live_data.get("linescore", {}) or {}
        linescore_teams = linescore.get("teams") or {}
        offense = linescore.get("offense") or {}
        defense = linescore.get("defense") or {}

        current_play = _select_live_current_play(live_data)
        play_payload = _live_play_payload(current_play) if current_play else {}
        count = play_payload.get("count") or {}

        all_plays = (live_data.get("plays") or {}).get("allPlays") or []
        recent_plays = [
            _live_play_payload(play)
            for play in all_plays[-5:]
        ]

        return {
            "game_pk": game_pk,
            "game_datetime": datetime_data.get("dateTime"),
            "official_date": datetime_data.get("officialDate"),
            "status": status.get("detailedState"),
            "status_code": status.get("statusCode"),
            "status_abstract": status.get("abstractGameState"),
            "is_live": status.get("abstractGameState") == "Live",
            "inning": linescore.get("currentInning"),
            "inning_ordinal": linescore.get("currentInningOrdinal"),
            "inning_state": linescore.get("inningState"),
            "inning_half": linescore.get("inningHalf"),
            "scheduled_innings": linescore.get("scheduledInnings"),
            "outs": linescore.get("outs") if linescore.get("outs") is not None else count.get("outs"),
            "balls": count.get("balls"),
            "strikes": count.get("strikes"),
            "away": {
                "id": (teams.get("away") or {}).get("id"),
                "name": (teams.get("away") or {}).get("name"),
                "runs": ((linescore_teams.get("away") or {}).get("runs")),
                "hits": ((linescore_teams.get("away") or {}).get("hits")),
                "errors": ((linescore_teams.get("away") or {}).get("errors")),
            },
            "home": {
                "id": (teams.get("home") or {}).get("id"),
                "name": (teams.get("home") or {}).get("name"),
                "runs": ((linescore_teams.get("home") or {}).get("runs")),
                "hits": ((linescore_teams.get("home") or {}).get("hits")),
                "errors": ((linescore_teams.get("home") or {}).get("errors")),
            },
            "batter": play_payload.get("batter") or _person_payload(offense.get("batter")),
            "pitcher": play_payload.get("pitcher") or _person_payload(defense.get("pitcher")),
            "on_deck": _person_payload(offense.get("onDeck")),
            "in_hole": _person_payload(offense.get("inHole")),
            "runners": {
                "first": _runner_payload(offense.get("first")),
                "second": _runner_payload(offense.get("second")),
                "third": _runner_payload(offense.get("third")),
            },
            "current_play": play_payload,
            "last_pitch": play_payload.get("last_pitch"),
            "last_hit": play_payload.get("last_hit"),
            "pitch_sequence": play_payload.get("pitch_sequence") or [],
            "recent_plays": recent_plays,
            "source": "mlb_live_feed",
        }

    @app.get("/live/game/{game_pk}/boxscore")
    def live_game_boxscore(game_pk: int) -> Dict[str, Any]:
        """Complete Away/Home batting and pitching lines for every participant."""
        feed = _fetch_live_feed(game_pk)
        if feed is None:
            raise HTTPException(status_code=502, detail="Could not fetch live game feed")
        return build_game_boxscore_payload(feed)

    @app.get("/live/game/{game_pk}/plays")
    def live_game_plays(game_pk: int, limit: int = Query(25, ge=1, le=100)) -> Dict[str, Any]:
        """Recent play-by-play with pitch and hit data."""
        feed = _fetch_live_feed(game_pk)
        if feed is None:
            raise HTTPException(status_code=502, detail="Could not fetch live game feed")

        plays = (feed.get("liveData", {}).get("plays") or {}).get("allPlays", [])
        recent = plays[-limit:]
        out = [_live_play_payload(play) for play in reversed(recent)]

        return {
            "game_pk": game_pk,
            "count": len(out),
            "plays": out,
            "source": "mlb_live_feed",
        }

    @app.get("/live/game/{game_pk}/linescore")
    def live_game_linescore(game_pk: int) -> Dict[str, Any]:
        """Inning-by-inning runs/hits/errors and game decisions."""
        feed = _fetch_live_feed(game_pk)
        if feed is None:
            raise HTTPException(status_code=502, detail="Could not fetch live game feed")

        game_data = feed.get("gameData", {})
        live_data = feed.get("liveData", {})

        teams = game_data.get("teams", {})
        linescore = live_data.get("linescore", {})
        decisions = live_data.get("decisions") or {}

        innings = []
        for inning in linescore.get("innings", []) or []:
            innings.append(
                {
                    "num": inning.get("num"),
                    "ordinal_num": inning.get("ordinalNum"),
                    "away": inning.get("away", {}),
                    "home": inning.get("home", {}),
                }
            )

        return {
            "game_pk": game_pk,
            "current_inning": linescore.get("currentInning"),
            "inning_state": linescore.get("inningState"),
            "scheduled_innings": linescore.get("scheduledInnings"),
            "teams": {
                "away": {
                    "id": (teams.get("away") or {}).get("id"),
                    "name": (teams.get("away") or {}).get("name"),
                    **((linescore.get("teams") or {}).get("away") or {}),
                },
                "home": {
                    "id": (teams.get("home") or {}).get("id"),
                    "name": (teams.get("home") or {}).get("name"),
                    **((linescore.get("teams") or {}).get("home") or {}),
                },
            },
            "innings": innings,
            "decisions": {
                "winner": decisions.get("winner"),
                "loser": decisions.get("loser"),
                "save": decisions.get("save"),
            },
        }

    return app


app = create_app()
