"""Deterministic canonical bullpen selection."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Tuple

from .pitcher_lifecycle import (
    CanonicalPitchingDecision,
    CanonicalPitchingDecisionAction,
    CanonicalPitchingDecisionContext,
)


CANONICAL_BULLPEN_SELECTOR_VERSION = (
    "canonical_bullpen_selector_v1"
)


class CanonicalBullpenRole(str, Enum):
    """Baseline bullpen role used by deterministic selection."""

    LONG_RELIEF = "long_relief"
    MIDDLE_RELIEF = "middle_relief"
    SETUP = "setup"
    CLOSER = "closer"


@dataclass(frozen=True)
class CanonicalBullpenPitcher:
    """One bullpen option and its game-usage metadata."""

    pitcher_id: str
    role: CanonicalBullpenRole
    available: bool = True
    appearance_priority: int = 0
    minimum_inning: int = 1
    maximum_inning: int = 99
    maximum_score_margin: int | None = None
    handedness: str | None = None
    fatigue_index: float = 0.0
    consecutive_days_worked: int = 0
    recent_pitch_count: int = 0

    def __post_init__(self) -> None:
        if not self.pitcher_id:
            raise ValueError("pitcher_id is required")

        if not isinstance(self.role, CanonicalBullpenRole):
            raise TypeError(
                "role must be a CanonicalBullpenRole"
            )

        if self.appearance_priority < 0:
            raise ValueError(
                "appearance_priority cannot be negative"
            )

        if self.minimum_inning < 1:
            raise ValueError(
                "minimum_inning must be positive"
            )

        if self.maximum_inning < self.minimum_inning:
            raise ValueError(
                "maximum_inning cannot precede minimum_inning"
            )

        if (
            self.maximum_score_margin is not None
            and self.maximum_score_margin < 0
        ):
            raise ValueError(
                "maximum_score_margin cannot be negative"
            )

        if self.handedness not in (None, "L", "R"):
            raise ValueError(
                "handedness must be L, R, or None"
            )

        if (
            isinstance(self.fatigue_index, bool)
            or not isinstance(
                self.fatigue_index,
                (int, float),
            )
            or not 0.0 <= float(
                self.fatigue_index
            ) <= 1.0
        ):
            raise ValueError(
                "fatigue_index must be between zero and one"
            )

        if (
            isinstance(
                self.consecutive_days_worked,
                bool,
            )
            or not isinstance(
                self.consecutive_days_worked,
                int,
            )
            or self.consecutive_days_worked < 0
        ):
            raise ValueError(
                "consecutive_days_worked must be a "
                "non-negative integer"
            )

        if (
            isinstance(self.recent_pitch_count, bool)
            or not isinstance(
                self.recent_pitch_count,
                int,
            )
            or self.recent_pitch_count < 0
        ):
            raise ValueError(
                "recent_pitch_count must be a "
                "non-negative integer"
            )


@dataclass(frozen=True)
class CanonicalBullpenSelectionContext:
    """Context required to choose one replacement pitcher."""

    pitching_decision: CanonicalPitchingDecision
    game_context: CanonicalPitchingDecisionContext
    bullpen: Tuple[CanonicalBullpenPitcher, ...]
    previously_used_pitcher_ids: Tuple[str, ...] = ()
    upcoming_batter_handedness: Tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not isinstance(
            self.pitching_decision,
            CanonicalPitchingDecision,
        ):
            raise TypeError(
                "pitching_decision must be a "
                "CanonicalPitchingDecision"
            )

        if not isinstance(
            self.game_context,
            CanonicalPitchingDecisionContext,
        ):
            raise TypeError(
                "game_context must be a "
                "CanonicalPitchingDecisionContext"
            )

        if self.pitching_decision.action is not (
            CanonicalPitchingDecisionAction.REPLACE
        ):
            raise ValueError(
                "bullpen selection requires a replace decision"
            )

        pitcher_ids = tuple(
            pitcher.pitcher_id
            for pitcher in self.bullpen
        )

        if len(pitcher_ids) != len(set(pitcher_ids)):
            raise ValueError(
                "bullpen pitcher identifiers must be unique"
            )

        if len(
            self.previously_used_pitcher_ids
        ) != len(set(self.previously_used_pitcher_ids)):
            raise ValueError(
                "previously used pitcher identifiers "
                "must be unique"
            )

        if len(self.upcoming_batter_handedness) > 5:
            raise ValueError(
                "upcoming batter handedness pocket "
                "cannot exceed five hitters"
            )

        if any(
            handedness not in ("L", "R", "S")
            for handedness in (
                self.upcoming_batter_handedness
            )
        ):
            raise ValueError(
                "upcoming batter handedness values "
                "must be L, R, or S"
            )


@dataclass(frozen=True)
class CanonicalBullpenSelection:
    """Deterministic replacement-pitcher selection."""

    pitcher_id: str
    role: CanonicalBullpenRole
    reason: str
    candidate_pitcher_ids: Tuple[str, ...]
    schema_version: str = (
        CANONICAL_BULLPEN_SELECTOR_VERSION
    )

    def __post_init__(self) -> None:
        if not self.pitcher_id:
            raise ValueError("pitcher_id is required")

        if not isinstance(self.role, CanonicalBullpenRole):
            raise TypeError(
                "role must be a CanonicalBullpenRole"
            )

        if not self.reason:
            raise ValueError("reason is required")

        if not self.candidate_pitcher_ids:
            raise ValueError(
                "candidate_pitcher_ids cannot be empty"
            )

        if self.pitcher_id not in self.candidate_pitcher_ids:
            raise ValueError(
                "selected pitcher must be a candidate"
            )

        if self.schema_version != (
            CANONICAL_BULLPEN_SELECTOR_VERSION
        ):
            raise ValueError(
                "unsupported bullpen selector schema"
            )


@dataclass(frozen=True)
class CanonicalBullpenSelector:
    """
    Transparent deterministic bullpen selector.

    Selection is role-aware, leverage-aware, inning-aware, and stable
    under identical inputs. Within the appropriate role tier, explicit
    handedness, fatigue, consecutive-day, and recent-pitch evidence
    calibrate which eligible reliever enters.
    """

    version: str = CANONICAL_BULLPEN_SELECTOR_VERSION

    def __post_init__(self) -> None:
        if self.version != (
            CANONICAL_BULLPEN_SELECTOR_VERSION
        ):
            raise ValueError(
                "unsupported bullpen selector version"
            )

    def select(
        self,
        context: CanonicalBullpenSelectionContext,
    ) -> CanonicalBullpenSelection:
        if not isinstance(
            context,
            CanonicalBullpenSelectionContext,
        ):
            raise TypeError(
                "context must be a "
                "CanonicalBullpenSelectionContext"
            )

        eligible = tuple(
            pitcher
            for pitcher in context.bullpen
            if self._is_eligible(
                pitcher=pitcher,
                context=context,
            )
        )

        if not eligible:
            raise ValueError(
                "no eligible bullpen pitcher is available"
            )

        target_roles = self._target_roles(
            context.game_context
        )

        ranked = tuple(
            sorted(
                eligible,
                key=lambda pitcher: (
                    self._role_rank(
                        pitcher.role,
                        target_roles,
                    ),
                    self._matchup_usage_score(
                        pitcher=pitcher,
                        context=context,
                    ),
                    pitcher.appearance_priority,
                    pitcher.pitcher_id,
                ),
            )
        )

        selected = ranked[0]

        return CanonicalBullpenSelection(
            pitcher_id=selected.pitcher_id,
            role=selected.role,
            reason=self._selection_reason(
                role=selected.role,
                context=context.game_context,
            ),
            candidate_pitcher_ids=tuple(
                pitcher.pitcher_id
                for pitcher in ranked
            ),
        )

    @staticmethod
    def _is_eligible(
        *,
        pitcher: CanonicalBullpenPitcher,
        context: CanonicalBullpenSelectionContext,
    ) -> bool:
        game = context.game_context

        if not pitcher.available:
            return False

        if pitcher.pitcher_id in (
            context.previously_used_pitcher_ids
        ):
            return False

        if pitcher.pitcher_id not in (
            game.available_reliever_ids
        ):
            return False

        if not (
            pitcher.minimum_inning
            <= game.inning
            <= pitcher.maximum_inning
        ):
            return False

        if pitcher.maximum_score_margin is not None:
            margin = abs(
                game.fielding_team_score
                - game.batting_team_score
            )

            if margin > pitcher.maximum_score_margin:
                return False

        return True

    @staticmethod
    def _target_roles(
        context: CanonicalPitchingDecisionContext,
    ) -> Tuple[CanonicalBullpenRole, ...]:
        score_margin = abs(
            context.fielding_team_score
            - context.batting_team_score
        )

        high_leverage = (
            score_margin <= 2
            and (
                context.runners_on_base > 0
                or context.outs <= 1
            )
        )

        if (
            context.inning >= 9
            and context.fielding_team_score
            > context.batting_team_score
            and score_margin <= 3
        ):
            return (
                CanonicalBullpenRole.CLOSER,
                CanonicalBullpenRole.SETUP,
                CanonicalBullpenRole.MIDDLE_RELIEF,
                CanonicalBullpenRole.LONG_RELIEF,
            )

        if context.inning >= 7 and high_leverage:
            return (
                CanonicalBullpenRole.SETUP,
                CanonicalBullpenRole.CLOSER,
                CanonicalBullpenRole.MIDDLE_RELIEF,
                CanonicalBullpenRole.LONG_RELIEF,
            )

        if context.inning <= 5:
            return (
                CanonicalBullpenRole.LONG_RELIEF,
                CanonicalBullpenRole.MIDDLE_RELIEF,
                CanonicalBullpenRole.SETUP,
                CanonicalBullpenRole.CLOSER,
            )

        return (
            CanonicalBullpenRole.MIDDLE_RELIEF,
            CanonicalBullpenRole.LONG_RELIEF,
            CanonicalBullpenRole.SETUP,
            CanonicalBullpenRole.CLOSER,
        )

    @staticmethod
    def _role_rank(
        role: CanonicalBullpenRole,
        target_roles: Tuple[CanonicalBullpenRole, ...],
    ) -> int:
        return target_roles.index(role)

    @staticmethod
    def _matchup_usage_score(
        *,
        pitcher: CanonicalBullpenPitcher,
        context: CanonicalBullpenSelectionContext,
    ) -> float:
        """
        Return a lower-is-better within-role usage score.

        Role suitability remains the primary ordering key. This score
        never allows a handedness preference to replace the correct
        closer, setup, middle, or long-relief tier.

        One or two consecutive days remain usable. Meaningful
        consecutive-day fatigue begins with the third day, while
        explicit fatigue and recent pitch volume contribute gradual
        penalties.
        """

        score = 0.0

        score += 40.0 * float(
            pitcher.fatigue_index
        )

        if pitcher.consecutive_days_worked >= 3:
            score += 18.0 * (
                pitcher.consecutive_days_worked - 2
            )

        score += min(
            25.0,
            0.25 * pitcher.recent_pitch_count,
        )

        pitcher_hand = pitcher.handedness
        pocket = context.upcoming_batter_handedness

        if pitcher_hand is not None and pocket:
            favorable = 0
            unfavorable = 0

            for batter_hand in pocket:
                if batter_hand == "S":
                    # A switch hitter is expected to bat from the
                    # opposite side and is therefore unfavorable to
                    # either conventional pitcher hand.
                    unfavorable += 1
                elif batter_hand == pitcher_hand:
                    favorable += 1
                else:
                    unfavorable += 1

            known = favorable + unfavorable

            if known:
                score += 12.0 * (
                    (unfavorable - favorable)
                    / known
                )

        return round(score, 6)

    @staticmethod
    def _selection_reason(
        *,
        role: CanonicalBullpenRole,
        context: CanonicalPitchingDecisionContext,
    ) -> str:
        if role is CanonicalBullpenRole.CLOSER:
            return "save_situation_closer"

        if role is CanonicalBullpenRole.SETUP:
            return "late_high_leverage_setup"

        if role is CanonicalBullpenRole.LONG_RELIEF:
            return "early_exit_long_relief"

        return "middle_relief_default"


def build_canonical_bullpen_selector(
) -> CanonicalBullpenSelector:
    """Return the default deterministic bullpen selector."""

    return CanonicalBullpenSelector()
