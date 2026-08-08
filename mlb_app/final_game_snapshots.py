"""Durable, immutable snapshots for completed MLB games.

The Live surface stays short-lived and feed-backed. Once MLB marks a game
final, this module materializes the complete public box score into a durable
record that the Final page can read without reconstructing yesterday's game
from live caches.
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Any, Dict, Iterable, List, Optional

from sqlalchemy import Column, Date, DateTime, Index, Integer, JSON, String
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from .database import Base


FINAL_SNAPSHOT_VERSION = 1
FINAL_STATUS_CODES = {"F", "O"}
FINAL_STATUS_LABELS = {"final", "game over", "completed early"}


class FinalGameSnapshot(Base):
    """One immutable, versioned final-game payload per MLB gamePk."""

    __tablename__ = "final_game_snapshots"

    id: int = Column(Integer, primary_key=True, autoincrement=True)
    game_pk: int = Column(Integer, nullable=False, unique=True, index=True)
    official_date: date = Column(Date, nullable=False, index=True)
    status_detail: str = Column(String(80), nullable=False, default="Final")
    away_team_id: Optional[int] = Column(Integer, nullable=True, index=True)
    away_team_name: Optional[str] = Column(String(120), nullable=True)
    away_score: Optional[int] = Column(Integer, nullable=True)
    home_team_id: Optional[int] = Column(Integer, nullable=True, index=True)
    home_team_name: Optional[str] = Column(String(120), nullable=True)
    home_score: Optional[int] = Column(Integer, nullable=True)
    payload_json = Column(JSON, nullable=False)
    snapshot_version: int = Column(Integer, nullable=False, default=FINAL_SNAPSHOT_VERSION)
    source: str = Column(String(64), nullable=False, default="mlb_live_feed")
    finalized_at: datetime = Column(DateTime, nullable=False, default=datetime.utcnow)
    created_at: datetime = Column(DateTime, nullable=False, default=datetime.utcnow)

    __table_args__ = (
        Index("ix_final_game_snapshots_date_game", "official_date", "game_pk"),
    )


def _pick(*values: Any) -> Any:
    return next((value for value in values if value is not None and value != ""), None)


def _safe_int(value: Any) -> Optional[int]:
    try:
        return int(value) if value is not None else None
    except (TypeError, ValueError):
        return None


def _person(person: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    if not person:
        return None
    player_id = _safe_int(person.get("id"))
    if player_id is None:
        return None
    return {
        "id": player_id,
        "name": person.get("fullName") or person.get("name") or "Unknown",
    }


def is_final_status(status: Optional[Dict[str, Any]]) -> bool:
    status = status or {}
    abstract = str(status.get("abstractGameState") or "").strip().lower()
    detailed = str(status.get("detailedState") or "").strip().lower()
    coded = str(status.get("codedGameState") or status.get("statusCode") or "").upper()
    return abstract == "final" or detailed in FINAL_STATUS_LABELS or coded in FINAL_STATUS_CODES


def is_final_feed(feed: Optional[Dict[str, Any]]) -> bool:
    return bool(feed) and is_final_status((feed.get("gameData") or {}).get("status"))


def _batting_line(player: Dict[str, Any]) -> Dict[str, Any]:
    stats = (player.get("stats") or {}).get("batting") or {}
    season = (player.get("seasonStats") or {}).get("batting") or {}
    game_status = player.get("gameStatus") or {}
    raw_order = _safe_int(player.get("battingOrder"))
    order_slot = raw_order // 100 if raw_order else None
    substitution_order = raw_order % 100 if raw_order else 0
    is_substitute = bool(game_status.get("isSubstitute")) or substitution_order > 0
    position = player.get("position") or {}

    return {
        "id": _safe_int((player.get("person") or {}).get("id")),
        "name": (player.get("person") or {}).get("fullName") or "Unknown",
        "position": position.get("abbreviation") or position.get("code"),
        "batting_order": raw_order,
        "batting_order_slot": order_slot,
        "substitution_order": substitution_order,
        "is_substitute": is_substitute,
        "entry_label": "PH" if is_substitute and position.get("abbreviation") == "PH" else (
            "PR" if is_substitute and position.get("abbreviation") == "PR" else (
                "SUB" if is_substitute else None
            )
        ),
        "ab": _pick(stats.get("atBats"), stats.get("ab")),
        "at_bats": _pick(stats.get("atBats"), stats.get("ab")),
        "r": stats.get("runs"),
        "runs": stats.get("runs"),
        "h": stats.get("hits"),
        "hits": stats.get("hits"),
        "rbi": stats.get("rbi"),
        "bb": _pick(stats.get("baseOnBalls"), stats.get("walks")),
        "walks": _pick(stats.get("baseOnBalls"), stats.get("walks")),
        "k": _pick(stats.get("strikeOuts"), stats.get("strikeouts")),
        "strikeouts": _pick(stats.get("strikeOuts"), stats.get("strikeouts")),
        "hr": _pick(stats.get("homeRuns"), stats.get("hr")),
        "home_runs": _pick(stats.get("homeRuns"), stats.get("hr")),
        "doubles": stats.get("doubles"),
        "triples": stats.get("triples"),
        "stolen_bases": stats.get("stolenBases"),
        "caught_stealing": stats.get("caughtStealing"),
        "hit_by_pitch": stats.get("hitByPitch"),
        "left_on_base": stats.get("leftOnBase"),
        "avg": _pick(season.get("avg"), stats.get("avg")),
        "season_avg": _pick(season.get("avg"), stats.get("avg")),
        "obp": _pick(season.get("obp"), stats.get("obp")),
        "slg": _pick(season.get("slg"), stats.get("slg")),
        "ops": _pick(season.get("ops"), stats.get("ops")),
        "season_ops": _pick(season.get("ops"), stats.get("ops")),
    }


def _pitching_line(player: Dict[str, Any]) -> Dict[str, Any]:
    stats = (player.get("stats") or {}).get("pitching") or {}
    season = (player.get("seasonStats") or {}).get("pitching") or {}
    return {
        "id": _safe_int((player.get("person") or {}).get("id")),
        "name": (player.get("person") or {}).get("fullName") or "Unknown",
        "ip": _pick(stats.get("inningsPitched"), stats.get("ip")),
        "innings_pitched": _pick(stats.get("inningsPitched"), stats.get("ip")),
        "h": stats.get("hits"),
        "hits": stats.get("hits"),
        "r": stats.get("runs"),
        "runs": stats.get("runs"),
        "er": _pick(stats.get("earnedRuns"), stats.get("er")),
        "earned_runs": _pick(stats.get("earnedRuns"), stats.get("er")),
        "bb": _pick(stats.get("baseOnBalls"), stats.get("walks")),
        "walks": _pick(stats.get("baseOnBalls"), stats.get("walks")),
        "k": _pick(stats.get("strikeOuts"), stats.get("strikeouts")),
        "strikeouts": _pick(stats.get("strikeOuts"), stats.get("strikeouts")),
        "hr": _pick(stats.get("homeRuns"), stats.get("hr")),
        "home_runs": _pick(stats.get("homeRuns"), stats.get("hr")),
        "pitches": _pick(stats.get("numberOfPitches"), stats.get("pitchCount"), stats.get("pitchesThrown")),
        "pitch_count": _pick(stats.get("numberOfPitches"), stats.get("pitchCount"), stats.get("pitchesThrown")),
        "strikes": stats.get("strikes"),
        "strikes_thrown": stats.get("strikes"),
        "balls": stats.get("balls"),
        "batters_faced": stats.get("battersFaced"),
        "ground_outs": stats.get("groundOuts"),
        "air_outs": stats.get("airOuts"),
        "hit_batters": stats.get("hitBatsmen"),
        "wild_pitches": stats.get("wildPitches"),
        "inherited_runners": stats.get("inheritedRunners"),
        "inherited_runners_scored": stats.get("inheritedRunnersScored"),
        "era": _pick(season.get("era"), stats.get("era")),
        "season_era": _pick(season.get("era"), stats.get("era")),
        "note": player.get("stats") and (player.get("gameStatus") or {}).get("status"),
    }


def _ordered_players(team_box: Dict[str, Any], kind: str) -> List[Dict[str, Any]]:
    players = team_box.get("players") or {}
    if kind == "batting":
        explicit_ids = [str(value) for value in (team_box.get("batters") or [])]
        explicit_ids.extend(str(value) for value in (team_box.get("battingOrder") or []))
        explicit = set(explicit_ids)
        rows = [
            _batting_line(player)
            for player in players.values()
            if str((player.get("person") or {}).get("id")) in explicit
            or bool(((player.get("stats") or {}).get("batting") or {}))
        ]
        rows = [row for row in rows if row.get("id") is not None]
        rows.sort(key=lambda row: (
            row.get("batting_order_slot") or 99,
            row.get("substitution_order") or 0,
            row.get("name") or "",
        ))
        return rows

    pitcher_ids = [str(value) for value in (team_box.get("pitchers") or [])]
    explicit = set(pitcher_ids)
    appearance_order = {player_id: index for index, player_id in enumerate(pitcher_ids)}
    rows = [
        _pitching_line(player)
        for player in players.values()
        if str((player.get("person") or {}).get("id")) in explicit
        or bool(((player.get("stats") or {}).get("pitching") or {}))
    ]
    rows = [row for row in rows if row.get("id") is not None]
    rows.sort(key=lambda row: (appearance_order.get(str(row.get("id")), 999), row.get("name") or ""))
    return rows


def _team_boxscore(feed: Dict[str, Any], side: str) -> Dict[str, Any]:
    game_data = feed.get("gameData") or {}
    team = ((game_data.get("teams") or {}).get(side) or {})
    team_box = (((feed.get("liveData") or {}).get("boxscore") or {}).get("teams") or {}).get(side) or {}
    return {
        "team_id": _safe_int(team.get("id")),
        "name": team.get("name"),
        "abbreviation": team.get("abbreviation") or team.get("teamCode") or team.get("fileCode"),
        "batters": _ordered_players(team_box, "batting"),
        "pitchers": _ordered_players(team_box, "pitching"),
    }


def _linescore(feed: Dict[str, Any]) -> Dict[str, Any]:
    live_data = feed.get("liveData") or {}
    game_data = feed.get("gameData") or {}
    raw = live_data.get("linescore") or {}
    teams = game_data.get("teams") or {}
    innings = []
    for inning in raw.get("innings") or []:
        innings.append({
            "num": inning.get("num"),
            "ordinal_num": inning.get("ordinalNum"),
            "away_runs": (inning.get("away") or {}).get("runs"),
            "away_hits": (inning.get("away") or {}).get("hits"),
            "away_errors": (inning.get("away") or {}).get("errors"),
            "home_runs": (inning.get("home") or {}).get("runs"),
            "home_hits": (inning.get("home") or {}).get("hits"),
            "home_errors": (inning.get("home") or {}).get("errors"),
        })

    decisions = live_data.get("decisions") or {}
    return {
        "away_team": (teams.get("away") or {}).get("name"),
        "home_team": (teams.get("home") or {}).get("name"),
        "innings": innings,
        "totals": {
            "away": {
                "runs": ((raw.get("teams") or {}).get("away") or {}).get("runs"),
                "hits": ((raw.get("teams") or {}).get("away") or {}).get("hits"),
                "errors": ((raw.get("teams") or {}).get("away") or {}).get("errors"),
                "left_on_base": ((raw.get("teams") or {}).get("away") or {}).get("leftOnBase"),
            },
            "home": {
                "runs": ((raw.get("teams") or {}).get("home") or {}).get("runs"),
                "hits": ((raw.get("teams") or {}).get("home") or {}).get("hits"),
                "errors": ((raw.get("teams") or {}).get("home") or {}).get("errors"),
                "left_on_base": ((raw.get("teams") or {}).get("home") or {}).get("leftOnBase"),
            },
        },
        "decisions": {
            "winner": _person(decisions.get("winner")),
            "loser": _person(decisions.get("loser")),
            "save": _person(decisions.get("save")),
        },
    }


def _scoring_plays(feed: Dict[str, Any]) -> List[Dict[str, Any]]:
    plays = (((feed.get("liveData") or {}).get("plays") or {}).get("allPlays") or [])
    output = []
    for play in plays:
        about = play.get("about") or {}
        if not about.get("isScoringPlay"):
            continue
        result = play.get("result") or {}
        output.append({
            "inning": about.get("inning"),
            "half_inning": about.get("halfInning"),
            "event": result.get("event"),
            "description": result.get("description"),
            "away_score": result.get("awayScore"),
            "home_score": result.get("homeScore"),
        })
    return output


def _top_hitter(boxscore: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    hitters: Iterable[Dict[str, Any]] = (
        (boxscore.get("away") or {}).get("batters") or []
    ) + ((boxscore.get("home") or {}).get("batters") or [])
    hitters = [hitter for hitter in hitters if (hitter.get("ab") or 0) or (hitter.get("walks") or 0)]
    return max(
        hitters,
        key=lambda hitter: (
            (hitter.get("rbi") or 0) * 4
            + (hitter.get("home_runs") or 0) * 3
            + (hitter.get("hits") or 0) * 2
            + (hitter.get("runs") or 0)
        ),
        default=None,
    )


def _natural_summary(payload: Dict[str, Any]) -> str:
    away = payload["away"]
    home = payload["home"]
    winner = away if (away.get("score") or 0) > (home.get("score") or 0) else home
    loser = home if winner is away else away
    sentences = [
        f"The {winner.get('name')} defeated the {loser.get('name')} "
        f"{winner.get('score')}–{loser.get('score')}."
    ]
    decisions = (payload.get("linescore") or {}).get("decisions") or {}
    winning_pitcher = (decisions.get("winner") or {}).get("name")
    losing_pitcher = (decisions.get("loser") or {}).get("name")
    save_pitcher = (decisions.get("save") or {}).get("name")
    if winning_pitcher and losing_pitcher:
        decision = f"{winning_pitcher} earned the win; {losing_pitcher} took the loss"
        if save_pitcher:
            decision += f", and {save_pitcher} recorded the save"
        sentences.append(decision + ".")
    hitter = _top_hitter(payload.get("boxscore") or {})
    if hitter:
        sentences.append(
            f"{hitter.get('name')} led the offense with {hitter.get('hits') or 0} hit(s), "
            f"{hitter.get('home_runs') or 0} home run(s), and {hitter.get('rbi') or 0} RBI."
        )
    return " ".join(sentences)


def build_game_boxscore_payload(feed: Dict[str, Any]) -> Dict[str, Any]:
    """Return the richer Away/Home box-score contract for live or final feeds."""

    game_pk = _safe_int(((feed.get("gameData") or {}).get("game") or {}).get("pk"))
    return {
        "game_pk": game_pk,
        "away": _team_boxscore(feed, "away"),
        "home": _team_boxscore(feed, "home"),
        "source": "mlb_live_feed",
    }


def build_final_game_payload(feed: Dict[str, Any]) -> Dict[str, Any]:
    """Normalize a final MLB feed into the durable public Final contract."""

    if not is_final_feed(feed):
        raise ValueError("MLB feed is not final")

    game_data = feed.get("gameData") or {}
    live_data = feed.get("liveData") or {}
    game = game_data.get("game") or {}
    datetime_data = game_data.get("datetime") or {}
    status = game_data.get("status") or {}
    venue = game_data.get("venue") or {}
    weather = game_data.get("weather") or {}
    linescore = _linescore(feed)
    boxscore = build_game_boxscore_payload(feed)
    away_box = boxscore["away"]
    home_box = boxscore["home"]
    away_total = (linescore.get("totals") or {}).get("away") or {}
    home_total = (linescore.get("totals") or {}).get("home") or {}

    payload = {
        "snapshot_version": FINAL_SNAPSHOT_VERSION,
        "game_pk": _safe_int(game.get("pk")),
        "official_date": datetime_data.get("officialDate"),
        "game_datetime": datetime_data.get("dateTime"),
        "status": "Final",
        "status_detail": status.get("detailedState") or "Final",
        "venue": venue.get("name"),
        "weather": {
            "condition": weather.get("condition"),
            "temp_f": weather.get("temp"),
            "wind": weather.get("wind"),
        } if weather else None,
        "away": {
            "team_id": away_box.get("team_id"),
            "name": away_box.get("name"),
            "abbreviation": away_box.get("abbreviation"),
            "score": away_total.get("runs"),
        },
        "home": {
            "team_id": home_box.get("team_id"),
            "name": home_box.get("name"),
            "abbreviation": home_box.get("abbreviation"),
            "score": home_total.get("runs"),
        },
        "linescore": linescore,
        "boxscore": boxscore,
        "scoring_plays": _scoring_plays(feed),
        "play_count": len(((live_data.get("plays") or {}).get("allPlays") or [])),
        "abs_tracker": {
            "available": False,
            "source": "mlb_live_feed",
            "events": [],
            "summary": None,
            "reason_unavailable": "ABS challenge events are not currently available from the public live feed.",
        },
        "source": "mlb_live_feed",
        "snapshotted_at": datetime.utcnow().isoformat() + "Z",
    }
    payload["summary"] = _natural_summary(payload)
    return payload


def serialize_snapshot(snapshot: FinalGameSnapshot, *, include_payload: bool = True) -> Dict[str, Any]:
    if include_payload:
        return dict(snapshot.payload_json or {})
    payload = snapshot.payload_json or {}
    return {
        "game_pk": snapshot.game_pk,
        "official_date": snapshot.official_date.isoformat(),
        "status": "Final",
        "status_detail": snapshot.status_detail,
        "away": payload.get("away") or {
            "team_id": snapshot.away_team_id,
            "name": snapshot.away_team_name,
            "score": snapshot.away_score,
        },
        "home": payload.get("home") or {
            "team_id": snapshot.home_team_id,
            "name": snapshot.home_team_name,
            "score": snapshot.home_score,
        },
        "venue": payload.get("venue"),
        "summary": payload.get("summary"),
        "decisions": (payload.get("linescore") or {}).get("decisions"),
        "snapshot_version": snapshot.snapshot_version,
        "finalized_at": snapshot.finalized_at.isoformat() + "Z",
    }


def persist_final_snapshot(session: Session, feed: Dict[str, Any]) -> FinalGameSnapshot:
    """Persist once; a final gamePk remains immutable after its first valid snapshot."""

    payload = build_final_game_payload(feed)
    game_pk = payload.get("game_pk")
    if game_pk is None:
        raise ValueError("Final feed is missing gamePk")
    existing = session.query(FinalGameSnapshot).filter(FinalGameSnapshot.game_pk == game_pk).one_or_none()
    if existing is not None:
        return existing

    official_date = payload.get("official_date")
    if not official_date:
        raise ValueError("Final feed is missing officialDate")
    away = payload.get("away") or {}
    home = payload.get("home") or {}
    snapshot = FinalGameSnapshot(
        game_pk=game_pk,
        official_date=date.fromisoformat(official_date),
        status_detail=payload.get("status_detail") or "Final",
        away_team_id=away.get("team_id"),
        away_team_name=away.get("name"),
        away_score=away.get("score"),
        home_team_id=home.get("team_id"),
        home_team_name=home.get("name"),
        home_score=home.get("score"),
        payload_json=payload,
        snapshot_version=FINAL_SNAPSHOT_VERSION,
        source="mlb_live_feed",
    )
    session.add(snapshot)
    try:
        session.commit()
    except IntegrityError:
        session.rollback()
        existing = session.query(FinalGameSnapshot).filter(FinalGameSnapshot.game_pk == game_pk).one_or_none()
        if existing is not None:
            return existing
        raise
    session.refresh(snapshot)
    return snapshot


def get_final_snapshot(session: Session, game_pk: int) -> Optional[FinalGameSnapshot]:
    return session.query(FinalGameSnapshot).filter(FinalGameSnapshot.game_pk == game_pk).one_or_none()


def list_final_snapshots(session: Session, official_date: date) -> List[FinalGameSnapshot]:
    return (
        session.query(FinalGameSnapshot)
        .filter(FinalGameSnapshot.official_date == official_date)
        .order_by(FinalGameSnapshot.game_pk.asc())
        .all()
    )
