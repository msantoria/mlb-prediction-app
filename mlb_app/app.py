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
"""

from __future__ import annotations

import datetime
import os
from typing import Any, Dict, List, Optional

import requests as _req

try:
    from fastapi import FastAPI, HTTPException, Query
    from fastapi.middleware.cors import CORSMiddleware
    from pydantic import BaseModel
    _FASTAPI = True
except ImportError:
    FastAPI = None
    HTTPException = Exception
    CORSMiddleware = None
    BaseModel = object
    _FASTAPI = False

from .database import StatcastEvent, get_engine, create_tables, get_session
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

MLB_STATS_BASE = "https://statsapi.mlb.com/api/v1"

HIT_EVENTS = {"single", "double", "triple", "home_run"}
OUTCOME_EVENTS = {
    "single", "double", "triple", "home_run",
    "strikeout", "strikeout_double_play",
    "walk", "intent_walk", "hit_by_pitch",
    "field_out", "force_out", "double_play",
    "grounded_into_double_play", "fielders_choice",
    "fielders_choice_out", "sac_fly", "sac_bunt",
}


def _get_session():
    db_url = os.getenv("DATABASE_URL", "sqlite:///mlb.db")
    engine = get_engine(db_url)
    create_tables(engine)
    return get_session(engine)


def _statcast_batting_avg(events: List[StatcastEvent]) -> Optional[float]:
    if not events:
        return None
    pa = len(events)
    hits = sum(1 for e in events if e.events in HIT_EVENTS)
    return round(hits / pa, 3) if pa else None


def _average(values: List[Optional[float]], digits: int = 3) -> Optional[float]:
    nums = [v for v in values if v is not None]
    if not nums:
        return None
    return round(sum(nums) / len(nums), digits)


def _normalize_pitch_label(pitch_type: Optional[str], pitch_name: Optional[str]) -> str:
    return pitch_name or pitch_type or "Unknown"


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


def _player_vs_pitch_type_summary(
    session,
    batter_id: int,
    pitcher_id: int,
    pitch_type: Optional[str],
    season: int,
):
    q = (
        session.query(StatcastEvent)
        .filter(
            StatcastEvent.batter_id == batter_id,
            StatcastEvent.pitcher_id == pitcher_id,
            StatcastEvent.pitch_type == pitch_type,
            StatcastEvent.game_date >= datetime.date(season, 1, 1),
        )
    )
    events = q.all()
    terminal = [e for e in events if e.events and e.events in OUTCOME_EVENTS]
    return {
        "pa": len(terminal),
        "batting_avg": _statcast_batting_avg(terminal),
        "xwoba": None,
        "avg_exit_velocity": _average([e.launch_speed for e in terminal], 1),
        "avg_launch_angle": _average([e.launch_angle for e in terminal], 1),
        "hard_hit_pct": round(sum(1 for e in terminal if (e.launch_speed or 0) >= 95) / len([e for e in terminal if e.launch_speed is not None]), 3)
        if any(e.launch_speed is not None for e in terminal) else None,
    }


def _head_to_head_summary(session, batter_id: int, pitcher_id: int, season: int) -> Dict[str, Any]:
    events = (
        session.query(StatcastEvent)
        .filter(
            StatcastEvent.batter_id == batter_id,
            StatcastEvent.pitcher_id == pitcher_id,
            StatcastEvent.game_date >= datetime.date(season, 1, 1),
        )
        .all()
    )
    terminal = [e for e in events if e.events and e.events in OUTCOME_EVENTS]
    return {
        "pa": len(terminal),
        "batting_avg": _statcast_batting_avg(terminal),
        "xwoba": None,
        "avg_exit_velocity": _average([e.launch_speed for e in terminal], 1),
        "avg_launch_angle": _average([e.launch_angle for e in terminal], 1),
    }


def _build_competitive_matchup(
    session,
    batter_id: int,
    batter_name: str,
    batting_order: int,
    opposing_pitcher_id: int,
    season: int,
) -> Dict[str, Any]:
    arsenal, arsenal_season = get_pitch_arsenal_with_fallback(session, opposing_pitcher_id, season)
    head_to_head = _head_to_head_summary(session, batter_id, opposing_pitcher_id, season)

    pitch_type_matrix = []
    for pitch in arsenal:
        batter_vs_type = _player_vs_pitch_type_summary(
            session, batter_id, opposing_pitcher_id, pitch.pitch_type, season
        )
        pa = batter_vs_type["pa"] or 0
        edge_score = _edge_score_from_components(
            batter_ba=batter_vs_type["batting_avg"],
            batter_xwoba=batter_vs_type["xwoba"],
            pitcher_xwoba=pitch.xwoba,
            pitcher_hard_hit_pct=pitch.hard_hit_pct,
            usage_pct=pitch.usage_pct,
        )
        confidence = _confidence_from_sample(pa, pitch.usage_pct)

        pitch_type_matrix.append(
            {
                "pitch_type": _normalize_pitch_label(pitch.pitch_type, pitch.pitch_name),
                "raw_pitch_type": pitch.pitch_type,
                "pitcher_usage_pct": pitch.usage_pct or 0.0,
                "pitcher_pitch_count": pitch.pitch_count,
                "pitcher_whiff_pct": pitch.whiff_pct,
                "pitcher_strikeout_pct": pitch.strikeout_pct,
                "pitcher_xwoba": pitch.xwoba,
                "pitcher_hard_hit_pct": pitch.hard_hit_pct,
                "batter_vs_type": batter_vs_type,
                "edge_score": edge_score,
                "confidence": confidence,
            }
        )

    pitch_type_matrix.sort(key=lambda x: x["pitcher_usage_pct"], reverse=True)
    biggest_edge = max(pitch_type_matrix, key=lambda x: x["edge_score"], default=None)
    biggest_weakness = min(pitch_type_matrix, key=lambda x: x["edge_score"], default=None)

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


class PredictRequest(BaseModel):  # type: ignore[misc]
    pitcher_id: int
    batter_id: int
    season: Optional[int] = None
    pitcher_throws: str = "R"


def create_app():
    if not _FASTAPI:
        return None

    app = FastAPI(
        title="MLB Prediction API",
        version="0.5.1",
        description="Statcast-powered daily matchup predictions",
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.get("/health")
    def health():
        return {"status": "ok", "version": "0.5.1"}

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

    @app.get("/matchup/{game_pk}")
    def get_matchup_detail(game_pk: int) -> Dict[str, Any]:
        url = f"{MLB_STATS_BASE}/schedule"
        params = {
            "gamePk": game_pk,
            "hydrate": "probablePitcher,team,linescore,lineups,decisions",
        }
        try:
            resp = _req.get(url, params=params, timeout=20)
            resp.raise_for_status()
        except Exception as exc:
            raise HTTPException(status_code=502, detail=f"MLB API error: {exc}")

        dates = resp.json().get("dates", [])
        if not dates or not dates[0].get("games"):
            raise HTTPException(status_code=404, detail=f"Game {game_pk} not found")

        game = dates[0]["games"][0]
        teams = game.get("teams", {})
        home = teams.get("home", {})
        away = teams.get("away", {})

        home_team_id = home.get("team", {}).get("id")
        away_team_id = away.get("team", {}).get("id")
        home_pitcher_id = home.get("probablePitcher", {}).get("id")
        away_pitcher_id = away.get("probablePitcher", {}).get("id")
        game_date_iso = game.get("gameDate", "")
        venue_name = game.get("venue", {}).get("name")
        season = int(game_date_iso[:4]) if game_date_iso else datetime.date.today().year

        home_record = home.get("leagueRecord", {})
        away_record = away.get("leagueRecord", {})

        lineups = game.get("lineups", {})
        home_lineup_raw = lineups.get("homePlayers", [])
        away_lineup_raw = lineups.get("awayPlayers", [])

        Session = _get_session()
        with Session() as session:

            def pitcher_detail(pid):
                if not pid:
                    return {"aggregate": None, "arsenal": [], "game_log": []}
                agg, data_source = get_pitcher_aggregate_with_fallback(session, pid, season)
                arsenal, arsenal_season = get_pitch_arsenal_with_fallback(session, pid, season)
                game_log = get_pitcher_game_log(session, pid, 5)
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
                    "arsenal": [
                        {
                            "pitch_type": r.pitch_type,
                            "pitch_name": r.pitch_name,
                            "usage_pct": r.usage_pct,
                            "whiff_pct": r.whiff_pct,
                            "strikeout_pct": r.strikeout_pct,
                            "rv_per_100": r.rv_per_100,
                            "xwoba": r.xwoba,
                            "hard_hit_pct": r.hard_hit_pct,
                        }
                        for r in arsenal
                    ],
                    "arsenal_season": arsenal_season,
                    "game_log": game_log,
                }

            def team_splits(tid):
                vsL = get_team_split(session, tid, season, "vsL")
                vsR = get_team_split(session, tid, season, "vsR")

                def sd(s):
                    if not s:
                        return None
                    return {
                        "pa": s.pa, "batting_avg": s.batting_avg,
                        "on_base_pct": s.on_base_pct, "slugging_pct": s.slugging_pct,
                        "k_pct": s.k_pct, "bb_pct": s.bb_pct, "home_runs": s.home_runs,
                    }
                return {"vsL": sd(vsL), "vsR": sd(vsR)}

            home_win_prob, away_win_prob = None, None
            if home_pitcher_id and away_pitcher_id and home_team_id and away_team_id:
                home_win_prob, away_win_prob = compute_win_probability(
                    session,
                    home_pitcher_id=home_pitcher_id,
                    away_pitcher_id=away_pitcher_id,
                    home_team_id=home_team_id,
                    away_team_id=away_team_id,
                    season=season,
                )

            return {
                "game_pk": game_pk,
                "game_date": game_date_iso,
                "venue": venue_name,
                "status": game.get("status", {}).get("detailedState"),
                "park_factor": get_park_factor(venue_name),
                "home_win_prob": home_win_prob,
                "away_win_prob": away_win_prob,
                "home_team": {
                    "id": home_team_id,
                    "name": home.get("team", {}).get("name"),
                    "record": f"{home_record.get('wins',0)}-{home_record.get('losses',0)}" if home_record else None,
                    "pitcher_id": home_pitcher_id,
                    "pitcher_name": home.get("probablePitcher", {}).get("fullName"),
                    **pitcher_detail(home_pitcher_id),
                    "splits": team_splits(home_team_id),
                    "lineup": [
                        {"id": p.get("id"), "name": p.get("fullName"), "position": p.get("primaryPosition", {}).get("abbreviation")}
                        for p in home_lineup_raw
                    ],
                },
                "away_team": {
                    "id": away_team_id,
                    "name": away.get("team", {}).get("name"),
                    "record": f"{away_record.get('wins',0)}-{away_record.get('losses',0)}" if away_record else None,
                    "pitcher_id": away_pitcher_id,
                    "pitcher_name": away.get("probablePitcher", {}).get("fullName"),
                    **pitcher_detail(away_pitcher_id),
                    "splits": team_splits(away_team_id),
                    "lineup": [
                        {"id": p.get("id"), "name": p.get("fullName"), "position": p.get("primaryPosition", {}).get("abbreviation")}
                        for p in away_lineup_raw
                    ],
                },
            }

    @app.get("/matchup/{game_pk}/competitive")
    def get_competitive_analysis(game_pk: int) -> Dict[str, Any]:
        url = f"{MLB_STATS_BASE}/schedule"
        params = {
            "gamePk": game_pk,
            "hydrate": "probablePitcher,team,lineups",
        }
        try:
            resp = _req.get(url, params=params, timeout=20)
            resp.raise_for_status()
        except Exception as exc:
            raise HTTPException(status_code=502, detail=f"MLB API error: {exc}")

        dates = resp.json().get("dates", [])
        if not dates or not dates[0].get("games"):
            raise HTTPException(status_code=404, detail=f"Game {game_pk} not found")

        game = dates[0]["games"][0]
        teams = game.get("teams", {})
        home = teams.get("home", {})
        away = teams.get("away", {})
        game_date_iso = game.get("gameDate", "")
        season = int(game_date_iso[:4]) if game_date_iso else datetime.date.today().year

        home_team_name = home.get("team", {}).get("name")
        away_team_name = away.get("team", {}).get("name")
        home_pitcher_id = home.get("probablePitcher", {}).get("id")
        away_pitcher_id = away.get("probablePitcher", {}).get("id")

        lineups = game.get("lineups", {})
        home_lineup_raw = lineups.get("homePlayers", []) or []
        away_lineup_raw = lineups.get("awayPlayers", []) or []

        Session = _get_session()
        with Session() as session:
            away_lineup_matchups = [
                _build_competitive_matchup(
                    session=session,
                    batter_id=p.get("id"),
                    batter_name=p.get("fullName") or f"Batter #{p.get('id')}",
                    batting_order=i + 1,
                    opposing_pitcher_id=home_pitcher_id,
                    season=season,
                )
                for i, p in enumerate(away_lineup_raw)
                if p.get("id") and home_pitcher_id
            ]
            home_lineup_matchups = [
                _build_competitive_matchup(
                    session=session,
                    batter_id=p.get("id"),
                    batter_name=p.get("fullName") or f"Batter #{p.get('id')}",
                    batting_order=i + 1,
                    opposing_pitcher_id=away_pitcher_id,
                    season=season,
                )
                for i, p in enumerate(home_lineup_raw)
                if p.get("id") and away_pitcher_id
            ]

        return {
            "game_pk": game_pk,
            "game_date": game_date_iso,
            "away_team": away_team_name,
            "home_team": home_team_name,
            "away_pitcher_id": away_pitcher_id,
            "home_pitcher_id": home_pitcher_id,
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
            multi = get_pitcher_multi_season(session, player_id, [season, season - 1, season - 2, season - 3])
            game_log = get_pitcher_game_log(session, player_id, 10)
            if not agg and not arsenal:
                raise HTTPException(status_code=404, detail=f"No data for pitcher {player_id}")
            return {
                "player_id": player_id,
                "data_source": data_source,
                "aggregate": {
                    c.name: getattr(agg, c.name)
                    for c in agg.__table__.columns
                } if agg else None,
                "arsenal": [
                    {
                        "pitch_type": r.pitch_type,
                        "pitch_name": r.pitch_name,
                        "usage_pct": r.usage_pct,
                        "whiff_pct": r.whiff_pct,
                        "strikeout_pct": r.strikeout_pct,
                        "rv_per_100": r.rv_per_100,
                        "xwoba": r.xwoba,
                        "hard_hit_pct": r.hard_hit_pct,
                    }
                    for r in arsenal
                ],
                "arsenal_season": arsenal_season,
                "multi_season": multi,
                "game_log": game_log,
            }

    @app.get("/pitcher/{player_id}/rolling")
    def pitcher_rolling(
        player_id: int,
        windows: str = Query("15,30,60,90,120,150"),
    ) -> Dict[str, Any]:
        sizes = [int(w) for w in windows.split(",") if w.strip().isdigit()]
        Session = _get_session()
        with Session() as session:
            result = []
            for n in sizes:
                stats = get_pitcher_rolling_by_games(session, player_id, n)
                result.append({
                    "window": f"L{n}G",
                    "n_requested": n,
                    "stats": stats,
                })
            return {"player_id": player_id, "windows": result}

    @app.get("/pitcher/{player_id}/game-log")
    def pitcher_game_log(player_id: int, n: int = 10) -> Dict[str, Any]:
        Session = _get_session()
        with Session() as session:
            return {"player_id": player_id, "game_log": get_pitcher_game_log(session, player_id, n)}

    @app.get("/batter/{player_id}")
    def get_batter(player_id: int) -> Dict[str, Any]:
        season = datetime.date.today().year
        Session = _get_session()
        with Session() as session:
            agg, data_source = get_batter_aggregate_with_fallback(session, player_id, season)
            split_L = get_player_split(session, player_id, season, "vsL")
            split_R = get_player_split(session, player_id, season, "vsR")
            multi = get_batter_multi_season(session, player_id, [season, season - 1, season - 2, season - 3])
            split_seasons = get_player_splits_multi_season(session, player_id, [season, season - 1, season - 2, season - 3])
            if not agg and not split_L and not split_R:
                raise HTTPException(status_code=404, detail=f"No data for batter {player_id}")

            def _sd(s):
                if not s:
                    return None
                return {
                    "pa": s.pa, "batting_avg": s.batting_avg,
                    "on_base_pct": s.on_base_pct, "slugging_pct": s.slugging_pct,
                    "iso": s.iso, "k_pct": s.k_pct, "bb_pct": s.bb_pct,
                    "home_runs": s.home_runs,
                }

            return {
                "player_id": player_id,
                "data_source": data_source,
                "aggregate": {
                    c.name: getattr(agg, c.name)
                    for c in agg.__table__.columns
                } if agg else None,
                "splits": {"vsL": _sd(split_L), "vsR": _sd(split_R)},
                "multi_season": multi,
                "split_seasons": split_seasons,
            }

    @app.get("/batter/{player_id}/rolling")
    def batter_rolling(
        player_id: int,
        windows: str = Query("10,25,50,100,200,400,1000"),
        type: str = Query("abs"),
    ) -> Dict[str, Any]:
        sizes = [int(w) for w in windows.split(",") if w.strip().isdigit()]
        Session = _get_session()
        with Session() as session:
            result = []
            for n in sizes:
                if type == "games":
                    stats = get_batter_rolling_by_games(session, player_id, n)
                    label = f"L{n}G"
                else:
                    stats = get_batter_rolling_by_abs(session, player_id, n)
                    label = f"L{n}"
                result.append({"window": label, "n_requested": n, "stats": stats})
            return {"player_id": player_id, "type": type, "windows": result}

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
        Session = _get_session()
        with Session() as session:
            seasons = [season, season - 1, season - 2, season - 3]
            return {
                "player_id": player_id,
                "seasons": get_player_splits_multi_season(session, player_id, seasons),
            }

    @app.get("/players/search")
    def search_players(name: str) -> List[Dict[str, Any]]:
        url = f"{MLB_STATS_BASE}/people/search"
        try:
            resp = _req.get(url, params={"sportId": 1, "names": name}, timeout=20)
            resp.raise_for_status()
        except Exception as exc:
            raise HTTPException(status_code=502, detail=f"MLB API error: {exc}")
        people = resp.json().get("people", [])
        results = []
        for p in people:
            pos = (p.get("primaryPosition") or {}).get("type") or ""
            pos_type = "Pitcher" if pos.lower() == "pitcher" else "Batter"
            results.append({
                "id": p.get("id"),
                "name": p.get("fullName"),
                "team": (p.get("currentTeam") or {}).get("name"),
                "position_type": pos_type,
            })
        return results

    @app.get("/players/all")
    def get_all_players(season: Optional[int] = None) -> List[Dict[str, Any]]:
        if not season:
            season = datetime.date.today().year
        url = f"{MLB_STATS_BASE}/sports/1/players"
        try:
            resp = _req.get(url, params={"season": season}, timeout=30)
            resp.raise_for_status()
        except Exception as exc:
            raise HTTPException(status_code=502, detail=f"MLB API error: {exc}")
        people = resp.json().get("people", [])
        out = []
        for p in people:
            pos = (p.get("primaryPosition") or {}).get("type") or ""
            out.append({
                "id": p.get("id"),
                "name": p.get("fullName"),
                "position_type": "Pitcher" if pos.lower() == "pitcher" else "Batter",
                "position": (p.get("primaryPosition") or {}).get("abbreviation"),
                "team": (p.get("currentTeam") or {}).get("name"),
                "active": p.get("active"),
            })
        return out

    @app.get("/team/{team_id}/roster")
    def get_team_roster(team_id: int, season: Optional[int] = None) -> Dict[str, Any]:
        if not season:
            season = datetime.date.today().year
        url = f"{MLB_STATS_BASE}/teams/{team_id}/roster"
        try:
            resp = _req.get(url, params={"rosterType": "active", "season": season}, timeout=20)
            resp.raise_for_status()
        except Exception as exc:
            raise HTTPException(status_code=502, detail=f"MLB API error: {exc}")
        roster = resp.json().get("roster", [])
        return {
            "team_id": team_id,
            "season": season,
            "roster": [
                {
                    "id": r.get("person", {}).get("id"),
                    "name": r.get("person", {}).get("fullName"),
                    "position": (r.get("position") or {}).get("abbreviation"),
                    "status": (r.get("status") or {}).get("description"),
                }
                for r in roster
            ],
        }

    @app.get("/standings")
    def get_standings(season: Optional[int] = None) -> List[Dict[str, Any]]:
        if not season:
            season = datetime.date.today().year
        url = f"{MLB_STATS_BASE}/standings"
        params = {
            "leagueId": "103,104",
            "season": season,
            "standingsTypes": "regularSeason",
            "hydrate": "team,division,league,record",
        }
        try:
            resp = _req.get(url, params=params, timeout=20)
            resp.raise_for_status()
        except Exception as exc:
            raise HTTPException(status_code=502, detail=f"MLB API error: {exc}")
        return resp.json().get("records", [])

    @app.get("/lineup/{team_id}")
    def get_team_lineup(team_id: int, date: Optional[str] = None) -> Dict[str, Any]:
        if not date:
            date = datetime.date.today().isoformat()
        url = f"{MLB_STATS_BASE}/schedule"
        params = {
            "sportId": 1,
            "date": date,
            "teamId": team_id,
            "hydrate": "lineups,probablePitcher,team",
        }
        try:
            resp = _req.get(url, params=params, timeout=20)
            resp.raise_for_status()
        except Exception as exc:
            raise HTTPException(status_code=502, detail=f"MLB API error: {exc}")

        dates = resp.json().get("dates", [])
        if not dates or not dates[0].get("games"):
            return {"team_id": team_id, "date": date, "lineup": [], "probable_pitcher": None}

        game = dates[0]["games"][0]
        teams = game.get("teams", {})
        side = "home" if teams.get("home", {}).get("team", {}).get("id") == team_id else "away"
        lineup_raw = game.get("lineups", {}).get(f"{side}Players", [])
        pitcher = teams.get(side, {}).get("probablePitcher", {})

        return {
            "team_id": team_id,
            "date": date,
            "game_pk": game.get("gamePk"),
            "probable_pitcher": {
                "id": pitcher.get("id"),
                "name": pitcher.get("fullName"),
            } if pitcher else None,
            "lineup": [
                {"batting_order": i + 1, "id": p.get("id"), "name": p.get("fullName")}
                for i, p in enumerate(lineup_raw)
            ],
        }

    @app.get("/team/{team_id}")
    def get_team(team_id: int, season: Optional[int] = None) -> Dict[str, Any]:
        if not season:
            season = datetime.date.today().year
        Session = _get_session()
        with Session() as session:
            vsL = get_team_split(session, team_id, season, "vsL")
            vsR = get_team_split(session, team_id, season, "vsR")

            def _sd(sp):
                if not sp:
                    return None
                return {
                    c.name: getattr(sp, c.name)
                    for c in sp.__table__.columns
                }

        standings_url = f"{MLB_STATS_BASE}/standings"
        standings_params = {
            "leagueId": "103,104",
            "season": season,
            "standingsTypes": "regularSeason",
            "hydrate": "team,division,record",
        }
        team_standing = None
        try:
            s_resp = _req.get(standings_url, params=standings_params, timeout=15)
            s_resp.raise_for_status()
            for div_record in s_resp.json().get("records", []):
                for tr in div_record.get("teamRecords", []):
                    if tr.get("team", {}).get("id") == team_id:
                        team_standing = {
                            "team_name": tr["team"].get("name"),
                            "wins": tr.get("wins"),
                            "losses": tr.get("losses"),
                            "pct": tr.get("winningPercentage"),
                            "games_back": tr.get("gamesBack"),
                            "division": div_record.get("division", {}).get("nameShort"),
                            "streak": tr.get("streak", {}).get("streakCode"),
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
            "splits": {"vsL": _sd(vsL), "vsR": _sd(vsR)},
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
        return {"pitcher_id": req.pitcher_id, "batter_id": req.batter_id, **result}

    return app


app = create_app()
