from __future__ import annotations

import datetime as dt
from typing import Any, Dict, List, Optional, Set, Tuple

import requests
from sqlalchemy import case, func
from sqlalchemy.orm import Session

from mlb_app.database import PitchArsenal, PitcherAggregate, StatcastEvent

MLB_STATS_BASE = "https://statsapi.mlb.com/api/v1"
MIN_PROFILE_PITCHES = 250
MIN_DAMAGE_BBE = 35
MIN_ARSENAL_PITCHES = 75


def _fetch_pitcher_names(player_ids: Set[int]) -> Dict[int, Dict[str, Optional[str]]]:
    ids = sorted(pid for pid in player_ids if pid)
    if not ids:
        return {}
    out: Dict[int, Dict[str, Optional[str]]] = {}
    for start in range(0, len(ids), 75):
        chunk = ids[start:start + 75]
        try:
            resp = requests.get(
                f"{MLB_STATS_BASE}/people",
                params={"personIds": ",".join(str(pid) for pid in chunk), "hydrate": "currentTeam"},
                timeout=8,
            )
            if not resp.ok:
                continue
            for person in resp.json().get("people", []) or []:
                pid = person.get("id")
                if not pid:
                    continue
                team = person.get("currentTeam") or {}
                out[int(pid)] = {
                    "player_name": person.get("fullName") or f"MLB ID {pid}",
                    "team": team.get("abbreviation") or team.get("name"),
                }
        except Exception:
            continue
    return out


def _display_name(pid: int, identities: Dict[int, Dict[str, Optional[str]]]) -> str:
    return (identities.get(pid) or {}).get("player_name") or f"MLB ID {pid}"


def _team(pid: int, identities: Dict[int, Dict[str, Optional[str]]]) -> Optional[str]:
    return (identities.get(pid) or {}).get("team")


def _event_samples(session: Session, season: int) -> Dict[int, Dict[str, int]]:
    season_start = dt.date(int(season), 1, 1)
    season_end = dt.date(int(season), 12, 31)
    canonical_pitches = (
        session.query(
            StatcastEvent.pitcher_id.label("pitcher_id"),
            StatcastEvent.game_pk.label("game_pk"),
            StatcastEvent.at_bat_number.label("at_bat_number"),
            StatcastEvent.pitch_number.label("pitch_number"),
            func.max(case((StatcastEvent.launch_speed.isnot(None), 1), else_=0)).label("is_bbe"),
        )
        .filter(
            StatcastEvent.game_date >= season_start,
            StatcastEvent.game_date <= season_end,
            StatcastEvent.pitcher_id.isnot(None),
            StatcastEvent.game_pk.isnot(None),
            StatcastEvent.at_bat_number.isnot(None),
            StatcastEvent.pitch_number.isnot(None),
        )
        .group_by(
            StatcastEvent.pitcher_id,
            StatcastEvent.game_pk,
            StatcastEvent.at_bat_number,
            StatcastEvent.pitch_number,
        )
        .subquery()
    )
    rows = (
        session.query(
            canonical_pitches.c.pitcher_id,
            func.count(),
            func.sum(canonical_pitches.c.is_bbe),
        )
        .group_by(canonical_pitches.c.pitcher_id)
        .all()
    )
    samples = {
        int(pid): {"pitches": int(pitches or 0), "batted_balls": int(bbe or 0)}
        for pid, pitches, bbe in rows
        if pid
    }

    # The season arsenal is an independent Savant aggregate and is a safer
    # minimum-sample fallback for pitchers whose legacy rows lack pitch IDs.
    arsenal_rows = (
        session.query(PitchArsenal.pitcher_id, func.sum(PitchArsenal.pitch_count))
        .filter(PitchArsenal.season == int(season))
        .group_by(PitchArsenal.pitcher_id)
        .all()
    )
    for pitcher_id, pitch_count in arsenal_rows:
        if not pitcher_id:
            continue
        sample = samples.setdefault(int(pitcher_id), {"pitches": 0, "batted_balls": 0})
        sample["pitches"] = max(sample["pitches"], int(pitch_count or 0))
    return samples


def _latest_aggregates(session: Session, season: int) -> List[PitcherAggregate]:
    rows = (
        session.query(PitcherAggregate)
        .filter(PitcherAggregate.end_date >= dt.date(int(season), 1, 1))
        .order_by(PitcherAggregate.end_date.desc())
        .all()
    )
    latest_by_pitcher: Dict[int, PitcherAggregate] = {}
    for row in rows:
        latest_by_pitcher.setdefault(row.pitcher_id, row)
    return list(latest_by_pitcher.values())


