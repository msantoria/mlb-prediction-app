from __future__ import annotations

import datetime
import time
from typing import Any, Dict, Optional, Tuple

import requests as _req
from fastapi import APIRouter, Query

from .batter_data_contract import (
    LOCAL_SPLITS_SOURCE,
    MLB_SEASON_SOURCE,
    MLB_SPLITS_SOURCE,
    MLB_YEAR_BY_YEAR_SOURCE,
    STATCAST_ROLLING_SOURCE,
    clean_rolling_by_ab,
    clean_rolling_by_games,
    clean_rolling_by_pa,
    clean_rolling_pitch_types,
    clean_rolling_splits,
    dedupe_rows,
    parse_window_list,
)
from .database import get_engine, create_tables, get_session
from .db_utils import (
    get_batter_aggregate_with_fallback,
    get_batter_at_bats,
    get_batter_data_quality,
    get_batter_leaderboards,
    get_batter_multi_season,
    get_batter_statcast_profile,
    get_player_splits_multi_season,
)
from .pitcher_intelligence import MLB_TIMEZONE, build_pitcher_intelligence_profile
from .pitcher_leaderboards import build_pitcher_leaderboards
from .official_player_stats import OfficialPlayerStatsUnavailable, fetch_official_hitting_season

MLB_STATS_BASE = "https://statsapi.mlb.com/api/v1"
router = APIRouter()

_LEADERBOARD_TTL_SECONDS = 3600
_BATTER_LEADERBOARD_TTL_SECONDS = 60
_leaderboard_cache: Dict[str, Tuple[float, Dict[str, Any]]] = {}
_pitcher_leaderboard_cache: Dict[str, Tuple[float, Dict[str, Any]]] = {}
_identity_cache: Dict[int, Tuple[float, Dict[str, Any]]] = {}


def _get_session():
    import os
    db_url = os.getenv("DATABASE_URL", "sqlite:///mlb.db")
    engine = get_engine(db_url)
    create_tables(engine)
    return get_session(engine)


def _safe_float(val) -> Optional[float]:
    try:
        return float(val) if val is not None else None
    except (TypeError, ValueError):
        return None


def _fetch_player_identity(player_id: int) -> Dict[str, Any]:
    cached = _identity_cache.get(player_id)
    if cached is not None:
        cached_at, payload = cached
        if time.monotonic() - cached_at < _LEADERBOARD_TTL_SECONDS:
            return payload

    payload = {"id": player_id, "name": None, "team": None, "team_abbreviation": None, "position": None, "position_type": None, "throws": None, "bats": None, "source": "fallback"}
    try:
        r = _req.get(f"{MLB_STATS_BASE}/people/{player_id}", params={"hydrate": "currentTeam"}, timeout=10)
        if r.ok:
            p = (r.json().get("people") or [{}])[0]
            team = p.get("currentTeam") or {}
            position = p.get("primaryPosition") or {}
            payload.update({
                "name": p.get("fullName"),
                "team": team.get("name"),
                "team_abbreviation": team.get("abbreviation"),
                "position": position.get("abbreviation"),
                "position_type": position.get("type"),
                "throws": (p.get("pitchHand") or {}).get("code"),
                "bats": (p.get("batSide") or {}).get("code"),
                "source": "mlb_stats_api_people",
            })
    except Exception:
        pass

    _identity_cache[player_id] = (time.monotonic(), payload)
    return payload


