"""Source observed canonical defensive distributions from Statcast."""

from __future__ import annotations

import datetime as dt
import hashlib
import json
from collections import Counter
from dataclasses import dataclass
from typing import Any, Iterable, Mapping, Tuple

from .defensive_distribution_backtest import (
    CanonicalObservedDefensiveDistribution,
)


CANONICAL_STATCAST_DEFENSIVE_DISTRIBUTION_SOURCE_VERSION = (
    "canonical_statcast_defensive_distribution_source_v1"
)

_STATCAST_TO_CANONICAL_EVENT = {
    "single": "single",
    "double": "double",
    "triple": "triple",
    "field_error": "reached_on_error",
    "field_out": "out",
    "force_out": "out",
    "fielders_choice_out": "out",
    "grounded_into_double_play": (
        "ground_ball_double_play"
    ),
    "double_play": "ground_ball_double_play",
    "fielders_choice": (
        "ground_ball_fielders_choice"
    ),
    "sac_fly": "sacrifice_fly",
}

_EXCLUDED_TERMINAL_EVENTS = frozenset(
    {
        "home_run",
        "strikeout",
        "strikeout_double_play",
        "walk",
        "intent_walk",
        "hit_by_pitch",
        "catcher_interf",
        "sac_bunt",
        "triple_play",
    }
)

CountPairs = Tuple[Tuple[str, int], ...]


def _value(row: Any, field_name: str) -> Any:
    if isinstance(row, Mapping):
        return row.get(field_name)
    return getattr(row, field_name, None)


def _date(value: Any, field_name: str) -> dt.date:
    if isinstance(value, dt.datetime):
        return value.date()
    if isinstance(value, dt.date):
        return value

    try:
        return dt.date.fromisoformat(str(value)[:10])
    except (TypeError, ValueError) as exc:
        raise ValueError(
            f"{field_name} must be an ISO date"
        ) from exc


