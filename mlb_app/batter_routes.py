from __future__ import annotations

import datetime
from typing import Any, Dict, Optional

import requests as _req
from fastapi import APIRouter, HTTPException, Query

from .database import get_engine, create_tables, get_session
from .db_utils import (
    get_batter_aggregate_with_fallback,
    get_batter_at_bats,
    get_batter_data_quality,
    get_batter_multi_season,
    get_batter_rolling_by_ab,
    get_batter_rolling_by_abs,
    get_batter_rolling_by_games,
    get_batter_rolling_by_pa,
    get_batter_rolling_pitch_types,
    get_batter_rolling_splits,
    get_player_splits_multi_season,
)

MLB_STATS_BASE = "https://statsapi.mlb.com/api/v1"
router = APIRouter()


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


def _fetch_batter_live_data(player_id: int, season: int) -> Dict[str, Any]:
    out: Dict[str, Any] = {
        "player_info": None,
        "season_stats": None,
        "splits": {"vsL": None, "vsR": None},
        "year_by_year": [],
    }

    try:
        r = _req.get(
            f"{MLB_STATS_BASE}/people/{player_id}",
            params={"hydrate": "currentTeam"},
            timeout=10,
        )
        if r.ok:
            p = (r.json().get("people") or [{}])[0]
            out["player_info"] = {
                "name": p.get("fullName"),
                "position": (p.get("primaryPosition") or {}).get("abbreviation"),
                "team": (p.get("currentTeam") or {}).get("name"),
                "bats": (p.get("batSide") or {}).get("code"),
                "throws": (p.get("pitchHand") or {}).get("code"),
                "birth_date": p.get("birthDate"),
                "mlb_debut": p.get("mlbDebutDate"),
            }
    except Exception:
        pass

    def _parse_stat(s: dict) -> Dict[str, Any]:
        pa = s.get("plateAppearances") or 0
        k = s.get("strikeOuts") or 0
        bb = s.get("baseOnBalls") or 0
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
            "batting_avg": _safe_float(s.get("avg")),
            "on_base_pct": _safe_float(s.get("obp")),
            "slugging_pct": _safe_float(s.get("slg")),
            "ops": _safe_float(s.get("ops")),
            "k_pct": round(k / pa, 3) if pa > 0 else None,
            "bb_pct": round(bb / pa, 3) if pa > 0 else None,
            "home_runs": s.get("homeRuns"),
        }

    try:
        r = _req.get(
            f"{MLB_STATS_BASE}/people/{player_id}/stats",
            params={"stats": "season", "group": "hitting", "season": season},
            timeout=10,
        )
        if r.ok:
            splits = (r.json().get("stats") or [{}])[0].get("splits", [])
            if splits:
                out["season_stats"] = _parse_stat(splits[0].get("stat", {}))
    except Exception:
        pass

    for sit, key in [("vl", "vsL"), ("vr", "vsR")]:
        try:
            r = _req.get(
                f"{MLB_STATS_BASE}/people/{player_id}/stats",
                params={"stats": "statSplits", "group": "hitting", "season": season, "sitCodes": sit},
                timeout=10,
            )
            if r.ok:
                splits = (r.json().get("stats") or [{}])[0].get("splits", [])
                if splits:
                    out["splits"][key] = _parse_stat(splits[0].get("stat", {}))
        except Exception:
            pass

    try:
        r = _req.get(
            f"{MLB_STATS_BASE}/people/{player_id}/stats",
            params={"stats": "yearByYear", "group": "hitting"},
            timeout=15,
        )
        if r.ok:
            for sp in (r.json().get("stats") or [{}])[0].get("splits", []):
                yr = sp.get("season")
                if yr:
                    row = _parse_stat(sp.get("stat", {}))
                    row["season"] = yr
                    out["year_by_year"].append(row)
            out["year_by_year"].sort(key=lambda x: x["season"], reverse=True)
    except Exception:
        pass

    return out


def _aggregate_to_dict(agg) -> Optional[Dict[str, Any]]:
    if not agg:
        return None
    return {
        "avg_exit_velocity": agg.avg_exit_velocity,
        "avg_launch_angle": agg.avg_launch_angle,
        "hard_hit_pct": agg.hard_hit_pct,
        "barrel_pct": agg.barrel_pct,
        "k_pct": agg.k_pct,
        "bb_pct": agg.bb_pct,
        "batting_avg": agg.batting_avg,
        "end_date": agg.end_date.isoformat() if agg.end_date else None,
        "window": agg.window,
    }


