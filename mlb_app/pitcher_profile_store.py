from __future__ import annotations

import datetime as dt
from typing import Any, Dict, List, Optional, Tuple

import requests as _req
from sqlalchemy import delete
from sqlalchemy.orm import Session

from .database import (
    PitchArsenal,
    PitchArsenal as LegacyPitchArsenal,
    PitcherAggregate,
    PitcherProfileArsenal,
    PitcherProfileOverview,
    PitcherProfileRecentGame,
    StatcastEvent,
)
from .db_utils import get_pitcher_game_log

MLB_STATS_BASE = "https://statsapi.mlb.com/api/v1"
FIP_CONSTANTS_BY_SEASON = {
    2023: 3.214,
    2024: 3.214,
    2025: 3.214,
    2026: 3.214,
}


def _safe_float(value: Any) -> Optional[float]:
    try:
        if value is None:
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def _clean_event_name(value: Any) -> Optional[str]:
    if value is None:
        return None
    text = str(value).strip().lower()
    if text in {"", "none", "null", "nan", "n/a", "na"}:
        return None
    return text


def _normalize_rate(value: Optional[float]) -> Optional[float]:
    if value is None:
        return None
    if value > 1:
        return round(value / 100.0, 4)
    return round(value, 4)


def _request_json(url: str, params: Optional[Dict[str, Any]] = None, timeout: int = 20) -> Dict[str, Any]:
    resp = _req.get(url, params=params, timeout=timeout)
    resp.raise_for_status()
    return resp.json()


def get_pitcher_profile_overview(session: Session, pitcher_id: int, season: int) -> Optional[PitcherProfileOverview]:
    return (
        session.query(PitcherProfileOverview)
        .filter(PitcherProfileOverview.player_id == pitcher_id, PitcherProfileOverview.season == season)
        .order_by(PitcherProfileOverview.updated_at.desc())
        .first()
    )


def get_pitcher_profile_arsenal(session: Session, pitcher_id: int, season: int) -> List[PitcherProfileArsenal]:
    return (
        session.query(PitcherProfileArsenal)
        .filter(PitcherProfileArsenal.player_id == pitcher_id, PitcherProfileArsenal.season == season)
        .order_by(PitcherProfileArsenal.usage_pct.desc().nullslast())
        .all()
    )


def get_pitcher_profile_recent_games(session: Session, pitcher_id: int, limit: int = 10) -> List[PitcherProfileRecentGame]:
    return (
        session.query(PitcherProfileRecentGame)
        .filter(PitcherProfileRecentGame.player_id == pitcher_id)
        .order_by(PitcherProfileRecentGame.game_date.desc(), PitcherProfileRecentGame.game_pk.desc().nullslast())
        .limit(limit)
        .all()
    )


def serialize_pitcher_profile_overview(row: Optional[PitcherProfileOverview]) -> Optional[Dict[str, Any]]:
    if not row:
        return None
    return {
        column.name: getattr(row, column.name)
        for column in row.__table__.columns
    }


def serialize_pitcher_profile_arsenal(rows: List[PitcherProfileArsenal]) -> List[Dict[str, Any]]:
    return [
        {column.name: getattr(row, column.name) for column in row.__table__.columns}
        for row in rows
    ]


def serialize_pitcher_profile_recent_games(rows: List[PitcherProfileRecentGame]) -> List[Dict[str, Any]]:
    return [
        {column.name: getattr(row, column.name) for column in row.__table__.columns}
        for row in rows
    ]


def _season_date_range(season: int) -> Tuple[dt.date, dt.date]:
    return dt.date(season, 1, 1), dt.date(season, 12, 31)


def _pitcher_events_for_season(session: Session, pitcher_id: int, season: int) -> List[StatcastEvent]:
    start_date, end_date = _season_date_range(season)
    return (
        session.query(StatcastEvent)
        .filter(
            StatcastEvent.pitcher_id == pitcher_id,
            StatcastEvent.game_date >= start_date,
            StatcastEvent.game_date <= end_date,
        )
        .all()
    )


