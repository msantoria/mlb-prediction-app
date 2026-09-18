"""Restore genuine archived pregame projections, preserving their original cutoff.

No simulation runs for a past date. Mutable current tables never supply historical
features. Post-start archives and missing source days are reported, not invented.
"""
from collections import Counter
from datetime import datetime, timedelta
import json
from sqlalchemy import select
from .database import SharedReportArtifact
from .model_tracker import ModelTrackerSnapshot
from .final_game_snapshots import FinalGameSnapshot
from .predicts_models import PredictsGame, PredictsPlayer
from .predicts_sources import collect
from .predicts_snapshots import promote, lock_due, grade
from .predicts_residuals import adjust, TARGETS
from .predicts_status import save_status
from .predicts_validation import utc, MODEL_VERSION


def _candidates(session, day):
    # All workspace versions: the current public GET intentionally hides older
    # versions, but their stored pregame baselines remain legitimate evidence.
    for artifact in session.scalars(select(SharedReportArtifact).where(
            SharedReportArtifact.artifact_type == "model_projection_date",
            SharedReportArtifact.target_date == day)):
        payload = artifact.payload_json
        if not isinstance(payload, dict):
            continue
        captured = max(utc(artifact.generated_at), utc(artifact.updated_at or artifact.generated_at))
        for game in payload.get("games") or []:
            yield captured, f"shared_report_artifacts:{artifact.id}", {
                **payload, "games": [game], "predicts_source_generated_at": captured.isoformat()+"Z"}
    for row in session.scalars(select(ModelTrackerSnapshot).where(
            ModelTrackerSnapshot.snapshot_date == day,
            ModelTrackerSnapshot.source == "model_projections")):
        try:
            raw = json.loads(row.raw_payload_json or "null")
        except (TypeError, ValueError):
            continue
        if not isinstance(raw, dict) or not isinstance(raw.get("game"), dict):
            continue
        # Tracker upserts can replace the payload. created_at does not prove the
        # currently stored prediction was available at that earlier time.
        captured = max(utc(row.created_at), utc(row.updated_at))
        yield captured, f"model_tracker_snapshots:{row.id}", {
            "date": day.isoformat(), "games": [raw["game"]],
            "predicts_source_generated_at": captured.isoformat()+"Z"}


def backfill_day(session, day, *, now=None, dry_run=False, hydrate_final=None):
    now = now or datetime.utcnow()
    if day >= now.date():
        raise ValueError("Backfill accepts completed dates only; use refresh for today")
    existing = set(session.scalars(select(PredictsGame.game_pk).where(PredictsGame.target_date == day)))
    candidates = sorted(_candidates(session, day), key=lambda item: (item[0], item[1]), reverse=True)
    selected, skipped = {}, []
    for captured, source, payload in candidates:
        game = payload["games"][0]
        pk = game.get("game_pk")
        if pk in existing or pk in selected:
            continue
        rows, rejected = collect(session, payload, day, captured, source_only=True)
        skipped.extend({**reason, "source": source} for reason in rejected)
        if pk in rows:
            selected[pk] = (captured, source, rows[pk])
    counts = Counter()
    if not dry_run:
        for pk, (captured, source, rows) in selected.items():
            for row in rows:
                row.update(imported_at=now.isoformat()+"Z", archive_source=source,
                    predicts_model_version=MODEL_VERSION,
                    predictions={metric: {**adjust(row, metric, None, []), "status": "archived_baseline"}
                                 for metric in TARGETS[row["player_type"]]})
            # The original source timestamp is validated against first pitch by
            # promote. Existing live/locked history is never replaced by replay.
            result = promote(session, rows, captured)
            counts[result] += 1
            if result == "captured":
                counts["players"] += len(rows)
        lock_due(session, now)
        session.commit()  # Per-date checkpoint; a retry cannot duplicate imports.
    ids = existing | set(selected)
    finals = set(session.scalars(select(FinalGameSnapshot.game_pk).where(
        FinalGameSnapshot.game_pk.in_(ids or [-1]))))
    hydration_errors = []
    if hydrate_final and not dry_run:
        for pk in sorted(ids-finals):
            try:
                result = hydrate_final(pk)
                if result.get("status") == "error":
                    hydration_errors.append({"game_pk": pk, "reason": "Final hydration failed"})
            except Exception as exc:
                hydration_errors.append({"game_pk": pk, "reason": type(exc).__name__})
        finals = set(session.scalars(select(FinalGameSnapshot.game_pk).where(
            FinalGameSnapshot.game_pk.in_(ids or [-1]))))
    graded = 0
    if not dry_run:
        for pk in sorted(ids):
            graded += grade(session, now, pk)
        session.commit()
    # Rejected newer copies do not constitute a gap when an earlier valid
    # archive (or an existing Predicts record) covers the same game.
    missing = {str(r.get("game_pk")) for r in skipped if r.get("game_pk") not in ids}
    report = {"date": day.isoformat(), "status": "dry_run" if dry_run else
        "partial" if missing or ids-finals else "complete" if ids else "no_saved_pregame_source",
        "source_candidates": len(candidates), "eligible_games": len(selected),
        "eligible_players": sum(len(r) for _, _, r in selected.values()),
        "already_present_games": len(existing), "imported_games": counts["captured"],
        "imported_players": counts["players"], "graded_now": graded,
        "missing_source_games": len(missing), "missing_final_game_pks": sorted(ids-finals),
        "rejected_reasons": dict(Counter(r["reason"] for r in skipped)),
        "rejected": skipped[:30], "hydration_errors": hydration_errors,
        "provenance": "archived_pregame_projection"}
    if not dry_run:
        save_status(session, "backfill", day, report, now)
        session.commit()
    return report


def backfill_range(session, start, end, *, now=None, dry_run=False, hydrate_final=None):
    now = now or datetime.utcnow()
    if start > end or (end-start).days > 30 or end >= now.date():
        raise ValueError("Backfill range must be ordered, at most 31 days, and end before today")
    days = []
    for n in range((end-start).days+1):
        day = start+timedelta(days=n)
        try:
            report = backfill_day(session, day, now=now, dry_run=dry_run, hydrate_final=hydrate_final)
        except Exception as exc:
            session.rollback()
            report = {"date": day.isoformat(), "status": "source_error", "reason": type(exc).__name__}
            if not dry_run:
                save_status(session, "backfill", day, report, now)
                session.commit()
        days.append(report)
    return {"start": start.isoformat(), "end": end.isoformat(), "dry_run": dry_run, "days": days,
            "imported_players": sum(d.get("imported_players", 0) for d in days),
            "graded_now": sum(d.get("graded_now", 0) for d in days)}
