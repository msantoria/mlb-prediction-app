"""Bounded analytical views over existing canonical sources; no new pitch ingestion."""
from collections import Counter, defaultdict
from datetime import timedelta
import math
import statistics
from sqlalchemy import select, func
from .database import StatcastEvent
from .predicts_probability import empirical
from .predicts_validation import number


def feature(value=None, *, n=0, status=None, source=None, **details):
    return {"value": value, "sample_size": n, "status": status or ("available" if value is not None else "unavailable"),
            "source": source, **details}


def bounded_pitches(session, ids, role, target_date):
    """One window query per role, with both date and per-player bounds."""
    if not ids:
        return {}
    table = StatcastEvent.__table__
    key = table.c.batter_id if role == "batter" else table.c.pitcher_id
    ranked = select(table, func.row_number().over(partition_by=key, order_by=(
        table.c.game_date.desc(), table.c.game_pk.desc(), table.c.at_bat_number.desc(),
        table.c.pitch_number.desc(), table.c.id.desc())).label("rn")).where(
            key.in_(ids), table.c.game_date < target_date,
            table.c.game_date >= target_date-timedelta(days=180)).subquery()
    rows = session.execute(select(ranked).where(ranked.c.rn <= 1500).order_by(ranked.c.rn)).mappings()
    grouped = defaultdict(list)
    for row in rows:
        grouped[row["batter_id" if role == "batter" else "pitcher_id"]].append(dict(row))
    return grouped


def pa_view(pitches):
    """Terminal-event view. Unstored base/score/release data remains null."""
    seen, rows = set(), []
    for pitch in pitches:
        key = (pitch["game_pk"], pitch["at_bat_number"])
        if None in key or not pitch.get("events") or key in seen:
            continue
        seen.add(key)
        rows.append({**pitch, "base_state": None, "score": None,
                     "times_through_order": None, "starter_or_bullpen": None})
    return rows


def process_windows(pitches, role):
    pas = pa_view(pitches)
    windows = {}
    for size in ((25, 50, 100, 250) if role == "batter" else (100, 250, 500)):
        rows = pas[:size] if role == "batter" else pitches[:size]
        values = [number(p.get("estimated_woba_using_speedangle")) for p in rows]
        values = [v for v in values if v is not None]
        windows[str(size)] = feature(statistics.mean(values) if values else None, n=len(values),
            source="statcast_events", opportunities=len(rows), requested=size,
            unit="PA" if role == "batter" else "pitches", metric="batted_ball_xwoba",
            complete=len(rows) == size)
    values = [number(p.get("estimated_woba_using_speedangle")) for p in pas]
    recent = [v for v in values[:25] if v is not None]
    prior = [v for v in values[25:125] if v is not None]
    trend = feature(source="statcast_events", method="disjoint_window_standard_error")
    if len(recent) >= 10 and len(prior) >= 30:
        se = math.sqrt(statistics.variance(recent)/len(recent) + statistics.variance(prior)/len(prior))
        difference = statistics.mean(recent)-statistics.mean(prior)
        reliability = len(recent)/(len(recent)+50)
        trend = feature(difference/se if se else None, n=len(recent), source="statcast_events",
                        recent=statistics.mean(recent), baseline=statistics.mean(prior),
                        baseline_sample_size=len(prior), difference=difference,
                        reliability=reliability, method="disjoint_window_standard_error",
                        change_point_score=None)
    else:
        trend["status"] = "insufficient_sample"
    return windows, trend


def expected_arsenal(pitches, matchup_rows, batter_hand):
    eligible = [p for p in pitches if p.get("stand") == batter_hand and p.get("pitch_type")]
    if not eligible:
        return feature(source="statcast_events+batter_pitch_type_matchups", reason="No handedness-conditioned pitcher sample")
    # Latest 250 pitches blended into the 1500-pitch window; recent evidence is shrunk.
    long = Counter(p["pitch_type"] for p in eligible)
    recent = Counter(p["pitch_type"] for p in eligible[:250])
    weight = sum(recent.values())/(sum(recent.values())+250)
    distribution = {kind: weight*recent[kind]/sum(recent.values())+(1-weight)*n/len(eligible) for kind,n in long.items()}
    usable = {r.pitch_type: r for r in matchup_rows if number(r.xwoba) is not None and (r.batted_ball_count or 0) > 0}
    total = sum(r.batted_ball_count for r in usable.values())
    prior = sum(r.xwoba*r.batted_ball_count for r in usable.values())/total if total else None
    if prior is None:
        return feature(source="batter_pitch_type_matchups", expected_distribution=distribution)
    coverage = sum(distribution[k] for k in distribution if k in usable)
    if coverage < .8:
        return feature(n=total, status="insufficient_sample", source="batter_pitch_type_matchups", coverage=coverage,
                       expected_distribution=distribution)
    raw = shrunk = 0
    for kind, probability in distribution.items():
        row = usable.get(kind)
        n = row.batted_ball_count if row else 0
        value = row.xwoba if row else prior
        raw += probability*value
        shrunk += probability*(n*value+50*prior)/(n+50)
    return feature(shrunk, n=total, source="statcast_events+batter_pitch_type_matchups", raw=raw,
                   reliability=total/(total+50), coverage=coverage, expected_distribution=distribution,
                   pitcher_sample_size=len(eligible), conditioning_hand=batter_hand, prior=prior)


def zone(pitch):
    x, z = number(pitch.get("plate_x")), number(pitch.get("plate_z"))
    if x is None or z is None:
        return None
    horizontal = "left" if x < -.28 else "right" if x > .28 else "middle"
    vertical = "low" if z < 2.1 else "high" if z > 2.9 else "middle"
    if abs(x) > .83 or z < 1.5 or z > 3.5:
        return "chase"
    return f"{horizontal}_{vertical}"