def _fetch_batter_live_data(player_id: int, season: int) -> Dict[str, Any]:
    out: Dict[str, Any] = {
        "player_info": None,
        "season_stats": None,
        "season_stats_source": None,
        "season_stats_warnings": [],
        "splits": {"vsL": None, "vsR": None},
        "splits_source": None,
        "year_by_year": [],
        "year_by_year_source": None,
    }

    identity = _fetch_player_identity(player_id)
    if identity.get("name"):
        out["player_info"] = {"name": identity.get("name"), "position": identity.get("position"), "team": identity.get("team"), "bats": identity.get("bats"), "throws": identity.get("throws"), "birth_date": None, "mlb_debut": None, "source": identity.get("source")}

    def _parse_stat(s: dict) -> Dict[str, Any]:
        pa = s.get("plateAppearances") or 0
        k = s.get("strikeOuts") or 0
        bb = s.get("baseOnBalls") or 0
        batting_avg = _safe_float(s.get("avg"))
        on_base_pct = _safe_float(s.get("obp"))
        slugging_pct = _safe_float(s.get("slg"))
        return {
            "g": s.get("gamesPlayed"),
            "ab": s.get("atBats"),
            "pa": pa,
            "r": s.get("runs"),
            "h": s.get("hits"),
            "doubles": s.get("doubles"),
            "triples": s.get("triples"),
            "hr": s.get("homeRuns"),
            "rbi": s.get("rbi"),
            "sb": s.get("stolenBases"),
            "bb": bb,
            "k": k,
            "batting_avg": batting_avg,
            "on_base_pct": on_base_pct,
            "slugging_pct": slugging_pct,
            "ops": _safe_float(s.get("ops")),
            "k_pct": round(k / pa, 3) if pa > 0 else None,
            "bb_pct": round(bb / pa, 3) if pa > 0 else None,
            "home_runs": s.get("homeRuns"),
            # Stable aliases retained for existing profile clients.
            "avg": batting_avg,
            "obp": on_base_pct,
            "slg": slugging_pct,
            "plate_appearances": pa,
        }

    try:
        r = _req.get(f"{MLB_STATS_BASE}/people/{player_id}/stats", params={"stats": "season", "group": "hitting", "season": season}, timeout=10)
        if r.ok:
            splits = (r.json().get("stats") or [{}])[0].get("splits", [])
            if splits:
                out["season_stats"] = _parse_stat(splits[0].get("stat", {}))
                out["season_stats"]["season"] = season
                out["season_stats"]["source"] = MLB_SEASON_SOURCE
                out["season_stats_source"] = MLB_SEASON_SOURCE
            else:
                out["season_stats_warnings"].append(f"MLB Stats API returned no season hitting split for {player_id} in {season}.")
        else:
            out["season_stats_warnings"].append(f"MLB Stats API season request failed with status {r.status_code}.")
    except Exception as exc:
        out["season_stats_warnings"].append(f"MLB Stats API season request failed: {exc}")

    for sit, key in [("vl", "vsL"), ("vr", "vsR")]:
        try:
            r = _req.get(f"{MLB_STATS_BASE}/people/{player_id}/stats", params={"stats": "statSplits", "group": "hitting", "season": season, "sitCodes": sit}, timeout=10)
            if r.ok:
                splits = (r.json().get("stats") or [{}])[0].get("splits", [])
                if splits:
                    out["splits"][key] = {**_parse_stat(splits[0].get("stat", {})), "season": season, "source": MLB_SPLITS_SOURCE}
                    out["splits_source"] = MLB_SPLITS_SOURCE
        except Exception:
            pass

    try:
        r = _req.get(f"{MLB_STATS_BASE}/people/{player_id}/stats", params={"stats": "yearByYear", "group": "hitting"}, timeout=15)
        if r.ok:
            by_season: Dict[str, Dict[str, Any]] = {}
            for sp in (r.json().get("stats") or [{}])[0].get("splits", []):
                yr = sp.get("season")
                if yr and yr not in by_season:
                    by_season[yr] = {**_parse_stat(sp.get("stat", {})), "season": yr, "source": MLB_YEAR_BY_YEAR_SOURCE}
            out["year_by_year"] = sorted(by_season.values(), key=lambda x: x["season"], reverse=True)
            out["year_by_year_source"] = MLB_YEAR_BY_YEAR_SOURCE if out["year_by_year"] else None
    except Exception:
        pass

    return out


