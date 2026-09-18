"""Evaluate frozen pregame predictions. Never refit on the evaluated outcomes."""
from collections import defaultdict
from copy import deepcopy
from datetime import timedelta
import math
import statistics
from sqlalchemy import select
from .predicts_models import PredictsPlayer, PredictsOutcome, PredictsGame
from .predicts_residuals import vector
from .predicts_validation import FEATURE_VERSION
from .predicts_probability import wilson


def history_query(start, end):
    return select(PredictsPlayer, PredictsOutcome, PredictsGame).join(PredictsOutcome,
        PredictsOutcome.snapshot_id==PredictsPlayer.id).join(PredictsGame,
        (PredictsGame.game_pk==PredictsPlayer.game_pk)&(PredictsGame.revision==PredictsPlayer.revision)).where(
        PredictsGame.target_date>=start, PredictsGame.target_date<=end)


def training_records(session, target_date, captured):
    query = history_query(target_date-timedelta(days=365), target_date-timedelta(days=1)).where(
        PredictsOutcome.graded_at<captured, PredictsPlayer.as_of<captured,
        PredictsPlayer.feature_version==FEATURE_VERSION).order_by(PredictsOutcome.graded_at.desc(), PredictsPlayer.id.desc()).limit(50000)
    groups = defaultdict(list)
    for snapshot,outcome,game in session.execute(query):
        row = snapshot.payload
        if row.get("provenance") not in {"true_point_in_time_snapshot", "archived_pregame_projection"} or not row.get("baseline_model_version"):
            continue
        for metric, result in outcome.payload["metrics"].items():
            if result.get("residual") is not None:
                groups[(row["player_type"],metric,row["baseline_model_version"])].append({
                    "snapshot_id": snapshot.id, "date": game.target_date.isoformat(),
                    "residual": result["residual"], "x": vector(row, metric)})
    return groups


def evaluate(session, start, end, *, player_type=None, metric=None, model_version=None,
             lineup_position=None, min_expected_pa=None, min_arsenal=None):
    query = history_query(start,end)
    if player_type:
        query = query.where(PredictsPlayer.player_type==player_type)
    groups = defaultdict(list)
    decisions = defaultdict(list)
    driver_results = defaultdict(list)
    result_rows = list(session.execute(query))
    payloads = [deepcopy(snapshot.payload) for snapshot, _outcome, _game in result_rows]
    for (snapshot,outcome,_game), row in zip(result_rows, payloads):
        if model_version and row.get("baseline_model_version") != model_version:
            continue
        if lineup_position and row.get("batting_order") != lineup_position:
            continue
        if any(threshold is not None and (row["features"].get(key,{}).get("value") is None or row["features"][key]["value"] < threshold)
               for key,threshold in (("opportunity",min_expected_pa),("arsenal",min_arsenal))):
            continue
        for name,result in outcome.payload["metrics"].items():
            if (metric and name != metric) or result.get("residual") is None:
                continue
            prediction = row.get("predictions", {}).get(name, {})
            groups[(row["player_type"],name,row.get("baseline_model_version"))].append((result,prediction))
            board = (row.get("decision_board") or {}).get(name) or {}
            category = board.get("category")
            if category:
                decisions[(row["player_type"], name, category, board.get("method_version", "legacy_v1"))].append((result, board))
                if category == "confirmed_lineup_shortlist":
                    for driver in board.get("drivers") or []:
                        if driver.get("z_score", 0) >= .25:
                            driver_results[(row["player_type"], name, driver.get("driver"))].append(result)
    summaries = []
    for (role,name,version),pairs in sorted(groups.items(), key=lambda item: str(item[0])):
        errors = [r["residual"] for r,p in pairs]
        adjusted = [r["adjusted_error"] for r,p in pairs if r.get("adjusted_error") is not None]
        probabilities = [(p["probability_over_baseline"],int(r["residual"]>0)) for r,p in pairs if p.get("probability_over_baseline") is not None]
        n,over = len(errors),sum(e>0 for e in errors)
        calibration = []
        for i in range(10):
            bucket = [(p,y) for p,y in probabilities if min(9,int(p*10))==i]
            if bucket:
                calibration.append({"low": i/10, "high": (i+1)/10, "n": len(bucket),
                    "predicted": statistics.mean(p for p,y in bucket), "observed": statistics.mean(y for p,y in bucket)})
        # Compare like-for-like populations when adjusted predictions are available.
        paired_baseline = [r["residual"] for r,p in pairs if r.get("adjusted_error") is not None]
        summaries.append({"player_type":role,"metric":name,"model_version":version,"n":n,
            "mae":statistics.mean(abs(e) for e in errors), "rmse":math.sqrt(statistics.mean(e*e for e in errors)),
            "bias_actual_minus_baseline":statistics.mean(errors),"median_residual":statistics.median(errors),
            "over_rate":over/n,"under_rate":sum(e<0 for e in errors)/n,"equal_rate":sum(e==0 for e in errors)/n,
            "interval_95_over_rate":wilson(over,n),"adjusted_n":len(adjusted),
            "paired_baseline_mae":statistics.mean(abs(e) for e in paired_baseline) if adjusted else None,
            "adjusted_mae":statistics.mean(abs(e) for e in adjusted) if adjusted else None,
            "adjusted_rmse":math.sqrt(statistics.mean(e*e for e in adjusted)) if adjusted else None,
            "probability_n":len(probabilities), "brier":statistics.mean((p-y)**2 for p,y in probabilities) if probabilities else None,
            "log_loss":statistics.mean(-y*math.log(max(1e-9,p))-(1-y)*math.log(max(1e-9,1-p)) for p,y in probabilities) if probabilities else None,
            "calibration":calibration})
    decision_summaries = []
    for (role, name, category, method_version), pairs in sorted(decisions.items(), key=lambda item: str(item[0])):
        resolved = [result for result, _board in pairs if result.get("residual") is not None]
        wins = sum(result["residual"] > 0 for result in resolved)
        decision_summaries.append({"player_type": role, "metric": name, "category": category,
            "method_version": method_version,
            "n": len(resolved), "wins": wins, "win_rate": wins / len(resolved) if resolved else None,
            "above": wins, "below": sum(r["residual"] < 0 for r in resolved),
            "equal": sum(r["residual"] == 0 for r in resolved),
            "average_actual_minus_baseline": statistics.mean(result["residual"] for result in resolved) if resolved else None})
    drivers = []
    for (role, name, driver), results in sorted(driver_results.items(), key=lambda item: str(item[0])):
        resolved = [result for result in results if result.get("residual") is not None]
        wins = sum(result["residual"] > 0 for result in resolved)
        drivers.append({"player_type": role, "metric": name, "driver": driver, "n": len(resolved),
            "wins": wins, "win_rate": wins / len(resolved) if resolved else None,
            "average_actual_minus_baseline": statistics.mean(result["residual"] for result in resolved) if resolved else None})
    return {"start":start.isoformat(),"end":end.isoformat(),"groups":summaries,
            "decision_performance": decision_summaries, "winning_drivers": drivers,
            "evaluation":"frozen_pregame_predictions",
            "record_definition":"Above/below/equal to Model Projections; not a sportsbook win/loss record. Only stored decision categories are evaluated.", "empty":not bool(summaries)}
