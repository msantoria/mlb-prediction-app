"""Predicts orchestration: expensive work runs in refresh; GETs only read snapshots."""
from collections import Counter
from copy import deepcopy
from datetime import date, datetime, timedelta
from functools import lru_cache
import logging
import os
from sqlalchemy import select, func, inspect
from .database import SharedReportArtifact, create_tables, get_engine, get_session
from .shared_artifacts import model_projection_date_key
from .predicts_models import PredictsGame, PredictsPlayer, PredictsOutcome, PredictsModelRun
from .predicts_sources import collect
from .predicts_snapshots import promote, lock_due, grade
from .predicts_backtest import training_records, evaluate
from .predicts_residuals import fit, adjust, TARGETS
from .predicts_validation import MODEL_VERSION, FEATURE_VERSION
from .predicts_status import coverage, get_status, save_status
from .predicts_decisions import enrich, attach_markets

logger = logging.getLogger(__name__)


@lru_cache(maxsize=2)
def _factory(url):
    engine = get_engine(url)
    create_tables(engine)
    return get_session(engine)


def session_factory():
    return _factory(os.getenv("DATABASE_URL", "sqlite:///mlb.db"))


def refresh(session, target_date, now=None):
    clock = (lambda: now) if now is not None else datetime.utcnow
    now = clock()
    lock_due(session,now)
    graded = grade(session,now)
    # Settlements must survive stale or failed pregame sources.
    session.commit()
    artifact = session.execute(select(SharedReportArtifact).where(
        SharedReportArtifact.artifact_key==model_projection_date_key(target_date.isoformat()))).scalar_one_or_none()
    if artifact is None:
        result = {"status":"unavailable", "reason":"No warmed Model Projections artifact", "graded":graded}
        save_status(session,"refresh",target_date,result,now)
        session.commit()
        return result
    payload = {**artifact.payload_json,"predicts_source_generated_at":artifact.generated_at.isoformat()+"Z"}
    rows,rejected = collect(session,payload,target_date,now)
    if not rows:
        result = {"status":"no_eligible_pregame_games", "date":target_date.isoformat(),
                  "games":{}, "graded":graded, "rejected":rejected}
        save_status(session,"refresh",target_date,result,now); session.commit()
        return result
    records = training_records(session,target_date,now)
    models = {key:fit(values) for key,values in records.items()}
    for model in models.values():
        if model and session.get(PredictsModelRun,model["id"]) is None:
            # Concurrent jobs use insert-on-conflict; immutable models are never rewritten.
            if session.get_bind().dialect.name=="postgresql":
                from sqlalchemy.dialects.postgresql import insert
            else:
                from sqlalchemy.dialects.sqlite import insert
            session.execute(insert(PredictsModelRun).values(id=model["id"],trained_at=now,
                training_cutoff=now,model_version=MODEL_VERSION,payload=model).on_conflict_do_nothing(index_elements=["id"]))
    counts = Counter()
    for pk,players in rows.items():
        for row in players:
            row["predicts_model_version"] = MODEL_VERSION
            row["git_sha"] = os.getenv("RAILWAY_GIT_COMMIT_SHA")
            row["predictions"] = {}
            for metric in TARGETS[row["player_type"]]:
                key = (row["player_type"],metric,row["baseline_model_version"])
                row["predictions"][metric] = adjust(row,metric,models.get(key),records.get(key,[]))
    enrich([row for players in rows.values() for row in players], force=True)
    for pk,players in rows.items():
        captured = clock()
        lock_due(session,captured)
        from .predicts_validation import utc
        if utc(players[0]["game_time"]) <= captured:
            counts["started_during_refresh"] += 1
            continue
        counts[promote(session,players,captured)] += 1
    result = {"status":"ready", "date":target_date.isoformat(),
              "games":dict(counts),"graded":graded,"rejected":rejected}
    save_status(session,"refresh",target_date,result,now); session.commit()
    return result


