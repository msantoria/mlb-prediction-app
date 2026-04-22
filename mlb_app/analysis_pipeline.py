"""
Daily Matchup Analysis Pipeline
===============================

This module orchestrates data retrieval from MLB Stats and Statcast
sources and computes feature vectors for each scheduled game on a given
date. The pipeline integrates team records, platoon splits, and
pitcher/batter Statcast aggregates to produce a dictionary of features
for each matchup. Model training and prediction logic should build
upon the outputs of this module.

Due to environment restrictions, Statcast data retrieval functions in
``statcast_utils`` raise ``NotImplementedError``. To compute real
statistics, implement those functions to download data from Baseball
Savant. The placeholder functions here will still demonstrate how to
combine available data sources.
"""

from __future__ import annotations

import datetime
from typing import Dict, List

from .data_ingestion import (
    fetch_schedule,
    fetch_team_records,
    fetch_team_splits,
)
from .player_splits import get_player_splits
from .pitcher_analysis import get_pitcher_metrics
from .batter_analysis import get_batter_metrics
from .hitter_profile import compute_hitter_profile
from .pitcher_profile import compute_pitcher_profile
from .environment_profile import compute_environment_profile
from .environment_data import build_environment_context
from .lineup_data import resolve_team_lineup
from .offense_profile_aggregation import build_projected_lineup_offense_profile


def _determine_hand(player_id: int) -> str | None:
    """Placeholder to determine a pitcher's throwing hand ('L' or 'R').

    This is intentionally unresolved until a real MLB Stats API or roster lookup
    is implemented. Returning None is safer than silently defaulting to 'R',
    because split selection should not pretend certainty when hand is unknown.
    """
    # TODO: implement real pitcher hand lookup.
    return None