def _innings_to_float(value: Any) -> Optional[float]:
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    try:
        if "." in text:
            whole, frac = text.split(".", 1)
            outs = int(frac[:1] or 0)
            if outs in {0, 1, 2}:
                return round(float(int(whole)) + outs / 3.0, 3)
        return float(text)
    except (TypeError, ValueError):
        return None


def _fetch_mlb_pitching_season_stats(pitcher_id: int, season: int) -> Dict[str, Any]:
    try:
        data = _request_json(
            f"{MLB_STATS_BASE}/people/{int(pitcher_id)}",
            params={"hydrate": f"currentTeam,stats(group=[pitching],type=[season],season={int(season)})"},
            timeout=12,
        )
        person = (data.get("people") or [{}])[0]
        team = person.get("currentTeam") or {}
        splits = (((person.get("stats") or [{}])[0]).get("splits") or [])
        stat = (splits[0] or {}).get("stat") if splits else {}
        return {
            "player_name": person.get("fullName"),
            "team_id": team.get("id"),
            "team_name": team.get("name"),
            "stat": stat or {},
        }
    except Exception:
        return {"player_name": None, "team_id": None, "team_name": None, "stat": {}}


def _derive_event_metrics(events: List[StatcastEvent]) -> Dict[str, Any]:
    cleaned_events = [_clean_event_name(getattr(event, "events", None)) for event in events]
    total = len(events)
    batted = [event for event in events if event.launch_speed is not None]
    batted_count = len(batted)
    hard_hit_count = sum(1 for event in batted if (event.launch_speed or 0) >= 95)
    barrel_count = sum(
        1
        for event in batted
        if event.launch_speed is not None and event.launch_angle is not None and event.launch_speed >= 98 and 8 <= event.launch_angle <= 50
    )
    xwoba_vals = [event.estimated_woba_using_speedangle for event in events if event.estimated_woba_using_speedangle is not None]
    xba_vals = [event.estimated_ba_using_speedangle for event in events if event.estimated_ba_using_speedangle is not None]
    ev_vals = [event.launch_speed for event in batted if event.launch_speed is not None]
    la_vals = [event.launch_angle for event in batted if event.launch_angle is not None]
    velo_vals = [event.release_speed for event in events if event.release_speed is not None]
    spin_vals = [event.release_spin_rate for event in events if event.release_spin_rate is not None]
    horiz_vals = [event.pfx_x for event in events if event.pfx_x is not None]
    vert_vals = [event.pfx_z for event in events if event.pfx_z is not None]

    ground_ball_count = sum(1 for event in batted if event.launch_angle is not None and event.launch_angle < 10)
    fly_ball_count = sum(1 for event in batted if event.launch_angle is not None and event.launch_angle >= 25)
    home_run_count = sum(1 for event_name in cleaned_events if event_name == "home_run")

    return {
        "event_rows": total,
        "batted_ball_count": batted_count,
        "hard_hit_pct": round(hard_hit_count / batted_count, 4) if batted_count else None,
        "barrel_pct": round(barrel_count / batted_count, 4) if batted_count else None,
        "xwoba_allowed": round(sum(xwoba_vals) / len(xwoba_vals), 3) if xwoba_vals else None,
        "xba_allowed": round(sum(xba_vals) / len(xba_vals), 3) if xba_vals else None,
        "avg_exit_velocity_allowed": round(sum(ev_vals) / len(ev_vals), 1) if ev_vals else None,
        "avg_launch_angle_allowed": round(sum(la_vals) / len(la_vals), 1) if la_vals else None,
        "avg_velocity": round(sum(velo_vals) / len(velo_vals), 1) if velo_vals else None,
        "avg_spin_rate": round(sum(spin_vals) / len(spin_vals), 0) if spin_vals else None,
        "avg_horiz_break": round(sum(horiz_vals) / len(horiz_vals), 3) if horiz_vals else None,
        "avg_vert_break": round(sum(vert_vals) / len(vert_vals), 3) if vert_vals else None,
        "gb_pct": round(ground_ball_count / batted_count, 4) if batted_count else None,
        "fb_pct": round(fly_ball_count / batted_count, 4) if batted_count else None,
        "hr_fb_pct": round(home_run_count / fly_ball_count, 4) if fly_ball_count else None,
        "whiff_rate": None,
        "csw_rate": None,
    }


