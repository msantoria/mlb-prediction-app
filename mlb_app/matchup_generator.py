"""
Matchup generation: assembles game-level feature vectors from the DB and
computes canonical win probabilities.
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Dict, List, Optional

from sqlalchemy.orm import Session

from .canonical_matchup_probability import compute_canonical_matchup_probability
from .db_utils import get_batter_aggregate, get_pitch_arsenal, get_pitcher_aggregate, get_player_split, get_team_split
from .etl import fetch_schedule
from .lineup_profile import build_lineup_offense_diagnostics, build_lineup_offense_inputs
from .performance import estimate_payload_bytes, record_probability_source, record_span, timing_span
from .pitcher_profile_store import get_pitcher_profile_overview
from .shared_payload_cache import env_ttl, get_cache, make_cache_key, set_cache

log = logging.getLogger(__name__)


def _empty_pitcher_features() -> Dict[str, Optional[float]]:
    return {k: None for k in [
        "avg_velocity", "avg_spin_rate", "hard_hit_pct", "k_pct", "bb_pct",
        "xwoba", "xba", "avg_horiz_break", "avg_vert_break",
        "avg_release_pos_x", "avg_release_pos_z", "avg_release_extension",
        "source_window", "source_type", "source_priority",
    ]}


def _format_pitcher_features(session: Session, pitcher_id: int) -> Dict[str, Optional[float]]:
    season = datetime.utcnow().year

    try:
        overview = get_pitcher_profile_overview(session, pitcher_id, season) or {}
    except Exception:
        overview = {}

    if any(
        overview.get(key) is not None
        for key in ["k_pct", "bb_pct", "hard_hit_pct", "xwoba_allowed", "xba_allowed", "avg_velocity", "avg_spin_rate"]
    ):
        return {
            "avg_velocity": overview.get("avg_velocity"),
            "avg_spin_rate": overview.get("avg_spin_rate"),
            "hard_hit_pct": overview.get("hard_hit_pct"),
            "k_pct": overview.get("k_pct"),
            "bb_pct": overview.get("bb_pct"),
            "xwoba": overview.get("xwoba_allowed"),
            "xba": overview.get("xba_allowed"),
            "avg_horiz_break": overview.get("avg_horiz_break"),
            "avg_vert_break": overview.get("avg_vert_break"),
            "avg_release_pos_x": overview.get("avg_release_pos_x"),
            "avg_release_pos_z": overview.get("avg_release_pos_z"),
            "avg_release_extension": overview.get("avg_release_extension"),
            "source_window": overview.get("data_window_used"),
            "source_type": overview.get("profile_source") or "pitcher_profile_overview",
            "source_priority": overview.get("source_priority_json"),
        }

    agg = get_pitcher_aggregate(session, pitcher_id, "90d")
    if not agg:
        return _empty_pitcher_features()

    return {
        "avg_velocity": agg.avg_velocity,
        "avg_spin_rate": agg.avg_spin_rate,
        "hard_hit_pct": agg.hard_hit_pct,
        "k_pct": agg.k_pct,
        "bb_pct": agg.bb_pct,
        "xwoba": agg.xwoba,
        "xba": agg.xba,
        "avg_horiz_break": agg.avg_horiz_break,
        "avg_vert_break": agg.avg_vert_break,
        "avg_release_pos_x": agg.avg_release_pos_x,
        "avg_release_pos_z": agg.avg_release_pos_z,
        "avg_release_extension": agg.avg_release_extension,
        "source_window": agg.window,
        "source_type": "pitcher_aggregates_90d",
        "source_priority": ["pitcher_aggregates"],
    }


def _format_pitch_arsenal(session: Session, pitcher_id: int, season: int) -> Dict:
    records = get_pitch_arsenal(session, pitcher_id, season)
    return {
        rec.pitch_type or "": {
            "usage_pct": rec.usage_pct,
            "whiff_pct": rec.whiff_pct,
            "strikeout_pct": rec.strikeout_pct,
            "rv_per_100": rec.rv_per_100,
            "xwoba": rec.xwoba,
            "hard_hit_pct": rec.hard_hit_pct,
        }
        for rec in records
    }


def _format_batter_features(session: Session, batter_id: int) -> Dict[str, Optional[float]]:
    agg = get_batter_aggregate(session, batter_id, "90d")
    if not agg:
        return {k: None for k in [
            "avg_exit_velocity", "avg_launch_angle", "hard_hit_pct",
            "barrel_pct", "k_pct", "bb_pct", "batting_avg",
        ]}
    return {
        "avg_exit_velocity": agg.avg_exit_velocity,
        "avg_launch_angle": agg.avg_launch_angle,
        "hard_hit_pct": agg.hard_hit_pct,
        "barrel_pct": agg.barrel_pct,
        "k_pct": agg.k_pct,
        "bb_pct": agg.bb_pct,
        "batting_avg": agg.batting_avg,
    }


def _pitcher_status(pitcher_id: Optional[int]) -> str:
    return "probable" if pitcher_id else "missing"


def _pitcher_source(pitcher_id: Optional[int]) -> Optional[str]:
    return "mlb_stats_probablePitcher" if pitcher_id else None


def _with_lineup_fallback_diagnostics(offense_inputs: Dict, diagnostics: Optional[Dict]) -> Dict:
    updated = dict(offense_inputs or {})
    diagnostics = diagnostics or {}
    for key in (
        "lineup_fallback_reason",
        "lineup_fallback_stage",
        "lineup_fetch_attempted",
        "lineup_fetch_succeeded",
        "lineup_side_found",
        "starting_lineup_count",
        "usable_hitter_profile_count",
        "real_player_profile_count",
        "fallback_player_count",
        "min_usable_hitters",
        "confirmed_lineup_inputs_would_activate",
    ):
        if key in diagnostics:
            updated[key] = diagnostics.get(key)
    return updated


def _with_lineup_exception_diagnostics(offense_inputs: Dict, exc: Exception) -> Dict:
    message = str(exc)
    exc_type = exc.__class__.__name__
    lowered = message.lower()
    updated = dict(offense_inputs or {})
    updated.update({
        "lineup_fallback_reason": "confirmed_lineup_fetch_or_build_error",
        "lineup_fallback_stage": "exception",
        "lineup_fetch_attempted": True,
        "lineup_fetch_succeeded": False,
        "lineup_fetch_error_type": exc_type,
        "lineup_fetch_error_message": message,
        "lineup_fetch_timeout": (
            "timeout" in lowered
            or "timed out" in lowered
            or exc_type in {"ReadTimeout", "ReadTimeoutError", "TimeoutError"}
        ),
    })
    return updated


def _format_team_offense_inputs(session: Session, team_id: int, season: int, split: str = "vsR") -> Dict[str, Optional[float]]:
    row = get_team_split(session, team_id, season, split) or get_team_split(
        session,
        team_id,
        season,
        "vsL" if split == "vsR" else "vsR",
    )
    if not row:
        return {
            "source": "missing_team_splits",
            "team_id": team_id,
            "season": season,
            "split": split,
            "pa": None,
            "hits": None,
            "doubles": None,
            "triples": None,
            "home_runs": None,
            "walks": None,
            "strikeouts": None,
            "batting_avg": None,
            "on_base_pct": None,
            "slugging_pct": None,
            "iso": None,
            "k_pct": None,
            "bb_pct": None,
        }

    batting_avg = row.batting_avg
    slugging_pct = row.slugging_pct
    computed_iso = None
    if batting_avg is not None and slugging_pct is not None:
        computed_iso = round(max(float(slugging_pct) - float(batting_avg), 0.0), 3)

    return {
        "source": "team_splits",
        "team_id": team_id,
        "season": season,
        "split": row.split,
        "pa": row.pa,
        "hits": row.hits,
        "doubles": row.doubles,
        "triples": row.triples,
        "home_runs": row.home_runs,
        "walks": row.walks,
        "strikeouts": row.strikeouts,
        "batting_avg": batting_avg,
        "on_base_pct": row.on_base_pct,
        "slugging_pct": slugging_pct,
        "iso": computed_iso,
        "stored_iso": row.iso,
        "k_pct": row.k_pct,
        "bb_pct": row.bb_pct,
        "lineup_source": "team_splits_fallback_not_confirmed_lineup",
        "sample_blend": {"type": "team_split", "season": season, "split": row.split},
    }


def _add_missing_pitcher_diagnostics(base_matchup: Dict) -> None:
    missing = []
    if not base_matchup.get("home_team_id"):
        missing.append("home_team_id")
    if not base_matchup.get("away_team_id"):
        missing.append("away_team_id")
    if not base_matchup.get("home_pitcher_id"):
        missing.append("home_pitcher_id")
    if not base_matchup.get("away_pitcher_id"):
        missing.append("away_pitcher_id")
    base_matchup.update({
        "model_version": "canonical_matchup_win_probability_v2",
        "legacy_model_version": "legacy_matchup_win_probability_v1",
        "legacy_home_win_prob": None,
        "legacy_away_win_prob": None,
        "lineup_status": "unknown",
        "data_confidence": "low",
        "probability_components": {},
        "pitcher_overview": {"home": {}, "away": {}},
        "batter_vs_arsenal_schema_version": "batter_vs_arsenal_v2",
        "batter_vs_arsenal_summary": {},
        "missing_inputs": missing,
    })


def _apply_canonical_probability(session: Session, base_matchup: Dict, season: int) -> None:
    with timing_span(
        "compute_canonical_matchup_probability",
        category="probability_resolution",
        route="/matchups",
        game_pk=base_matchup.get("game_pk"),
        date=base_matchup.get("game_date"),
        probability_source="canonical_matchup_win_probability_v2",
    ):
        canonical = compute_canonical_matchup_probability(
            session=session,
            home_pitcher_id=base_matchup["home_pitcher_id"],
            away_pitcher_id=base_matchup["away_pitcher_id"],
            home_team_id=base_matchup["home_team_id"],
            away_team_id=base_matchup["away_team_id"],
            season=season,
            context=base_matchup,
        )
    for key in (
        "model_version",
        "legacy_model_version",
        "home_win_prob",
        "away_win_prob",
        "legacy_home_win_prob",
        "legacy_away_win_prob",
        "lineup_status",
        "data_confidence",
        "probability_components",
        "pitcher_overview",
        "batter_vs_arsenal_schema_version",
        "batter_vs_arsenal_summary",
        "missing_inputs",
    ):
        base_matchup[key] = canonical.get(key)
    record_probability_source(canonical.get("model_version") or "canonical_matchup_win_probability_v2")


def _generate_matchups_for_date_uncached(session: Session, date_str: str) -> List[Dict]:
    try:
        date_obj = datetime.strptime(date_str, "%Y-%m-%d")
    except ValueError:
        raise ValueError("date_str must be in YYYY-MM-DD format")

    with timing_span("matchups.fetch_schedule", category="schedule", route="/matchups", date=date_str):
        schedule = fetch_schedule(date_str)
    season = date_obj.year
    matchups = []

    for game in schedule:
        home_team = game.get("home", {}).get("team", {}).get("id")
        away_team = game.get("away", {}).get("team", {}).get("id")
        home_pitcher_id = game.get("home", {}).get("probablePitcher", {}).get("id")
        away_pitcher_id = game.get("away", {}).get("probablePitcher", {}).get("id")
        home_record = game.get("home", {}).get("leagueRecord", {})
        away_record = game.get("away", {}).get("leagueRecord", {})

        base_matchup = {
            "game_date": date_str,
            "game_pk": game.get("_game_pk"),
            "game_time": game.get("_game_date"),
            "venue": game.get("_venue"),
            "status": game.get("_status"),
            "weather": game.get("_weather"),
            "home_team_id": home_team,
            "away_team_id": away_team,
            "home_team_name": game.get("home", {}).get("team", {}).get("name"),
            "away_team_name": game.get("away", {}).get("team", {}).get("name"),
            "home_team_record": f"{home_record.get('wins', 0)}-{home_record.get('losses', 0)}" if home_record else None,
            "away_team_record": f"{away_record.get('wins', 0)}-{away_record.get('losses', 0)}" if away_record else None,
            "home_pitcher_id": home_pitcher_id,
            "away_pitcher_id": away_pitcher_id,
            "home_pitcher_name": game.get("home", {}).get("probablePitcher", {}).get("fullName"),
            "away_pitcher_name": game.get("away", {}).get("probablePitcher", {}).get("fullName"),
            "home_pitcher_hand": game.get("home", {}).get("probablePitcher", {}).get("pitchHand", {}).get("code"),
            "away_pitcher_hand": game.get("away", {}).get("probablePitcher", {}).get("pitchHand", {}).get("code"),
            "home_pitcher_status": _pitcher_status(home_pitcher_id),
            "away_pitcher_status": _pitcher_status(away_pitcher_id),
            "home_pitcher_source": _pitcher_source(home_pitcher_id),
            "away_pitcher_source": _pitcher_source(away_pitcher_id),
            "home_win_prob": None,
            "away_win_prob": None,
            "legacy_home_win_prob": None,
            "legacy_away_win_prob": None,
            "model_version": "canonical_matchup_win_probability_v2",
            "legacy_model_version": "legacy_matchup_win_probability_v1",
            "lineup_status": "unknown",
            "data_confidence": "low",
            "probability_components": {},
            "pitcher_overview": {"home": {}, "away": {}},
            "batter_vs_arsenal_schema_version": "batter_vs_arsenal_v2",
            "batter_vs_arsenal_summary": {},
            "missing_inputs": [],
            "home_pitcher_features": {},
            "away_pitcher_features": {},
            "home_pitch_arsenal": {},
            "away_pitch_arsenal": {},
            "home_offense_inputs": {},
            "away_offense_inputs": {},
        }

        if not all([home_team, away_team, home_pitcher_id, away_pitcher_id]):
            _add_missing_pitcher_diagnostics(base_matchup)
            matchups.append(base_matchup)
            continue

        try:
            with timing_span("matchups.pitcher_features", category="db", route="/matchups", game_pk=game.get("_game_pk"), date=date_str):
                base_matchup["home_pitcher_features"] = _format_pitcher_features(session, home_pitcher_id)
                base_matchup["away_pitcher_features"] = _format_pitcher_features(session, away_pitcher_id)
        except Exception:
            log.exception(
                "Pitcher feature formatting failed for game_pk=%s date=%s home_pitcher_id=%s away_pitcher_id=%s",
                game.get("_game_pk"), date_str, home_pitcher_id, away_pitcher_id,
            )

        try:
            with timing_span("matchups.pitch_arsenal", category="db", route="/matchups", game_pk=game.get("_game_pk"), date=date_str):
                base_matchup["home_pitch_arsenal"] = _format_pitch_arsenal(session, home_pitcher_id, season)
                base_matchup["away_pitch_arsenal"] = _format_pitch_arsenal(session, away_pitcher_id, season)
        except Exception:
            log.exception(
                "Pitch arsenal formatting failed for game_pk=%s date=%s home_pitcher_id=%s away_pitcher_id=%s season=%s",
                game.get("_game_pk"), date_str, home_pitcher_id, away_pitcher_id, season,
            )

        try:
            home_split = "vsL" if game.get("away", {}).get("probablePitcher", {}).get("pitchHand", {}).get("code") == "L" else "vsR"
            away_split = "vsL" if game.get("home", {}).get("probablePitcher", {}).get("pitchHand", {}).get("code") == "L" else "vsR"
            home_team_fallback = _format_team_offense_inputs(session, home_team, season, home_split)
            away_team_fallback = _format_team_offense_inputs(session, away_team, season, away_split)
            base_matchup["home_offense_inputs"] = home_team_fallback
            base_matchup["away_offense_inputs"] = away_team_fallback

            try:
                with timing_span("build_lineup_offense_diagnostics", category="formula", route="/matchups", game_pk=game.get("_game_pk"), date=date_str, extra={"side": "home"}):
                    home_lineup_diagnostics = build_lineup_offense_diagnostics(
                        session=session,
                        game_pk=game.get("_game_pk"),
                        side="home",
                        team_id=home_team,
                        season=season,
                        split=home_split,
                        team_fallback=home_team_fallback,
                    )
                with timing_span("build_lineup_offense_inputs", category="formula", route="/matchups", game_pk=game.get("_game_pk"), date=date_str, extra={"side": "home"}):
                    home_lineup_inputs = build_lineup_offense_inputs(
                        session=session,
                        game_pk=game.get("_game_pk"),
                        side="home",
                        team_id=home_team,
                        season=season,
                        split=home_split,
                        team_fallback=home_team_fallback,
                    )
                base_matchup["home_offense_inputs"] = home_lineup_inputs or _with_lineup_fallback_diagnostics(base_matchup["home_offense_inputs"], home_lineup_diagnostics)
            except Exception as exc:
                base_matchup["home_offense_inputs"] = _with_lineup_exception_diagnostics(base_matchup["home_offense_inputs"], exc)
                log.exception("Confirmed home lineup offense input failed; using fallback for game_pk=%s date=%s home_team_id=%s", game.get("_game_pk"), date_str, home_team)

            try:
                with timing_span("build_lineup_offense_diagnostics", category="formula", route="/matchups", game_pk=game.get("_game_pk"), date=date_str, extra={"side": "away"}):
                    away_lineup_diagnostics = build_lineup_offense_diagnostics(
                        session=session,
                        game_pk=game.get("_game_pk"),
                        side="away",
                        team_id=away_team,
                        season=season,
                        split=away_split,
                        team_fallback=away_team_fallback,
                    )
                with timing_span("build_lineup_offense_inputs", category="formula", route="/matchups", game_pk=game.get("_game_pk"), date=date_str, extra={"side": "away"}):
                    away_lineup_inputs = build_lineup_offense_inputs(
                        session=session,
                        game_pk=game.get("_game_pk"),
                        side="away",
                        team_id=away_team,
                        season=season,
                        split=away_split,
                        team_fallback=away_team_fallback,
                    )
                base_matchup["away_offense_inputs"] = away_lineup_inputs or _with_lineup_fallback_diagnostics(base_matchup["away_offense_inputs"], away_lineup_diagnostics)
            except Exception as exc:
                base_matchup["away_offense_inputs"] = _with_lineup_exception_diagnostics(base_matchup["away_offense_inputs"], exc)
                log.exception("Confirmed away lineup offense input failed; using fallback for game_pk=%s date=%s away_team_id=%s", game.get("_game_pk"), date_str, away_team)
        except Exception:
            log.exception(
                "Team offense input formatting failed for game_pk=%s date=%s home_team_id=%s away_team_id=%s season=%s",
                game.get("_game_pk"), date_str, home_team, away_team, season,
            )

        try:
            _apply_canonical_probability(session, base_matchup, season)
        except Exception:
            log.exception(
                "Canonical win probability failed for game_pk=%s date=%s home_pitcher_id=%s away_pitcher_id=%s",
                game.get("_game_pk"), date_str, home_pitcher_id, away_pitcher_id,
            )

        matchups.append(base_matchup)

    return matchups


def generate_matchups_for_date(session: Session, date_str: str) -> List[Dict]:
    """Generate daily matchup slate with a process-local TTL cache.

    This restores the Friday fast-load pattern without touching app.py. The first
    request for a date performs the expensive schedule, lineup, canonical model,
    simulation, and starter-overview work. Repeated homepage/model calls for the
    same date reuse the cached slate for MATCHUPS_CACHE_TTL_SECONDS.
    """
    cache_key = make_cache_key("matchups", "date", date_str)
    ttl_seconds = env_ttl("MATCHUPS_CACHE_TTL_SECONDS")
    with timing_span("generate_matchups_for_date.cache_lookup", category="cache", route="/matchups", date=date_str):
        cached = get_cache(cache_key, ttl_seconds)
    if cached is not None:
        if isinstance(cached, list):
            for game in cached:
                if isinstance(game, dict):
                    game.setdefault("cache_hit", True)
                    game.setdefault("cache_key", cache_key)
                    game.setdefault("ttl_seconds", ttl_seconds)
        record_span(
            "generate_matchups_for_date",
            category="route",
            route="/matchups",
            date=date_str,
            cache_status="HIT",
            probability_source="canonical_matchup_win_probability_v2",
            payload_bytes=estimate_payload_bytes(cached),
        )
        record_probability_source("canonical_matchup_win_probability_v2")
        return cached

    with timing_span("_generate_matchups_for_date_uncached", category="route", route="/matchups", date=date_str, cache_status="MISS"):
        matchups = _generate_matchups_for_date_uncached(session, date_str)
    if isinstance(matchups, list):
        for game in matchups:
            if isinstance(game, dict):
                game.setdefault("cache_hit", False)
                game.setdefault("cache_key", cache_key)
                game.setdefault("ttl_seconds", ttl_seconds)
    record_span(
        "generate_matchups_for_date",
        category="route",
        route="/matchups",
        date=date_str,
        cache_status="MISS",
        probability_source="canonical_matchup_win_probability_v2",
        payload_bytes=estimate_payload_bytes(matchups),
    )
    record_probability_source("canonical_matchup_win_probability_v2")
    return set_cache(cache_key, matchups)


__all__ = ["generate_matchups_for_date"]
