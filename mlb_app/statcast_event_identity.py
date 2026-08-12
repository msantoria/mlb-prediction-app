"""Canonical pitch identity and duplicate-safe Statcast reads.

MLB identifies a pitch inside a game by ``game_pk + at_bat_number +
pitch_number``.  Older application loads did not always populate those fields,
so legacy rows are only used for pitcher/date scopes that have no canonical
rows at all.
"""

from __future__ import annotations

from typing import Any, Iterable, List, Sequence, Tuple

from sqlalchemy import and_, case, func, or_
from sqlalchemy.orm import Session

from .database import StatcastEvent


NULLISH_TEXT = {"", "nan", "none", "null", "na", "n/a"}


def has_canonical_pitch_identity(event: StatcastEvent) -> bool:
    return (
        event.game_pk is not None
        and event.at_bat_number is not None
        and event.pitch_number is not None
    )


def canonical_pitch_key(event: StatcastEvent) -> Tuple[Any, ...] | None:
    if not has_canonical_pitch_identity(event):
        return None
    return (event.game_pk, event.at_bat_number, event.pitch_number)


def _clean_text(value: Any) -> Any:
    if value is None:
        return None
    normalized = str(value).strip().lower()
    return None if normalized in NULLISH_TEXT else normalized


def _legacy_pitch_key(event: StatcastEvent) -> Tuple[Any, ...]:
    """Best available identity for rows created before MLB ordering was stored."""

    return (
        event.game_date,
        event.pitcher_id,
        event.batter_id,
        _clean_text(event.pitch_type),
        _clean_text(event.description),
        _clean_text(event.events),
        event.inning,
        _clean_text(event.inning_topbot),
        event.outs_when_up,
        event.balls,
        event.strikes,
        event.release_speed,
        event.release_spin_rate,
        event.pfx_x,
        event.pfx_z,
        event.plate_x,
        event.plate_z,
        event.launch_speed,
        event.launch_angle,
        _clean_text(event.stand),
        _clean_text(event.p_throws),
    )


def _scope(event: StatcastEvent) -> Tuple[Any, ...]:
    return (event.game_date, event.pitcher_id)


def _event_quality(event: StatcastEvent) -> Tuple[int, int]:
    fields = (
        event.pitch_type,
        event.description,
        event.events,
        event.release_speed,
        event.release_spin_rate,
        event.pfx_x,
        event.pfx_z,
        event.plate_x,
        event.plate_z,
        event.launch_speed,
        event.launch_angle,
        event.estimated_woba_using_speedangle,
        event.estimated_ba_using_speedangle,
        event.stand,
        event.p_throws,
        event.home_team,
        event.away_team,
    )
    populated = sum(
        value is not None and (not isinstance(value, str) or _clean_text(value) is not None)
        for value in fields
    )
    return populated, int(event.id or 0)


def dedupe_statcast_events(events: Iterable[StatcastEvent]) -> List[StatcastEvent]:
    """Return one best row per pitch and suppress shadowed legacy copies.

    If a pitcher/date has canonical MLB pitch identities, incomplete legacy
    rows from that same scope are ignored.  This prevents old overlapping ETL
    snapshots from being added to the canonical game rows.
    """

    rows = list(events)
    canonical_scopes = {_scope(event) for event in rows if has_canonical_pitch_identity(event)}
    selected: dict[Tuple[Any, ...], Tuple[int, StatcastEvent]] = {}

    for position, event in enumerate(rows):
        canonical = canonical_pitch_key(event)
        if canonical is None and _scope(event) in canonical_scopes:
            continue
        key = ("canonical", *canonical) if canonical is not None else ("legacy", *_legacy_pitch_key(event))
        existing = selected.get(key)
        if existing is None:
            selected[key] = (position, event)
            continue
        if _event_quality(event) > _event_quality(existing[1]):
            selected[key] = (existing[0], event)

    return [event for _, event in sorted(selected.values(), key=lambda item: item[0])]


