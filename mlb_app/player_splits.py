"""
Player Splits Utilities
=======================

This module defines helper functions to retrieve hitter splits
against left- and right-handed pitching from the MLB Stats API.
The splits correspond to the situation codes ``vl`` (versus
left-handed pitching) and ``vr`` (versus right-handed pitching).

The primary entry point is :func:`fetch_player_splits`, which
fetches per-player hitting stats for a given season.  This data
mirrors the functionality of Layer 14 in the original project,
but is simplified to focus on the key numeric metrics used in
matchup analysis.

Functions
---------
fetch_player_splits(player_ids, season)
    Retrieve season-long hitting stats for each player in
    ``player_ids``, split by pitcher handedness.

Note
----
The MLB Stats API supports fetching multiple players at once by
specifying a comma-separated list of IDs in the ``personIds``
query parameter.  The ``hydrate=stats`` parameter instructs the
API to include statistics in the response.  See the Stats API
documentation for further details.
"""

from __future__ import annotations

from typing import Dict, List, Optional

import requests


def fetch_player_splits(player_ids: List[int], season: int) -> List[Dict[str, float]]:
    """Fetch player hitting splits vs left- and right-handed pitching.

    This function retrieves hitting statistics for each player in
    ``player_ids`` for the specified season.  It returns two
    records per player – one for ``vl`` (versus left-handed
    pitchers) and one for ``vr`` (versus right-handed pitchers) –
    containing commonly used rate and counting stats.  If the API
    request fails or no data is available, an empty list is
    returned.

    Parameters
    ----------
    player_ids : list of int
        List of MLBAM identifiers for the players.
    season : int
        Season year (e.g., 2025).

    Returns
    -------
    list of dict
        A list of dictionaries.  Each dictionary includes the
        ``player_id``, ``player_name``, ``season``, ``split`` (either
        ``vl`` or ``vr``) and numeric hitting stats such as plate
        appearances, hits, home runs, on-base percentage (``obp``),
        slugging percentage (``slg``) and OPS (``ops``).
    """
    if not player_ids:
        return []

    # Construct comma-separated list of IDs
    ids_str = ",".join(str(pid) for pid in player_ids)
    # The hydrate string requests stat splits for the season by
    # specifying the situation codes.  See Stats API docs for
    # details.  We request hitting group and statSplits type.
    hydrate_value = (
        f"stats(group=[hitting],type=[statSplits],sitCodes=[vl,vr],season={season})"
    )
    params = {
        "personIds": ids_str,
        "hydrate": hydrate_value,
    }
    url = "https://statsapi.mlb.com/api/v1/people"
    try:
        resp = requests.get(url, params=params, timeout=30)
        resp.raise_for_status()
    except requests.RequestException:
        return []

    data = resp.json()
    results: List[Dict[str, float]] = []
    for person in data.get("people", []):
        pid = person.get("id")
        first = person.get("firstName", "")
        last = person.get("lastName", "")
        player_name = f"{first} {last}".strip()
        stats_list = person.get("stats", [])
        if not stats_list:
            continue
        splits = stats_list[0].get("splits", [])
        for split_entry in splits:
            split_info = split_entry.get("split", {}) or {}
            split_code = (
                split_info.get("code")
                or split_info.get("value")
                or split_entry.get("sitCode")
                or split_entry.get("splitCode")
            )

            # MLB Stats API responses can vary slightly by endpoint/version.
            # Normalize common split descriptions back to the vL/vR codes used
            # throughout the app.
            split_label = str(
                split_info.get("description")
                or split_info.get("label")
                or split_info.get("type")
                or ""
            ).lower()

            if split_code not in {"vl", "vr"}:
                if "vs left" in split_label or "vs lhp" in split_label or "left" in split_label:
                    split_code = "vl"
                elif "vs right" in split_label or "vs rhp" in split_label or "right" in split_label:
                    split_code = "vr"

            # Only process 'vl' and 'vr'. Other codes are ignored.
            if split_code not in {"vl", "vr"}:
                continue

            stat = split_entry.get("stat", {})
            # Keys to extract; similar to team splits but per-player.
            numeric_keys = [
                "plateAppearances",
                "atBats",
                "hits",
                "doubles",
                "triples",
                "homeRuns",
                "runs",
                "rbi",
                "baseOnBalls",
                "strikeOuts",
                "hitByPitch",
                "stolenBases",
                "caughtStealing",
                "avg",
                "obp",
                "slg",
                "ops",
            ]
            row: Dict[str, float] = {
                "player_id": pid,
                "player_name": player_name,
                "season": season,
                "split": split_code,
            }
            for k in numeric_keys:
                try:
                    row[k] = float(stat.get(k, 0))
                except (TypeError, ValueError):
                    row[k] = 0.0

            # Add normalized aliases consumed by hitter profile builders.
            row["k_pct"] = (
                row["strikeOuts"] / row["plateAppearances"]
                if row.get("plateAppearances") else None
            )
            row["bb_pct"] = (
                row["baseOnBalls"] / row["plateAppearances"]
                if row.get("plateAppearances") else None
            )
            row["iso"] = (
                row["slg"] - row["avg"]
                if row.get("slg") is not None and row.get("avg") is not None
                else None
            )

            results.append(row)
    return results
