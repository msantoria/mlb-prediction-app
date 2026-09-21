"""Canonical trial result with trial-owned derived pitching state."""

from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Dict, Tuple

from mlb_app.simulation.box_score import (
    PitcherBoxScore,
    ReducedBoxScore,
)

from .contracts import CanonicalGameResult
from .defensive_event_authority import (
    CanonicalDefensiveEventAuthorityRecord,
)
from .earned_run_reconstruction import (
    CanonicalPitcherRunLine,
)


@dataclass(frozen=True)
class CanonicalExecutedTrial:
    """
    One completed canonical game plus trial-owned derived state.

    The game remains a pure immutable event result. Pitcher run
    reconstruction is carried separately because it is produced by
    the trial-owned pitching manager.
    """

    game: CanonicalGameResult
    reconstructed_pitcher_run_lines: Tuple[
        CanonicalPitcherRunLine,
        ...,
    ] = ()
    earned_run_reconstruction_complete: bool = False
    defensive_event_authority_records: Tuple[
        CanonicalDefensiveEventAuthorityRecord,
        ...,
    ] = ()

    def __post_init__(self) -> None:
        if not isinstance(
            self.game,
            CanonicalGameResult,
        ):
            raise TypeError(
                "game must be a CanonicalGameResult"
            )

        if any(
            not isinstance(
                line,
                CanonicalPitcherRunLine,
            )
            for line in self.reconstructed_pitcher_run_lines
        ):
            raise TypeError(
                "reconstructed pitcher lines must use "
                "CanonicalPitcherRunLine"
            )

        pitcher_ids = tuple(
            line.pitcher_id
            for line in self.reconstructed_pitcher_run_lines
        )

        if len(pitcher_ids) != len(set(pitcher_ids)):
            raise ValueError(
                "reconstructed pitcher identifiers "
                "must be unique"
            )

        if not isinstance(
            self.earned_run_reconstruction_complete,
            bool,
        ):
            raise TypeError(
                "earned_run_reconstruction_complete "
                "must be a boolean"
            )

        if any(
            not isinstance(
                record,
                CanonicalDefensiveEventAuthorityRecord,
            )
            for record
            in self.defensive_event_authority_records
        ):
            raise TypeError(
                "defensive event authority records must use "
                "CanonicalDefensiveEventAuthorityRecord"
            )


def overlay_reconstructed_pitcher_run_lines(
    *,
    box_score: ReducedBoxScore,
    run_lines: Tuple[
        CanonicalPitcherRunLine,
        ...,
    ],
) -> ReducedBoxScore:
    """
    Replace reducer run attribution with reconstructed responsibility.

    Appearance statistics remain reducer-derived. Every pitcher line is
    marked reconstructed, including pitchers with zero charged runs.
    """

    if not isinstance(
        box_score,
        ReducedBoxScore,
    ):
        raise TypeError(
            "box_score must be a ReducedBoxScore"
        )

    if any(
        not isinstance(line, CanonicalPitcherRunLine)
        for line in run_lines
    ):
        raise TypeError(
            "run_lines must contain "
            "CanonicalPitcherRunLine values"
        )

    reconstructed: Dict[
        str,
        CanonicalPitcherRunLine,
    ] = {
        line.pitcher_id: line
        for line in run_lines
    }

    updated_pitchers = []

    for pitcher in box_score.pitchers:
        line = reconstructed.pop(
            pitcher.player_id,
            None,
        )

        updated_pitchers.append(
            replace(
                pitcher,
                runs_allowed=(
                    line.runs_allowed
                    if line is not None
                    else 0
                ),
                earned_runs=(
                    line.earned_runs
                    if line is not None
                    else 0
                ),
                earned_run_status="reconstructed",
            )
        )

    if reconstructed:
        missing_ids = ", ".join(
            sorted(reconstructed)
        )
        raise ValueError(
            "reconstructed pitcher line has no "
            f"box-score appearance: {missing_ids}"
        )

    return replace(
        box_score,
        pitchers=tuple(updated_pitchers),
    )
