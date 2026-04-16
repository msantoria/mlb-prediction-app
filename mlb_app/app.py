"""
FastAPI application for the MLB prediction engine.

Endpoints:
    GET  /matchups?date=YYYY-MM-DD       Daily matchups with win probabilities
    GET  /pitcher/{player_id}            Multi-season stats, arsenal, game log
    GET  /batter/{player_id}             Multi-season stats, splits, Statcast
    GET  /team/{team_id}                 Rotation, bullpen, batting splits
    POST /predict                        Score a specific pitcher vs batter

Run:
    uvicorn mlb_app.app:app --reload
"""

from __future__ import annotations

import datetime
import os
from typing import Any, Dict, List, Optional

try:
    from fastapi import FastAPI, HTTPException
    from fastapi.middleware.cors import CORSMiddleware
    from pydantic import BaseModel
    _FASTAPI = True
except ImportError:
    FastAPI = None
    HTTPException = Exception
    CORSMiddleware = None
    BaseModel = object
    _FASTAPI = False

from .database import get_engine, create_tables, get_session, BatterAggregate
from .matchup_generator import generate_matchups_for_date
from .db_utils import (
    get_pitcher_aggregate,
    get_batter_aggregate,
    get_pitch_arsenal,
    get_player_split,
    get_team_split,
    get_pitcher_multi_season_stats,
    get_pitcher_game_log,
    get_team_rotation,
    get_team_bullpen,
)
from .scoring import score_individual_matchup


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
        version="0.4.0",
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
        return {"status": "ok", "version": "0.4.0"}

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

    @app.get("/pitcher/{player_id}")
    def get_pitcher(player_id: int) -> Dict[str, Any]:
        Session = _get_session()
        with Session() as session:
            season = datetime.date.today().year
            arsenal = get_pitch_arsenal(session, player_id, season)
            multi_season = get_pitcher_multi_season_stats(session, player_id)
            game_log = get_pitcher_game_log(session, player_id, limit=10)
            if not multi_season and not arsenal:
                raise HTTPException(
                    status_code=404,
                    detail=f"No data found for pitcher {player_id}",
                )

            def _season_label(row) -> int:
                """Derive a display season from the window or end_date."""
                if row.window and row.window.isdigit() and len(row.window) == 4:
                    return int(row.window)
                return row.end_date.year if row.end_date else season

            def _data_source(row) -> str:
                """Return 'season' for full-season windows, '90d' otherwise."""
                if row.window and row.window.isdigit() and len(row.window) == 4:
                    return "season"
                return row.window or "90d"

            return {
                "player_id": player_id,
                "multi_season_stats": [
                    {
                        "season": _season_label(r),
                        "k_pct": r.k_pct,
                        "bb_pct": r.bb_pct,
                        "xwoba": r.xwoba,
                        "hard_hit_pct": r.hard_hit_pct,
                        "velo": r.avg_velocity,
                        "spin": r.avg_spin_rate,
                        "data_source": _data_source(r),
                    }
                    for r in multi_season
                ],
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
                "game_log": [
                    {
                        "date": g.game_date.isoformat() if g.game_date else None,
                        "opponent": g.opponent,
                        "result": g.result,
                        "ip": g.ip,
                        "h": g.hits,
                        "r": g.runs,
                        "er": g.earned_runs,
                        "k": g.strikeouts,
                        "bb": g.walks,
                        "hr": g.home_runs,
                        "pitches": g.pitches,
                    }
                    for g in game_log
                ],
            }


    @app.get("/batter/{player_id}")
    def get_batter(player_id: int) -> Dict[str, Any]:
        Session = _get_session()
        with Session() as session:
            season = datetime.date.today().year
            split_L = get_player_split(session, player_id, season, "vsL")
            split_R = get_player_split(session, player_id, season, "vsR")
            multi_season = (
                session.query(BatterAggregate)
                .filter(BatterAggregate.batter_id == player_id)
                .order_by(BatterAggregate.end_date.desc())
                .all()
            )

            if not multi_season and not split_L and not split_R:
                raise HTTPException(
                    status_code=404,
                    detail=f"No data found for batter {player_id}",
                )

            def _split_dict(s):
                if not s:
                    return None
                return {
                    "pa": s.pa, "batting_avg": s.batting_avg,
                    "on_base_pct": s.on_base_pct, "slugging_pct": s.slugging_pct,
                    "iso": s.iso, "k_pct": s.k_pct, "bb_pct": s.bb_pct,
                    "home_runs": s.home_runs,
                }

            def _ms_label(row) -> int:
                if row.window and row.window.isdigit() and len(row.window) == 4:
                    return int(row.window)
                return row.end_date.year if row.end_date else season

            def _ms_source(row) -> str:
                if row.window and row.window.isdigit() and len(row.window) == 4:
                    return "season"
                return row.window or "90d"

            return {
                "player_id": player_id,
                "multi_season_stats": [
                    {
                        "season": _ms_label(r),
                        "k_pct": r.k_pct,
                        "bb_pct": r.bb_pct,
                        "ev": r.avg_exit_velocity,
                        "la": r.avg_launch_angle,
                        "barrel_pct": r.barrel_pct,
                        "hard_hit_pct": r.hard_hit_pct,
                        "batting_avg": r.batting_avg,
                        "data_source": _ms_source(r),
                    }
                    for r in multi_season
                ],
                "splits": {"vsL": _split_dict(split_L), "vsR": _split_dict(split_R)},
                "statcast_metrics": (
                    {
                        "exit_velocity": multi_season[0].avg_exit_velocity,
                        "launch_angle": multi_season[0].avg_launch_angle,
                        "hard_hit_pct": multi_season[0].hard_hit_pct,
                        "barrel_pct": multi_season[0].barrel_pct,
                    }
                    if multi_season else None
                ),
            }

    @app.get("/team/{team_id}")
    def get_team(team_id: int) -> Dict[str, Any]:
        Session = _get_session()
        with Session() as session:
            season = datetime.date.today().year
            split_vsL = get_team_split(session, team_id, season, "vsL")
            split_vsR = get_team_split(session, team_id, season, "vsR")
            rotation = get_team_rotation(session, team_id, season)
            bullpen = get_team_bullpen(session, team_id, season)
            if not rotation and not bullpen and not split_vsL and not split_vsR:
                raise HTTPException(
                    status_code=404,
                    detail=f"No data found for team {team_id}",
                )

            def _team_split_dict(s):
                if not s:
                    return None
                return {
                    "pa": s.pa,
                    "batting_avg": s.batting_avg,
                    "on_base_pct": s.on_base_pct,
                    "slugging_pct": s.slugging_pct,
                    "iso": s.iso,
                    "k_pct": s.k_pct,
                    "bb_pct": s.bb_pct,
                    "home_runs": s.home_runs,
                }

            def _roster_dict(r, is_starter: bool) -> Dict[str, Any]:
                entry: Dict[str, Any] = {
                    "pitcher_id": r.pitcher_id,
                    "name": r.player_name,
                    "era": r.era,
                    "whip": r.whip,
                    "k_pct": r.k_pct,
                    "bb_pct": r.bb_pct,
                    "ip": r.ip,
                }
                if is_starter:
                    entry["w"] = r.wins
                    entry["l"] = r.losses
                    entry["xfip"] = r.xfip
                    entry["next_start"] = (
                        r.next_start.isoformat() if r.next_start else None
                    )
                else:
                    entry["sv"] = r.saves
                    entry["holds"] = r.holds
                return entry

            return {
                "team_id": team_id,
                "rotation": [_roster_dict(r, is_starter=True) for r in rotation],
                "bullpen": [_roster_dict(r, is_starter=False) for r in bullpen],
                "batting_splits": {
                    "vsLHP": _team_split_dict(split_vsL),
                    "vsRHP": _team_split_dict(split_vsR),
                },
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

    return app


app = create_app()
