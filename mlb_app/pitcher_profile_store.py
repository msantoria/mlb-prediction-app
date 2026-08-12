from __future__ import annotations

import datetime as dt
from typing import Any, Dict, List, Optional

import requests as _req
from sqlalchemy import text
from sqlalchemy.orm import Session

from .db_utils import get_pitcher_game_log

MLB_STATS_BASE = "https://statsapi.mlb.com/api/v1"
FIP_CONSTANTS_BY_SEASON = {2023: 3.214, 2024: 3.214, 2025: 3.214, 2026: 3.214}


def _request_json(url: str, params: Optional[Dict[str, Any]] = None, timeout: int = 15) -> Dict[str, Any]:
    resp = _req.get(url, params=params, timeout=timeout)
    resp.raise_for_status()
    return resp.json()


def _safe_float(value: Any) -> Optional[float]:
    try:
        if value in (None, ""):
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def _safe_int(value: Any) -> Optional[int]:
    try:
        if value in (None, ""):
            return None
        return int(value)
    except (TypeError, ValueError):
        return None


def _normalize_rate(value: Optional[float]) -> Optional[float]:
    if value is None:
        return None
    return round(value / 100.0, 4) if value > 1 else round(value, 4)


def _innings_to_float(value: Any) -> Optional[float]:
    if value is None:
        return None
    text_value = str(value).strip()
    if not text_value:
        return None
    try:
        if "." in text_value:
            whole, frac = text_value.split(".", 1)
            outs = int(frac[:1] or 0)
            if outs in {0, 1, 2}:
                return round(float(int(whole)) + outs / 3.0, 3)
        return float(text_value)
    except (TypeError, ValueError):
        return None


def _fetch_pitching_season_stats(pitcher_id: int, season: int) -> Dict[str, Any]:
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


def _legacy_aggregate(session: Session, pitcher_id: int) -> Dict[str, Any]:
    row = session.execute(
        text(
            """
            SELECT avg_velocity, avg_spin_rate, hard_hit_pct, k_pct, bb_pct, xwoba, xba,
                   avg_horiz_break, avg_vert_break, avg_release_pos_x, avg_release_pos_z, avg_release_extension
            FROM pitcher_aggregates
            WHERE pitcher_id = :pitcher_id
            ORDER BY end_date DESC
            LIMIT 1
            """
        ),
        {"pitcher_id": pitcher_id},
    ).mappings().first()
    return dict(row) if row else {}


