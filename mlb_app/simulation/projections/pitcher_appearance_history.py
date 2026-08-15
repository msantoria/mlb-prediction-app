"""Historical MLB pitcher appearance-sequence evidence."""

from __future__ import annotations

from copy import deepcopy
from typing import Any, Mapping, Sequence


SCHEMA_VERSION = (
    "canonical_pitcher_appearance_history_v1"
)


def _identifier(value: Any) -> str | None:
    if value in (None, "") or isinstance(value, bool):
        return None

    normalized = str(value).strip()
    return normalized or None


def _nonnegative_int(value: Any) -> int | None:
    if value in (None, "") or isinstance(value, bool):
        return None

    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return None

    return parsed if parsed >= 0 else None


def _outs(pitching: Mapping[str, Any]) -> int | None:
    direct = _nonnegative_int(
        pitching.get("outs")
    )

    if direct is not None:
        return direct

    innings = pitching.get("inningsPitched")

    if innings in (None, ""):
        return None

    try:
        whole, partial = str(innings).split(".")
        whole_outs = int(whole) * 3
        partial_outs = int(partial)
    except (TypeError, ValueError):
        return None

    if partial_outs not in {0, 1, 2}:
        return None

    return whole_outs + partial_outs


def _team_side(
    game_data: Mapping[str, Any],
    team_id: str,
) -> str | None:
    teams = game_data.get("teams")

    if not isinstance(teams, Mapping):
        return None

    for side in ("away", "home"):
        team = teams.get(side)

        if (
            isinstance(team, Mapping)
            and _identifier(team.get("id"))
            == team_id
        ):
            return side

    return None