def _derive_standard_metrics(stat: Dict[str, Any]) -> Dict[str, Any]:
    hits = _safe_float(stat.get("hits"))
    hr = _safe_float(stat.get("homeRuns") or stat.get("homeRunsAllowed"))
    bb = _safe_float(stat.get("baseOnBalls") or stat.get("walks"))
    hbp = _safe_float(stat.get("hitBatsmen") or stat.get("hitByPitch")) or 0.0
    strikeouts = _safe_float(stat.get("strikeOuts") or stat.get("strikeouts"))
    at_bats = _safe_float(stat.get("atBats") or stat.get("ab"))
    runs = _safe_float(stat.get("runs") or stat.get("r"))
    sacrifice_flies = _safe_float(stat.get("sacFlies") or stat.get("sf")) or 0.0
    innings = _innings_to_float(stat.get("inningsPitched") or stat.get("ip"))
    batters_faced = _safe_float(stat.get("battersFaced") or stat.get("totalBattersFaced"))
    era = _safe_float(stat.get("era"))
    whip = _safe_float(stat.get("whip"))

    k_pct = round(strikeouts / batters_faced, 4) if batters_faced and strikeouts is not None else None
    bb_pct = round(bb / batters_faced, 4) if batters_faced and bb is not None else None
    k_minus_bb_pct = round(k_pct - bb_pct, 4) if k_pct is not None and bb_pct is not None else None
    hr_per_9 = round((hr * 9.0) / innings, 4) if innings and hr is not None else None
    babip = None
    if hits is not None and hr is not None and at_bats is not None and strikeouts is not None:
        denominator = at_bats - strikeouts - hr + sacrifice_flies
        if denominator > 0:
            babip = round((hits - hr) / denominator, 4)
    lob_pct = None
    if hits is not None and bb is not None and runs is not None and hr is not None:
        denominator = hits + bb + hbp - (1.4 * hr)
        if denominator > 0:
            lob_pct = round((hits + bb + hbp - runs) / denominator, 4)
    fip = None
    if innings and innings > 0 and hr is not None and bb is not None and strikeouts is not None:
        constant = FIP_CONSTANTS_BY_SEASON.get(dt.date.today().year) or FIP_CONSTANTS_BY_SEASON.get(2026) or 3.214
        fip = round(((13 * hr) + (3 * (bb + hbp)) - (2 * strikeouts)) / innings + constant, 3)
    # SIERA is intentionally conservative but always populated once key rates exist.
    siera = None
    if k_pct is not None and bb_pct is not None:
        gb_for_formula = 0.44
        siera = round(6.145 - (16.986 * k_pct) + (11.434 * bb_pct) - (1.858 * gb_for_formula) + (7.653 * (k_pct ** 2)) + (6.664 * (gb_for_formula ** 2)) + (10.130 * k_pct * gb_for_formula) - (5.195 * bb_pct * gb_for_formula), 3)

    return {
        "era": era,
        "whip": whip,
        "strikeouts": int(strikeouts) if strikeouts is not None else None,
        "walks": int(bb) if bb is not None else None,
        "home_runs_allowed": int(hr) if hr is not None else None,
        "hits_allowed": int(hits) if hits is not None else None,
        "runs_allowed": int(runs) if runs is not None else None,
        "innings_pitched": innings,
        "batters_faced": int(batters_faced) if batters_faced is not None else None,
        "k_pct": k_pct,
        "bb_pct": bb_pct,
        "k_minus_bb_pct": k_minus_bb_pct,
        "hr_per_9": hr_per_9,
        "babip": babip,
        "lob_pct": lob_pct,
        "fip": fip,
        "siera": siera,
    }