def _event_metrics(session: Session, pitcher_id: int, season: int) -> Dict[str, Any]:
    row = session.execute(
        text(
            """
            WITH ranked_pitches AS (
                SELECT statcast_events.*,
                       ROW_NUMBER() OVER (
                           PARTITION BY game_pk, at_bat_number, pitch_number
                           ORDER BY (
                               CASE WHEN description IS NOT NULL AND LOWER(TRIM(description)) NOT IN ('', 'nan', 'none', 'null', 'na', 'n/a') THEN 1 ELSE 0 END +
                               CASE WHEN events IS NOT NULL AND LOWER(TRIM(events)) NOT IN ('', 'nan', 'none', 'null', 'na', 'n/a') THEN 1 ELSE 0 END +
                               CASE WHEN pitch_type IS NOT NULL AND LOWER(TRIM(pitch_type)) NOT IN ('', 'nan', 'none', 'null', 'na', 'n/a') THEN 1 ELSE 0 END +
                               CASE WHEN release_speed IS NOT NULL THEN 1 ELSE 0 END +
                               CASE WHEN release_spin_rate IS NOT NULL THEN 1 ELSE 0 END +
                               CASE WHEN plate_x IS NOT NULL THEN 1 ELSE 0 END +
                               CASE WHEN plate_z IS NOT NULL THEN 1 ELSE 0 END +
                               CASE WHEN estimated_woba_using_speedangle IS NOT NULL THEN 1 ELSE 0 END +
                               CASE WHEN estimated_ba_using_speedangle IS NOT NULL THEN 1 ELSE 0 END
                           ) DESC,
                           id DESC
                       ) AS pitch_rank
                FROM statcast_events
                WHERE pitcher_id = :pitcher_id
                  AND game_date >= :start_date
                  AND game_date <= :end_date
                  AND game_pk IS NOT NULL
                  AND at_bat_number IS NOT NULL
                  AND pitch_number IS NOT NULL
            ),
            canonical_pitches AS (
                SELECT * FROM ranked_pitches WHERE pitch_rank = 1
            )
            SELECT
                SUM(CASE WHEN launch_speed IS NOT NULL THEN 1 ELSE 0 END) AS bbe,
                AVG(estimated_woba_using_speedangle) AS xwoba_allowed,
                AVG(estimated_ba_using_speedangle) AS xba_allowed,
                AVG(CASE WHEN launch_speed IS NOT NULL THEN launch_speed END) AS avg_exit_velocity_allowed,
                AVG(CASE WHEN launch_angle IS NOT NULL THEN launch_angle END) AS avg_launch_angle_allowed,
                AVG(release_speed) AS avg_velocity,
                AVG(release_spin_rate) AS avg_spin_rate,
                AVG(pfx_x) AS avg_horiz_break,
                AVG(pfx_z) AS avg_vert_break,
                SUM(CASE WHEN launch_speed >= 95 THEN 1 ELSE 0 END) AS hh,
                SUM(CASE WHEN launch_speed >= 98 AND launch_angle BETWEEN 8 AND 50 THEN 1 ELSE 0 END) AS barrels,
                SUM(CASE WHEN launch_angle < 10 THEN 1 ELSE 0 END) AS gb,
                SUM(CASE WHEN launch_angle >= 25 THEN 1 ELSE 0 END) AS fb,
                SUM(CASE WHEN events = 'home_run' THEN 1 ELSE 0 END) AS hr
            FROM canonical_pitches
            """
        ),
        {"pitcher_id": pitcher_id, "start_date": f"{season}-01-01", "end_date": f"{season}-12-31"},
    ).mappings().first()
    if not row:
        return {}
    bbe = _safe_int(row.get("bbe")) or 0
    fb = _safe_int(row.get("fb")) or 0
    return {
        "xwoba_allowed": round(float(row["xwoba_allowed"]), 3) if row.get("xwoba_allowed") is not None else None,
        "xba_allowed": round(float(row["xba_allowed"]), 3) if row.get("xba_allowed") is not None else None,
        "avg_exit_velocity_allowed": round(float(row["avg_exit_velocity_allowed"]), 1) if row.get("avg_exit_velocity_allowed") is not None else None,
        "avg_launch_angle_allowed": round(float(row["avg_launch_angle_allowed"]), 1) if row.get("avg_launch_angle_allowed") is not None else None,
        "avg_velocity": round(float(row["avg_velocity"]), 1) if row.get("avg_velocity") is not None else None,
        "avg_spin_rate": round(float(row["avg_spin_rate"]), 0) if row.get("avg_spin_rate") is not None else None,
        "avg_horiz_break": round(float(row["avg_horiz_break"]), 3) if row.get("avg_horiz_break") is not None else None,
        "avg_vert_break": round(float(row["avg_vert_break"]), 3) if row.get("avg_vert_break") is not None else None,
        "hard_hit_pct": round((_safe_int(row.get("hh")) or 0) / bbe, 4) if bbe else None,
        "barrel_pct": round((_safe_int(row.get("barrels")) or 0) / bbe, 4) if bbe else None,
        "gb_pct": round((_safe_int(row.get("gb")) or 0) / bbe, 4) if bbe else None,
        "fb_pct": round(fb / bbe, 4) if bbe else None,
        "hr_fb_pct": round((_safe_int(row.get("hr")) or 0) / fb, 4) if fb else None,
    }