def materialize_canonical_pitcher_appearance_history(
    *,
    team_id: Any,
    game_feeds: Any,
    short_start_maximum_outs: int = 6,
    bulk_follower_minimum_outs: int = 9,
) -> dict[str, Any]:
    """
    Aggregate historical appearance sequences from final MLB feeds.

    Short starts and early multi-inning followers are historical role
    evidence. They never assert that the same assignment is planned
    for today's game.
    """

    normalized_team_id = _identifier(team_id)

    if normalized_team_id is None:
        raise ValueError("team_id is required")

    if (
        not isinstance(game_feeds, Sequence)
        or isinstance(game_feeds, (str, bytes))
    ):
        raise TypeError(
            "game_feeds must be a sequence"
        )

    for value, name in (
        (
            short_start_maximum_outs,
            "short_start_maximum_outs",
        ),
        (
            bulk_follower_minimum_outs,
            "bulk_follower_minimum_outs",
        ),
    ):
        if (
            isinstance(value, bool)
            or not isinstance(value, int)
            or value < 0
        ):
            raise ValueError(
                f"{name} must be a non-negative integer"
            )

    evidence = {}
    processed_game_pks = []
    skipped_game_count = 0
    malformed_appearance_count = 0
    detected_pair_count = 0
    detected_pairs = []

    def pitcher_record(pitcher_id: str) -> dict[str, Any]:
        return evidence.setdefault(
            pitcher_id,
            {
                "pitcher_id": pitcher_id,
                "appearance_count": 0,
                "start_count": 0,
                "short_start_count": 0,
                "relief_appearance_count": 0,
                "relief_outs": 0,
                "early_multi_inning_relief_count": 0,
                "bulk_follower_count": 0,
                "games_observed": [],
                "source": (
                    "mlb_stats_final_game_"
                    "appearance_sequence"
                ),
            },
        )

    for feed in game_feeds:
        if not isinstance(feed, Mapping):
            skipped_game_count += 1
            continue

        game_data = feed.get("gameData")
        live_data = feed.get("liveData")

        if (
            not isinstance(game_data, Mapping)
            or not isinstance(live_data, Mapping)
        ):
            skipped_game_count += 1
            continue

        status = game_data.get("status")
        abstract_state = (
            status.get("abstractGameState")
            if isinstance(status, Mapping)
            else None
        )

        if abstract_state not in {None, "Final"}:
            skipped_game_count += 1
            continue

        side = _team_side(
            game_data,
            normalized_team_id,
        )

        if side is None:
            skipped_game_count += 1
            continue

        game_pk = _identifier(
            game_data.get("gamePk")
            or feed.get("gamePk")
        )

        if game_pk is None:
            skipped_game_count += 1
            continue

        boxscore = live_data.get("boxscore")

        if not isinstance(boxscore, Mapping):
            skipped_game_count += 1
            continue

        teams = boxscore.get("teams")
        team_box = (
            teams.get(side)
            if isinstance(teams, Mapping)
            else None
        )

        if not isinstance(team_box, Mapping):
            skipped_game_count += 1
            continue

        ordered_ids = team_box.get("pitchers")
        players = team_box.get("players")

        if (
            not isinstance(ordered_ids, Sequence)
            or isinstance(ordered_ids, (str, bytes))
            or not isinstance(players, Mapping)
        ):
            skipped_game_count += 1
            continue

        appearances = []

        for sequence_index, raw_pitcher_id in enumerate(
            ordered_ids
        ):
            pitcher_id = _identifier(
                raw_pitcher_id
            )

            if pitcher_id is None:
                malformed_appearance_count += 1
                continue

            player = players.get(f"ID{pitcher_id}")

            if not isinstance(player, Mapping):
                malformed_appearance_count += 1
                continue

            stats = player.get("stats")
            pitching = (
                stats.get("pitching")
                if isinstance(stats, Mapping)
                else None
            )

            if not isinstance(pitching, Mapping):
                malformed_appearance_count += 1
                continue

            appearance_outs = _outs(pitching)

            if appearance_outs is None:
                malformed_appearance_count += 1
                continue

            games_started = _nonnegative_int(
                pitching.get("gamesStarted")
            )
            started = (
                games_started == 1
                or sequence_index == 0
            )
            row = pitcher_record(pitcher_id)
            row["appearance_count"] += 1
            row["games_observed"].append(game_pk)

            if started:
                row["start_count"] += 1

                if (
                    appearance_outs
                    <= short_start_maximum_outs
                ):
                    row["short_start_count"] += 1
            else:
                row["relief_appearance_count"] += 1
                row["relief_outs"] += (
                    appearance_outs
                )

            appearances.append({
                "pitcher_id": pitcher_id,
                "sequence_index": sequence_index,
                "started": started,
                "outs": appearance_outs,
            })

        if appearances:
            processed_game_pks.append(game_pk)
        else:
            skipped_game_count += 1
            continue

        if len(appearances) < 2:
            continue

        first = appearances[0]
        second = appearances[1]
        opener_detected = (
            first["started"] is True
            and first["outs"]
            <= short_start_maximum_outs
        )
        bulk_detected = (
            second["started"] is False
            and second["outs"]
            >= bulk_follower_minimum_outs
        )

        if opener_detected and bulk_detected:
            bulk_record = pitcher_record(
                second["pitcher_id"]
            )
            bulk_record[
                "early_multi_inning_relief_count"
            ] += 1
            bulk_record["bulk_follower_count"] += 1
            detected_pair_count += 1
            detected_pairs.append({
                "game_pk": game_pk,
                "opener_id": first["pitcher_id"],
                "opener_outs": first["outs"],
                "bulk_follower_id":
                    second["pitcher_id"],
                "bulk_follower_outs":
                    second["outs"],
                "source": (
                    "mlb_stats_final_game_"
                    "appearance_sequence"
                ),
            })

    records = []

    for pitcher_id in sorted(evidence):
        row = deepcopy(evidence[pitcher_id])
        row["games_observed"] = sorted(
            set(row["games_observed"])
        )
        records.append(row)

    return {
        "schema_version": SCHEMA_VERSION,
        "status": (
            "materialized"
            if processed_game_pks
            else "unavailable"
        ),
        "team_id": normalized_team_id,
        "processed_game_count": len(
            set(processed_game_pks)
        ),
        "processed_game_pks": sorted(
            set(processed_game_pks)
        ),
        "skipped_game_count": skipped_game_count,
        "malformed_appearance_count":
            malformed_appearance_count,
        "pitcher_count": len(records),
        "detected_opener_bulk_pair_count":
            detected_pair_count,
        "detected_opener_bulk_pairs":
            detected_pairs,
        "evidence_by_pitcher_id": evidence,
        "records": records,
        "interpretation": {
            "appearance_order_is_historical": True,
            "short_starts_are_opener_evidence": True,
            "early_length_is_bulk_evidence": True,
            "planned_role_claimed": False,
            "future_assignment_inferred": False,
        },
        "safety_checks": {
            "game_feeds_unchanged": True,
            "database_writes_performed": False,
            "production_authority_changed": False,
        },
        "database_writes_performed": False,
        "production_authority_changed": False,
    }