def build_pitcher_profile_rows(session: Session, pitcher_id: int, season: int) -> Tuple[Optional[PitcherProfileOverview], List[PitcherProfileArsenal], List[PitcherProfileRecentGame]]:
    mlb = _fetch_mlb_pitching_season_stats(pitcher_id, season)
    legacy_agg = (
        session.query(PitcherAggregate)
        .filter(PitcherAggregate.pitcher_id == pitcher_id, PitcherAggregate.window.in_(["90d", str(season)]))
        .order_by(PitcherAggregate.end_date.desc())
        .first()
    )
    events = _pitcher_events_for_season(session, pitcher_id, season)
    event_metrics = _derive_event_metrics(events)
    standard = _derive_standard_metrics(mlb.get("stat") or {})

    gb_pct = event_metrics.get("gb_pct")
    fb_pct = event_metrics.get("fb_pct")
    hr_fb_pct = event_metrics.get("hr_fb_pct")
    overview = PitcherProfileOverview(
        player_id=pitcher_id,
        season=season,
        player_name=mlb.get("player_name"),
        team_id=mlb.get("team_id"),
        team_name=mlb.get("team_name"),
        era=standard.get("era"),
        whip=standard.get("whip"),
        innings_pitched=standard.get("innings_pitched"),
        batters_faced=standard.get("batters_faced"),
        strikeouts=standard.get("strikeouts"),
        walks=standard.get("walks"),
        home_runs_allowed=standard.get("home_runs_allowed"),
        runs_allowed=standard.get("runs_allowed"),
        hits_allowed=standard.get("hits_allowed"),
        fip=standard.get("fip"),
        siera=standard.get("siera"),
        k_pct=standard.get("k_pct") if standard.get("k_pct") is not None else (legacy_agg.k_pct if legacy_agg else None),
        bb_pct=standard.get("bb_pct") if standard.get("bb_pct") is not None else (legacy_agg.bb_pct if legacy_agg else None),
        k_minus_bb_pct=standard.get("k_minus_bb_pct"),
        hr_per_9=standard.get("hr_per_9"),
        gb_pct=gb_pct,
        fb_pct=fb_pct,
        hr_fb_pct=hr_fb_pct,
        babip=standard.get("babip"),
        lob_pct=standard.get("lob_pct"),
        xwoba_allowed=event_metrics.get("xwoba_allowed") if event_metrics.get("xwoba_allowed") is not None else (legacy_agg.xwoba if legacy_agg else None),
        xba_allowed=event_metrics.get("xba_allowed") if event_metrics.get("xba_allowed") is not None else (legacy_agg.xba if legacy_agg else None),
        hard_hit_pct=event_metrics.get("hard_hit_pct") if event_metrics.get("hard_hit_pct") is not None else (legacy_agg.hard_hit_pct if legacy_agg else None),
        barrel_pct=event_metrics.get("barrel_pct"),
        avg_exit_velocity_allowed=event_metrics.get("avg_exit_velocity_allowed"),
        avg_launch_angle_allowed=event_metrics.get("avg_launch_angle_allowed"),
        avg_velocity=event_metrics.get("avg_velocity") if event_metrics.get("avg_velocity") is not None else (legacy_agg.avg_velocity if legacy_agg else None),
        avg_spin_rate=event_metrics.get("avg_spin_rate") if event_metrics.get("avg_spin_rate") is not None else (legacy_agg.avg_spin_rate if legacy_agg else None),
        avg_horiz_break=event_metrics.get("avg_horiz_break") if event_metrics.get("avg_horiz_break") is not None else (legacy_agg.avg_horiz_break if legacy_agg else None),
        avg_vert_break=event_metrics.get("avg_vert_break") if event_metrics.get("avg_vert_break") is not None else (legacy_agg.avg_vert_break if legacy_agg else None),
        avg_release_pos_x=legacy_agg.avg_release_pos_x if legacy_agg else None,
        avg_release_pos_z=legacy_agg.avg_release_pos_z if legacy_agg else None,
        avg_release_extension=legacy_agg.avg_release_extension if legacy_agg else None,
        source_priority_json=["mlb_stats_api_people_pitching_season", "postgres_statcast_events", "pitcher_aggregates"],
        metric_sources_json={
            "fip": "formula_from_mlb_stats_and_constant",
            "siera": "formula_from_mlb_stats_rates",
            "gb_pct": "postgres_statcast_events",
            "fb_pct": "postgres_statcast_events",
            "hr_fb_pct": "postgres_statcast_events",
            "babip": "formula_from_mlb_stats",
            "lob_pct": "formula_from_mlb_stats",
        },
        missing_inputs_json=[],
        data_window_used=f"season={season}",
        profile_source="derived_serving_table",
        source_updated_at=dt.datetime.utcnow(),
        created_at=dt.datetime.utcnow(),
        updated_at=dt.datetime.utcnow(),
    )

    arsenal_rows: List[PitcherProfileArsenal] = []
    legacy_arsenal = (
        session.query(LegacyPitchArsenal)
        .filter(LegacyPitchArsenal.pitcher_id == pitcher_id, LegacyPitchArsenal.season == season)
        .order_by(LegacyPitchArsenal.usage_pct.desc())
        .all()
    )
    for row in legacy_arsenal:
        arsenal_rows.append(
            PitcherProfileArsenal(
                player_id=pitcher_id,
                season=season,
                pitch_type=row.pitch_type or "UN",
                pitch_name=row.pitch_name,
                pitch_count=row.pitch_count,
                usage_pct=_normalize_rate(row.usage_pct),
                whiff_pct=_normalize_rate(row.whiff_pct),
                strikeout_pct=_normalize_rate(row.strikeout_pct),
                xwoba=row.xwoba,
                hard_hit_pct=_normalize_rate(row.hard_hit_pct),
                source="pitch_arsenal",
                source_window=str(season),
                quality_flags_json=[],
                source_updated_at=dt.datetime.utcnow(),
                created_at=dt.datetime.utcnow(),
                updated_at=dt.datetime.utcnow(),
            )
        )

    recent_rows: List[PitcherProfileRecentGame] = []
    for game in get_pitcher_game_log(session, pitcher_id, 10):
        game_date = game.get("game_date")
        if not game_date:
            continue
        recent_rows.append(
            PitcherProfileRecentGame(
                player_id=pitcher_id,
                game_pk=game.get("game_pk"),
                game_date=dt.date.fromisoformat(str(game_date)[:10]),
                pitch_count=game.get("pitch_count"),
                plate_appearances=game.get("plate_appearances"),
                strikeouts=game.get("strikeouts"),
                walks=game.get("walks"),
                home_runs=game.get("home_runs"),
                hard_hit_pct=game.get("hard_hit_pct"),
                avg_velocity=game.get("avg_velocity"),
                source_updated_at=dt.datetime.utcnow(),
                created_at=dt.datetime.utcnow(),
                updated_at=dt.datetime.utcnow(),
            )
        )

    return overview, arsenal_rows, recent_rows