def _aggregate_to_dict(agg) -> Optional[Dict[str, Any]]:
    if not agg:
        return None
    return {"avg_exit_velocity": agg.avg_exit_velocity, "avg_launch_angle": agg.avg_launch_angle, "hard_hit_pct": agg.hard_hit_pct, "barrel_pct": agg.barrel_pct, "k_pct": agg.k_pct, "bb_pct": agg.bb_pct, "batting_avg": agg.batting_avg, "end_date": agg.end_date.isoformat() if agg.end_date else None, "window": agg.window, "source": "postgres_batter_aggregates"}


def _statcast_profile_to_aggregate(profile: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    if not profile:
        return None
    fields = (
        "avg_exit_velocity",
        "avg_launch_angle",
        "hard_hit_pct",
        "barrel_pct",
        "k_pct",
        "bb_pct",
        "batting_avg",
        "end_date",
        "window",
        "source",
        "actual_pa",
        "canonical_pitch_rows",
        "duplicate_rows_removed",
    )
    return {field: profile.get(field) for field in fields}


def _canonical_multi_season_rows(
    session,
    batter_id: int,
    seasons: list[int],
    current_season: int,
    current_profile: Optional[Dict[str, Any]],
) -> list[Dict[str, Any]]:
    stored_by_season = {
        int(row["season"]): row
        for row in get_batter_multi_season(session, batter_id, seasons)
        if row.get("season") is not None
    }
    rows: list[Dict[str, Any]] = []
    for profile_season in seasons:
        profile = current_profile if profile_season == current_season else get_batter_statcast_profile(
            session,
            batter_id,
            start_date=datetime.date(profile_season, 1, 1),
            end_date=datetime.date(profile_season, 12, 31),
        )
        if not profile:
            rows.append(stored_by_season.get(profile_season, {"season": profile_season, "label": str(profile_season)}))
            continue
        rows.append(
            {
                "season": profile_season,
                "label": "YTD (90d)" if profile_season == current_season else str(profile_season),
                "avg_exit_velocity": profile.get("avg_exit_velocity"),
                "avg_launch_angle": profile.get("avg_launch_angle"),
                "hard_hit_pct": profile.get("hard_hit_pct"),
                "barrel_pct": profile.get("barrel_pct"),
                "k_pct": profile.get("k_pct"),
                "bb_pct": profile.get("bb_pct"),
                "batting_avg": profile.get("batting_avg"),
                "actual_pa": profile.get("actual_pa"),
                "source": profile.get("source"),
            }
        )
    return rows


@router.get("/data/freshness")
def data_freshness() -> Dict[str, Any]:
    from .data_freshness import build_data_freshness_payload
    Session = _get_session()
    with Session() as session:
        return build_data_freshness_payload(session)


@router.get("/player/{id}/identity")
def player_identity(id: int) -> Dict[str, Any]:
    return _fetch_player_identity(id)


@router.get("/batters/leaderboards")
def batters_leaderboards(season: Optional[int] = None, min_pa: int = Query(25, ge=1), min_bbe: int = Query(100, ge=1), limit: int = Query(10, ge=1, le=50)) -> Dict[str, Any]:
    if season is None:
        season = datetime.datetime.now(MLB_TIMEZONE).year
    cache_key = f"{season}:{min_pa}:{min_bbe}:{limit}"
    cached = _leaderboard_cache.get(cache_key)
    if cached is not None:
        cached_at, data = cached
        if time.monotonic() - cached_at < _BATTER_LEADERBOARD_TTL_SECONDS:
            return data
    official_hitting: Dict[str, Any] = {}
    official_warning: Optional[str] = None
    try:
        official_hitting = fetch_official_hitting_season(season)
    except OfficialPlayerStatsUnavailable as exc:
        official_warning = str(exc)

    Session = _get_session()
    with Session() as session:
        result = get_batter_leaderboards(
            session,
            season=season,
            min_pa=min_pa,
            min_bbe=min_bbe,
            limit=limit,
            official_hitting=official_hitting,
        )
    if official_warning:
        result.setdefault("warnings", []).append(
            f"Official MLB counting stats unavailable: {official_warning}"
        )
    _leaderboard_cache[cache_key] = (time.monotonic(), result)
    return result


@router.get("/pitchers/leaderboards")
def pitchers_leaderboards(season: Optional[int] = None, limit: int = Query(10, ge=1, le=50)) -> Dict[str, Any]:
    cache_key = f"pitchers:{season}:{limit}"
    cached = _pitcher_leaderboard_cache.get(cache_key)
    if cached is not None:
        cached_at, data = cached
        if time.monotonic() - cached_at < _LEADERBOARD_TTL_SECONDS:
            return data
    Session = _get_session()
    with Session() as session:
        result = build_pitcher_leaderboards(session, season=season, limit=limit)
    _pitcher_leaderboard_cache[cache_key] = (time.monotonic(), result)
    return result


@router.get("/pitcher/{id}/intelligence")
def pitcher_intelligence(id: int, season: Optional[int] = None, days_back: int = Query(365, ge=1, le=3650)) -> Dict[str, Any]:
    if season is None:
        season = datetime.datetime.now(MLB_TIMEZONE).year
    Session = _get_session()
    with Session() as session:
        return build_pitcher_intelligence_profile(session, id, season, days_back=days_back)


@router.get("/batter/{id}/profile")
def batter_profile(id: int, season: Optional[int] = None) -> Dict[str, Any]:
    if season is None:
        season = datetime.datetime.now(MLB_TIMEZONE).year
    Session = _get_session()
    with Session() as session:
        today = datetime.datetime.now(MLB_TIMEZONE).date()
        season_start = datetime.date(season, 1, 1)
        season_end = min(datetime.date(season, 12, 31), today)
        data_quality = get_batter_data_quality(session, id)
        latest_text = data_quality.get("latest_event_date")
        latest_date = datetime.date.fromisoformat(latest_text) if latest_text else None
        profile_end = (
            latest_date
            if latest_date is not None and season_start <= latest_date <= season_end
            else season_end
        )
        profile_start = max(season_start, profile_end - datetime.timedelta(days=89))
        statcast_profile = get_batter_statcast_profile(
            session,
            id,
            start_date=profile_start,
            end_date=profile_end,
        )
        stored_agg, stored_agg_label = get_batter_aggregate_with_fallback(session, id, season)
        aggregate = _statcast_profile_to_aggregate(statcast_profile) or _aggregate_to_dict(stored_agg)
        agg_label = "Canonical Statcast · Last 90 Days" if statcast_profile else stored_agg_label
        seasons = [season, season - 1, season - 2]
        multi_season = _canonical_multi_season_rows(
            session,
            id,
            seasons,
            season,
            statcast_profile,
        )
        live = _fetch_batter_live_data(id, season)
        local_splits = get_player_splits_multi_season(session, id, seasons)
        splits = local_splits or live.get("splits")
        return {
            "batter_id": id,
            "season": season,
            "player_info": live.get("player_info"),
            "season_stats": live.get("season_stats"),
            "season_stats_source": live.get("season_stats_source"),
            "season_stats_warnings": live.get("season_stats_warnings", []),
            "season_stats_contract": "Official season hitting line only. Do not replace with local Statcast aggregate semantics.",
            "aggregate_label": agg_label,
            "aggregate": aggregate,
            "aggregate_source": aggregate.get("source") if aggregate else None,
            "statcast": statcast_profile,
            "statcast_source": statcast_profile.get("source") if statcast_profile else None,
            "multi_season": dedupe_rows(multi_season, ["season", "label"]),
            "multi_season_source": "postgres_statcast_events_canonical_pitch_identity",
            "splits": splits,
            "splits_source": LOCAL_SPLITS_SOURCE if local_splits else live.get("splits_source"),
            "year_by_year": dedupe_rows(live.get("year_by_year", []), ["season"]),
            "year_by_year_source": live.get("year_by_year_source"),
            "rolling_sources": {"pa": STATCAST_ROLLING_SOURCE, "ab": STATCAST_ROLLING_SOURCE, "games": STATCAST_ROLLING_SOURCE, "splits": STATCAST_ROLLING_SOURCE, "pitch_types": STATCAST_ROLLING_SOURCE},
            "data_quality": data_quality,
        }


@router.get("/batter/{id}/rolling/pa")
def batter_rolling_pa(id: int, windows: str = Query("10,25,50,100")) -> Dict[str, Any]:
    parsed = parse_window_list(windows, [10, 25, 50, 100])
    Session = _get_session()
    with Session() as session:
        return {"batter_id": id, "window_type": "PA", "source": STATCAST_ROLLING_SOURCE, "windows": {str(w): clean_rolling_by_pa(session, id, w) for w in parsed}, "data_quality": get_batter_data_quality(session, id)}


@router.get("/batter/{id}/rolling/ab")
def batter_rolling_ab(id: int, windows: str = Query("10,25,50,100")) -> Dict[str, Any]:
    parsed = parse_window_list(windows, [10, 25, 50, 100])
    Session = _get_session()
    with Session() as session:
        return {"batter_id": id, "window_type": "AB", "source": STATCAST_ROLLING_SOURCE, "windows": {str(w): clean_rolling_by_ab(session, id, w) for w in parsed}, "data_quality": get_batter_data_quality(session, id)}


@router.get("/batter/{id}/rolling/games")
def batter_rolling_games(id: int, windows: str = Query("5,10,15,30")) -> Dict[str, Any]:
    parsed = parse_window_list(windows, [5, 10, 15, 30])
    Session = _get_session()
    with Session() as session:
        return {"batter_id": id, "window_type": "games", "source": STATCAST_ROLLING_SOURCE, "windows": {str(w): clean_rolling_by_games(session, id, w) for w in parsed}, "data_quality": get_batter_data_quality(session, id)}


@router.get("/batter/{id}/rolling/splits")
def batter_rolling_splits(id: int, pa: int = 100) -> Dict[str, Any]:
    Session = _get_session()
    with Session() as session:
        return {"batter_id": id, **clean_rolling_splits(session, id, pa)}


@router.get("/batter/{id}/rolling/pitch-types")
def batter_rolling_pitch_types(id: int, pa: int = 100) -> Dict[str, Any]:
    Session = _get_session()
    with Session() as session:
        return {"batter_id": id, **clean_rolling_pitch_types(session, id, pa)}


@router.get("/batter/{id}/rolling/legacy")
def batter_rolling_legacy(id: int) -> Dict[str, Any]:
    windows = [10, 25, 50, 100, 200, 400, 1000]
    Session = _get_session()
    with Session() as session:
        return {"batter_id": id, "window_type": "PA", "legacy_note": "Legacy rolling abs endpoint uses PA-style terminal outcomes. Use /rolling/ab for strict AB windows.", "source": STATCAST_ROLLING_SOURCE, "windows": {str(w): clean_rolling_by_pa(session, id, w) for w in windows}, "data_quality": get_batter_data_quality(session, id)}


@router.get("/batter/{id}/qa")
def batter_data_quality(id: int) -> Dict[str, Any]:
    Session = _get_session()
    with Session() as session:
        return {"batter_id": id, "data_quality": get_batter_data_quality(session, id)}


@router.get("/batter/{id}/at-bats/ordered")
def batter_ordered_at_bats(id: int, limit: int = 50, offset: int = 0) -> Dict[str, Any]:
    Session = _get_session()
    with Session() as session:
        total, rows = get_batter_at_bats(session, id, n=limit, offset=offset)
        deduped_rows = dedupe_rows(rows, ["game_pk", "at_bat_number", "pitcher_id", "result"])
        return {"batter_id": id, "total": total, "limit": limit, "offset": offset, "events": deduped_rows, "source": STATCAST_ROLLING_SOURCE, "duplicate_rows_removed": max(len(rows) - len(deduped_rows), 0), "data_quality": get_batter_data_quality(session, id)}