def canonical_event_ids_subquery(session: Session, *filters: Any):
    """Return IDs for the richest row at each canonical MLB pitch identity."""

    text_quality = sum(
        case(
            (
                and_(
                    column.isnot(None),
                    func.lower(func.trim(column)).notin_(tuple(NULLISH_TEXT)),
                ),
                1,
            ),
            else_=0,
        )
        for column in (StatcastEvent.pitch_type, StatcastEvent.description, StatcastEvent.events)
    )
    numeric_quality = sum(
        case((column.isnot(None), 1), else_=0)
        for column in (
            StatcastEvent.release_speed,
            StatcastEvent.release_spin_rate,
            StatcastEvent.pfx_x,
            StatcastEvent.pfx_z,
            StatcastEvent.plate_x,
            StatcastEvent.plate_z,
            StatcastEvent.launch_speed,
            StatcastEvent.launch_angle,
            StatcastEvent.estimated_woba_using_speedangle,
            StatcastEvent.estimated_ba_using_speedangle,
        )
    )
    quality = text_quality + numeric_quality
    ranked = (
        session.query(
            StatcastEvent.id.label("event_id"),
            func.row_number()
            .over(
                partition_by=(
                    StatcastEvent.game_pk,
                    StatcastEvent.at_bat_number,
                    StatcastEvent.pitch_number,
                ),
                order_by=(quality.desc(), StatcastEvent.id.desc()),
            )
            .label("pitch_rank"),
        )
        .filter(
            *filters,
            StatcastEvent.game_pk.isnot(None),
            StatcastEvent.at_bat_number.isnot(None),
            StatcastEvent.pitch_number.isnot(None),
        )
        .subquery()
    )
    return (
        session.query(ranked.c.event_id)
        .filter(ranked.c.pitch_rank == 1)
        .subquery()
    )


def load_canonical_statcast_events(
    session: Session,
    *filters: Any,
    order_by: Sequence[Any] | None = None,
) -> Tuple[List[StatcastEvent], dict[str, int]]:
    """Load duplicate-safe events plus warehouse quality diagnostics."""

    raw_query = session.query(StatcastEvent).filter(*filters)
    raw_rows = int(raw_query.with_entities(func.count(StatcastEvent.id)).scalar() or 0)
    complete_rows = int(
        raw_query.with_entities(func.count(StatcastEvent.id))
        .filter(
            StatcastEvent.game_pk.isnot(None),
            StatcastEvent.at_bat_number.isnot(None),
            StatcastEvent.pitch_number.isnot(None),
        )
        .scalar()
        or 0
    )

    ids = canonical_event_ids_subquery(session, *filters)
    canonical_query = session.query(StatcastEvent).join(ids, StatcastEvent.id == ids.c.event_id)
    if order_by:
        canonical_query = canonical_query.order_by(*order_by)
    canonical = canonical_query.all()

    # Preserve genuinely legacy-only dates, but never add legacy snapshots on
    # top of canonical rows for the same pitcher and date.
    legacy: List[StatcastEvent] = []
    if complete_rows == 0:
        legacy = dedupe_statcast_events(raw_query.all())
    elif complete_rows < raw_rows:
        canonical_scopes = (
            session.query(
                StatcastEvent.game_date.label("game_date"),
                StatcastEvent.pitcher_id.label("pitcher_id"),
            )
            .filter(
                *filters,
                StatcastEvent.game_pk.isnot(None),
                StatcastEvent.at_bat_number.isnot(None),
                StatcastEvent.pitch_number.isnot(None),
            )
            .distinct()
            .subquery()
        )
        legacy_rows = (
            raw_query.outerjoin(
                canonical_scopes,
                and_(
                    canonical_scopes.c.game_date == StatcastEvent.game_date,
                    canonical_scopes.c.pitcher_id == StatcastEvent.pitcher_id,
                ),
            )
            .filter(
                or_(
                    StatcastEvent.game_pk.is_(None),
                    StatcastEvent.at_bat_number.is_(None),
                    StatcastEvent.pitch_number.is_(None),
                ),
                canonical_scopes.c.game_date.is_(None),
            )
            .all()
        )
        legacy = dedupe_statcast_events(legacy_rows)

    events = canonical + legacy
    if order_by:
        # SQL ordering applies to canonical rows; legacy-only rows are rare and
        # are sorted deterministically for downstream calculations.
        events.sort(key=lambda event: (event.game_date, int(event.id or 0)))

    diagnostics = {
        "raw_rows": raw_rows,
        "complete_identity_rows": complete_rows,
        "incomplete_identity_rows": max(raw_rows - complete_rows, 0),
        "canonical_pitch_rows": len(canonical),
        "legacy_pitch_rows": len(legacy),
        "duplicate_rows_removed": max(raw_rows - len(events), 0),
    }
    return events, diagnostics