def _sample_label(pid: int, samples: Dict[int, Dict[str, int]], fallback: Optional[str] = None) -> str:
    sample = samples.get(pid) or {}
    pitches = sample.get("pitches") or 0
    bbe = sample.get("batted_balls") or 0
    if pitches:
        return f"{pitches} pitches · {bbe} BBE"
    return fallback or "sample pending"


def _row(pid: int, value: float, rank: int, identities: Dict[int, Dict[str, Optional[str]]], samples: Dict[int, Dict[str, int]], *, sample: Optional[str] = None, detail: Optional[str] = None, extra: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    return {
        "rank": rank,
        "player_id": pid,
        "player_name": _display_name(pid, identities),
        "team": _team(pid, identities),
        "value": round(float(value), 4),
        "sample": sample or _sample_label(pid, samples),
        "detail": detail,
        **(extra or {}),
    }


def _rank_profile(rows: List[Tuple[PitcherAggregate, float, str]], identities: Dict[int, Dict[str, Optional[str]]], samples: Dict[int, Dict[str, int]], limit: int) -> List[Dict[str, Any]]:
    rows.sort(key=lambda item: item[1], reverse=True)
    return [_row(row.pitcher_id, value, idx + 1, identities, samples, detail=detail) for idx, (row, value, detail) in enumerate(rows[:limit])]


def _quality_profiles(latest: List[PitcherAggregate], samples: Dict[int, Dict[str, int]], identities: Dict[int, Dict[str, Optional[str]]], limit: int) -> List[Dict[str, Any]]:
    scored = []
    for row in latest:
        sample = samples.get(row.pitcher_id, {})
        if (sample.get("pitches") or 0) < MIN_PROFILE_PITCHES:
            continue
        if None in (row.k_pct, row.bb_pct, row.xwoba, row.hard_hit_pct):
            continue
        k_minus_bb = float(row.k_pct) - float(row.bb_pct)
        value = (k_minus_bb * 1.6) + ((0.330 - float(row.xwoba)) * 2.2) + ((0.380 - float(row.hard_hit_pct)) * 0.9)
        if row.avg_velocity is not None:
            value += (float(row.avg_velocity) - 92.0) / 100.0
        detail = f"K-BB {k_minus_bb * 100:.1f}% · xwOBA {row.xwoba:.3f} · HH {row.hard_hit_pct * 100:.1f}%"
        scored.append((row, value, detail))
    return _rank_profile(scored, identities, samples, limit)


def _command_profiles(latest: List[PitcherAggregate], samples: Dict[int, Dict[str, int]], identities: Dict[int, Dict[str, Optional[str]]], limit: int) -> List[Dict[str, Any]]:
    scored = []
    for row in latest:
        sample = samples.get(row.pitcher_id, {})
        if (sample.get("pitches") or 0) < MIN_PROFILE_PITCHES:
            continue
        if row.k_pct is None or row.bb_pct is None:
            continue
        value = float(row.k_pct) - float(row.bb_pct)
        detail = f"K {row.k_pct * 100:.1f}% · BB {row.bb_pct * 100:.1f}%"
        scored.append((row, value, detail))
    return _rank_profile(scored, identities, samples, limit)


def _damage_profiles(latest: List[PitcherAggregate], samples: Dict[int, Dict[str, int]], identities: Dict[int, Dict[str, Optional[str]]], limit: int) -> List[Dict[str, Any]]:
    scored = []
    for row in latest:
        sample = samples.get(row.pitcher_id, {})
        if (sample.get("pitches") or 0) < MIN_PROFILE_PITCHES or (sample.get("batted_balls") or 0) < MIN_DAMAGE_BBE:
            continue
        if row.xwoba is None or row.hard_hit_pct is None:
            continue
        value = (0.330 - float(row.xwoba)) + ((0.380 - float(row.hard_hit_pct)) * 0.45)
        detail = f"xwOBA {row.xwoba:.3f} · HH {row.hard_hit_pct * 100:.1f}%"
        scored.append((row, value, detail))
    return _rank_profile(scored, identities, samples, limit)


def _release_profiles(latest: List[PitcherAggregate], samples: Dict[int, Dict[str, int]], identities: Dict[int, Dict[str, Optional[str]]], limit: int) -> List[Dict[str, Any]]:
    scored = []
    for row in latest:
        sample = samples.get(row.pitcher_id, {})
        if (sample.get("pitches") or 0) < MIN_PROFILE_PITCHES:
            continue
        if row.avg_release_extension is None or row.avg_velocity is None:
            continue
        value = float(row.avg_release_extension) + ((float(row.avg_velocity) - 92.0) / 10.0)
        detail = f"Ext {row.avg_release_extension:.2f} ft · Velo {row.avg_velocity:.1f}"
        scored.append((row, value, detail))
    return _rank_profile(scored, identities, samples, limit)


def _power_profiles(latest: List[PitcherAggregate], samples: Dict[int, Dict[str, int]], identities: Dict[int, Dict[str, Optional[str]]], limit: int) -> List[Dict[str, Any]]:
    scored = []
    for row in latest:
        sample = samples.get(row.pitcher_id, {})
        if (sample.get("pitches") or 0) < MIN_PROFILE_PITCHES:
            continue
        if row.avg_velocity is None:
            continue
        spin_bonus = ((float(row.avg_spin_rate or 0) - 2300.0) / 10000.0) if row.avg_spin_rate else 0.0
        extension_bonus = ((float(row.avg_release_extension or 0) - 6.0) / 10.0) if row.avg_release_extension else 0.0
        value = (float(row.avg_velocity) - 90.0) / 10.0 + spin_bonus + extension_bonus
        detail = f"Velo {row.avg_velocity:.1f}" + (f" · Spin {row.avg_spin_rate:.0f}" if row.avg_spin_rate else "")
        scored.append((row, value, detail))
    return _rank_profile(scored, identities, samples, limit)


def _arsenal_profiles(rows: List[PitchArsenal], identities: Dict[int, Dict[str, Optional[str]]], samples: Dict[int, Dict[str, int]], limit: int) -> List[Dict[str, Any]]:
    usable = []
    for row in rows:
        if (row.pitch_count or 0) < MIN_ARSENAL_PITCHES:
            continue
        if row.whiff_pct is None or row.xwoba is None:
            continue
        value = (float(row.whiff_pct) * 1.2) + ((0.330 - float(row.xwoba)) * 1.8)
        label = row.pitch_name or row.pitch_type or "Pitch"
        detail = f"{label} · Whiff {row.whiff_pct * 100:.1f}% · xwOBA {row.xwoba:.3f}"
        usable.append((row, value, detail))
    usable.sort(key=lambda item: item[1], reverse=True)
    board = []
    for idx, (row, value, detail) in enumerate(usable[:limit]):
        board.append(_row(
            row.pitcher_id,
            value,
            idx + 1,
            identities,
            samples,
            sample=f"{row.pitch_count or 0} {row.pitch_name or row.pitch_type or 'pitch'}",
            detail=detail,
            extra={"pitch_type": row.pitch_type, "pitch_name": row.pitch_name, "pitch_count": row.pitch_count},
        ))
    return board


def build_pitcher_leaderboards(session: Session, season: Optional[int] = None, limit: int = 10) -> Dict[str, Any]:
    if season is None:
        season = dt.date.today().year

    samples = _event_samples(session, int(season))
    latest = _latest_aggregates(session, int(season))
    arsenal_rows = session.query(PitchArsenal).filter(PitchArsenal.season == int(season)).all()
    identity_ids = {row.pitcher_id for row in latest} | {row.pitcher_id for row in arsenal_rows}
    identities = _fetch_pitcher_names(identity_ids)

    leaderboards = {
        "pitcher_quality": _quality_profiles(latest, samples, identities, limit),
        "command_index": _command_profiles(latest, samples, identities, limit),
        "damage_suppression": _damage_profiles(latest, samples, identities, limit),
        "power_stuff": _power_profiles(latest, samples, identities, limit),
        "release_weapon": _release_profiles(latest, samples, identities, limit),
        "arsenal_weapon": _arsenal_profiles(arsenal_rows, identities, samples, limit),
    }

    unavailable = [key for key, rows in leaderboards.items() if not rows]
    return {
        "season": int(season),
        "limit": int(limit),
        "leaderboards": leaderboards,
        "identity_source": "mlb_stats_api_people" if identities else "fallback_player_id",
        "sample_rules": {
            "profile_min_pitches": MIN_PROFILE_PITCHES,
            "arsenal_min_pitch_count": MIN_ARSENAL_PITCHES,
            "damage_min_batted_balls": MIN_DAMAGE_BBE,
        },
        "notes": [
            "Landing boards use baseball-composite indexes with minimum samples instead of raw lowest/highest rate traps.",
            "Release leaderboards use PitcherAggregate release fields; location visuals use plate_x/plate_z in the pitcher intelligence endpoint.",
        ],
        "unavailable_metrics": unavailable,
    }
