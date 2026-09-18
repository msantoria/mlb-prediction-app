"""Atomic snapshot promotion and idempotent Final grading."""
from datetime import date, datetime
import hashlib
import json
from sqlalchemy import select, update
from .predicts_models import PredictsGame, PredictsPlayer, PredictsOutcome
from .predicts_validation import asof, utc, FEATURE_VERSION, number
from .predicts_residuals import TARGETS
from .final_game_snapshots import FinalGameSnapshot


def promote(session, rows, captured):
    if not rows:
        return "empty"
    first = rows[0]
    pk, starts = first["game_pk"], utc(first["game_time"])
    for row in rows:
        asof(row["projection_generated_at"], captured, starts)
        if row["game_pk"] != pk or utc(row["game_time"]) != starts:
            raise ValueError("Mixed games in candidate")
    digest = hashlib.sha256(json.dumps(rows, sort_keys=True, allow_nan=False).encode()).hexdigest()
    dialect = session.get_bind().dialect.name
    if dialect == "postgresql":
        from sqlalchemy.dialects.postgresql import insert
    elif dialect == "sqlite":
        from sqlalchemy.dialects.sqlite import insert
    else:
        raise ValueError("Predicts requires PostgreSQL or SQLite")
    session.execute(insert(PredictsGame).values(game_pk=pk, target_date=date.fromisoformat(first["date"]), starts_at=starts,
        revision=0, updated_at=captured).on_conflict_do_nothing(index_elements=["game_pk"]))
    game = session.execute(select(PredictsGame).where(PredictsGame.game_pk==pk).with_for_update()).scalar_one()
    if game.locked_at is not None or game.starts_at <= captured:
        return "locked"
    if game.input_hash == digest:
        return "unchanged"
    if game.revision > 0 and captured <= game.updated_at:
        return "superseded"
    revision = game.revision + 1
    # A compare-and-swap protects SQLite tests as well as PostgreSQL row locks.
    result = session.execute(update(PredictsGame).where(PredictsGame.game_pk==pk,
        PredictsGame.revision==game.revision, PredictsGame.locked_at.is_(None),
        PredictsGame.starts_at>captured).values(revision=revision, starts_at=starts,
        input_hash=digest, updated_at=captured).execution_options(synchronize_session=False))
    if result.rowcount != 1:
        return "conflict"
    for row in rows:
        session.add(PredictsPlayer(game_pk=pk, revision=revision, player_id=row["player_id"],
            player_type=row["player_type"], as_of=captured, feature_version=FEATURE_VERSION,
            payload={**row, "as_of": captured.isoformat()+"Z", "snapshot_version": revision}))
    session.flush()
    session.expire(game)
    return "captured"


def lock_due(session, now):
    return session.execute(update(PredictsGame).where(PredictsGame.starts_at<=now,
        PredictsGame.locked_at.is_(None)).values(locked_at=now)).rowcount


def _actuals(line, role):
    if role == "pitcher":
        return {"strikeouts": number(line.get("strikeouts"))}
    actual = {k: number(line.get(k)) for k in ("hits", "home_runs")}
    parts = [number(line.get(k)) for k in ("hits", "doubles", "triples", "home_runs")]
    actual["total_bases"] = parts[0]+parts[1]+2*parts[2]+3*parts[3] if all(p is not None for p in parts) else None
    return actual


def grade(session, now, game_pk=None):
    query = select(PredictsPlayer, PredictsGame, FinalGameSnapshot).join(PredictsGame,
        (PredictsPlayer.game_pk==PredictsGame.game_pk)&(PredictsPlayer.revision==PredictsGame.revision)).join(
        FinalGameSnapshot, FinalGameSnapshot.game_pk==PredictsGame.game_pk).outerjoin(
        PredictsOutcome, PredictsOutcome.snapshot_id==PredictsPlayer.id).where(PredictsOutcome.snapshot_id.is_(None))
    if game_pk is not None:
        query = query.where(PredictsGame.game_pk==game_pk)
    graded = 0
    for snapshot, game, final in session.execute(query):
        if snapshot.as_of >= game.starts_at or final.finalized_at > now:
            continue
        official_start = final.payload_json.get("game_datetime")
        if official_start and snapshot.as_of >= utc(official_start):
            continue
        if game.locked_at is None:
            game.locked_at = now
        box = (final.payload_json.get("boxscore") or {}).get(snapshot.payload["team_side"]) or {}
        group = box.get("batters" if snapshot.player_type=="batter" else "pitchers") or []
        line = next((r for r in group if r.get("id")==snapshot.player_id), None)
        actuals = _actuals(line, snapshot.player_type) if line else {}
        metrics = {}
        for metric in TARGETS[snapshot.player_type]:
            actual, baseline = actuals.get(metric), snapshot.payload["baseline"].get(metric)
            adjusted = (snapshot.payload["predictions"].get(metric) or {}).get("adjusted")
            residual = actual-baseline if actual is not None and baseline is not None else None
            metrics[metric] = {"actual": actual, "baseline": baseline, "adjusted": adjusted,
                "residual": residual, "absolute_error": abs(residual) if residual is not None else None,
                "squared_error": residual**2 if residual is not None else None,
                "adjusted_error": actual-adjusted if actual is not None and adjusted is not None else None,
                "result": None if residual is None else "over" if residual>0 else "under" if residual<0 else "equal"}
        values = dict(snapshot_id=snapshot.id, final_snapshot_id=final.id, graded_at=now,
            payload={"status": "graded" if line else "did_not_appear", "metrics": metrics,
                     "prediction_stage": snapshot.payload.get("prediction_stage", "model_projection_baseline"),
                     "decision_board": snapshot.payload.get("decision_board", {}),
                     "source": "final_game_snapshots", "final_snapshot_version": final.snapshot_version})
        if session.get_bind().dialect.name == "postgresql":
            from sqlalchemy.dialects.postgresql import insert
        else:
            from sqlalchemy.dialects.sqlite import insert
        graded += session.execute(insert(PredictsOutcome).values(**values).on_conflict_do_nothing(
            index_elements=["snapshot_id"])).rowcount
    session.flush()
    return graded
