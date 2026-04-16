"""
FastAPI application for the MLB prediction engine.

Endpoints:
    GET  /health                         Service health check
    GET  /standings?season=YYYY          AL/NL division standings
    GET  /matchups?date=YYYY-MM-DD       Daily matchups with win probabilities
    GET  /pitcher/{player_id}            Pitcher aggregate + pitch arsenal
    GET  /batter/{player_id}             Batter aggregate + platoon splits
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

from .database import get_engine, create_tables, get_session
from .matchup_generator import generate_matchups_for_date
from .db_utils import (
    get_pitcher_aggregate,
    get_batter_aggregate,
    get_pitch_arsenal,
    get_player_split,
)
from .scoring import score_individual_matchup
from .data_ingestion import fetch_standings


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

    @app.get("/standings")
    def get_standings(season: Optional[int] = None) -> Dict[str, Any]:
        """Return AL/NL division standings for the given season.

        Query Parameters
        ----------------
        season : int, optional
            Season year (e.g. 2025).  Defaults to the current calendar year.

        Returns
        -------
        dict
            Nested dict keyed by league (``"AL"`` / ``"NL"``) and division
            (``"East"`` / ``"Central"`` / ``"West"``).  Each division contains
            a list of team records with ``team_id``, ``name``, ``w``, ``l``,
            ``pct``, ``gb``, ``l10``, and ``streak``.
        """
        resolved_season = season or datetime.date.today().year
        try:
            return fetch_standings(resolved_season)
        except RuntimeError as exc:
            raise HTTPException(status_code=502, detail=str(exc))

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
            agg = get_pitcher_aggregate(session, player_id, "90d")
            season = datetime.date.today().year
            arsenal = get_pitch_arsenal(session, player_id, season)
            if not agg and not arsenal:
                raise HTTPException(
                    status_code=404,
                    detail=f"No data found for pitcher {player_id}",
                )
            return {
                "player_id": player_id,
                "aggregate": {
                    c.name: getattr(agg, c.name)
                    for c in agg.__table__.columns
                    if c.name != "_sa_instance_state"
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
            }

    @app.get("/batter/{player_id}")
    def get_batter(player_id: int) -> Dict[str, Any]:
        Session = _get_session()
        with Session() as session:
            agg = get_batter_aggregate(session, player_id, "90d")
            season = datetime.date.today().year
            split_L = get_player_split(session, player_id, season, "vsL")
            split_R = get_player_split(session, player_id, season, "vsR")
            if not agg and not split_L and not split_R:
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

            return {
                "player_id": player_id,
                "aggregate": {
                    c.name: getattr(agg, c.name)
                    for c in agg.__table__.columns
                    if c.name != "_sa_instance_state"
                } if agg else None,
                "splits": {"vsL": _split_dict(split_L), "vsR": _split_dict(split_R)},
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