@router.get("/batter/{id}/profile")
def batter_profile(id: int, season: Optional[int] = None) -> Dict[str, Any]:
    if season is None:
        season = datetime.date.today().year
    Session = _get_session()
    with Session() as session:
        agg, agg_label = get_batter_aggregate_with_fallback(session, id, season)
        seasons = [season, season - 1, season - 2]
        live = _fetch_batter_live_data(id, season)
        return {
            "batter_id": id,
            "season": season,
            "player_info": live.get("player_info"),
            "season_stats": live.get("season_stats"),
            "aggregate_label": agg_label,
            "aggregate": _aggregate_to_dict(agg),
            "multi_season": get_batter_multi_season(session, id, seasons),
            "splits": get_player_splits_multi_season(session, id, seasons) or live.get("splits"),
            "year_by_year": live.get("year_by_year", []),
            "data_quality": get_batter_data_quality(session, id),
        }


@router.get("/batter/{id}/rolling/pa")
def batter_rolling_pa(id: int, windows: str = Query("10,25,50,100")) -> Dict[str, Any]:
    parsed = [int(w.strip()) for w in windows.split(",") if w.strip().isdigit()]
    parsed = parsed or [10, 25, 50, 100]
    Session = _get_session()
    with Session() as session:
        return {
            "batter_id": id,
            "window_type": "PA",
            "windows": {str(w): get_batter_rolling_by_pa(session, id, w) for w in parsed},
            "data_quality": get_batter_data_quality(session, id),
        }


@router.get("/batter/{id}/rolling/ab")
def batter_rolling_ab(id: int, windows: str = Query("10,25,50,100")) -> Dict[str, Any]:
    parsed = [int(w.strip()) for w in windows.split(",") if w.strip().isdigit()]
    parsed = parsed or [10, 25, 50, 100]
    Session = _get_session()
    with Session() as session:
        return {
            "batter_id": id,
            "window_type": "AB",
            "windows": {str(w): get_batter_rolling_by_ab(session, id, w) for w in parsed},
            "data_quality": get_batter_data_quality(session, id),
        }


@router.get("/batter/{id}/rolling/games")
def batter_rolling_games(id: int, windows: str = Query("5,10,15,30")) -> Dict[str, Any]:
    parsed = [int(w.strip()) for w in windows.split(",") if w.strip().isdigit()]
    parsed = parsed or [5, 10, 15, 30]
    Session = _get_session()
    with Session() as session:
        return {
            "batter_id": id,
            "window_type": "games",
            "windows": {str(w): get_batter_rolling_by_games(session, id, w) for w in parsed},
            "data_quality": get_batter_data_quality(session, id),
        }


@router.get("/batter/{id}/rolling/splits")
def batter_rolling_splits(id: int, pa: int = 100) -> Dict[str, Any]:
    Session = _get_session()
    with Session() as session:
        return {"batter_id": id, **get_batter_rolling_splits(session, id, pa)}


@router.get("/batter/{id}/rolling/pitch-types")
def batter_rolling_pitch_types(id: int, pa: int = 100) -> Dict[str, Any]:
    Session = _get_session()
    with Session() as session:
        return {"batter_id": id, **get_batter_rolling_pitch_types(session, id, pa)}


@router.get("/batter/{id}/rolling/legacy")
def batter_rolling_legacy(id: int) -> Dict[str, Any]:
    windows = [10, 25, 50, 100, 200, 400, 1000]
    Session = _get_session()
    with Session() as session:
        return {
            "batter_id": id,
            "window_type": "PA",
            "legacy_note": "Legacy rolling abs endpoint uses PA-style terminal outcomes. Use /rolling/ab for strict AB windows.",
            "windows": {str(w): get_batter_rolling_by_abs(session, id, w) for w in windows},
            "data_quality": get_batter_data_quality(session, id),
        }


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
        return {
            "batter_id": id,
            "total": total,
            "limit": limit,
            "offset": offset,
            "events": rows,
            "data_quality": get_batter_data_quality(session, id),
        }
