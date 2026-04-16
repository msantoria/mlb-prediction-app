"""
FastAPI application for the MLB prediction engine.

Endpoints:
    GET  /matchups?date=YYYY-MM-DD            Daily matchups with win probabilities
    GET  /pitcher/{player_id}                 Pitcher aggregate + pitch arsenal
    GET  /pitcher/{player_id}/rolling         Game-based rolling metrics (L15G–L150G)
    GET  /batter/{player_id}                  Batter aggregate + platoon splits
    GET  /batter/{player_id}/rolling          AB-based rolling metrics (L10–L1000)
    GET  /batter/{player_id}/at-bats          Paginated at-bat history
    POST /predict                             Score a specific pitcher vs batter

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

from .database import get_engine, create_tables, get_session, AtBatOutcome
from .matchup_generator import generate_matchups_for_date
from .db_utils import (
    get_pitcher_aggregate,
    get_batter_aggregate,
    get_pitch_arsenal,
    get_player_split,
    get_pitcher_rolling_by_games,
    get_batter_rolling_by_abs,
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

    @app.get("/pitcher/{player_id}/rolling")
    def get_pitcher_rolling(
        player_id: int, windows: str = "15,30,60,90,120,150"
    ) -> Dict[str, Any]:
        """Return game-based rolling metrics for a pitcher.

        ``windows`` is a comma-separated list of game counts.  Each entry
        produces a key ``L{n}G`` in the response (e.g. ``L15G``, ``L30G``).
        Metrics for each window are computed on-the-fly from
        ``StatcastEvent`` data.
        """
        try:
            game_counts = [int(w.strip()) for w in windows.split(",") if w.strip()]
        except ValueError:
            raise HTTPException(
                status_code=422,
                detail="windows must be a comma-separated list of integers",
            )
        if not game_counts:
            raise HTTPException(status_code=422, detail="windows must not be empty")

        Session = _get_session()
        with Session() as session:
            result: Dict[str, Any] = {}
            for n in game_counts:
                metrics = get_pitcher_rolling_by_games(session, player_id, n)
                result[f"L{n}G"] = metrics if metrics else None
            if all(v is None for v in result.values()):
                raise HTTPException(
                    status_code=404,
                    detail=f"No Statcast data found for pitcher {player_id}",
                )
        return {"player_id": player_id, "rolling": result}

    @app.get("/batter/{player_id}/rolling")
    def get_batter_rolling(
        player_id: int, windows: str = "10,25,50,100,200,400,1000"
    ) -> Dict[str, Any]:
        """Return AB-based rolling metrics for a batter.

        ``windows`` is a comma-separated list of at-bat counts.  Each entry
        produces a key ``L{n}`` in the response (e.g. ``L10``, ``L25``).
        Metrics are computed on-the-fly from ``StatcastEvent`` rows where
        ``events IS NOT NULL``.
        """
        try:
            ab_counts = [int(w.strip()) for w in windows.split(",") if w.strip()]
        except ValueError:
            raise HTTPException(
                status_code=422,
                detail="windows must be a comma-separated list of integers",
            )
        if not ab_counts:
            raise HTTPException(status_code=422, detail="windows must not be empty")

        Session = _get_session()
        with Session() as session:
            result: Dict[str, Any] = {}
            for n in ab_counts:
                metrics = get_batter_rolling_by_abs(session, player_id, n)
                result[f"L{n}"] = metrics if metrics else None
            if all(v is None for v in result.values()):
                raise HTTPException(
                    status_code=404,
                    detail=f"No Statcast data found for batter {player_id}",
                )
        return {"player_id": player_id, "rolling": result}

    @app.get("/batter/{player_id}/at-bats")
    def get_batter_at_bats(
        player_id: int, n: int = 50, offset: int = 0
    ) -> Dict[str, Any]:
        """Return a paginated list of recent at-bats for a batter.

        Results are ordered chronologically (oldest first within the page).
        Use ``offset`` to page through the history; ``n`` controls page size.

        Each item contains: ``ab_number``, ``date``, ``pitcher_id``,
        ``result``, ``exit_velocity``, ``launch_angle``, ``last_pitch_type``.
        """
        if n < 1 or n > 500:
            raise HTTPException(
                status_code=422, detail="n must be between 1 and 500"
            )
        if offset < 0:
            raise HTTPException(
                status_code=422, detail="offset must be >= 0"
            )

        Session = _get_session()
        with Session() as session:
            # Fetch the most-recent (n + offset) rows then slice to the page
            rows = (
                session.query(AtBatOutcome)
                .filter(AtBatOutcome.batter_id == player_id)
                .order_by(AtBatOutcome.ab_number.desc())
                .limit(n + offset)
                .all()
            )
            if not rows:
                raise HTTPException(
                    status_code=404,
                    detail=f"No at-bat data found for batter {player_id}",
                )
            # Apply offset and reverse to chronological order
            page = list(reversed(rows[offset : offset + n]))
            at_bats = [
                {
                    "ab_number": r.ab_number,
                    "date": r.game_date.isoformat() if r.game_date else None,
                    "pitcher_id": r.pitcher_id,
                    "result": r.result,
                    "exit_velocity": r.exit_velocity,
                    "launch_angle": r.launch_angle,
                    "last_pitch_type": r.last_pitch_type,
                }
                for r in page
            ]
        return {
            "player_id": player_id,
            "n": n,
            "offset": offset,
            "count": len(at_bats),
            "at_bats": at_bats,
        }

    return app

app = create_app()