def location_compatibility(hitter_pitches, pitcher_pitches, hand):
    counts = Counter((p.get("pitch_type"),zone(p)) for p in pitcher_pitches
                     if zone(p) is not None and p.get("pitch_type") and p.get("stand") == hand)
    damage = defaultdict(list)
    for p in pa_view(hitter_pitches):
        value = number(p.get("estimated_woba_using_speedangle"))
        if value is not None and zone(p) is not None:
            damage[(p.get("pitch_type"),zone(p))].append(value)
    total = sum(counts.values())
    observations = [v for values in damage.values() for v in values]
    if not total or not observations:
        return feature(source="statcast_events")
    prior = statistics.mean(observations)
    details = []
    for key, count in counts.items():
        values = damage.get(key, [])
        shrunk = (sum(values)+30*prior)/(len(values)+30)
        details.append({"pitch_type": key[0], "zone": key[1], "pitcher_probability": count/total,
                        "hitter_xwoba": statistics.mean(values) if values else None,
                        "shrunk_xwoba": shrunk, "sample_size": len(values)})
    coverage = sum(d["pitcher_probability"] for d in details if d["sample_size"] > 0)
    value = sum(d["pitcher_probability"]*d["shrunk_xwoba"] for d in details) if coverage >= .5 else None
    return feature(value, n=len(observations), source="statcast_events", zones=details, coverage=coverage,
                   reliability=len(observations)/(len(observations)+100),
                   zone_definition="fixed_plate_coordinates_v1; individual strike-zone height unavailable")


def workload(starts):
    starts = starts[:5]
    pitches = [number(r.get("pitches")) for r in starts]
    pitches = [v for v in pitches if v is not None and 0 <= v <= 160]
    faced = [number(r.get("batters_faced")) for r in starts]
    faced = [v for v in faced if v is not None and 0 <= v <= 50]
    if not pitches:
        return feature(source="final_game_snapshots")
    return feature(statistics.mean(pitches), n=len(pitches), source="final_game_snapshots",
                   expected_batters_faced=statistics.mean(faced) if faced else None,
                   pitch_distribution=empirical(pitches),
                   probability_third_time_through_order=sum(v>=19 for v in faced)/len(faced) if faced else None,
                   previous_start_pitches=pitches[0], max_recent_pitches=max(pitches),
                   last_3_starts=empirical(pitches[:3]), method="last_five_official_starts_empirical")


def exposure(pa, starter_bf, team_pa):
    if any(number(v) is None for v in (pa, starter_bf, team_pa)) or team_pa <= 0:
        return feature(source="model_projections")
    share = min(1, max(0, starter_bf/team_pa))
    return feature(pa*share, source="model_projections", expected_pa_vs_starter=pa*share,
                   expected_pa_vs_bullpen=pa*(1-share), starter_share=share, bullpen_share=1-share,
                   method="team_opportunity_share", pa_vs_rhp=None, pa_vs_lhp=None)


def environment(profile):
    weather = profile.get("weather") or {}
    run = profile.get("run_environment") or {}
    temperature = number(weather.get("temperature_f"))
    pressure = number(weather.get("pressure_hpa"))
    humidity = number(weather.get("humidity_pct"))
    density = None
    if temperature is not None and pressure is not None and humidity is not None and 0 <= humidity <= 100:
        celsius = (temperature-32)*5/9
        if -60 < celsius < 60 and 800 < pressure < 1100:
            vapour = humidity/100 * 6.1078*10**(7.5*celsius/(237.3+celsius))*100
            density = (pressure*100-vapour)/(287.05*(celsius+273.15))+vapour/(461.495*(celsius+273.15))
    return feature(number(run.get("run_scoring_index")), source="model_projection_environment",
                   weather=weather, air_density_kg_m3=density, hr_index=number(run.get("hr_boost_index")),
                   park=profile.get("park"), carry_factor=None, directional_park_factors=None)


def opponent_adjusted(pitches, role, players, captured):
    """Re-express recent batted-ball xwOBA relative to the observed canonical population.

    Opponent strength is what was available at capture, not a claim about what
    was known before each historical PA. The whole calculation is frozen pregame.
    """
    opponent_role = "pitcher" if role == "batter" else "hitter"
    pool = {pid:p for pid,p in players.items() if p.player_type in ({"pitcher"} if opponent_role=="pitcher" else {"hitter","batter"})
            and number(p.xwoba) is not None and (p.plate_appearances or 0)>=30
            and captured-p.updated_at<=timedelta(hours=36)}
    if not pool:
        return feature(source="dashboard_player_current+statcast_events", status="insufficient_sample")
    n = sum(p.plate_appearances for p in pool.values())
    reference = sum(p.xwoba*p.plate_appearances for p in pool.values())/n
    raw,quality = [],[]
    for pa in pa_view(pitches)[:50]:
        opponent=pool.get(pa.get("pitcher_id" if role=="batter" else "batter_id"))
        value=number(pa.get("estimated_woba_using_speedangle"))
        if opponent is not None and value is not None:
            raw.append(value); quality.append(opponent.xwoba)
    if len(raw)<10:
        return feature(n=len(raw),source="dashboard_player_current+statcast_events",status="insufficient_sample")
    reliability=len(raw)/(len(raw)+50)
    adjustment=reliability*(reference-statistics.mean(quality))
    return feature(statistics.mean(raw)+adjustment,n=len(raw),source="dashboard_player_current+statcast_events",
                   raw_recent=statistics.mean(raw),opponent_quality=statistics.mean(quality),
                   reference_population=reference,reference_sample_size=n,reliability=reliability,
                   method="current_asof_opponent_xwoba_adjustment")