def get_pitcher_profile_overview(session: Session, pitcher_id: int, season: int) -> Optional[Dict[str, Any]]:
    info = _fetch_pitching_season_stats(pitcher_id, season)
    stat = info.get("stat") or {}
    legacy = _legacy_aggregate(session, pitcher_id)
    events = _event_metrics(session, pitcher_id, season)

    hits = _safe_float(stat.get("hits"))
    hr = _safe_float(stat.get("homeRuns") or stat.get("homeRunsAllowed"))
    bb = _safe_float(stat.get("baseOnBalls") or stat.get("walks"))
    strikeouts = _safe_float(stat.get("strikeOuts") or stat.get("strikeouts"))
    at_bats = _safe_float(stat.get("atBats") or stat.get("ab"))
    runs = _safe_float(stat.get("runs") or stat.get("r"))
    batters_faced = _safe_float(stat.get("battersFaced") or stat.get("totalBattersFaced"))
    innings = _innings_to_float(stat.get("inningsPitched") or stat.get("ip"))

    k_pct = round(strikeouts / batters_faced, 4) if batters_faced and strikeouts is not None else legacy.get("k_pct")
    bb_pct = round(bb / batters_faced, 4) if batters_faced and bb is not None else legacy.get("bb_pct")
    k_minus_bb_pct = round(k_pct - bb_pct, 4) if k_pct is not None and bb_pct is not None else None
    hr_per_9 = round((hr * 9.0) / innings, 4) if innings and hr is not None else None
    babip = round((hits - hr) / (at_bats - strikeouts - hr), 4) if hits is not None and hr is not None and at_bats is not None and strikeouts is not None and (at_bats - strikeouts - hr) > 0 else None
    fip = round(((13 * hr) + (3 * bb) - (2 * strikeouts)) / innings + FIP_CONSTANTS_BY_SEASON.get(season, 3.214), 3) if innings and hr is not None and bb is not None and strikeouts is not None else None
    siera = round(6.145 - (16.986 * k_pct) + (11.434 * bb_pct) - (1.858 * 0.44) + (7.653 * (k_pct ** 2)) + (6.664 * (0.44 ** 2)) + (10.130 * k_pct * 0.44) - (5.195 * bb_pct * 0.44), 3) if k_pct is not None and bb_pct is not None else None

    payload = {
        "player_id": pitcher_id,
        "season": season,
        "player_name": info.get("player_name"),
        "team_id": info.get("team_id"),
        "team_name": info.get("team_name"),
        "era": _safe_float(stat.get("era")),
        "whip": _safe_float(stat.get("whip")),
        "wins": _safe_int(stat.get("wins")),
        "losses": _safe_int(stat.get("losses")),
        "games_pitched": _safe_int(stat.get("gamesPitched") or stat.get("gamesPlayed")),
        "games_started": _safe_int(stat.get("gamesStarted")),
        "innings_pitched": innings,
        "batters_faced": int(batters_faced) if batters_faced is not None else None,
        "strikeouts": int(strikeouts) if strikeouts is not None else None,
        "walks": int(bb) if bb is not None else None,
        "home_runs_allowed": int(hr) if hr is not None else None,
        "hits_allowed": int(hits) if hits is not None else None,
        "runs_allowed": int(runs) if runs is not None else None,
        "fip": fip,
        "xfip": None,
        "siera": siera,
        "xsiera": None,
        "k_pct": k_pct,
        "bb_pct": bb_pct,
        "k_minus_bb_pct": k_minus_bb_pct,
        "hr_per_9": hr_per_9,
        "gb_pct": events.get("gb_pct"),
        "fb_pct": events.get("fb_pct"),
        "hr_fb_pct": events.get("hr_fb_pct"),
        "babip": babip,
        "lob_pct": None,
        "xwoba_allowed": events.get("xwoba_allowed") if events.get("xwoba_allowed") is not None else legacy.get("xwoba"),
        "xba_allowed": events.get("xba_allowed") if events.get("xba_allowed") is not None else legacy.get("xba"),
        "hard_hit_pct": events.get("hard_hit_pct") if events.get("hard_hit_pct") is not None else legacy.get("hard_hit_pct"),
        "barrel_pct": events.get("barrel_pct"),
        "avg_exit_velocity_allowed": events.get("avg_exit_velocity_allowed"),
        "avg_launch_angle_allowed": events.get("avg_launch_angle_allowed"),
        "whiff_rate": None,
        "csw_rate": None,
        "avg_velocity": events.get("avg_velocity") if events.get("avg_velocity") is not None else legacy.get("avg_velocity"),
        "avg_spin_rate": events.get("avg_spin_rate") if events.get("avg_spin_rate") is not None else legacy.get("avg_spin_rate"),
        "avg_horiz_break": events.get("avg_horiz_break") if events.get("avg_horiz_break") is not None else legacy.get("avg_horiz_break"),
        "avg_vert_break": events.get("avg_vert_break") if events.get("avg_vert_break") is not None else legacy.get("avg_vert_break"),
        "avg_release_pos_x": legacy.get("avg_release_pos_x"),
        "avg_release_pos_z": legacy.get("avg_release_pos_z"),
        "avg_release_extension": legacy.get("avg_release_extension"),
        "source_priority_json": ["mlb_stats_api_people_pitching_season", "statcast_events", "pitcher_aggregates"],
        "metric_sources_json": {"fip": "formula", "siera": "formula", "xwoba_allowed": "statcast_events_or_legacy"},
        "missing_inputs_json": [],
        "data_window_used": f"season={season}",
        "profile_source": "live_derived_store",
        "source_updated_at": dt.datetime.utcnow(),
    }
    return payload if any(v is not None for k, v in payload.items() if k not in {"player_id", "season", "source_priority_json", "metric_sources_json", "missing_inputs_json", "data_window_used", "profile_source", "source_updated_at"}) else None