def refresh_safely(target_date):
    """Shared worker entry point. Failures remain observable without breaking source surfaces."""
    try:
        with session_factory()() as session:
            result = refresh(session,date.fromisoformat(target_date))
        logger.info("Predicts refresh: %s",result)
        return result
    except Exception:
        logger.exception("Predicts refresh failed for %s",target_date)
        return {"status":"source_error","date":target_date}


def grade_safely(game_pk):
    try:
        with session_factory()() as session:
            result = grade(session,datetime.utcnow(),game_pk)
            session.commit()
            return result
    except Exception:
        logger.exception("Predicts Final grading failed for game %s",game_pk)
        return 0


def slate(session,target_date=None,game_pk=None,player_id=None):
    query = select(PredictsPlayer,PredictsGame,PredictsOutcome).join(PredictsGame,
        (PredictsPlayer.game_pk==PredictsGame.game_pk)&(PredictsPlayer.revision==PredictsGame.revision)).outerjoin(
        PredictsOutcome,PredictsOutcome.snapshot_id==PredictsPlayer.id)
    if target_date:
        query = query.where(PredictsGame.target_date==target_date)
    if game_pk:
        query = query.where(PredictsGame.game_pk==game_pk)
    if player_id:
        query = query.where(PredictsPlayer.player_id==player_id)
    now,rows = datetime.utcnow(),[]
    for player,game,outcome in session.execute(query.order_by(PredictsGame.starts_at,PredictsPlayer.player_id)):
        rows.append({**deepcopy(player.payload),"snapshot_id":player.id,
            "locked":game.locked_at is not None or game.starts_at<=now,
            "outcome":{**outcome.payload,"graded_at":outcome.graded_at.isoformat()+"Z"} if outcome else None})
    enrich(rows)
    if rows:
        try:
            from .model_tracker_price_snapshots import ModelTrackerPriceSnapshot
            if inspect(session.connection()).has_table(ModelTrackerPriceSnapshot.__tablename__):
                market_date = target_date or date.fromisoformat(rows[0]["date"])
                market_query = select(ModelTrackerPriceSnapshot).where(
                    ModelTrackerPriceSnapshot.snapshot_date == market_date,
                    ModelTrackerPriceSnapshot.provider == "bet105").order_by(
                        ModelTrackerPriceSnapshot.captured_at.desc())
                attach_markets(rows, list(session.scalars(market_query)))
        except Exception:
            # Price capture is optional. Prediction reads must remain available.
            logger.warning("Predicts market context unavailable", exc_info=True)
    stage_counts = dict(Counter(row["prediction_stage"] for row in rows))
    return {"date":target_date.isoformat() if target_date else None,"records":rows,
            "status":"ready" if rows else "unavailable", "record_count":len(rows),
            "stage_counts":stage_counts,
            "reason":None if rows else "No eligible pregame snapshots have been captured for this selection.",
            "feature_version":FEATURE_VERSION,"model_version":MODEL_VERSION,
            "timing_contract":{
                "before_confirmed_lineup":"Model Projections is the numerical driver and the slate remains a baseline board.",
                "after_confirmed_lineup":"The confirmed nine are re-ranked with frozen projection, opportunity, trend, process and matchup evidence.",
                "numerical_adjustment":"The MLBGPT line changes only when the residual model beats the baseline on a later temporal holdout.",
                "market_context":"Captured Bet105 lines are comparison-only and never model inputs.",
            }}


def health(session,today):
    last = session.scalar(select(func.max(PredictsPlayer.as_of)))
    return {"last_capture":last.isoformat()+"Z" if last else None,
        "cold_start":session.scalar(select(func.count()).select_from(PredictsModelRun).where(
            PredictsModelRun.model_version==MODEL_VERSION))==0,
        "minimum_training_rows":100,"minimum_holdout_rows":30,"minimum_game_dates":14,
        "recent_evaluation":evaluate(session,today-timedelta(days=30),today),
        "today_refresh":get_status(session,"refresh",today),
        "month_coverage":coverage(session,today)}