def _positive_integer(
    value: Any,
    field_name: str,
) -> int:
    if isinstance(value, bool):
        raise ValueError(
            f"{field_name} must be a positive integer"
        )

    try:
        parsed = int(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(
            f"{field_name} must be a positive integer"
        ) from exc

    if parsed <= 0:
        raise ValueError(
            f"{field_name} must be a positive integer"
        )

    return parsed


def _event(value: Any) -> str | None:
    if value is None:
        return None

    normalized = str(value).strip().lower()

    if normalized in {
        "",
        "nan",
        "none",
        "null",
    }:
        return None

    return normalized


def _validate_counts(
    values: CountPairs,
    field_name: str,
) -> None:
    keys = tuple(key for key, _ in values)

    if keys != tuple(sorted(keys)):
        raise ValueError(
            f"{field_name} must be sorted"
        )
    if len(keys) != len(set(keys)):
        raise ValueError(
            f"{field_name} keys must be unique"
        )
    if any(
        not key or count <= 0
        for key, count in values
    ):
        raise ValueError(
            f"{field_name} requires non-empty keys "
            "and positive counts"
        )


@dataclass(frozen=True)
class CanonicalStatcastDefensiveDistributionSource:
    """Auditable observed defensive-distribution source."""

    window_start: str
    window_end: str
    through_date: str
    source_row_count: int
    terminal_row_count: int
    nonterminal_row_count: int
    duplicate_terminal_row_count: int
    excluded_event_counts: CountPairs
    unmapped_event_counts: CountPairs
    digest: str
    observed: CanonicalObservedDefensiveDistribution
    schema_version: str = (
        CANONICAL_STATCAST_DEFENSIVE_DISTRIBUTION_SOURCE_VERSION
    )

    def __post_init__(self) -> None:
        start = _date(
            self.window_start,
            "window_start",
        )
        end = _date(
            self.window_end,
            "window_end",
        )
        through = _date(
            self.through_date,
            "through_date",
        )

        if end < start:
            raise ValueError(
                "window_end must not precede window_start"
            )
        if end > through:
            raise ValueError(
                "window_end must not exceed through_date"
            )
        if self.source_row_count <= 0:
            raise ValueError(
                "source_row_count must be positive"
            )
        if self.terminal_row_count <= 0:
            raise ValueError(
                "terminal_row_count must be positive"
            )
        if self.nonterminal_row_count < 0:
            raise ValueError(
                "nonterminal_row_count cannot be negative"
            )
        if self.duplicate_terminal_row_count < 0:
            raise ValueError(
                "duplicate_terminal_row_count cannot "
                "be negative"
            )
        if (
            self.terminal_row_count
            + self.nonterminal_row_count
            != self.source_row_count
        ):
            raise ValueError(
                "source row counts must reconcile"
            )

        _validate_counts(
            self.excluded_event_counts,
            "excluded_event_counts",
        )
        _validate_counts(
            self.unmapped_event_counts,
            "unmapped_event_counts",
        )

        classified_terminal_count = (
            self.observed.observation_count
            + sum(
                count
                for _, count
                in self.excluded_event_counts
            )
            + sum(
                count
                for _, count
                in self.unmapped_event_counts
            )
            + self.duplicate_terminal_row_count
        )
        if classified_terminal_count != (
            self.terminal_row_count
        ):
            raise ValueError(
                "terminal classifications must reconcile"
            )

        if len(self.digest) != 64:
            raise ValueError(
                "digest must be a SHA-256 hex digest"
            )
        try:
            int(self.digest, 16)
        except ValueError as exc:
            raise ValueError(
                "digest must be a SHA-256 hex digest"
            ) from exc

        if self.schema_version != (
            CANONICAL_STATCAST_DEFENSIVE_DISTRIBUTION_SOURCE_VERSION
        ):
            raise ValueError(
                "unsupported Statcast defensive "
                "distribution source version"
            )

    def to_diagnostics(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "status": "ready",
            "ready": True,
            "window_start": self.window_start,
            "window_end": self.window_end,
            "through_date": self.through_date,
            "source_row_count": self.source_row_count,
            "terminal_row_count": self.terminal_row_count,
            "nonterminal_row_count": (
                self.nonterminal_row_count
            ),
            "duplicate_terminal_row_count": (
                self.duplicate_terminal_row_count
            ),
            "included_observation_count": (
                self.observed.observation_count
            ),
            "excluded_event_counts": dict(
                self.excluded_event_counts
            ),
            "unmapped_event_counts": dict(
                self.unmapped_event_counts
            ),
            "digest": self.digest,
            "observed": self.observed.to_diagnostics(),
            "database_accessed": False,
            "network_accessed": False,
            "measurement_only": True,
            "activation_permitted": False,
            "production_authority_changed": False,
        }


def source_statcast_defensive_distribution(
    rows: Iterable[Any],
    *,
    window_start: str,
    window_end: str,
    through_date: str,
) -> CanonicalStatcastDefensiveDistributionSource:
    """Canonicalize caller-owned Statcast terminal rows."""

    if isinstance(rows, (str, bytes, Mapping)):
        raise TypeError(
            "rows must be an iterable of Statcast records"
        )

    start = _date(window_start, "window_start")
    end = _date(window_end, "window_end")
    through = _date(through_date, "through_date")

    if end < start:
        raise ValueError(
            "window_end must not precede window_start"
        )
    if end > through:
        raise ValueError(
            "window_end must not exceed through_date"
        )

    values = tuple(rows)

    if not values:
        raise ValueError(
            "rows must contain Statcast records"
        )

    terminal_by_identity: dict[
        tuple[int, int],
        dict[str, object],
    ] = {}
    terminal_row_count = 0
    nonterminal_row_count = 0
    duplicate_terminal_row_count = 0

    for row in values:
        game_date = _date(
            _value(row, "game_date"),
            "game_date",
        )

        if not start <= game_date <= end:
            raise ValueError(
                "Statcast row game_date must fall "
                "within source window"
            )
        if game_date > through:
            raise ValueError(
                "Statcast row exceeds through_date"
            )

        event_name = _event(
            _value(row, "events")
        )

        if event_name is None:
            nonterminal_row_count += 1
            continue

        terminal_row_count += 1
        game_pk = _positive_integer(
            _value(row, "game_pk"),
            "game_pk",
        )
        at_bat_number = _positive_integer(
            _value(row, "at_bat_number"),
            "at_bat_number",
        )
        identity = (
            game_pk,
            at_bat_number,
        )
        terminal = {
            "game_date": game_date.isoformat(),
            "game_pk": game_pk,
            "at_bat_number": at_bat_number,
            "event": event_name,
        }

        existing = terminal_by_identity.get(identity)

        if existing is None:
            terminal_by_identity[identity] = terminal
            continue

        if existing == terminal:
            duplicate_terminal_row_count += 1
            continue

        raise ValueError(
            "conflicting terminal Statcast events "
            f"for identity {identity}"
        )

    if terminal_row_count == 0:
        raise ValueError(
            "rows contain no terminal Statcast events"
        )

    final_counts: Counter[str] = Counter()
    excluded_counts: Counter[str] = Counter()
    unmapped_counts: Counter[str] = Counter()

    canonical_terminals = tuple(
        sorted(
            terminal_by_identity.values(),
            key=lambda value: (
                value["game_date"],
                value["game_pk"],
                value["at_bat_number"],
            ),
        )
    )

    for terminal in canonical_terminals:
        event_name = str(terminal["event"])
        canonical = _STATCAST_TO_CANONICAL_EVENT.get(
            event_name
        )

        if canonical is not None:
            final_counts[canonical] += 1
        elif event_name in _EXCLUDED_TERMINAL_EVENTS:
            excluded_counts[event_name] += 1
        else:
            unmapped_counts[event_name] += 1

    if not final_counts:
        raise ValueError(
            "source window contains no comparable "
            "defensive observations"
        )

    payload = {
        "schema_version": (
            CANONICAL_STATCAST_DEFENSIVE_DISTRIBUTION_SOURCE_VERSION
        ),
        "window_start": start.isoformat(),
        "window_end": end.isoformat(),
        "through_date": through.isoformat(),
        "terminal_events": canonical_terminals,
    }
    digest = hashlib.sha256(
        json.dumps(
            payload,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()

    source_identifier = (
        "statcast:defensive:"
        f"{start.isoformat()}:"
        f"{end.isoformat()}:"
        f"through:{through.isoformat()}:"
        f"{digest}"
    )
    observed = CanonicalObservedDefensiveDistribution(
        source_identifier=source_identifier,
        observation_count=sum(final_counts.values()),
        final_event_type_counts=tuple(
            sorted(final_counts.items())
        ),
    )

    return CanonicalStatcastDefensiveDistributionSource(
        window_start=start.isoformat(),
        window_end=end.isoformat(),
        through_date=through.isoformat(),
        source_row_count=len(values),
        terminal_row_count=terminal_row_count,
        nonterminal_row_count=nonterminal_row_count,
        duplicate_terminal_row_count=(
            duplicate_terminal_row_count
        ),
        excluded_event_counts=tuple(
            sorted(excluded_counts.items())
        ),
        unmapped_event_counts=tuple(
            sorted(unmapped_counts.items())
        ),
        digest=digest,
        observed=observed,
    )