def generate_daily_matchups(date_str: str) -> List[Dict]:
    """Compute feature dictionaries for each game scheduled on a date.

    Parameters
    ----------
    date_str : str
        Date in ``YYYY-MM-DD`` format for which to generate matchups.

    Returns
    -------
    list of dict
        Each dictionary contains matchup metadata, team records, platoon splits,
        pitcher metrics, and structured hitter/pitcher/environment profiles.
        All profile keys and nested sections are always present. If supporting
        data is unavailable, values remain None and metadata describes provenance
        and readiness.
    """
    target_date = datetime.datetime.strptime(date_str, "%Y-%m-%d").date()
    schedule = fetch_schedule(date_str)
    season = target_date.year
    team_records = {rec["team"]["id"]: rec for rec in fetch_team_records(season)}

    matchups = []

    for game in schedule:
        game_info = {
            "gamePk": game.get("gamePk"),
            "gameDate": game.get("gameDate"),
            "homeTeam": game.get("teams", {}).get("home", {}).get("team", {}).get("name"),
            "awayTeam": game.get("teams", {}).get("away", {}).get("team", {}).get("name"),
        }

        home_team = game.get("teams", {}).get("home", {}).get("team", {}) or {}
        away_team = game.get("teams", {}).get("away", {}).get("team", {}) or {}
        home_team_id = home_team.get("id")
        away_team_id = away_team.get("id")

        home_pitcher = game.get("teams", {}).get("home", {}).get("probablePitcher")
        away_pitcher = game.get("teams", {}).get("away", {}).get("probablePitcher")

        home_pitcher_id = home_pitcher.get("id") if isinstance(home_pitcher, dict) else None
        away_pitcher_id = away_pitcher.get("id") if isinstance(away_pitcher, dict) else None

        home_record = team_records.get(home_team_id, {})
        away_record = team_records.get(away_team_id, {})

        matchup_features: Dict[str, object] = game_info.copy()
        matchup_features.update(
            {
                "homeRecord": {
                    "wins": home_record.get("wins"),
                    "losses": home_record.get("losses"),
                    "runDifferential": home_record.get("runDifferential"),
                },
                "awayRecord": {
                    "wins": away_record.get("wins"),
                    "losses": away_record.get("losses"),
                    "runDifferential": away_record.get("runDifferential"),
                },
            }
        )

        # Placeholder hand logic is intentionally unresolved until real lookup
        # is implemented. Do not silently assume RHP/LHP buckets when hand is unknown.
        home_hand = _determine_hand(home_pitcher_id) if home_pitcher_id else None
        away_hand = _determine_hand(away_pitcher_id) if away_pitcher_id else None

        if away_hand == "R":
            home_vs_pitcher_hand = fetch_team_splits(home_team_id, season, "vsRHP")
            home_split_source = "vsRHP"
        elif away_hand == "L":
            home_vs_pitcher_hand = fetch_team_splits(home_team_id, season, "vsLHP")
            home_split_source = "vsLHP"
        else:
            home_vs_pitcher_hand = {}
            home_split_source = "unknown"

        if home_hand == "R":
            away_vs_pitcher_hand = fetch_team_splits(away_team_id, season, "vsRHP")
            away_split_source = "vsRHP"
        elif home_hand == "L":
            away_vs_pitcher_hand = fetch_team_splits(away_team_id, season, "vsLHP")
            away_split_source = "vsLHP"
        else:
            away_vs_pitcher_hand = {}
            away_split_source = "unknown"

        home_lineup, home_lineup_source = resolve_team_lineup(
            game=game,
            team_id=home_team_id,
            side="home",
            season=season,
        )
        away_lineup, away_lineup_source = resolve_team_lineup(
            game=game,
            team_id=away_team_id,
            side="away",
            season=season,
        )

        home_projected_lineup_offense_profile = build_projected_lineup_offense_profile(
            lineup=home_lineup,
            season=season,
            pitcher_hand=away_hand,
            lineup_source=home_lineup_source,
        )
        away_projected_lineup_offense_profile = build_projected_lineup_offense_profile(
            lineup=away_lineup,
            season=season,
            pitcher_hand=home_hand,
            lineup_source=away_lineup_source,
        )

        matchup_features.update(
            {
                "homeTeamSplit": home_vs_pitcher_hand,
                "awayTeamSplit": away_vs_pitcher_hand,
            }
        )

        home_pitcher_metrics: Dict[str, object] = {}
        away_pitcher_metrics: Dict[str, object] = {}

        if home_pitcher_id:
            try:
                home_pitcher_metrics = get_pitcher_metrics(
                    home_pitcher_id,
                    (target_date - datetime.timedelta(days=365)).isoformat(),
                    date_str,
                )
            except NotImplementedError:
                home_pitcher_metrics = {}

        if away_pitcher_id:
            try:
                away_pitcher_metrics = get_pitcher_metrics(
                    away_pitcher_id,
                    (target_date - datetime.timedelta(days=365)).isoformat(),
                    date_str,
                )
            except NotImplementedError:
                away_pitcher_metrics = {}

        matchup_features["homePitcherMetrics"] = home_pitcher_metrics
        matchup_features["awayPitcherMetrics"] = away_pitcher_metrics

        # Structured pitcher profiles with provenance metadata.
        home_pitcher_profile = compute_pitcher_profile(
            {
                **(home_pitcher_metrics or {}),
                "source_type": "statcast_aggregate" if home_pitcher_metrics else "missing",
                "source_fields_used": sorted(list((home_pitcher_metrics or {}).keys())),
                "data_confidence": "medium" if home_pitcher_metrics else "low",
                "generated_from": "get_pitcher_metrics",
            }
        )
        away_pitcher_profile = compute_pitcher_profile(
            {
                **(away_pitcher_metrics or {}),
                "source_type": "statcast_aggregate" if away_pitcher_metrics else "missing",
                "source_fields_used": sorted(list((away_pitcher_metrics or {}).keys())),
                "data_confidence": "medium" if away_pitcher_metrics else "low",
                "generated_from": "get_pitcher_metrics",
            }
        )

        # Temporary offense profile source: team split data proxy.
        # This is explicitly marked as team-level and not lineup-derived.
        home_team_offense_profile = compute_hitter_profile(
            {
                **(home_vs_pitcher_hand or {}),
                "source_type": "team_split_proxy",
                "source_fields_used": sorted(list((home_vs_pitcher_hand or {}).keys())),
                "data_confidence": "low" if home_split_source == "unknown" else "medium",
                "generated_from": "fetch_team_splits",
                "profile_granularity": "team",
                "is_projected_lineup_derived": False,
                "split_source": home_split_source,
            }
        )
        away_team_offense_profile = compute_hitter_profile(
            {
                **(away_vs_pitcher_hand or {}),
                "source_type": "team_split_proxy",
                "source_fields_used": sorted(list((away_vs_pitcher_hand or {}).keys())),
                "data_confidence": "low" if away_split_source == "unknown" else "medium",
                "generated_from": "fetch_team_splits",
                "profile_granularity": "team",
                "is_projected_lineup_derived": False,
                "split_source": away_split_source,
            }
        )

        venue = game.get("venue", {}) or {}
        environment_context = build_environment_context(game)
        environment_profile = compute_environment_profile(environment_context)

        matchup_features.update(
            {
                "homePitcherProfile": home_pitcher_profile,
                "awayPitcherProfile": away_pitcher_profile,
                "homeTeamOffenseProfile": home_team_offense_profile,
                "awayTeamOffenseProfile": away_team_offense_profile,
                "homeProjectedLineupOffenseProfile": home_projected_lineup_offense_profile,
                "awayProjectedLineupOffenseProfile": away_projected_lineup_offense_profile,
                "environmentProfile": environment_profile,
            }
        )

        matchup_features["homeLineupMetrics"] = {}
        matchup_features["awayLineupMetrics"] = {}

        matchups.append(matchup_features)

    return matchups
