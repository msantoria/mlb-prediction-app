"""Additive Predicts tables; canonical players, pitches and finals remain authoritative."""
from sqlalchemy import Column, Date, DateTime, ForeignKey, Index, Integer, JSON, String, UniqueConstraint, event
from .database import Base


class PredictsGame(Base):
    __tablename__ = "predicts_game_snapshots"
    game_pk = Column(Integer, primary_key=True, autoincrement=False)
    target_date = Column(Date, nullable=False, index=True)
    starts_at = Column(DateTime, nullable=False)
    revision = Column(Integer, nullable=False, default=0)
    locked_at = Column(DateTime)
    input_hash = Column(String(64))
    updated_at = Column(DateTime, nullable=False)


class PredictsPlayer(Base):
    __tablename__ = "predicts_player_snapshots"
    id = Column(Integer, primary_key=True)
    game_pk = Column(Integer, ForeignKey("predicts_game_snapshots.game_pk"), nullable=False)
    revision = Column(Integer, nullable=False)
    player_id = Column(Integer, nullable=False, index=True)
    player_type = Column(String(16), nullable=False)
    as_of = Column(DateTime, nullable=False)
    feature_version = Column(String(64), nullable=False)
    payload = Column(JSON, nullable=False)
    __table_args__ = (
        UniqueConstraint("game_pk", "revision", "player_id", "player_type", name="uq_predicts_player_revision"),
        Index("ix_predicts_point_in_time", "game_pk", "player_id", "as_of", "feature_version"),
    )


class PredictsOutcome(Base):
    __tablename__ = "predicts_outcomes"
    snapshot_id = Column(Integer, ForeignKey("predicts_player_snapshots.id"), primary_key=True)
    final_snapshot_id = Column(Integer, ForeignKey("final_game_snapshots.id"), nullable=False)
    graded_at = Column(DateTime, nullable=False, index=True)
    payload = Column(JSON, nullable=False)


class PredictsModelRun(Base):
    __tablename__ = "predicts_model_runs"
    id = Column(String(64), primary_key=True)
    trained_at = Column(DateTime, nullable=False)
    training_cutoff = Column(DateTime, nullable=False)
    model_version = Column(String(64), nullable=False)
    payload = Column(JSON, nullable=False)


def _immutable(*_):
    raise ValueError("Predicts historical records are append-only")


for model in (PredictsPlayer, PredictsOutcome, PredictsModelRun):
    event.listen(model, "before_update", _immutable)
    event.listen(model, "before_delete", _immutable)

# Database enforcement also covers bulk SQL and scripts that bypass the ORM.
from sqlalchemy import DDL
for model in (PredictsPlayer, PredictsOutcome, PredictsModelRun):
    name = model.__tablename__
    for operation in ("UPDATE", "DELETE"):
        trigger = f"{name}_deny_{operation.lower()}"
        event.listen(model.__table__, "after_create", DDL(
            f"CREATE TRIGGER {trigger} BEFORE {operation} ON {name} "
            "BEGIN SELECT RAISE(ABORT, 'Predicts records are append-only'); END"
        ).execute_if(dialect="sqlite"))
    event.listen(model.__table__, "after_create", DDL(
        "CREATE OR REPLACE FUNCTION predicts_deny_history_mutation() RETURNS trigger "
        "LANGUAGE plpgsql AS $$ BEGIN RAISE EXCEPTION 'Predicts records are append-only'; END; $$"
    ).execute_if(dialect="postgresql"))
    event.listen(model.__table__, "after_create", DDL(
        f"CREATE TRIGGER {name}_immutable BEFORE UPDATE OR DELETE ON {name} "
        "FOR EACH ROW EXECUTE FUNCTION predicts_deny_history_mutation()"
    ).execute_if(dialect="postgresql"))

for operation in ("UPDATE", "DELETE"):
    event.listen(PredictsGame.__table__, "after_create", DDL(
        f"CREATE TRIGGER predicts_locked_game_{operation.lower()} BEFORE {operation} ON predicts_game_snapshots "
        "WHEN OLD.locked_at IS NOT NULL BEGIN SELECT RAISE(ABORT, 'Predicts game is locked'); END"
    ).execute_if(dialect="sqlite"))
event.listen(PredictsGame.__table__, "after_create", DDL(
    "CREATE OR REPLACE FUNCTION predicts_guard_locked_game() RETURNS trigger LANGUAGE plpgsql AS $$ "
    "BEGIN IF OLD.locked_at IS NOT NULL THEN RAISE EXCEPTION 'Predicts game is locked'; END IF; "
    "IF TG_OP = 'DELETE' THEN RETURN OLD; END IF; RETURN NEW; END; $$"
).execute_if(dialect="postgresql"))
event.listen(PredictsGame.__table__, "after_create", DDL(
    "CREATE TRIGGER predicts_locked_game BEFORE UPDATE OR DELETE ON predicts_game_snapshots "
    "FOR EACH ROW EXECUTE FUNCTION predicts_guard_locked_game()"
).execute_if(dialect="postgresql"))