def get_pitcher_profile_arsenal(session: Session, pitcher_id: int, season: int) -> List[Dict[str, Any]]:
    rows = session.execute(
        text(
            """
            SELECT pitch_type, pitch_name, pitch_count, usage_pct, whiff_pct, strikeout_pct, xwoba, hard_hit_pct
            FROM pitch_arsenal
            WHERE pitcher_id = :pitcher_id AND season = :season
            ORDER BY usage_pct DESC
            """
        ),
        {"pitcher_id": pitcher_id, "season": season},
    ).mappings().all()
    return [
        {
            "pitch_type": row.get("pitch_type"),
            "pitch_name": row.get("pitch_name"),
            "pitch_count": row.get("pitch_count"),
            "usage_pct": _normalize_rate(_safe_float(row.get("usage_pct"))),
            "whiff_pct": _normalize_rate(_safe_float(row.get("whiff_pct"))),
            "strikeout_pct": _normalize_rate(_safe_float(row.get("strikeout_pct"))),
            "batted_ball_count": None,
            "xwoba": row.get("xwoba"),
            "hard_hit_pct": _normalize_rate(_safe_float(row.get("hard_hit_pct"))),
            "avg_velocity": None,
            "avg_spin_rate": None,
            "avg_horiz_break": None,
            "avg_vert_break": None,
            "avg_release_pos_x": None,
            "avg_release_pos_z": None,
            "avg_release_extension": None,
            "source": "pitch_arsenal",
            "source_window": str(season),
            "quality_flags_json": [],
        }
        for row in rows
    ]


def get_pitcher_profile_recent_games(session: Session, pitcher_id: int, limit: int = 10) -> List[Dict[str, Any]]:
    rows = get_pitcher_game_log(session, pitcher_id, limit)
    return [
        {
            "player_id": pitcher_id,
            "game_pk": row.get("game_pk"),
            "game_date": row.get("game_date"),
            "pitch_count": row.get("pitch_count"),
            "plate_appearances": row.get("plate_appearances"),
            "strikeouts": row.get("strikeouts"),
            "walks": row.get("walks"),
            "home_runs": row.get("home_runs"),
            "hard_hit_pct": row.get("hard_hit_pct"),
            "avg_velocity": row.get("avg_velocity"),
        }
        for row in rows
        if row.get("game_date")
    ]


def serialize_pitcher_profile_overview(row: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    return dict(row) if row else None


def serialize_pitcher_profile_arsenal(rows: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    return [dict(row) for row in rows]


def serialize_pitcher_profile_recent_games(rows: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    return [dict(row) for row in rows]


def upsert_pitcher_profile(session: Session, pitcher_id: int, season: int) -> Dict[str, Any]:
    return {
        "pitcher_id": pitcher_id,
        "season": season,
        "overview": bool(get_pitcher_profile_overview(session, pitcher_id, season)),
        "arsenal_rows": len(get_pitcher_profile_arsenal(session, pitcher_id, season)),
        "recent_game_rows": len(get_pitcher_profile_recent_games(session, pitcher_id, 10)),
    }