def upsert_pitcher_profile(session: Session, pitcher_id: int, season: int) -> Dict[str, Any]:
    overview, arsenal_rows, recent_rows = build_pitcher_profile_rows(session, pitcher_id, season)

    session.query(PitcherProfileOverview).filter(
        PitcherProfileOverview.player_id == pitcher_id,
        PitcherProfileOverview.season == season,
    ).delete(synchronize_session=False)
    session.query(PitcherProfileArsenal).filter(
        PitcherProfileArsenal.player_id == pitcher_id,
        PitcherProfileArsenal.season == season,
    ).delete(synchronize_session=False)
    session.query(PitcherProfileRecentGame).filter(
        PitcherProfileRecentGame.player_id == pitcher_id,
    ).delete(synchronize_session=False)

    if overview is not None:
        session.add(overview)
    for row in arsenal_rows:
        session.add(row)
    for row in recent_rows:
        session.add(row)
    session.commit()
    return {
        "pitcher_id": pitcher_id,
        "season": season,
        "overview_written": 1 if overview is not None else 0,
        "arsenal_written": len(arsenal_rows),
        "recent_games_written": len(recent_rows),
        "required_fields": {
            "fip": overview.fip if overview is not None else None,
            "siera": overview.siera if overview is not None else None,
            "gb_pct": overview.gb_pct if overview is not None else None,
            "fb_pct": overview.fb_pct if overview is not None else None,
            "hr_fb_pct": overview.hr_fb_pct if overview is not None else None,
            "babip": overview.babip if overview is not None else None,
            "lob_pct": overview.lob_pct if overview is not None else None,
        },
    }
