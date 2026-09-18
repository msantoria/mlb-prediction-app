"""Small durable job reports and coverage over the actual Predicts rows."""
from datetime import datetime
from sqlalchemy import select, func
from .database import SharedReportArtifact
from .predicts_models import PredictsGame, PredictsPlayer, PredictsOutcome


def save_status(session, kind, day, payload, now=None):
    now = now or datetime.utcnow()
    if session.get_bind().dialect.name == "postgresql":
        from sqlalchemy.dialects.postgresql import insert
    else:
        from sqlalchemy.dialects.sqlite import insert
    values = dict(artifact_key=f"predicts:{kind}:{day.isoformat()}",
        artifact_type=f"predicts_{kind}", target_date=day, payload_json=payload,
        row_count=payload.get("imported_players", 0), generated_at=now, updated_at=now)
    statement = insert(SharedReportArtifact).values(**values)
    session.execute(statement.on_conflict_do_update(index_elements=["artifact_key"], set_=values))


def get_status(session, kind, day):
    row = session.scalar(select(SharedReportArtifact).where(
        SharedReportArtifact.artifact_key == f"predicts:{kind}:{day.isoformat()}"))
    return {**row.payload_json, "checked_at": row.generated_at.isoformat()+"Z"} if row else None


def coverage(session, today):
    start = today.replace(day=1)
    rows = session.execute(select(PredictsGame.target_date,
        func.count(func.distinct(PredictsGame.game_pk)), func.count(PredictsPlayer.id),
        func.count(PredictsOutcome.snapshot_id)).join(PredictsPlayer,
            (PredictsPlayer.game_pk == PredictsGame.game_pk) &
            (PredictsPlayer.revision == PredictsGame.revision)).outerjoin(
            PredictsOutcome, PredictsOutcome.snapshot_id == PredictsPlayer.id).where(
            PredictsGame.target_date >= start, PredictsGame.target_date <= today
        ).group_by(PredictsGame.target_date)).all()
    counts = {day.isoformat(): {"games": games, "players": players, "graded_players": graded}
              for day, games, players, graded in rows}
    reports = {row.target_date.isoformat(): row.payload_json for row in session.scalars(
        select(SharedReportArtifact).where(SharedReportArtifact.artifact_type == "predicts_backfill",
            SharedReportArtifact.target_date >= start, SharedReportArtifact.target_date <= today))}
    days = []
    for n in range(1, today.day+1):
        day = today.replace(day=n).isoformat()
        report = reports.get(day)
        days.append({"date": day, **counts.get(day, {"games": 0, "players": 0, "graded_players": 0}),
                     "backfill": report})
    return {"start": start.isoformat(), "end": today.isoformat(), "days": days,
            "games": sum(d["games"] for d in days), "players": sum(d["players"] for d in days),
            "graded_players": sum(d["graded_players"] for d in days)}
