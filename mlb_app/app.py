"""
FastAPI application for the MLB prediction engine.

Endpoints:
    GET  /matchups?date=YYYY-MM-DD       Daily matchups with win probabilities
    GET  /matchups/{game_pk}             Matchup detail + enriched lineups
    GET  /lineup/{team_id}?date=…        Live lineup enriched with Statcast + splits
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
from .data_ingestion import fetch_live_lineup
from .etl import fetch_schedule


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

    @app.get("/lineup/{team_id}")
    def get_lineup(team_id: int, date: str) -> List[Dict[str, Any]]:
        """Return the live batting order for a team on a given date, enriched
        with each batter's 90-day Statcast aggregate and platoon splits.

        The endpoint resolves the team's game for the requested date via the
        MLB schedule, fetches the confirmed lineup from the liveData endpoint,
        then joins each batter with their ``BatterAggregate`` (90d window) and
        ``PlayerSplit`` records (vsL / vsR) from the local database.

        Path parameters
        ---------------
        team_id : int
            MLBAM team identifier.

        Query parameters
        ----------------
        date : str
            Date in ``YYYY-MM-DD`` format.

        Returns
        -------
        list of dict
            Ordered batting lineup.  Each entry contains ``batter_id``,
            ``name``, ``position``, ``batting_order``, ``aggregate``
            (90d Statcast metrics or ``null``), ``vs_lhp`` (platoon split
            vs left-handed pitching or ``null``), and ``vs_rhp`` (platoon
            split vs right-handed pitching or ``null``).
        """
        # ── 1. Find the game_pk for this team on the requested date ──────────
        try:
            games = fetch_schedule(date)
        except Exception as exc:
            raise HTTPException(status_code=502, detail=f"Schedule fetch failed: {exc}")

        game_pk: Optional[int] = None
        team_side: str = "home"
        for game in games:
            home_id = game.get("home", {}).get("team", {}).get("id")
            away_id = game.get("away", {}).get("team", {}).get("id")
            if team_id in (home_id, away_id):
                game_pk = game.get("_game_pk")
                team_side = "home" if team_id == home_id else "away"
                break

        if game_pk is None:
            raise HTTPException(
                status_code=404,
                detail=f"No game found for team {team_id} on {date}",
            )

        # ── 2. Fetch live lineup from MLB liveData ────────────────────────────
        try:
            lineup_data = fetch_live_lineup(game_pk)
        except RuntimeError as exc:
            raise HTTPException(status_code=502, detail=str(exc))

        batters = lineup_data.get(team_side, [])
        if not batters:
            raise HTTPException(
                status_code=404,
                detail=f"Lineup not yet available for team {team_id} (game {game_pk})",
            )

        # ── 3. Enrich each batter with DB stats ───────────────────────────────
        season = int(date[:4])

        def _agg_dict(agg) -> Optional[Dict[str, Any]]:
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
            }

        def _split_dict(s) -> Optional[Dict[str, Any]]:
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

        Session = _get_session()
        enriched: List[Dict[str, Any]] = []
        with Session() as session:
            for batter in batters:
                batter_id = batter["batter_id"]
                agg = get_batter_aggregate(session, batter_id, "90d")
                split_l = get_player_split(session, batter_id, season, "vsL")
                split_r = get_player_split(session, batter_id, season, "vsR")
                enriched.append(
                    {
                        "batter_id": batter_id,
                        "name": batter["name"],
                        "position": batter["position"],
                        "batting_order": batter["batting_order"],
                        "aggregate": _agg_dict(agg),
                        "vs_lhp": _split_dict(split_l),
                        "vs_rhp": _split_dict(split_r),
                    }
                )

        return enriched

    @app.get("/matchups/{game_pk}")
    def get_matchup_detail(game_pk: int) -> Dict[str, Any]:
        """Return detailed matchup data for a single game, including live lineups.

        Combines the scheduled game metadata and win-probability features
        already produced by :func:`generate_matchups_for_date` with the
        confirmed batting orders (enriched with Statcast aggregates and
        platoon splits) fetched from the MLB liveData endpoint.

        Path parameters
        ---------------
        game_pk : int
            The MLB game primary key.

        Returns
        -------
        dict
            All fields from the daily matchup response for this game, plus
            ``away_lineup`` and ``home_lineup`` lists.  Each lineup entry
            mirrors the shape returned by ``GET /lineup/{team_id}``.
        """
        import requests as _requests

        # ── 1. Resolve game date from the schedule using game_pk ─────────────
        schedule_url = (
            "https://statsapi.mlb.com/api/v1/schedule"
            f"?sportId=1&gamePk={game_pk}&hydrate=probablePitcher,team,linescore"
        )
        try:
            resp = _requests.get(schedule_url, timeout=20)
            resp.raise_for_status()
            sched_data = resp.json()
        except Exception as exc:
            raise HTTPException(status_code=502, detail=f"Schedule fetch failed: {exc}")

        dates = sched_data.get("dates", [])
        if not dates or not dates[0].get("games"):
            raise HTTPException(
                status_code=404, detail=f"Game {game_pk} not found in MLB schedule"
            )

        game_date = dates[0]["date"]  # "YYYY-MM-DD"
        season = int(game_date[:4])

        # ── 2. Build the base matchup record ─────────────────────────────────
        Session = _get_session()
        with Session() as session:
            try:
                all_matchups = generate_matchups_for_date(session, game_date)
            except Exception as exc:
                raise HTTPException(status_code=500, detail=str(exc))

        # Locate the specific game within today's matchups
        game_info = dates[0]["games"][0]
        game_teams = game_info.get("teams", {})
        home_team_id = game_teams.get("home", {}).get("team", {}).get("id")
        away_team_id = game_teams.get("away", {}).get("team", {}).get("id")

        base_matchup: Optional[Dict[str, Any]] = None
        for m in all_matchups:
            if (
                m.get("home_team_id") == home_team_id
                and m.get("away_team_id") == away_team_id
            ):
                base_matchup = m
                break

        if base_matchup is None:
            # Fall back to a minimal structure if matchup generator didn't
            # include this game (e.g., no probable pitchers yet)
            base_matchup = {
                "game_date": game_date,
                "home_team_id": home_team_id,
                "away_team_id": away_team_id,
            }

        # ── 3. Fetch and enrich lineups ───────────────────────────────────────
        def _agg_dict(agg) -> Optional[Dict[str, Any]]:
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
            }

        def _split_dict(s) -> Optional[Dict[str, Any]]:
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

        try:
            lineup_data = fetch_live_lineup(game_pk)
        except RuntimeError:
            # Lineup not yet available — return base matchup without lineups
            lineup_data = {"away": [], "home": []}

        Session2 = _get_session()
        enriched_lineups: Dict[str, List[Dict[str, Any]]] = {"away": [], "home": []}
        with Session2() as session:
            for side in ("away", "home"):
                for batter in lineup_data.get(side, []):
                    batter_id = batter["batter_id"]
                    agg = get_batter_aggregate(session, batter_id, "90d")
                    split_l = get_player_split(session, batter_id, season, "vsL")
                    split_r = get_player_split(session, batter_id, season, "vsR")
                    enriched_lineups[side].append(
                        {
                            "batter_id": batter_id,
                            "name": batter["name"],
                            "position": batter["position"],
                            "batting_order": batter["batting_order"],
                            "aggregate": _agg_dict(agg),
                            "vs_lhp": _split_dict(split_l),
                            "vs_rhp": _split_dict(split_r),
                        }
                    )

        return {
            **base_matchup,
            "away_lineup": enriched_lineups["away"],
            "home_lineup": enriched_lineups["home"],
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
