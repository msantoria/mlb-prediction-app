"""
FastAPI application for the MLB prediction engine.

Endpoints:
    GET  /health
    GET  /matchups?date=YYYY-MM-DD
    GET  /matchup/{game_pk}              Full detail: pitchers, lineup, splits, game log
    GET  /pitcher/{id}                   Aggregate + arsenal
    GET  /pitcher/{id}/rolling           L15G–L150G rolling stats
    GET  /pitcher/{id}/game-log          Recent game-by-game appearances
    GET  /batter/{id}                    Aggregate + platoon splits
    GET  /batter/{id}/rolling            L10–L1000 AB rolling stats
    GET  /batter/{id}/at-bats            Chronological at-bat session
    GET  /standings                      MLB AL/NL standings
    GET  /lineup/{team_id}               Day-of lineup from MLB Stats API
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

from .database import get_engine, create_tables, get_session
from .matchup_generator import generate_matchups_for_date
from .db_utils import (
    get_pitcher_aggregate,
    get_pitcher_aggregate_with_fallback,
    get_batter_aggregate,
    get_batter_aggregate_with_fallback,
    get_pitch_arsenal,
    get_pitch_arsenal_with_fallback,
    get_player_split,
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


def _get_session():
    db_url = os.getenv("DATABASE_URL", "sqlite:///mlb.db")
    engine = get_engine(db_url)
    create_tables(engine)
    return get_session(engine)


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
        version="0.5.0",
        description="Statcast-powered daily matchup predictions",
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # -------------------------------------------------------------------------
    # Health
    # -------------------------------------------------------------------------

    @app.get("/health")
    def health():
        return {"status": "ok", "version": "0.5.0"}

    # -------------------------------------------------------------------------
    # Matchups
    # -------------------------------------------------------------------------

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
        """Full matchup detail: probable pitchers, lineup, team splits, recent outings."""
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

    # -------------------------------------------------------------------------
    # Pitcher endpoints
    # -------------------------------------------------------------------------

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

    # -------------------------------------------------------------------------
    # Batter endpoints
    # -------------------------------------------------------------------------

    @app.get("/batter/{player_id}")
    def get_batter(player_id: int) -> Dict[str, Any]:
        season = datetime.date.today().year
        Session = _get_session()
        with Session() as session:
            agg, data_source = get_batter_aggregate_with_fallback(session, player_id, season)
            split_L = get_player_split(session, player_id, season, "vsL")
            split_R = get_player_split(session, player_id, season, "vsR")
            multi = get_batter_multi_season(session, player_id, [season, season - 1, season - 2, season - 3])
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

    # -------------------------------------------------------------------------
    # Standings
    # -------------------------------------------------------------------------

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

    # -------------------------------------------------------------------------
    # Lineup
    # -------------------------------------------------------------------------

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

    # -------------------------------------------------------------------------
    # Team
    # -------------------------------------------------------------------------

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

    # -------------------------------------------------------------------------
    # Predict
    # -------------------------------------------------------------------------

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
